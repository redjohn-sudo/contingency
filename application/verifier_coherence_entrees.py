"""Entrées invalides, calculs finis et rendu des blocages, sans réseau."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coherence_mesures as cm
import catalogue
import controles
import rapport_controles
import rapport_nl
import verifier_periode_exacte as exemples


def dossier():
    return {'profil_brut': [10.] * 96, 'unite_profil': 'kw',
            'profil_horodatages': exemples.periode(),
            'periode_facture_debut': '2026-09-01', 'periode_facture_fin': '2026-09-01',
            'kwmax_facture': 10., 'kwh_facture': 240.,
            'mesure_au_point_de_livraison': True, 'gtv_kw': 20.}


class EntreesCoherence(unittest.TestCase):
    def bloque_fini(self, resultat, raison=None):
        self.assertEqual(resultat['statut'], 'bloque')
        if raison:
            self.assertEqual(resultat['valeurs']['raison'], raison)
        json.dumps(resultat, allow_nan=False)
        phrase, _ = rapport_nl._zin(resultat)
        self.assertTrue(phrase)
        self.assertNotIn('Unité', phrase)
        return resultat

    def test_kwmax_invalide(self):
        for valeur in (False, True, -1, '', [], {}, float('inf'), float('nan'), 10**400):
            with self.subTest(valeur=repr(valeur)):
                self.bloque_fini(cm.controler_unite([10.], 'kw', valeur), 'kwmax_invalide')

    def test_kwh_invalide(self):
        for valeur in (False, True, -1, '', [], {}, float('inf'), float('nan'), 10**400):
            with self.subTest(valeur=repr(valeur)):
                self.bloque_fini(cm.controler_energie([10.], valeur), 'kwh_invalide')

    def test_profil_invalide(self):
        for profil in (None, [], {}, '10', [False], [-1], ['10'], [float('inf')], [float('nan')], [10**400]):
            with self.subTest(profil=repr(profil)):
                self.bloque_fini(cm.controler_unite(profil, 'kw', 10), 'profil_invalide')
                self.bloque_fini(cm.controler_energie(profil, 10), 'profil_invalide')

    def test_conversion_deborde(self):
        self.bloque_fini(cm.controler_unite([1e308], 'kwh_par_quart', 10), 'profil_invalide')
        with self.assertRaises(ValueError):
            cm.en_kw([1e308], 'kwh_par_quart')

    def test_somme_et_ecart_debordent(self):
        self.bloque_fini(cm.controler_energie([1e308] * 96, 10), 'calcul_non_fini')
        self.bloque_fini(cm.controler_energie([10], 1e-320), 'calcul_non_fini')
        self.bloque_fini(cm.controler_unite([10], 'kw', 1e-320), 'calcul_non_fini')
        self.bloque_fini(cm.controler_unite([1.79e308], 'kw', 1.79e308, False), 'calcul_non_fini')

    def test_facture_nulle_profil_positif(self):
        for pointe in (.01, 10):
            self.bloque_fini(cm.controler_unite([pointe], 'kw', 0), 'kwmax_nul')
        resultat = self.bloque_fini(cm.controler_energie([10], 0), 'kwh_nul')
        self.assertIsNone(resultat['valeurs']['ecart'])

    def test_zero_contre_zero_energie_coherente_unite_indecidable(self):
        self.bloque_fini(cm.controler_unite([0] * 96, 'kw', 0), 'pointes_nulles')
        energie = cm.controler_energie([0] * 96, 0)
        self.assertEqual(energie['statut'], 'constat')
        self.assertEqual(energie['valeurs']['ecart'], 0)
        json.dumps(energie, allow_nan=False)

    def test_profil_nul_ne_confirme_pas_unite_sur_arrondi(self):
        for facture in (.01, 1., 10.):
            self.bloque_fini(cm.controler_unite([0] * 96, 'kw', facture), 'pointe_nulle')

    def test_position_compteur_stricte(self):
        for valeur in ('false', 'oui', 0, 1, [], {}):
            self.bloque_fini(cm.signaler_correction_pertes(valeur), 'point_livraison_invalide')
            self.bloque_fini(cm.controler_unite([10], 'kw', 10, valeur), 'point_livraison_invalide')

    def test_mois_mal_forme_ne_plante_pas(self):
        for mois in ('2026-13', '2026', '2026-09-tronque', '0000-09', '', False, 0, [], {}, '2026-9'):
            d = dossier()
            del d['periode_facture_debut'], d['periode_facture_fin']
            d['mois_facture'] = mois
            resultat = cm.executer(d)
            self.bloque_fini(resultat[0], 'periode_invalide')
            self.assertFalse(cm.puissance_fiable(resultat))

    def test_borne_partielle_ne_retombe_pas_sur_le_mois(self):
        for cle in ('periode_facture_debut', 'periode_facture_fin'):
            d = dossier()
            del d[cle]
            d['mois_facture'] = '2026-09'
            self.assertIsNone(cm.periode_du_dossier(d)[0 if cle.endswith('debut') else 1])
            self.bloque_fini(cm.executer(d)[0])

    def test_mois_valide_et_annee_bissextile(self):
        self.assertEqual(cm.periode_du_dossier({'mois_facture': '2024-02'}), ('2024-02-01', '2024-02-29'))
        self.assertEqual(cm.periode_du_dossier({'mois_facture': '2026-02'}), ('2026-02-01', '2026-02-28'))

    def test_faux_type_profil_ne_plante_pas(self):
        for profil in (False, 10, {}, [], 'abc'):
            d = dossier(); d['profil_brut'] = profil
            d['profil_kw'] = [10] * 96
            resultat = cm.executer(d)
            self.assertFalse(cm.puissance_fiable(resultat))
            json.dumps(resultat, allow_nan=False)

    def test_unite_fausse_ne_valide_pas_energie(self):
        d = dossier(); d['unite_profil'] = 'kwh_par_quart'; d['kwh_facture'] = 960
        resultat = cm.executer(d)
        energie = next(r for r in resultat if r['id'] == 'COH-ENERGIE')
        self.bloque_fini(energie, 'unite_non_confirmee')

    def test_rapport_fr_nl_sur_entrees_invalides(self):
        for cle, valeur in [('kwmax_facture', 0), ('kwmax_facture', float('inf')),
                            ('kwh_facture', float('nan')), ('kwh_facture', 0),
                            ('mesure_au_point_de_livraison', 'false'),
                            ('profil_brut', [float('inf')] * 96),
                            ('profil_brut', False)]:
            d = dossier(); d[cle] = valeur
            resultats = controles.executer_tous(d)
            json.dumps(resultats, allow_nan=False)
            rapport = rapport_controles.composer(d, resultats)
            json.dumps(rapport, allow_nan=False)
            fr = rapport_controles.en_html(rapport)
            nl = rapport_nl.en_html(rapport)
            unite = next(r for r in resultats if r['id'] == 'COH-UNITE')
            if unite['statut'] == 'bloque':
                self.assertIn('MESURES NON VÉRIFIÉES', rapport_controles.en_texte(rapport))
                self.assertIn('Metingen niet bevestigd', nl)
            else:
                energie = next(r for r in resultats if r['id'] == 'COH-ENERGIE')
                self.assertEqual(energie['statut'], 'bloque')
                self.assertIn(rapport_nl._zin(energie)[0], nl)
            self.assertNotIn('Énergie', nl)
            self.assertTrue(fr)

    def test_dossier_valide_reste_fiable(self):
        resultat = cm.executer(dossier())
        self.assertTrue(cm.puissance_fiable(resultat))
        self.assertTrue(all(r['statut'] == 'constat' for r in resultat))
        self.assertEqual(len(resultat), 4)

    def test_version_catalogue_ne_reprend_pas_un_cache_ancien(self):
        with tempfile.TemporaryDirectory() as rep:
            chemin = Path(rep) / 'catalogue.json'
            chemin.write_text(json.dumps({'empreinte_source': 'ancienne', 'genere_le': '2020-01-01', 'nombre_entrees': 999}))
            with patch.object(rapport_controles, 'CATALOGUE_JSON', chemin):
                version = rapport_controles._version_catalogue()
            self.assertEqual(version['empreinte'], catalogue.empreinte())
            self.assertEqual(version['nombre_entrees'], str(len(catalogue.charger())))
            self.assertEqual(version['genere_le'], 'inconnu')

    def test_version_catalogue_reprend_date_cache_correspondant(self):
        with tempfile.TemporaryDirectory() as rep:
            chemin = Path(rep) / 'catalogue.json'
            chemin.write_text(json.dumps({'empreinte_source': catalogue.empreinte(), 'genere_le': '2026-09-27', 'nombre_entrees': 999}))
            with patch.object(rapport_controles, 'CATALOGUE_JSON', chemin):
                version = rapport_controles._version_catalogue()
            self.assertEqual(version['genere_le'], '2026-09-27')
            self.assertEqual(version['nombre_entrees'], str(len(catalogue.charger())))


if __name__ == '__main__':
    unittest.main()
