"""Reproductions de la revue du 27/09, données fictives et aucun appel IA."""
import copy
import unittest

import extraction_fiche as extraction
import controles
import champ_communal
from serveur import lire_export
from verifier_csv_compteur import configuration
import verifier_optimisation_contrat as tests_contrats
from verifier_optimisation_contrat import preuve
from optimisation_contrat import comparer_contrats


def extraire(champ, valeur, ligne, citation=None):
    documents = [{'nom': 'ATO fictif.txt', 'texte': ligne}]
    reponse = {'champs': dict.fromkeys(extraction.CHAMPS),
               'preuves': {cle: [] for cle in extraction.CHAMPS}, 'alertes': []}
    reponse['champs'][champ] = valeur
    reponse['preuves'][champ] = [{'repere': 'D1:L1', 'citation': ligne if citation is None else citation}]
    return extraction.controler(reponse, documents, extraction.indexer(documents))


class RevueImportExtraction(unittest.TestCase):
    def test_01_fuseau_utc_nominal_jamais_reinterprete_local(self):
        reglages = configuration() | {'format_temps': '%Y-%m-%d %H:%M %Z', 'horodatage_marque': 'fin'}
        with self.assertRaisesRegex(ValueError, '%Z'):
            lire_export('Tijd;Verbruik\n2026-08-01 00:15 UTC;100\n', reglages)

    def test_01_decalage_numerique_est_conserve(self):
        # Depuis le 30/09 (corpus Fluvius, relecture de Fable), le fuseau déclaré décrit l'écriture du fichier : le
        # décalage écrit est conservé s'il concorde, et arrête la lecture s'il contredit la déclaration.
        reglages = configuration() | {'format_temps': '%Y-%m-%d %H:%M %z', 'horodatage_marque': 'fin', 'fuseau': 'UTC'}
        _, dates = lire_export('Tijd;Verbruik\n2026-08-01 00:15 +0000;100\n', reglages)
        self.assertEqual(dates, ['2026-08-01T00:15:00+00:00'])
        with self.assertRaisesRegex(ValueError, 'fuseau déclaré'):
            lire_export('Tijd;Verbruik\n2026-08-01 00:15 +0000;100\n', reglages | {'fuseau': 'Europe/Amsterdam'})

    def test_02_milliers_avec_zero_initial_refuses(self):
        for valeur in ('0.125', '00.500', '012.500', '+0.250'):
            with self.subTest(valeur=valeur), self.assertRaisesRegex(ValueError, 'milliers'):
                lire_export('Tijd;Verbruik\n2026-08-01T00:15:00Z;' + valeur + '\n', configuration() | {'fuseau': 'UTC'})

    def test_02_milliers_declares_valides_acceptes(self):
        valeurs, _ = lire_export('Tijd;Verbruik\n2026-08-01T00:15:00Z;12.500,25\n', configuration() | {'fuseau': 'UTC'})
        self.assertEqual(valeurs, [12500.25])

    def test_14_citation_vide_ne_valide_aucun_champ(self):
        for champ, valeur in [('type_transportrecht', 'vast'), ('gtv_kw', 100)]:
            with self.subTest(champ=champ):
                r = extraire(champ, valeur, 'Vast transportrecht, vermogen 100 kW.', '  ')
                self.assertNotIn(champ, r['valeurs'])
                self.assertIn(champ, r['refus'])

    def test_14_nature_doigt_sur_ligne_ne_suffit_pas(self):
        for ligne in ('Het transportrecht is tijdsblokgebonden.', 'Vast bedrag: 100 euro.',
                      'Geen vast transportrecht.', 'Vast transportrecht en tijdsblokgebonden transport.'):
            with self.subTest(ligne=ligne):
                self.assertNotIn('type_transportrecht', extraire('type_transportrecht', 'vast', ligne)['valeurs'])

    def test_14_natures_explicitement_ecrites_acceptees(self):
        for valeur, ligne in [('vast', 'Het transportrecht is vast.'),
                              ('tijdsblok', 'Het transportrecht is tijdsblokgebonden.'),
                              ('tijdsduurgebonden', 'Tijdsduurgebonden transportrecht.'),
                              ('non_firm', 'Non-firm transportrecht.')]:
            with self.subTest(valeur=valeur):
                r = extraire('type_transportrecht', valeur, ligne)
                self.assertEqual(r['valeurs']['type_transportrecht']['valeur'], valeur)

    def test_15_periode_avec_jours_ne_devient_pas_un_mois_civil(self):
        self.assertEqual(extraction._periode('15 augustus 2026 t/m 14 september 2026'),
                         ('2026-08-15', '2026-09-14'))

    def test_15_periodes_ambigues_invalides_ou_inversees_refusees(self):
        for texte in ('augustus - september 2026', '15 augustus 2026',
                      '31-02-2026 t/m 31-03-2026', '31-03-2026 t/m 01-03-2026'):
            with self.subTest(texte=texte):
                self.assertIsNone(extraction._periode(texte))

    def test_15_modele_ne_peut_reduire_une_ligne_a_un_seul_mois(self):
        r = extraire('verbruiksperiode', 'augustus 2026',
                     'Verbruiksperiode: 15 augustus 2026 t/m 14 september 2026', 'augustus 2026')
        self.assertEqual(r['valeurs']['periode_facture_debut']['valeur'], '2026-08-15')
        self.assertEqual(r['valeurs']['periode_facture_fin']['valeur'], '2026-09-14')


class RevueContrats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tests_contrats.Comparateur.setUpClass()

    def setUp(self):
        self.configuration = copy.deepcopy(tests_contrats.Comparateur.configuration)

    def calculer(self):
        return comparer_contrats(tests_contrats.Comparateur.valeurs, tests_contrats.Comparateur.dates, self.configuration)

    def test_07_borne_indeterminee_ou_interdite_bloque_la_dominance(self):
        for categorie, details in [('e', {}), ('e', {'derniere_hausse': '2026-06-01'}),
                                  ('c', {'exception_acceptee': False, 'changement_deja_effectue': True})]:
            with self.subTest(categorie=categorie, details=details):
                self.configuration['options'][0]['demande_gtv'] = preuve(
                    {'date_demande': '2026-08-20', 'categorie_code': categorie, **details})
                r = self.calculer()
                self.assertIsNone(r['dominante'])
                self.assertEqual(r['options'][1]['statut'], 'incomplet')

    def test_08_prix_manquant_conserve_le_rapport_sans_gagnant(self):
        autre = copy.deepcopy(self.configuration['options'][0])
        autre['id'] = 'autre'
        autre['tarif']['valeur']['energie_eur_kwh'] = None
        self.configuration['options'].append(autre)
        r = self.calculer()
        self.assertIsNone(r['dominante'])
        self.assertIsNotNone(r['options'][0]['cout_annuel_reference_eur'])
        self.assertIsNone(r['options'][2]['cout_annuel_reference_eur'])
        self.assertEqual(r['options'][2]['statut'], 'incomplet')
        self.assertTrue(any('energie_eur_kwh' in m for m in r['options'][2]['manquants']))

    def test_08_prix_invalide_identifie_option_et_champ(self):
        self.configuration['options'][0]['tarif']['valeur']['energie_eur_kwh'] = -1
        with self.assertRaisesRegex(ValueError, 'cible.*energie_eur_kwh'):
            self.calculer()


class RevueRegles(unittest.TestCase):
    def seuil(self, **ajouts):
        return controles.seuil_permis({'commune': 'Dordrecht', 'chimie_batterie': 'LFP',
                                      'capacite_kwh': 2000, 'puissance_kw': 500,
                                      'date_mise_en_service': None, **ajouts})

    def test_03_chimie_hors_champ_ne_declenche_pas_permis_lithium(self):
        r = self.seuil(chimie_batterie='sodium-ion')
        self.assertFalse(r['valeurs']['permis_communal_requis'])
        self.assertEqual(r['valeurs']['pgs37_1'], 'hors_champ_chimie')
        self.assertNotIn('permis communal obligatoire', r['constat'])

    def test_03_anteriorite_conforme_ne_declenche_pas_permis_communal(self):
        r = self.seuil(date_mise_en_service='2024-01-10', conforme_plan_temporaire=True)
        self.assertFalse(r['valeurs']['permis_communal_requis'])
        self.assertNotIn('permis communal obligatoire', r['constat'])

    def test_03_chimie_inconnue_ne_valide_pas_pgs(self):
        self.assertEqual(self.seuil(chimie_batterie=None)['statut'], 'bloque')

    def test_03_pgs_400_mwh_inclus_et_500_sur_mesure(self):
        self.assertEqual(self.seuil(capacite_kwh=400000)['valeurs']['pgs37_1'], 'dans_plage')
        self.assertEqual(self.seuil(capacite_kwh=500000)['valeurs']['pgs37_1'], 'sur_mesure')

    def test_04_dates_invalides_bloquent_uniquement_le_controle(self):
        for champ, valeur in [('date_demande', '01-05-2026'), ('date_depot', '2026-02-30'),
                              ('date_mise_en_service', '20/06/2026')]:
            with self.subTest(champ=champ):
                dossier = {'commune': 'Oosterhout', 'zone_nommee': 'aucune', 'gestionnaire': 'enexis',
                           'date_demande': '2026-01-01', 'date_offre': '2026-02-01',
                           'date_signature': '2026-03-01', 'date_depot': '2026-03-01',
                           'date_mise_en_service': None, champ: valeur}
                resultats = controles.executer_tous(dossier)
                self.assertEqual(len(resultats), len(controles.REGISTRE))
                self.assertTrue(any(r['statut'] == 'bloque' and champ in str(r.get('manque')) for r in resultats))

    def test_04_dates_inversees_ne_produisent_pas_delai_negatif(self):
        r = controles.delai_offre({'date_demande': '2026-05-01', 'date_offre': '2026-03-01',
                                  'date_signature': '2026-02-01'})
        self.assertEqual(r['statut'], 'bloque')
        self.assertNotIn('jours_demande_offre', r.get('valeurs', {}))

    def test_04_champ_communal_direct_date_invalide_indetermine(self):
        r = champ_communal.dans_le_champ({'date_mise_en_service': '20/06/2026', 'zone_nommee': 'aucune'}, 'Oosterhout')
        self.assertEqual(r['statut'], 'indetermine')

    def test_06_stedin_ne_recoit_pas_la_bascule_enexis(self):
        for gestionnaire in ('Stedin', 'TenneT', 'inconnu'):
            with self.subTest(gestionnaire=gestionnaire):
                r = controles.regime_depot({'date_depot': '2026-05-01', 'gestionnaire': gestionnaire})
                self.assertEqual(r['statut'], 'bloque')
                self.assertNotIn('regime_anterieur', r.get('valeurs', {}))

    def test_09_best_zone_decrite_et_zone_inconnue(self):
        for zone in ('Buitengebied Best', 'buitengebied'):
            with self.subTest(zone=zone):
                r = champ_communal.dans_le_champ({'zone': zone, 'couplee_parc_pv': True}, 'Best')
                self.assertEqual(r['statut'], 'dans_le_champ')
        self.assertEqual(champ_communal.dans_le_champ({'zone': 'à préciser', 'couplee_parc_pv': True}, 'Best')['statut'], 'indetermine')

    def test_09_oosterhout_prefixed_zone_exclue(self):
        for zone in ('bedrijventerrein Everdenberg-Oost', 'Bedrijventerrein Everdenberg Oost'):
            with self.subTest(zone=zone):
                r = champ_communal.dans_le_champ({'date_mise_en_service': None, 'zone_nommee': zone}, 'Oosterhout')
                self.assertEqual(r['statut'], 'hors_champ')


if __name__ == '__main__':
    unittest.main()
