"""Vérifie les rapports batterie synthétiques dans Brave, sans accès réseau."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

import rapport_controles
import rapport_nl
from verifier_engagements_batterie import dossier, service


def main():
    sortie = Path(__file__).resolve().parents[1] / '.local/controles-batterie'
    sortie.mkdir(parents=True, exist_ok=True)
    rapport = rapport_controles.composer(dossier() | {'batterie_utile_dc_annoncee_kwh': 200.,
                                                     'batterie_puissance_dc_demandee_kw': 150.,
                                                     'batterie_engagements_simultanes': [service('Piek', 100, 10, 60, 20),
                                                                                       service('Reserve', 60, 20, 40, 30)]})
    erreurs, captures = [], []
    with sync_playwright() as outil:
        navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
        try:
            for langue, texte in {'fr': rapport_controles.en_html(rapport),
                                   'nl': rapport_nl.en_html(rapport, 'Fictief testgeval')}.items():
                (sortie / f'rapport-{langue}.html').write_text(texte)
                contexte = navigateur.new_context(viewport={'width': 600, 'height': 1000})
                contexte.route('**/*', lambda route: route.abort())
                page = contexte.new_page()
                page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
                page.set_content(texte)
                assert 'CTRL-BAT-ENGAGEMENTS' in page.locator('body').inner_text()
                for largeur in (600, 2000):
                    page.set_viewport_size({'width': largeur, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (langue, largeur)
                    chemin = sortie / f'rapport-{langue}-{largeur}.png'
                    page.screenshot(path=str(chemin), full_page=True)
                    captures.append(str(chemin))
                page.set_viewport_size({'width': 600, 'height': 1000})
                page.set_content('<iframe style="width:390px;height:900px;border:0"></iframe>')
                cadre = page.frames[-1]
                cadre.set_content(texte)
                assert cadre.evaluate('innerWidth') == 390
                assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth'), (langue, 390)
                chemin = sortie / f'rapport-{langue}-390.png'
                page.locator('iframe').screenshot(path=str(chemin))
                captures.append(str(chemin))
                contexte.close()
        finally:
            navigateur.close()
    assert not erreurs, erreurs
    bilan = {'erreurs_javascript': erreurs, 'langues': ['fr', 'nl'],
             'largeurs_verifiees': [600, 2000, 390], 'captures': captures}
    (sortie / 'verification.json').write_text(json.dumps(bilan, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(bilan, ensure_ascii=False))


if __name__ == '__main__':
    main()
