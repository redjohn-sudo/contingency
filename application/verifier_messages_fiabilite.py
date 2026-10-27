"""Contrat des messages FR/NL de fiabilité, sans calcul ni décision d'import."""
import math
from string import Formatter
import unittest

import messages_fiabilite as messages


class MessagesFiabilite(unittest.TestCase):
    def test_codes_du_premier_lot_disponibles(self):
        attendus = {   'ANOMALIE_DOUBLON',
    'ANOMALIE_PAS',
    'ANOMALIE_TROU',
    'BILAN_LIGNES',
    'CANAL_ABSENT',
    'CONFIRMATION_PERIMEE',
    'FUSEAU_CONTRADICTOIRE',
    'GRANDEUR_INDEX_DOCUMENTE',
    'GRANDEUR_INDEX_POSSIBLE',
    'HEURE_AMBIGUE',
    'HEURE_INEXISTANTE',
    'HEURE_REPETEE_A_CONFIRMER',
    'HEURE_REPETEE_ORDRE_AMBIGU',
    'INTERPRETATION_A_CONFIRMER',
    'PERIODE_ANCIENNE',
    'PERIODE_ANNEE_EN_COURS',
    'PERIODE_ANNEE_FUTURE',
    'PERIODE_ANNEE_INCOMPLETE',
    'PERIODE_NON_CIVILE',
    'PERIODE_PARTIELLE',
    'POINTE_A_CONFIRMER',
    'POINTS_MULTIPLES',
    'QUALITE_ESTIMEE',
    'QUALITE_INCONNUE',
    'QUALITE_INVALIDE',
    'QUALITE_POINTE_NON_MESUREE',
    'QUALITE_POINTE_INTERVALLE_NON_MESUREE',
    'QUALITE_VALEURS_NON_MESUREES',
    'UNITE_ABSENTE',
    'UNITE_CONTRADICTOIRE',
    'UNITE_NON_RECOUPEE',
    'UNITE_RECOUPEE',
    'VALEUR_ATYPIQUE',
    'VALEUR_INVALIDE'}
        self.assertTrue(attendus <= set(messages.CODES))
        self.assertEqual(len(messages.CODES), len(set(messages.CODES)))

    def test_catalogues_et_parametres_correspondent(self):
        self.assertEqual(set(messages.MESSAGES_FR), set(messages.MESSAGES_NL))
        self.assertEqual(set(messages.CODES), set(messages.PARAMETRES))
        for code in messages.CODES:
            for catalogue in (messages.MESSAGES_FR, messages.MESSAGES_NL):
                with self.subTest(code=code, catalogue=catalogue is messages.MESSAGES_FR):
                    champs = set()
                    for _, champ, formatage, conversion in Formatter().parse(catalogue[code]):
                        if champ is not None:
                            self.assertTrue(champ.isidentifier())
                            self.assertFalse(formatage)
                            self.assertIsNone(conversion)
                            champs.add(champ)
                    self.assertEqual(champs, set(messages.PARAMETRES[code]))

    def test_tous_les_messages_se_rendent_dans_les_deux_langues(self):
        for code in messages.CODES:
            parametres = {nom: ('2024-10-27T02:15:00+02:00' if nom in messages.CHAMPS_DATES else 'TEMOIN_' + nom)
                          for nom in messages.PARAMETRES[code]}
            for langue in ('fr', 'nl'):
                with self.subTest(code=code, langue=langue):
                    rendu = messages.message_fiabilite(code, langue, **parametres)
                    self.assertIsInstance(rendu, str)
                    self.assertTrue(rendu.strip())
                    for nom, valeur in parametres.items():
                        if nom not in messages.CHAMPS_DATES:
                            self.assertIn(valeur, rendu)
                    self.assertNotIn('—', rendu)
                    self.assertNotIn('--', rendu)

    def test_francais_par_defaut(self):
        self.assertEqual(
            messages.message_fiabilite('UNITE_ABSENTE', colonne='puissance_kw'),
            messages.message_fiabilite('UNITE_ABSENTE', 'fr', colonne='puissance_kw'),
        )

    def test_code_inconnu_refuse(self):
        with self.assertRaisesRegex(ValueError, 'Code'):
            messages.message_fiabilite('FIAB-INVENTE')

    def test_langue_inconnue_ne_retombe_pas_sur_le_francais(self):
        for langue in ('en', '', None):
            with self.subTest(langue=langue), self.assertRaisesRegex(ValueError, 'Langue'):
                messages.message_fiabilite('UNITE_ABSENTE', langue, colonne='kWh')

    def test_parametre_manquant_signale(self):
        with self.assertRaisesRegex(ValueError, 'colonne'):
            messages.message_fiabilite('UNITE_ABSENTE')

    def test_parametre_inattendu_signale(self):
        with self.assertRaisesRegex(ValueError, 'inattendus'):
            messages.message_fiabilite('UNITE_ABSENTE', colonne='kWh', compteur='301')

    def test_valeur_absente_non_affichee_comme_texte(self):
        with self.assertRaisesRegex(ValueError, 'colonne'):
            messages.message_fiabilite('UNITE_ABSENTE', colonne=None)

    def test_objets_et_booleens_ne_sont_pas_des_valeurs_affichables(self):
        for valeur in (True, False, {}, [], object()):
            with self.subTest(type=type(valeur)), self.assertRaises(ValueError):
                messages.message_fiabilite('QUALITE_INCONNUE', raison=valeur)

    def test_nombres_non_finis_refuses(self):
        for valeur in (math.nan, math.inf, -math.inf):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                messages.message_fiabilite('QUALITE_INCONNUE', raison=valeur)

    def test_zero_et_nombres_conserves_sans_conversion(self):
        rendu = messages.message_fiabilite(
            'BILAN_LIGNES', lues=100, conservees=96, filtrees=4, rejetees=0,
        )
        for valeur in ('100', '96', '4', '0'):
            self.assertIn(valeur, rendu)
        self.assertIn('0.25', messages.message_fiabilite('QUALITE_INCONNUE', raison=0.25))

    def test_donnees_client_ne_sont_pas_reinterpretees_comme_gabarit(self):
        brut = '0E-8 {ne_pas_evaluer} <strong>301</strong> & 123456789012345678'
        for langue in ('fr', 'nl'):
            rendu = messages.message_fiabilite(
                'VALEUR_INVALIDE', langue, ligne=7, colonne='énergie',
                valeur_brute=brut, format_attendu='kWh',
            )
            self.assertIn(brut, rendu)
        # Contrat : texte brut, à échapper par le moteur HTML lors de l'intégration.

    def test_neerlandais_sans_traduire_les_pieces_du_client(self):
        rendu = messages.message_fiabilite(
            'QUALITE_ESTIMEE', 'nl', methode='Méthode source 17', origine='ORIGINE_A',
        )
        self.assertIn('Geschatte of gereconstrueerde waarde', rendu)
        self.assertIn('Méthode source 17', rendu)
        self.assertIn('ORIGINE_A', rendu)

    def test_atypique_n_est_pas_un_refus_ni_un_changement_d_unite(self):
        for langue, temoin in (('fr', "ne prouve pas une erreur d'unité"),
                               ('nl', 'bewijst geen fout in de eenheid')):
            rendu = messages.message_fiabilite(
                'VALEUR_ATYPIQUE', langue, ligne=9, valeur_brute='2380',
                interpretation='kW', reference='facture',
            )
            self.assertIn(temoin, rendu)
            self.assertIn('2380', rendu)
            for interdit in ('120 %', '500 kWh', 'refusé', 'geweigerd'):
                self.assertNotIn(interdit, rendu)

    def test_estimation_sans_facteur_universel(self):
        for langue in ('fr', 'nl'):
            rendu = messages.message_fiabilite(
                'QUALITE_ESTIMEE', langue, methode='copie', origine='source',
            )
            self.assertNotIn('1 %', rendu)
            self.assertNotIn('1%', rendu)
            self.assertNotIn('1.01', rendu)

    def test_ambiguite_conserve_les_lignes(self):
        rendu = messages.message_fiabilite(
            'HEURE_REPETEE_ORDRE_AMBIGU', jour='2024-10-27',
        )
        self.assertIn('lignes restent conservées', rendu)
        self.assertIn('désambiguïsation justifiée', rendu)

    def test_confirmation_liee_a_la_version(self):
        rendu = messages.message_fiabilite(
            'INTERPRETATION_A_CONFIRMER', lignes='42', interpretation='UTC+02',
            preuve='convention source', version='a' * 64,
        )
        self.assertIn('a' * 64, rendu)
        self.assertIn('Le calcul attend cette confirmation', rendu)

    def test_annee_future_non_qualifiee_d_historique_recent(self):
        rendu = messages.message_fiabilite(
            'PERIODE_ANNEE_FUTURE', annee=2027, annee_scan=2026,
        )
        self.assertIn('ne peut pas être qualifiée de mesure historique récente', rendu)

    def test_rendu_ne_modifie_pas_les_parametres(self):
        avant = {'colonne': 'compteur'}
        messages.message_fiabilite('UNITE_ABSENTE', **avant)
        self.assertEqual(avant, {'colonne': 'compteur'})
        self.assertNotEqual(messages.MESSAGES_FR, messages.MESSAGES_NL)

    def test_dates_fr_et_nl_sans_changement_d_instant(self):
        for langue, attendu in (
            ('fr', '27/10/2024 à 02:15:00 UTC+02:00'),
            ('nl', '27-10-2024 om 02:15:00 UTC+02:00'),
        ):
            rendu = messages.message_fiabilite(
                'ANOMALIE_DOUBLON', langue, instant='2024-10-27T02:15:00+02:00',
            )
            self.assertIn(attendu, rendu)

    def test_heures_repetees_restent_distinctes(self):
        for decalage in ('+02:00', '+01:00'):
            rendu = messages.message_fiabilite(
                'ANOMALIE_DOUBLON', instant='2024-10-27T02:15:00' + decalage,
            )
            self.assertIn('02:15:00 UTC' + decalage, rendu)

    def test_aucun_fuseau_invente(self):
        rendu = messages.message_fiabilite(
            'ANOMALIE_DOUBLON', instant='2024-10-27T02:15:00',
        )
        self.assertIn('fuseau non indiqué', rendu)
        self.assertNotIn('UTC+', rendu)

    def test_date_civile_sans_heure_inventee(self):
        rendu = messages.message_fiabilite(
            'HEURE_REPETEE_ORDRE_AMBIGU', jour='2024-10-27',
        )
        self.assertIn('27/10/2024', rendu)
        self.assertNotIn('00:00', rendu)

    def test_dates_invalides_ou_non_iso_refusees(self):
        for valeur in ('27/10/2024', '2024-02-30', '2024-10-27T25:00', 2024):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                messages.message_fiabilite('ANOMALIE_DOUBLON', instant=valeur)

    def test_precision_horaire_source_conservee(self):
        rendu = messages.message_fiabilite(
            'ANOMALIE_DOUBLON', instant='2024-10-27T02:15:00.123456789Z',
        )
        self.assertIn('02:15:00.123456789 UTC+00:00', rendu)

    def test_listes_de_lignes_et_de_decalages_rendues_sans_tri(self):
        lignes, decalages = [8, 7], ['+02:00', '+01:00']
        rendu = messages.message_fiabilite(
            'HEURE_REPETEE_A_CONFIRMER', jour='2024-10-27',
            lignes_ete=lignes, lignes_hiver=[12, 11], decalages=decalages, empreinte='a' * 64, identite='b' * 64,
        )
        self.assertIn('8, 7', rendu)
        self.assertIn('12, 11', rendu)
        self.assertIn('+02:00, +01:00', rendu)
        self.assertEqual(lignes, [8, 7])
        self.assertEqual(decalages, ['+02:00', '+01:00'])

    def test_liste_de_lignes_invalide_refusee(self):
        for valeur in ([], [None], [True], [['7']], [math.inf]):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                messages.message_fiabilite(
                    'HEURE_REPETEE_A_CONFIRMER', jour='2024-10-27', lignes_ete=valeur,
                    lignes_hiver=[12, 13, 14, 15], decalages=['+02:00', '+01:00'], empreinte='a' * 64, identite='b' * 64,
                )

    def test_codes_et_parametres_du_modele_opus_393def5(self):
        attendus = {
            'PERIODE_ANNEE_FUTURE': ('annee', 'annee_scan'),
            'PERIODE_ANNEE_EN_COURS': ('annee', 'annee_scan'),
            'PERIODE_NON_CIVILE': ('debut', 'fin', 'jours'),
            'PERIODE_PARTIELLE': ('debut', 'fin', 'jours'),
            'ANOMALIE_TROU': ('apres', 'avant', 'quarts'),
            'ANOMALIE_DOUBLON': ('instant',),
            'ANOMALIE_ORDRE': ('de', 'vers'),
            'ANOMALIE_PAS': ('ligne', 'ecart_minutes'),
            'UNITE_NON_RECOUPEE': ('unite', 'source'),
        }
        for code, parametres in attendus.items():
            with self.subTest(code=code):
                self.assertEqual(set(parametres), set(messages.PARAMETRES[code]))

    def test_codes_et_parametres_heure_repetee_opus_f3ccd4c(self):
        parametres = {'jour': '2025-10-26', 'decalages': ['+02:00', '+01:00'],
                      'empreinte': 'ab' * 32, 'identite': 'cd' * 32, 'lignes_ete': [578, 579, 580, 581],
                      'lignes_hiver': [582, 583, 584, 585]}
        for code in ('HEURE_REPETEE_A_CONFIRMER', 'HEURE_REPETEE_INTERPRETEE'):
            self.assertEqual(set(parametres), set(messages.PARAMETRES[code]))
            for langue in ('fr', 'nl'):
                with self.subTest(code=code, langue=langue):
                    rendu = messages.message_fiabilite(code, langue, **parametres)
                    for attendu in ('ab' * 32, 'cd' * 32, '578, 579, 580, 581', '582, 583, 584, 585', '+02:00, +01:00'):
                        self.assertIn(attendu, rendu)
        self.assertEqual(messages.PARAMETRES['HEURE_REPETEE_ORDRE_AMBIGU'], ('jour',))

    def test_confirmation_heure_repetee_distingue_attente_et_interpretation(self):
        parametres = {'jour': '2025-10-26', 'decalages': ['+02:00', '+01:00'],
                      'empreinte': 'a' * 64, 'identite': 'b' * 64,
                      'lignes_ete': (1, 2, 3, 4), 'lignes_hiver': (5, 6, 7, 8)}
        for langue, attente, confirmation in (('fr', 'puis confirmez', 'a été confirmée'),
                                               ('nl', 'en bevestig', 'is de interpretatie')):
            with self.subTest(langue=langue):
                self.assertIn(attente, messages.message_fiabilite('HEURE_REPETEE_A_CONFIRMER', langue, **parametres))
                confirme = messages.message_fiabilite('HEURE_REPETEE_INTERPRETEE', langue, **parametres)
                self.assertIn(confirmation, confirme)
                self.assertNotIn(attente, confirme)

    def test_empreinte_seule_ne_suffit_pas_pour_afficher_une_confirmation(self):
        parametres = {'jour': '2025-10-26', 'decalages': ['+02:00', '+01:00'],
                      'empreinte': 'a' * 64, 'lignes_ete': [1, 2, 3, 4], 'lignes_hiver': [5, 6, 7, 8]}
        for code in ('HEURE_REPETEE_A_CONFIRMER', 'HEURE_REPETEE_INTERPRETEE'):
            for langue in ('fr', 'nl'):
                with self.subTest(code=code, langue=langue), self.assertRaisesRegex(ValueError, 'manquants = identite'):
                    messages.message_fiabilite(code, langue, **parametres)

    def test_changement_de_conventions_demande_une_nouvelle_confirmation(self):
        parametres = {'jour': '2025-10-26', 'decalages': ['+02:00', '+01:00'],
                      'empreinte': 'a' * 64, 'identite': 'b' * 64,
                      'lignes_ete': [1, 2, 3, 4], 'lignes_hiver': [5, 6, 7, 8]}
        for langue, attendu in (('fr', 'Toute modification des conventions nécessite une nouvelle confirmation.'),
                                ('nl', 'Bij gewijzigde conventies is een nieuwe bevestiging nodig.')):
            with self.subTest(langue=langue):
                rendu = messages.message_fiabilite('HEURE_REPETEE_A_CONFIRMER', langue, **parametres)
                self.assertIn(attendu, rendu)

    def test_codes_et_parametres_vraisemblance_opus_2c6a7d9(self):
        for code, parametres in {
            'GRANDEUR_INDEX_POSSIBLE': {'premier', 'dernier', 'quarts', 'identite', 'confirmation'},
            'UNITE_RECOUPEE': {'unite', 'source'},
            'UNITE_NON_RECOUPEE': {'unite', 'source'},
            'QUALITE_INCONNUE': {'raison'},
            'QUALITE_POINTE_NON_MESUREE': {'instant', 'pointe_kw', 'qualite'},
            'QUALITE_VALEURS_NON_MESUREES': {'estime', 'calcule', 'inconnue', 'quarts'},
        }.items():
            with self.subTest(code=code):
                self.assertEqual(set(messages.PARAMETRES[code]), parametres)

    def test_index_possible_sans_confirmation_explicite_dans_les_deux_langues(self):
        for langue, absence in (('fr', 'non fournie'), ('nl', 'niet verstrekt')):
            with self.subTest(langue=langue):
                rendu = messages.message_fiabilite('GRANDEUR_INDEX_POSSIBLE', langue,
                                                   premier=100, dernier=167.1, quarts=672, identite='a' * 64,
                                                   confirmation=None)
                self.assertIn(absence, rendu)
                self.assertNotIn('None', rendu)
                for valeur in ('100', '167.1', '672'):
                    self.assertIn(valeur, rendu)
        with self.assertRaisesRegex(ValueError, 'source'):
            messages.message_fiabilite('UNITE_RECOUPEE', unite='kW', source=None)

    def test_index_possible_confirme_ne_devient_pas_une_erreur_certaine(self):
        for langue, prudent in (
            ('fr', 'ne prouve pas une erreur'),
            ('nl', 'bewijst geen fout'),
        ):
            with self.subTest(langue=langue):
                rendu = messages.message_fiabilite('GRANDEUR_INDEX_POSSIBLE', langue,
                                                   premier=100, dernier=167.1, quarts=672,
                                                   identite='a' * 64, confirmation='a' * 64)
                self.assertIn('a' * 64, rendu)
                self.assertIn(prudent, rendu)
                self.assertNotIn('puissance_moyenne_kw', rendu)
                self.assertNotIn('refusé', rendu)

    def test_unite_recoupee_preserve_la_piece_et_le_caractere_declare(self):
        source = 'Facture JAN-2025, page 3, {texte_client} <référence>'
        for langue, declare in (('fr', 'déclaré'), ('nl', 'opgave')):
            with self.subTest(langue=langue):
                rendu = messages.message_fiabilite('UNITE_RECOUPEE', langue, unite='kW', source=source)
                self.assertIn(source, rendu)
                self.assertIn('kW', rendu)
                self.assertIn(declare, rendu)

    def test_qualite_comptes_optionnels_absents_signifient_zero(self):
        import itertools
        noms = ('estime', 'calcule', 'inconnue')
        self.assertEqual(set(messages.PARAMETRES_OPTIONNELS['QUALITE_VALEURS_NON_MESUREES']), set(noms))
        for taille in (1, 2, 3):
            for presents in itertools.combinations(noms, taille):
                partiels = {nom: i + 1 for i, nom in enumerate(presents)}
                complets = {nom: partiels.get(nom, 0) for nom in noms}
                for langue in ('fr', 'nl'):
                    with self.subTest(presents=presents, langue=langue):
                        self.assertEqual(
                            messages.message_fiabilite('QUALITE_VALEURS_NON_MESUREES', langue, quarts=672, **partiels),
                            messages.message_fiabilite('QUALITE_VALEURS_NON_MESUREES', langue, quarts=672, **complets),
                        )
                self.assertEqual(set(partiels), set(presents))

    def test_qualite_compte_requis_et_faute_de_cle_non_ignoree(self):
        for parametres in ({'quarts': 672}, {'quarts': 672, 'estimee': 1}, {'estime': 1}):
            with self.subTest(parametres=parametres), self.assertRaises(ValueError):
                messages.message_fiabilite('QUALITE_VALEURS_NON_MESUREES', **parametres)

    def test_pointe_non_mesuree_garde_instant_decalage_valeur_et_reserve(self):
        for langue, reserve in (('fr', 'restent à confirmer'), ('nl', 'moeten nog worden bevestigd')):
            for qualite, fr, nl in (('estime', 'estimée', 'geschat'), ('calcule', 'calculée', 'berekend'),
                                   ('inconnue', 'inconnue', 'onbekend')):
                with self.subTest(langue=langue, qualite=qualite):
                    rendu = messages.message_fiabilite('QUALITE_POINTE_NON_MESUREE', langue,
                                                       instant='2025-10-26T02:15:00+01:00',
                                                       pointe_kw=300.25, qualite=qualite)
                    for attendu in ('300,25', '02:15:00 UTC+01:00', reserve, fr if langue == 'fr' else nl):
                        self.assertIn(attendu, rendu)

    def test_pointe_numerique_virgule_sans_arrondi(self):
        for langue in ('fr', 'nl'):
            for valeur, attendu in ((595.0, '595'), (595, '595'), (300.25, '300,25'),
                                    (0.0, '0'), (0.000125, '0,000125'),
                                    (595.123456789, '595,123456789')):
                with self.subTest(langue=langue, valeur=valeur):
                    rendu = messages.message_fiabilite('QUALITE_POINTE_NON_MESUREE', langue,
                                                       instant='2025-01-02T08:30:00+01:00',
                                                       pointe_kw=valeur, qualite='inconnue')
                    self.assertIn(f'{attendu} kW', rendu)

    def test_pointe_texte_source_reste_litterale(self):
        for langue in ('fr', 'nl'):
            rendu = messages.message_fiabilite('QUALITE_POINTE_NON_MESUREE', langue,
                                               instant='2025-01-02T08:30:00+01:00',
                                               pointe_kw='595.0', qualite='inconnue')
            self.assertIn('595.0 kW', rendu)

    def test_pointe_marque_la_fin_du_quart_sans_decaler_l_instant(self):
        for langue, fin in (('fr', "quart d'heure se terminant le"),
                            ('nl', 'kwartier dat eindigt op')):
            for decalage in ('+01:00', '+02:00'):
                with self.subTest(langue=langue, decalage=decalage):
                    rendu = messages.message_fiabilite('QUALITE_POINTE_NON_MESUREE', langue,
                                                       instant='2025-10-26T02:30:00' + decalage,
                                                       pointe_kw=595.0, qualite='estime')
                    self.assertIn(fin, rendu)
                    self.assertIn('02:30:00 UTC' + decalage, rendu)
                    self.assertNotIn('02:15', rendu)

    def test_pointe_numerique_non_finie_ou_booleenne_refusee(self):
        for valeur in (math.nan, math.inf, -math.inf, True, False):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                messages.message_fiabilite('QUALITE_POINTE_NON_MESUREE',
                                           instant='2025-01-02T08:30:00+01:00',
                                           pointe_kw=valeur, qualite='inconnue')

    def test_pointe_intervalle_natif_annonce_le_pas_et_la_fin(self):
        for langue, duree, fin, reserve in (
            ('fr', 'intervalle de {pas} minutes', 'se terminant le', 'restent à confirmer'),
            ('nl', 'interval van {pas} minuten', 'eindigt op', 'moeten nog worden bevestigd'),
        ):
            for pas in (5, 10, 15, 30, 60):
                with self.subTest(langue=langue, pas=pas):
                    rendu = messages.message_fiabilite('QUALITE_POINTE_INTERVALLE_NON_MESUREE', langue,
                                                       instant='2025-03-30T03:00:00+02:00',
                                                       pointe_kw=595.25, qualite='inconnue', pas_minutes=pas)
                    for attendu in (duree.format(pas=pas), fin, '03:00:00 UTC+02:00', '595,25 kW', reserve):
                        self.assertIn(attendu, rendu)
                    self.assertNotIn("quart d'heure", rendu)
                    self.assertNotIn('kwartier', rendu)

    def test_pointe_intervalle_reutilise_le_formatage_sans_perdre_la_source(self):
        for langue, libelle in (('fr', 'estimée'), ('nl', 'geschat')):
            for valeur, attendu in ((595.0, '595'), (-12.25, '-12,25'), ('595.0 <source>', '595.0 <source>')):
                with self.subTest(langue=langue, valeur=valeur):
                    rendu = messages.message_fiabilite('QUALITE_POINTE_INTERVALLE_NON_MESUREE', langue,
                                                       instant='2025-10-26T02:30:00+01:00', pointe_kw=valeur,
                                                       qualite='estime', pas_minutes=30)
                    for texte in (attendu + ' kW', libelle, '02:30:00 UTC+01:00'):
                        self.assertIn(texte, rendu)

    def test_pointe_intervalle_contrat_exact_sans_pas_implicite(self):
        self.assertEqual(set(messages.PARAMETRES['QUALITE_POINTE_INTERVALLE_NON_MESUREE']),
                         {'instant', 'pointe_kw', 'qualite', 'pas_minutes'})
        avec_pas = {'instant': '2025-01-02T08:30:00+01:00', 'pointe_kw': 595, 'qualite': 'inconnue', 'pas_minutes': 10}
        with self.assertRaisesRegex(ValueError, 'pas_minutes'):
            messages.message_fiabilite('QUALITE_POINTE_INTERVALLE_NON_MESUREE',
                                       **{k: v for k, v in avec_pas.items() if k != 'pas_minutes'})
        for valeur in (math.nan, math.inf, -math.inf, True, False):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                messages.message_fiabilite('QUALITE_POINTE_INTERVALLE_NON_MESUREE', **(avec_pas | {'pointe_kw': valeur}))

    def test_index_possible_parle_d_intervalles_sans_modifier_le_contrat(self):
        for langue, attendu in (('fr', '144 intervalles'), ('nl', '144 intervallen')):
            rendu = messages.message_fiabilite('GRANDEUR_INDEX_POSSIBLE', langue,
                                               premier=100, dernier=200, quarts=144,
                                               identite='a' * 64, confirmation=None)
            self.assertIn(attendu, rendu)
            self.assertNotIn('144 quarts', rendu)
            self.assertNotIn('144 kwartieren', rendu)

    def test_qualite_inconnue_preserve_le_motif(self):
        raison = 'Motif source {brut} <texte> & 301'
        for langue in ('fr', 'nl'):
            self.assertIn(raison, messages.message_fiabilite('QUALITE_INCONNUE', langue, raison=raison))
        with self.assertRaises(ValueError):
            messages.message_fiabilite('QUALITE_INCONNUE', nombre=672)

    def test_grandeur_identite_absente_refusee(self):
        with self.assertRaisesRegex(ValueError, 'identite'):
            messages.message_fiabilite('GRANDEUR_INDEX_POSSIBLE', premier=100, dernier=167.1,
                                       quarts=672, confirmation=None)

    def test_une_valeur_estimee_sans_faute_de_nombre(self):
        for langue, attendu, interdit in (
            ('fr', 'Valeurs estimées : 1', '1 valeurs sont estimées'),
            ('nl', 'Geschatte waarden: 1', '1 waarden geschat'),
        ):
            with self.subTest(langue=langue):
                rendu = messages.message_fiabilite('QUALITE_VALEURS_NON_MESUREES', langue,
                                                   quarts=1340, estime=1)
                self.assertIn(attendu, rendu)
                self.assertNotIn(interdit, rendu)


if __name__ == '__main__':
    unittest.main()
