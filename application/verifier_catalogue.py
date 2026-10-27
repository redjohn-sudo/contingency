import unittest

import catalogue
from routage_agents import planifier


class CatalogueTest(unittest.TestCase):
    def test_catalogue_est_indexe_sans_doublon(self):
        entrees = catalogue.charger()
        self.assertGreaterEqual(len(entrees), 100)
        self.assertEqual(len(entrees), len(set(entrees)))
        self.assertTrue(all(entree.get('nom') for entree in entrees.values()))

    def test_selection_reste_a_revoir(self):
        selection = catalogue.selectionner(['RES-001', 'SEC-001'])
        self.assertEqual([x['statut'] for x in selection], ['a_revoir', 'a_revoir'])
        self.assertTrue(all(x['source'] for x in selection))

    def test_contrainte_inconnue_bloquee(self):
        with self.assertRaises(ValueError):
            catalogue.selectionner(['REG-999'])

    def test_contrainte_personnalisee_est_tracee_sans_fausse_certitude(self):
        selection = catalogue.personnalisees([{
            'nom': 'Limite de bruit du voisinage',
            'forme_mesurable': 'niveau_db_nuit <= 45',
            'source': 'courrier de la commune, 24/09/2026',
            'consequence': 'demander une étude acoustique si dépassée',
            'confiance': 'a_verifier',
        }])
        self.assertEqual(selection[0]['statut'], 'a_revoir')
        self.assertEqual(selection[0]['origine'], 'ingenieur')
        self.assertTrue(selection[0]['id'].startswith('CUSTOM-'))

    def test_second_avis_declenche_seulement_sur_doute(self):
        propre = planifier({'modele': 'deepseek', 'alertes': [],
                            'propositions': {'plafond_kw': {'valeur': 100, 'preuves': [{'valide': True}]}}})
        self.assertFalse(propre['second_avis_requis'])
        doute = planifier({'modele': 'deepseek', 'alertes': ['valeur manquante'],
                           'propositions': {'plafond_kw': {'valeur': None, 'preuves': []}}})
        self.assertTrue(doute['second_avis_requis'])
        self.assertIn('alertes_extraction', doute['raisons'])


if __name__ == '__main__':
    unittest.main()
