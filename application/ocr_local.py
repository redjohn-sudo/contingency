"""PDF natif et OCR Tesseract local, exécuté dans .venv-documents.

Les images et chiffres lus restent des preuves à vérifier, sans normalisation.
Le processus parent borne aussi l'exécution et arrête les processus enfants.
"""
import csv
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version

LIMITE_PAGES = 60
LIMITE_OCTETS = 5 * 1024 * 1024
LIMITE_PIXELS = 12_000_000
LIMITE_TEXTE = 2_000_000
DELAI_TOTAL = 95
DELAI_PAGE = 15
DPI = 300
LANGUES = 'fra+eng+nld'


def executer(arguments, echeance, delai):
    restant = min(delai, echeance - time.monotonic())
    if restant <= 0:
        raise ValueError('limite de temps atteinte ; import incomplet refusé.')
    try:
        return subprocess.run(arguments, capture_output=True, check=True,
                              timeout=restant, env=os.environ.copy())
    except subprocess.TimeoutExpired as cause:
        raise ValueError('limite de temps atteinte ; import incomplet refusé.') from cause
    except (OSError, subprocess.CalledProcessError) as cause:
        raise ValueError('outil de lecture indisponible ou PDF illisible ; import incomplet refusé.') from cause


def lire_mots(chemin):
    """Conserver texte, score brut du moteur et boîte dans l'image rendue."""
    mots = []
    with chemin.open(encoding='utf-8') as fichier:
        for ligne in csv.DictReader(fichier, delimiter='\t', quoting=csv.QUOTE_NONE):
            if ligne.get('level') != '5' or not ligne.get('text', '').strip():
                continue
            score = float(ligne['conf'])
            mots.append({'texte': ligne['text'], 'score_moteur': round(score, 2),
                         'boite_pixels': [int(ligne[cle]) for cle in ('left', 'top', 'width', 'height')],
                         'contient_nombre': bool(re.search(r'\d', ligne['text']))})
    return mots


def lire(chemin):
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_brut

    debut = time.monotonic()
    echeance = debut + DELAI_TOTAL
    chemin = Path(chemin)
    if chemin.stat().st_size > LIMITE_OCTETS:
        raise ValueError('limite de 5 Mio dépassée.')
    empreinte = hashlib.sha256(chemin.read_bytes()).hexdigest()
    prefixe_source = f'sources/{empreinte}'
    try:
        pdf = pdfium.PdfDocument(chemin)
    except pdfium.PdfiumError as cause:
        raise ValueError('PDF illisible ou protégé par un mot de passe.') from cause
    with pdf:
        if not 1 <= len(pdf) <= LIMITE_PAGES:
            raise ValueError('limite de 60 pages dépassée ou PDF vide ; import incomplet refusé.')
        original = executer(['pdftotext', '-layout', str(chemin), '-'], echeance, 20).stdout.decode('utf-8')
        if len(original) > LIMITE_TEXTE:
            raise ValueError('texte PDF trop volumineux ; import incomplet refusé.')
        textes_pages = original.split('\f')
        if textes_pages and not textes_pages[-1].strip():
            textes_pages.pop()
        if len(textes_pages) != len(pdf):
            raise ValueError('repérage des pages incohérent ; import incomplet refusé.')
        pages, lignes, pages_ocr, avertissements = [], [], [], []
        version_tesseract = None
        total_caracteres = len(original)
        for index in range(len(pdf)):
            if time.monotonic() >= echeance:
                raise ValueError('limite de temps atteinte ; import incomplet refusé.')
            numero = index + 1
            natif = textes_pages[index]
            with closing(pdf[index]) as page:
                # Toute image, même petite, peut contenir un chiffre utile.
                images_presentes = any(page.get_objects(filter=[pdfium_brut.FPDF_PAGEOBJ_IMAGE]))
                besoin_ocr = images_presentes or not natif.strip()
                lecture = {'page': numero, 'mode': 'texte', 'texte_original': natif,
                           'texte_ocr': '', 'image_source': None, 'plages_lignes': [],
                           'mots_ocr': [], 'a_verifier': False}

                def ajouter(texte, origine):
                    if not texte.strip():
                        return
                    lignes.append(f'[Page {numero}, {origine}]')
                    premier = len(lignes) + 1
                    lignes.extend(texte.rstrip('\n').splitlines())
                    lecture['plages_lignes'].append({'debut': premier, 'fin': len(lignes),
                                                     'origine': origine})

                ajouter(natif, 'texte original')
                if besoin_ocr:
                    if version_tesseract is None:
                        if not shutil.which('tesseract'):
                            raise ValueError('Tesseract absent pour une page scannée ; import incomplet refusé.')
                        version_tesseract = executer(['tesseract', '--version'], echeance, 5).stdout.decode().splitlines()[0]
                        langues = executer(['tesseract', '--list-langs'], echeance, 5).stdout.decode().splitlines()
                        if not set(LANGUES.split('+')).issubset(langues):
                            raise ValueError('modèles Tesseract fra, eng et nld requis localement ; aucun téléchargement automatique.')
                    largeur, hauteur = page.get_size()
                    if not (math.isfinite(largeur) and math.isfinite(hauteur) and largeur > 0 and hauteur > 0):
                        raise ValueError(f'dimensions invalides page {numero}.')
                    pixels = math.ceil(largeur * DPI / 72) * math.ceil(hauteur * DPI / 72)
                    if pixels > LIMITE_PIXELS:
                        raise ValueError(f'page {numero} trop grande pour le rendu OCR (12 millions de pixels).')
                    nom_image = f'page-{numero:04d}.png'
                    image = chemin.parent / nom_image
                    with closing(page.render(scale=DPI / 72)) as bitmap:
                        dimensions_image = [bitmap.width, bitmap.height]
                        with bitmap.to_pil() as rendu:
                            rendu.save(image, dpi=(DPI, DPI))
                    with tempfile.TemporaryDirectory() as travail:
                        sortie = Path(travail) / 'lecture'
                        executer(['tesseract', str(image), str(sortie), '-l', LANGUES,
                                  '--psm', '3', '--dpi', str(DPI), 'txt', 'tsv'], echeance, DELAI_PAGE)
                        ocr = sortie.with_suffix('.txt').read_text(encoding='utf-8')
                        mots = lire_mots(sortie.with_suffix('.tsv'))
                    total_caracteres += len(ocr)
                    if total_caracteres > LIMITE_TEXTE:
                        raise ValueError('texte OCR trop volumineux ; import incomplet refusé.')
                    lecture.update({'mode': 'mixte' if natif.strip() else 'ocr',
                                    'texte_ocr': ocr, 'image_source': f'{prefixe_source}/{nom_image}',
                                    'mots_ocr': mots, 'a_verifier': True,
                                    'raison_ocr': 'image_presente' if images_presentes else 'page_sans_texte',
                                    'dimensions_image': dimensions_image,
                                    'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest()})
                    ajouter(ocr, 'OCR à vérifier')
                    pages_ocr.append(numero)
                    if not ocr.strip():
                        avertissements.append(f'Page {numero} : aucun texte reconnu par OCR ; vérifier l’image, la page peut être vide ou illisible.')
                    if any(mot['score_moteur'] < 70 for mot in mots):
                        avertissements.append(f'Page {numero} : certains mots ont un score moteur inférieur à 70 ; vérifier l’image.')
                pages.append(lecture)
        texte = '\n'.join(lignes) + '\n'
        if not any(page['texte_original'].strip() or page['texte_ocr'].strip() for page in pages):
            raise ValueError('aucun texte reconnu, même après OCR ; import incomplet refusé.')
    return {'texte': texte, 'texte_original': original,
            'source_pdf': {'sha256': empreinte, 'chemin': f'{prefixe_source}/source.pdf'},
            'lecture_ocr': {
                'statut': 'extrait_a_verifier' if pages_ocr else 'non_necessaire',
                'moteur': version_tesseract, 'pypdfium2': version('pypdfium2'),
                'langues': LANGUES.split('+') if pages_ocr else [], 'dpi': DPI if pages_ocr else None,
                'pages': pages, 'pages_ocr': pages_ocr, 'avertissements': avertissements,
                'secondes': round(time.monotonic() - debut, 3),
                'limites': {'pages': LIMITE_PAGES, 'octets': LIMITE_OCTETS,
                            'secondes_document': DELAI_TOTAL, 'secondes_ocr_page': DELAI_PAGE,
                            'pixels_page': LIMITE_PIXELS},
                'message': ('OCR local à vérifier sur les images conservées, en particulier chiffres, unités et cellules. '
                            'Les scores du moteur ne sont pas des probabilités de lecture correcte. '
                            'Le texte original reste conservé séparément.' if pages_ocr else
                            'Texte natif lu page par page. Aucun OCR nécessaire, ce statut ne valide pas les chiffres.')
            }}


if __name__ == '__main__':
    os.environ.setdefault('OMP_THREAD_LIMIT', '2')
    os.environ.setdefault('OMP_NUM_THREADS', '2')
    try:
        resultat = lire(sys.argv[1])
        Path(sys.argv[2]).write_text(json.dumps(resultat, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    except Exception as erreur:
        # Un échec ne doit jamais devenir silencieusement un document partiel.
        print('Lecture PDF : ' + str(erreur), file=sys.stderr)
        sys.exit(1)
