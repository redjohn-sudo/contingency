"""Tests du repérage GOTORK, de ses limites et du dossier de concertation."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

import gotork


@lru_cache(maxsize=6)
def calendrier(jour='2026-09-27'):
    fin = date.fromisoformat(jour)
    debut = gotork._decaler_mois(fin, -12)
    local = ZoneInfo('Europe/Amsterdam')
    instant = datetime.combine(debut, time(), local).astimezone(timezone.utc)
    limite = datetime.combine(fin, time(), local).astimezone(timezone.utc)
    instants = []
    while instant < limite:
        instant += timedelta(minutes=15)
        instants.append(instant.isoformat())
    return tuple(instants)


def fiche(**changements):
    resultat = gotork.modele()
    resultat.update(site='Site fictif pour tests', pays='NL', date_analyse='2026-09-27',
                    reseau='MT', tension_kv=20, direction='soutirage',
                    congestion_confirmee=True, source_congestion='Rapport fictif du gestionnaire',
                    contrat_ferme=True, gtv_kw=1000, source_gtv='ATO fictif, page 2',
                    gtv_constant_sur_periode=True, source_mesures='Export compteur fictif')
    resultat.update(changements)
    return resultat


class GotorkSeuils(unittest.TestCase):
    def calcul(self, pointe, **changements):
        configuration = fiche(**changements)
        dates = calendrier(configuration['date_analyse'])
        return gotork.analyser([pointe] * len(dates), dates, configuration)

    def test_decision_2024_et_aucune_perte_certaine(self):
        r = self.calcul(500)
        self.assertEqual(r['date_decision'], '2024-04-16')
        self.assertEqual(r['date_entree_vigueur'], '2024-04-26')
        self.assertFalse(r['perte_certaine'])
        self.assertIsNone(r['nouveau_gtv_kw'])
        self.assertIn('stcrt-2024-13531', r['sources'][0])

    def test_exactement_50_pour_cent_declenche_le_signal(self):
        r = self.calcul(500)
        self.assertEqual(r['statut'], 'risque_conditionnel')
        self.assertTrue(r['mesures']['seuil_relatif_atteint'])
        self.assertFalse(r['mesures']['seuil_absolu_atteint'])

    def test_juste_plus_de_50_pour_cent_ne_declenche_pas_seul(self):
        r = self.calcul(500.001)
        self.assertEqual(r['statut'], 'seuil_non_atteint')

    def test_un_mw_exact_declenche_meme_au_dessus_de_50_pour_cent(self):
        r = self.calcul(2000, gtv_kw=3000)
        self.assertFalse(r['mesures']['seuil_relatif_atteint'])
        self.assertTrue(r['mesures']['seuil_absolu_atteint'])
        self.assertEqual(r['statut'], 'risque_conditionnel')

    def test_juste_moins_de_un_mw_inutilise(self):
        self.assertEqual(self.calcul(2000.001, gtv_kw=3000)['statut'], 'seuil_non_atteint')

    def test_seuil_haute_tension_sous_110_kv(self):
        r = self.calcul(2000, gtv_kw=3000, reseau='HT', tension_kv=109.999)
        self.assertEqual(r['mesures']['seuil_absolu_kw'], 1000)
        self.assertEqual(r['statut'], 'risque_conditionnel')

    def test_a_110_kv_un_mw_ne_suffit_plus(self):
        r = self.calcul(29000, gtv_kw=30000, reseau='HT', tension_kv=110)
        self.assertEqual(r['mesures']['seuil_absolu_kw'], 10000)
        self.assertEqual(r['statut'], 'seuil_non_atteint')

    def test_a_110_kv_dix_mw_exacts_declenchent(self):
        r = self.calcul(20000, gtv_kw=30000, reseau='HT', tension_kv=110)
        self.assertTrue(r['mesures']['seuil_absolu_atteint'])
        self.assertEqual(r['statut'], 'risque_conditionnel')

    def test_a_380_kv_seuil_relatif_reste_applicable(self):
        r = self.calcul(5000, gtv_kw=10000, reseau='HT', tension_kv=380)
        self.assertTrue(r['mesures']['seuil_relatif_atteint'])
        self.assertFalse(r['mesures']['seuil_absolu_atteint'])
        self.assertEqual(r['statut'], 'risque_conditionnel')

    def test_la_pointe_compte_et_non_la_moyenne(self):
        dates = calendrier()
        valeurs = [100.] * len(dates)
        valeurs[len(valeurs) // 2] = 900.
        r = gotork.analyser(valeurs, dates, fiche())
        self.assertEqual(r['statut'], 'seuil_non_atteint')
        self.assertEqual(r['mesures']['pointe_12_mois_kw'], 900)

    def test_depassement_gtv_ne_devient_pas_une_reserve_negative(self):
        r = self.calcul(1200)
        self.assertEqual(r['statut'], 'seuil_non_atteint')
        self.assertEqual(r['mesures']['inutilise_kw'], 0)

    def test_profil_nul_est_mesurable(self):
        self.assertEqual(self.calcul(0)['statut'], 'risque_conditionnel')

    def test_sens_injection_explicitement_documente(self):
        self.assertEqual(self.calcul(400, direction='injection')['statut'], 'risque_conditionnel')

    def test_annee_avec_jour_bissextile(self):
        r = self.calcul(400, date_analyse='2025-02-28')
        self.assertEqual(r['mesures']['nombre_quarts'], 366 * 96)
        self.assertEqual(r['periode_attendue']['debut_inclus'], '2024-02-28')

    def test_douze_mois_peuvent_avoir_une_heure_de_moins(self):
        r = self.calcul(400, date_analyse='2025-03-31')
        self.assertEqual(r['mesures']['nombre_quarts'], 365 * 96 - 4)

    def test_douze_mois_peuvent_avoir_une_heure_de_plus(self):
        r = self.calcul(400, date_analyse='2025-10-27')
        self.assertEqual(r['mesures']['nombre_quarts'], 365 * 96 + 4)


class GotorkEntrees(unittest.TestCase):
    def calcul(self, configuration=None, valeurs=None, dates=None):
        dates = calendrier() if dates is None else dates
        valeurs = [400.] * len(dates) if valeurs is None else valeurs
        return gotork.analyser(valeurs, dates, configuration or fiche())

    def test_aucune_donnee_reste_indetermine(self):
        r = gotork.analyser([], [], gotork.modele())
        self.assertEqual(r['statut'], 'indetermine')
        self.assertIsNone(r['mesures'])

    def test_fiche_racine_non_objet_refusee(self):
        for configuration in (None, True, 12, 'fiche', []):
            with self.subTest(configuration=configuration), self.assertRaises(ValueError):
                gotork.analyser([], [], configuration)

    def test_structure_profil_et_horodatages_invalide(self):
        for valeurs, dates in ((None, []), ([], None), ('400', []), ([], 'date'),
                              ([], []), ([400], []), ([400] * 35141, ['date'] * 35141)):
            with self.subTest(type_valeurs=type(valeurs).__name__, type_dates=type(dates).__name__):
                r = gotork.analyser(valeurs, dates, fiche())
                self.assertEqual(r['statut'], 'indetermine')
                self.assertIsNone(r['mesures'])

    def test_bt_hors_congestion_non_ferme_et_hors_pays(self):
        for changement in ({'reseau': 'BT'}, {'congestion_confirmee': False},
                           {'contrat_ferme': False}, {'pays': 'FR'}):
            with self.subTest(changement=changement):
                r = self.calcul(fiche(**changement))
                self.assertEqual(r['statut'], 'hors_champ_declare')
                self.assertIsNone(r['mesures'])

    def test_bool_textuel_ou_entier_ne_confirme_pas(self):
        for champ in ('congestion_confirmee', 'contrat_ferme', 'gtv_constant_sur_periode'):
            for valeur in (None, 'true', 'false', 1, 0, []):
                with self.subTest(champ=champ, valeur=valeur):
                    self.assertEqual(self.calcul(fiche(**{champ: valeur}))['statut'], 'indetermine')

    def test_sources_et_reseau_manquants_bloquent(self):
        for champ in ('source_gtv', 'source_congestion', 'source_mesures', 'reseau', 'direction', 'pays'):
            r = self.calcul(fiche(**{champ: None}))
            self.assertEqual(r['statut'], 'indetermine', champ)
            self.assertIn(champ, r['manques'])

    def test_tension_ht_obligatoire_et_mt_non_contradictoire(self):
        for changement in ({'reseau': 'HT', 'tension_kv': None}, {'reseau': 'HT', 'tension_kv': 0},
                           {'reseau': 'HT', 'tension_kv': True}, {'reseau': 'MT', 'tension_kv': 110}):
            with self.subTest(changement=changement):
                self.assertEqual(self.calcul(fiche(**changement))['statut'], 'indetermine')

    def test_gtv_invalide_ne_chiffre_rien(self):
        for valeur in (None, False, '1000', -1, 0, float('inf'), float('nan'), 10**400):
            with self.subTest(valeur=repr(valeur)):
                r = self.calcul(fiche(gtv_kw=valeur))
                self.assertEqual(r['statut'], 'indetermine')
                self.assertIsNone(r['mesures'])
                json.dumps(r, allow_nan=False)

    def test_puissances_invalides_ne_chiffrent_rien(self):
        dates = calendrier()
        for valeur in (None, True, '400', -1, float('inf'), float('nan'), 10**400):
            with self.subTest(valeur=repr(valeur)):
                valeurs = [400.] * len(dates)
                valeurs[123] = valeur
                self.assertEqual(self.calcul(valeurs=valeurs)['statut'], 'indetermine')

    def test_annee_ancienne_ne_remplace_pas_douze_mois_precedents(self):
        self.assertEqual(self.calcul(dates=calendrier('2025-09-27'))['statut'], 'indetermine')

    def test_un_quart_manquant_aux_bornes_bloque(self):
        for dates in (calendrier()[1:], calendrier()[:-1]):
            self.assertEqual(self.calcul(dates=dates)['statut'], 'indetermine')

    def test_trou_doublon_et_inversion_bloquent(self):
        for mode in ('trou', 'doublon', 'inversion'):
            dates = list(calendrier())
            if mode == 'trou':
                dates.pop(250)
            elif mode == 'doublon':
                dates[250] = dates[249]
            else:
                dates[250], dates[251] = dates[251], dates[250]
            self.assertEqual(self.calcul(dates=dates)['statut'], 'indetermine', mode)

    def test_sans_fuseau_et_hors_quart_bloquent(self):
        for date_invalide in ('2025-09-26T22:15:00', '2025-09-26T22:16:00+00:00'):
            dates = list(calendrier()); dates[0] = date_invalide
            self.assertEqual(self.calcul(dates=dates)['statut'], 'indetermine')

    def test_decalages_locaux_aux_changements_heure_acceptes(self):
        dates = [datetime.fromisoformat(d).astimezone(ZoneInfo('Europe/Amsterdam')).isoformat()
                 for d in calendrier()]
        self.assertEqual(self.calcul(dates=dates)['statut'], 'risque_conditionnel')

    def test_date_invalide_et_avant_entree_en_vigueur(self):
        for jour in (None, True, '20260927', '2026-02-30', '2024-04-25'):
            self.assertEqual(self.calcul(fiche(date_analyse=jour))['statut'], 'indetermine')

    def test_affaire_lienden_2021_ne_recoit_pas_gotork_2024(self):
        # Données documentaires publiques ACM/25/198794 ; aucune courbe réelle.
        # On vérifie uniquement l'absence d'application rétroactive de GOTORK.
        configuration = fiche(site='Van Tuijl, Lienden : faits de 2021',
                              date_analyse='2021-09-21', gtv_kw=2788,
                              direction='injection', source_gtv='ATO 2009 relaté par ACM le 18/06/2026')
        r = gotork.analyser([], [], configuration)
        self.assertEqual(r['statut'], 'indetermine')
        self.assertIsNone(r['nouveau_gtv_kw'])
        self.assertFalse(r['perte_certaine'])
        self.assertTrue(any('entrée en vigueur' in m for m in r['manques']))

    def test_pas_de_modification_des_entrees(self):
        configuration = fiche()
        configuration['besoins_futurs'] = [{'description': 'Projet fictif', 'puissance_kw': 900,
                                          'date_mise_service': '2027-03-01', 'reference': 'Devis fictif'}]
        avant = deepcopy(configuration)
        self.calcul(configuration)
        self.assertEqual(configuration, avant)

    def test_site_non_textuel_refuse(self):
        for valeur in (True, 25, [], {}, float('nan')):
            with self.subTest(valeur=repr(valeur)), self.assertRaises(ValueError):
                self.calcul(fiche(site=valeur))

    def test_empreinte_change_avec_une_mesure(self):
        valeurs = [400.] * len(calendrier())
        a = self.calcul(valeurs=valeurs)
        valeurs[123] = 401.
        b = self.calcul(valeurs=valeurs)
        self.assertNotEqual(a['mesures']['sha256'], b['mesures']['sha256'])


class GotorkDefense(unittest.TestCase):
    def calcul(self, **changements):
        return gotork.analyser([400.] * len(calendrier()), calendrier(), fiche(**changements))

    def test_besoin_futur_documente_ne_prononce_pas_exemption(self):
        r = self.calcul(besoins_futurs=[{'description': 'Nouvelle ligne fictive', 'puissance_kw': 1000,
                                       'date_mise_service': '2027-05-01', 'reference': 'Commande fictive'}])
        self.assertEqual(r['statut'], 'risque_conditionnel')
        self.assertEqual(r['dossier_defense']['besoins_futurs'][0]['statut'], 'a_examiner')
        self.assertFalse(r['pieces_authentifiees'])
        self.assertIsNone(r['nouveau_gtv_kw'])

    def test_date_projet_invalide_reste_incomplete(self):
        r = self.calcul(besoins_futurs=[{'description': 'Projet', 'puissance_kw': 500,
                                       'date_mise_service': '2027-02-30', 'reference': 'Devis'}])
        self.assertEqual(r['dossier_defense']['besoins_futurs'][0]['statut'], 'incomplet')

    def test_projet_numerique_invalide_reste_json_fini(self):
        r = self.calcul(besoins_futurs=[{'description': 'Projet', 'puissance_kw': float('nan'),
                                       'date_mise_service': '2027-01-01', 'reference': 'Devis'}])
        self.assertEqual(r['dossier_defense']['besoins_futurs'][0]['statut'], 'incomplet')
        json.dumps(r, allow_nan=False)

    def test_champs_projet_invalides_ne_polluent_pas_le_json(self):
        for champ in ('description', 'puissance_kw', 'reference', 'date_mise_service'):
            for invalide in (float('nan'), float('inf'), True, ['texte']):
                projet = {'description': 'Projet', 'puissance_kw': 500,
                          'date_mise_service': '2027-01-01', 'reference': 'Devis'}
                projet[champ] = invalide
                with self.subTest(champ=champ, invalide=repr(invalide)):
                    r = self.calcul(besoins_futurs=[projet])
                    self.assertEqual(r['dossier_defense']['besoins_futurs'][0]['statut'], 'incomplet')
                    json.dumps(r, allow_nan=False)

    def test_structure_besoins_futurs_invalide_refusee(self):
        for projets in ('Projet à lancer', True, {}, [None], ['Projet sans champs']):
            with self.subTest(projets=projets), self.assertRaises(ValueError):
                self.calcul(besoins_futurs=projets)

    def test_structure_justificatifs_exception_invalide_refusee(self):
        for pieces in ('Note de sécurité', True, {}, [True], [None]):
            with self.subTest(pieces=pieces), self.assertRaises(ValueError):
                self.calcul(justificatifs_exception=pieces)

    def test_notification_deux_mois_et_compte_rendu(self):
        r = self.calcul(date_notification='2026-07-31', source_notification='Lettre fictive')
        self.assertEqual(r['concertation_avant_date_indicative'], '2026-09-30')
        self.assertIn('indicative', r['note_delai'])
        self.assertIn('dix jours ouvrés', ' '.join(r['procedure']))

    def test_notification_future_ou_non_sourcee_bloque_date(self):
        for changement in ({'date_notification': '2026-09-28', 'source_notification': 'Lettre'},
                           {'date_notification': '2024-04-25', 'source_notification': 'Lettre'},
                           {'date_notification': '2026-08-01', 'source_notification': ''}):
            r = self.calcul(**changement)
            self.assertNotIn('concertation_avant_date_indicative', r)

    def test_pointe_24_mois_documentee_et_exceptions_a_examiner(self):
        r = self.calcul(pointe_24_mois_kw=900, source_pointe_24_mois='Calcul fictif',
                       justificatifs_exception=['Note de sécurité fictive'])
        defense = r['dossier_defense']
        self.assertEqual(defense['pointe_24_mois']['kw'], 900)
        self.assertEqual(defense['exceptions_a_examiner'], ['Note de sécurité fictive'])
        self.assertEqual(r['statut'], 'risque_conditionnel')

    def test_pointe_24_mois_sans_piece_ne_devient_pas_preuve(self):
        r = self.calcul(pointe_24_mois_kw=900)
        self.assertIsNone(r['dossier_defense']['pointe_24_mois'])

    def test_rapport_echappe_html_et_garde_sources(self):
        r = self.calcul(site='<script>alert(1)</script>')
        texte = gotork.rapport(r)
        self.assertNotIn('<script>', texte)
        self.assertIn('&lt;script&gt;', texte)
        self.assertIn(gotork.SOURCE, texte)
        self.assertIn('aucune perte de droit', texte)

    def test_rapport_indique_la_periode_mesuree(self):
        texte = gotork.rapport(self.calcul())
        self.assertIn('2025-09-27', texte)
        self.assertIn('2026-09-27', texte)
        self.assertIn('Europe/Amsterdam', texte)

    def test_rapport_ne_transforme_pas_une_reference_en_lien_actif(self):
        r = self.calcul(site='[cliquer](javascript:alert(1))',
                       source_gtv='![image](https://example.invalid/pixel)')
        texte = gotork.rapport(r)
        self.assertNotIn('[cliquer](javascript:', texte)
        self.assertNotIn('![image](https://', texte)

    def test_rapport_avec_notification_projets_et_pointe_24_mois(self):
        r = self.calcul(date_notification='2026-07-31', source_notification='Lettre',
                       pointe_24_mois_kw=800, source_pointe_24_mois='Relevé',
                       besoins_futurs=[{'description': 'Ligne à installer', 'puissance_kw': 950,
                                        'date_mise_service': '2027-05-01', 'reference': 'Commande'},
                                       {'description': 'Extension non chiffrée'}])
        rendu = gotork.rapport(r)
        self.assertIn('2026-09-30', rendu)
        self.assertIn('800 kW', rendu)
        self.assertIn('950 kW', rendu)
        self.assertIn('Justification incomplète', rendu)
        self.assertNotIn('None kW', rendu)

    def test_rapport_vierge_affiche_donnees_a_completer(self):
        self.assertIn('Données à compléter', gotork.rapport(gotork.analyser([], [], gotork.modele())))


class GotorkCommande(unittest.TestCase):
    def appeler(self, *arguments):
        return subprocess.run([sys.executable, str(Path(__file__).with_name('preparer_gotork.py')), *map(str, arguments)],
                              capture_output=True, text=True, timeout=30)

    def test_modele_et_dossier_vierge(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            self.assertEqual(self.appeler('--modele', rep/'fiche.json').returncode, 0)
            execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
            self.assertEqual(execution.returncode, 0, execution.stderr)
            r = json.loads((rep/'dossier/gotork.json').read_text())
            self.assertEqual(r['statut'], 'indetermine')
            self.assertTrue((rep/'dossier/dossier-defense.md').exists())

    def test_ne_remplace_pas_une_fiche_existante(self):
        with tempfile.TemporaryDirectory() as rep:
            cible = Path(rep)/'fiche.json'; cible.write_text('texte existant')
            self.assertNotEqual(self.appeler('--modele', cible).returncode, 0)
            self.assertEqual(cible.read_text(), 'texte existant')

    def test_csv_complet_produit_dossier_et_statut(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            (rep/'fiche.json').write_text(json.dumps(fiche()))
            (rep/'profil.csv').write_text('fin_intervalle,puissance_kw\n' + ''.join(f'{d},400\n' for d in calendrier()))
            execution = self.appeler('--fiche', rep/'fiche.json', '--profil', rep/'profil.csv', '--sortie', rep/'dossier')
            self.assertEqual(execution.returncode, 0, execution.stderr)
            self.assertEqual(json.loads(execution.stdout)['statut'], 'risque_conditionnel')

    def test_csv_colonnes_incorrectes_refuse_sans_sortie(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            (rep/'fiche.json').write_text(json.dumps(fiche()))
            (rep/'profil.csv').write_text('fin_intervalle,puissance_kw\n2026-01-01T00:00Z,4,5\n')
            execution = self.appeler('--fiche', rep/'fiche.json', '--profil', rep/'profil.csv', '--sortie', rep/'dossier')
            self.assertNotEqual(execution.returncode, 0)
            self.assertFalse((rep/'dossier').exists())

    def test_json_ambigu_refuse_avant_creation_dossier(self):
        for texte in ('{"gtv_kw": 1000, "gtv_kw": 2000}',
                      '{"annexe": {"source": "A", "source": "B"}}',
                      '{"annexe": NaN}', '{"annexe": Infinity}',
                      '{"annexe": -Infinity}', '{"annexe": 1e9999}',
                      r'{"site":"\ud800"}'):
            with self.subTest(texte=texte), tempfile.TemporaryDirectory() as rep:
                rep = Path(rep)
                (rep/'fiche.json').write_text(texte, encoding='utf-8')
                execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
                self.assertEqual(execution.returncode, 2, execution.stderr)
                self.assertNotIn('Traceback', execution.stderr)
                self.assertFalse((rep/'dossier').exists())

    def test_json_bom_et_accents_acceptes(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            donnees = gotork.modele()
            donnees['site'] = 'Entrepôt fictif, bâtiment été'
            (rep/'fiche.json').write_text(json.dumps(donnees, ensure_ascii=False), encoding='utf-8-sig')
            execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
            self.assertEqual(execution.returncode, 0, execution.stderr)
            self.assertEqual(json.loads((rep/'dossier/gotork.json').read_text())['site'], donnees['site'])

    def test_arguments_de_modele_incompatibles_refuses(self):
        for option in ('--fiche', '--profil', '--sortie'):
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

    def test_csv_structure_invalide_refusee_sans_sortie(self):
        for contenu in ('', 'puissance_kw,fin_intervalle\n400,date\n',
                        'fin_intervalle,puissance_kw\n2026-01-01T00:00Z\n',
                        'fin_intervalle,puissance_kw\n"citation non fermée\n',
                        'fin_intervalle,puissance_kw\n2026-01-01T00:00Z,texte\n'):
            with self.subTest(contenu=contenu), tempfile.TemporaryDirectory() as rep:
                rep = Path(rep)
                (rep/'fiche.json').write_text(json.dumps(fiche()))
                (rep/'profil.csv').write_text(contenu)
                execution = self.appeler('--fiche', rep/'fiche.json', '--profil', rep/'profil.csv', '--sortie', rep/'dossier')
                self.assertEqual(execution.returncode, 2, execution.stderr)
                self.assertFalse((rep/'dossier').exists())

    def test_dossier_existant_preserve(self):
        with tempfile.TemporaryDirectory() as rep:
            rep = Path(rep)
            (rep/'fiche.json').write_text(json.dumps(gotork.modele()))
            (rep/'dossier').mkdir()
            (rep/'dossier/gotork.json').write_text('preuve conservée')
            execution = self.appeler('--fiche', rep/'fiche.json', '--sortie', rep/'dossier')
            self.assertEqual(execution.returncode, 2, execution.stderr)
            self.assertEqual((rep/'dossier/gotork.json').read_text(), 'preuve conservée')
            self.assertFalse((rep/'dossier/dossier-defense.md').exists())


if __name__ == '__main__':
    unittest.main()
