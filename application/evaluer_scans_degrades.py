"""Banc OCR local sur dossier inédit construit, sans appel de modèle distant."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
import controle_documentaire as controle
import documents
from verifier_ocr import fabriquer_pdf

RACINE = Path(__file__).resolve().parent.parent
CHAMPS = {
    'plafond_kw': 275.5, 'puissance_kw': 62.8, 'puissance_max_kw': 120.5,
    'rendement': .93, 'duree_heures': 3.25, 'ouverture_heure': 7.5, 'echeance_heure': 18.25,
}
PAGES = [
    ['ATELIER LIERRE : DOSSIER FICTIF', 'Contrat de fourniture',
     'Site : Atelier Lierre', 'Plafond reseau : 275,5 kW.',
     'Puissance apparente : 400 kVA.', 'Document cree pour un essai logiciel.'],
    ['ATELIER LIERRE : DOSSIER FICTIF', 'Fiche de fonctionnement machine',
     'Site : Atelier Lierre', 'Puissance absorbee machine : 62,8 kW.',
     'Duree consecutive : 195 minutes.', 'Debut autorise : 07:30.',
     'Fin obligatoire : 18:15.', 'Ne pas confondre puissance et energie.'],
    ['ATELIER LIERRE : DOSSIER FICTIF', 'Proposition de stockage',
     'Site : Atelier Lierre', 'Puissance maximale batterie : 120,5 kW.',
     'Rendement par sens : 93 %.', 'Capacite nominale : 375 kWh.',
     'Capacite utile : 300 kWh.', 'Profondeur de decharge : 80 %.'],
]
VARIANTES = ('lisible', 'inclinaison', 'faible_contraste', 'basse_resolution', 'flou', 'photocopie_cumulee')
DEGRADATIONS = {
    'lisible': 'Image 1600 x 2264, texte Noto/DejaVu/Arial 40 px.',
    'inclinaison': 'Rotation 3 degrés, interpolation bicubique, fond blanc.',
    'faible_contraste': 'Contraste multiplié par 0,18.',
    'basse_resolution': 'Réduction 400 x 566, puis agrandissement bilinéaire.',
    'flou': 'Flou gaussien de rayon 2,8 px.',
    'photocopie_cumulee': 'Réduction 320 x 453, contraste 0,25, bruit gaussien sigma 5 et graine 20260922, flou 0,55, JPEG qualité 30, agrandissement puis rotation 2 degrés.',
}


def police():
    candidats = ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                 '/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf',
                 '/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf',
                 '/System/Library/Fonts/Supplemental/Arial.ttf']
    disponible = next((Path(p) for p in candidats if Path(p).exists()), None)
    if disponible is None:
        raise RuntimeError('Installer une police DejaVu Sans, Noto Sans ou Arial pour fabriquer les scans.')
    return disponible


def page_source(lignes, chemin_police):
    image = Image.new('RGB', (1600, 2264), 'white')
    dessin = ImageDraw.Draw(image)
    fonte = ImageFont.truetype(str(chemin_police), 40)
    for i, ligne in enumerate(lignes):
        dessin.text((100, 220 + i * 125), ligne, font=fonte, fill='black')
    return image


def degrader(image, variante):
    if variante == 'lisible':
        return image.copy()
    if variante == 'inclinaison':
        return image.rotate(3, resample=Image.Resampling.BICUBIC, fillcolor='white')
    if variante == 'faible_contraste':
        return ImageEnhance.Contrast(image).enhance(.18)
    if variante == 'basse_resolution':
        return image.resize((400, 566), Image.Resampling.LANCZOS).resize(image.size, Image.Resampling.BILINEAR)
    if variante == 'flou':
        return image.filter(ImageFilter.GaussianBlur(2.8))
    if variante == 'photocopie_cumulee':
        petite = image.resize((320, 453), Image.Resampling.LANCZOS)
        petite = ImageEnhance.Contrast(petite).enhance(.25)
        bruit = np.random.default_rng(20260922).normal(0, 5, (453, 320, 1))
        petite = Image.fromarray(np.clip(np.asarray(petite).astype(float) + bruit, 0, 255).astype('uint8'))
        petite = petite.filter(ImageFilter.GaussianBlur(.55))
        flux = io.BytesIO()
        petite.save(flux, format='JPEG', quality=30)
        flux.seek(0)
        with Image.open(flux) as jpeg:
            image = jpeg.convert('RGB').resize(image.size, Image.Resampling.BILINEAR)
        return image.rotate(2, resample=Image.Resampling.BICUBIC, fillcolor='white')
    raise ValueError(variante)


def mesurer(lecture):
    doc = {'texte': lecture['texte'], 'nom': 'atelier-lierre.pdf', 'lecture_ocr': lecture['lecture_ocr']}
    resultats = {}
    for champ, attendu in CHAMPS.items():
        valeurs, preuves = [], []
        for numero, ligne in enumerate(doc['texte'].splitlines(), 1):
            for valeur in controle.valeurs_ligne(champ, ligne):
                accepte, raison = controle.controler_valeur(champ, valeur, doc, numero)
                preuves.append({'ligne': numero, 'texte': ligne, 'valeur': valeur, 'controle_accepte': accepte, 'raison': raison})
                if accepte and not any(controle.egal(valeur, v) for v in valeurs):
                    valeurs.append(valeur)
        statut = 'exact' if len(valeurs) == 1 and controle.egal(valeurs[0], attendu) else 'absent_ou_bloque' if not valeurs else 'divergent'
        resultats[champ] = {'attendu': attendu, 'valeurs_lisibles_par_regles': valeurs, 'statut': statut, 'preuves': preuves}
    mots = [m for p in lecture['lecture_ocr']['pages'] for m in p['mots_ocr'] if m['contient_nombre']]
    return {'champs': resultats, 'exacts': sum(v['statut'] == 'exact' for v in resultats.values()),
            'absents_ou_bloques': sum(v['statut'] == 'absent_ou_bloque' for v in resultats.values()),
            'divergents': sum(v['statut'] == 'divergent' for v in resultats.values()),
            'mots_numeriques_faible_score': [m for m in mots if m['score_moteur'] < 70],
            'avertissements_ocr': lecture['lecture_ocr']['avertissements'],
            'pages_marquees_a_verifier': all(p['a_verifier'] for p in lecture['lecture_ocr']['pages']),
            'limite': 'OCR reel puis regles locales. Aucun LLM. Cas construit, pas un dossier client ni une mesure generale de precision OCR.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sortie', type=Path, default=RACINE/'audit-scans-20260922')
    args = parser.parse_args()
    args.sortie.mkdir(exist_ok=True, parents=True)
    chemin_police = police()
    manifeste = {'nature': 'Dossier fictif nouveau, attentes fixees avant OCR, pas une evaluation independante.',
                 'attendus': CHAMPS, 'textes_originaux': PAGES, 'variantes': list(VARIANTES),
                 'degradations': DEGRADATIONS,
                 'police': chemin_police.name, 'police_sha256': hashlib.sha256(chemin_police.read_bytes()).hexdigest(),
                 'nouvel_appel_ia': False}
    (args.sortie/'attendus.json').write_text(json.dumps(manifeste, ensure_ascii=False, indent=2))
    resultats = []
    for variante in VARIANTES:
        repertoire = args.sortie/variante
        repertoire.mkdir(exist_ok=True)
        images = [degrader(page_source(lignes, chemin_police), variante) for lignes in PAGES]
        for numero, image in enumerate(images, 1):
            image.save(repertoire/f'page-{numero}.png')
        pdf = fabriquer_pdf([{'image': image} for image in images])
        (repertoire/'dossier.pdf').write_bytes(pdf)
        natif = subprocess.run(['pdftotext', str(repertoire/'dossier.pdf'), '-'], capture_output=True, check=True).stdout
        if natif.strip():
            raise AssertionError('Le PDF du banc doit être raster, sans texte caché.')
        debut = time.monotonic()
        resultat = {'variante': variante, 'pdf_sha256': hashlib.sha256(pdf).hexdigest(), 'octets': len(pdf)}
        try:
            lecture = documents.lire_pdf(pdf, stockage=repertoire)
            (repertoire/'lecture.json').write_text(json.dumps(lecture, ensure_ascii=False, indent=2))
            (repertoire/'texte.txt').write_text(lecture['texte'])
            resultat.update(mesurer(lecture))
        except ValueError as erreur:
            resultat.update({'import_refuse': str(erreur)})
        resultat['secondes'] = round(time.monotonic()-debut, 3)
        resultats.append(resultat)
        (args.sortie/'resultats.json').write_text(json.dumps(resultats, ensure_ascii=False, indent=2))
        print(json.dumps({k:v for k,v in resultat.items() if k not in {'champs','mots_numeriques_faible_score','avertissements_ocr'}}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
