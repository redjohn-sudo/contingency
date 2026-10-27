"""Vrais PDF raster et texte, OCR local et refus des imports hors limites."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

import documents


def enfant_deja_arrete(pid):
    """Nettoie un éventuel orphelin sans transformer ce nettoyage en réussite."""
    etat = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    if not etat or etat.startswith('Z'):
        return True
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        # Il a disparu entre ps et kill : l'arrêt demandé a bien eu lieu.
        return True
    return False


def fabriquer_pdf(pages, dimensions=(595, 842)):
    """Petit générateur de fixtures PDF, sans couche texte cachée dans les scans."""
    objets = [b'', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    references = []

    def objet(contenu):
        objets.append(contenu)
        return len(objets)

    def flux(contenu, attributs=b''):
        return b'<< /Length ' + str(len(contenu)).encode() + b' ' + attributs + b' >>\nstream\n' + contenu + b'\nendstream'

    for page in pages:
        dessin = b''
        ressources = b'/Font << /F1 3 0 R >>'
        if page.get('image') is not None:
            image = page['image'].convert('RGB')
            attributs = (f'/Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} '
                         '/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode').encode()
            reference = objet(flux(zlib.compress(image.tobytes()), attributs))
            ressources += f' /XObject << /Im1 {reference} 0 R >>'.encode()
            dessin += f'q {dimensions[0]} 0 0 {dimensions[1]} 0 0 cm /Im1 Do Q\n'.encode()
        for numero, texte in enumerate(page.get('textes', [])):
            echappe = texte.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            dessin += f'BT /F1 16 Tf 50 {dimensions[1]-60-numero*30} Td ({echappe}) Tj ET\n'.encode('latin-1')
        contenu = objet(flux(dessin))
        reference = objet((f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {dimensions[0]} {dimensions[1]}] '
                           f'/Contents {contenu} 0 R /Resources << ').encode() + ressources + b' >> >>')
        references.append(reference)
    objets[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objets[1] = (f'<< /Type /Pages /Count {len(pages)} /Kids [' + ' '.join(f'{ref} 0 R' for ref in references) + '] >>').encode()
    resultat = bytearray(b'%PDF-1.4\n')
    positions = [0]
    for numero, contenu in enumerate(objets, start=1):
        positions.append(len(resultat))
        resultat.extend(f'{numero} 0 obj\n'.encode() + contenu + b'\nendobj\n')
    depart = len(resultat)
    resultat.extend(f'xref\n0 {len(objets)+1}\n0000000000 65535 f \n'.encode())
    resultat.extend(''.join(f'{position:010d} 00000 n \n' for position in positions[1:]).encode())
    resultat.extend(f'trailer\n<< /Size {len(objets)+1} /Root 1 0 R >>\nstartxref\n{depart}\n%%EOF\n'.encode())
    return bytes(resultat)


def fabriquer_scan():
    from PIL import Image, ImageDraw, ImageFont
    polices = [Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
               Path('/usr/share/fonts/noto/NotoSans-Regular.ttf'),
               Path('/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf'),
               Path('/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf'),
               Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    police = ImageFont.truetype(str(next(p for p in polices if p.exists())), 48)
    image = Image.new('RGB', (1600, 2264), 'white')
    dessin = ImageDraw.Draw(image)
    lignes = ['ESSAI FICTIF DE LECTURE', 'Puissance disponible : 150 kW',
              'Energie utile : 480 kWh', 'Rendement : 0.92',
              'Duree : 2,5 h', 'Puissance apparente : 200 kVA',
              'Tolerance : -1.5 %']
    for numero, texte in enumerate(lignes):
        dessin.text((120, 350 + 110 * numero), texte, font=police, fill='black')
    return image


class VerificationOCR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = fabriquer_scan()
        cls.mesures = []

    def setUp(self):
        self.temporaire = tempfile.TemporaryDirectory()
        self.repertoire = Path(self.temporaire.name)
        self.patch_sources = patch.object(documents, 'SOURCES', self.repertoire / 'sources')
        self.patch_sources.start()

    def tearDown(self):
        self.patch_sources.stop()
        self.temporaire.cleanup()

    def lecture(self, donnees, nom):
        debut = time.monotonic()
        resultat = documents.lire_pdf(donnees)
        self.mesures.append({'cas': nom, 'secondes': round(time.monotonic() - debut, 3),
                            'pages_ocr': resultat['lecture_ocr']['pages_ocr']})
        self.assertEqual((self.repertoire / resultat['source_pdf']['chemin']).read_bytes(), donnees)
        self.assertEqual(resultat['source_pdf']['sha256'], hashlib.sha256(donnees).hexdigest())
        lignes = resultat['texte'].splitlines()
        for page in resultat['lecture_ocr']['pages']:
            for plage in page['plages_lignes']:
                texte = page['texte_ocr'] if plage['origine'] == 'OCR à vérifier' else page['texte_original']
                self.assertEqual(lignes[plage['debut']-1:plage['fin']], texte.rstrip('\n').splitlines())
        return resultat

    def verifier_chiffres(self, texte):
        # Le rendu de police Linux change parfois la casse de kW et les espaces.
        # Tolérer uniquement ces variantes dans ce contrôle, jamais les chiffres,
        # signes ou unités différentes. Le texte OCR brut reste inchangé et vérifié
        # contre ses plages de lignes dans lecture(). Ce test ne certifie pas l'OCR.
        attendus = {'150 kW': r'150\s*[kK][wW]', '480 kWh': r'480\s*[kK][wW][hH]',
                    '0.92': r'0\.92', '2,5 h': r'2,5\s*h',
                    '200 kVA': r'200\s*[kK][vV][aA]', '-1.5 %': r'-1\.5\s*%'}
        for attendu, motif in attendus.items():
            with self.subTest(valeur=attendu):
                self.assertRegex(texte, r'(?<![\w.,+\-])' + motif + r'(?![\w.,])')

    def test_scan_reel_chiffres_unites_et_source(self):
        donnees = fabriquer_pdf([{'image': self.image}])
        chemin = self.repertoire / 'scan.pdf'
        chemin.write_bytes(donnees)
        texte_poppler = subprocess.run(['pdftotext', str(chemin), '-'], check=True, capture_output=True).stdout
        self.assertFalse(texte_poppler.strip(), 'Le scan ne doit pas contenir de couche texte.')
        resultat = self.lecture(donnees, 'scan')
        self.assertEqual(resultat['lecture_ocr']['pages_ocr'], [1])
        self.assertEqual(resultat['lecture_ocr']['statut'], 'extrait_a_verifier')
        self.assertFalse(resultat['texte_original'].strip())
        self.verifier_chiffres(resultat['texte'])
        page = resultat['lecture_ocr']['pages'][0]
        self.assertTrue((self.repertoire / page['image_source']).exists())
        self.assertTrue(page['a_verifier'])
        self.assertTrue(any(mot['contient_nombre'] and mot['boite_pixels'][2] > 0 for mot in page['mots_ocr']))

    def test_pdf_texte_original_inchange(self):
        donnees = fabriquer_pdf([{'textes': ['plafond_kw = 150', 'Rendement = 0.92']}])
        resultat = self.lecture(donnees, 'texte')
        self.assertEqual(resultat['lecture_ocr']['pages_ocr'], [])
        self.assertEqual(resultat['lecture_ocr']['statut'], 'non_necessaire')
        self.assertIn('plafond_kw = 150', resultat['texte_original'])
        source = self.repertoire / resultat['source_pdf']['chemin']
        brut = subprocess.run(['pdftotext', '-layout', str(source), '-'], check=True, capture_output=True).stdout.decode()
        self.assertEqual(resultat['texte_original'], brut)

    def test_pdf_mixte_ne_saute_pas_la_page_scannee(self):
        resultat = self.lecture(fabriquer_pdf([{'textes': ['CONTRAT 150 kW']}, {'image': self.image}]), 'deux_pages_mixtes')
        self.assertEqual(resultat['lecture_ocr']['pages_ocr'], [2])
        self.assertEqual(len(resultat['lecture_ocr']['pages']), 2)
        self.assertIn('CONTRAT 150 kW', resultat['texte_original'])
        self.verifier_chiffres(resultat['lecture_ocr']['pages'][1]['texte_ocr'])

    def test_texte_et_scan_sur_la_meme_page(self):
        resultat = self.lecture(fabriquer_pdf([{'textes': ['TITRE NATIF 700 kW'], 'image': self.image}]), 'meme_page_mixte')
        page = resultat['lecture_ocr']['pages'][0]
        self.assertEqual(page['mode'], 'mixte')
        self.assertIn('TITRE NATIF 700 kW', resultat['texte_original'])
        self.verifier_chiffres(page['texte_ocr'])
        self.assertEqual(len(page['plages_lignes']), 2)

    def test_page_vide_signalee_et_numerotation_preservee(self):
        resultat = self.lecture(fabriquer_pdf([{}, {'textes': ['Contrat 150 kW']}]), 'page_vide')
        self.assertEqual(len(resultat['lecture_ocr']['pages']), 2)
        self.assertTrue(any('Page 1 : aucun texte reconnu' in message for message in resultat['lecture_ocr']['avertissements']))
        self.assertIn('[Page 2, texte original]', resultat['texte'])

    def test_refus_pdf_trop_long(self):
        with self.assertRaisesRegex(ValueError, '60 pages'):
            documents.lire_pdf(fabriquer_pdf([{'textes': ['Contrat 150 kW']}] * 61))

    def test_pdf_natif_44_pages_accepte(self):
        resultat = self.lecture(fabriquer_pdf([{'textes': [f'Page {numero}, contrat 150 kW']} for numero in range(1, 45)]), '44_pages_natives')
        self.assertEqual(len(resultat['lecture_ocr']['pages']), 44)
        self.assertEqual(resultat['lecture_ocr']['pages_ocr'], [])
        self.assertIn('Page 44, contrat 150 kW', resultat['texte_original'])

    def test_stockage_optionnel(self):
        stockage = self.repertoire / 'dossier_serveur'
        donnees = fabriquer_pdf([{'textes': ['Contrat 150 kW']}])
        resultat = documents.lire_pdf(donnees, stockage=stockage)
        self.assertEqual((stockage / resultat['source_pdf']['chemin']).read_bytes(), donnees)

    def test_ocr_absent_ne_supprime_pas_une_page(self):
        outils = self.repertoire / 'outils'
        outils.mkdir()
        import shutil
        (outils / 'pdftotext').symlink_to(shutil.which('pdftotext'))
        with patch.dict(os.environ, {'PATH': str(outils)}):
            with self.assertRaisesRegex(ValueError, 'Tesseract absent'):
                documents.lire_pdf(fabriquer_pdf([{'textes': ['Contrat 150 kW']}, {'image': self.image}]))

    def test_refus_pdf_trop_lourd(self):
        with self.assertRaisesRegex(ValueError, '5 Mio'):
            documents.lire_pdf(b'%PDF-' + b'x' * (5 * 1024 * 1024))

    def test_refus_pdf_invalide(self):
        with self.assertRaisesRegex(ValueError, 'illisible'):
            documents.lire_pdf(b'%PDF-1.4\ncorrompu')

    def test_refus_rendu_demesure(self):
        with self.assertRaisesRegex(ValueError, '12 millions de pixels'):
            documents.lire_pdf(fabriquer_pdf([{'image': self.image}], dimensions=(5000, 5000)))

    def test_delai_arrete_aussi_le_processus_enfant(self):
        fichier_pid = self.repertoire / 'enfant.pid'
        faux_script = self.repertoire / 'lecture_lente.py'
        faux_script.write_text('import subprocess, sys, time\nfrom pathlib import Path\n'
                              'enfant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
                              f'Path({str(fichier_pid)!r}).write_text(str(enfant.pid))\n'
                              'time.sleep(30)\n')
        with patch.object(documents, 'SCRIPT_OCR', faux_script), patch.object(documents, 'DELAI_LECTURE_PDF', 1):
            with self.assertRaisesRegex(ValueError, 'limite de 100 secondes'):
                documents.lire_pdf(fabriquer_pdf([{'textes': ['150 kW']}]))
        self.assertTrue(fichier_pid.exists(), 'Le processus enfant doit avoir été lancé pour que le test soit significatif.')
        pid = int(fichier_pid.read_text())
        self.assertTrue(enfant_deja_arrete(pid), 'Le processus OCR enfant continue après le délai.')

    def test_enfant_disparu_entre_ps_et_kill(self):
        with patch('subprocess.run') as ps, patch('os.kill', side_effect=ProcessLookupError):
            ps.return_value.stdout = 'S'
            self.assertTrue(enfant_deja_arrete(123))

    def test_enfant_nettoye_par_le_test_reste_un_echec(self):
        with patch('subprocess.run') as ps, patch('os.kill') as tuer:
            ps.return_value.stdout = 'S'
            self.assertFalse(enfant_deja_arrete(123))
            tuer.assert_called_once_with(123, signal.SIGKILL)

    def test_enfant_arrete_ou_zombie_pas_de_signal(self):
        for etat in ('', 'Z', 'Zs'):
            with self.subTest(etat=etat), patch('subprocess.run') as ps, patch('os.kill') as tuer:
                ps.return_value.stdout = etat
                self.assertTrue(enfant_deja_arrete(123))
                tuer.assert_not_called()


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(VerificationOCR)
    resultat = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'mesures': VerificationOCR.mesures}, ensure_ascii=False, indent=2))
    sys.exit(0 if resultat.wasSuccessful() else 1)
