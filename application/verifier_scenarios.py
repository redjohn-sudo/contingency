"""Independent machine scenarios preserve evidence and require fresh approval."""
import copy
import tempfile
import unittest
from pathlib import Path
import serveur
from fastapi.testclient import TestClient

class MachineScenarios(unittest.TestCase):
    def test_clone_preserves_factory_and_invalidates_machine_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            original_dir = serveur.DOSSIERS
            serveur.DOSSIERS = Path(directory)
            try:
                original = {"id":"a"*32,"documents":[],"profil":[480]*96,"profil_sha256":"profile", "nature":"test",
                    "faits":{key:{"valeur":73,"document":-1,"ligne":0,"motif":"Explicit assumption"} for key in serveur.CHAMPS},
                    "revision":"approved", "resultat":{"old":"result"}, "revue_documentaire":{"old":"approved"},
                    "extraction_ia":{"recorded":"unchanged"}}
                serveur.sauver(original)
                response = TestClient(serveur.app).post('/api/'+original['id']+'/scenario')
                self.assertEqual(response.status_code,200)
                clone = serveur.charger(response.json()['id'])
                self.assertNotEqual(clone['id'],original['id'])
                self.assertEqual(serveur.charger(original['id']),original)
                for key in ('documents','profil','profil_sha256','extraction_ia'):
                    self.assertEqual(clone[key],original[key])
                self.assertIsNone(clone['revision'])
                self.assertIsNone(clone['resultat'])
                self.assertEqual(clone['revue_documentaire'],{})
                for key in ('puissance_kw','duree_heures','ouverture_heure','echeance_heure'):
                    self.assertIsNone(clone['faits'][key]['valeur'])
                self.assertEqual(clone['faits']['plafond_kw'],original['faits']['plafond_kw'])
                clone['faits']['plafond_kw']['valeur']=650
                serveur.sauver(clone)
                self.assertEqual(serveur.charger(original['id']),original)
            finally:
                serveur.DOSSIERS=original_dir

class DocumentChanges(unittest.TestCase):
    def test_new_documents_clear_model_response_and_preserve_profile(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            old_dir=serveur.DOSSIERS
            serveur.DOSSIERS=Path(directory)
            try:
                original={"id":"b"*32,"documents":[{"nom":"grid.txt","texte":"plafond_kw = 650", "sha256":"old"}],
                    "profil":[480]*96,"profil_sha256":"same-profile","nature":"test", "faits":{},
                    "revision":"approved","resultat":{"old":"result"},"extraction_ia":{"old":"model"},"revue_documentaire":{"old":"decision"}}
                serveur.sauver(original)
                client=TestClient(serveur.app)
                response=client.post('/api/'+original['id']+'/documents',json={"keep":[0],"documents":[{"nom":"new-machine.txt","base64":base64.b64encode(b'Machine power: 90 kW').decode()}]})
                self.assertEqual(response.status_code,200)
                fresh=serveur.charger(response.json()['id'])
                self.assertEqual(len(fresh['documents']),2)
                self.assertIn('90 kW',fresh['documents'][1]['texte'])
                self.assertIsNone(fresh['extraction_ia'])
                self.assertIsNone(fresh['revision'])
                self.assertIsNone(fresh['resultat'])
                self.assertTrue(all(f['valeur'] is None for f in fresh['faits'].values()))
                self.assertEqual(fresh['profil'],original['profil'])
                self.assertEqual(fresh['profil_sha256'],original['profil_sha256'])
                self.assertEqual(serveur.charger(original['id']),original)
                empty=client.post('/api/'+original['id']+'/documents',json={"keep":[],"documents":[]})
                self.assertEqual(empty.status_code,422)
            finally:serveur.DOSSIERS=old_dir

if __name__=='__main__': unittest.main()
