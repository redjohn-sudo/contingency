"""Exports synthétiques, sans prétendre représenter un schéma privé de portail."""
import copy
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from lecteur_csv_compteur import apercu, convertir_csv, decoder, modele

AMSTERDAM = ZoneInfo('Europe/Amsterdam')


def configuration():
    return modele() | {'meetbedrijf': 'Portail fictif, test uniquement',
                        'colonne_temps': 'Tijd', 'colonne_valeur': 'Verbruik',
                        'format_temps': 'ISO8601', 'separateur': ';', 'decimal': ',',
                        'milliers': '.', 'fuseau': 'Europe/Amsterdam', 'horodatage_marque': 'debut',
                        'unite': 'kwh_par_quart', 'colonne_compteur': 'EAN',
                        'filtres': {'EAN': 'SITE-A-FICTIF', 'Kanaal': 'Afname'},
                        'colonne_statut': 'Status', 'statuts': {'V': 'valide', 'E': 'estime', 'I': 'invalide'}}


def export_synthetique(nombre=96, debut=None, autres=False):
    debut = debut or datetime(2026, 1, 1, tzinfo=AMSTERDAM)
    debut = debut.astimezone(timezone.utc)
    flux = io.StringIO()
    ecrivain = csv.writer(flux, delimiter=';', lineterminator='\n')
    ecrivain.writerow(['EAN', 'Tijd', 'Kanaal', 'Verbruik', 'Status'])
    for i in range(nombre):
        temps = (debut + timedelta(minutes=15 * i)).astimezone(AMSTERDAM).isoformat()
        ecrivain.writerow(['SITE-A-FICTIF', temps, 'Afname', '50,125', 'E' if i == 5 else 'V'])
        if autres:
            # Leur statut rejeté ne concerne pas le canal sélectionné.
            ecrivain.writerow(['SITE-A-FICTIF', temps, 'Teruglevering', '1,00', 'I'])
            ecrivain.writerow(['SITE-B-FICTIF', temps, 'Afname', '2,00', 'I'])
    return flux.getvalue()


class CSVCompteurTest(unittest.TestCase):
    def test_conversion_kwh_par_quart_vers_kw_et_fin(self):
        r = convertir_csv(export_synthetique(), configuration())
        self.assertEqual(r['valeurs_kw'], [200.5] * 96)
        self.assertEqual(r['horodatages'][0], '2026-01-01T00:15:00+01:00')
        self.assertEqual(r['horodatages'][-1], '2026-01-02T00:00:00+01:00')
        self.assertEqual(r['provenance']['facteur_vers_kw'], 4)
        self.assertTrue(r['csv'].startswith('fin_intervalle,puissance_kw\n'))

    def test_deux_compteurs_et_deux_sens_separes(self):
        r = convertir_csv(export_synthetique(autres=True), configuration())
        self.assertEqual(r['provenance']['lignes_source'], 288)
        self.assertEqual(r['provenance']['lignes_ecartees'], 192)
        self.assertEqual(r['provenance']['compteurs'], ['SITE-A-FICTIF'])
        self.assertEqual(r['valeurs_kw'], [200.5] * 96)

    def test_qualite_et_lignes_originales_conservees(self):
        r = convertir_csv(export_synthetique(autres=True), configuration())
        self.assertEqual(r['provenance']['statuts_source'], {'V': 95, 'E': 1})
        self.assertEqual(r['qualites'][5], {'ligne_source': 17, 'statut_source': 'E', 'qualite': 'estime'})
        self.assertTrue(any('estimées' in a for a in r['avertissements']))

    def test_statut_absent_reste_inconnu(self):
        r = convertir_csv(export_synthetique(), configuration() | {'colonne_statut': ''})
        self.assertEqual({q['qualite'] for q in r['qualites']}, {'inconnue'})
        self.assertTrue(any('inconnue' in a for a in r['avertissements']))

    def test_statut_rejete_ou_inconnu_refuse(self):
        for statut in ('I', '?'):
            with self.subTest(statut=statut), self.assertRaisesRegex(ValueError, 'Statut inconnu ou invalide'):
                convertir_csv(export_synthetique().replace(';V\n', ';' + statut + '\n', 1), configuration())

    def test_statut_sans_dictionnaire_refuse(self):
        with self.assertRaisesRegex(ValueError, 'signification'):
            convertir_csv(export_synthetique(), configuration() | {'statuts': {}})

    def test_kw_ne_subit_pas_conversion(self):
        r = convertir_csv(export_synthetique(), configuration() | {'unite': 'kw'})
        self.assertEqual(r['valeurs_kw'][0], 50.125)
        self.assertEqual(r['provenance']['facteur_vers_kw'], 1)

    def test_horodatage_de_fin_non_decale(self):
        r = convertir_csv(export_synthetique(), configuration() | {'horodatage_marque': 'fin'})
        self.assertEqual(r['horodatages'][0], '2026-01-01T00:00:00+01:00')

    def test_jours_dst_92_et_100_quarts(self):
        from serveur import _lire_profil_detaille
        for debut, n in [(datetime(2026, 3, 29, tzinfo=AMSTERDAM), 92),
                         (datetime(2026, 10, 25, tzinfo=AMSTERDAM), 100)]:
            with self.subTest(debut=debut):
                r = convertir_csv(export_synthetique(n, debut), configuration())
                kw, fins = _lire_profil_detaille(r['csv'], jours_civils=True)
                self.assertEqual(kw, [200.5] * n)
                self.assertEqual(fins, r['horodatages'])
                self.assertTrue(fins[-1][11:].startswith('00:00:00'))

    def test_heure_locale_ambigue_ou_inexistante_refusee(self):
        for instant in ('2026-10-25T02:00:00', '2026-03-29T02:00:00'):
            texte = 'EAN;Tijd;Kanaal;Verbruik;Status\nSITE-A-FICTIF;' + instant + ';Afname;50,125;V\n'
            with self.subTest(instant=instant), self.assertRaisesRegex(ValueError, 'ambiguë'):
                convertir_csv(texte, configuration())

    def test_horodatage_non_quart_ou_trou_ou_doublon_refuse(self):
        lignes = export_synthetique().splitlines()
        textes = ['\n'.join(lignes[:3] + lignes[4:]), '\n'.join(lignes[:3] + [lignes[2]] + lignes[3:]),
                  export_synthetique().replace('00:15:00', '00:16:00', 1)]
        for texte in textes:
            with self.subTest(texte=texte[:60]), self.assertRaises(ValueError):
                convertir_csv(texte, configuration())

    def test_index_et_unite_absente_refuses(self):
        for modification in ({'unite': 'index_kwh'}, {'unite': None}, {'nature_valeurs': 'index'},
                             {'pas_minutes': 60}, {'nature_valeurs': ''}):
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                convertir_csv(export_synthetique(), configuration() | modification)

    def test_un_seul_compteur_obligatoire_meme_sans_chevauchement(self):
        texte = export_synthetique().replace('SITE-A-FICTIF', 'SITE-B-FICTIF', 1)
        with self.assertRaisesRegex(ValueError, 'Plusieurs compteurs'):
            convertir_csv(texte, configuration() | {'filtres': {'Kanaal': 'Afname'}})
        with self.assertRaisesRegex(ValueError, 'un seul compteur'):
            convertir_csv(export_synthetique(), configuration() | {'colonne_compteur': ''})
        r = convertir_csv(export_synthetique(), configuration() | {'colonne_compteur': '', 'compteur_unique': True})
        self.assertTrue(r['provenance']['compteur_unique_declare'])

    def test_date_et_heure_separees_preambule_et_milliers(self):
        texte = 'FICHIER FICTIF\nDate;Heure;Valeur\n01-01-2026;00:00+0100;1.250,125\n'
        config = configuration() | {'lignes_avant_entete': 1, 'colonne_date': 'Date', 'colonne_temps': 'Heure',
                                   'colonne_valeur': 'Valeur', 'format_temps': '%d-%m-%Y %H:%M%z',
                                   'colonne_compteur': '', 'compteur_unique': True, 'colonne_statut': '', 'filtres': {}}
        r = convertir_csv(texte, config)
        self.assertEqual(r['valeurs_kw'], [5000.5])
        self.assertEqual(r['qualites'][0]['ligne_source'], 3)

    def test_entete_duplique_et_largeur_irreguliere_refuses(self):
        textes = [export_synthetique().replace('EAN;Tijd;', 'Tijd;Tijd;', 1),
                  export_synthetique().replace(';V\n', ';V;exces\n', 1),
                  export_synthetique().replace(';V\n', '\n', 1)]
        for texte in textes:
            with self.subTest(texte=texte[:45]), self.assertRaises(ValueError):
                convertir_csv(texte, configuration())

    def test_convention_manquante_non_devinee(self):
        for champ in ('meetbedrijf', 'fuseau', 'decimal', 'milliers', 'format_temps', 'horodatage_marque', 'kanaal'):
            with self.subTest(champ=champ), self.assertRaisesRegex(ValueError, 'Convention obligatoire'):
                convertir_csv(export_synthetique(), configuration() | {champ: None})

    def test_negatif_et_non_fini_refuses(self):
        for valeur in ('-10,0', 'nan', 'inf', '1.23,456'):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                convertir_csv(export_synthetique().replace('50,125', valeur, 1), configuration())

    def test_aucune_ligne_selectionnee_refusee(self):
        with self.assertRaisesRegex(ValueError, 'Aucune mesure'):
            convertir_csv(export_synthetique(), configuration() | {'filtres': {'EAN': 'absent'}})

    def test_configuration_intacte_et_empreinte_reproductible(self):
        config = configuration()
        avant = copy.deepcopy(config)
        r = convertir_csv(export_synthetique(), config)
        self.assertEqual(config, avant)
        self.assertEqual(r, convertir_csv(export_synthetique(), config))
        self.assertEqual(len(r['provenance']['empreinte_texte_source']), 64)

    def test_encodages_et_apercu_sans_interpretation(self):
        texte = 'Énergie;Heure\n1,25;00:00\n'
        self.assertEqual(decoder(texte.encode('cp1252'), 'cp1252'), texte)
        self.assertEqual(decoder(texte.encode('utf-16'), 'utf-16'), texte)
        with self.assertRaises(ValueError):
            decoder(texte.encode('cp1252'))
        self.assertEqual(apercu(texte, ';')['exemples'][0]['valeurs']['Énergie'], '1,25')

    def test_commande_produit_csv_et_audit_sans_ecraser_source(self):
        script = str(Path(__file__).with_name('lecteur_csv_compteur.py'))
        with tempfile.TemporaryDirectory() as temporaire:
            racine = Path(temporaire)
            source, config = racine / 'source.csv', racine / 'conventions.json'
            original = export_synthetique()
            source.write_text(original)
            config.write_text(json.dumps(configuration()))
            commande = [sys.executable, script, 'convertir', str(source), '--configuration', str(config),
                        '--sortie', str(racine / 'resultat')]
            resultat = subprocess.run(commande, capture_output=True, text=True, timeout=30)
            self.assertEqual(resultat.returncode, 0, resultat.stderr)
            self.assertEqual(source.read_text(), original)
            self.assertTrue((racine / 'resultat/profil.csv').exists())
            audit = json.loads((racine / 'resultat/import.json').read_text())
            self.assertEqual(audit['provenance']['lignes_importees'], 96)
            self.assertIn('empreinte_fichier_source', audit['provenance'])
            self.assertEqual(subprocess.run(commande, capture_output=True, timeout=30).returncode, 2)

    def test_api_apercu_et_conversion_sans_modele_ni_etude_creee(self):
        import serveur
        from verifier_live import demo_temporaire
        with demo_temporaire() as client, patch.object(serveur, 'extraire_avec_nebius') as fournisseur:
            self.assertEqual(client.get('/import-compteur').status_code, 200)
            avant = list(serveur.DOSSIERS.glob('*.json'))
            vue = client.post('/api/compteur/apercu', json={'texte': export_synthetique(), 'separateur': ';'})
            self.assertEqual(vue.status_code, 200)
            self.assertEqual(vue.json()['nombre_lignes'], 96)
            resultat = client.post('/api/compteur/convertir', json={
                'texte': export_synthetique(), 'configuration': configuration()})
            self.assertEqual(resultat.status_code, 200, resultat.text)
            self.assertEqual(resultat.json()['valeurs_kw'], [200.5] * 96)
            self.assertEqual(list(serveur.DOSSIERS.glob('*.json')), avant)
            fournisseur.assert_not_called()

    def test_api_refuse_contenu_mal_forme_et_origine_externe(self):
        from verifier_live import demo_temporaire
        with demo_temporaire() as client:
            for contenu in ([], {'texte': None}, {'texte': export_synthetique(), 'configuration': None}):
                with self.subTest(contenu=str(contenu)[:50]):
                    self.assertEqual(client.post('/api/compteur/convertir', json=contenu).status_code, 422)
            self.assertEqual(client.post('/api/compteur/apercu', json={'texte': '', 'separateur': ';'},
                                         headers={'Origin': 'https://externe.invalid'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
