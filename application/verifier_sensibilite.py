"""Contrôle indépendant LP et protections contre les résultats périmés."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from fastapi.testclient import TestClient
import serveur
from moteur import capacite_rapide, dimensionner
from sensibilite_dossier import analyser


class Sensibilite(unittest.TestCase):
    def setUp(self):
        self.temporaire = tempfile.TemporaryDirectory()
        self.dossiers = patch.object(serveur, 'DOSSIERS', Path(self.temporaire.name))
        self.dossiers.start()
        self.client = TestClient(serveur.app)
        dossier = self.client.post('/api/exemple').json()
        self.url = f"/api/{dossier['id']}"
        reponse = self.client.post(self.url + '/preparer', json={'faits': dossier['faits']})
        self.assertEqual(reponse.status_code, 200, reponse.text)
        self.dossier = serveur.charger(dossier['id'])
        charge = np.asarray(self.dossier['profil'], dtype=float)
        charge[32:48] += 40
        calcul = capacite_rapide(charge, 150, rendement=.9, puissance_max=120)
        self.dossier['resultat'] = dict(revision=self.dossier['revision'], retenu=calcul, initial=calcul,
            debuts_heures=[8], methode='Planning fixé pour vérification indépendante', preuve_solveur={'statut': 'inconnu'})
        serveur.sauver(self.dossier)
        self.hypotheses = dict(variation_charge_pct=10, variation_plafond_kw=15,
                              motif='Variations exploratoires de test, sans probabilité mesurée.', validation=True)

    def tearDown(self):
        self.client.close()
        self.dossiers.stop()
        self.temporaire.cleanup()

    def envoyer(self, hypotheses=None, revision=None):
        return self.client.post(self.url + '/sensibilite', json={
            'revision': self.dossier['revision'] if revision is None else revision,
            'hypotheses': self.hypotheses if hypotheses is None else hypotheses})

    def test_cinq_variantes_verifiees_par_lp_independant(self):
        original = copy.deepcopy(self.dossier)
        with patch.object(serveur, 'extraire_avec_nebius', side_effect=AssertionError('Aucun appel IA')):
            reponse = self.envoyer()
        self.assertEqual(reponse.status_code, 200, reponse.text)
        analyse = reponse.json()['sensibilite']
        self.assertEqual(len(analyse['scenarios']), 5)
        for scenario in analyse['scenarios']:
            charge = np.asarray(original['profil']) * (1 + scenario['variation_charge_pct'] / 100)
            charge[32:48] += 40
            lp = dimensionner(charge, scenario['plafond_kw'], rendement=.9, puissance_max=120)
            self.assertEqual(lp['statut'], scenario['calcul']['statut'])
            if lp['statut'] == 0:
                self.assertAlmostEqual(lp['capacite_utile_kwh'], scenario['calcul']['capacite_utile_kwh'], places=5)
        apres = serveur.charger(original['id'])
        for cle in ('faits', 'documents', 'profil', 'resultat', 'revision'):
            self.assertEqual(apres[cle], original[cle])
        besoins = {s['nom']: s['calcul']['capacite_utile_kwh'] for s in analyse['scenarios']}
        self.assertLess(besoins['charge_basse'], besoins['reference'])
        self.assertGreater(besoins['charge_haute'], besoins['reference'])
        self.assertGreater(besoins['plafond_bas'], besoins['reference'])
        self.assertLess(besoins['plafond_haut'], besoins['reference'])
        self.assertTrue(self.client.get(self.url + '/donnees').json()['sensibilite_courante'])
        rapport = self.client.get(self.url + '/rapport').text
        self.assertIn(analyse['empreinte'], rapport)
        self.assertIn('Planning machine conservé', rapport)
        self.assertIn('réserve de secours', rapport)

    def test_planning_impossible_ne_devient_pas_zero(self):
        reponse = self.envoyer(self.hypotheses | {'variation_plafond_kw': 150})
        self.assertEqual(reponse.status_code, 200, reponse.text)
        scenario = next(s for s in reponse.json()['sensibilite']['scenarios'] if s['nom'] == 'plafond_bas')
        self.assertEqual(scenario['calcul']['statut'], 2)
        self.assertNotIn('capacite_utile_kwh', scenario['calcul'])
        self.assertFalse(scenario['capacite_reference_suffisante'])
        self.assertIn('Irréalisable pour ce planning', self.client.get(self.url + '/rapport').text)

    def test_revision_resultat_et_validation_obligatoires(self):
        self.assertEqual(self.envoyer(revision='ancienne').status_code, 422)
        self.assertEqual(self.envoyer(self.hypotheses | {'validation': False}).status_code, 422)
        self.dossier['resultat'] = None
        serveur.sauver(self.dossier)
        self.assertEqual(self.envoyer().status_code, 422)

    def test_parametres_aberrants_refuses(self):
        for cle, valeur in [('variation_charge_pct', -1), ('variation_charge_pct', 51),
                            ('variation_charge_pct', True), ('variation_charge_pct', '10'),
                            ('variation_plafond_kw', 151), ('motif', 'court'), ('motif', None)]:
            with self.subTest(cle=cle, valeur=valeur):
                self.assertEqual(self.envoyer(self.hypotheses | {cle: valeur}).status_code, 422)
        self.assertEqual(self.envoyer(self.hypotheses | {'variation_charge_pct': 0, 'variation_plafond_kw': 0}).status_code, 422)
        for valeur in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                analyser(self.dossier, self.hypotheses | {'variation_charge_pct': valeur})

    def test_resultat_altere_bloque(self):
        self.dossier['resultat']['retenu']['capacite_utile_kwh'] += 10
        serveur.sauver(self.dossier)
        self.assertEqual(self.envoyer().status_code, 422)

    def test_ancienne_sensibilite_effacee_apres_preparation(self):
        self.assertEqual(self.envoyer().status_code, 200)
        self.client.post(self.url + '/preparer', json={'faits': self.dossier['faits']})
        self.assertNotIn('sensibilite', serveur.charger(self.dossier['id']))
        self.assertEqual(self.envoyer().status_code, 422)

    def test_sensibilite_alteree_suspendue_dans_exports(self):
        self.assertEqual(self.envoyer().status_code, 200)
        dossier = serveur.charger(self.dossier['id'])
        dossier['sensibilite']['scenarios'][0]['calcul']['capacite_utile_kwh'] = 999
        serveur.sauver(dossier)
        self.assertFalse(self.client.get(self.url + '/donnees').json()['sensibilite_courante'])
        rapport = self.client.get(self.url + '/rapport').text
        self.assertIn('résultats suspendus', rapport)
        self.assertNotIn('## Sensibilité du planning validé', rapport)

    def test_doc_modifie_invalide_revision(self):
        self.assertEqual(self.envoyer().status_code, 200)
        dossier = serveur.charger(self.dossier['id'])
        dossier['documents'][0]['texte'] += '\nDocument révisé'
        serveur.sauver(dossier)
        self.assertEqual(self.envoyer().status_code, 422)
        self.assertFalse(self.client.get(self.url + '/donnees').json()['sensibilite_courante'])


if __name__ == '__main__':
    unittest.main()
