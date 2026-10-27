"""Parcours guidé réel dans un navigateur isolé : archive DeepSeek du 24/09, aucun appel IA.

Réécrit le 24/09 pour l'interface guidée du 23/09 (factory.js, parcours.js) :
accueil, documents, quatre alertes à trancher, sept valeurs, simulation, résultat.
L'ancienne version cliquait sur #exemple, bouton désormais caché exprès puisque
la démo ouvre elle-même le dossier archivé.
"""
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import lancer_demo_archivee as demo
import serveur

SORTIE = Path(__file__).resolve().parent.parent / 'audit-revue-20260924'
URL = 'http://127.0.0.1:8766'
ETAPE = "document.getElementById('journey-step').innerText.includes('{} of 5')"


def position(page):
    return page.locator('#review-position').inner_text()


def sans_defilement_horizontal(cible):
    return cible.evaluate('document.documentElement.scrollWidth <= innerWidth')


def main():
    SORTIE.mkdir(exist_ok=True)
    ancien = serveur.DOSSIERS
    with tempfile.TemporaryDirectory() as temporaire:
        demo.configurer(temporaire)
        try:
            with TestClient(serveur.app) as client, sync_playwright() as outil:
                navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
                try:
                    contexte = navigateur.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
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
                                      headers={k: v for k, v in reponse.headers.items()
                                               if k.lower() not in {'content-length', 'content-encoding', 'transfer-encoding'}})

                    contexte.route('**/*', servir)
                    page = contexte.new_page()
                    page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))

                    # 1. La démo ouvre seule le dossier archivé et propose l'exemple.
                    page.goto(URL + '/demo')
                    page.locator('#try-sample').wait_for()
                    identifiant = page.evaluate('dossier.id')
                    assert page.locator('#exemple').is_hidden()
                    for largeur in (600, 2000):
                        page.set_viewport_size({'width': largeur, 'height': 1100})
                        assert sans_defilement_horizontal(page), f'défilement horizontal à {largeur} px (accueil)'
                        page.screenshot(path=str(SORTIE / f'accueil-{largeur}.png'))
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.locator('#try-sample').click()
                    page.wait_for_function(ETAPE.format(2))
                    assert page.locator('.keep-document:checked').count() == 9

                    # 2. « Analyser » rejoue la réponse enregistrée, sans nouvel appel.
                    page.locator('#analyze-documents').click()
                    page.wait_for_function(ETAPE.format(3), timeout=120000)
                    relance = client.post(f'/api/{identifiant}/extraire')
                    assert relance.status_code == 200
                    assert relance.json()['extraction_ia']['execution'] == 'recorded'
                    assert relance.json()['extraction_ia']['modele'] == 'deepseek-ai/DeepSeek-V4.1-Flash'

                    # 3. Quatre alertes : aucune ne passe sans accord explicite.
                    assert position(page) == '1 / 4'
                    assert 'The battery numbers do not add up.' in page.locator('#verification').inner_text()
                    assert page.locator('#preparer').is_disabled(), 'une alerte peut être franchie sans accord'
                    for rang in range(1, 5):
                        assert position(page) == f'{rang} / 4'
                        page.locator('.accord-alerte:visible').check()
                        page.locator('#preparer').click()

                    # 4. Sept valeurs : trois manquent, les hypothèses de démo les remplissent.
                    assert position(page) == '1 / 7'
                    assert '4 / 7' in page.locator('#bilan-valeurs').inner_text()
                    for _ in range(7):
                        if page.locator('#hypotheses-demo:visible').count():
                            page.locator('#hypotheses-demo').click()
                        page.locator('#preparer').click()
                    assert '7 / 7' in page.locator('#bilan-valeurs').inner_text()
                    page.wait_for_function(ETAPE.format(4))

                    # 5. Le calcul exige l'accord sur les valeurs.
                    assert page.locator('#calculer').is_disabled()
                    page.locator('#accord').check()
                    page.locator('#calculer').click()
                    page.wait_for_function(ETAPE.format(5), timeout=120000)
                    resultat_affiche = page.locator('#resultat').inner_text()
                    assert '45.84 kWh' in resultat_affiche, resultat_affiche[:300]
                    assert '137.51 kWh' in resultat_affiche
                    for largeur in (600, 2000):
                        page.set_viewport_size({'width': largeur, 'height': 1100})
                        assert sans_defilement_horizontal(page), f'défilement horizontal à {largeur} px (résultat)'
                        page.screenshot(path=str(SORTIE / f'resultat-{largeur}.png'))

                    # Le parcours peut créer une étude distincte de l'archive ouverte au départ.
                    identifiant = page.evaluate('dossier.id')
                    donnees = client.get(f'/api/{identifiant}/donnees').json()
                    assert donnees['controle_rapport']['statut'] == 'optimal'
                    rapport = client.get(f'/api/{identifiant}/rapport')
                    assert rapport.status_code == 200
                    (SORTIE / 'rapport.md').write_text(rapport.text)
                    (SORTIE / 'donnees.json').write_text(json.dumps(donnees, ensure_ascii=False, indent=2))

                    # 6. Vraie largeur de téléphone : 390 px dans une iframe.
                    # Page neuve : set_content garde les minuteurs de l'ancienne page.
                    page = contexte.new_page()
                    page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
                    page.set_viewport_size({'width': 1000, 'height': 1000})
                    page.set_content(f'<iframe src="{URL}/demo" style="width:390px;height:900px;border:0"></iframe>')
                    cadre = page.frames[1]
                    # L'accueil ne s'affiche qu'à la première visite : attendre le dossier.
                    cadre.wait_for_function('typeof dossier!=="undefined"&&dossier&&dossier.id')
                    assert sans_defilement_horizontal(cadre), 'défilement horizontal à 390 px'
                    page.locator('iframe').screenshot(path=str(SORTIE / 'accueil-390.png'))

                    assert not erreurs, erreurs
                    assert not externes, externes
                    bilan = {'archive_deepseek_20260924': True, 'nouvel_appel_ia': False,
                             'alertes_bloquees_sans_accord': 4, 'valeurs_completees': '7 / 7',
                             'calcul_bloque_sans_accord': True, 'resultat_45_84_kwh': True,
                             'controle_rapport': donnees['controle_rapport']['statut'],
                             'largeurs_verifiees': [390, 600, 2000], 'erreurs_javascript': erreurs,
                             'requetes_externes': externes,
                             'non_couvert': 'variante « Change schedule » et libellés français, à ajouter'}
                    (SORTIE / 'verification.json').write_text(json.dumps(bilan, ensure_ascii=False, indent=2))
                    print(json.dumps(bilan, ensure_ascii=False))
                finally:
                    navigateur.close()
        finally:
            serveur.DOSSIERS = ancien


if __name__ == '__main__':
    main()
