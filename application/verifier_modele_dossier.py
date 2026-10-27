import unittest

from modele_dossier import evenement, nouveau_dossier, normaliser, verifier


class ModeleDossierTest(unittest.TestCase):
    def setUp(self):
        self.dossier = nouveau_dossier(
            identifiant='a' * 32,
            documents=[],
            profil=[0.0],
            profil_sha256='profil',
            nature='fixture',
            faits={},
        )

    def test_nouveau_dossier_contient_les_etapes_v4(self):
        self.assertEqual(self.dossier['schema_version'], 'contingency-dossier-1')
        self.assertEqual(self.dossier['contraintes'], [])
        self.assertEqual(self.dossier['validations'], [])
        self.assertEqual(self.dossier['scenarios'], [])
        self.assertEqual(self.dossier['suivi'], {'evenements': []})
        self.assertEqual(verifier(self.dossier), [])
        self.assertIn('profil_horodatages', self.dossier)
        self.assertIsNone(self.dossier['gtv_declare_kw'])
        self.assertIsNone(self.dossier['commune'])
        self.assertEqual(self.dossier['source_document'], {})
        self.assertIsNone(self.dossier['terrain_industriel_zone'])

    def test_evenement_ne_modifie_pas_l_archive_source(self):
        resultat = evenement(self.dossier, 'import', {'nombre': 0})
        self.assertEqual(self.dossier['suivi']['evenements'], [])
        self.assertEqual(resultat['suivi']['evenements'][0]['type'], 'import')

    def test_normaliser_une_archive_ancienne(self):
        ancien = {'id': 'b' * 32, 'documents': [], 'profil': [], 'faits': {}}
        resultat = normaliser(ancien)
        self.assertEqual(verifier(resultat), [])
        self.assertEqual(resultat['schema_version'], 'contingency-dossier-1')
        self.assertEqual(resultat['profil_horodatages'], [])
        self.assertIsNone(resultat['date_depot'])


if __name__ == '__main__':
    unittest.main()
