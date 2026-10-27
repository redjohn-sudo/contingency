"""Parcours navigateur isolé : preuves exactes, variantes et exports."""
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import lancer_demo_archivee as demo
import serveur

SORTIE = Path(__file__).resolve().parent.parent / '.local/preuves-sensibilite'
URL = 'http://127.0.0.1:8766'


def verifier_preuves(page, bloc):
    boutons = bloc.locator('.preuve-contexte')
    for bouton in boutons.all():
        bouton.evaluate('(e)=>{for(let p=e.parentElement;p;p=p.parentElement){if(p.tagName==="DETAILS")p.open=true}}')
        citation = bouton.get_attribute('data-citation')
        bouton.click()
        assert page.locator('#passage-preuve mark').first.inner_text() == citation
        page.locator('#passage-preuve button').first.click()
    return boutons.count()


def preparer(page, capture=None):
    page.locator('#try-sample').click()
    page.locator('#analyze-documents').click()
    page.locator('.alerte-documentaire:visible').first.wait_for()
    total_preuves = 0
    for _ in range(page.locator('.alerte-documentaire').count()):
        total_preuves += verifier_preuves(page, page.locator('.alerte-documentaire:visible'))
        page.locator('.accord-alerte:visible').check()
        page.locator('#preparer').click()
    for _ in range(page.locator('#faits>.fait').count()):
        bloc = page.locator('#faits>.fait:visible')
        if bloc.get_attribute('data-cle') == 'plafond_kw' and capture:
            bloc.locator('[data-disclosure="source"]').click()
            capture(page, bloc.locator('.source-courte .preuve-contexte').first)
        if page.locator('#hypotheses-demo:visible').count():
            page.locator('#hypotheses-demo').click()
        page.locator('#preparer').click()
    assert page.locator('#calculer').is_disabled()
    page.locator('#accord').check()
    page.locator('#calculer').click()
    page.locator('#resultat').wait_for(state='visible')
    return total_preuves


def sensibilite(page):
    page.locator('#sensibilite summary').click()
    assert page.locator('#calculer-sensibilite').is_disabled()
    page.locator('#variation-plafond').fill('25')
    page.locator('#motif-sensibilite').fill('Exploratory stress test, not measured site uncertainty.')
    page.locator('#accord-sensibilite').check()
    page.locator('#calculer-sensibilite').click()
    page.locator('.resultats-sensibilite').wait_for(state='visible')
    assert page.locator('.resultats-sensibilite tbody tr').count() == 5


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    ancien = serveur.DOSSIERS
    with tempfile.TemporaryDirectory() as temporaire:
        demo.configurer(temporaire)
        try:
            with TestClient(serveur.app) as client, sync_playwright() as outil:
                navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
                try:
                    contexte = navigateur.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                    contexte.add_init_script("try{localStorage.removeItem('contingency-welcome-v2')}catch{}")
                    erreurs, externes = [], []

                    def servir(route):
                        requete = route.request
                        if not requete.url.startswith(URL + '/'):
                            externes.append(requete.url)
                            route.abort()
                            return
                        adresse = urlsplit(requete.url)
                        reponse = client.request(requete.method, adresse.path + ('?' + adresse.query if adresse.query else ''),
                            content=requete.post_data_buffer,
                            headers={'content-type': requete.headers.get('content-type', 'application/json')})
                        route.fulfill(status=reponse.status_code, body=reponse.content,
                            headers={k: v for k, v in reponse.headers.items() if k.lower() not in
                                     {'content-length', 'content-encoding', 'transfer-encoding'}})

                    contexte.route('**/*', servir)
                    page = contexte.new_page()
                    page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
                    for langue in ('fr', 'en'):
                        page.goto(URL + '/demo?lang=' + langue)
                        def capturer_preuve(page, preuve):
                            for largeur in (600, 2000):
                                page.set_viewport_size({'width': largeur, 'height': 1100})
                                preuve.click()
                                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                                page.screenshot(path=str(SORTIE / f'preuve-{langue}-{largeur}.png'))
                                page.locator('#passage-preuve button').first.click()
                        total_preuves = preparer(page, capturer_preuve)
                        assert total_preuves >= 5, total_preuves
                        sensibilite(page)
                        identifiant = page.evaluate('dossier.id')
                        export = client.get(f'/api/{identifiant}/donnees').json()
                        assert export['sensibilite_courante']
                        assert abs(export['resultat']['retenu']['capacite_utile_kwh'] - 45.84) < .01
                        assert client.get(f'/api/{identifiant}/rapport-lisible').status_code == 200
                        (SORTIE / f'sensibilite-{langue}.json').write_text(json.dumps(export['sensibilite'], ensure_ascii=False, indent=2))
                        (SORTIE / f'rapport-{langue}.md').write_text(client.get(f'/api/{identifiant}/rapport').text)
                        for largeur in (600, 2000):
                            page.set_viewport_size({'width': largeur, 'height': 1100})
                            page.locator('#sensibilite').scroll_into_view_if_needed()
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                            page.screenshot(path=str(SORTIE / f'sensibilite-{langue}-{largeur}.png'))
                        page.locator('#variation-charge').fill('20')
                        assert not page.locator('#accord-sensibilite').is_checked()
                        assert not page.locator('.resultats-sensibilite').is_visible()
                        assert page.locator('#calculer-sensibilite').is_disabled()
                        page.locator('#compare-again').click()
                        page.locator('#v-echeance_heure').fill('17')
                        assert not page.locator('#resultat').is_visible()

                    # Citations répétées, repères erronés et contenu HTML hostile restent du texte.
                    essais = page.evaluate('''() => {
                      const precedent = dossier;
                      dossier = {documents:[{nom:'test <img src=x onerror=alert(1)>', texte:'Avant\\n150 kW et 150 kW <img src=x onerror=alert(1)>\\nAprès'}]};
                      const faux = boutonPreuve(0,2,'999 kW') === '' && boutonPreuve(0,99,'150 kW') === '' &&
                        boutonRepere({valide:true,repere:'D1:P9:L2',citation:'150 kW'}) === '' &&
                        boutonRepere({valide:false,repere:'D1:L2',citation:'150 kW'}) === '';
                      const zone = document.createElement('div'); zone.innerHTML = boutonPreuve(0,2,'150 kW'); document.body.append(zone);
                      zone.querySelector('button').click();
                      const exact = document.querySelectorAll('#passage-preuve mark').length === 2;
                      const sur = !document.querySelector('#passage-preuve img');
                      document.querySelector('#passage-preuve').close(); zone.remove(); dossier=precedent;
                      return {faux,exact,sur};
                    }''')
                    assert all(essais.values()), essais
                    page.close()
                    page = contexte.new_page()
                    page.set_viewport_size({'width': 1000, 'height': 1000})
                    page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
                    page.set_content(f'<iframe src="{URL}/demo?lang=en" style="width:390px;height:900px;border:0"></iframe>')
                    cadre = page.frames[1]
                    def capturer_mobile(cadre, preuve):
                        preuve.click()
                        assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        page.locator('iframe').screenshot(path=str(SORTIE / 'preuve-en-390.png'))
                        cadre.locator('#passage-preuve button').first.click()
                    preparer(cadre, capturer_mobile)
                    sensibilite(cadre)
                    cadre.locator('#sensibilite').scroll_into_view_if_needed()
                    assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.locator('iframe').screenshot(path=str(SORTIE / 'sensibilite-en-390.png'))
                    assert not erreurs, erreurs
                    assert not externes, externes
                    bilan = {'preuves_exactes': True, 'preuves_alertes_consultables': total_preuves,
                             'ambiguite_et_injection_html': essais, 'cinq_scenarios': True,
                             'validation_requise': True, 'resultat_initial_preserve_45_84': True,
                             'exports': True, 'nouvel_appel_ia': False, 'parametres_langue_testes': ['fr', 'en'],
                             'langue_interface': 'en',
                             'largeurs': [390, 600, 2000], 'erreurs_js': erreurs, 'requetes_externes': externes}
                    (SORTIE / 'verification.json').write_text(json.dumps(bilan, ensure_ascii=False, indent=2))
                    print(json.dumps(bilan, ensure_ascii=False))
                finally:
                    navigateur.close()
        finally:
            serveur.DOSSIERS = ancien


if __name__ == '__main__':
    main()
