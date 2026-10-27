"""Import d'une vraie semaine de mesures de centre de calcul (ESIF, NLR, CC BY 4.0) par le convertisseur strict.

Deux familles, séparées exprès :
- VraiCSV : la semaine native de docs/preuves/centres-donnees/donnees-reelles, lue telle quelle. Aucune
  interpolation, aucun arrondi de date, aucune décimation, aucune suppression. Ces mesures ne sont pas des
  quarts d'heure : le refus de la conversion est le résultat correct, pas un défaut à contourner.
- ContreExemplesConstruits : petits fichiers fabriqués pour un seul comportement (trou, valeur négative).
Ni appel au modèle, ni dossier d'étude créé, ni calcul de batterie.
"""
import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from lecteur_csv_compteur import apercu, convertir_csv, modele

DOSSIER = Path(__file__).resolve().parent.parent / 'docs' / 'preuves' / 'centres-donnees' / 'donnees-reelles'
CSV_ESIF = DOSSIER / 'esif-semaine-2024-01-01-native.csv'
AUDIT = DOSSIER / 'audit-esif.json'
COLONNES = ['ligne_source', 'horodatage_source', 'horodatage_utc', 'qualite', 'it_power_kw', 'cooling_kw',
            'hvac_kw', 'pump_kw', 'plug_and_light_kw', 'somme_composants_kw']


def texte_esif():
    return CSV_ESIF.read_text(encoding='utf-8')


def lignes_esif():
    return list(csv.DictReader(io.StringIO(texte_esif())))


def declaration(**autres):
    """Ce que l'on peut déclarer de vrai sur ce fichier : UTC explicite, kW, un seul site."""
    return modele() | {'meetbedrijf': 'NLR ESIF, données publiques CC BY 4.0 (pas un compteur contractuel)',
                       'colonne_temps': 'horodatage_utc', 'colonne_valeur': 'somme_composants_kw',
                       'format_temps': 'ISO8601', 'separateur': ',', 'decimal': '.', 'milliers': 'aucun',
                       'fuseau': 'UTC', 'horodatage_marque': 'debut', 'unite': 'kw',
                       'compteur_unique': True} | autres


MOIS = {m: i for i, m in enumerate(('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}


def instant_source(brut):
    """« Sun Dec 31 2023 17:00:02 GMT-0700 (Mountain Standard Time) » : date, heure et décalage explicites.
    Table de mois fixe : strptime %a %b dépendrait de la langue du système (revue du lot)."""
    _, mois, jour, annee, heure, gmt = brut.split(' (', 1)[0].split()
    return datetime.strptime(f'{annee}-{MOIS[mois]:02d}-{jour} {heure} {gmt[3:]}', '%Y-%m-%d %H:%M:%S %z')


class VraiCSV(unittest.TestCase):
    def test_le_fichier_teste_est_bien_celui_de_l_audit(self):
        attendu = json.loads(AUDIT.read_text(encoding='utf-8'))['semaine']['csv_sha256']
        self.assertEqual(hashlib.sha256(CSV_ESIF.read_bytes()).hexdigest(), attendu)

    def test_apercu_complet_sans_perte(self):
        vue = apercu(texte_esif(), ',')
        self.assertEqual(vue['colonnes'], COLONNES)
        self.assertEqual(vue['nombre_lignes'], 10071)
        self.assertEqual(vue['exemples'][0]['valeurs']['horodatage_utc'], '2024-01-01T00:00:02+00:00')

    def test_fausse_declaration_en_quarts_d_heure_refusee_des_la_premiere_ligne(self):
        import serveur
        for marque in ('debut', 'fin'):
            with self.subTest(marque=marque), patch('serveur.lire_export', wraps=serveur.lire_export) as lecteur:
                with self.assertRaises(ValueError) as refus:
                    convertir_csv(texte_esif(), declaration(horodatage_marque=marque))
                self.assertEqual(str(refus.exception), 'Horodatage hors d’un quart d’heure exact ligne 2.')
                # Le lecteur strict a reçu les 10 071 points, dans l'ordre : rien n'a été supprimé en route.
                transmis = lecteur.call_args.args[0].splitlines()
                self.assertEqual(len(transmis) - 1, 10071)
                self.assertTrue(transmis[1].startswith('2024-01-01T00:00:02+00:00,'))

    def test_ligne_de_commande_refuse_sans_creer_de_sortie(self):
        import subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as repertoire:
            configuration = Path(repertoire) / 'declaration.json'
            configuration.write_text(json.dumps(declaration(), ensure_ascii=False), encoding='utf-8')
            sortie = Path(repertoire) / 'sortie'
            r = subprocess.run([sys.executable, 'lecteur_csv_compteur.py', 'convertir', str(CSV_ESIF),
                                '--configuration', str(configuration), '--sortie', str(sortie)],
                               cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertEqual(r.stderr.strip(), 'Import refusé : Horodatage hors d’un quart d’heure exact ligne 2.')
            self.assertFalse(sortie.exists())

    def test_les_deux_trous_reels_sont_conserves_sans_interpolation(self):
        lignes = lignes_esif()
        instants = [datetime.fromisoformat(l['horodatage_utc']) for l in lignes]
        self.assertEqual(len(instants), 10071)
        self.assertEqual(instants, sorted(instants))
        trous = [(a.isoformat(), b.isoformat(), (b - a).total_seconds())
                 for a, b in zip(instants, instants[1:]) if (b - a).total_seconds() > 90]
        self.assertEqual(trous, [('2024-01-03T15:58:02+00:00', '2024-01-03T16:01:02+00:00', 180.0),
                                 ('2024-01-04T20:45:02+00:00', '2024-01-04T20:53:02+00:00', 480.0)])
        attendus = json.loads(AUDIT.read_text(encoding='utf-8'))['semaine']['ecarts_superieurs_a_90_secondes']
        self.assertEqual([(t['avant_utc'], t['apres_utc'], float(t['secondes'])) for t in attendus], trous)
        # Les numéros de ligne source se suivent : rien n'a été supprimé ni inséré dans l'extrait.
        numeros = [int(l['ligne_source']) for l in lignes]
        self.assertEqual(numeros, list(range(numeros[0], numeros[0] + len(numeros))))

    def test_frontiere_du_31_decembre_local_contre_utc(self):
        lignes = lignes_esif()
        for ligne in lignes:
            local = instant_source(ligne['horodatage_source'])
            # Même instant, à la seconde près : pas d'arrondi de date ni de décalage perdu.
            self.assertEqual(local.astimezone(timezone.utc), datetime.fromisoformat(ligne['horodatage_utc']), ligne['ligne_source'])
        veille_locale = [l for l in lignes if instant_source(l['horodatage_source']).date().isoformat() == '2023-12-31']
        self.assertTrue(veille_locale)
        # La veille locale (UTC-7) tombe entièrement le 1er janvier en UTC : la semaine UTC ne perd pas ces sept heures.
        self.assertTrue(all(l['horodatage_utc'].startswith('2024-01-01T0') for l in veille_locale))
        self.assertEqual(instant_source(veille_locale[0]['horodatage_source']).utcoffset(), timedelta(hours=-7))
        self.assertEqual(veille_locale[-1]['horodatage_utc'][:13], '2024-01-01T06')

    def test_api_apercu_et_refus_sans_modele_ni_dossier(self):
        import serveur
        from verifier_live import demo_temporaire
        with demo_temporaire() as client, patch.object(serveur, 'extraire_avec_nebius') as fournisseur:
            avant = sorted(serveur.DOSSIERS.glob('*'))
            vue = client.post('/api/compteur/apercu', json={'texte': texte_esif(), 'separateur': ','})
            self.assertEqual(vue.status_code, 200, vue.text)
            self.assertEqual(vue.json()['nombre_lignes'], 10071)
            for faux, motif in ((declaration(), 'Horodatage hors d’un quart d’heure exact ligne 2.'),
                                (declaration(pas_minutes=1), 'Déclarer des valeurs par intervalle de 15 minutes : ')):
                with self.subTest(configuration=faux['pas_minutes']):
                    refus = client.post('/api/compteur/convertir', json={'texte': texte_esif(), 'configuration': faux})
                    self.assertEqual(refus.status_code, 422, refus.text)
                    self.assertTrue(refus.json()['detail'].startswith(motif), refus.text)
            self.assertEqual(sorted(serveur.DOSSIERS.glob('*')), avant)
            fournisseur.assert_not_called()


class RegleDeDeclaration(unittest.TestCase):
    """Refus décidés sur la déclaration, avant toute lecture des lignes : ils ne prouvent rien sur le fichier ESIF lui-même."""

    def test_points_natifs_declares_tels_quels_sont_refuses(self):
        # Déclaration honnête : échantillons d'environ une minute, pas des intervalles de 15 minutes.
        for honnete in ({'pas_minutes': 1}, {'nature_valeurs': 'echantillons'}, {'nature_valeurs': 'echantillons', 'pas_minutes': 1}):
            with self.subTest(declaration=honnete), self.assertRaisesRegex(ValueError, 'intervalle de 15 minutes'):
                convertir_csv(texte_esif(), declaration(**honnete))

    def test_refus_des_points_natifs_dit_quoi_preparer_sans_agreger(self):
        # Décision du coordinateur (bus #909) : le refus décrit aussi les échantillons instantanés,
        # rappelle l'unité kWh par quart acceptée, et ne promet aucune agrégation.
        with self.assertRaises(ValueError) as refus:
            convertir_csv(texte_esif(), declaration(pas_minutes=1))
        message = str(refus.exception)
        for attendu in ('puissance moyenne en kW', 'kWh par quart', 'échantillons instantanés',
                        'index cumulés', 'préparation adaptée et documentée', 'Aucune agrégation n’est effectuée ici'):
            self.assertIn(attendu, message)
        self.assertNotIn('pas des index cumulés', message)  # ancienne phrase, muette sur les échantillons


class ContreExemplesConstruits(unittest.TestCase):
    """Fichiers fabriqués : chacun ne prouve qu'un comportement du lecteur, pas une propriété des données ESIF."""

    def test_un_quart_d_heure_manquant_est_refuse_et_non_comble(self):
        debut = datetime(2024, 1, 1, tzinfo=timezone.utc)
        instants = [debut + timedelta(minutes=15 * i) for i in range(96) if i != 40]
        texte = 'instant,kw\n' + ''.join(f'{t.isoformat()},100.0\n' for t in instants)
        with self.assertRaisesRegex(ValueError, 'Export irrégulier'):
            convertir_csv(texte, declaration(colonne_temps='instant', colonne_valeur='kw', pas_minutes=15))

    def test_valeur_negative_refusee_sans_diagnostic_trop_certain(self):
        from serveur import VALEURS_NEGATIVES, lire_export
        debut = datetime(2026, 1, 5, tzinfo=timezone.utc)
        lignes = [f'{(debut + timedelta(minutes=15 * (i + 1))).isoformat()},{-3.5 if i == 7 else 120.0}' for i in range(96)]
        with self.assertRaises(ValueError) as refus:
            lire_export('fin_intervalle,puissance_kw\n' + '\n'.join(lignes) + '\n')
        message = str(refus.exception)
        self.assertEqual(message, VALEURS_NEGATIVES)
        # Plusieurs causes possibles : canal mélangé, convention de signe, anomalie de mesure.
        for cause in ('injection', 'convention de signe', 'anomalie de mesure'):
            self.assertIn(cause, message)
        self.assertNotIn("l'export mélange", message)  # ancienne affirmation, trop certaine
        self.assertIn('Vérifier', message)

    def test_message_negatif_garde_sa_traduction_anglaise(self):
        from serveur import VALEURS_NEGATIVES
        import re
        traductions = (Path(__file__).resolve().parent / 'english.js').read_text(encoding='utf-8')
        entree = re.search(re.escape(json.dumps(VALEURS_NEGATIVES, ensure_ascii=False)) + r':\s*("(?:[^"\\]|\\.)*")', traductions)
        self.assertIsNotNone(entree, 'clé absente de english.js')
        anglais = json.loads(entree.group(1))
        for cause in ('feed-in', 'sign convention', 'measurement anomaly', 'Check the exported channel'):
            self.assertIn(cause, anglais)
        self.assertNotIn('the export mixes', anglais)  # ancienne affirmation, trop certaine


if __name__ == '__main__':
    unittest.main(verbosity=2)
