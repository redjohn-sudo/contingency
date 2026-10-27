"""Montants, conditions, entrées adverses et commandes des dossiers d’aides NL."""
from copy import deepcopy
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

import dossier_subventions as aides


def fiche_flex(volet='scan', bas=12000, haut=None):
    configuration = aides.modele()['flex_e']
    configuration.update(volet=volet, date_demande='2026-09-27T15:00:00+02:00',
                         couts_eligibles_ht_eur={'min': bas, 'max': bas if haut is None else haut})
    configuration['conditions'] = {cle: True for cle in configuration['conditions']}
    if volet == 'faisabilite':
        configuration['conditions']['mesures_admises'] = True
    return configuration


def fiche_eia(code='260101', bas=100000, haut=None):
    configuration = aides.modele()['eia']
    configuration.update(code=code, regime_is=True, puissance_kw=50, capacite_kwh=100,
                         production_crete_kw=50, date_engagement='2026-09-01',
                         date_declaration='2026-09-27', deduction_integralement_utilisable=True,
                         couts_eligibles_avant_aides_eur={'min': bas, 'max': bas if haut is None else haut},
                         aides_sur_memes_couts_eur={'min': 0, 'max': 0})
    configuration['conditions'] = {cle: True for cle in configuration['conditions']}
    return configuration


def fiche_complete(batterie=True):
    return {'site': 'Dossier fictif de test', 'batterie_envisagee': batterie,
            'flex_e': fiche_flex(), 'eia': fiche_eia()}


class FlexEMontants(unittest.TestCase):
    def test_o18_regle_fournisseur_inconnue_ne_devient_pas_accord(self):
        for volet in ('scan', 'faisabilite'):
            with self.subTest(volet=volet):
                f = fiche_flex(volet, 40000)
                f['conditions'].pop('conseiller_fourniture_conforme', None)
                r = aides.flex_e(f)
                self.assertEqual(r['statut'], 'a_completer')
                controle = next(c for c in r['controles'] if c['champ'] == 'conseiller_fourniture_conforme')
                self.assertEqual(controle['statut'], 'a_confirmer')

    def test_o18_regle_fournisseur_non_respectee_annule_aide(self):
        for volet in ('scan', 'faisabilite'):
            with self.subTest(volet=volet):
                f = fiche_flex(volet, 40000)
                f['conditions']['conseiller_fourniture_conforme'] = False
                r = aides.flex_e(f)
                self.assertEqual(r['statut'], 'non_eligible_selon_declarations')
                self.assertEqual(r['si_conditions_remplies_eur']['max'], 0)

    def test_o18_conformite_fournisseur_declaree_reste_a_revoir(self):
        for volet in ('scan', 'faisabilite'):
            f = fiche_flex(volet, 40000)
            f['conditions']['conseiller_fourniture_conforme'] = True
            r = aides.flex_e(f)
            self.assertEqual(r['statut'], 'conditions_declarees_a_revoir')
            controle = next(c for c in r['controles'] if c['champ'] == 'conseiller_fourniture_conforme')
            self.assertEqual(controle['statut'], 'declaree_satisfaite')
            self.assertIn('fournisseur', controle['condition'])

    def test_scan_50_pour_cent_sans_promesse(self):
        r = aides.flex_e(fiche_flex())
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 6000)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 6000)
        self.assertEqual(r['avantage_prudent_eur']['min'], 0)
        self.assertEqual(r['avantage_prudent_eur']['max'], 6000)
        self.assertEqual(r['avantage_prudent_eur']['periode'], 'ponctuel')

    def test_scan_plafonne_a_10000(self):
        r = aides.flex_e(fiche_flex(bas=30000, haut=40000))
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 10000)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 10000)

    def test_scan_fourchette_traverse_plafond(self):
        r = aides.flex_e(fiche_flex(bas=10000, haut=30000))
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 5000)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 10000)

    def test_faisabilite_sous_minimum_ne_recoit_ni_10k_ni_125k(self):
        r = aides.flex_e(fiche_flex('faisabilite', bas=19999.98))
        self.assertEqual(r['statut'], 'non_eligible_selon_declarations')
        self.assertEqual(r['avantage_prudent_eur']['max'], 0)

    def test_faisabilite_20000_permet_aide_minimale(self):
        r = aides.flex_e(fiche_flex('faisabilite', bas=20000))
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 10000)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 10000)
        self.assertEqual(r['avantage_prudent_eur']['min'], 0)

    def test_faisabilite_moyenne_est_proportionnelle_au_cout(self):
        r = aides.flex_e(fiche_flex('faisabilite', bas=40000, haut=60000))
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 20000)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 30000)

    def test_faisabilite_plafonnee(self):
        r = aides.flex_e(fiche_flex('faisabilite', bas=250000, haut=400000))
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 125000)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 125000)

    def test_fourchette_traversant_minimum_inclut_zero(self):
        r = aides.flex_e(fiche_flex('faisabilite', bas=10000, haut=30000))
        self.assertEqual(r['statut'], 'a_completer')
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 0)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 15000)

    def test_sans_cout_aucun_plafond_utilise_comme_gain(self):
        for volet in ('scan', 'faisabilite'):
            f = fiche_flex(volet); f['couts_eligibles_ht_eur'] = None
            r = aides.flex_e(f)
            self.assertIsNone(r['avantage_prudent_eur'])
            self.assertIsNone(r['si_conditions_remplies_eur'])

    def test_toutes_conditions_requises_absentes_donnent_zero(self):
        for cle in aides.CONDITIONS_FLEX:
            with self.subTest(condition=cle):
                f = fiche_flex(); f['conditions'][cle] = False
                r = aides.flex_e(f)
                self.assertEqual(r['statut'], 'non_eligible_selon_declarations')
                self.assertEqual(r['avantage_prudent_eur']['max'], 0)

    def test_scan_peche_et_visite_specificites(self):
        for cle in ('hors_peche_aquaculture', 'visite_site_prevue'):
            f = fiche_flex(); f['conditions'][cle] = False
            self.assertEqual(aides.flex_e(f)['avantage_prudent_eur']['max'], 0)

    def test_faisabilite_peche_non_exclue_par_regle_scan(self):
        f = fiche_flex('faisabilite', 40000)
        f['conditions']['hors_peche_aquaculture'] = False
        self.assertEqual(aides.flex_e(f)['statut'], 'conditions_declarees_a_revoir')

    def test_faisabilite_cogeneration_et_curtailment_exclus(self):
        f = fiche_flex('faisabilite', 40000); f['conditions']['mesures_admises'] = False
        self.assertEqual(aides.flex_e(f)['avantage_prudent_eur']['max'], 0)

    def test_condition_inconnue_ne_devient_pas_accord(self):
        f = fiche_flex(); f['conditions']['inscription_kvk'] = None
        r = aides.flex_e(f)
        self.assertEqual(r['statut'], 'a_completer')
        self.assertEqual(r['avantage_prudent_eur']['min'], 0)

    def test_fenetre_2026_et_fuseau_neerlandais(self):
        for jour, possible in (('2026-05-06T06:59:59Z', False),
                               ('2026-05-06T07:00:00Z', True),
                               ('2026-10-15T14:59:59Z', True),
                               ('2026-10-15T15:00:01Z', False),
                               ('2027-09-27T15:00:00+02:00', False)):
            with self.subTest(jour=jour):
                f = fiche_flex(); f['date_demande'] = jour
                r = aides.flex_e(f)
                self.assertEqual(r['avantage_prudent_eur']['max'] > 0, possible)

    def test_date_sans_fuseau_refusee(self):
        for valeur in ('2026-09-27', '2026-09-27T15:00:00', True, [], 'invalide'):
            f = fiche_flex(); f['date_demande'] = valeur
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                aides.flex_e(f)

    def test_date_absente_reste_a_completer(self):
        f = fiche_flex(); f['date_demande'] = None
        self.assertEqual(aides.flex_e(f)['statut'], 'a_completer')

    def test_date_hors_plage_convertible_refusee_proprement(self):
        for instant in ('0001-01-01T00:00:00+14:00', '9999-12-31T23:59:59-12:00'):
            with self.subTest(instant=instant), self.assertRaisesRegex(ValueError, 'date_demande'):
                f = fiche_flex()
                f['date_demande'] = instant
                aides.flex_e(f)

    def test_volet_invalide_et_deux_volets_refuses(self):
        for valeur in ('scan,faisabilite', ['scan', 'faisabilite'], None, True):
            f = fiche_flex(); f['volet'] = valeur
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                aides.flex_e(f)


class EIACalcul(unittest.TestCase):
    def test_40_pour_cent_deduction_et_7600_10320_economie(self):
        r = aides.eia(fiche_eia(), True)
        self.assertEqual(r['deduction_base_imposable_eur']['min'], 40000)
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 7600)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 10320)
        self.assertEqual(r['avantage_prudent_eur']['min'], 0)

    def test_subvention_meme_cout_retiree_avant_deduction(self):
        f = fiche_eia(); f['aides_sur_memes_couts_eur'] = {'min': 10000, 'max': 10000}
        r = aides.eia(f, True)
        self.assertEqual(r['assiette_nette_eur']['min'], 90000)
        self.assertEqual(r['deduction_base_imposable_eur']['max'], 36000)
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 6840)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 9288)

    def test_fourchettes_couts_et_aides_bornees_prudemment(self):
        f = fiche_eia(bas=90000, haut=110000)
        f['aides_sur_memes_couts_eur'] = {'min': 10000, 'max': 20000}
        r = aides.eia(f, True)
        self.assertEqual(r['assiette_nette_eur']['min'], 70000)
        self.assertEqual(r['assiette_nette_eur']['max'], 100000)

    def test_absence_montant_aide_ne_signifie_pas_zero(self):
        f = fiche_eia(); f['aides_sur_memes_couts_eur'] = None
        self.assertIsNone(aides.eia(f, True)['avantage_prudent_eur'])

    def test_sans_batterie_zero(self):
        r = aides.eia(fiche_eia(), False)
        self.assertEqual(r['statut'], 'sans_batterie')
        self.assertEqual(r['avantage_prudent_eur']['min'], 0)
        self.assertEqual(r['avantage_prudent_eur']['max'], 0)

    def test_condition_excluante_supprime_aussi_deduction_affichee(self):
        f = fiche_eia(); f['conditions']['materiel_neuf'] = False
        r = aides.eia(f, True)
        self.assertEqual(r['deduction_base_imposable_eur']['max'], 0)

    def test_sans_batterie_aucune_deduction_affichee(self):
        self.assertEqual(aides.eia(fiche_eia(), False)['deduction_base_imposable_eur']['max'], 0)

    def test_ineligibilite_technique_connue_prime_sur_regime_fiscal_distinct(self):
        f = fiche_eia(); f.update(regime_is=False, puissance_kw=4)
        r = aides.eia(f, True)
        self.assertEqual(r['avantage_prudent_eur']['max'], 0)

    def test_assiette_et_aides_restent_visibles_pour_relecture(self):
        f = fiche_eia(bas=90000, haut=110000)
        f['aides_sur_memes_couts_eur'] = {'min': 10000, 'max': 20000}
        r = aides.eia(f, True)
        self.assertEqual(r['couts_avant_aides_eur']['min'], 90000)
        self.assertEqual(r['aides_deduites_eur']['max'], 20000)

    def test_batterie_inconnue_reste_a_completer(self):
        r = aides.eia(fiche_eia(), None)
        self.assertEqual(r['statut'], 'a_completer')
        self.assertEqual(r['avantage_prudent_eur']['min'], 0)

    def test_conditions_communes_non_satisfaites_donnent_zero(self):
        for cle in aides.CONDITIONS_EIA:
            with self.subTest(cle=cle):
                f = fiche_eia(); f['conditions'][cle] = False
                self.assertEqual(aides.eia(f, True)['avantage_prudent_eur']['max'], 0)

    def test_seuils_5_kw_15_kwh_inclus(self):
        f = fiche_eia(); f.update(puissance_kw=5, capacite_kwh=15)
        self.assertEqual(aides.eia(f, True)['statut'], 'conditions_declarees_a_revoir')
        for champ, valeur in (('puissance_kw', 4.999), ('capacite_kwh', 14.999)):
            f = fiche_eia(); f[champ] = valeur
            self.assertEqual(aides.eia(f, True)['avantage_prudent_eur']['max'], 0)

    def test_code_251118_exige_production_strictement_plus_15_kw(self):
        f = fiche_eia('251118'); f['production_crete_kw'] = 15
        self.assertEqual(aides.eia(f, True)['avantage_prudent_eur']['max'], 0)
        f['production_crete_kw'] = 15.001
        self.assertGreater(aides.eia(f, True)['avantage_prudent_eur']['max'], 0)

    def test_code_251118_renouvelable_et_meme_raccordement(self):
        for champ in ('production_renouvelable', 'meme_raccordement'):
            f = fiche_eia('251118'); f['conditions'][champ] = False
            self.assertEqual(aides.eia(f, True)['avantage_prudent_eur']['max'], 0)

    def test_code_260101_pilotage_et_logiciel_marche(self):
        for champ in ('pilotage_automatique_marche', 'logiciel_connecte_marche'):
            f = fiche_eia(); f['conditions'][champ] = False
            self.assertEqual(aides.eia(f, True)['avantage_prudent_eur']['max'], 0)

    def test_conditions_autre_code_ne_bloquent_pas(self):
        f = fiche_eia(); f['conditions']['meme_raccordement'] = False
        self.assertEqual(aides.eia(f, True)['statut'], 'conditions_declarees_a_revoir')
        f = fiche_eia('251118'); f['conditions']['logiciel_connecte_marche'] = False
        self.assertEqual(aides.eia(f, True)['statut'], 'conditions_declarees_a_revoir')

    def test_code_absent_ou_non_pris_en_charge(self):
        f = fiche_eia(); f['code'] = None
        self.assertEqual(aides.eia(f, True)['statut'], 'a_completer')
        for code in ('251118/260101', 260101, 'inconnu', True):
            f = fiche_eia(); f['code'] = code
            with self.subTest(code=code), self.assertRaises(ValueError):
                aides.eia(f, True)

    def test_millesime_2025_ne_prend_pas_codes_2026_sans_declarer_ineligibilite(self):
        f = fiche_eia(); f.update(date_engagement='2025-09-01', date_declaration='2025-09-27')
        r = aides.eia(f, True)
        self.assertEqual(r['statut'], 'hors_champ_millesime')
        self.assertIsNone(r['avantage_prudent_eur'])
        self.assertIsNone(r['deduction_base_imposable_eur'])

    def test_delai_trois_mois_depuis_engagement_fin_de_mois(self):
        f = fiche_eia(); f.update(date_engagement='2026-01-31', date_declaration='2026-04-30')
        r = aides.eia(f, True)
        self.assertEqual(r['date_limite_indicative'], '2026-04-30')
        self.assertEqual(r['statut'], 'conditions_declarees_a_revoir')

    def test_date_avant_engagement_refusee(self):
        f = fiche_eia(); f['date_declaration'] = '2026-08-31'
        with self.assertRaises(ValueError):
            aides.eia(f, True)

    def test_date_declaration_invalide_refusee_meme_sans_engagement(self):
        for date_invalide in ('2026-02-30', '20260927', True, []):
            f = fiche_eia(); f.update(date_engagement=None, date_declaration=date_invalide)
            with self.subTest(date=date_invalide), self.assertRaises(ValueError):
                aides.eia(f, True)

    def test_api_eia_directe_refuse_booleens_implicites(self):
        for valeur in ('false', 'true', 0, 1, [], {}):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                aides.eia(fiche_eia(), valeur)

    def test_declaration_hors_delai_ne_conserve_pas_avantage(self):
        f = fiche_eia(); f['date_declaration'] = '2027-02-01'
        r = aides.eia(f, True)
        self.assertEqual(r['statut'], 'non_eligible_selon_declarations')
        self.assertEqual(r['avantage_prudent_eur']['min'], 0)
        self.assertEqual(r['avantage_prudent_eur']['max'], 0)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 0)
        self.assertEqual(r['deduction_base_imposable_eur']['max'], 0)

    def test_o8_sept_mois_apres_commande_zero_eia(self):
        f = fiche_eia()
        f.update(date_engagement='2026-02-10', date_declaration='2026-09-01')
        r = aides.eia(f, True)
        self.assertEqual(r['avantage_prudent_eur']['max'], 0)
        self.assertEqual(r['deduction_base_imposable_eur']['max'], 0)
        delai = next(c for c in r['controles'] if c['champ'] == 'delai_declaration')
        self.assertEqual(delai['statut'], 'non_satisfaite')

    def test_o8_declaration_absente_reste_inconnue(self):
        f = fiche_eia(); f['date_declaration'] = None
        r = aides.eia(f, True)
        self.assertEqual(r['statut'], 'a_completer')
        self.assertEqual(next(c for c in r['controles'] if c['champ'] == 'delai_declaration')['statut'], 'a_confirmer')

    def test_absence_profit_ne_fabrique_pas_de_remboursement(self):
        f = fiche_eia(); f['deduction_integralement_utilisable'] = False
        r = aides.eia(f, True)
        self.assertEqual(r['statut'], 'a_completer')
        self.assertEqual(r['avantage_prudent_eur']['min'], 0)
        self.assertIn('report fiscal', ' '.join(r['hypotheses']))

    def test_impot_sur_revenu_ne_devient_pas_non_eligibilite_eia(self):
        f = fiche_eia(); f['regime_is'] = False
        r = aides.eia(f, True)
        self.assertEqual(r['statut'], 'hors_champ_calcul_fiscal')
        self.assertIsNone(r['avantage_prudent_eur'])

    def test_minimum_2500_et_fourchette_le_traversant(self):
        r = aides.eia(fiche_eia(bas=2499.99), True)
        self.assertEqual(r['avantage_prudent_eur']['max'], 0)
        r = aides.eia(fiche_eia(bas=2500), True)
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 190)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 258)
        r = aides.eia(fiche_eia(bas=2000, haut=3000), True)
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 0)
        self.assertEqual(r['si_conditions_remplies_eur']['max'], 309.60)

    def test_aide_superieure_cout_refusee(self):
        f = fiche_eia(); f['aides_sur_memes_couts_eur'] = {'min': 100001, 'max': 100001}
        with self.assertRaises(ValueError):
            aides.eia(f, True)

    def test_deduction_traversant_minimum_inclut_aussi_zero(self):
        r = aides.eia(fiche_eia(bas=2000, haut=3000), True)
        self.assertEqual(r['deduction_base_imposable_eur']['min'], 0)
        self.assertEqual(r['deduction_base_imposable_eur']['max'], 1200)
        self.assertEqual(r['si_conditions_remplies_eur']['min'], 0)
        self.assertEqual(r['statut'], 'a_completer')


class AidesEntreesEtSorties(unittest.TestCase):
    def test_objets_racines_invalides_refuses(self):
        for valeur in (None, True, 12, [], 'fiche'):
            for fonction in (aides.preparer, aides.flex_e):
                with self.subTest(valeur=valeur, fonction=fonction.__name__), self.assertRaises(ValueError):
                    fonction(valeur)
            with self.subTest(valeur=valeur, fonction='eia'), self.assertRaises(ValueError):
                aides.eia(valeur, True)

    def test_utilisation_fiscale_refuse_booleens_implicites(self):
        for valeur in ('false', 'true', 0, 1, [], {}):
            f = fiche_eia(); f['deduction_integralement_utilisable'] = valeur
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                aides.eia(f, True)

    def test_fourchettes_invalides_refusees(self):
        for plage in (False, 10000, '10000', [], {}, {'min': 2, 'max': 1},
                      {'min': -1, 'max': 1}, {'min': True, 'max': 1},
                      {'min': float('nan'), 'max': 1}, {'min': 0, 'max': float('inf')},
                      {'min': 0, 'max': 10**400}):
            f = fiche_flex(); f['couts_eligibles_ht_eur'] = plage
            with self.subTest(plage=repr(plage)), self.assertRaises(ValueError):
                aides.flex_e(f)

    def test_booleens_texte_et_entiers_refuses(self):
        for valeur in ('true', 'false', 0, 1, [], {}):
            with self.subTest(valeur=valeur):
                f = fiche_flex(); f['conditions']['inscription_kvk'] = valeur
                with self.assertRaises(ValueError): aides.flex_e(f)
                f = fiche_eia(); f['regime_is'] = valeur
                with self.assertRaises(ValueError): aides.eia(f, True)
                f = fiche_complete(); f['batterie_envisagee'] = valeur
                with self.assertRaises(ValueError): aides.preparer(f)

    def test_structures_conditions_et_pieces_refusees(self):
        for champ in ('conditions', 'pieces'):
            for valeur in (None, True, [], 'texte'):
                f = fiche_flex(); f[champ] = valeur
                with self.subTest(champ=champ, valeur=valeur), self.assertRaises(ValueError):
                    aides.flex_e(f)

    def test_aucun_total_annuel_ponctuel(self):
        r = aides.preparer(fiche_complete())
        self.assertIsNone(r['total_gain_eur'])
        self.assertEqual(set(r['scenarios']), {'avec_batterie', 'sans_batterie'})
        self.assertIn('quart d’heure', ' '.join(r['scenarios']['avec_batterie']))

    def test_dossier_vierge_aucun_gain_invente(self):
        r = aides.preparer(aides.modele())
        for bloc in ('flex_e', 'eia'):
            self.assertEqual(r[bloc]['statut'], 'a_completer')
            self.assertIsNone(r[bloc]['avantage_prudent_eur'])
        json.dumps(r, allow_nan=False)

    def test_conditions_declarees_ne_certifient_pas_les_pieces(self):
        r = aides.preparer(fiche_complete())
        self.assertFalse(r['pieces_authentifiees'])
        self.assertTrue(all(p['statut'] == 'a_fournir' for p in r['flex_e']['pieces']))
        self.assertEqual(r['flex_e']['statut'], 'conditions_declarees_a_revoir')

    def test_reference_de_piece_reste_declaree(self):
        f = fiche_complete(); f['eia']['pieces']['fiscalite'] = 'Note fictive du comptable'
        r = aides.preparer(f)
        p = next(p for p in r['eia']['pieces'] if p['id'] == 'fiscalite')
        self.assertEqual(p['statut'], 'reference_declaree')

    def test_rapport_echappe_html_et_cite_sources(self):
        f = fiche_complete(); f['site'] = '<script>alert(1)</script>'
        texte = aides.rapport(aides.preparer(f))
        self.assertNotIn('<script>', texte)
        self.assertIn('&lt;script&gt;', texte)
        self.assertIn(aides.SOURCES['is'], texte)
        self.assertIn('7,6 à 10,32', texte)
        self.assertIn('Avec batterie', texte)
        self.assertIn('Sans batterie', texte)

    def test_rapport_ne_rend_pas_liens_images_et_tableau_dans_les_references(self):
        f = fiche_complete(); f['site'] = '[cliquer](javascript:alert(1))'
        f['flex_e']['pieces']['devis'] = '![image](https://example.invalid/pixel) | montant fictif'
        texte = aides.rapport(aides.preparer(f))
        self.assertNotIn('[cliquer](javascript:', texte)
        self.assertNotIn('![image](https://', texte)
        self.assertIn('\\| montant fictif', texte)

    def test_ancien_resultat_sans_detail_assiette_reste_lisible(self):
        r = aides.preparer(fiche_complete())
        r['flex_e'].pop('couts_eligibles_ht_eur')
        r['eia'].pop('couts_avant_aides_eur')
        r['eia'].pop('aides_deduites_eur')
        self.assertIn('Non chiffrable', aides.rapport(r))

    def test_entrees_non_modifiees(self):
        f = fiche_complete(); avant = deepcopy(f)
        aides.rapport(aides.preparer(f))
        self.assertEqual(f, avant)

    def test_site_invalide_ne_propage_pas_nan(self):
        f = fiche_complete(); f['site'] = float('nan')
        with self.assertRaises(ValueError):
            aides.preparer(f)

    def test_chaque_avantage_est_fourchette_et_source(self):
        for batterie in (False, True, None):
            r = aides.preparer(fiche_complete(batterie))
            for cle in ('flex_e', 'eia'):
                bloc = r[cle]
                self.assertTrue(bloc['sources'])
                self.assertTrue(bloc['hypotheses'])
                for montant in ('avantage_prudent_eur', 'si_conditions_remplies_eur'):
                    if bloc[montant] is not None:
                        self.assertLessEqual(bloc[montant]['min'], bloc[montant]['max'])
                        self.assertEqual(bloc[montant]['periode'], 'ponctuel')

    def test_assiette_scan_est_visible_dans_dossier(self):
        r = aides.flex_e(fiche_flex(bas=12000, haut=16000))
        self.assertEqual(r['couts_eligibles_ht_eur']['min'], 12000)
        self.assertEqual(r['couts_eligibles_ht_eur']['max'], 16000)


class InvariantsAides(unittest.TestCase):
    """Échantillons reproductibles, oracle arithmétique indépendant en décimal."""
    def centimes(self, nombre):
        return float(nombre.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))

    def test_scan_200_budgets_plafond_et_proportion(self):
        aleatoire = random.Random(27092026)
        for _ in range(200):
            centimes = aleatoire.randrange(0, 10000000)
            cout = Decimal(centimes) / 100
            r = aides.flex_e(fiche_flex(bas=float(cout)))
            attendu = self.centimes(min(cout / 2, Decimal(10000)))
            self.assertEqual(r['si_conditions_remplies_eur']['max'], attendu)
            self.assertEqual(r['avantage_prudent_eur']['min'], 0)

    def test_faisabilite_200_budgets_minimum_sans_arrondi_force(self):
        aleatoire = random.Random(27092027)
        for _ in range(200):
            cout = Decimal(aleatoire.randrange(0, 50000000)) / 100
            attendu = Decimal(0) if cout < 20000 else min(cout / 2, Decimal(125000))
            r = aides.flex_e(fiche_flex('faisabilite', bas=float(cout)))
            self.assertEqual(r['si_conditions_remplies_eur']['max'], self.centimes(attendu))

    def test_eia_200_assiettes_nettes_codes_et_taux(self):
        aleatoire = random.Random(27092028)
        for _ in range(200):
            cout = Decimal(aleatoire.randrange(250000, 100000000)) / 100
            subvention = Decimal(aleatoire.randrange(0, int(cout * 100) + 1)) / 100
            base = cout - subvention
            f = fiche_eia(bas=float(cout))
            f['aides_sur_memes_couts_eur'] = {'min': float(subvention), 'max': float(subvention)}
            r = aides.eia(f, True)
            attendu = base * Decimal('.4') * Decimal('.258') if base >= 2500 else Decimal(0)
            self.assertEqual(r['si_conditions_remplies_eur']['max'], self.centimes(attendu))

    def test_plus_de_subvention_ne_fait_pas_monter_eia(self):
        precedent = float('inf')
        for montant in range(0, 100001, 1000):
            f = fiche_eia(); f['aides_sur_memes_couts_eur'] = {'min': montant, 'max': montant}
            courant = aides.eia(f, True)['avantage_prudent_eur']['max']
            self.assertLessEqual(courant, precedent)
            precedent = courant


class AidesCommandes(unittest.TestCase):
    def appeler(self, *arguments):
        return subprocess.run([sys.executable, str(Path(__file__).with_name('preparer_subventions.py')), *map(str, arguments)],
                              capture_output=True, text=True, timeout=30)

    def test_modele_et_dossier_vierge(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            self.assertEqual(self.appeler('--modele', rep/'fiche.json').returncode, 0)
            execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
            self.assertEqual(execution.returncode, 0, execution.stderr)
            self.assertTrue((rep/'dossier/subventions.json').exists())
            self.assertTrue((rep/'dossier/dossier-subventions.md').exists())

    def test_dossier_complet_calcul_et_rapport(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            (rep/'fiche.json').write_text(json.dumps(fiche_complete()))
            execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
            self.assertEqual(execution.returncode, 0, execution.stderr)
            r = json.loads((rep/'dossier/subventions.json').read_text())
            self.assertEqual(r['eia']['si_conditions_remplies_eur']['max'], 10320)

    def test_refuse_ecrasement_fiche_et_dossier(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            (rep/'fiche.json').write_text(json.dumps(fiche_complete()))
            avant = (rep/'fiche.json').read_text()
            self.assertNotEqual(self.appeler('--modele', rep/'fiche.json').returncode, 0)
            self.assertEqual((rep/'fiche.json').read_text(), avant)
            (rep/'dossier').mkdir(); (rep/'dossier/temoin').write_text('conserver')
            self.assertNotEqual(self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier').returncode, 0)
            self.assertEqual((rep/'dossier/temoin').read_text(), 'conserver')

    def test_erreur_json_refuse_sans_sortie(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep); (rep/'fiche.json').write_text('{')
            self.assertNotEqual(self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier').returncode, 0)
            self.assertFalse((rep/'dossier').exists())

    def test_json_ambigu_refuse_avant_creation_dossier(self):
        for texte in ('{"batterie_envisagee": false, "batterie_envisagee": true}',
                      '{"annexe": {"montant": 0, "montant": 10000}}',
                      '{"annexe": NaN}', '{"annexe": Infinity}',
                      '{"annexe": -Infinity}', '{"annexe": 1e9999}',
                      r'{"annexe":"\ud800"}'):
            with self.subTest(texte=texte), tempfile.TemporaryDirectory() as rep:
                rep = Path(rep)
                texte = texte[:-1] + ',' + json.dumps(fiche_complete())[1:]
                (rep/'fiche.json').write_text(texte, encoding='utf-8')
                execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
                self.assertEqual(execution.returncode, 2, execution.stderr)
                self.assertNotIn('Traceback', execution.stderr)
                self.assertFalse((rep/'dossier').exists())

    def test_json_bom_et_accents_acceptes(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            donnees = fiche_complete()
            donnees['site'] = 'Entrepôt fictif, bâtiment été'
            (rep/'fiche.json').write_text(json.dumps(donnees, ensure_ascii=False), encoding='utf-8-sig')
            execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
            self.assertEqual(execution.returncode, 0, execution.stderr)
            self.assertEqual(json.loads((rep/'dossier/subventions.json').read_text())['site'], donnees['site'])

    def test_arguments_de_modele_incompatibles_refuses(self):
        for option in ('--fiche', '--sortie'):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as rep:
                modele = Path(rep)/'modele.json'
                execution = self.appeler('--modele', modele, option, Path(rep)/'autre')
                self.assertEqual(execution.returncode, 2, execution.stderr)
                self.assertFalse(modele.exists())

    def test_fiche_trop_grande_et_absente_refusees_sans_sortie(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            for contenu in (None, '{}' + ' ' * (1024 * 1024)):
                if contenu is not None:
                    (rep/'fiche.json').write_text(contenu)
                execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
                self.assertEqual(execution.returncode, 2, execution.stderr)
                self.assertFalse((rep/'dossier').exists())


if __name__ == '__main__':
    unittest.main()
