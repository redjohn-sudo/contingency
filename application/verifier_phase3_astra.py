"""Régressions attribuées à Astra, phase 3 du 29 septembre 2026."""
import csv
import io
import unittest

from lecteur_csv_compteur import convertir_csv
from verifier_csv_compteur import configuration, export_synthetique
from champ_communal import dans_le_champ
from rapport_html import rendre_rapport
from serveur import _texte_rapport


class ImportNumerique(unittest.TestCase):
    def export(self, valeurs):
        lignes = list(csv.reader(io.StringIO(export_synthetique()), delimiter=';'))
        for index, ligne in enumerate(lignes[1:]):
            ligne[3] = valeurs[index % len(valeurs)]
        flux = io.StringIO()
        csv.writer(flux, delimiter=';', lineterminator='\n').writerows(lignes)
        return flux.getvalue()

    def test_o7_trois_decimales_sans_zero_initial_refusees_si_ambigues(self):
        with self.assertRaisesRegex(ValueError, 'ambigu'):
            convertir_csv(self.export(['25.000', '12.500', '31.250', '18.750']), configuration())

    def test_o7_convention_decimale_correcte_conserve_les_kw(self):
        r = convertir_csv(self.export(['25.000', '12.500', '31.250', '18.750']),
                          configuration() | {'decimal': '.', 'milliers': 'aucun'})
        self.assertEqual(r['valeurs_kw'][:4], [100, 50, 125, 75])

    def test_o7_vrais_milliers_avec_decimale_explicite_restent_valides(self):
        r = convertir_csv(self.export(['25.000,0', '12.500,0']), configuration())
        self.assertEqual(r['valeurs_kw'][:2], [100000, 50000])


class ZonesOosterhout(unittest.TestCase):
    def test_o16_zone_exacte_ou_prefixe_admis_reste_exclue(self):
        for zone in ('Everdenberg-Oost', 'Bedrijventerrein Everdenberg Oost',
                     'Energiepark A59', 'Zonnepark Dorst'):
            with self.subTest(zone=zone):
                r = dans_le_champ({'date_mise_en_service': None, 'zone_nommee': zone}, 'Oosterhout')
                self.assertEqual(r['statut'], 'hors_champ')

    def test_o16_proximite_negation_suffixe_et_nom_inconnu_restent_indetermines(self):
        for zone in ('naast bedrijventerrein Everdenberg-Oost', 'Zonnepark Dorst-West',
                     'niet in Energiepark A59', 'zone inconnue'):
            with self.subTest(zone=zone):
                r = dans_le_champ({'date_mise_en_service': None, 'zone_nommee': zone}, 'Oosterhout')
                self.assertEqual(r['statut'], 'indetermine')
                self.assertIn('zone_nommee', [m['champ'] for m in r['manque']])

    def test_o16_absence_de_zone_explicitement_declaree(self):
        r = dans_le_champ({'date_mise_en_service': None, 'zone_nommee': 'aucune'}, 'Oosterhout')
        self.assertEqual(r['statut'], 'dans_le_champ')


class RapportImprimable(unittest.TestCase):
    def test_o17_numero_facture_restitue_sans_echappement_visible(self):
        texte = _texte_rapport('Factuur #2026-081.pdf')
        r = rendre_rapport(texte, 'test')
        self.assertIn('<p>Factuur #2026-081.pdf</p>', r)

    def test_o17_cellule_et_titre_restituent_le_numero(self):
        texte = _texte_rapport('Factuur #2026-081.pdf')
        r = rendre_rapport('# ' + texte + '\n| Document |\n| --- |\n| ' + texte + ' |', 'test')
        self.assertIn('<h1>Factuur #2026-081.pdf</h1>', r)
        self.assertIn('<td>Factuur #2026-081.pdf</td>', r)

    def test_o17_contenu_documentaire_ne_cree_pas_de_titre_ni_html(self):
        r = rendre_rapport(_texte_rapport('# <img src=x>\n## faux titre'), 'test')
        self.assertNotIn('<h1>', r)
        self.assertNotIn('<h2>', r)
        self.assertIn('<p># &lt;img src=x&gt; ## faux titre</p>', r)

    def test_o17_barre_oblique_originale_preservee(self):
        r = rendre_rapport(_texte_rapport(r'Archive\#2026.pdf'), 'test')
        self.assertIn(r'<p>Archive\#2026.pdf</p>', r)


if __name__ == '__main__':
    unittest.main()
