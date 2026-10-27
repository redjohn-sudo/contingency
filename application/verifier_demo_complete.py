"""Répétition persistante : import réel, un appel autorisé, revue simulée, calcul, repli.

Les phases sont séparées afin qu'une préparation ou un rejeu ne consomme aucun crédit.
Les valeurs ajoutées par la revue sont des hypothèses de test, pas un avis d'ingénieur.
"""
import argparse
import base64
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
import serveur
import extraction_nebius
import protocole_structure

RACINE = Path(__file__).resolve().parent.parent
AUDIT = RACINE / 'audit-demo-20260922'
ETAT = AUDIT / 'etat.json'


def ecrire(chemin, valeur):
    chemin.write_text(json.dumps(valeur, ensure_ascii=False, indent=2) + '\n')


def obtenir(reponse):
    reponse.raise_for_status()
    return reponse.json()


def preparer(client):
    if ETAT.exists():
        raise SystemExit('Import déjà conservé ; aucun écrasement automatique.')
    chemins = [RACINE / 'evaluation-dossier-long/sources' / nom for nom in
               ('liander-av-zakelijk.pdf', 'liander-tarieven-2026.pdf', 'atlas.pdf', 'kaeser.pdf')]
    chemins += sorted((RACINE / 'evaluation-dossier-long/v2/pieces').glob('D*.txt'))
    assert len(chemins) == 9 and all(p.is_file() for p in chemins)
    origine = datetime(2026, 1, 5, tzinfo=timezone.utc)
    profil = 'fin_intervalle,puissance_kw\n' + ''.join(
        f'{(origine + timedelta(minutes=15*(i+1))).isoformat()},{620 if 36 <= i < 52 else 480}\n'
        for i in range(96))
    debut = time.perf_counter()
    dossier = obtenir(client.post('/api/importer', json={
        'documents': [{'nom': p.name, 'base64': base64.b64encode(p.read_bytes()).decode()} for p in chemins],
        'profil': profil}))
    stocke = serveur.charger(dossier['id'])
    stocke['nature'] = ('TEST TECHNIQUE CONSTRUIT : quatre PDF publics, cinq pièces fictives v2, '
                        'profil fictif. Toute revue de ce script est simulée, sans validation métier.')
    serveur.sauver(stocke)
    etat = {'id': dossier['id'], 'date_utc': datetime.now(timezone.utc).isoformat(),
            'import_secondes': round(time.perf_counter()-debut, 3),
            'documents': [{'nom': d['nom'], 'sha256': d['sha256'],
                           'pages_ocr': d.get('lecture_ocr', {}).get('pages_ocr', []),
                           'lecture_structuree': d.get('lecture_structuree', {}).get('statut')}
                          for d in stocke['documents']],
            'faits_avant_extraction': copy.deepcopy(stocke['faits']),
            'caracteres': sum(len(d['texte']) for d in stocke['documents'])}
    ecrire(ETAT, etat)
    print(json.dumps(etat, ensure_ascii=False), flush=True)


def extraire(client, etat):
    dossier = serveur.charger(etat['id'])
    if dossier.get('extraction_ia'):
        raise SystemExit('Une extraction est déjà conservée : utiliser le rejeu, sans nouvel appel.')
    debut = time.perf_counter()
    dossier = obtenir(client.post(f'/api/{etat["id"]}/extraire'))
    assert dossier['faits'] == etat['faits_avant_extraction'], 'Application automatique interdite.'
    etat.update(extraction_secondes=round(time.perf_counter()-debut, 3),
                faits_inchanges=True, modele=dossier['extraction_ia']['modele'])
    ecrire(ETAT, etat)
    ecrire(AUDIT/'extraction.json', dossier['extraction_ia'])
    print(json.dumps({'modele': etat['modele'], 'secondes': etat['extraction_secondes'],
                      'faits_inchanges': True, 'decision': dossier['extraction_ia']['decision']},
                     ensure_ascii=False), flush=True)


def rejouer(client, etat):
    identifiant = etat['id']
    dossier = serveur.charger(identifiant)
    if not dossier.get('extraction_ia'):
        raise SystemExit('Aucune extraction conservée ; le rejeu ne lance pas de modèle.')
    with patch.object(serveur, 'extraire_avec_nebius', side_effect=AssertionError('Appel réseau interdit pendant le rejeu.')):
        dossier = obtenir(client.post(f'/api/{identifiant}/extraire'))
    assert client.post(f'/api/{identifiant}/calculer', json={'validation': False}).status_code == 422
    faits = copy.deepcopy(etat['faits_avant_extraction'])
    propositions = dossier['extraction_ia']['propositions']
    hypotheses = []
    for champ, proposition in propositions.items():
        if proposition['valeur'] is not None:
            faits[champ].update(valeur=proposition['valeur'], document=proposition['document'],
                                ligne=proposition['ligne'], motif='Acceptation simulée pour le test technique.')
    # Ces trois valeurs sont annoncées comme hypothèses de la simulation.
    # Le script ne transforme aucune proposition bloquée en fait documentaire validé.
    for champ, valeur, motif in (
        ('puissance_max_kw', 100, 'Hypothèse de test : puissance batterie de 100 kW ; devis et réserve à clarifier.'),
        ('puissance_kw', 73, 'Hypothèse de test : dix compresseurs à 7,3 kW ; application de la fiche au site non validée.'),
        ('rendement', 0.88**0.5, 'Hypothèse de pertes symétriques : racine de 0,88 ; rendement par sens non fourni.')):
        if faits[champ]['valeur'] is None:
            faits[champ].update(valeur=valeur, document=-1, ligne=0, motif=motif)
            hypotheses.append({'champ': champ, 'valeur': valeur, 'motif': motif})
    manquants = [c for c, f in faits.items() if f['valeur'] is None]
    if manquants:
        raise SystemExit('Revue requise sur des champs non prévus : ' + ', '.join(manquants))
    revue = {a['id']: {'decision': 'simulation_limitee',
                       'motif': 'Revue SIMULÉE pour vérifier la chaîne ; aucune résolution métier. Alerte : '+a['code']}
             for a in dossier['audit_documentaire']['anomalies']}
    dossier = obtenir(client.post(f'/api/{identifiant}/preparer', json={'faits': faits, 'revue_documentaire': revue}))
    debut = time.perf_counter()
    dossier = obtenir(client.post(f'/api/{identifiant}/calculer', json={'revision': dossier['revision'], 'validation': True}))
    calcul_secondes = round(time.perf_counter()-debut, 3)
    rapport = client.get(f'/api/{identifiant}/rapport')
    rapport.raise_for_status()
    export = obtenir(client.get(f'/api/{identifiant}/donnees'))
    assert 'Extraction documentaire proposée' in rapport.text
    assert export['controle_rapport']['statut'] != 'bloque', export['controle_rapport']
    (AUDIT/'rapport.md').write_text(rapport.text)
    ecrire(AUDIT/'donnees.json', export)
    resultat = {'id': identifiant, 'modele': dossier['extraction_ia']['modele'],
                'nature': dossier['nature'], 'rejeu_sans_appel_modele': True,
                'validation_absente_refusee': True, 'hypotheses_simulees': hypotheses,
                'calcul_secondes': calcul_secondes, 'calcul_statut': dossier['resultat']['retenu']['statut'],
                'solveur_statut': dossier['resultat']['preuve_solveur']['statut'],
                'capacite_utile_kwh': dossier['resultat']['retenu'].get('capacite_utile_kwh'),
                'controle_rapport': export['controle_rapport']['statut'], 'rapport_http': rapport.status_code}
    ecrire(AUDIT/'parcours.json', resultat)
    print(json.dumps(resultat, ensure_ascii=False, indent=2), flush=True)


def simuler(client, etat):
    """Exercer la chaîne sans réseau, dans un stockage séparé du futur essai réel."""
    global AUDIT, ETAT
    original = serveur.charger(etat['id'])
    empreinte_avant = serveur.empreinte(original)
    reponse = {'resume': 'Réponse fabriquée pour un test logiciel hors ligne, aucun modèle exécuté.',
               'champs': {c: None for c in serveur.CHAMPS},
               'preuves': {c: [] for c in serveur.CHAMPS},
               'alertes': ['sources_contradictoires'], 'decision': 'demander_information'}
    index = protocole_structure.indexer_lignes(original['documents'])
    for champ, valeur, document, texte in (
        ('plafond_kw', 650, 5, 'Gecontracteerd transportvermogen afname'),
        ('duree_heures', 4, 6, 'aaneengesloten blok'),
        ('ouverture_heure', 8, 6, 'aaneengesloten blok'),
        ('echeance_heure', 16, 6, 'aaneengesloten blok')):
        repere, ligne = next((r, l) for r, l in index.items()
                             if l['document'] == document and texte in l['texte'])
        reponse['champs'][champ] = valeur
        reponse['preuves'][champ] = [{'repere': repere, 'citation': ligne['texte']}]
    sortie = {'model': extraction_nebius.configuration()['modele'],
               'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(reponse)}}],
               'usage': {}}
    audit_initial, etat_initial = AUDIT, ETAT
    AUDIT = AUDIT / 'hors-ligne'
    AUDIT.mkdir(exist_ok=True)
    ETAT = AUDIT / 'etat.json'
    try:
        with tempfile.TemporaryDirectory() as temporaire, patch.object(serveur, 'DOSSIERS', Path(temporaire)):
            original['nature'] += ' EXTRACTION IA SIMULÉE, aucun appel de modèle pendant cette répétition.'
            serveur.sauver(original)
            etat_simule = copy.deepcopy(etat)
            with patch.object(extraction_nebius, 'charger_cle', return_value='factice'), \
                    patch.object(extraction_nebius, 'appeler', return_value=(sortie, 0)):
                extraire(client, etat_simule)
            copie = serveur.charger(etat['id'])
            copie['extraction_ia'].update(modele='SIMULATION LOCALE, aucun appel IA', simulation=True, journal_api=[])
            serveur.sauver(copie)
            etat_simule['modele'] = copie['extraction_ia']['modele']
            ecrire(ETAT, etat_simule)
            ecrire(AUDIT/'extraction.json', copie['extraction_ia'])
            rejouer(client, etat_simule)
    finally:
        AUDIT, ETAT = audit_initial, etat_initial
    assert serveur.empreinte(serveur.charger(etat['id'])) == empreinte_avant, 'Le dossier réel ne doit pas recevoir la simulation.'


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument('phase', choices=('preparer', 'extraire', 'rejouer', 'simuler'))
    args = options.parse_args()
    AUDIT.mkdir(exist_ok=True)
    with TestClient(serveur.app) as client:
        if args.phase == 'preparer':
            preparer(client)
        else:
            etat = json.loads(ETAT.read_text())
            {'extraire': extraire, 'rejouer': rejouer, 'simuler': simuler}[args.phase](client, etat)


if __name__ == '__main__':
    main()
