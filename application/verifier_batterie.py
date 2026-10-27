"""Contrôles batterie : formules, bornes, données absentes et rapports, sans réseau."""
import copy
import html
import re
import unittest

import controles
import controles_batterie as batterie
import diagnostic
import rapport_controles
import rapport_nl


def fiche():
    return {'batterie_nominale_dc_kwh': 250., 'batterie_soc_min_pct': 10.,
            'batterie_soc_max_pct': 90., 'batterie_soh_pct': 80.,
            'batterie_utile_dc_annoncee_kwh': 160., 'batterie_c_rate_decharge_max': .5,
            'batterie_puissance_dc_demandee_kw': 125., 'batterie_source': 'Fictief testblad, 27/09/2026'}


class BatterieTest(unittest.TestCase):
    def controle(self, identifiant, dossier):
        return next(r for r in controles.executer_tous(dossier) if r['id'] == identifiant)

    def test_capacite_nominale_reserve_et_sante_sont_multipliees(self):
        r = self.controle('CTRL-BAT-SOC', fiche())
        self.assertEqual(r['statut'], 'constat')
        self.assertAlmostEqual(r['valeurs']['exploitable_dc_kwh'], 160.)
        self.assertEqual(r['nature'], 'controle_coherence')
        self.assertEqual(r['perimetre'], 'courant_continu')
        self.assertEqual(r['source_donnees'], fiche()['batterie_source'])

    def test_capacite_surestimee_declenche_alerte(self):
        r = self.controle('CTRL-BAT-SOC', fiche() | {'batterie_utile_dc_annoncee_kwh': 200.})
        self.assertEqual(r['statut'], 'alerte')
        self.assertAlmostEqual(r['valeurs']['surestimation_dc_kwh'], 40.)

    def test_capacite_inferieure_ou_egale_ne_declenche_pas_alerte(self):
        for annoncee in (0, 120, 160):
            with self.subTest(annoncee=annoncee):
                r = batterie.capacite_exploitable(fiche() | {'batterie_utile_dc_annoncee_kwh': annoncee})
                self.assertEqual(r['statut'], 'constat')

    def test_soh_zero_ne_devient_pas_une_valeur_manquante(self):
        r = self.controle('CTRL-BAT-SOC', fiche() | {'batterie_soh_pct': 0})
        self.assertEqual(r['statut'], 'alerte')
        self.assertEqual(r['valeurs']['exploitable_dc_kwh'], 0)

    def test_aucune_fenetre_ni_sante_par_defaut(self):
        for champ in batterie.BESOINS_SOC:
            with self.subTest(champ=champ):
                d = fiche()
                del d[champ]
                r = self.controle('CTRL-BAT-SOC', d)
                self.assertEqual(r['statut'], 'bloque')
                self.assertIn(champ, [m['champ'] for m in r['manque']])
                self.assertNotIn('valeurs', r)

    def test_bornes_physiques_et_valeurs_non_finies(self):
        cas = {'batterie_nominale_dc_kwh': [0, -1, float('nan'), float('inf'), True, {}, []],
               'batterie_soc_min_pct': [-1, 101, float('nan'), True],
               'batterie_soc_max_pct': [-1, 101, float('inf'), True, 'inconnu'],
               'batterie_soh_pct': [-1, 101, float('nan'), False],
               'batterie_utile_dc_annoncee_kwh': [-1, float('inf'), True]}
        for champ, valeurs in cas.items():
            for valeur in valeurs:
                with self.subTest(champ=champ, valeur=valeur):
                    r = self.controle('CTRL-BAT-SOC', fiche() | {champ: valeur})
                    self.assertEqual(r['statut'], 'bloque')
                    self.assertIn(champ, [m['champ'] for m in r['manque']])

    def test_fenetre_nulle_ou_inversee_bloquee(self):
        for maximum in (5, 10):
            r = batterie.capacite_exploitable(fiche() | {'batterie_soc_max_pct': maximum})
            self.assertEqual(r['statut'], 'bloque')

    def test_reference_absente_ou_non_textuelle_bloquee(self):
        for source in ('', '   ', None, 2026, True):
            for identifiant in ('CTRL-BAT-SOC', 'CTRL-BAT-PUISSANCE'):
                with self.subTest(source=source, identifiant=identifiant):
                    r = self.controle(identifiant, fiche() | {'batterie_source': source})
                    self.assertEqual(r['statut'], 'bloque')

    def test_c_rate_emploie_la_capacite_nominale(self):
        r = self.controle('CTRL-BAT-PUISSANCE', fiche())
        self.assertEqual(r['statut'], 'constat')
        self.assertEqual(r['valeurs']['puissance_max_dc_kw'], 125.)
        self.assertEqual(r['valeurs']['c_rate_demande'], .5)

    def test_demande_plus_puissante_que_fiche(self):
        r = batterie.puissance_decharge(fiche() | {'batterie_puissance_dc_demandee_kw': 150.})
        self.assertEqual(r['statut'], 'alerte')
        self.assertEqual(r['valeurs']['depassement_dc_kw'], 25.)

    def test_c_rate_manquant_ne_devient_pas_1c(self):
        d = fiche()
        del d['batterie_c_rate_decharge_max']
        r = self.controle('CTRL-BAT-PUISSANCE', d)
        self.assertEqual(r['statut'], 'bloque')

    def test_puissance_et_taux_invalides_bloquent(self):
        for champ, valeurs in {'batterie_c_rate_decharge_max': [0, -1, float('nan'), True],
                               'batterie_puissance_dc_demandee_kw': [-1, float('inf'), False]}.items():
            for valeur in valeurs:
                with self.subTest(champ=champ, valeur=valeur):
                    self.assertEqual(self.controle('CTRL-BAT-PUISSANCE', fiche() | {champ: valeur})['statut'], 'bloque')

    def test_depassement_numerique_refuse(self):
        r = batterie.puissance_decharge(fiche() | {'batterie_nominale_dc_kwh': 1e308,
                                                   'batterie_c_rate_decharge_max': 1e308})
        self.assertEqual(r['statut'], 'bloque')

    def test_champs_batterie_facultatifs_dans_diagnostic(self):
        modele = diagnostic.modele()
        for champ in batterie.BESOINS_SOC | batterie.BESOINS_PUISSANCE:
            self.assertIn(champ, modele['valeurs'])
            self.assertFalse(diagnostic.CHAMPS_FICHE[champ][1])
        controles_vides = controles.executer_tous({'profil_kw': [50] * 96, 'gtv_kw': 100})
        self.assertEqual(next(r for r in controles_vides if r['id'] == 'CTRL-MARGE')['statut'], 'constat')

    def test_dossier_reste_identique(self):
        d = fiche()
        avant = copy.deepcopy(d)
        controles.executer_tous(d)
        self.assertEqual(d, avant)

    def test_rapport_fr_et_nl_reprennent_formules_et_limites(self):
        d = fiche() | {'batterie_utile_dc_annoncee_kwh': 200., 'batterie_puissance_dc_demandee_kw': 150.}
        rapport = rapport_controles.composer(d)
        francais = rapport_controles.en_texte(rapport)
        neerlandais = html.unescape(re.sub(r'<[^>]+>', ' ', rapport_nl.en_html(rapport)))
        self.assertIn('160.000 kWh DC', francais)
        self.assertIn('125.000 kW DC', francais)
        self.assertIn('160,0 kWh DC', neerlandais)
        self.assertIn('125,0 kW DC', neerlandais)
        self.assertIn('geen garantie', neerlandais)
        self.assertIn(batterie.SOURCE_PUISSANCE, francais)
        self.assertIn(batterie.SOURCE_CAPACITE, neerlandais)
        for terme in ('capacité', 'puissance', 'évaluable'):
            self.assertNotIn(terme, neerlandais)


if __name__ == '__main__':
    unittest.main()
