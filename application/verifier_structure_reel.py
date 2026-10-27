"""Un appel réel au modèle configuré via l'endpoint applicatif, sur les textes archivés des neuf pièces.

La trace du 22/09 (Kimi) reste dans audit-structure-20260922 ; celle du 24/09
(DeepSeek, modèle retenu le 23/09) va dans audit-structure-20260924.
"""
import datetime
import os
import hashlib
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import serveur

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / os.environ.get('CONTINGENCY_SORTIE_ESSAI', 'audit-structure-20260924')


def main():
    SORTIE.mkdir(exist_ok=True)
    cible = SORTIE / 'essai-reel.json'
    if cible.exists():
        raise SystemExit('Trace déjà présente : aucun appel relancé automatiquement.')
    # Mêmes neuf textes que la démo archivée : fichiers séparés s'ils existent,
    # sinon ceux conservés dans le rapport audité du 22/09 (empreintes vérifiées).
    from lancer_demo_archivee import documents_archives
    documents = documents_archives()
    debut = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    profil = 'fin_intervalle,puissance_kw\n' + ''.join(
        f'{(debut + datetime.timedelta(minutes=15*(i+1))).isoformat()},60\n' for i in range(96))
    with tempfile.TemporaryDirectory() as repertoire, patch.object(serveur, 'DOSSIERS', Path(repertoire)):
        dossier = serveur.creer(documents, profil, 'Test sur textes archivés : quatre PDF publics et cinq pièces construites ; profil fictif. Aucun nouvel OCR.')
        client = TestClient(serveur.app)
        reponse = client.post(f'/api/{dossier["id"]}/extraire')
        if reponse.status_code != 200:
            raise SystemExit(f'Échec HTTP applicatif {reponse.status_code} : ' + reponse.text[:500])
        resultat = reponse.json()
        assert resultat['faits'] == dossier['faits'], 'Les propositions ne doivent pas être appliquées automatiquement.'
        export = client.get(f'/api/{dossier["id"]}/donnees').json()
        cible.write_text(json.dumps({'date_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                   'limite': dossier['nature'], 'faits_inchanges': True,
                                   'extraction': export['extraction_ia']}, ensure_ascii=False, indent=2))
    e = resultat['extraction_ia']
    print(json.dumps({'modele': e['modele'], 'decision': e['decision'], 'faits_inchanges': True,
                      'champs': {c: {'valeur': p['valeur'], 'preuves': len(p['preuves']),
                                     'preuves_invalides': sum(not r['valide'] for r in p['preuves']),
                                     'controle': p['controle']} for c, p in e['propositions'].items()},
                      'journal_api': e['journal_api']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
