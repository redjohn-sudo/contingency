"""Réserves simultanées, pas de compensation ni revenu implicite."""
import copy
import html
import re
import unittest

import controles
import controles_batterie as batterie
import couverture
import diagnostic
import rapport_controles
import rapport_nl
from verifier_batterie import fiche


def service(nom='Peak shaving', decharge_kw=40, charge_kw=10, decharge_kwh=30, charge_kwh=20):
    return {'nom': nom, 'source': 'Fictieve reservering, 27/09/2026',
            'puissance_decharge_dc_kw': decharge_kw, 'puissance_charge_dc_kw': charge_kw,
            'energie_decharge_dc_kwh': decharge_kwh, 'energie_charge_dc_kwh': charge_kwh}


def dossier():
    return fiche() | {'batterie_soc_instant_pct': 50, 'batterie_instant_engagements': '2026-09-27T12:00:00+02:00',
                      'batterie_nature_etat': 'hypothese', 'batterie_source_etat': 'Fictief scenario, geen meting',
                      'batterie_charge_max_dc_kw': 100, 'batterie_decharge_max_dc_kw': 125,
                      'batterie_engagements_simultanes': [service(), service('Reserve', 60, 20, 40, 30)]}


class EngagementsBatterieTest(unittest.TestCase):
    def controle(self, d):
        return next(r for r in controles.executer_tous(d) if r['id'] == 'CTRL-BAT-ENGAGEMENTS')

    def test_reserves_tiennent_dans_quatre_budgets(self):
        r = self.controle(dossier())
        self.assertEqual(r['statut'], 'constat')
        self.assertEqual(r['nature'], 'regle_conception_interne')
        self.assertEqual(r['valeurs']['engage'], dict(zip(batterie.AXES_ENGAGEMENTS, [100, 30, 70, 50])))
        self.assertEqual(r['valeurs']['disponible'], dict(zip(batterie.AXES_ENGAGEMENTS, [125, 100, 80, 80])))
        self.assertEqual(r['valeurs']['axes_depasses'], [])
        self.assertEqual(r['valeurs']['nombre_services'], 2)

    def test_chaque_budget_peut_declencher_seul(self):
        for axe, valeur in zip(batterie.AXES_ENGAGEMENTS, [126, 101, 81, 81]):
            with self.subTest(axe=axe):
                s = service(decharge_kw=0, charge_kw=0, decharge_kwh=0, charge_kwh=0) | {axe: valeur}
                r = self.controle(dossier() | {'batterie_engagements_simultanes': [s]})
                self.assertEqual(r['statut'], 'alerte')
                self.assertEqual(r['valeurs']['axes_depasses'], [axe])
                self.assertEqual(r['valeurs']['deficits'][axe], 1)

    def test_pas_de_compensation_charge_decharge(self):
        r = self.controle(dossier() | {'batterie_engagements_simultanes': [service(decharge_kw=150, charge_kw=150)]})
        self.assertEqual(r['statut'], 'alerte')
        self.assertIn('puissance_decharge_dc_kw', r['valeurs']['axes_depasses'])
        self.assertIn('puissance_charge_dc_kw', r['valeurs']['axes_depasses'])

    def test_capacite_exploitable_ne_remplace_pas_etat_actuel(self):
        r = self.controle(dossier() | {'batterie_soc_instant_pct': 10})
        self.assertEqual(r['statut'], 'alerte')
        self.assertEqual(r['valeurs']['exploitable_dc_kwh'], 160)
        self.assertEqual(r['valeurs']['disponible']['energie_decharge_dc_kwh'], 0)
        self.assertEqual(r['valeurs']['disponible']['energie_charge_dc_kwh'], 160)

    def test_borne_exacte_egale_acceptee(self):
        r = self.controle(dossier() | {'batterie_engagements_simultanes': [service('Exact', 125, 100, 80, 80)]})
        self.assertEqual(r['statut'], 'constat')

    def test_etat_hors_fenetre_refuse(self):
        for soc in (9, 91, float('nan'), True):
            self.assertEqual(self.controle(dossier() | {'batterie_soc_instant_pct': soc})['statut'], 'bloque')

    def test_aucun_champ_requis_implicite(self):
        for champ in batterie.BESOINS_ENGAGEMENTS:
            with self.subTest(champ=champ):
                d = dossier()
                del d[champ]
                r = self.controle(d)
                self.assertEqual(r['statut'], 'bloque')
                self.assertIn(champ, [m['champ'] for m in r['manque']])

    def test_services_incomplets_invalides_ou_dupliques_refuses(self):
        manque = service()
        del manque['energie_charge_dc_kwh']
        for services in ([], None, [None], [manque], [service(), service()], [service() | {'source': ''}],
                         [service() | {'nom': ''}], [service(decharge_kw=-1)],
                         [service(charge_kw=float('inf'))], [service(decharge_kwh=True)],
                         [service(charge_kwh=float('nan'))]):
            with self.subTest(services=services):
                r = self.controle(dossier() | {'batterie_engagements_simultanes': services})
                self.assertEqual(r['statut'], 'bloque')

    def test_somme_numerique_hors_domaine_refusee(self):
        d = dossier() | {'batterie_engagements_simultanes': [service('A', 1e308), service('B', 1e308)]}
        self.assertEqual(self.controle(d)['statut'], 'bloque')

    def test_instant_explicitement_date_avec_fuseau(self):
        for instant in ('2026-09-27', '2026-09-27T12:00:00', 'inconnu', True):
            with self.subTest(instant=instant):
                r = self.controle(dossier() | {'batterie_instant_engagements': instant})
                self.assertEqual(r['statut'], 'bloque')
        self.assertEqual(self.controle(dossier() | {'batterie_instant_engagements': '2026-09-27T10:00:00Z'})['statut'], 'constat')

    def test_mesure_et_hypothese_explicitement_distinguees(self):
        for nature in ('mesure', 'hypothese'):
            r = self.controle(dossier() | {'batterie_nature_etat': nature})
            self.assertEqual(r['valeurs']['nature_etat'], nature)
        self.assertEqual(self.controle(dossier() | {'batterie_nature_etat': 'certain'})['statut'], 'bloque')

    def test_sources_et_entree_non_modifiees(self):
        d = dossier()
        avant = copy.deepcopy(d)
        r = self.controle(d)
        self.assertEqual(d, avant)
        self.assertEqual(r['valeurs']['services'][0]['source'], d['batterie_engagements_simultanes'][0]['source'])
        self.assertIn(d['batterie_source_etat'], r['source_donnees'])

    def test_limites_et_source_etat_invalides_refusees(self):
        for champ, valeurs in {'batterie_charge_max_dc_kw': [-1, float('nan'), True],
                               'batterie_decharge_max_dc_kw': [-1, float('inf'), False],
                               'batterie_source_etat': ['', '  ', None, 123]}.items():
            for valeur in valeurs:
                with self.subTest(champ=champ, valeur=valeur):
                    self.assertEqual(self.controle(dossier() | {champ: valeur})['statut'], 'bloque')

    def test_reserve_nulle_et_batterie_indisponible_ne_sont_pas_absences(self):
        d = dossier() | {'batterie_engagements_simultanes': [service('Nul', 0, 0, 0, 0)],
                          'batterie_charge_max_dc_kw': 0, 'batterie_decharge_max_dc_kw': 0,
                          'batterie_soh_pct': 0}
        self.assertEqual(self.controle(d)['statut'], 'constat')

    def test_fiche_diagnostic_contient_champs_facultatifs(self):
        for champ in batterie.BESOINS_ENGAGEMENTS:
            self.assertIn(champ, diagnostic.modele()['valeurs'])
            self.assertFalse(diagnostic.CHAMPS_FICHE[champ][1])

    def test_regle_interne_ne_gonfle_pas_couverture_juridique(self):
        bilan = couverture.etablir()
        self.assertIn('ECO-010', bilan['par_categorie']['conception'])
        self.assertNotIn('ECO-010', bilan['par_categorie']['testee'])
        self.assertIn('ECO-010', bilan['conception_testees'])
        self.assertEqual(bilan['total_testees'], bilan['testees'] + len(bilan['conception_testees']))
        self.assertEqual(sum(map(len, bilan['par_categorie'].values())), bilan['total'])
        self.assertIn('sans portée juridique', couverture.phrase(bilan))

    def test_rapports_expliquent_instant_et_limites(self):
        rapport = rapport_controles.composer(dossier())
        francais = rapport_controles.en_texte(rapport)
        neerlandais = html.unescape(re.sub(r'<[^>]+>', ' ', rapport_nl.en_html(rapport)))
        self.assertIn('100.000/125.000 kW DC', francais)
        self.assertIn('70.000/80.000 kWh DC', francais)
        self.assertIn('100,0/125,0 kW DC', neerlandais)
        self.assertIn('70,0/80,0 kWh DC', neerlandais)
        self.assertIn('zonder juridische werking', neerlandais)
        self.assertIn('aanname', neerlandais)
        for cle in batterie.BESOINS_ENGAGEMENTS:
            self.assertNotIn(cle, neerlandais)


if __name__ == '__main__':
    unittest.main()
