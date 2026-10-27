# -*- coding: utf-8 -*-
"""Atelier local : documents, validation explicite, simulation et rapport."""
import copy
import base64
import csv
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, HTMLResponse
from starlette.concurrency import run_in_threadpool

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE.parent / 'optimisation'))
from moteur import capacite_rapide, VERSION
from documents import completer, conserver_sources, lire_pdf, PYTHON as PYTHON_DOCUMENTS
from coherence import controler
from extraction_nebius import extraire as extraire_avec_nebius
from extraction_nebius import VERSION as VERSION_EXTRACTION
from extraction_nebius import empreinte_extraction
from controle_documentaire import auditer_documents, verifier_revue, controler_valeur
from rapport_html import rendre_rapport
from modele_dossier import nouveau_dossier, normaliser, CHAMPS_METIER_OPTIONNELS
from catalogue import (resume as resume_catalogue,
                       selectionner as selectionner_contraintes,
                       personnalisees as personnaliser_contraintes)
from routage_agents import planifier as planifier_agents
from sensibilite_dossier import analyser, lignes_rapport
from horodatages import ErreurDonnees, lire_fins_quarts, refuser_si_irregulier

app = FastAPI()
DOSSIERS = RACINE / '.local'
LIMITE_DOCUMENT = 5 * 1024 * 1024
CHAMPS = {
 'plafond_kw': ('Plafond réseau', 'kW'),
 'puissance_max_kw': ('Puissance maximale batterie', 'kW'),
 'rendement': ('Rendement par sens', 'ratio'),
 'puissance_kw': ('Puissance de la machine ajoutée', 'kW'),
 'duree_heures': ('Durée consécutive par bloc de 24 h', 'h'),
 'ouverture_heure': ('Début autorisé dans le bloc', 'h'),
 'echeance_heure': ('Fin obligatoire dans le bloc', 'h'),
}

def empreinte(objet):
    return hashlib.sha256(json.dumps(objet, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def sauver(dossier):
    _sauver_dans(dossier, DOSSIERS)


def _sauver_dans(dossier, stockage):
    stockage = Path(stockage)
    stockage.mkdir(exist_ok=True)
    cible = stockage / (dossier['id'] + '.json')
    temporaire = cible.with_suffix('.tmp')
    temporaire.write_text(json.dumps(dossier, ensure_ascii=False, allow_nan=False))
    temporaire.replace(cible)

def charger(identifiant):
    if not re.fullmatch('[a-f0-9]{32}', identifiant):
        raise ValueError('Identifiant invalide')
    fichier = DOSSIERS / (identifiant + '.json')
    if not fichier.exists():
        raise ValueError('Dossier introuvable')
    return json.loads(fichier.read_text())

VALEURS_NEGATIVES = ("Valeurs négatives dans le profil : import refusé. Elles peuvent venir d'un export qui mêle "
                     "consommation (afname) et injection (teruglevering), d'une convention de signe inversée ou d'une "
                     "anomalie de mesure. Vérifier le canal exporté et sa convention de signe avant de réimporter.")

def _lire_profil_detaille(texte, jours_civils=False):
    """jours_civils : le diagnostic lit des mois civils, dont les jours de changement d'heure
    comptent 92 ou 100 quarts (vu en rejouant une courbe au format Kenter, 25/09). COH-PERIODE
    contrôle ensuite la couverture ; l'application web garde ses blocs de 96."""
    if not isinstance(texte, str):
        raise ValueError('CSV attendu sous forme de texte.')
    try:
        lecteur = csv.DictReader(io.StringIO(texte.lstrip('\ufeff')), strict=True)
        entetes = lecteur.fieldnames or []
        if len(entetes) != 2 or set(entetes) != {'fin_intervalle', 'puissance_kw'}:
            raise ValueError('CSV attendu : fin_intervalle,puissance_kw, deux colonnes uniques (puissance moyenne en kW).')
        lignes, numeros = [], []
        for ligne in lecteur:
            numero = lecteur.line_num  # ligne physique (fin de l'enregistrement s'il en occupe plusieurs)
            if None in ligne or any(v is None or not v.strip() for v in ligne.values()):
                raise ValueError(f'Colonne vide, absente ou en trop dans le CSV, ligne {numero}.')
            lignes.append(ligne)
            numeros.append(numero)
            if len(lignes) > 35140:
                raise ValueError('Profil trop long : au maximum 366 jours de quarts d’heure.')
    except csv.Error as erreur:
        raise ValueError(f'CSV mal formé : {erreur}') from erreur
    if jours_civils:
        if not 92 <= len(lignes) <= 35140:
            raise ValueError('Profil attendu : au moins un jour et au plus 366 jours de quarts d’heure.')
    elif not 96 <= len(lignes) <= 35136 or len(lignes) % 96:
        raise ValueError('Profil attendu : blocs complets de 96 mesures, au maximum 366 blocs.')
    dates = lire_fins_quarts((l['fin_intervalle'] for l in lignes), lignes=numeros)
    try:
        valeurs = [float(l['puissance_kw']) for l in lignes]
    except ValueError as erreur:
        raise ValueError('Puissance illisible : le CSV canonique attend un nombre avec point décimal, en kW.') from erreur
    # Des quarts négatifs ont été vus sur de vraies courbes industrielles (VEA, six profils refusés, vérification
    # du 27/09) sans que leur cause soit établie (docs/contraintes/VERIFICATION-CONTRATS-CORPUS-20260927.md).
    # Causes plausibles : canal mêlé, convention de signe, anomalie de mesure. On refuse sans affirmer laquelle.
    if any(math.isfinite(v) and v < 0 for v in valeurs):
        raise ValueError(VALEURS_NEGATIVES)
    if any(not math.isfinite(v) or v > 1e7 for v in valeurs):
        raise ValueError('Puissance du profil invalide (0 à 10 millions de kW).')
    return valeurs, [date.isoformat() for date in dates]


# Version du comportement de lire_export : une confirmation donnée à une version antérieure ne vaut pas pour celle-ci.
LECTEUR_EXPORT_VERSION = '2026-09-30'


def _identite_interpretation(empreinte, conventions):
    """Ce que confirme l'utilisateur : ce fichier, lu avec ces conventions, par cette version du lecteur (revue
    d'Astra de 1842576, P1-C). Changer début ou fin d'intervalle, l'unité, la colonne ou le compteur change
    l'identité, donc la confirmation. La confirmation elle-même est exclue, pour ne pas dépendre d'elle-même."""
    canonique = json.dumps({'fichier': empreinte, 'lecteur': LECTEUR_EXPORT_VERSION,
                            'conventions': {k: v for k, v in conventions.items() if k != 'heure_repetee_confirmee'}},
                           sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonique.encode('utf-8')).hexdigest()


def _decalage(instant):
    brut = instant.strftime('%z')
    return f'{brut[:3]}:{brut[3:]}'


def _heures_repetees(horaires, ambigus, zone, configuration, empreinte, identite, journal, nombres_bruts=None):
    """Heure répétée d'octobre en heure locale sans décalage (AF03, OF2 ; conditions d'Astra du 30/09).

    Proposée seulement si les lignes ambiguës forment, dans l'ordre du fichier, deux fois la même heure complète et
    régulière : la première lue en heure d'été, la seconde en heure d'hiver. Acceptée seulement si la configuration
    confirme l'identité de cette interprétation (fichier, conventions, version du lecteur) ; sinon refus qui montre
    lignes, décalages, empreinte du fichier et identité à confirmer. Un ordre mêlé (classement
    par heure affichée, comme l'open data Fluvius) ou une ligne manquante bloquent, même confirmés. Rien n'est supprimé
    ni fabriqué : chaque ligne garde sa mesure, seul son instant UTC est fixé. ``paires`` (hors paramètres du catalogue) :
    chaque heure répétée avec ses deux lignes, valeurs telles qu'écrites et instants proposés, pour voir avant de
    confirmer que ce sont deux mesures (relecture de Fable, FB5). Aucune paire pour un ordre mêlé.
    """
    blocs = []
    for element in ambigus:
        if blocs and element[0] == blocs[-1][-1][0] + 1:
            blocs[-1].append(element)
        else:
            blocs.append([element])
    constats, lisibles = [], []
    for bloc in blocs:
        reperes, lignes = [x[1] for x in bloc], [x[2] for x in bloc]
        moitie = len(bloc) // 2
        jour = reperes[0].date().isoformat()
        suite = lambda seq: all(b - a == timedelta(minutes=15) for a, b in zip(seq, seq[1:]))  # noqa: E731
        if len(bloc) % 2 or reperes[:moitie] != reperes[moitie:] or not suite(reperes[:moitie]):
            constats.append({'code': 'HEURE_REPETEE_ORDRE_AMBIGU', 'gravite': 'bloquant', 'lignes': lignes,
                             'parametres': {'jour': jour}})
            continue
        ete, hiver = (_decalage(reperes[0].replace(tzinfo=zone, fold=f)) for f in (0, 1))
        occurrence = lambda k, fold: {'ligne': lignes[k], 'instant': reperes[k].replace(tzinfo=zone, fold=fold).isoformat(),  # noqa: E731
                                      'valeur': nombres_bruts[bloc[k][0]] if nombres_bruts is not None else None}
        constats.append({'code': 'HEURE_REPETEE_A_CONFIRMER', 'gravite': 'bloquant', 'lignes': lignes,
                         'parametres': {'jour': jour, 'decalages': [ete, hiver], 'empreinte': empreinte, 'identite': identite,
                                        'lignes_ete': lignes[:moitie], 'lignes_hiver': lignes[moitie:]},
                         'paires': [{'heure': reperes[k].strftime('%H:%M'), 'ete': occurrence(k, 0),
                                     'hiver': occurrence(moitie + k, 1)} for k in range(moitie)]})
        lisibles.append(bloc)
    ambigus_ordre = [c for c in constats if c['code'] == 'HEURE_REPETEE_ORDRE_AMBIGU']
    if ambigus_ordre:
        c = ambigus_ordre[0]
        raise ErreurDonnees(f"Heure locale ambiguë lignes {c['lignes'][0]} à {c['lignes'][-1]} : heure répétée du "
                            f"{c['parametres']['jour']} (passage à l'heure d'hiver), sans deux heures complètes et ordonnées. "
                            "L'ordre physique des mesures ne peut pas être établi : calcul bloqué. Fournir un export avec "
                            "décalages UTC, ou une convention d'ordre documentée par le meetbedrijf.", constats)
    if configuration.get('heure_repetee_confirmee') != identite:
        c = constats[0]
        p = c['parametres']
        raise ErreurDonnees(f"Heure locale ambiguë lignes {c['lignes'][0]} à {c['lignes'][-1]} : heure répétée du "
                            f"{p['jour']} (passage à l'heure d'hiver), sans décalage. Interprétation proposée d'après l'ordre du "
                            f"fichier : lignes {p['lignes_ete'][0]} à {p['lignes_ete'][-1]} en heure d'été ({p['decalages'][0]}), "
                            f"lignes {p['lignes_hiver'][0]} à {p['lignes_hiver'][-1]} en heure d'hiver ({p['decalages'][1]}). "
                            f"À confirmer avec heure_repetee_confirmee = {identite} (ce fichier, SHA-256 {empreinte}, lu "
                            "avec ces conventions : en changer demande une nouvelle confirmation), ou fournir un export "
                            "avec décalages UTC.", constats)
    for bloc, c in zip(lisibles, constats):
        moitie = len(bloc) // 2
        for k, (i, repere, _) in enumerate(bloc):
            horaires[i] = repere.replace(tzinfo=zone, fold=0 if k < moitie else 1)
        journal.append({**c, 'code': 'HEURE_REPETEE_INTERPRETEE', 'gravite': 'info'})


def lire_export(texte, configuration=None, journal=None, lignes_source=None, empreinte_source=None, conventions_source=None):
    """Lit un CSV après déclaration explicite des colonnes et conventions.

    journal reçoit les interprétations acceptées (heure répétée confirmée). lignes_source et empreinte_source
    rattachent lignes et empreinte au fichier d'origine quand l'appelant a d'abord réécrit ce fichier, et
    conventions_source ses conventions d'origine (colonnes, unité, compteur) pour l'identité à confirmer.

    Aucun format de portail n'est codé comme reconnu : leurs en-têtes et leurs
    conventions d'horodatage ne sont pas publiés. Le seul raccourci accepté est
    le CSV interne explicite fin_intervalle,puissance_kw.
    """
    texte = texte.lstrip('\ufeff')
    if not configuration:
        lignes_entete = next(csv.reader(io.StringIO(texte)), [])
        if lignes_entete == ['fin_intervalle', 'puissance_kw']:
            return _lire_profil_detaille(texte)
        raise ValueError('Export non reconnu. Déclarer les colonnes, séparateur, décimales, fuseau et début/fin avant lecture.')

    requis = {'colonne_temps', 'colonne_valeur', 'format_temps', 'separateur', 'decimal', 'milliers',
              'fuseau', 'horodatage_marque', 'meetbedrijf', 'kanaal'}
    if not isinstance(configuration, dict) or not requis <= configuration.keys():
        raise ValueError('Configuration d’import incomplète : colonnes, séparateur, décimales, fuseau et marqueur début/fin obligatoires.')
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    fuseau = configuration['fuseau']
    marque = configuration['horodatage_marque']
    separateur = configuration['separateur']
    decimal = configuration['decimal']
    milliers = configuration['milliers']
    canal = configuration['kanaal']
    if (marque not in ('debut', 'fin') or separateur not in (',', ';', '\t')
            or decimal not in (',', '.') or milliers not in ('aucun', '.', ',', 'espace')
            or milliers == decimal or canal not in ('afname', 'teruglevering')
            or not str(configuration['meetbedrijf']).strip()):
        raise ValueError('Convention invalide : séparateur ou marqueur début/fin non pris en charge.')
    if canal != 'afname':
        raise ValueError('Ce diagnostic compare la consommation afname à la facture. Le canal teruglevering ne peut pas la remplacer.')
    if not isinstance(configuration['format_temps'], str) or '%Z' in configuration['format_temps']:
        raise ValueError('format_temps : %Z est ambigu ; utiliser %z avec un décalage UTC numérique, ou ISO8601 avec fuseau.')
    try:
        zone = ZoneInfo(fuseau)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as erreur:
        raise ValueError('Fuseau horaire inconnu, fournir un nom IANA explicite (ex. Europe/Amsterdam ou UTC).') from erreur

    lecteur = csv.DictReader(io.StringIO(texte), delimiter=separateur)
    entetes = lecteur.fieldnames or []
    if len(entetes) != len(set(entetes)) or configuration['colonne_temps'] not in entetes or configuration['colonne_valeur'] not in entetes:
        raise ValueError('Colonnes absentes ou dupliquées : vérifier l’aperçu des trois premières lignes.')
    horaires, valeurs, nombres_bruts, numeros, ambigus = [], [], [], [], []
    journal = [] if journal is None else journal
    for rang, ligne in enumerate(lecteur):
        # Ligne physique du fichier lu (P2-B d'Astra), ou du fichier source quand l'appelant l'a réécrit.
        numero = lignes_source[rang] if lignes_source is not None else lecteur.line_num
        if None in ligne or any(valeur is None for valeur in ligne.values()):
            raise ValueError(f'Nombre de colonnes incohérent ligne {numero}.')
        brut_temps = (ligne.get(configuration['colonne_temps']) or '').strip()
        brut_valeur = (ligne.get(configuration['colonne_valeur']) or '').strip()
        try:
            if configuration['format_temps'] == 'ISO8601':
                instant = datetime.fromisoformat(brut_temps.replace('Z', '+00:00'))
            else:
                instant = datetime.strptime(brut_temps, configuration['format_temps'])
        except ValueError as erreur:
            raise ValueError(f'Horodatage illisible ligne {numero}; vérifier le format_temps déclaré.') from erreur
        if instant.tzinfo is None:
            # L'heure locale est admise seulement si elle identifie un instant unique.
            candidats = [instant.replace(tzinfo=zone, fold=i) for i in (0, 1)]
            valides = [c for c in candidats if c.astimezone(ZoneInfo('UTC')).astimezone(zone).replace(tzinfo=None) == instant]
            distincts = {c.utcoffset() for c in valides}
            if not valides:
                raise ValueError(f'Heure locale ambiguë ou inexistante ligne {numero}; fournir son décalage UTC explicite.')
            if len(distincts) != 1:
                ambigus.append((len(horaires), instant, numero))  # heure répétée d'octobre, fixée après lecture complète
            instant = valides[0] if len(distincts) == 1 else instant
        else:
            # Relecture de Fable du 30/09 (corpus Fluvius) : un décalage écrit qui contredit le fuseau déclaré n'est
            # départagé en silence ni pour le marqueur (avant, le « Z » l'emportait), ni pour la déclaration.
            local = instant.astimezone(zone)
            if local.utcoffset() != instant.utcoffset():
                convention = f"{fuseau} (UTC{local.isoformat()[-6:]})"
                raise ErreurDonnees(f"Ligne {numero} : l'horodatage « {brut_temps} » porte un décalage UTC différent de celui "
                                    f"du fuseau déclaré, {convention} à cet instant. Déclarer le fuseau tel qu'il est écrit "
                                    "(UTC pour un « Z ») ou faire corriger l'export : aucun fuseau n'est remplacé en silence.",
                                    [{"code": "FUSEAU_CONTRADICTOIRE", "gravite": "bloquant", "lignes": [numero],
                                      "parametres": {"ligne": numero, "valeur_brute": brut_temps, "convention": convention}}])
            instant = local
        if instant.minute % 15 or instant.second or instant.microsecond:
            raise ValueError(f'Horodatage hors d’un quart d’heure exact ligne {numero}.')
        sep_milliers = {'aucun': None, '.': '.', ',': ',', 'espace': ' ' }[milliers]
        nombre = brut_valeur.strip()
        if sep_milliers:
            groupes = nombre.split(decimal)
            entier = groupes[0]
            motif_groupe = r'[+-]?[1-9]\d{0,2}(?:' + re.escape(sep_milliers) + r'\d{3})+'
            if not (re.fullmatch(r'[+-]?\d+', entier) or re.fullmatch(motif_groupe, entier)) or len(groupes) > 2:
                raise ValueError(f'Séparateur de milliers incohérent ligne {numero}.')
            nombre = entier.replace(sep_milliers, '') + (decimal + groupes[1] if len(groupes) == 2 else '')
        elif ' ' in nombre:
            raise ValueError(f'Séparateur de milliers non déclaré ligne {numero}.')
        if decimal == ',':
            if '.' in nombre or nombre.count(',') > 1:
                raise ValueError(f'Notation numérique ambiguë ligne {numero}.')
            nombre = nombre.replace(',', '.')
        elif ',' in nombre:
            raise ValueError(f'Notation numérique ambiguë ligne {numero}.')
        if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', nombre):
            raise ValueError(f'Notation numérique ambiguë ligne {numero}.')
        try:
            valeur = float(nombre)
        except ValueError as erreur:
            raise ValueError(f'Valeur illisible ligne {numero}.') from erreur
        if not math.isfinite(valeur) or valeur < 0 or valeur > 1e7:
            raise ValueError(f'Valeur hors limites ligne {numero}.')
        horaires.append(instant)
        valeurs.append(valeur)
        nombres_bruts.append(brut_valeur)
        numeros.append(numero)
    if not valeurs or len(valeurs) > 35136:
        raise ValueError('Export vide ou supérieur à 366 jours.')
    if ambigus:
        empreinte = empreinte_source or hashlib.sha256(texte.encode('utf-8')).hexdigest()
        identite = _identite_interpretation(empreinte, conventions_source or configuration)
        _heures_repetees(horaires, ambigus, zone, configuration, empreinte, identite, journal, nombres_bruts)
    if marque == 'debut':
        horaires = [(h.astimezone(ZoneInfo('UTC')) + timedelta(minutes=15)).astimezone(zone) for h in horaires]
    if milliers in ('.', ',') and all(re.fullmatch(r'[+-]?[1-9]\d{0,2}' + re.escape(milliers) + r'\d{3}', n) for n in nombres_bruts):
        raise ValueError('Notation numérique ambiguë : toutes les valeurs ont trois chiffres après un séparateur, sans décimale déclarée visible. Vérifier les conventions du fichier ; fournir une décimale explicite pour de vrais milliers.')
    refuser_si_irregulier([h.astimezone(ZoneInfo('UTC')) for h in horaires], numeros,
                          'Export irrégulier : trou, doublon ou pas différent de 15 minutes. Les changements d’heure doivent inclure le fuseau ou un décalage UTC.')
    return valeurs, [h.isoformat() for h in horaires]


def apercu_export(texte, nombre=3):
    """Aperçu brut, sans interprétation ni sélection automatique de colonnes."""
    try:
        dialecte = csv.Sniffer().sniff(texte[:8192], delimiters=',;\t')
    except csv.Error as erreur:
        raise ValueError('Séparateur non déterminé : le déclarer manuellement.') from erreur
    return list(csv.reader(io.StringIO(texte), dialecte))[:nombre + 1]


def lire_profil(texte):
    """Compatibilité historique : retourne uniquement les puissances."""
    return _lire_profil_detaille(texte)[0]

def creer(documents, profil, nature, metadonnees=None, source_document=None, stockage=None):
    valeurs, horodatages = _lire_profil_detaille(profil)
    faits = {}
    for cle in CHAMPS:
        candidats = []
        for index, doc in enumerate(documents):
            for ligne, texte in enumerate(doc['texte'].splitlines(), 1):
                m = re.fullmatch(r'\s*'+cle+r'\s*=\s*([0-9]+(?:[.,][0-9]+)?)\s*', texte)
                if m:
                    candidats.append({'valeur':float(m[1].replace(',','.')), 'document':index, 'ligne':ligne, 'motif':''})
        faits[cle] = candidats[0] if len(candidats)==1 else {'valeur':None, 'document':-1, 'ligne':0, 'motif':''}
    dossier = nouveau_dossier(
        identifiant=uuid.uuid4().hex,
        documents=documents,
        profil=valeurs,
        profil_sha256=hashlib.sha256(profil.encode()).hexdigest(),
        nature=nature,
        faits=faits,
        profil_horodatages=horodatages,
        metadonnees=metadonnees,
        source_document=source_document,
    )
    dossier['catalogue'] = resume_catalogue()
    if stockage is None:
        sauver(dossier)
    else:
        _sauver_dans(dossier, stockage)
    return public(dossier)

def public(dossier):
    dossier = normaliser(dossier)
    return {k:v for k,v in dossier.items() if k not in {'profil', '_owner'}} | {'nombre_mesures':len(dossier['profil']), 'champs':CHAMPS,
        'profil_apercu': dossier['profil'][:96],
        'audit_documentaire':auditer_documents(dossier['documents'])}

def revision_dossier(dossier):
    contenu={'faits':dossier['faits'],'documents':dossier['documents'],'profil':dossier['profil_sha256'],
             'contraintes':dossier.get('contraintes',[]),'catalogue':dossier.get('catalogue')}
    if dossier.get('revue_documentaire'):
        contenu['revue_documentaire']=dossier['revue_documentaire']
    return empreinte(contenu)

def controler_export(dossier):
    """Une ancienne validation ne couvre pas des alertes découvertes depuis."""
    controle = controler(dossier, revision_dossier(dossier))
    audit = auditer_documents(dossier['documents'])
    try:
        verifier_revue(audit, dossier.get('revue_documentaire', {}))
    except ValueError as erreur:
        controle['statut'] = 'bloque'
        controle['conclusion'] = 'Conclusion suspendue : revue documentaire manquante ou périmée.'
        controle['anomalies'].append(str(erreur))
    controle['audit_documentaire'] = audit
    return controle

def sensibilite_valide(dossier):
    analyse = dossier.get('sensibilite')
    return bool(analyse and analyse.get('revision') == revision_dossier(dossier)
                and analyse.get('resultat_sha256') == empreinte(dossier.get('resultat'))
                and analyse.get('empreinte') == empreinte({k: v for k, v in analyse.items() if k != 'empreinte'}))

def verifier_faits(dossier, faits):
    if set(faits) != set(CHAMPS):
        raise ValueError('Tous les paramètres doivent être renseignés.')
    propres = {}
    for cle, fait in faits.items():
        try:
            if isinstance(fait['valeur'], bool):
                raise ValueError('Valeur booléenne interdite')
            valeur = float(fait['valeur'])
        except (TypeError, KeyError) as e:
            raise ValueError('Valeur numérique manquante : '+cle) from e
        if not math.isfinite(valeur) or valeur < 0 or valeur > 1e7:
            raise ValueError('Valeur invalide : '+cle)
        document, ligne = int(fait['document']), int(fait['ligne'])
        motif = str(fait.get('motif','')).strip()
        if document == -1:
            if len(motif) < 8:
                raise ValueError('Justifier l’hypothèse : '+CHAMPS[cle][0])
            citation = 'Hypothèse : '+motif
        elif 0 <= document < len(dossier['documents']):
            lignes = dossier['documents'][document]['texte'].splitlines()
            if not 1 <= ligne <= len(lignes) or not lignes[ligne-1].strip():
                raise ValueError('Ligne source absente ou vide : '+cle)
            citation = lignes[ligne-1].strip()
            extrait = re.fullmatch(r'\s*'+cle+r'\s*=\s*([0-9]+(?:[.,][0-9]+)?)\s*', citation)
            if extrait and float(extrait[1].replace(',','.')) != valeur and len(motif) < 8:
                raise ValueError('Justifier la correction de la valeur source : '+CHAMPS[cle][0])
            if not extrait:
                etabli, controle = controler_valeur(cle, valeur, dossier['documents'][document], ligne)
                if not etabli and (len(motif) < 30 or motif == 'Proposition Nebius acceptée après vérification humaine.'):
                    raise ValueError('Valeur non établie par sa source : '+cle+'. '+controle+'. Justifiez précisément une hypothèse de simulation (30 caractères minimum).')
        else:
            raise ValueError('Document source inconnu')
        propres[cle] = dict(valeur=valeur,document=document,ligne=ligne,motif=motif,citation=citation)
    v = {k:f['valeur'] for k,f in propres.items()}
    if not 0 < v['rendement'] <= 1:
        raise ValueError('Le rendement par sens doit être compris entre 0 exclu et 1 inclus.')
    for cle in ['duree_heures','ouverture_heure','echeance_heure']:
        if v[cle]*4 != int(v[cle]*4):
            raise ValueError('Horaires attendus par multiples de 15 minutes.')
    if not 0 <= v['ouverture_heure'] < v['echeance_heure'] <= 24 or not 0 < v['duree_heures'] <= v['echeance_heure']-v['ouverture_heure']:
        raise ValueError('La durée ne tient pas dans la fenêtre autorisée.')
    return propres

@app.middleware('http')
async def local_uniquement(request: Request, suite):
    if getattr(app.state, 'public_app', False):
        return await suite(request)  # Public entrypoint enforces origins and session ownership.
    origine = request.headers.get('origin')
    hote = request.headers.get('host','')
    if hote not in {'127.0.0.1:8766','localhost:8766','testserver'} or (origine and origine not in {'http://127.0.0.1:8766','http://localhost:8766'}):
        return Response('Origine non autorisée', status_code=403)
    return await suite(request)

@app.exception_handler(ValueError)
async def erreur_valeur(request, erreur):
    corps = {'detail': str(erreur)}
    if getattr(erreur, 'constats', None):
        corps['constats'] = erreur.constats  # FB5 : l'aperçu montre lignes, décalages et identité à confirmer
    return Response(json.dumps(corps, ensure_ascii=False), status_code=422, media_type='application/json')

@app.get('/')
def accueil():
    return FileResponse(RACINE/'index.html')


@app.get('/import-compteur')
def page_import_compteur():
    return FileResponse(RACINE / 'import_compteur.html')


@app.get('/contrats')
def page_contrats():
    return FileResponse(RACINE / 'contrats.html')


@app.post('/api/contrats/profil')
async def profil_contrats(request: Request):
    from optimisation_contrat import analyser_annee
    from fiche_contrats import modele_contrats
    contenu = await contenu_compteur(request)
    def calculer():
        valeurs, dates = _lire_profil_detaille(contenu['texte'], jours_civils=True)
        resume, _, _ = analyser_annee(valeurs, dates)
        return {'profil': resume, 'modele': modele_contrats(resume['sha256'], resume['annee_mesuree'])}
    return await run_in_threadpool(calculer)


@app.post('/api/contrats/comparer')
async def comparaison_contrats(request: Request):
    from optimisation_contrat import comparer_contrats
    from rapport_contrats import rendre_comparaison, verifier_langue
    contenu = await contenu_compteur(request)
    langue = verifier_langue(contenu.get('langue', 'fr'))
    def calculer():
        valeurs, dates = _lire_profil_detaille(contenu['texte'], jours_civils=True)
        resultat = comparer_contrats(valeurs, dates, contenu.get('configuration'))
        return {'resultat': resultat, 'html': rendre_comparaison(resultat, langue), 'langue': langue}
    return await run_in_threadpool(calculer)


async def contenu_compteur(request: Request):
    from lecteur_csv_compteur import LIMITE_OCTETS
    brut = await request.body()
    if len(brut) > LIMITE_OCTETS:
        raise HTTPException(413, 'Export et configuration limités à 20 Mio.')
    try:
        contenu = json.loads(brut)
    except RecursionError as erreur:
        raise ValueError('Le fichier JSON comporte trop de niveaux imbriqués.') from erreur
    if not isinstance(contenu, dict) or not isinstance(contenu.get('texte'), str):
        raise ValueError('Fournir le texte CSV et ses conventions.')
    return contenu


@app.post('/api/compteur/apercu')
async def apercu_compteur(request: Request):
    from lecteur_csv_compteur import apercu
    contenu = await contenu_compteur(request)
    return await run_in_threadpool(apercu, contenu['texte'], contenu.get('separateur'),
                                   contenu.get('lignes_avant_entete', 0))


@app.post('/api/compteur/convertir')
async def convertir_compteur(request: Request):
    from lecteur_csv_compteur import convertir_csv
    contenu = await contenu_compteur(request)
    resultat = await run_in_threadpool(convertir_csv, contenu['texte'], contenu.get('configuration'))
    # Revue d'Astra de a5e4094 (P2-N) : empreinte des octets du fichier d'origine, que seul le navigateur a lus ;
    # empreinte_texte_source reste celle du texte décodé, qui porte la confirmation de l'heure répétée.
    octets = contenu.get('empreinte_octets')
    if isinstance(octets, str) and re.fullmatch(r'[0-9a-f]{64}', octets):
        resultat['provenance'].update(empreinte_fichier_source=octets, empreinte_fichier_source_par='navigateur')
    return resultat

@app.get('/revue-documentaire.js')
def script_revue():
    return FileResponse(RACINE/'revue_documentaire.js', media_type='text/javascript')

@app.get('/graphiques.js')
def script_graphiques():
    return FileResponse(RACINE/'graphiques.js', media_type='text/javascript')

@app.get('/interface.css')
def style_interface():
    return FileResponse(RACINE/'interface.css', media_type='text/css')

@app.get('/parcours.js')
def script_parcours():
    return FileResponse(RACINE/'parcours.js', media_type='text/javascript')

@app.get('/english.js')
def script_anglais():
    return FileResponse(RACINE/'english.js', media_type='text/javascript')

@app.get('/factory.js')
def script_factory():
    return FileResponse(RACINE/'factory.js', media_type='text/javascript')

@app.get('/factory.css')
def style_factory():
    return FileResponse(RACINE/'factory.css', media_type='text/css')

@app.get('/api/{identifiant}/study')
def etude_existante(identifiant: str):
    return public(charger(identifiant))

@app.post('/api/{identifiant}/scenario')
def nouveau_scenario(identifiant: str):
    # Reuse the same factory documents and demand, never add a simulated machine
    # to the baseline or treat an earlier study as installed equipment.
    dossier = copy.deepcopy(charger(identifiant))
    dossier['id'] = uuid.uuid4().hex
    dossier['revision'] = None
    dossier['resultat'] = None
    dossier['revue_documentaire'] = {}
    for key in ('puissance_kw', 'duree_heures', 'ouverture_heure', 'echeance_heure'):
        dossier['faits'][key] = {'valeur': None, 'document': -1, 'ligne': 0, 'motif': ''}
    sauver(dossier)
    return public(dossier)

@app.get('/fonts/figtree.ttf')
def police_interface():
    return FileResponse(RACINE/'assets/fonts/figtree.ttf', media_type='font/ttf')
@app.get('/preuves.js')
def script_preuves():
    return FileResponse(RACINE / 'preuves.js', media_type='text/javascript')

@app.get('/sensibilite.js')
def script_sensibilite():
    return FileResponse(RACINE / 'sensibilite.js', media_type='text/javascript')

@app.get('/api/{identifiant}/source/{numero}')
def source_originale(identifiant: str, numero: int):
    dossier = charger(identifiant)
    if not 0 <= numero < len(dossier['documents']):
        raise ValueError('Source inconnue.')
    source = dossier['documents'][numero].get('source_pdf')
    if not source:
        raise ValueError('PDF original non conservé pour cet ancien import. Réimportez le document.')
    chemin = (DOSSIERS / source['chemin']).resolve()
    if not chemin.is_relative_to(DOSSIERS.resolve()) or not chemin.is_file():
        raise ValueError('PDF original introuvable.')
    if hashlib.sha256(chemin.read_bytes()).hexdigest() != source['sha256']:
        raise ValueError('Le PDF conservé ne correspond plus à la source importée.')
    return FileResponse(chemin, media_type='application/pdf')

@app.post('/api/exemple')
def exemple():
    # Un cas court entièrement fictif et identifiable, sans ambiguïté d'unité externe.
    from datetime import timedelta
    profil = 'fin_intervalle,puissance_kw\n'
    origine = datetime(2026,1,1,tzinfo=timezone.utc)
    for i in range(96):
        puissance = 180 if 32 <= i < 48 else 60
        profil += f'{(origine+timedelta(minutes=15*(i+1))).isoformat()},{puissance}\n'
    texte = 'CAS FICTIF, aucun contrat ni machine client.\nplafond_kw = 150\npuissance_max_kw = 120\nrendement = 0.9\npuissance_kw = 40\nduree_heures = 4\nouverture_heure = 8\necheance_heure = 18\n'
    return creer([{'nom':'hypotheses-exemple.txt','type_document':'hypothese_simulation','texte':texte,'sha256':hashlib.sha256(texte.encode()).hexdigest()}],profil,'Exemple entièrement fictif, une journée répétée cycliquement.')

def decoder_documents(entrees, stockage=None):
    documents = []
    if not 1 <= len(entrees) <= 20:
        raise ValueError('Déposer entre un et vingt documents.')
    for entree in entrees:
        if not isinstance(entree.get('nom'), str) or any(
                unicodedata.category(c) in ('Cc', 'Zl', 'Zp') for c in entree['nom']):
            raise ValueError('Nom de document invalide : caractères de contrôle ou sauts de ligne interdits.')
        nom = Path(entree['nom']).name
        donnees = base64.b64decode(entree['base64'], validate=True)
        if len(donnees)>LIMITE_DOCUMENT:
            raise ValueError('Limite de 5 Mio par document.')
        if nom.lower().endswith('.pdf'):
            lecture_pdf = lire_pdf(donnees, stockage=DOSSIERS if stockage is None else stockage)
            texte = lecture_pdf['texte']
        elif nom.lower().endswith('.txt'):
            texte = donnees.decode('utf-8-sig')
        else:
            raise ValueError('Documents acceptés : PDF ou TXT UTF-8.')
        if not texte.strip():
            raise ValueError('Aucun texte exploitable dans '+nom+'. Fournir une copie plus lisible.')
        document={'nom':nom,'texte':texte,'sha256':hashlib.sha256(donnees).hexdigest()}
        if nom.lower().endswith('.pdf'):
            document.update(lecture_pdf)
            document['lecture_structuree']=completer(donnees,texte,cache=Path(stockage)/'cache' if stockage is not None else None)
            if lecture_pdf['lecture_ocr']['pages_ocr']:
                document['lecture_structuree']['message'] += ' Lecture structurée complémentaire sans OCR : ne couvre pas nécessairement les pages scannées.'
        documents.append(document)
    return documents

@app.post('/api/importer')
async def importer(request: Request):
    brut = await request.body()
    if len(brut) > 145_000_000:
        raise ValueError('Dossier trop volumineux : vingt documents de 5 Mio maximum.')
    contenu = json.loads(brut)
    metadonnees = contenu.get('metadonnees', {})
    if not isinstance(metadonnees, dict):
        raise ValueError('metadonnees doit être un objet.')
    inconnus = set(metadonnees) - set(CHAMPS_METIER_OPTIONNELS)
    if inconnus:
        raise ValueError('Champ métier inconnu : ' + ', '.join(sorted(inconnus)))
    sources = contenu.get('source_document', {})
    if not isinstance(sources, dict) or any(not isinstance(cle, str) or not isinstance(valeur, str) or not valeur.strip()
                                            for cle, valeur in sources.items()):
        raise ValueError('source_document doit associer chaque champ à un nom de document non vide.')
    sources_inconnues = set(sources) - set(metadonnees)
    if sources_inconnues:
        raise ValueError('source_document référence un champ absent des metadonnees : ' + ', '.join(sorted(sources_inconnues)))
    sources_manquantes = set(metadonnees) - set(sources)
    if sources_manquantes:
        raise ValueError('source_document manquant pour : ' + ', '.join(sorted(sources_manquantes)))
    lire_profil(contenu['profil'])
    with tempfile.TemporaryDirectory(prefix='contingency-import-') as stockage:
        documents = await run_in_threadpool(decoder_documents, contenu['documents'], stockage)
        resultat = creer(documents,contenu['profil'],'Documents importés, valeurs et origine à vérifier par l’utilisateur. Horaires relatifs à chaque bloc de 96 mesures.', metadonnees, sources, stockage=stockage)
        finaliser_import(stockage, resultat['id'])
        return resultat


def finaliser_import(stockage, identifiant):
    """Publie le dossier validé et ses sources, jamais les caches provisoires."""
    stockage = Path(stockage)
    dossier = json.loads((stockage / (identifiant + '.json')).read_text())
    conserver_sources(stockage / 'sources', DOSSIERS / 'sources')
    sauver(dossier)

@app.post('/api/{identifiant}/documents')
async def documents_scenario(identifiant: str, request: Request):
    brut = await request.body()
    if len(brut) > 145_000_000:
        raise ValueError('Files too large.')
    contenu = json.loads(brut)
    return await run_in_threadpool(remplacer_documents, identifiant, contenu)

def remplacer_documents(identifiant, contenu):
    base = charger(identifiant)
    keep = contenu.get('keep', list(range(len(base['documents']))))
    if not isinstance(keep, list) or any(type(i) is not int or not 0 <= i < len(base['documents']) for i in keep) or len(set(keep)) != len(keep):
        raise ValueError('Invalid document selection.')
    entrees = contenu.get('documents', [])
    if not 1 <= len(keep) + len(entrees) <= 20:
        raise ValueError('Select between 1 and 20 documents.')
    with tempfile.TemporaryDirectory(prefix='contingency-import-') as stockage:
        additions = decoder_documents(entrees, stockage) if entrees else []
        return _remplacer_documents_valides(base, keep, additions, stockage)


def _remplacer_documents_valides(base, keep, additions, stockage):
    documents = [base['documents'][i] for i in keep] + additions
    # New evidence must never inherit the old model response or approval.
    fresh = copy.deepcopy(base)
    fresh.update(id=uuid.uuid4().hex, documents=documents, extraction_ia=None,
                 revision=None, resultat=None, revue_documentaire={})
    for cle in ('mode_extraction', 'empreinte_documents_demo', 'repli_de'):
        fresh.pop(cle, None)
    fresh['faits'] = {key: {'valeur':None, 'document':-1, 'ligne':0, 'motif':''} for key in CHAMPS}
    fresh['nature'] = 'Uploaded documents with the existing factory demand profile. Inputs require review.'
    resultat = public(fresh)
    _sauver_dans(fresh, stockage)
    finaliser_import(stockage, fresh['id'])
    return resultat

@app.post('/api/{identifiant}/preparer')
async def preparer(identifiant: str, request: Request):
    dossier = charger(identifiant)
    contenu = await request.json()
    faits = verifier_faits(dossier, contenu['faits'])
    audit = auditer_documents(dossier['documents'])
    revue = verifier_revue(audit, contenu.get('revue_documentaire', {}))
    dossier['faits'] = faits
    dossier['audit_documentaire'] = audit
    dossier['revue_documentaire'] = revue
    dossier['revision'] = revision_dossier(dossier)
    dossier['resultat'] = None
    dossier.pop('sensibilite', None)
    sauver(dossier)
    return public(dossier)

@app.post('/api/{identifiant}/contraintes')
async def contraintes(identifiant: str, request: Request):
    """Sélectionne des règles du catalogue pour revue humaine explicite."""
    dossier = normaliser(charger(identifiant))
    contenu = await request.json()
    identifiants = contenu.get('ids')
    if not isinstance(identifiants, list) or any(not isinstance(i, str) for i in identifiants):
        raise ValueError('ids doit être une liste de contraintes.')
    selection = selectionner_contraintes(identifiants)
    entrees_personnalisees = contenu.get('personnalisees', [])
    if not isinstance(entrees_personnalisees, list):
        raise ValueError('personnalisees doit être une liste.')
    dossier['contraintes'] = selection + personnaliser_contraintes(entrees_personnalisees)
    dossier['catalogue'] = resume_catalogue()
    dossier['revision'] = None
    dossier['resultat'] = None
    sauver(dossier)
    return public(dossier)

@app.post('/api/{identifiant}/extraire')
def extraire_ia(identifiant: str):
    dossier = charger(identifiant)
    precedente = dossier.get('extraction_ia') or {}
    if dossier.get('mode_extraction') == 'demo_archivee':
        if (precedente.get('execution') == 'recorded'
                and dossier.get('empreinte_documents_demo') == empreinte(dossier['documents'])):
            return public(dossier)
        raise HTTPException(409, 'Les pièces ont changé : la réponse enregistrée ne peut pas être rejouée.')
    if ((not getattr(app.state, 'live_ai', False) or precedente.get('execution') == 'live')
            and precedente.get('version') == VERSION_EXTRACTION
            and precedente.get('empreinte') == empreinte_extraction(dossier['documents'])):
        return public(dossier)
    dossier['extraction_ia'] = extraire_avec_nebius(dossier['documents'])
    dossier['extraction_ia']['routage_agents'] = planifier_agents(
        dossier['extraction_ia'], dossier['extraction_ia'].get('audit_documentaire'), dossier.get('contraintes'))
    sauver(dossier)
    return public(dossier)

@app.post('/api/{identifiant}/calculer')
async def calculer(identifiant: str, request: Request):
    dossier = charger(identifiant)
    contenu = await request.json()
    if not dossier['revision'] or contenu.get('revision') != dossier['revision'] or contenu.get('validation') is not True:
        raise ValueError('Validation explicite de la révision courante requise.')
    verifier_revue(auditer_documents(dossier['documents']), dossier.get('revue_documentaire', {}))
    if dossier['revision'] != revision_dossier(dossier):
        raise ValueError('Les documents, hypothèses ou revues ont changé : nouvelle validation requise.')
    v = {k:f['valeur'] for k,f in dossier['faits'].items()}
    jours = np.array(dossier['profil']).reshape(-1,96)
    premier = int(v['ouverture_heure']*4)
    duree = int(v['duree_heures']*4)
    dernier = int(v['echeance_heure']*4)-duree
    debuts = [premier+int(np.argmin(np.convolve(j,np.ones(duree),mode='valid')[premier:dernier+1])) for j in jours]
    def simuler(departs):
        charge = jours.copy()
        for i,d in enumerate(departs):
            charge[i,d:d+duree] += v['puissance_kw']
        return capacite_rapide(charge.ravel(),v['plafond_kw'],rendement=v['rendement'],puissance_max=v['puissance_max_kw'])
    initial = simuler([premier]*len(jours))
    retenu = simuler(debuts)
    # Ne pas remplacer un scénario réalisable par une heuristique plus mauvaise.
    methode = 'Créneau de plus faible demande par bloc (heuristique)'
    if initial['statut']==0 and (retenu['statut']!=0 or initial['capacite_utile_kwh'] < retenu['capacite_utile_kwh']):
        retenu,debuts,methode = initial,[premier]*len(jours),'Départ au début de la fenêtre'
    preuve_solveur = {'statut':'indisponible','raison':'Environnement OR-Tools non installé.'}
    python_documents = PYTHON_DOCUMENTS
    if python_documents.exists():
        try:
            execution = subprocess.run([str(python_documents), str(RACINE.parent/'optimisation/planning_solveur.py')],
                input=json.dumps({'profil':dossier['profil'],'valeurs':v,'limite_s':4}),
                capture_output=True,text=True,timeout=25,check=True)
            preuve_solveur = json.loads(execution.stdout)
            if 'calcul' in preuve_solveur:
                candidat = preuve_solveur['calcul']
                if retenu['statut'] != 0 or candidat['capacite_utile_kwh'] <= retenu['capacite_utile_kwh']+1e-6:
                    retenu = candidat
                    debuts = preuve_solveur['debuts_pas']
                    methode = ('Planning optimal dans le modèle déclaré (OR-Tools/SCIP)' if preuve_solveur['statut']=='optimal'
                               else 'Planning réalisable OR-Tools/SCIP, optimalité non prouvée')
        except subprocess.CalledProcessError as erreur:
            message=erreur.stderr or 'Erreur du processus solveur sans détail.'
            physique=any(terme in message for terme in ['contrôle physique','Capacité sous-estimée','Optimum non concordant'])
            preuve_solveur={'statut':'echec','type_echec':'controle_physique' if physique else 'processus', 'raison':message}
        except (subprocess.SubprocessError,ValueError) as erreur:
            preuve_solveur = {'statut':'echec','raison':'Recherche conjointe non terminée ; stratégies de référence conservées.'}
    dossier.pop('sensibilite', None)
    dossier['resultat'] = {'initial':initial,'retenu':retenu,'debuts_heures':[d/4 for d in debuts], 'methode':methode,'preuve_solveur':preuve_solveur,'moteur':VERSION,'validation':'Validation utilisateur pour simulation, pas certification métier.','revision':dossier['revision']}
    sauver(dossier)
    return public(dossier)

@app.post('/api/{identifiant}/sensibilite')
async def sensibilite(identifiant: str, request: Request):
    dossier = charger(identifiant)
    contenu = await request.json()
    if not isinstance(contenu, dict) or contenu.get('revision') != dossier.get('revision') or not dossier.get('revision'):
        raise ValueError('La sensibilité nécessite la révision validée courante.')
    if not dossier.get('resultat') or controler_export(dossier)['statut'] not in ('optimal', 'realisable'):
        raise ValueError('Calculez et contrôlez un planning réalisable avant sa sensibilité.')
    analyse = analyser(dossier, contenu.get('hypotheses'))
    analyse['resultat_sha256'] = empreinte(dossier['resultat'])
    analyse['empreinte'] = empreinte(analyse)
    dossier['sensibilite'] = analyse
    sauver(dossier)
    return public(dossier)

def _texte_rapport(valeur):
    """Un champ documentaire reste du texte dans une seule ligne du rapport."""
    return ' '.join(str(valeur).splitlines()).replace('|', '/').replace('#', r'\#')


@app.get('/api/{identifiant}/rapport')
def rapport(identifiant: str):
    d = charger(identifiant)
    if not d['resultat']:
        raise ValueError('Aucun calcul validé disponible.')
    r = d['resultat']; calcul = r['retenu']
    controle=controler_export(d)
    lignes = ['# Étude de capacité réseau', '',_texte_rapport(d['nature']),'', '## Résultat de simulation', '',
        controle['conclusion'],
        '', 'Conclusion issue du contrôle déterministe du planning.', 'Départs par bloc (heures relatives) : '+', '.join(map(str,r['debuts_heures'])), '']
    lignes += ['']+['Contrôle : '+_texte_rapport(a) for a in controle['anomalies']]
    audit = controle['audit_documentaire']
    if audit['anomalies']:
        # Ne jamais transformer un clic d'approbation en résolution de l'incertitude physique.
        lignes += ['', '## Alertes documentaires maintenues', '',
            'Simulation exploratoire. Les alertes et les décisions déclarées par l’utilisateur sont conservées ci-dessous. Les motifs ne constituent pas une vérification indépendante. Ce résultat ne valide pas la faisabilité du site.']
        for alerte in audit['anomalies']:
            lignes += ['', _texte_rapport(alerte['code'])+': '+_texte_rapport(alerte['message'])]
            lignes += [f"D{p['document']+1}:L{p['ligne']} : {_texte_rapport(p['citation'])}" for p in alerte['preuves']]
            revue = d.get('revue_documentaire',{}).get(alerte['id'],{})
            libelle = 'Alerte déclarée non applicable par l’utilisateur : ' if revue.get('decision') == 'non_applicable' else 'Hypothèse de simulation : '
            lignes += [libelle + _texte_rapport(revue.get('motif','REVUE MANQUANTE'))]
        if any(a['code'] == 'reserve_prioritaire' for a in audit['anomalies']):
            lignes += ['', 'La capacité calculée concerne le lissage dans le modèle déclaré. La réserve de secours obligatoire n’est pas modélisée : un besoin de lissage nul ne signifie pas qu’aucune batterie ne serait nécessaire sur le site.']
    if controle['statut'] in ('realisable','optimal'):
        lignes += ['Pic réseau recalculé : %.2f kW.' % controle['calcul_verification']['pic_reseau_kw']]
    if r.get('preuve_solveur',{}).get('raison'):
        lignes += ['Motif brut du solveur : '+_texte_rapport(r['preuve_solveur']['raison'])]
    lignes += ['', '## Paramètres vérifiés par l’utilisateur', '', '| Paramètre | Valeur | Source |', '| :--- | ---: | :--- |']
    for cle,f in d['faits'].items():
        source = 'Hypothèse déclarée' if f['document']==-1 else _texte_rapport(d['documents'][f['document']]['nom'])+', ligne '+str(f['ligne'])
        citation = _texte_rapport(f['citation'])
        if f['motif'] and f['document'] != -1:
            citation += ' (correction/commentaire : '+_texte_rapport(f['motif'])+')'
        lignes.append(f"| {CHAMPS[cle][0]} | {f['valeur']} {CHAMPS[cle][1]} | {source}: {citation} |")
    extraction=d.get('extraction_ia')
    trace_ia=('Extraction documentaire proposée par '+_texte_rapport(extraction['modele'])+' via Nebius, puis citations contrôlées par le programme et valeurs validées par l’utilisateur.' if extraction else 'Aucune extraction IA exécutée pour ce dossier.')
    lignes += ['', '## Portée', '', 'Demande connue à l’avance. Pas de 15 minutes, puissance moyenne. Un cycle machine par bloc de 24 heures, sans jours exclus. Rendement constant par sens. État initial du stockage libre et cyclique. Pas de vieillissement, de démarrages, de tarifs ni de contraintes de personnel. Les stratégies de référence sont heuristiques. Une preuve d’optimalité OR-Tools ne vaut que dans ce modèle discret et aux tolérances du solveur. Un échec des heuristiques ne prouve pas que tout planning est impossible.', '', 'Le planning est une enveloppe quart-horaire, pas une consigne EMS. Le pilotage réel peut exiger une réaction à la seconde et doit être vérifié avec le système de contrôle du site.', '', 'Aucune économie financière ni durée humaine économisée mesurée. Simulation, pas recommandation d’achat. '+trace_ia, '', '## Recherche du planning', '', 'Statut brut OR-Tools (à lire avec le contrôle de cohérence ci-dessus) : '+r.get('preuve_solveur',{}).get('statut','non testé'), 'Optimalité uniquement si le solveur la certifie dans le modèle déclaré. Recherche conjointe limitée à sept blocs et quatre secondes ; au-delà, les stratégies de référence sont utilisées.', '', '## Traçabilité', '', 'Révision validée : '+d['revision'], 'Profil SHA-256 : '+d['profil_sha256'], 'Moteur : '+VERSION, 'Résultat SHA-256 : '+empreinte(r)]
    if extraction:
        lignes += ['Extraction IA : '+_texte_rapport(extraction['empreinte']), 'Recherche documentaire : '+_texte_rapport(extraction['methode_recherche'])]
        if 'decision' in extraction:
            lignes += ['Décision après contrôles : '+_texte_rapport(extraction['decision']),
                       'Cette décision documentaire ne valide ni la faisabilité ni les pièces.']
        for champ, proposition in extraction.get('propositions', {}).items():
            for preuve in proposition.get('preuves', []):
                etat = 'citation retrouvée' if preuve['valide'] else 'preuve refusée'
                citation = _texte_rapport(preuve['citation'])
                lignes += [f"Preuve {_texte_rapport(champ)}, {_texte_rapport(preuve['repere'])} ({etat}) : {citation}"]
    if d.get('sensibilite'):
        if controle['statut'] in ('realisable', 'optimal') and sensibilite_valide(d):
            lignes += lignes_rapport(d['sensibilite'])
        else:
            lignes += ['', 'Analyse de sensibilité périmée ou altérée : résultats suspendus.']
    lignes += [_texte_rapport(doc['nom'])+' SHA-256 : '+_texte_rapport(doc['sha256']) for doc in d['documents']]
    for doc in d['documents']:
        if 'lecture_structuree' in doc:
            lecture=doc['lecture_structuree']
            lignes += ['Lecture structurée de '+_texte_rapport(doc['nom'])+' : '+_texte_rapport(lecture['statut']),_texte_rapport(lecture.get('controle',{}).get('message',lecture['message']))]
    return Response('\n'.join(' '.join(ligne.splitlines()) for ligne in lignes),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="etude.md"'})

@app.get('/api/{identifiant}/rapport-lisible')
def rapport_lisible(identifiant: str, lang: str = 'fr'):
    if lang == 'en':
        from rapport_anglais import render
        dossier = charger(identifiant)
        if not dossier.get('resultat'):
            raise ValueError('No validated calculation available.')
        return HTMLResponse(render(dossier, controler_export(dossier), empreinte(dossier['resultat'])))
    texte = rapport(identifiant).body.decode('utf-8')
    return HTMLResponse(rendre_rapport(texte, identifiant))

@app.get('/api/{identifiant}/donnees')
def donnees(identifiant: str):
    d = charger(identifiant)
    if d.get('resultat'):
        d['controle_rapport']=controler_export(d)
    if d.get('sensibilite'):
        d['sensibilite_courante'] = sensibilite_valide(d) and d.get('controle_rapport', {}).get('statut') in ('realisable', 'optimal')
    return Response(json.dumps(d,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="etude.json"'})

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8766)
