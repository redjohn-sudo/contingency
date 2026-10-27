"""Formule pondérée, calendrier explicite, preuve du quart et comparaison annuelle."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verifier_optimisation_contrat as exemples
from pointes_ponderees import (facteur, maxima_mensuels_ponderes, verifier_calendrier,
                              FACTEURS_MOIS, ETE)
from optimisation_contrat import analyser_annee, comparer_contrats, verifier_assiette_tarif, cout_transport
from rapport_contrats import rendre_comparaison

ZONE = ZoneInfo('Europe/Amsterdam')


def calendrier(resume):
    return {'annee_mesuree': resume['annee_mesuree'], 'sha256_profil': resume['sha256'],
            'regime': 'transmission_terrestre', 'jours_feries': [],
            'jours_feries_exhaustifs': True, 'convention_heure': 'debut_quart_local',
            'version_grille': 'stcrt-2026-4090-annexe5', 'grille_verifiee': True}


def configuration_ponderee():
    exemples.Comparateur.setUpClass()
    c = copy.deepcopy(exemples.Comparateur.configuration)
    c['site']['valeur'].update(gestionnaire='tennet', reseau='transmission', tension_kv=150)
    c['contrat_actuel']['valeur']['categorie'] = 'HS-fictif'
    c['options'][0]['categorie']['valeur'] = 'HS-fictif'
    for fiche in (c['tarif_actuel'], c['options'][0]['tarif']):
        fiche['valeur'].update(gestionnaire='tennet', categorie='HS-fictif', categorie_code='b', assiette_pointes='mensuelle_ponderee')
    c['options'][0]['offre']['valeur'].update(gestionnaire='tennet', categorie='HS-fictif', tension_kv=150)
    c['calendrier_ponderation_actuel'] = exemples.preuve(calendrier(exemples.Comparateur.resume))
    c['options'][0]['calendrier_ponderation'] = exemples.preuve(calendrier(exemples.Comparateur.resume))
    return c


class GrilleEtMaxima(unittest.TestCase):
    def test_modele_lie_annee_sans_confirmer_les_pieces(self):
        from fiche_contrats import modele_contrats
        modele = modele_contrats('empreinte-fictive', 2025)
        preuves = [modele['calendrier_ponderation_actuel']] + [o['calendrier_ponderation'] for o in modele['options']]
        for preuve in preuves:
            self.assertEqual(preuve['statut'], 'a_verifier')
            self.assertEqual(preuve['valeur']['annee_mesuree'], 2025)
            self.assertEqual(preuve['valeur']['sha256_profil'], 'empreinte-fictive')
            self.assertIsNone(preuve['valeur']['grille_verifiee'])
            self.assertIsNone(preuve['valeur']['jours_feries_exhaustifs'])

    def test_dimensions_et_facteurs_possibles(self):
        self.assertEqual(set(FACTEURS_MOIS), set(range(1, 13)))
        for ligne in list(FACTEURS_MOIS.values()) + [ETE]:
            self.assertEqual(len(ligne), 24)
            self.assertLessEqual(set(ligne), {6, 7, 8, 9, 10})

    def test_heures_mois_et_weekend(self):
        # Dates de travail explicites : 2 janvier, 3 mars, 2 avril 2025.
        for instant, attendu in [('2025-01-02T00:00', .7), ('2025-01-02T06:00', .8),
                                 ('2025-01-02T07:45', .9), ('2025-01-02T08:00', 1),
                                 ('2025-01-02T22:00', .9), ('2025-01-02T23:45', .8),
                                 ('2025-03-03T16:45', .9), ('2025-03-03T17:00', 1),
                                 ('2025-03-03T21:00', .9), ('2025-04-02T12:00', .6),
                                 ('2025-01-04T12:00', .6)]:
            with self.subTest(instant=instant):
                self.assertEqual(facteur(datetime.fromisoformat(instant).replace(tzinfo=ZONE), 'transmission_terrestre', set()), attendu)

    def test_ferie_prime_sur_jour_de_travail(self):
        instant = datetime(2025, 1, 1, 12, tzinfo=ZONE)
        self.assertEqual(facteur(instant, 'transmission_terrestre', set()), 1)
        self.assertEqual(facteur(instant, 'transmission_terrestre', {'2025-01-01'}), .6)

    def test_deux_heures_d_automne_conservent_le_meme_facteur(self):
        a = datetime(2025, 10, 26, 0, 0, tzinfo=timezone.utc)
        b = datetime(2025, 10, 26, 1, 0, tzinfo=timezone.utc)
        cal = calendrier({'annee_mesuree': 2025, 'sha256': 'fictif'})
        r = maxima_mensuels_ponderes([90, 100], [a, b], cal)['mensuel']['10']
        self.assertEqual(facteur(a, cal['regime'], set()), facteur(b, cal['regime'], set()))
        self.assertEqual(r['debut_local'], '2025-10-26T02:00:00+01:00')
        self.assertEqual(r['pointe_ponderee_kw'], 60)

    def test_pondere_avant_de_prendre_maximum(self):
        debuts = [datetime(2025, 1, 2, 2, tzinfo=ZONE), datetime(2025, 1, 2, 12, tzinfo=ZONE)]
        valeurs = [120, 100]
        cal = calendrier({'annee_mesuree': 2025, 'sha256': 'fictif'})
        r = maxima_mensuels_ponderes(valeurs, debuts, cal)['mensuel']['1']
        self.assertEqual(r['pointe_ponderee_kw'], 100)
        self.assertEqual(r['puissance_brute_kw'], 100)
        self.assertEqual(r['facteur'], 1)
        self.assertEqual(r['position_quart'], 1)
        self.assertEqual(valeurs, [120, 100])

    def test_egalite_conserve_premier_quart(self):
        d = [datetime(2025, 1, 2, 12, tzinfo=ZONE), datetime(2025, 1, 2, 13, tzinfo=ZONE)]
        cal = calendrier({'annee_mesuree': 2025, 'sha256': 'fictif'})
        self.assertEqual(maxima_mensuels_ponderes([100, 100], d, cal)['mensuel']['1']['position_quart'], 0)

    def test_mois_selon_debut_local_pas_date_utc(self):
        d = datetime(2025, 1, 31, 23, tzinfo=timezone.utc)
        cal = calendrier({'annee_mesuree': 2025, 'sha256': 'fictif'})
        r = maxima_mensuels_ponderes([100], [d], cal)
        self.assertEqual(set(r['mensuel']), {'2'})

    def test_regime_mer_ne_depend_pas_du_calendrier(self):
        for mois in range(1, 13):
            for heure in range(24):
                self.assertEqual(facteur(datetime(2025, mois, 1, heure, tzinfo=ZONE), 'mer_art_3_8_2_f', set()), .9)

    def test_date_naive_quart_mal_aligne_et_regime_refuses(self):
        for d, regime in [(datetime(2025, 1, 1), 'transmission_terrestre'),
                          (datetime(2025, 1, 1, 0, 1, tzinfo=ZONE), 'transmission_terrestre'),
                          (datetime(2025, 1, 1, tzinfo=ZONE), 'autre')]:
            with self.assertRaises(ValueError):
                facteur(d, regime, set())

    def test_puissances_non_finies_negatives_et_bool_refusees(self):
        cal = calendrier({'annee_mesuree': 2025, 'sha256': 'fictif'})
        for valeur in (-1, float('nan'), float('inf'), True, '100'):
            with self.assertRaises(ValueError):
                maxima_mensuels_ponderes([valeur], [datetime(2025, 1, 1, tzinfo=ZONE)], cal)


class ComparaisonPonderee(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configuration = configuration_ponderee()
        cls.valeurs, cls.dates = exemples.Comparateur.valeurs, exemples.Comparateur.dates
        cls.resume = exemples.Comparateur.resume

    def setUp(self):
        self.c = copy.deepcopy(self.configuration)

    def calcul(self, valeurs=None):
        return comparer_contrats(valeurs or self.valeurs, self.dates, self.c)

    def test_facture_ponderee_et_ecart_exact(self):
        r = self.calcul()
        self.assertEqual(r['dominante'], 'cible')
        self.assertAlmostEqual(r['options'][0]['cout_annuel_reference_eur'], 92520)
        self.assertAlmostEqual(r['options'][1]['cout_annuel_reference_eur'], 92120)
        self.assertAlmostEqual(r['options'][1]['ecart_reference_eur'], 400)
        self.assertAlmostEqual(r['options'][1]['cout_transport']['pointes_eur'], 2160)
        self.assertEqual(r['options'][1]['pointes_ponderees']['somme_maxima_kw'], 1080)

    def test_calendrier_manquant_pas_de_prix_ni_gagnant(self):
        del self.c['options'][0]['calendrier_ponderation']
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertIsNone(r['options'][1]['cout_annuel_reference_eur'])

    def test_calendrier_hypothetique_cout_conditionnel(self):
        self.c['options'][0]['calendrier_ponderation']['statut'] = 'hypothese'
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertAlmostEqual(r['options'][1]['cout_annuel_reference_eur'], 92120)

    def test_annee_empreinte_et_dates_feriees_incoherentes_refusees(self):
        for cle, valeur in [('annee_mesuree', 2026), ('annee_mesuree', True),
                           ('sha256_profil', 'autre'), ('jours_feries', None),
                           ('jours_feries', ['2025-01-01', '2025-01-01']),
                           ('jours_feries', ['2026-01-01']), ('jours_feries', ['2025-02-30'])]:
            self.setUp()
            self.c['options'][0]['calendrier_ponderation']['valeur'][cle] = valeur
            with self.subTest(cle=cle, valeur=valeur), self.assertRaises(ValueError):
                self.calcul()

    def test_confirmations_calendrier_absentes_pas_de_prix(self):
        for cle in ('grille_verifiee', 'version_grille', 'jours_feries_exhaustifs', 'convention_heure', 'regime'):
            self.setUp()
            del self.c['options'][0]['calendrier_ponderation']['valeur'][cle]
            r = self.calcul()
            self.assertIsNone(r['dominante'])
            self.assertIsNone(r['options'][1]['cout_annuel_reference_eur'])
            self.assertIn('Geen financieel beste optie vastgesteld', rendre_comparaison(r, 'nl'))

    def test_grille_non_transposee_autre_annee_tarifaire(self):
        self.c['annee_tarifaire'] = 2027
        self.c['date_comparaison'] = '2027-01-01'
        for fiche in (self.c['tarif_actuel'], self.c['options'][0]['tarif']):
            fiche['valeur']['annee'] = 2027
        self.assertIsNone(self.calcul()['options'][0]['cout_annuel_reference_eur'])

    def test_regional_150kv_pas_tenneT_par_inference(self):
        self.c['site']['valeur'].update(gestionnaire='liander', reseau='distribution')
        self.assertIsNone(self.calcul()['options'][0]['cout_annuel_reference_eur'])

    def test_offshore_categorie_b_refusee_a_acceptee(self):
        for cle in ('calendrier_ponderation_actuel',):
            self.c[cle]['valeur']['regime'] = 'mer_art_3_8_2_f'
        self.c['options'][0]['calendrier_ponderation']['valeur']['regime'] = 'mer_art_3_8_2_f'
        self.assertIsNone(self.calcul()['options'][0]['cout_annuel_reference_eur'])
        for fiche in (self.c['tarif_actuel'], self.c['options'][0]['tarif']):
            fiche['valeur']['categorie_code'] = 'a'
        self.assertAlmostEqual(self.calcul()['options'][0]['cout_transport']['pointes_eur'], 2160)

    def test_faible_pointe_ponderee_n_autorise_pas_depassement_gtv(self):
        valeurs = list(self.valeurs)
        debuts = exemples.Comparateur.debuts
        position = next(i for i, d in enumerate(debuts) if d.month == 4 and d.day == 2 and d.hour == 12)
        valeurs[position] = 150
        resume, _, _ = analyser_annee(valeurs, self.dates)
        self.c['provenance']['valeur']['sha256_profil'] = resume['sha256']
        self.c['calendrier_ponderation_actuel']['valeur']['sha256_profil'] = resume['sha256']
        self.c['options'][0]['calendrier_ponderation']['valeur']['sha256_profil'] = resume['sha256']
        r = self.calcul(valeurs)['options'][1]
        self.assertEqual(r['pointes_ponderees']['mensuel']['4']['pointe_ponderee_kw'], 90)
        self.assertEqual(r['depassements']['quarts'], 1)
        self.assertEqual(r['statut'], 'incompatible')

    def test_seuil_600h_et_zero_bloquent_regime_hebdo(self):
        tarif = self.c['tarif_actuel']['valeur']
        for energie in (0, 59999.99, 60000):
            resume = dict(self.resume, pointe_kw=100, energie_kwh=energie)
            self.assertTrue(any('hebdomadaire' in s for s in verifier_assiette_tarif(tarif, resume, 'fixe', 0)))
        resume = dict(self.resume, pointe_kw=100, energie_kwh=60000.01)
        self.assertEqual(verifier_assiette_tarif(tarif, resume, 'fixe', 0), [])
        self.assertTrue(verifier_assiette_tarif(tarif, dict(self.resume, pointe_kw=0, energie_kwh=0), 'fixe', 0))

    def test_ms_n_accepte_pas_ponderation(self):
        tarif = self.c['tarif_actuel']['valeur']
        tarif['categorie_code'] = 'e'
        self.assertTrue(verifier_assiette_tarif(tarif, self.resume, 'fixe', 0))

    def test_cout_pondere_sans_maxima_ne_reprend_pas_pointe_brute(self):
        tarif = self.c['tarif_actuel']['valeur']
        with self.assertRaisesRegex(ValueError, 'Douze maxima pondérés'):
            cout_transport(tarif, self.resume, self.valeurs, 120, 'HS-fictif', 'tennet', 2026)

    def test_rapport_fr_nl_affiche_quart_brut_facteur_et_maximum(self):
        r = self.calcul()
        for langue, attendu in [('fr', 'Quarts qui déterminent les maxima pondérés'), ('nl', 'Kwartieren die de gewogen maxima bepalen')]:
            html = rendre_comparaison(r, langue)
            self.assertIn(attendu, html)
            self.assertIn('2025-01-01T08:00:00+01:00', html)
            self.assertIn('100,00 kW', html)
            self.assertIn('0,80', html)
            self.assertIn('1,00', html)


if __name__ == '__main__':
    unittest.main()
