"""Puissances contractuelles invalides, zéro et rendus, sans réseau."""
import json
import unittest

import controles
import controles_contrat as contrat
import rapport_controles
import rapport_nl
import verifier_coherence_entrees as exemples


INVALIDES = (False, True, -1, '400', '', [], {}, float('nan'), float('inf'), -float('inf'), 10**400)


class EntreesContrat(unittest.TestCase):
    def bloque(self, resultat):
        self.assertEqual(resultat['statut'], 'bloque', resultat)
        json.dumps(resultat, allow_nan=False)

    def test_marge_et_depassements_refusent_les_gtv_invalides(self):
        for valeur in INVALIDES:
            with self.subTest(valeur=repr(valeur)):
                self.bloque(contrat.marge_contractuelle([10.], valeur))
                self.bloque(contrat.depassements_par_bloc([10.], valeur))

    def test_capacite_de_raccordement_invalide(self):
        for valeur in INVALIDES:
            with self.subTest(valeur=repr(valeur)):
                self.bloque(contrat.gtv_maximal(valeur))

    def test_declarations_invalides(self):
        for valeur in INVALIDES:
            with self.subTest(valeur=repr(valeur)):
                self.bloque(contrat.ecart_gtv_declare(valeur, 10.))
                self.bloque(contrat.ecart_gtv_declare(10., valeur))

    def test_profils_directs_invalides(self):
        for profil in (False, True, 10, '10', {}, ['10'], [-1], [False], [float('nan')], [float('inf')], [10**400]):
            with self.subTest(profil=repr(profil)):
                self.bloque(contrat.marge_contractuelle(profil, 10.))
                self.bloque(contrat.depassements_par_bloc(profil, 10.))

    def test_gtv_zero_est_une_valeur_et_non_une_donnee_absente(self):
        for profil in ([0.] * 96, [10.] * 96):
            marge = contrat.marge_contractuelle(profil, 0.)
            self.assertEqual(marge['statut'], 'constat' if max(profil) == 0 else 'alerte')
            self.assertIsNone(marge['valeurs']['taux_utilisation'])
            self.assertEqual(marge['valeurs']['marge_kw'], -max(profil))
            nl, _ = rapport_nl._zin(marge)
            self.assertIn('geen gebruikspercentage gedefinieerd', nl)
            self.assertNotIn('nan', nl.lower())
        self.assertEqual(contrat.gtv_maximal(0.)['valeurs']['gtv_max_kw'], 0.)
        self.assertEqual(contrat.ecart_gtv_declare(10., 0.)['valeurs']['gtv_opposable_kw'], 0.)

    def test_ratio_qui_deborde_est_bloque(self):
        for valeur in (1e-320, 1e-307):
            resultat = contrat.marge_contractuelle([100.], valeur)
            self.bloque(resultat)
            self.assertEqual(resultat['valeurs']['raison'], 'calcul_contrat_non_fini')
            self.assertIn('numerieke bereik', rapport_nl._zin(resultat)[0])

    def test_registre_bloque_tous_les_consommateurs_de_la_valeur(self):
        for champ in ('gtv_kw', 'gtv_declare_kw', 'capacite_aansluiting_kva'):
            for valeur in INVALIDES:
                with self.subTest(champ=champ, valeur=repr(valeur)):
                    dossier = exemples.dossier()
                    dossier.update(gtv_declare_kw=20., capacite_aansluiting_kva=30.,
                                   tarif_kw_mois_eur=2., mois_factures=12)
                    dossier[champ] = valeur
                    resultats = controles.executer_tous(dossier)
                    for resultat in resultats:
                        entree = controles.REGISTRE.get(resultat['id'])
                        if entree and champ in entree['besoins']:
                            self.bloque(resultat)
                    # Une donnée invalide ne bloque pas la cohérence de la facture.
                    self.assertEqual(next(r for r in resultats if r['id'] == 'COH-UNITE')['statut'], 'constat')
                    rapport = rapport_controles.composer(dossier, resultats)
                    json.dumps(rapport, allow_nan=False)
                    self.assertTrue(rapport_controles.en_texte(rapport))
                    self.assertTrue(rapport_controles.en_html(rapport))
                    self.assertTrue(rapport_nl.en_html(rapport))

    def test_registre_sur_profil_kw_sans_brut(self):
        for profil in (False, '10', {}, (), [float('nan')], [False], ['10']):
            with self.subTest(profil=repr(profil)):
                dossier = {'profil_kw': profil, 'gtv_kw': 10.}
                resultats = controles.executer_tous(dossier)
                for resultat in resultats:
                    if 'profil_kw' in controles.REGISTRE[resultat['id']]['besoins']:
                        self.bloque(resultat)
                rapport = rapport_controles.composer(dossier, resultats)
                json.dumps(rapport, allow_nan=False)
                self.assertTrue(rapport_nl.en_html(rapport))

    def test_rapport_complet_gtv_zero(self):
        dossier = exemples.dossier(); dossier['gtv_kw'] = 0.
        rapport = rapport_controles.composer(dossier)
        json.dumps(rapport, allow_nan=False)
        self.assertIn('geen gebruikspercentage gedefinieerd', rapport_nl.en_html(rapport))

    def test_direction_invalide_est_bloquee_dans_le_registre(self):
        for direction in ('autre', None, False, [], {}):
            with self.subTest(direction=repr(direction)):
                dossier = {'capacite_aansluiting_kva': 10., 'direction': direction}
                resultat = next(r for r in controles.executer_tous(dossier) if r['id'] == 'CTRL-GTV-MAX')
                self.bloque(resultat)
                self.assertEqual(resultat['valeurs']['raison'], 'direction_invalide')
                self.assertIn('Ongeldige transportrichting', rapport_nl._zin(resultat)[0])
        self.assertEqual(rapport_nl._waarde('direction', 'soutirage'), 'afname')
        self.assertEqual(rapport_nl._waarde('direction', 'injection'), 'invoeding')

    def test_valeurs_valides_et_tuple_restent_acceptes(self):
        self.assertEqual(contrat.marge_contractuelle((10., 20.), 30.)['valeurs']['marge_kw'], 10.)
        self.assertEqual(contrat.gtv_maximal(100., 'injection')['valeurs']['gtv_max_kw'], 100.)
        self.assertEqual(contrat.gtv_maximal(100., 'soutirage')['valeurs']['gtv_max_kw'], 85.)
        self.assertEqual(contrat.ecart_gtv_declare(30., 20.)['valeurs']['ecart_kw'], 10.)

    def test_prix_et_mois_invalides_ne_produisent_pas_un_cout(self):
        for champ in ('tarif_kw_mois_eur', 'mois_factures'):
            for valeur in INVALIDES:
                with self.subTest(champ=champ, valeur=repr(valeur)):
                    d = {'profil_kw': [100.] * 96, 'gtv_kw': 200., 'tarif_kw_mois_eur': 2., 'mois_factures': 12}
                    d[champ] = valeur
                    direct = controles.capacite_dormante(d)
                    self.bloque(direct)
                    self.assertNotIn('cout_eur', direct.get('valeurs', {}))
                    r = rapport_controles.composer(d)
                    cout = next(c for c in r['controles'] if c['id'] == 'CTRL-CAPACITE-DORMANTE')
                    self.bloque(cout)
                    json.dumps(r, allow_nan=False)
                    self.assertTrue(rapport_nl.en_html(r))

    def test_cout_qui_deborde_est_bloque(self):
        for champ in ('tarif_kw_mois_eur', 'mois_factures'):
            d = {'profil_kw': [100.] * 96, 'gtv_kw': 200., 'tarif_kw_mois_eur': 2., 'mois_factures': 12}
            d[champ] = 1e308
            r = controles.capacite_dormante(d)
            self.bloque(r)
            self.assertEqual(r['valeurs']['raison'], 'calcul_contrat_non_fini')

    def test_tarif_zero_mois_zero_et_prorata_restent_explicitement_possibles(self):
        for tarif, mois, cout in ((0., 12, 0.), (2., 0., 0.), (2., .5, 100.), (2., 12., 2400.)):
            r = controles.capacite_dormante({'profil_kw': [100.] * 96, 'gtv_kw': 200.,
                                            'tarif_kw_mois_eur': tarif, 'mois_factures': mois})
            self.assertEqual(r['valeurs']['cout_eur'], cout)
            self.assertTrue(r['valeurs']['hypothese_gtv_et_tarif_constants'])
            self.assertIn('pas une économie garantie', r['constat'])
            self.assertIn('geen gegarandeerde besparing', rapport_nl._zin(r)[0])

    def test_consequences_ne_generalisent_pas_le_tarif_mensuel_ou_irreversibilite(self):
        marge = contrat.marge_contractuelle([100.], 200.)
        self.assertIn('hebdomadaires', marge['consequence_contractuelle'])
        self.assertIn('weekmaxima', rapport_nl._zin(marge)[1])
        dormant = controles.capacite_dormante({'profil_kw': [100.], 'gtv_kw': 200.,
                                              'tarif_kw_mois_eur': 2., 'mois_factures': 12})
        self.assertNotIn('immédiate', dormant['consequence_contractuelle'])
        self.assertNotIn('niet terug te draaien', rapport_nl._zin(dormant)[1])
        self.assertIn('beschikbare transportcapaciteit', rapport_nl._zin(dormant)[1])


if __name__ == '__main__':
    unittest.main()
