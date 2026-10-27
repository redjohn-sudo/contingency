"""Banc facultatif sur VEA 2016, sans réseau ni téléchargement implicite.

Les horaires sont reconstruits pour tester le code. Ni leur convention
source ni aucun contrat néerlandais ne sont confirmés par ce banc.
Exécution explicite : python verifier_contrats_corpus.py --archive vea.zip
    --sortie resultat.json. Ce corpus n'est pas ajouté aux tests unitaires.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import time
import zipfile
from zoneinfo import ZoneInfo

from optimisation_contrat import analyser_annee, comparer_contrats, VERSION
from rapport_contrats import rendre_comparaison

SOURCE = 'https://zenodo.org/records/13734730'
ATTRIBUTION = 'Paul Hendrik Tiemann et VEA, profils industriels allemands 2016, CC BY 4.0'


def hypothese(valeur):
    return {'valeur': valeur, 'statut': 'hypothese',
            'source': 'FICTIF : donnée du banc de vérification, aucun contrat client.',
            'verifie_par': '', 'date_verification': None}


def configuration(empreinte, pointe):
    gtv = math.ceil(pointe * 1.1) + 1
    tarif = {'gestionnaire': 'enexis', 'categorie': 'MS-fictif', 'annee': 2026,
             'categorie_code': 'e', 'assiette_pointes': 'mensuelle_non_ponderee',
             'contrat_eur_kw_an': 20, 'pointe_eur_kw_mois': 2,
             'energie_eur_kwh': .1, 'fixe_transport_eur_an': 120, 'autres_reseau_eur_an': 240}
    options = []
    for produit, capacite in [('fixe', pointe), ('cbc', gtv)]:
        offre = {'gestionnaire': 'enexis', 'tension_kv': 10, 'categorie': 'MS-fictif',
                 'produit': produit, 'gtv_fixe_kw': capacite, 'gtv_variable_kw': 0,
                 'admissibilite_confirmee': True, 'conditions_verifiees': True,
                 'regles_actuelles_verifiees': True, 'baisse_gtv_acceptee': True,
                 'date_effet': '2026-10-01'}
        option = {'id': produit, 'libelle': 'Option FICTIVE ' + produit, 'produit': produit,
                  'gtv_fixe_kw': hypothese(capacite), 'categorie': hypothese('MS-fictif'),
                  'offre': hypothese(offre), 'tarif': hypothese(dict(tarif)),
                  'couts_complementaires_eur_an': hypothese(0), 'couts_exhaustifs': hypothese(True)}
        if produit == 'cbc':
            option['programme'] = hypothese({'mode': 'recurrent', 'plages': [{
                'debut_heure': 18, 'fin_heure': 20, 'jours': list(range(7)),
                'mois': list(range(1, 13)), 'plafond_kw': pointe * .8}]})
            option['remuneration'] = hypothese({'mode': 'jour_actif', 'euros_par_jour': 50,
                'regle_defaut': 'jour_entier', 'annexe1_verifiee': True})
        options.append(option)
    return {'provenance': hypothese({'nature': 'mesure_individuelle', 'canal': 'afname',
                'site_unique': True, 'qualites_controlees': False, 'fuseau_confirme': False,
                'sha256_profil': empreinte}),
            'site': hypothese({'gestionnaire': 'enexis', 'reseau': 'distribution',
                'tension_kv': 10, 'grande_connexion': True,
                'puissance_raccordement_kw': gtv * 2, 'congestion': True}),
            'contrat_actuel': hypothese({'produit': 'fixe', 'gtv_kw': gtv, 'categorie': 'MS-fictif'}),
            'tarif_actuel': hypothese(tarif), 'couts_actuels_eur_an': hypothese(0),
            'couts_actuels_exhaustifs': hypothese(True),
            'date_comparaison': '2026-10-01', 'annee_tarifaire': 2026, 'options': options}


def proche(obtenu, attendu):
    if not math.isclose(obtenu, attendu, rel_tol=1e-11, abs_tol=1e-6):
        raise AssertionError(f'Écart numérique : {obtenu} contre {attendu}.')


def verifier_site(valeurs, fins, debuts):
    resume, _, _ = analyser_annee(valeurs, fins)
    pointe = max(valeurs)
    c = configuration(resume['sha256'], pointe)
    r = comparer_contrats(valeurs, fins, c)
    assert r['dominante'] is None, 'Aucun gagnant ne peut être annoncé sur ces contrats fictifs.'
    assert len(r['options']) == 3
    maxima = [max(p for p, instant in zip(valeurs, debuts) if instant.month == mois)
              for mois in range(1, 13)]
    energie = math.fsum(p / 4 for p in valeurs)
    base = c['contrat_actuel']['valeur']['gtv_kw'] * 20 + sum(maxima) * 2 + energie * .1 + 360
    fixe = pointe * 20 + sum(maxima) * 2 + energie * .1 + 360
    jours_perdus = sorted({instant.date().isoformat() for p, instant in zip(valeurs, debuts)
                          if 18 <= instant.hour < 20 and p - pointe * .8 > 1e-9})
    # Année bissextile, une activation quotidienne dans ce contrat FICTIF.
    versement = (366 - len(jours_perdus)) * 50
    proche(r['profil']['energie_kwh'], energie)
    proche(r['options'][0]['cout_annuel_reference_eur'], base)
    proche(r['options'][1]['cout_annuel_reference_eur'], fixe)
    proche(r['options'][1]['ecart_reference_eur'], base - fixe)
    proche(r['options'][2]['cout_annuel_reference_eur'], base - versement)
    assert r['options'][2]['remuneration_cbc']['jours_perdus'] == jours_perdus
    assert r['options'][2]['remuneration_cbc']['jours_actifs'] == 366
    for mois, maximum in enumerate(maxima, 1):
        proche(r['profil']['mensuel'][str(mois)]['pointe_kw'], maximum)
    assert r['options'][2]['statut'] == ('incompatible' if jours_perdus else 'incomplet')
    avant = json.dumps(r, allow_nan=False, sort_keys=True)
    for langue in ('fr', 'nl'):
        rendu = rendre_comparaison(r, langue)
        assert f'lang="{langue}"' in rendu
        assert 'FICTIF' in rendu
    assert avant == json.dumps(r, allow_nan=False, sort_keys=True)
    return {'profil_sha256': resume['sha256'], 'pointe_kw': pointe,
            'energie_kwh': energie, 'jours_cbc_en_defaut': len(jours_perdus),
            'rapports_verifies': ['fr', 'nl'], 'dominante': None}


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--archive', type=Path, required=True)
    arguments.add_argument('--sortie', type=Path, required=True)
    arguments.add_argument('--pas-selection', type=int, default=18)
    args = arguments.parse_args()
    if args.pas_selection < 1:
        arguments.error('Le pas de sélection doit être positif.')
    zone = ZoneInfo('Europe/Amsterdam')
    depart = datetime(2016, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    debuts = [(depart + timedelta(minutes=15 * i)).astimezone(zone) for i in range(35136)]
    fins = [(depart + timedelta(minutes=15 * (i + 1))).isoformat() for i in range(35136)]
    debut = time.perf_counter()
    bilan = {'version': VERSION, 'source': SOURCE, 'attribution': ATTRIBUTION,
             'nature': 'Vérification numérique, aucun résultat commercial.',
             'horaires': 'Reconstruction continue Europe/Amsterdam pour le test ; convention source non confirmée.',
             'contrats_et_prix': 'Tous fictifs et marqués hypothèse ; aucune correspondance à un contrat réel.',
             'selection': f'Une ligne sur {args.pas_selection}, à partir de la première, sans sélection par résultat.',
             'lignes_lues': 0, 'sites': [], 'refus_entrees': [], 'echecs': []}
    dossier_code = Path(__file__).resolve().parent
    bilan['fichiers_calcul_sha256'] = {
        nom: hashlib.sha256((dossier_code / nom).read_bytes()).hexdigest()
        for nom in ('optimisation_contrat.py', 'regles_contrats_nl.py',
                    'pointes_ponderees.py', 'horodatages.py', 'rapport_contrats.py',
                    'messages_contrats_nl.py', 'verifier_contrats_corpus.py')}
    with args.archive.open('rb') as fichier:
        bilan['archive_sha256'] = hashlib.file_digest(fichier, 'sha256').hexdigest()
    with zipfile.ZipFile(args.archive) as archive, archive.open('load_profiles_tabsep.csv') as fichier:
        lignes = csv.reader(io.TextIOWrapper(fichier, encoding='utf-8'), delimiter='\t')
        entete = next(lignes)
        # L'archive publiée porte un séparateur final sur l'en-tête seulement.
        if entete and entete[-1] == '':
            entete = entete[:-1]
        assert entete == ['id'] + [f'time{i}' for i in range(35136)], 'En-tête VEA 2016 inattendu.'
        for numero, ligne in enumerate(lignes):
            bilan['lignes_lues'] += 1
            if numero % args.pas_selection:
                continue
            identifiant = ligne[0]
            try:
                valeurs = [float(p) for p in ligne[1:]]
                assert len(valeurs) == 35136
                if any(not math.isfinite(p) or not 0 <= p <= 1e7 for p in valeurs):
                    try:
                        analyser_annee(valeurs, fins)
                    except ValueError:
                        bilan['refus_entrees'].append(identifiant)
                        continue
                    raise AssertionError('Valeur hors périmètre acceptée.')
                bilan['sites'].append({'id': identifiant, **verifier_site(valeurs, fins, debuts)})
            except (ValueError, AssertionError, KeyError, TypeError, OverflowError) as erreur:
                bilan['echecs'].append({'id': identifiant, 'erreur': str(erreur)})
            if numero % (args.pas_selection * 25) == 0:
                print(f"{len(bilan['sites'])} sites vérifiés, {len(bilan['echecs'])} échecs", flush=True)
    bilan['secondes'] = time.perf_counter() - debut
    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    args.sortie.write_text(json.dumps(bilan, ensure_ascii=False, allow_nan=False, indent=2))
    print(json.dumps({'sites_verifies': len(bilan['sites']), 'refus_entrees': len(bilan['refus_entrees']),
                      'echecs': len(bilan['echecs']), 'secondes': bilan['secondes']}, ensure_ascii=False))
    return int(bool(bilan['echecs']) or not bilan['sites'])


if __name__ == '__main__':
    raise SystemExit(main())
