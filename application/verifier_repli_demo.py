"""Échec IA simulé puis repli dans Brave, sans aucun appel fournisseur.

Exécution autonome, captures dans .local/repli-demo. L'étude initiale reste intacte,
la réponse archivée conserve sa provenance, y compris dans une iframe de 390 px.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import serveur
from verifier_live import demo_temporaire

URL = 'http://127.0.0.1:8766'
SORTIE = Path(__file__).resolve().parents[1] / '.local/repli-demo'


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    erreurs = []
    captures = []
    with demo_temporaire() as client, sync_playwright() as outil, patch.object(
            serveur, 'extraire_avec_nebius', side_effect=ValueError('Analyse simulée indisponible.')) as fournisseur:
        def servir(route):
            requete = route.request
            if not requete.url.startswith(URL + '/'):
                route.abort()
                return
            adresse = urlsplit(requete.url)
            if adresse.path == '/verification-cadre':
                route.fulfill(content_type='text/html', body=f'<iframe src="{URL}/demo" style="width:390px;height:900px;border:0"></iframe>')
                return
            reponse = client.request(requete.method, adresse.path + ('?' + adresse.query if adresse.query else ''),
                                     content=requete.post_data_buffer,
                                     headers={'content-type': requete.headers.get('content-type', 'application/json')})
            route.fulfill(status=reponse.status_code, body=reponse.content,
                          headers={k: v for k, v in reponse.headers.items()
                                   if k.lower() not in {'content-length', 'content-encoding', 'transfer-encoding'}})

        def executer_repli(cadre):
            cadre.locator('#try-sample').click()
            cadre.locator('#analyze-documents').wait_for(state='visible')
            identifiant = cadre.evaluate('dossier.id')
            avant = serveur.charger(identifiant)
            machines_avant = cadre.evaluate('JSON.parse(localStorage.getItem("contingency-machines-v2"))')
            cadre.locator('#analyze-documents').click()
            cadre.locator('#demo-repli').wait_for(state='visible')
            assert 'indisponible' in cadre.locator('#document-error').inner_text()
            assert serveur.charger(identifiant) == avant
            cadre.locator('#demo-repli').click()
            cadre.wait_for_function('dossier?.mode_extraction === "demo_archivee"')
            assert cadre.evaluate('dossier.id') != identifiant
            assert cadre.evaluate('factory.machine') is None
            assert cadre.evaluate('dossier.extraction_ia.execution') == 'recorded'
            assert 'Recorded demonstration' in cadre.locator('#provenance-analyse').inner_text()
            assert serveur.charger(identifiant) == avant
            assert cadre.locator('#factory-studies [data-machine-id]').count() == 0
            assert cadre.evaluate('JSON.parse(localStorage.getItem("contingency-machines-v2"))') == machines_avant
            cadre.wait_for_function('scrollY === 0')
            return identifiant

        navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
        try:
            contexte = navigateur.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
            contexte.route('**/*', servir)
            page = contexte.new_page()
            page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
            page.goto(URL + '/demo')
            source = executer_repli(page)
            assert fournisseur.call_count == 1
            for largeur in (600, 2000):
                page.set_viewport_size({'width': largeur, 'height': 1100})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), largeur
                chemin = SORTIE / f'repli-{largeur}.png'
                page.screenshot(path=str(chemin), full_page=True)
                captures.append(str(chemin))
            # Les étapes suivantes restent un rejeu, même dans un serveur live.
            page.locator('#add-machine').click()
            page.locator('#machine-form button[type=submit]').click()
            page.locator('#analyze-documents').click()
            page.wait_for_function('factory.canReview && dossier.extraction_ia.execution === "recorded"')
            assert fournisseur.call_count == 1
            assert page.locator('#factory-studies [data-machine-id]').count() == 1
            assert page.evaluate('JSON.parse(localStorage.getItem("contingency-machines-v2")).length') == 2
            page.locator('#retour-etude').click()
            page.wait_for_function('(source) => dossier.id === source', arg=source)
            assert page.evaluate('dossier.extraction_ia') is None
            assert page.evaluate('factory.machine') is not None
            assert page.locator('#retour-etude').is_hidden()
            assert fournisseur.call_count == 1
            contexte.close()

            mobile = navigateur.new_context(viewport={'width': 600, 'height': 1000}, reduced_motion='reduce')
            mobile.route('**/*', servir)
            parent = mobile.new_page()
            parent.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
            parent.goto(URL + '/verification-cadre')
            cadre = parent.frames[-1]
            cadre.wait_for_selector('#try-sample')
            executer_repli(cadre)
            assert cadre.evaluate('innerWidth') == 390
            assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
            chemin = SORTIE / 'repli-390.png'
            parent.locator('iframe').screenshot(path=str(chemin))
            captures.append(str(chemin))
            assert fournisseur.call_count == 2
            mobile.close()
        finally:
            navigateur.close()
    assert not erreurs, erreurs
    resultat = {'appels_fournisseur_reels': 0, 'echecs_simules': 2,
                'largeurs_verifiees': [600, 2000, 390], 'erreurs_javascript': erreurs,
                'captures': captures}
    (SORTIE / 'verification.json').write_text(json.dumps(resultat, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(resultat, ensure_ascii=False))


if __name__ == '__main__':
    main()
