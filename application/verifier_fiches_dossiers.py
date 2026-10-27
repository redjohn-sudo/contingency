"""Fiches des dossiers : lecture stricte, bornée et compatible UTF-8."""
from pathlib import Path
import tempfile
import unittest

from fiches_dossiers import lire_fiche, TAILLE_MAX_FICHE, PROFONDEUR_MAX_FICHE


class LectureFiches(unittest.TestCase):
    def lire(self, contenu):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / 'fiche.json'
            chemin.write_bytes(contenu.encode('utf-8') if isinstance(contenu, str) else contenu)
            return lire_fiche(chemin)

    def test_objet_valide_et_nombre_scientifique(self):
        attendu = {'site': 'Entrepôt', 'valeurs': [None, True, False, 1250.0, -0.25]}
        self.assertEqual(self.lire('{"site":"Entrepôt","valeurs":[null,true,false,1.25e3,-0.25]}'), attendu)

    def test_bom_utf8_accepte(self):
        self.assertEqual(self.lire(b'\xef\xbb\xbf{"site":"A"}'), {'site': 'A'})

    def test_objets_uniquement(self):
        for contenu in ('[]', 'null', '1', 'true', '"texte"'):
            with self.subTest(contenu=contenu), self.assertRaisesRegex(ValueError, 'objet JSON'):
                self.lire(contenu)

    def test_doublons_simples_imbriques_et_echappes_refuses(self):
        for contenu in ('{"a":1,"a":2}', '{"annexe":[{"a":1,"a":2}]}',
                        r'{"a":1,"\u0061":2}'):
            with self.subTest(contenu=contenu), self.assertRaisesRegex(ValueError, 'répété'):
                self.lire(contenu)

    def test_nombres_non_finis_refuses_partout(self):
        for nombre in ('NaN', 'Infinity', '-Infinity', '1e9999', '-1e9999'):
            with self.subTest(nombre=nombre), self.assertRaises(ValueError):
                self.lire('{"annexe":[' + nombre + ']}')

    def test_utf8_et_unicode_invalides_refuses(self):
        for contenu in (b'{"site":"\xff"}', r'{"site":"\ud800"}', r'{"\udfff":1}'):
            with self.subTest(contenu=contenu), self.assertRaises(ValueError):
                self.lire(contenu)

    def test_paire_unicode_valide_acceptee(self):
        self.assertEqual(self.lire(r'{"symbole":"\ud834\udd1e"}'), {'symbole': '\U0001d11e'})

    def test_limite_taille_en_octets(self):
        contenu = b'{}' + b' ' * (TAILLE_MAX_FICHE - 2)
        self.assertEqual(self.lire(contenu), {})
        with self.assertRaisesRegex(ValueError, '1 Mio'):
            self.lire(contenu + b' ')

    def test_imbrication_extreme_refusee_sans_erreur_recursion_brute(self):
        with self.assertRaisesRegex(ValueError, 'imbriquée'):
            self.lire('{"annexe":' + '[' * 2000 + '0' + ']' * 2000 + '}')

    def test_limite_imbrication_explicite(self):
        profondeur = PROFONDEUR_MAX_FICHE - 1
        self.lire('{"annexe":' + '[' * profondeur + '0' + ']' * profondeur + '}')
        with self.assertRaisesRegex(ValueError, '64 niveaux'):
            self.lire('{"annexe":' + '[' * (profondeur + 1) + '0' + ']' * (profondeur + 1) + '}')

    def test_json_incomplet_et_texte_apres_objet_refuses(self):
        for contenu in ('', '{', '{} {}', '{"a":1,}', '{"a":"ligne\nbrisée"}'):
            with self.subTest(contenu=contenu), self.assertRaises(ValueError):
                self.lire(contenu)


if __name__ == '__main__':
    unittest.main()
