"""Live mode cannot reuse an archived response; unchanged live evidence is cached."""
import copy
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import serveur
import extraction_nebius
from lancer_demo_archivee import configurer


@contextmanager
def demo_temporaire():
    """Isole routes et dossiers, et interdit tout accès au fournisseur."""
    anciennes_routes = list(serveur.app.router.routes)
    ancien_dossier = serveur.DOSSIERS
    ancien_extracteur = serveur.extraire_avec_nebius
    ancien_live = getattr(serveur.app.state, 'live_ai', False)
    try:
        with tempfile.TemporaryDirectory() as repertoire, patch(
                'urllib.request.urlopen', side_effect=AssertionError('Appel externe interdit')):
            configurer(Path(repertoire), live=True)
            with TestClient(serveur.app) as client:
                yield client
    finally:
        serveur.DOSSIERS = ancien_dossier
        serveur.extraire_avec_nebius = ancien_extracteur
        serveur.app.state.live_ai = ancien_live
        serveur.app.router.routes = anciennes_routes


class LiveMode(unittest.TestCase):
    def test_repli_apres_echec_ouvre_un_autre_dossier_sans_appel(self):
        with demo_temporaire() as client:
            etude = client.post('/api/demo/archive').json()
            originale = serveur.charger(etude['id'])
            originale['documents'] = [{'nom': 'client.txt', 'texte': 'Pièce du client, différente de la démo.', 'sha256': 'client'}]
            serveur.sauver(originale)
            with patch.object(serveur, 'extraire_avec_nebius', side_effect=ValueError('Nebius inaccessible.')) as fournisseur:
                echec = client.post(f'/api/{etude["id"]}/extraire')
                self.assertEqual(echec.status_code, 422)
                reponse = client.post(f'/api/{etude["id"]}/demo-repli')
                self.assertEqual(reponse.status_code, 200)
                repli = reponse.json()
                self.assertNotEqual(repli['id'], etude['id'])
                self.assertEqual(repli['repli_de'], etude['id'])
                self.assertEqual(repli['origine_demo'], repli['id'])
                self.assertEqual(repli['mode_extraction'], 'demo_archivee')
                self.assertEqual(repli['extraction_ia']['execution'], 'recorded')
                self.assertIn('REJEU', repli['extraction_ia']['resume'])
                self.assertNotEqual(repli['documents'], originale['documents'])
                self.assertIsNone(repli['revision'])
                self.assertIsNone(repli['resultat'])
                # Le repli reste gratuit même si le serveur général est en mode live.
                relance = client.post(f'/api/{repli["id"]}/extraire')
                self.assertEqual(relance.status_code, 200)
                self.assertEqual(relance.json()['extraction_ia']['execution'], 'recorded')
                self.assertEqual(fournisseur.call_count, 1)
                scenario = client.post(f'/api/{repli["id"]}/scenario').json()
                self.assertEqual(scenario['origine_demo'], repli['origine_demo'])
            self.assertEqual(serveur.charger(etude['id']), originale)

    def test_repli_refuse_source_inconnue(self):
        with demo_temporaire() as client:
            avant = list(serveur.DOSSIERS.glob('*.json'))
            reponse = client.post('/api/' + 'a' * 32 + '/demo-repli')
            self.assertEqual(reponse.status_code, 422)
            self.assertEqual(list(serveur.DOSSIERS.glob('*.json')), avant)

    def test_repli_refuse_une_archive_modifiee_sans_appel(self):
        with demo_temporaire() as client:
            etude = client.post('/api/demo/archive').json()
            repli = client.post(f'/api/{etude["id"]}/demo-repli').json()
            dossier = serveur.charger(repli['id'])
            dossier['documents'][0]['texte'] += '\nNouvelle clause.'
            serveur.sauver(dossier)
            with patch.object(serveur, 'extraire_avec_nebius') as fournisseur:
                reponse = client.post(f'/api/{repli["id"]}/extraire')
                self.assertEqual(reponse.status_code, 409)
                fournisseur.assert_not_called()

    def test_nouvelles_pieces_sortent_du_repli_sans_heriter_la_reponse(self):
        with demo_temporaire() as client:
            etude = client.post('/api/demo/archive').json()
            repli = client.post(f'/api/{etude["id"]}/demo-repli').json()
            avant = copy.deepcopy(serveur.charger(repli['id']))
            nouvelle = client.post(f'/api/{repli["id"]}/documents', json={'keep': [0]}).json()
            self.assertNotEqual(nouvelle['id'], repli['id'])
            self.assertIsNone(nouvelle['extraction_ia'])
            self.assertNotIn('mode_extraction', nouvelle)
            self.assertNotIn('repli_de', nouvelle)
            self.assertEqual(serveur.charger(repli['id']), avant)

    def test_archive_keeps_its_original_model_after_live_default_changes(self):
        old_dir=serveur.DOSSIERS
        old_extractor=serveur.extraire_avec_nebius
        old_live=getattr(serveur.app.state,'live_ai',False)
        old_routes=list(serveur.app.router.routes)
        try:
            with tempfile.TemporaryDirectory() as directory:
                configurer(Path(directory),live=False)
                client=TestClient(serveur.app)
                study=client.post('/api/demo/archive').json()
                self.assertEqual(study['extraction_ia']['execution'],'recorded')
                self.assertEqual(study['extraction_ia']['modele'],'deepseek-ai/DeepSeek-V4.1-Flash')
                # L'archive du 24/09 porte l'empreinte actuelle : relancer l'extraction
                # renvoie la réponse enregistrée, sans appel (l'extracteur lève 503).
                relance=client.post('/api/'+study['id']+'/extraire')
                self.assertEqual(relance.status_code,200)
                self.assertEqual(relance.json()['extraction_ia']['execution'],'recorded')
        finally:
            serveur.DOSSIERS=old_dir
            serveur.extraire_avec_nebius=old_extractor
            serveur.app.state.live_ai=old_live
            serveur.app.router.routes=old_routes

    def test_live_seed_and_cache_provenance(self):
        old_dir=serveur.DOSSIERS
        old_extractor=serveur.extraire_avec_nebius
        old_live=getattr(serveur.app.state,'live_ai',False)
        old_routes=list(serveur.app.router.routes)
        try:
            with tempfile.TemporaryDirectory() as directory:
                configurer(Path(directory),live=True)
                client=TestClient(serveur.app)
                self.assertIn('window.CONTINGENCY_LIVE_AI=true',client.get('/demo').text)
                study=client.post('/api/demo/archive').json()
                self.assertIsNone(study['extraction_ia'])
                self.assertIsNone(study['revision'])
                self.assertEqual(study['faits']['plafond_kw']['valeur'],650)
                stored=serveur.charger(study['id'])
                recorded={'execution':'recorded','version':extraction_nebius.VERSION,
                          'empreinte':extraction_nebius.empreinte_extraction(stored['documents'])}
                stored['extraction_ia']=recorded
                serveur.sauver(stored)
                live=dict(recorded,execution='live')
                with patch.object(serveur,'extraire_avec_nebius',return_value=live) as model:
                    url='/api/'+study['id']+'/extraire'
                    first=client.post(url)
                    self.assertEqual(first.status_code,200)
                    self.assertEqual(first.json()['extraction_ia']['execution'],'live')
                    self.assertEqual(client.post(url).json()['extraction_ia'],live)
                    self.assertEqual(model.call_count,1)
                self.assertEqual(serveur.charger(study['id'])['faits'],stored['faits'])
        finally:
            serveur.DOSSIERS=old_dir
            serveur.extraire_avec_nebius=old_extractor
            serveur.app.state.live_ai=old_live
            serveur.app.router.routes=old_routes

if __name__=='__main__':unittest.main()
