"""Parcours de comparaison dans Brave, fichiers fictifs, réseau extérieur bloqué."""
import json
import copy
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from verifier_live import demo_temporaire
import verifier_optimisation_contrat as exemples
import verifier_pointes_ponderees as ponderation
import serveur

URL = 'http://127.0.0.1:8766'
SORTIE = Path(__file__).resolve().parents[1] / '.local/contrats-nl/navigateur'


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    exemples.ParcoursContrats.setUpClass()
    erreurs = []
    with demo_temporaire() as client, sync_playwright() as outil, patch.object(serveur, 'extraire_avec_nebius', side_effect=AssertionError('IA interdite')) as ia:
        def servir(route):
            requete = route.request
            if not requete.url.startswith(URL + '/'):
                route.abort(); return
            adresse = urlsplit(requete.url)
            if adresse.path == '/cadre':
                route.fulfill(content_type='text/html', body=f'<iframe src="{URL}/contrats" style="width:390px;height:1300px;border:0"></iframe>')
                return
            rapports = {'/rapport-test': 'comparaison.html', '/rapport-nl-test': 'comparaison-nl.html',
                        '/rapport-pondere-nl-test': 'comparaison-ponderee-nl.html'}
            if adresse.path in rapports:
                fichier = rapports[adresse.path]
                route.fulfill(content_type='text/html', body=(SORTIE / fichier).read_text())
                return
            reponse = client.request(requete.method, adresse.path, content=requete.post_data_buffer,
                                     headers={'content-type': requete.headers.get('content-type', 'application/json')})
            route.fulfill(status=reponse.status_code, body=reponse.content,
                          headers={k: v for k, v in reponse.headers.items() if k.lower() not in {'content-length', 'content-encoding', 'transfer-encoding'}})

        def importer(cadre, langue='fr'):
            cadre.locator('#langue').select_option(langue)
            cadre.locator('#profil').set_input_files({'name': 'profil-fictif.csv', 'mimeType': 'text/csv', 'buffer': exemples.ParcoursContrats.csv.encode()})
            cadre.locator('#analyser').click()
            cadre.locator('#modele').wait_for(state='visible')
            assert '2015' not in cadre.locator('#mesures').inner_text()
            assert '2025' in cadre.locator('#mesures').inner_text()
            cadre.locator('#fiche').set_input_files({'name': 'contrats-fictifs.json', 'mimeType': 'application/json', 'buffer': json.dumps(exemples.Comparateur.configuration).encode()})
            cadre.locator('#comparer').click()
            cadre.locator('#resultat').wait_for(state='visible')
            assert 'Option fictive' in cadre.locator('#resume').inner_text()
            assert not cadre.locator('#erreur').inner_text()

        navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
        try:
            contexte = navigateur.new_context(viewport={'width': 1440, 'height': 1200}, reduced_motion='reduce')
            contexte.route('**/*', servir)
            page = contexte.new_page(); page.on('pageerror', lambda e: erreurs.append(str(e)))
            page.goto(URL + '/contrats'); importer(page)
            for identifiant, fichier in [('telecharger', 'comparaison.html'), ('calcul', 'comparaison.json')]:
                with page.expect_download() as attente:
                    page.locator('#' + identifiant).click()
                attente.value.save_as(SORTIE / fichier)
                assert attente.value.suggested_filename == fichier
            for largeur in (600, 2000):
                page.set_viewport_size({'width': largeur, 'height': 1200})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(SORTIE / f'parcours-{largeur}.png'), full_page=True)
            page.locator('#langue').select_option('nl')
            assert page.locator('#resultat').is_hidden()
            page.locator('#comparer').click()
            page.locator('#resultat').wait_for(state='visible')
            with page.expect_download() as attente:
                page.locator('#telecharger').click()
            attente.value.save_as(SORTIE / 'comparaison-nl.html')
            assert '<html lang="nl">' in (SORTIE / 'comparaison-nl.html').read_text()
            page.locator('#fiche').set_input_files({'name': 'ponderation-fictive.json', 'mimeType': 'application/json', 'buffer': json.dumps(ponderation.configuration_ponderee()).encode()})
            page.locator('#comparer').click()
            page.locator('#resultat').wait_for(state='visible')
            with page.expect_download() as attente:
                page.locator('#telecharger').click()
            attente.value.save_as(SORTIE / 'comparaison-ponderee-nl.html')
            assert 'Kwartieren die de gewogen maxima bepalen' in (SORTIE / 'comparaison-ponderee-nl.html').read_text()
            depassee = copy.deepcopy(exemples.Comparateur.configuration)
            depassee['contrat_actuel']['valeur']['gtv_kw'] = 90
            page.locator('#fiche').set_input_files({'name': 'reference-depassee.json', 'mimeType': 'application/json', 'buffer': json.dumps(depassee).encode()})
            page.locator('#comparer').click()
            page.locator('#resultat').wait_for(state='visible')
            assert page.locator('#resume').inner_text() == 'Aucun gagnant financier établi'
            assert 'référence actuelle dépassée' in page.locator('#options').inner_text()
            non_fixe = copy.deepcopy(exemples.Comparateur.configuration)
            non_fixe['contrat_actuel']['valeur']['produit'] = 'cbc'
            page.locator('#fiche').set_input_files({'name': 'reference-cbc.json', 'mimeType': 'application/json', 'buffer': json.dumps(non_fixe).encode()})
            page.locator('#comparer').click()
            page.locator('#resultat').wait_for(state='visible')
            assert page.locator('#resume').inner_text() == 'Aucun gagnant financier établi'
            assert 'référence non prise en charge' in page.locator('#contexte').inner_text()
            assert page.locator('#options').inner_text() == ''
            # Changer le fichier invalide la conclusion et les liens précédents.
            page.locator('#fiche').set_input_files({'name': 'invalide.json', 'mimeType': 'application/json', 'buffer': b'{invalide'})
            assert page.locator('#resultat').is_hidden()
            page.locator('#comparer').click()
            page.wait_for_function('document.getElementById("erreur").textContent.length > 0')
            assert page.locator('#resultat').is_hidden()
            page.goto(URL + '/rapport-test')
            for largeur in (600, 2000):
                page.set_viewport_size({'width': largeur, 'height': 1200})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(SORTIE / f'rapport-{largeur}.png'), full_page=True)
            page.goto(URL + '/rapport-nl-test')
            assert page.locator('html').get_attribute('lang') == 'nl'
            assert 'Laagste referentiekosten' in page.locator('h1').inner_text()
            assert 'NorthC' in page.locator('.risque').inner_text()
            for largeur in (600, 2000):
                page.set_viewport_size({'width': largeur, 'height': 1200})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(SORTIE / f'rapport-nl-{largeur}.png'), full_page=True)
            page.goto(URL + '/rapport-pondere-nl-test')
            page.locator('summary').filter(has_text='Kwartieren die de gewogen maxima bepalen').first.click()
            assert '92.520,00 €' in page.locator('body').inner_text()
            for largeur in (600, 2000):
                page.set_viewport_size({'width': largeur, 'height': 1200})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(SORTIE / f'rapport-pondere-nl-{largeur}.png'), full_page=True)
            contexte.close()
            mobile = navigateur.new_context(viewport={'width': 600, 'height': 1400})
            mobile.route('**/*', servir)
            parent = mobile.new_page(); parent.on('pageerror', lambda e: erreurs.append(str(e)))
            parent.goto(URL + '/cadre'); cadre = parent.frames[-1]; importer(cadre)
            assert cadre.evaluate('innerWidth') == 390
            assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
            parent.locator('iframe').screenshot(path=str(SORTIE / 'parcours-390.png'))
            cadre.goto(URL + '/rapport-test')
            assert cadre.evaluate('innerWidth') == 390
            assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
            parent.locator('iframe').screenshot(path=str(SORTIE / 'rapport-390.png'))
            cadre.goto(URL + '/contrats'); importer(cadre, 'nl')
            cadre.goto(URL + '/rapport-nl-test')
            assert cadre.evaluate('innerWidth') == 390
            assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
            parent.locator('iframe').screenshot(path=str(SORTIE / 'rapport-nl-390.png'))
            cadre.goto(URL + '/rapport-pondere-nl-test')
            cadre.locator('summary').filter(has_text='Kwartieren die de gewogen maxima bepalen').first.click()
            assert cadre.evaluate('innerWidth') == 390
            assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
            cadre.locator('summary').filter(has_text='Kwartieren die de gewogen maxima bepalen').first.scroll_into_view_if_needed()
            parent.locator('iframe').screenshot(path=str(SORTIE / 'rapport-pondere-nl-390.png'))
            mobile.close(); ia.assert_not_called()
        finally:
            navigateur.close()
    assert not erreurs, erreurs
    resultat = {'largeurs': [600, 2000, 390], 'erreurs_javascript': erreurs,
                'appels_ia': 0, 'langues_rapport': ['fr', 'nl'],
                'telechargements': ['comparaison.html', 'comparaison.json', 'comparaison-nl.html', 'comparaison-ponderee-nl.html']}
    (SORTIE / 'verification.json').write_text(json.dumps(resultat, indent=2) + '\n')
    print(json.dumps(resultat))


if __name__ == '__main__':
    main()
