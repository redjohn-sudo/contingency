"""La correction retenue contre la facture suit tous les contrôles du profil."""
from copy import deepcopy
import json
import unittest

import coherence_mesures as cm
import controles
import rapport_controles
import rapport_nl
import verifier_coherence_entrees as exemples


def dossier_pertes():
    dossier = exemples.dossier()
    dossier.update(profil_brut=[400.] * 96, kwmax_facture=405.6,
                   kwh_facture=9734.4, mesure_au_point_de_livraison=False,
                   gtv_kw=405.)
    return dossier


class PropagationPertes(unittest.TestCase):
    def resultats(self, dossier=None):
        return {r['id']: r for r in controles.executer_tous(dossier or dossier_pertes())}

    def test_facteur_explicite_dans_la_correspondance_facture(self):
        unite = self.resultats()['COH-UNITE']['valeurs']
        self.assertEqual(unite['facteur_correction_pertes'], 1.014)
        self.assertEqual(unite['pointe_kw'], 400.)
        self.assertAlmostEqual(unite['pointe_comparee'], 405.6)

    def test_marge_et_quarts_depasses_prennent_les_pertes(self):
        marge = self.resultats()['CTRL-MARGE']
        self.assertEqual(marge['statut'], 'alerte')
        self.assertAlmostEqual(marge['valeurs']['pointe_kw'], 405.6)
        self.assertAlmostEqual(marge['valeurs']['marge_kw'], -.6)
        self.assertEqual(marge['valeurs']['nombre_quarts_en_depassement'], 96)

    def test_energie_reprend_exactement_le_meme_facteur(self):
        energie = self.resultats()['COH-ENERGIE']
        self.assertEqual(energie['statut'], 'constat')
        self.assertAlmostEqual(energie['valeurs']['energie_profil_kwh'], 9734.4)
        self.assertAlmostEqual(energie['valeurs']['ecart'], 0.)
        self.assertEqual(energie['valeurs']['facteur_correction_pertes'], 1.014)

    def test_limite_hors_bloc_recoit_aussi_le_profil_corrige(self):
        dossier = dossier_pertes()
        dossier.update(type_transportrecht='tijdsblok', blocs_transport='00:00-06:00',
                       gtv_hors_bloc_kw=405.)
        transport = self.resultats(dossier)['CTRL-TRANSPORTRECHT']
        self.assertEqual(transport['statut'], 'alerte')
        self.assertEqual(transport['valeurs']['quarts_hors_bloc_au_dessus'], 72)
        self.assertAlmostEqual(transport['valeurs']['pointe_hors_bloc_kw'], 405.6)

    def test_export_deja_corrige_ne_recoit_pas_deux_fois_les_pertes(self):
        dossier = dossier_pertes()
        dossier['profil_brut'] = [405.6] * 96
        resultat = self.resultats(dossier)
        self.assertEqual(resultat['COH-UNITE']['valeurs']['facteur_correction_pertes'], 1.)
        self.assertAlmostEqual(resultat['CTRL-MARGE']['valeurs']['pointe_kw'], 405.6)
        self.assertAlmostEqual(resultat['COH-ENERGIE']['valeurs']['energie_profil_kwh'], 9734.4)

    def test_conversion_kwh_et_correction_une_seule_fois(self):
        dossier = dossier_pertes()
        dossier.update(profil_brut=[100.] * 96, unite_profil='kwh_par_quart')
        resultat = self.resultats(dossier)
        self.assertAlmostEqual(resultat['CTRL-MARGE']['valeurs']['pointe_kw'], 405.6)
        self.assertAlmostEqual(resultat['COH-ENERGIE']['valeurs']['energie_profil_kwh'], 9734.4)

    def test_profil_fourni_et_dossier_non_modifies(self):
        dossier = dossier_pertes()
        dossier['profil_kw'] = [1.] * 96  # Ancien dérivé : le brut vérifié prime.
        original = deepcopy(dossier)
        resultat = self.resultats(dossier)
        self.assertEqual(dossier, original)
        self.assertAlmostEqual(resultat['CTRL-MARGE']['valeurs']['pointe_kw'], 405.6)

    def test_mesure_au_point_de_livraison_n_invente_pas_de_correction(self):
        dossier = dossier_pertes()
        dossier.update(mesure_au_point_de_livraison=True, kwmax_facture=400., kwh_facture=9600.)
        resultat = self.resultats(dossier)
        self.assertEqual(resultat['COH-UNITE']['valeurs']['facteur_correction_pertes'], 1.)
        self.assertEqual(resultat['CTRL-MARGE']['valeurs']['marge_kw'], 5.)

    def test_export_brut_correspondant_reste_brut_meme_hors_livraison(self):
        dossier = dossier_pertes()
        dossier.update(kwmax_facture=400., kwh_facture=9600.)
        resultat = self.resultats(dossier)
        self.assertEqual(resultat['COH-UNITE']['valeurs']['facteur_correction_pertes'], 1.)
        self.assertEqual(resultat['CTRL-MARGE']['valeurs']['marge_kw'], 5.)
        rapport = rapport_controles.composer(dossier, list(resultat.values()))
        self.assertNotIn('Pointe brute', rapport_controles.en_texte(rapport))
        self.assertNotIn('Piek vóór correctie', rapport_nl.en_html(rapport))

    def test_ecart_non_explique_reste_bloque(self):
        dossier = dossier_pertes()
        dossier['kwmax_facture'] = 450.
        resultat = self.resultats(dossier)
        self.assertEqual(resultat['COH-UNITE']['statut'], 'bloque')
        self.assertEqual(resultat['CTRL-MARGE']['statut'], 'bloque')
        self.assertEqual(resultat['COH-ENERGIE']['statut'], 'bloque')

    def test_deux_candidats_dans_la_tolerance_ne_sont_pas_departages_par_ordre(self):
        for facture in (402.8, 403., 404.):
            with self.subTest(facture=facture):
                dossier = dossier_pertes(); dossier['kwmax_facture'] = facture
                resultats = self.resultats(dossier)
                unite = resultats['COH-UNITE']
                self.assertEqual(unite['statut'], 'bloque')
                self.assertEqual(unite['valeurs']['raison'], 'correction_pertes_ambigue')
                self.assertNotIn('facteur_correction_pertes', unite['valeurs'])
                self.assertEqual(unite['valeurs']['facteurs_possibles'], [1., 1.014])
                self.assertEqual(resultats['CTRL-MARGE']['statut'], 'bloque')
                self.assertEqual(resultats['COH-ENERGIE']['statut'], 'bloque')
                with self.assertRaises(ValueError):
                    cm.profil_comparable(dossier['profil_brut'], 'kw', unite)

    def test_ambiguite_petites_puissances_meme_si_une_pointe_est_exacte(self):
        for facture in (10., 10.14):
            unite = cm.controler_unite([10.], 'kw', facture, False)
            self.assertEqual(unite['statut'], 'bloque')
            self.assertEqual(unite['valeurs']['raison'], 'correction_pertes_ambigue')

    def test_rapport_ambigu_explique_le_blocage_fr_nl(self):
        dossier = dossier_pertes(); dossier['kwmax_facture'] = 404.
        rapport = rapport_controles.composer(dossier)
        json.dumps(rapport, allow_nan=False)
        self.assertIn('Correction de pertes indéterminable', rapport_controles.en_texte(rapport))
        nl = rapport_nl.en_html(rapport)
        self.assertIn('Verliescorrectie niet vast te stellen', nl)
        self.assertIn('handmatige vergelijking nodig', nl)
        self.assertNotIn('Ruimte binnen het huidige contract:', nl)

    def test_profil_comparable_refuse_un_facteur_absent_ou_non_confirme(self):
        for unite in ({'id': 'COH-UNITE', 'statut': 'bloque'},
                      {'id': 'COH-UNITE', 'statut': 'constat'},
                      {'id': 'COH-UNITE', 'statut': 'constat', 'valeurs': {'facteur_correction_pertes': True}},
                      {'id': 'COH-UNITE', 'statut': 'constat', 'valeurs': {'facteur_correction_pertes': 2.}}):
            with self.subTest(unite=unite), self.assertRaises(ValueError):
                cm.profil_comparable([400.], 'kw', unite)

    def test_rapports_fr_nl_distinguent_brut_et_compare(self):
        rapport = rapport_controles.composer(dossier_pertes())
        json.dumps(rapport, allow_nan=False)
        self.assertEqual(rapport['profil']['pointe_brute_kw'], 400.)
        self.assertEqual(rapport['profil']['pointe_kw'], 405.6)
        self.assertEqual(rapport['profil']['facteur_correction_pertes'], 1.014)
        for contenu in (rapport_controles.en_texte(rapport), rapport_controles.en_html(rapport)):
            self.assertIn('Pointe brute 400.0 kW', contenu)
            self.assertIn('+1.4 %', contenu)
            self.assertIn('taux convenu reste à vérifier', contenu)
        nl = rapport_nl.en_html(rapport)
        self.assertIn('Piek vóór correctie: 400,0 kW', nl)
        self.assertIn('+1,4 %', nl)
        self.assertIn('405,6', nl)
        self.assertIn('MS-aansluitingen met LS-meting', nl)
        self.assertIn('het overeengekomen percentage moet nog worden gecontroleerd', nl)
        self.assertNotIn('Pointe brute', nl)


if __name__ == '__main__':
    unittest.main()
