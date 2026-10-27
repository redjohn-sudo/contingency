"""Cas limites synthétiques du lecteur Kenter ; aucun appel au fournisseur."""
import copy
import csv
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lecteur_kenter import lire_kenter

INSTANT = int(datetime.fromisoformat('2026-08-31T12:00:00+02:00').timestamp())


def mesure(valeur=1.23456789, instant=INSTANT, origine='Measured', statut='Valid'):
    return {'origin': origine, 'status': statut, 'timestamp': instant, 'value': valeur}


def reponse(mesures=None, pics=None):
    resultat = [{'channelId': '16180', 'Measurements': mesures if mesures is not None else [mesure()]}]
    if pics is not None:
        resultat.append({'channelId': '18160', 'Measurements': pics})
    return resultat


def valeurs(lu):
    return [float(l['puissance_kw']) for l in csv.DictReader(lu['csv'].splitlines())]


class RobustesseKenter(unittest.TestCase):
    def test_preserve_precision_sans_arrondi_six_chiffres(self):
        for valeur in [1.23456789, 123456.789012345, 0.0000000123456789, 0.1]:
            with self.subTest(valeur=valeur):
                self.assertEqual(valeurs(lire_kenter(reponse([mesure(valeur)]))), [valeur * 4])

    def test_refuse_non_finis_et_negatifs_sur_les_deux_canaux(self):
        for valeur in [float('nan'), float('inf'), -float('inf'), -0.01, 10**400]:
            for canal in ['quart', 'pic']:
                with self.subTest(valeur=str(valeur)[:30], canal=canal):
                    contenu = reponse([mesure(valeur)]) if canal == 'quart' else reponse(pics=[mesure(valeur)])
                    with self.assertRaises(ValueError):
                        lire_kenter(contenu)

    def test_refuse_chaines_booleens_null_objets_comme_nombres(self):
        for valeur in [True, False, None, '1.25', [], {}]:
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                lire_kenter(reponse([mesure(valeur)]))

    def test_limite_appliquee_apres_conversion_en_kw(self):
        self.assertEqual(valeurs(lire_kenter(reponse([mesure(2_500_000)]))), [10_000_000])
        with self.assertRaises(ValueError):
            lire_kenter(reponse([mesure(2_500_000.1)]))
        with self.assertRaises(ValueError):
            lire_kenter(reponse(pics=[mesure(10_000_001)]))

    def test_zero_accepte(self):
        self.assertEqual(valeurs(lire_kenter(reponse([mesure(0)]))), [0])

    def test_refuse_timestamp_fractionnaire_meme_si_troncature_donnerait_un_quart(self):
        with self.assertRaisesRegex(ValueError, 'entières'):
            lire_kenter(reponse([mesure(instant=INSTANT + 0.5)]))

    def test_refuse_timestamp_booleen_texte_et_float(self):
        for instant in [True, str(INSTANT), float(INSTANT), None, float('nan')]:
            with self.subTest(instant=instant), self.assertRaises(ValueError):
                lire_kenter(reponse([mesure(instant=instant)]))

    def test_refuse_timestamp_trop_grand(self):
        with self.assertRaises(ValueError):
            lire_kenter(reponse([mesure(instant=10**300)]))

    def test_refuse_quart_non_aligne(self):
        with self.assertRaisesRegex(ValueError, 'quart'):
            lire_kenter(reponse([mesure(instant=INSTANT + 1), mesure(instant=INSTANT + 901)]))

    def test_pic_mensuel_pas_force_au_quart(self):
        lu = lire_kenter(reponse(pics=[mesure(30, instant=INSTANT + 1)]))
        self.assertEqual(lu['kwmax_facture_par_mois'], {'2026-08': 30})

    def test_refuse_invalid_sur_pic_aussi(self):
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            lire_kenter(reponse(pics=[mesure(30, statut='Invalid')]))

    def test_refuse_statut_et_origine_inconnus(self):
        for origine, statut in [('Measured', 'Unexpected'), ('Other', None), ('Measured', None),
                               ('Estimated', 'Valid'), ('Unknown', 'ManualAccepted'), ([], None), ('Measured', [])]:
            with self.subTest(origine=origine, statut=statut), self.assertRaises(ValueError):
                lire_kenter(reponse([mesure(origine=origine, statut=statut)]))

    def test_preserve_estime_calcule_inconnu_et_validation_manuelle(self):
        for origine, statut, qualite in [('Measured', 'ManualAccepted', 'mesure'),
                                         ('Estimated', None, 'estime'), ('Calculated', None, 'calcule'),
                                         ('Unknown', None, 'inconnue')]:
            with self.subTest(origine=origine):
                lu = lire_kenter(reponse([mesure(origine=origine, statut=statut)]))
                self.assertEqual(lu['qualites'][0]['qualite'], qualite)
                self.assertEqual(lu['qualites'][0]['status'], statut)
                self.assertEqual(bool(lu['avertissements']), qualite != 'mesure')

    def test_qualite_absente_reste_inconnue(self):
        lu = lire_kenter(reponse([{'timestamp': INSTANT, 'value': 12}]))
        self.assertEqual(lu['qualites'][0]['qualite'], 'inconnue')
        self.assertTrue(lu['avertissements'])

    def test_qualite_pic_conservee_et_avertie(self):
        lu = lire_kenter(reponse(pics=[mesure(30, origine='Estimated', statut=None)]))
        self.assertEqual(lu['kwmax_qualites_par_mois']['2026-08']['qualite'], 'estime')
        self.assertTrue(lu['avertissements'])

    def test_chevauchements_identiques_comptes(self):
        contenu = reponse([mesure(), mesure(2, INSTANT + 900)], pics=[mesure(40)])
        lu = lire_kenter([contenu, copy.deepcopy(contenu)])
        self.assertEqual(len(valeurs(lu)), 2)
        self.assertEqual(lu['provenance']['doublons_identiques'], {'16180': 2, '18160': 1})
        self.assertEqual(lu['statuts'], {'Measured/Valid': 2})
        self.assertTrue(lu['avertissements'])

    def test_refuse_doublon_quart_avec_qualite_differente(self):
        with self.assertRaisesRegex(ValueError, 'contradictoires'):
            lire_kenter(reponse([mesure(), mesure(statut='ManualAccepted')]))

    def test_refuse_deux_valeurs_du_meme_quart(self):
        with self.assertRaisesRegex(ValueError, 'contradictoires'):
            lire_kenter(reponse([mesure(1), mesure(2)]))

    def test_refuse_ecrasement_silencieux_pic_mensuel(self):
        for autre in [mesure(41), mesure(40, statut='ManualAccepted'), mesure(40, instant=INSTANT + 900)]:
            with self.subTest(autre=autre), self.assertRaisesRegex(ValueError, 'contradictoires'):
                lire_kenter(reponse(pics=[mesure(40), autre]))

    def test_tri_utc_est_explicite(self):
        lu = lire_kenter(reponse([mesure(2, INSTANT + 900), mesure(1)]))
        self.assertEqual(valeurs(lu), [4, 8])
        self.assertTrue(lu['provenance']['tri_utc_effectue'])
        self.assertTrue(any('chronologique' in a for a in lu['avertissements']))

    def test_entree_deja_triee_pas_d_avertissement_de_tri(self):
        lu = lire_kenter(reponse([mesure(), mesure(2, INSTANT + 900)]))
        self.assertFalse(lu['provenance']['tri_utc_effectue'])
        self.assertFalse(lu['avertissements'])

    def test_doublons_ne_masquent_pas_un_trou(self):
        with self.assertRaisesRegex(ValueError, 'consécutives'):
            lire_kenter(reponse([mesure(), mesure(), mesure(2, INSTANT + 1800)]))

    def test_mauvaise_structure_renvoie_valueerror(self):
        for contenu in [None, {}, [None], [1], ['erreur'], [{'channelId': True, 'Measurements': []}],
                        [{'channelId': '16180', 'Measurements': [None]}],
                        [{'channelId': '16180', 'Measurements': [12]}],
                        [{'channelId': '16180', 'Measurements': {}}], b'\xff', 'pas json']:
            with self.subTest(contenu=contenu), self.assertRaises(ValueError):
                lire_kenter(contenu)

    def test_entree_non_modifiee_et_json_equivalent(self):
        contenu = reponse()
        avant = copy.deepcopy(contenu)
        self.assertEqual(lire_kenter(contenu), lire_kenter(json.dumps(contenu)))
        self.assertEqual(contenu, avant)

    def test_changement_heure_utc_continu(self):
        debut = int(datetime.fromisoformat('2026-10-25T02:45:00+02:00').timestamp())
        lu = lire_kenter(reponse([mesure(1, debut), mesure(2, debut + 900)]))
        horaires = [q['fin_intervalle'] for q in lu['qualites']]
        self.assertEqual(horaires, ['2026-10-25T02:45:00+02:00', '2026-10-25T02:00:00+01:00'])
        self.assertFalse(lu['provenance']['tri_utc_effectue'])


if __name__ == '__main__':
    unittest.main()
