"""Dossiers fictifs explicites, calculs annuels vérifiables et pièces manquantes."""
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimisation_contrat import (analyser_annee, comparer_contrats, programme_annuel,
                                  cout_transport, remuneration_cbc, depassements, verifier_assiette_tarif)


def preuve(valeur):
    return {'valeur': valeur, 'source': 'Pièce FICTIVE de test', 'statut': 'verifie',
            'verifie_par': 'Test synthétique', 'date_verification': '2026-09-27'}


def annee(annee=2025, puissance=100):
    zone = ZoneInfo('Europe/Amsterdam')
    debut = datetime(annee, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    fin = datetime(annee + 1, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    n = int((fin - debut).total_seconds() / 900)
    return [puissance] * n, [(debut + timedelta(minutes=15 * (i + 1))).isoformat() for i in range(n)]


def tarif():
    return {'gestionnaire': 'enexis', 'categorie': 'MS-exemple', 'annee': 2026,
            'categorie_code': 'e', 'assiette_pointes': 'mensuelle_non_ponderee',
            'contrat_eur_kw_an': 20, 'pointe_eur_kw_mois': 2,
            'energie_eur_kwh': .1, 'fixe_transport_eur_an': 120, 'autres_reseau_eur_an': 240}


def offre(produit='fixe', gtv=100, variable=0):
    return preuve({'gestionnaire': 'enexis', 'tension_kv': 10, 'categorie': 'MS-exemple',
                   'produit': produit, 'gtv_fixe_kw': gtv, 'gtv_variable_kw': variable,
                   'admissibilite_confirmee': True, 'conditions_verifiees': True,
                   'regles_actuelles_verifiees': True, 'baisse_gtv_acceptee': True,
                   'date_effet': '2026-10-01'})


def option(produit='fixe', gtv=100, variable=0):
    o = {'id': 'cible', 'libelle': 'Option fictive', 'produit': produit,
         'gtv_fixe_kw': preuve(gtv), 'categorie': preuve('MS-exemple'),
         'offre': offre(produit, gtv, variable), 'tarif': preuve(tarif()),
         'couts_complementaires_eur_an': preuve(0), 'couts_exhaustifs': preuve(True)}
    if produit in ('tijdsblok', 'volledig_variabel', 'tijdsduur'):
        o.update(gtv_variable_kw=preuve(variable), part_variable_facturee=preuve(.25))
    return o


def plage(debut=0, fin=24, plafond=110):
    return {'debut_heure': debut, 'fin_heure': fin, 'mois': list(range(1, 13)),
            'jours': list(range(7)), 'plafond_kw': plafond}


class Comparateur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.valeurs, cls.dates = annee()
        cls.resume, _, cls.debuts = analyser_annee(cls.valeurs, cls.dates)
        cls.configuration = {
            'provenance': preuve({'nature': 'mesure_individuelle', 'canal': 'afname',
                                  'site_unique': True, 'qualites_controlees': True,
                                  'fuseau_confirme': True, 'sha256_profil': cls.resume['sha256']}),
            'site': preuve({'gestionnaire': 'enexis', 'reseau': 'distribution', 'tension_kv': 10,
                            'grande_connexion': True, 'puissance_raccordement_kw': 200, 'congestion': True}),
            'contrat_actuel': preuve({'produit': 'fixe', 'gtv_kw': 120, 'categorie': 'MS-exemple'}),
            'tarif_actuel': preuve(tarif()), 'couts_actuels_eur_an': preuve(0),
            'couts_actuels_exhaustifs': preuve(True), 'date_comparaison': '2026-10-01',
            'annee_tarifaire': 2026, 'options': [option()]}

    def setUp(self):
        self.c = copy.deepcopy(self.configuration)

    def calcul(self):
        return comparer_contrats(self.valeurs, self.dates, self.c)

    def test_facture_et_ecart_exact(self):
        r = self.calcul()
        self.assertEqual(r['dominante'], 'cible')
        self.assertAlmostEqual(r['options'][0]['cout_annuel_reference_eur'], 92760)
        self.assertAlmostEqual(r['options'][1]['ecart_reference_eur'], 400)
        self.assertEqual(r['profil']['quarts'], 35040)
        self.assertEqual(len(r['profil']['mensuel']), 12)

    def test_nature_actuelle_absente_bloque_tout_chiffrage(self):
        del self.c['contrat_actuel']['valeur']['produit']
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertEqual(r['options'], [])
        self.assertTrue(any('droit entièrement fixe' in m for m in r['manquants']))

    def test_reference_non_fixe_jamais_remplacee_par_fixe(self):
        for produit in ('cbc', 'tijdsblok', 'volledig_variabel', 'tijdsduur', False, [], {}):
            with self.subTest(produit=produit):
                self.c['contrat_actuel']['valeur']['produit'] = produit
                r = self.calcul()
                self.assertIsNone(r['dominante'])
                self.assertEqual(r['options'], [])
                self.assertTrue(any('non prise en charge' in m for m in r['manquants']))

    def test_nombres_non_finis_refuses_dans_les_annotations(self):
        for chemin in [('options', 0, 'tarif', 'source'), ('options', 0, 'libelle'),
                       ('provenance', 'valeur', 'nature'), ('provenance', 'valeur', 'note')]:
            for valeur in (float('nan'), float('inf'), float('-inf')):
                with self.subTest(chemin=chemin, valeur=valeur):
                    self.setUp()
                    cible = self.c
                    for cle in chemin[:-1]:
                        cible = cible[cle]
                    cible[chemin[-1]] = valeur
                    with self.assertRaisesRegex(ValueError, 'objet JSON sans nombre non fini'):
                        self.calcul()

    def test_structure_non_json_refusee(self):
        for valeur in ({1, 2}, object()):
            self.c['note'] = valeur
            with self.assertRaisesRegex(ValueError, 'objet JSON'):
                self.calcul()
        self.c['note'] = self.c
        with self.assertRaisesRegex(ValueError, 'objet JSON'):
            self.calcul()

    def test_texte_nan_accepte_comme_texte(self):
        self.c['options'][0]['libelle'] = 'NaN'
        resultat = self.calcul()
        self.assertEqual(resultat['options'][1]['libelle'], 'NaN')
        self.assertEqual(resultat['dominante'], 'cible')

    def test_cout_implementation_change_le_minimum(self):
        self.c['options'][0]['couts_complementaires_eur_an'] = preuve(500)
        self.assertEqual(self.calcul()['dominante'], 'actuel')

    def test_egalite_pas_de_gagnant_unique(self):
        self.c['options'][0]['couts_complementaires_eur_an'] = preuve(400)
        self.assertIsNone(self.calcul()['dominante'])

    def test_tarif_manquant_bloque_meme_si_autre_option_calculee(self):
        autre = option(); autre['id'] = 'inconnue'; del autre['tarif']
        self.c['options'].append(autre)
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertIsNone(r['options'][2]['cout_annuel_reference_eur'])

    def test_hypothese_calculee_jamais_gagnante(self):
        self.c['options'][0]['tarif']['statut'] = 'hypothese'
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertAlmostEqual(r['options'][1]['ecart_reference_eur'], 400)
        self.assertEqual(r['options'][1]['statut'], 'incomplet')

    def test_validation_partielle_ne_suffit_pas(self):
        for cle in ('source', 'verifie_par', 'date_verification'):
            self.setUp(); del self.c['options'][0]['tarif'][cle]
            self.assertIsNone(self.calcul()['dominante'])

    def test_tension_ou_grande_connexion_absente(self):
        for cle in ('tension_kv', 'grande_connexion'):
            self.setUp(); del self.c['site']['valeur'][cle]
            self.assertIsNone(self.calcul()['dominante'])

    def test_offre_mauvais_site_tarif_ou_produit(self):
        for cle, valeur in [('tension_kv', 20), ('categorie', 'LS'), ('gestionnaire', 'liander'),
                            ('gtv_fixe_kw', True), ('produit', 'cbc'), ('gtv_variable_kw', 20)]:
            self.setUp(); self.c['options'][0]['offre']['valeur'][cle] = valeur
            self.assertIsNone(self.calcul()['dominante'])

    def test_date_absente_future_ou_expiree(self):
        for modification in ({'date_effet': None}, {'date_effet': '2026-11-01'}, {'date_fin': '2026-09-30'}):
            self.setUp(); self.c['options'][0]['offre']['valeur'].update(modification)
            self.assertIsNone(self.calcul()['dominante'])

    def test_regles_non_verifiees_pas_gagnant(self):
        self.c['options'][0]['offre']['valeur']['regles_actuelles_verifiees'] = False
        self.assertIsNone(self.calcul()['dominante'])

    def test_date_fin_mal_formee_jamais_ignoree(self):
        for valeur in (False, 0, '', [], {}, '2026', '2026-13-01'):
            with self.subTest(valeur=valeur):
                self.c['options'][0]['offre']['valeur']['date_fin'] = valeur
                with self.assertRaises(ValueError):
                    self.calcul()

    def test_date_fin_absente_nulle_ou_dernier_jour(self):
        for valeur in (None, '2026-10-01', '2026-10-02'):
            with self.subTest(valeur=valeur):
                self.c['options'][0]['offre']['valeur']['date_fin'] = valeur
                self.assertEqual(self.calcul()['dominante'], 'cible')

    def test_categorie_non_textuelle_ou_vide_refusee(self):
        for categorie in ('', '  ', False, 0, [], {}):
            with self.subTest(categorie=categorie):
                self.c['options'][0]['categorie'] = preuve(categorie)
                self.c['options'][0]['tarif']['valeur']['categorie'] = categorie
                self.c['options'][0]['offre']['valeur']['categorie'] = categorie
                with self.assertRaises(ValueError):
                    self.calcul()

    def test_droit_ferme_non_retabli_automatiquement(self):
        r = self.calcul()['options'][1]
        self.assertIn('NorthC', r['risque_northc'])
        self.c['options'][0]['offre']['valeur']['baisse_gtv_acceptee'] = False
        self.assertIsNone(self.calcul()['dominante'])

    def test_profil_agrege_ou_synthetique_pas_gagnant(self):
        for nature in ('agrege', 'synthetique'):
            self.c['provenance']['valeur']['nature'] = nature
            self.assertIsNone(self.calcul()['dominante'])

    def test_provenance_empreinte_incorrecte(self):
        self.c['provenance']['valeur']['sha256_profil'] = 'autre profil'
        self.assertIsNone(self.calcul()['dominante'])

    def test_profil_annee_incomplete_refuse(self):
        for v, d in [(self.valeurs[:-1], self.dates[:-1]), (self.valeurs, self.dates[1:])]:
            with self.assertRaises(ValueError): analyser_annee(v, d)

    def test_annee_decalee_refusee(self):
        dates = [(datetime.fromisoformat(d) + timedelta(days=1)).isoformat() for d in self.dates]
        with self.assertRaises(ValueError): analyser_annee(self.valeurs, dates)

    def test_annee_bissextile_et_mois_dst(self):
        v, d = annee(2024)
        r, _, debuts = analyser_annee(v, d)
        self.assertEqual(r['quarts'], 35136)
        self.assertEqual(r['mensuel']['2']['quarts'], 29 * 96)
        self.assertEqual(r['mensuel']['3']['quarts'], 31 * 96 - 4)
        self.assertEqual(r['mensuel']['10']['quarts'], 31 * 96 + 4)
        self.assertEqual(debuts[-1].year, 2024)

    def test_valeurs_invalides(self):
        for mauvais in (True, -1, float('nan'), float('inf'), '100', 10**400):
            v = list(self.valeurs); v[0] = mauvais
            with self.assertRaises(ValueError): analyser_annee(v, self.dates)

    def test_tarif_annuel_pas_mensuel(self):
        t = tarif(); t['contrat_eur_kw_an'] = 2.29 * 12
        c = cout_transport(t, self.resume, self.valeurs, 100, 'MS-exemple', 'enexis', 2026)
        self.assertAlmostEqual(c['capacite_eur'], 2748)

    def test_changement_categorie_recalcule_fixe_et_energie(self):
        o = self.c['options'][0]
        o['categorie'] = preuve('autre')
        o['offre']['valeur']['categorie'] = 'autre'
        o['tarif']['valeur'].update(categorie='autre', energie_eur_kwh=.2, fixe_transport_eur_an=240)
        r = self.calcul()
        self.assertEqual(r['dominante'], 'actuel')
        self.assertAlmostEqual(r['options'][1]['cout_transport']['energie_eur'], 175200)

    def test_tarif_mauvaise_categorie_annee_operateur_refuse(self):
        for cle, valeur in [('categorie', 'autre'), ('annee', 2025), ('gestionnaire', 'liander')]:
            self.setUp(); self.c['options'][0]['tarif']['valeur'][cle] = valeur
            with self.assertRaises(ValueError): self.calcul()

    def test_assiette_absente_pas_de_prix_annonce(self):
        del self.c['options'][0]['tarif']['valeur']['assiette_pointes']
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertIsNone(r['options'][1]['cout_annuel_reference_eur'])

    def test_hs_pas_de_pointe_ordinaire(self):
        t = tarif(); t['categorie_code'] = 'b'
        self.assertTrue(any('pondéré' in m for m in verifier_assiette_tarif(t, self.resume, 'fixe', 0)))

    def test_ts_courte_utilisation_pas_de_pointe_mensuelle(self):
        t = tarif(); t['categorie_code'] = 'c'
        for heures in (0, 600):
            r = dict(self.resume, energie_kwh=100 * heures, pointe_kw=100)
            self.assertTrue(any('hebdomadaire' in m for m in verifier_assiette_tarif(t, r, 'fixe', 0)))
        self.assertFalse(verifier_assiette_tarif(t, dict(self.resume, energie_kwh=60001, pointe_kw=100), 'fixe', 0))

    def test_ls_sans_pointe(self):
        t = tarif(); t.update(categorie_code='g', assiette_pointes='aucune', pointe_eur_kw_mois=0)
        self.assertFalse(verifier_assiette_tarif(t, self.resume, 'fixe', 0))
        t['pointe_eur_kw_mois'] = 1
        self.assertTrue(verifier_assiette_tarif(t, self.resume, 'fixe', 0))

    def test_ms_ne_supprime_pas_sa_pointe(self):
        t = tarif(); t.update(assiette_pointes='aucune', pointe_eur_kw_mois=0)
        self.assertTrue(verifier_assiette_tarif(t, self.resume, 'fixe', 0))

    def test_variable_pas_remise_50_pourcent_arbitraire(self):
        for produit in ('volledig_variabel', 'tijdsduur'):
            self.assertTrue(verifier_assiette_tarif(tarif(), self.resume, produit, .5))
            self.assertFalse(verifier_assiette_tarif(tarif(), self.resume, produit, 0))

    def test_tarif_energie_par_quart(self):
        t = tarif(); t['energie_eur_kwh'] = [.2] * len(self.valeurs)
        with self.assertRaises(ValueError): cout_transport(t, self.resume, self.valeurs, 100, 'MS-exemple', 'enexis', 2026)
        t['sha256_profil'] = self.resume['sha256']
        self.assertAlmostEqual(cout_transport(t, self.resume, self.valeurs, 100, 'MS-exemple', 'enexis', 2026)['energie_eur'], 175200)

    def test_depassement_aucune_charge_effacee(self):
        self.c['options'][0]['gtv_fixe_kw'] = preuve(90)
        self.c['options'][0]['offre']['valeur']['gtv_fixe_kw'] = 90
        r = self.calcul()['options'][1]
        self.assertEqual(r['statut'], 'incompatible')
        self.assertEqual(r['depassements']['quarts'], 35040)
        self.assertEqual(r['depassements']['energie_au_dessus_kwh'], 87600)

    def test_reference_actuelle_depassee_prix_inconnu_bloque_ecart(self):
        self.c['contrat_actuel']['valeur']['gtv_kw'] = 90
        r = self.calcul()
        actuel = r['options'][0]
        self.assertEqual(actuel['statut'], 'reference_depassee')
        self.assertFalse(actuel['refus'])
        self.assertEqual(actuel['depassements']['quarts'], 35040)
        self.assertIsNone(actuel['cout_annuel_reference_eur'])
        self.assertIsNone(r['options'][1]['ecart_reference_eur'])
        self.assertIsNone(r['dominante'])

    def test_reference_depassee_correction_documentee(self):
        self.c['contrat_actuel']['valeur']['gtv_kw'] = 90
        self.c['cout_depassement_actuel_eur_an'] = preuve(1000)
        r = self.calcul()
        self.assertEqual(r['options'][0]['statut'], 'reference_depassee')
        self.assertAlmostEqual(r['options'][1]['ecart_reference_eur'], 800)
        self.assertEqual(r['dominante'], 'cible')

    def test_reference_depassee_meme_moins_chere_pas_recommandee(self):
        self.c['contrat_actuel']['valeur']['gtv_kw'] = 90
        self.c['cout_depassement_actuel_eur_an'] = preuve(0)
        r = self.calcul()
        self.assertLess(r['options'][0]['cout_annuel_reference_eur'], r['options'][1]['cout_annuel_reference_eur'])
        self.assertEqual(r['dominante'], 'cible')

    def test_reference_cout_depassement_hypothetique_bloque(self):
        self.c['contrat_actuel']['valeur']['gtv_kw'] = 90
        self.c['cout_depassement_actuel_eur_an'] = preuve(1000) | {'statut': 'hypothese'}
        self.assertIsNone(self.calcul()['dominante'])

    def test_bloc_remise_sur_capacite_seule(self):
        o = option('tijdsblok', 100, 20)
        o['programme'] = preuve({'mode': 'recurrent', 'plages': [plage(0, 6)]})
        self.c['options'] = [o]
        r = self.calcul()['options'][1]
        self.assertEqual(r['capacite_facturee_kw'], 105)
        self.assertEqual(r['cout_transport']['capacite_eur'], 2100)
        self.assertEqual(r['cout_transport']['pointes_eur'], 2400)
        self.assertEqual(r['cout_transport']['energie_eur'], 87600)

    def test_bloc_coefficient_ou_horaire_non_confirme_bloque(self):
        o = option('tijdsblok', 100, 20)
        o['programme'] = preuve({'mode': 'recurrent', 'plages': [plage(0, 6)]})
        o['classement_tarifaire'] = preuve({'puissance_totale_kw': 120, 'categorie': 'MS-exemple', 'categorie_code': 'e'})
        o['part_variable_facturee'] = preuve(.1)
        self.c['options'] = [o]
        self.assertIsNone(self.calcul()['dominante'])
        o['part_variable_facturee'] = preuve(.25)
        self.assertEqual(self.calcul()['dominante'], 'cible')
        o['programme']['valeur']['plages'] = [plage(6, 12)]
        self.assertIsNone(self.calcul()['dominante'])

    def test_classement_bloc_sur_puissance_complete(self):
        o = option('tijdsblok', 100, 20)
        o['programme'] = preuve({'mode': 'recurrent', 'plages': [plage(0, 6)]})
        self.c['options'] = [o]
        self.assertIsNone(self.calcul()['dominante'])
        o['classement_tarifaire'] = preuve({'puissance_totale_kw': 105, 'categorie': 'MS-exemple', 'categorie_code': 'e'})
        self.assertIsNone(self.calcul()['dominante'])
        o['classement_tarifaire']['valeur']['puissance_totale_kw'] = 120
        r = self.calcul()
        self.assertEqual(r['dominante'], 'cible')
        self.assertEqual(r['options'][1]['capacite_facturee_kw'], 105)
        self.assertEqual(r['options'][1]['classement_tarifaire']['puissance_totale_kw'], 120)
        o['classement_tarifaire']['valeur']['categorie_code'] = 'f'
        self.assertIsNone(self.calcul()['dominante'])

    def test_liander_pas_remplacement_meme_offre_declaree(self):
        o = option('tijdsblok', 100, 20)
        o['programme'] = preuve({'mode': 'recurrent', 'plages': [plage(0, 6)]})
        self.c['options'] = [o]
        self.c['site']['valeur'].update(gestionnaire='liander', region='Friesland')
        self.c['tarif_actuel']['valeur']['gestionnaire'] = 'liander'
        o['tarif']['valeur']['gestionnaire'] = 'liander'; o['offre']['valeur']['gestionnaire'] = 'liander'
        r = self.calcul()['options'][1]
        self.assertEqual(r['statut'], 'incompatible')
        self.assertTrue(any('Liander' in refus for refus in r['refus']))

    def test_bloc_heures_entieres(self):
        with self.assertRaises(ValueError):
            programme_annuel({'mode': 'recurrent', 'plages': [plage(0, 6.25)]}, 'tijdsblok', 100, 20, self.debuts, self.resume['sha256'])

    def test_bloc_programme_horodate_ne_contourne_pas_heures_entieres(self):
        with self.assertRaises(ValueError):
            programme_annuel({'mode': 'horodate'}, 'tijdsblok', 100, 20, self.debuts, self.resume['sha256'])

    def test_variable_allocations_inconnues_pas_gagnant(self):
        self.c['options'] = [option('volledig_variabel', 80, 40)]
        self.assertIsNone(self.calcul()['dominante'])

    def test_pas_85_pourcent_meilleurs_quarts(self):
        with self.assertRaises(ValueError):
            programme_annuel({'mode': 'recurrent', 'plages': [plage()]}, 'tijdsduur', 0, 120, self.debuts, self.resume['sha256'])

    def test_programme_lie_empreinte(self):
        with self.assertRaises(ValueError):
            programme_annuel({'mode': 'horodate', 'sha256_profil': 'autre'}, 'cbc', 120, 0, self.debuts, self.resume['sha256'])

    def test_allocation_variable_ne_supprime_pas_droit_ferme(self):
        p = {'mode': 'horodate', 'sha256_profil': self.resume['sha256'],
             'plafonds_kw': [99] * len(self.debuts), 'actifs': [True] * len(self.debuts)}
        with self.assertRaises(ValueError):
            programme_annuel(p, 'volledig_variabel', 100, 20, self.debuts, self.resume['sha256'])

    def test_cbc_jour_entier_perdu(self):
        o = option('cbc', 120)
        o['programme'] = preuve({'mode': 'recurrent', 'plages': [plage(plafond=99)]})
        o['remuneration'] = preuve({'mode': 'jour_actif', 'euros_par_jour': 10,
                                   'annexe1_verifiee': True, 'regle_defaut': 'jour_entier'})
        self.c['options'] = [o]
        r = self.calcul()['options'][1]
        self.assertEqual(r['remuneration_cbc']['brute_eur'], 3650)
        self.assertEqual(r['remuneration_cbc']['perdue_eur'], 3650)
        self.assertEqual(len(r['remuneration_cbc']['jours_perdus']), 365)
        self.assertEqual(r['statut'], 'incompatible')

    def test_un_quart_cbc_annule_tout_le_jour(self):
        dates = self.debuts[:96]
        actifs = [True] * 96
        r = remuneration_cbc({'mode': 'jour_actif', 'euros_par_jour': 100, 'annexe1_verifiee': True,
                             'regle_defaut': 'jour_entier'}, dates, actifs, {'jours': ['2025-01-01']})
        self.assertEqual(r['perdue_eur'], 100)

    def test_cbc_absence_annexe_pas_tarif_invente(self):
        o = option('cbc', 120); o['programme'] = preuve({'mode': 'recurrent', 'plages': [plage()]})
        self.c['options'] = [o]
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertIsNone(r['options'][1]['remuneration_cbc'])

    def test_cbc_conforme_rend_compensation_explicite(self):
        o = option('cbc', 120); o['programme'] = preuve({'mode': 'recurrent', 'plages': [plage()]})
        o['remuneration'] = preuve({'mode': 'jour_actif', 'euros_par_jour': 10,
                                   'annexe1_verifiee': True, 'regle_defaut': 'jour_entier'})
        self.c['options'] = [o]
        r = self.calcul()
        self.assertEqual(r['dominante'], 'cible')
        self.assertEqual(r['options'][1]['ecart_reference_eur'], 3650)

    def test_cbc_annexe_non_verifiee_calcul_conditionnel(self):
        o = option('cbc', 120); o['programme'] = preuve({'mode': 'recurrent', 'plages': [plage()]})
        o['remuneration'] = preuve({'mode': 'jour_actif', 'euros_par_jour': 10,
                                   'annexe1_verifiee': False, 'regle_defaut': 'jour_entier'})
        self.c['options'] = [o]
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertEqual(r['options'][1]['statut'], 'incomplet')
        self.assertTrue(any('Annexe 1' in m for m in r['options'][1]['manquants']))

    def test_defaut_ato_hors_appel_pas_perte_cbc_automatique(self):
        r = depassements([130, 100], self.debuts[:2], [120, 110], [False, True])
        self.assertEqual(r['quarts'], 0)

    def test_zero_explicite_accepte(self):
        t = tarif()
        for cle in ('contrat_eur_kw_an', 'pointe_eur_kw_mois', 'energie_eur_kwh', 'fixe_transport_eur_an', 'autres_reseau_eur_an'):
            t[cle] = 0
        self.assertEqual(cout_transport(t, self.resume, self.valeurs, 0, 'MS-exemple', 'enexis', 2026)['total_eur'], 0)

    def test_identifiant_duplique_refuse(self):
        self.c['options'].append(option())
        with self.assertRaises(ValueError): self.calcul()

    def test_sans_site_retourne_parametres_pas_exception(self):
        del self.c['site']
        r = self.calcul()
        self.assertFalse(r['options'])
        self.assertTrue(r['manquants'])
        self.assertIsNone(r['dominante'])

    def test_date_offre_inferieure_borne_bloque(self):
        self.c['options'][0]['demande_gtv'] = preuve({'date_demande': '2026-09-27', 'categorie_code': 'e',
                                                     'derniere_hausse': '2026-03-01'})
        r = self.calcul()
        self.assertIsNone(r['dominante'])
        self.assertEqual(r['options'][1]['borne_date_gtv']['borne_reglementaire'], '2027-03-01')


class ParcoursContrats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Comparateur.setUpClass()
        cls.csv = 'fin_intervalle,puissance_kw\n' + ''.join(f'{d},{v}\n' for d, v in zip(Comparateur.dates, Comparateur.valeurs))

    def test_api_compare_sans_ia_ni_ecriture_dossier(self):
        from unittest.mock import patch
        from verifier_live import demo_temporaire
        import serveur
        with demo_temporaire() as client, patch.object(serveur, 'extraire_avec_nebius', side_effect=AssertionError('Aucun appel IA')) as ia:
            avant = set(serveur.DOSSIERS.glob('*'))
            r = client.post('/api/contrats/comparer', json={'texte': self.csv, 'configuration': Comparateur.configuration})
            self.assertEqual(r.status_code, 200, r.text[:1000])
            self.assertEqual(r.json()['resultat']['dominante'], 'cible')
            self.assertIn('Coût de référence le plus faible', r.json()['html'])
            self.assertEqual(set(serveur.DOSSIERS.glob('*')), avant)
            ia.assert_not_called()

    def test_api_profil_et_fiche_vide(self):
        from verifier_live import demo_temporaire
        with demo_temporaire() as client:
            r = client.post('/api/contrats/profil', json={'texte': self.csv})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['modele']['provenance']['valeur']['sha256_profil'], r.json()['profil']['sha256'])
            self.assertEqual(r.json()['modele']['provenance']['statut'], 'a_verifier')
            self.assertIsNone(r.json()['modele']['contrat_actuel']['valeur']['produit'])
            r = client.post('/api/contrats/comparer', json={'texte': self.csv, 'configuration': r.json()['modele']})
            self.assertEqual(r.status_code, 200)
            self.assertIsNone(r.json()['resultat']['dominante'])
            self.assertIn('Aucun gagnant financier établi', r.json()['html'])

    def test_api_reference_actuelle_non_fixe_sans_chiffrage(self):
        from verifier_live import demo_temporaire
        configuration = copy.deepcopy(Comparateur.configuration)
        configuration['contrat_actuel']['valeur']['produit'] = 'cbc'
        with demo_temporaire() as client:
            r = client.post('/api/contrats/comparer', json={'texte': self.csv, 'configuration': configuration})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['resultat']['options'], [])
            self.assertIn('référence non prise en charge', r.json()['html'])

    def test_api_annee_incomplete_422(self):
        from verifier_live import demo_temporaire
        with demo_temporaire() as client:
            texte = '\n'.join(self.csv.splitlines()[:97]) + '\n'
            r = client.post('/api/contrats/profil', json={'texte': texte})
            self.assertEqual(r.status_code, 422)
            self.assertIn('année civile complète', r.json()['detail'])

    def test_api_entiers_geants_refuses_sans_erreur_serveur(self):
        from verifier_live import demo_temporaire
        with demo_temporaire() as client:
            for parent, champ in [('site', 'tension_kv'), ('site', 'puissance_raccordement_kw'),
                                  ('tarif_actuel', 'contrat_eur_kw_an')]:
                with self.subTest(champ=champ):
                    configuration = copy.deepcopy(Comparateur.configuration)
                    configuration[parent]['valeur'][champ] = 10**400
                    r = client.post('/api/contrats/comparer', json={'texte': self.csv, 'configuration': configuration})
                    self.assertEqual(r.status_code, 422, r.text[:300])
                    self.assertIn('detail', r.json())

    def test_api_nan_dans_annotation_refuse(self):
        import json
        from verifier_live import demo_temporaire
        configuration = copy.deepcopy(Comparateur.configuration)
        configuration['options'][0]['libelle'] = float('nan')
        with demo_temporaire() as client:
            r = client.post('/api/contrats/comparer', content=json.dumps({'texte': self.csv, 'configuration': configuration}), headers={'content-type': 'application/json'})
            self.assertEqual(r.status_code, 422)
            self.assertIn('nombre non fini', r.json()['detail'])

    def test_api_json_trop_imbrique_refuse(self):
        from verifier_live import demo_temporaire
        from unittest.mock import patch
        import serveur
        with demo_temporaire() as client:
            r = client.post('/api/contrats/profil', content='[' * 2000 + '0' + ']' * 2000, headers={'content-type': 'application/json'})
            self.assertEqual(r.status_code, 422)
            # Certaines dépendances augmentent la limite de récursion Python.
            # Le refus du parseur est donc aussi reproduit explicitement.
            with patch.object(serveur.json, 'loads', side_effect=RecursionError('profondeur')):
                r = client.post('/api/contrats/profil', content='{}', headers={'content-type': 'application/json'})
            self.assertEqual(r.status_code, 422)
            self.assertIn('niveaux imbriqués', r.json()['detail'])

    def test_rapport_echappe_les_sources_et_libelles(self):
        from rapport_contrats import rendre_comparaison
        c = copy.deepcopy(Comparateur.configuration)
        c['options'][0]['libelle'] = '<script>alert(1)</script>'
        c['options'][0]['tarif']['source'] = '<img src=x onerror=alert(1)>'
        r = comparer_contrats(Comparateur.valeurs, Comparateur.dates, c)
        html = rendre_comparaison(r)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;script&gt;', html)

    def test_page_disponible(self):
        from verifier_live import demo_temporaire
        with demo_temporaire() as client:
            r = client.get('/contrats')
            self.assertEqual(r.status_code, 200)
            self.assertIn('Comparer les contrats', r.text)


if __name__ == '__main__':
    unittest.main()
