"""Rapports FR/NL : même calcul, messages complets et données conservées."""
import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verifier_optimisation_contrat as exemples
from optimisation_contrat import comparer_contrats
from rapport_contrats import rendre_comparaison, montant
from messages_contrats_nl import traduire_message, MESSAGES
from regles_contrats_nl import admissibilite, premiere_date_gtv


class RapportContrats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exemples.Comparateur.setUpClass()
        cls.valeurs = exemples.Comparateur.valeurs
        cls.dates = exemples.Comparateur.dates
        cls.configuration = exemples.Comparateur.configuration
        cls.resultat = comparer_contrats(cls.valeurs, cls.dates, cls.configuration)

    def test_fr_par_defaut_et_montants_nl(self):
        self.assertEqual(rendre_comparaison(self.resultat), rendre_comparaison(self.resultat, 'fr'))
        self.assertEqual(montant(1234.56, langue='nl'), '1.234,56 €')
        self.assertEqual(montant(-1234.56, langue='nl'), '-1.234,56 €')
        self.assertEqual(montant(None, langue='nl'), 'Nog in te vullen')

    def test_nl_sans_modification_des_calculs(self):
        avant = copy.deepcopy(self.resultat)
        html = rendre_comparaison(self.resultat, 'nl')
        for attendu in ['lang="nl"', 'Laagste referentiekosten', 'Huidig contract', '92.760,00 €', '400,00 €', 'Europe/Amsterdam', 'NorthC', '23 juni 2026', 'geen voorspelling', 'menselijke controles', 'kW']:
            self.assertIn(attendu, html)
        self.assertNotIn('Europa/Amsterdam', html)
        self.assertIn('Een lager tarief geeft geen recht op herstel', html)
        self.assertEqual(avant, self.resultat)

    def test_continuite_concerne_le_transport(self):
        message = 'Allocations futures et continuité du transport non garanties par la relecture historique.'
        self.assertEqual(traduire_message(message, 'nl'), 'De historische berekening garandeert geen toekomstige toewijzingen en geen continuïteit van het transport.')

    def test_pourcentages_du_catalogue_avec_espace(self):
        for traduction in MESSAGES.values():
            self.assertNotRegex(traduction, r'\d%')

    def test_libelles_sources_lecteurs_echappes_non_traduits(self):
        r = copy.deepcopy(self.resultat)
        texte_client = '<img src=x onerror=alert(1)> Date d’effet confirmée manquante.'
        r['options'][1]['libelle'] = texte_client
        r['options'][1]['traces']['tarif']['source'] = texte_client
        r['options'][1]['traces']['tarif']['verifie_par'] = '<script>lecteur</script>'
        r['traces']['provenance']['source'] = texte_client
        html = rendre_comparaison(r, 'nl')
        self.assertNotIn('<img ', html)
        self.assertNotIn('<script>', html)
        self.assertEqual(html.count('Date d’effet confirmée manquante.'), 5)
        self.assertIn('&lt;script&gt;lecteur&lt;/script&gt;', html)

    def test_dossier_vide_et_preuves_manquantes(self):
        r = comparer_contrats(self.valeurs, self.dates, {})
        html = rendre_comparaison(r, 'nl')
        self.assertIn('Geen financieel beste optie vastgesteld', html)
        self.assertIn('provenance: waarde en bewijsstuk ontbreken.', html)
        self.assertIn('Nog in te vullen', html)
        c = copy.deepcopy(self.configuration)
        c['provenance']['valeur']['fuseau_confirme'] = False
        c['options'][0]['offre']['statut'] = 'hypothese'
        c['options'][0]['offre']['valeur']['tension_kv'] = 20
        c['options'][0]['offre']['valeur']['conditions_verifiees'] = False
        html = rendre_comparaison(comparer_contrats(self.valeurs, self.dates, c), 'nl')
        self.assertIn('Herkomst: bevestig fuseau_confirme.', html)
        self.assertIn('Aanbod: controleer of tension_kv overeenkomt.', html)
        self.assertIn('Aanbod: bevestig conditions_verifiees.', html)
        self.assertIn('Aanname', html)

    def test_cbc_defaut_reference_depassee_et_borne(self):
        c = copy.deepcopy(self.configuration)
        c['contrat_actuel']['valeur']['gtv_kw'] = 90
        o = exemples.option('cbc', 110)
        o['programme'] = exemples.preuve({'mode': 'recurrent', 'plages': [exemples.plage(18, 20, 95)]})
        o['remuneration'] = exemples.preuve({'mode': 'jour_actif', 'euros_par_jour': 50, 'regle_defaut': 'jour_entier', 'annexe1_verifiee': False})
        o['demande_gtv'] = exemples.preuve({'date_demande': '2026-09-27', 'categorie_code': 'e'})
        c['options'] = [o]
        html = rendre_comparaison(comparer_contrats(self.valeurs, self.dates, c), 'nl')
        for attendu in ['Huidige referentie overschreden', 'Bruto CBC-vergoeding', '18.250,00 €', 'Vervallen op dagen', 'risico op afsluiting', 'wettelijke datumgrens', '2026-10-01', 'geen automatische verhoging', 'voorwaardelijk']:
            self.assertIn(attendu, html)
        self.assertNotIn('risico van ontbinding', html)

    def test_reference_non_fixe_ou_inconnue_expliquee_en_nl(self):
        for produit, phrase in [(None, 'bevestig een volledig vast transportrecht'),
                               ('cbc', 'De bijbehorende grenzen en vergoeding mogen niet worden genegeerd.')]:
            c = copy.deepcopy(self.configuration)
            c['contrat_actuel']['valeur']['produit'] = produit
            resultat = comparer_contrats(self.valeurs, self.dates, c)
            self.assertEqual(resultat['options'], [])
            rendu = rendre_comparaison(resultat, 'nl')
            self.assertIn(phrase, rendu)
            self.assertNotIn('92.760', rendu)
            self.assertNotIn('Contrat actuel :', rendu)

    def test_messages_publics_produits_operateurs(self):
        for produit in ('fixe', 'cbc', 'tijdsblok', 'volledig_variabel', 'tijdsduur'):
            for operateur in ('liander', 'enexis', 'stedin', 'tennet', 'inconnu'):
                for reseau in (None, 'distribution', 'transmission'):
                    for confirmation in (None, False, True):
                        r = admissibilite(produit, operateur, reseau=reseau, grande_connexion=confirmation, congestion=confirmation, remplacement=True)
                        for cle in ('manquants', 'refus', 'remarques'):
                            for message in r[cle]:
                                self.assertTrue(traduire_message(message, 'nl'))

    def test_messages_bornes_toutes_categories(self):
        for categorie in ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', None):
            for jour in ('2026-02-20', '2026-09-27'):
                for sens in ('baisse', 'hausse'):
                    r = premiere_date_gtv(jour, categorie, sens=sens)
                    for message in r['manquants'] + r['conditions'] + [r['limite_source']]:
                        self.assertTrue(traduire_message(message, 'nl'))

    def test_catalogue_couvre_messages_statiques_du_moteur(self):
        # Une nouvelle réserve doit avoir sa traduction avant de livrer le NL.
        for fichier in ('optimisation_contrat.py', 'regles_contrats_nl.py', 'pointes_ponderees.py'):
            arbre = ast.parse(Path(__file__).with_name(fichier).read_text())
            for noeud in ast.walk(arbre):
                if (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute)
                    and noeud.func.attr == 'append' and isinstance(noeud.func.value, ast.Name)
                    and noeud.func.value.id in ('manque', 'manquants', 'communs', 'refus', 'conditions', 'remarques')
                    and noeud.args and isinstance(noeud.args[0], ast.Constant) and isinstance(noeud.args[0].value, str)):
                    with self.subTest(message=noeud.args[0].value):
                        self.assertIn(noeud.args[0].value, MESSAGES)

    def test_message_inconnu_refuse(self):
        with self.assertRaisesRegex(ValueError, 'Traduction néerlandaise absente'):
            traduire_message('Une réserve ajoutée sans traduction.', 'nl')

    def test_langues_inconnues_refusees(self):
        for langue in ('en', None, {}, '<script>'):
            with self.assertRaisesRegex(ValueError, 'Langue du rapport'):
                rendre_comparaison(self.resultat, langue)

    def test_api_nl_et_refus_langue_inconnue_sans_ia(self):
        from verifier_live import demo_temporaire
        import serveur
        texte = 'fin_intervalle,puissance_kw\n' + ''.join(f'{d},{v}\n' for d, v in zip(self.dates, self.valeurs))
        with demo_temporaire() as client, patch.object(serveur, 'extraire_avec_nebius', side_effect=AssertionError('IA interdite')) as ia:
            r = client.post('/api/contrats/comparer', json={'texte': texte, 'configuration': self.configuration, 'langue': 'nl'})
            self.assertEqual(r.status_code, 200, r.text[:500])
            self.assertEqual(r.json()['langue'], 'nl')
            self.assertIn('lang="nl"', r.json()['html'])
            self.assertEqual(r.json()['resultat'], self.resultat)
            r = client.post('/api/contrats/comparer', json={'texte': texte, 'configuration': self.configuration, 'langue': 'en'})
            self.assertEqual(r.status_code, 422)
            ia.assert_not_called()

    def test_cli_nl_produit_deux_fichiers(self):
        from comparer_contrats import main
        with tempfile.TemporaryDirectory() as temporaire:
            dossier = Path(temporaire)
            (dossier / 'profil.csv').write_text('fin_intervalle,puissance_kw\n' + ''.join(f'{d},{v}\n' for d, v in zip(self.dates, self.valeurs)))
            (dossier / 'fiche.json').write_text(json.dumps(self.configuration))
            with patch.object(sys, 'argv', ['comparer_contrats.py', '--profil', str(dossier / 'profil.csv'), '--fiche', str(dossier / 'fiche.json'), '--sortie', str(dossier / 'sortie'), '--langue', 'nl']):
                main()
            self.assertIn('lang="nl"', (dossier / 'sortie/comparaison.html').read_text())
            self.assertEqual(json.loads((dossier / 'sortie/comparaison.json').read_text()), self.resultat)


if __name__ == '__main__':
    unittest.main()
