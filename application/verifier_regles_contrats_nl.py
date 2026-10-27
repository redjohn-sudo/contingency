"""Repères de date et filtre opérateur : aucune disponibilité inventée."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from regles_contrats_nl import admissibilite, premiere_date_gtv


class DatesContrats(unittest.TestCase):
    def test_baisse_ef_prochain_mois(self):
        r = premiere_date_gtv('2026-09-27', 'e', historique_12_mois_confirme=True)
        self.assertEqual(r['borne_reglementaire'], '2026-10-01')
        self.assertIsNone(r['date_confirmee'])

    def test_douze_mois_depuis_hausse(self):
        self.assertEqual(premiere_date_gtv('2026-09-27', 'f', derniere_hausse='2026-03-01')['borne_reglementaire'], '2027-03-01')

    def test_historique_absent_pas_de_date(self):
        self.assertIsNone(premiere_date_gtv('2026-09-27', 'e')['borne_reglementaire'])

    def test_exception_ef_acceptee(self):
        self.assertEqual(premiere_date_gtv('2026-09-27', 'e', derniere_hausse='2026-08-01', exception_acceptee=True)['borne_reglementaire'], '2026-10-01')

    def test_exception_ad_et_une_seule_modification(self):
        for lettre in 'abcd':
            self.assertIsNone(premiere_date_gtv('2026-09-27', lettre)['borne_reglementaire'])
            r = premiere_date_gtv('2026-09-27', lettre, exception_acceptee=True, changement_deja_effectue=False)
            self.assertEqual(r['borne_reglementaire'], '2026-10-01')
            self.assertIsNone(premiere_date_gtv('2026-09-27', lettre, exception_acceptee=True, changement_deja_effectue=True)['borne_reglementaire'])

    def test_decembre(self):
        self.assertEqual(premiere_date_gtv('2026-12-31', 'e', sens='hausse')['borne_reglementaire'], '2027-01-01')

    def test_bissextile(self):
        self.assertEqual(premiere_date_gtv('2028-03-01', 'e', derniere_hausse='2028-02-29')['borne_reglementaire'], '2029-02-28')

    def test_pas_application_retroactive(self):
        self.assertIsNone(premiere_date_gtv('2025-09-27', 'e', historique_12_mois_confirme=True)['borne_reglementaire'])

    def test_ls_pas_assimile_a_ms(self):
        for lettre in ('g', 'h'):
            r = premiere_date_gtv('2026-09-27', lettre, historique_12_mois_confirme=True)
            self.assertIsNone(r['borne_reglementaire'])
            self.assertTrue(any('LS' in m for m in r['manquants']))

    def test_categorie_inconnue_ne_se_deduit_pas(self):
        self.assertIsNone(premiere_date_gtv('2026-09-27', 'MS')['borne_reglementaire'])

    def test_entrees_invalides(self):
        for jour in (None, True, '2026-09-31', '20260927', '2026-09-27T00:00:00', '9999-01-01'):
            with self.subTest(jour=jour), self.assertRaises(ValueError):
                premiere_date_gtv(jour, 'e')
        for champs in ({'derniere_hausse': '2026-10-01'}, {'exception_acceptee': 1}, {'historique_12_mois_confirme': 'oui'}, {'sens': 'inconnu'}):
            with self.subTest(champs=champs), self.assertRaises(ValueError):
                premiere_date_gtv('2026-09-27', 'e', **champs)


class ProduitsContrats(unittest.TestCase):
    def base(self, produit, operateur='enexis', **champs):
        contexte = dict(reseau='distribution', tension_kv=10, grande_connexion=True)
        contexte.update(champs)
        return admissibilite(produit, operateur, **contexte)

    def test_enexis_remplacement_possibilite_pas_offre(self):
        r = self.base('tijdsblok', remplacement=True)
        self.assertFalse(r['refus'])
        self.assertEqual(r['statut'], 'a_confirmer')

    def test_liander_interdit_remplacement(self):
        self.assertEqual(self.base('tijdsblok', 'liander', region='Friesland', remplacement=True)['statut'], 'incompatible')

    def test_liander_region_pas_generale(self):
        r = self.base('tijdsblok', 'liander', region='Amsterdam')
        self.assertTrue(any('Friesland' in m for m in r['manquants']))

    def test_stedin_zeeland_seulement(self):
        self.assertTrue(any('Zeeland' in m for m in self.base('tijdsblok', 'stedin')['manquants']))

    def test_tijdsduur_distribution_refuse(self):
        self.assertEqual(self.base('tijdsduur')['statut'], 'incompatible')

    def test_tijdsduur_tennet_transmission_pas_auto(self):
        r = self.base('tijdsduur', 'tennet', reseau='transmission', tension_kv=150)
        self.assertFalse(r['refus'])
        self.assertTrue(r['manquants'])

    def test_tijdsblok_transmission_refuse(self):
        self.assertEqual(self.base('tijdsblok', 'tennet', reseau='transmission', tension_kv=150)['statut'], 'incompatible')

    def test_tension_seule_ne_deduit_pas_reseau(self):
        self.assertEqual(self.base('fixe', 'liander', tension_kv=150)['statut'], 'a_confirmer')

    def test_reststroom_non_disponible_generale(self):
        for operateur in ('enexis', 'stedin'):
            self.assertTrue(any('Reststroom' in m for m in self.base('volledig_variabel', operateur, congestion=True)['manquants']))

    def test_vvtr_hors_congestion(self):
        self.assertEqual(self.base('volledig_variabel', congestion=False)['statut'], 'incompatible')

    def test_tensions_invalides(self):
        for tension in (True, '10', -10, 0, float('nan'), float('inf')):
            with self.subTest(tension=tension), self.assertRaises(ValueError):
                self.base('fixe', tension_kv=tension)

    def test_cbc_annexe_prioritaire(self):
        self.assertTrue(any('annexe 1' in m and 'jour entier' in m for m in self.base('cbc')['remarques']))


if __name__ == '__main__':
    unittest.main()
