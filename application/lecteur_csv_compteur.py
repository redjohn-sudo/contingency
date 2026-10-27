"""Import d'un export compteur CSV sans retouche de ses lignes dans un tableur.

Les conventions sont déclarées, aucun format commercial n'est deviné. Les
colonnes de plusieurs compteurs ou canaux se sélectionnent par filtres exacts.
Sortie : fins ISO avec fuseau, kW moyens, provenance et qualité conservées.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path

LIMITE_OCTETS = 20 * 1024 * 1024
LIMITE_LIGNES = 200_000


def modele():
    """Aucun nom de colonne n'est attribué à un fournisseur sans export vérifié."""
    return {'meetbedrijf': '', 'colonne_temps': '', 'colonne_date': '', 'colonne_valeur': '',
            'format_temps': '', 'separateur': '', 'decimal': '', 'milliers': '',
            'fuseau': '', 'horodatage_marque': '', 'kanaal': 'afname',
            'unite': '', 'nature_valeurs': 'intervalle', 'pas_minutes': 15,
            'lignes_avant_entete': 0, 'filtres': {}, 'colonne_statut': '', 'statuts': {},
            'colonne_compteur': '', 'compteur_unique': False}


def decoder(donnees: bytes, encodage: str = 'utf-8-sig') -> str:
    if len(donnees) > LIMITE_OCTETS:
        raise ValueError('Export supérieur à 20 Mio.')
    if encodage not in ('utf-8-sig', 'utf-8', 'utf-16', 'cp1252'):
        raise ValueError('Encodage non pris en charge : UTF-8, UTF-16 ou cp1252 explicite.')
    try:
        return donnees.decode(encodage)
    except (UnicodeError, LookupError) as erreur:
        raise ValueError('Texte illisible dans cet encodage. Déclarer celui du fichier, sans remplacer les caractères.') from erreur


def _tableau(texte: str, configuration: dict):
    if not isinstance(texte, str) or len(texte.encode('utf-8')) > LIMITE_OCTETS:
        raise ValueError('Export attendu en texte, au maximum 20 Mio.')
    separateur = configuration.get('separateur')
    if separateur not in (',', ';', '\t'):
        raise ValueError('Déclarer le séparateur : virgule, point-virgule ou tabulation.')
    saut = configuration.get('lignes_avant_entete', 0)
    if isinstance(saut, bool) or not isinstance(saut, int) or not 0 <= saut <= 50:
        raise ValueError('Le nombre de lignes avant en-tête doit être un entier de 0 à 50.')
    flux = io.StringIO(texte.lstrip('\ufeff'))
    for _ in range(saut):
        if not flux.readline():
            raise ValueError('En-tête absent après les lignes ignorées.')
    lecteur = csv.DictReader(flux, delimiter=separateur, strict=True)
    try:
        entetes = lecteur.fieldnames or []
        if not entetes or any(not e.strip() for e in entetes) or len(entetes) != len(set(entetes)):
            raise ValueError('En-têtes vides ou dupliqués : import refusé.')
        lignes = []
        for ligne in lecteur:
            if len(lignes) >= LIMITE_LIGNES:
                raise ValueError('Plus de 200 000 lignes dans cet export.')
            if None in ligne or any(v is None for v in ligne.values()):
                raise ValueError(f'Nombre de colonnes incohérent à la ligne {lecteur.line_num + saut}.')
            lignes.append((lecteur.line_num + saut, ligne))
    except csv.Error as erreur:
        raise ValueError(f'CSV mal formé : {erreur}') from erreur
    return entetes, lignes


def apercu(texte: str, separateur: str, lignes_avant_entete: int = 0):
    entetes, lignes = _tableau(texte, {'separateur': separateur, 'lignes_avant_entete': lignes_avant_entete})
    return {'colonnes': entetes, 'nombre_lignes': len(lignes),
            'exemples': [{'ligne': numero, 'valeurs': ligne} for numero, ligne in lignes[:5]]}


def convertir_csv(texte: str, configuration: dict) -> dict:
    if not isinstance(configuration, dict):
        raise ValueError('La configuration doit être un objet.')
    configuration = copy.deepcopy(configuration)
    for champ in ('meetbedrijf', 'format_temps', 'decimal', 'milliers', 'fuseau', 'horodatage_marque', 'kanaal'):
        if not isinstance(configuration.get(champ), str) or not configuration[champ].strip():
            raise ValueError(f'Convention obligatoire : {champ}.')
    unite = configuration.get('unite')
    if unite not in ('kw', 'kwh_par_quart'):
        raise ValueError('Unité obligatoire : kw ou kwh_par_quart. Les index cumulés ne sont pas des consommations par intervalle.')
    if configuration.get('nature_valeurs') != 'intervalle' or configuration.get('pas_minutes') != 15:
        # Texte décidé par le coordinateur (bus #909) : il couvre aussi les échantillons instantanés (ESIF)
        # et ne promet aucune agrégation, qui ne se fait pas ici.
        raise ValueError('Déclarer des valeurs par intervalle de 15 minutes : puissance moyenne en kW ou énergie en kWh '
                         'par quart, selon l’unité déclarée. Les échantillons instantanés, les autres pas de mesure, '
                         'les index cumulés et les totaux mensuels nécessitent une préparation adaptée et documentée '
                         'avant cet import. Aucune agrégation n’est effectuée ici.')
    entetes, lignes = _tableau(texte, configuration)
    colonne_compteur = configuration.get('colonne_compteur', '')
    if colonne_compteur:
        if not isinstance(colonne_compteur, str) or colonne_compteur not in entetes:
            raise ValueError('Colonne compteur absente du fichier.')
    elif configuration.get('compteur_unique') is not True:
        raise ValueError('Déclarer la colonne compteur, ou confirmer que le fichier concerne un seul compteur.')
    requis = ('colonne_temps', 'colonne_valeur')
    optionnels = ('colonne_date', 'colonne_statut')
    for cle in (*requis, *optionnels):
        colonne = configuration.get(cle, '')
        if not isinstance(colonne, str) or (cle in requis or colonne) and colonne not in entetes:
            raise ValueError(f'Colonne absente ou invalide : {cle}.')
    selection = [configuration[c] for c in requis] + [configuration[c] for c in optionnels if configuration.get(c)]
    if len(selection) != len(set(selection)):
        raise ValueError('Les colonnes de date, heure, valeur et statut doivent être distinctes.')
    filtres = configuration.get('filtres', {})
    if not isinstance(filtres, dict) or any(c not in entetes or not isinstance(v, str) or not v
                                          for c, v in filtres.items()):
        raise ValueError('Filtres attendus : nom de colonne existante et valeur textuelle exacte.')
    colonne_statut = configuration.get('colonne_statut')
    statuts = configuration.get('statuts', {})
    if colonne_statut and (not isinstance(statuts, dict) or not statuts
                          or any(not isinstance(c, str) or v not in ('mesure', 'valide', 'estime', 'invalide')
                                 for c, v in statuts.items())):
        raise ValueError('Déclarer la signification de chaque statut : mesure (origine mesurée documentée par la source), '
                         'valide (validé, origine non documentée), estime ou invalide.')
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie)
    ecrivain.writerow(['instant', 'valeur'])
    conservees, compte_statuts, qualites, compteurs = [], {}, [], set()
    for numero, ligne in lignes:
        if any(ligne[c] != valeur for c, valeur in filtres.items()):
            continue
        if colonne_compteur:
            compteur = ligne[colonne_compteur].strip()
            if not compteur:
                raise ValueError(f'Identifiant compteur absent à la ligne {numero}.')
            compteurs.add(compteur)
            if len(compteurs) > 1:
                raise ValueError('Plusieurs compteurs sélectionnés : ajouter un filtre exact sur leur identifiant.')
        qualite = 'inconnue'
        brut_statut = ligne[colonne_statut].strip() if colonne_statut else ''
        if colonne_statut:
            qualite = statuts.get(brut_statut)
            if qualite not in ('mesure', 'valide', 'estime'):
                raise ValueError(f'Statut inconnu ou invalide à la ligne {numero} : {brut_statut!r}.')
            compte_statuts[brut_statut] = compte_statuts.get(brut_statut, 0) + 1
        temps = ligne[configuration['colonne_temps']].strip()
        if configuration.get('colonne_date'):
            temps = ligne[configuration['colonne_date']].strip() + ' ' + temps
        ecrivain.writerow([temps, ligne[configuration['colonne_valeur']]])
        conservees.append(numero)
        qualites.append({'ligne_source': numero, 'statut_source': brut_statut, 'qualite': qualite})
    if not conservees:
        raise ValueError('Aucune mesure après sélection du compteur et du canal.')
    # Même lecteur strict que le diagnostic : pas de trou, doublon, heure locale
    # ambiguë ou chiffre dont la virgule / les milliers seraient devinés.
    from horodatages import controle_import
    from serveur import lire_export
    lecture = configuration | {'separateur': ',', 'colonne_temps': 'instant', 'colonne_valeur': 'valeur'}
    journal = []
    valeurs, dates = lire_export(sortie.getvalue(), lecture, journal=journal, lignes_source=conservees,
                                 empreinte_source=hashlib.sha256(texte.encode('utf-8')).hexdigest(),
                                 conventions_source=configuration)
    facteur = 4 if unite == 'kwh_par_quart' else 1
    puissances = [v * facteur for v in valeurs]
    if any(not math.isfinite(v) or v > 1e7 for v in puissances):
        raise ValueError('Puissance convertie hors limites, au maximum 10 millions de kW.')
    normalise = io.StringIO()
    ecrivain = csv.writer(normalise, lineterminator='\n')
    ecrivain.writerow(['fin_intervalle', 'puissance_kw'])
    ecrivain.writerows(zip(dates, puissances))
    avertissements = []
    if not colonne_statut:
        avertissements.append('Qualité des mesures inconnue : aucune colonne de statut déclarée.')
    if any(q['qualite'] == 'valide' for q in qualites):
        # Revue d'Astra de d5ec7f4 (P1-H) : une validation ne dit pas l'origine ; une valeur validée peut être reconstruite.
        avertissements.append('Statut « valide » sans origine documentée : la mesure directe n’est pas établie.')
    if any(q['qualite'] == 'estime' for q in qualites):
        avertissements.append('Des mesures estimées sont présentes ; elles ne constituent pas toutes des mesures observées.')
    avertissements.append('Unité déclarée : à recouper avec la facture du même intervalle avant conclusion de puissance.')
    return {'csv': normalise.getvalue(), 'valeurs_kw': puissances, 'horodatages': dates,
            'unite': 'kw', 'qualites': qualites, 'avertissements': avertissements, 'journal': journal,
            'controle': controle_import(puissances, dates, unite),
            'provenance': {'format': 'csv_declare', 'configuration': configuration,
                           'empreinte_texte_source': hashlib.sha256(texte.encode('utf-8')).hexdigest(),
                           # Ce que le dossier client vérifie avant de reprendre ces qualités (AF06, 30/09).
                           'empreinte_profil_csv': hashlib.sha256(normalise.getvalue().encode('utf-8')).hexdigest(),
                           'facteur_vers_kw': facteur, 'lignes_source': len(lignes),
                           'compteurs': sorted(compteurs), 'compteur_unique_declare': not bool(colonne_compteur),
                           'lignes_importees': len(conservees), 'lignes_ecartees': len(lignes) - len(conservees),
                           'statuts_source': compte_statuts}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('modele')
    vue = actions.add_parser('apercu')
    vue.add_argument('fichier', type=Path)
    vue.add_argument('--separateur', required=True, choices=[',', ';', '\t'])
    vue.add_argument('--lignes-avant-entete', type=int, default=0)
    conversion = actions.add_parser('convertir')
    conversion.add_argument('fichier', type=Path)
    conversion.add_argument('--configuration', type=Path, required=True)
    conversion.add_argument('--sortie', type=Path, required=True)
    for commande in (vue, conversion):
        commande.add_argument('--encodage', choices=['utf-8-sig', 'utf-8', 'utf-16', 'cp1252'], default='utf-8-sig')
    args = parser.parse_args()
    try:
        if args.action == 'modele':
            resultat = modele()
        else:
            donnees = args.fichier.read_bytes()
            texte = decoder(donnees, args.encodage)
            if args.action == 'apercu':
                resultat = apercu(texte, args.separateur, args.lignes_avant_entete)
            else:
                configuration = json.loads(args.configuration.read_text(encoding='utf-8-sig'))
                lu = convertir_csv(texte, configuration)
                # Pas d'écrasement silencieux du fichier d'origine ni d'un audit antérieur.
                if args.sortie.exists():
                    raise ValueError('Le répertoire de sortie existe déjà. Choisir un nouveau répertoire.')
                args.sortie.mkdir(parents=True)
                (args.sortie / 'profil.csv').write_bytes(lu['csv'].encode('utf-8'))  # octets de empreinte_profil_csv
                lu['provenance'].update(empreinte_fichier_source=hashlib.sha256(donnees).hexdigest(),
                                        encodage=args.encodage)
                audit = {k: v for k, v in lu.items() if k not in ('csv', 'valeurs_kw', 'horodatages')}
                (args.sortie / 'import.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
                resultat = {'sortie': str(args.sortie), 'mesures': len(lu['valeurs_kw']),
                            'avertissements': lu['avertissements']}
    except (OSError, ValueError) as erreur:
        parser.exit(2, f'Import refusé : {erreur}\n')
    print(json.dumps(resultat, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
