"""Rendus FR/NL des périodes et erreurs EN, Brave sans réseau extérieur."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

import rapport_controles
import rapport_nl
from verifier_periode_exacte import periode


def main():
    racine = Path(__file__).resolve().parent
    sortie = racine.parent / '.local/periode-exacte'
    sortie.mkdir(parents=True, exist_ok=True)
    dossier = {'profil_brut': [12.5] * 92, 'profil_horodatages': periode()[:-4],
               'unite_profil': 'kw', 'kwmax_facture': 12.5, 'kwh_facture': 287.5,
               'gtv_kw': 30, 'periode_facture_debut': '2026-09-01',
               'periode_facture_fin': '2026-09-01', 'mesure_au_point_de_livraison': True}
    rapport = rapport_controles.composer(dossier)
    captures, erreurs = [], []
    with sync_playwright() as outil:
        navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
        try:
            contexte = navigateur.new_context(viewport={'width': 600, 'height': 1000})
            contexte.route('**/*', lambda route: route.abort())
            page = contexte.new_page()
            page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
            for langue, contenu, attendu in [
                ('fr', rapport_controles.en_html(rapport), 'MESURES NON VÉRIFIÉES'),
                ('nl', rapport_nl.en_html(rapport, 'Fictief testgeval'), 'Metingen niet bevestigd'),
            ]:
                (sortie / f'rapport-{langue}.html').write_text(contenu)
                page.set_content(contenu)
                assert attendu.lower() in page.locator('body').inner_text().lower()
                assert 'Europe/Amsterdam' in page.locator('body').inner_text()
                for largeur in (600, 2000):
                    page.set_viewport_size({'width': largeur, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    chemin = sortie / f'rapport-{langue}-{largeur}.png'
                    page.screenshot(path=str(chemin), full_page=True)
                    captures.append(str(chemin))
                page.set_viewport_size({'width': 600, 'height': 1000})
                page.set_content('<iframe style="width:390px;height:900px;border:0"></iframe>')
                cadre = page.frames[-1]
                cadre.set_content(contenu)
                assert cadre.evaluate('innerWidth') == 390
                assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
                chemin = sortie / f'rapport-{langue}-390.png'
                page.locator('iframe').screenshot(path=str(chemin))
                captures.append(str(chemin))
            page.set_content('<main><p>Erreur import</p></main>')
            page.add_script_tag(content=(racine / 'english.js').read_text())
            cas = {
                'Horodatage 1 invalide : Horodatage sans fuseau : préciser le décalage UTC ou utiliser l’import configuré.': 'Invalid timestamp 1: Timestamp has no time zone: provide a UTC offset or use the configured import.',
                'Horodatage 12 invalide : Horodatage hors d’un quart d’heure exact.': 'Invalid timestamp 12: The timestamp is not on an exact quarter-hour boundary.',
                'Colonne vide, absente ou en trop dans le CSV, ligne 7.': 'Empty, missing or extra CSV column at row 7.',
                'CSV mal formé : unexpected end of data': 'Malformed CSV: unexpected end of data',
            }
            for message, attendu in cas.items():
                assert page.evaluate('message => window.uiText(message)', message) == attendu
            contexte.close()
        finally:
            navigateur.close()
    assert not erreurs, erreurs
    resultat = {'largeurs_verifiees': [600, 2000, 390], 'langues_rapport': ['fr', 'nl'],
                'erreurs_import_traduites_en': len(cas), 'erreurs_javascript': erreurs,
                'captures': captures}
    (sortie / 'verification.json').write_text(json.dumps(resultat, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(resultat, ensure_ascii=False))


if __name__ == '__main__':
    main()
