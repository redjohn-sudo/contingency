"""Enregistre les vrais écrans du rejeu hors ligne, sans appel IA ni voix synthétique."""
import json
import os
from pathlib import Path
import shutil
import playwright
from playwright.sync_api import sync_playwright

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / 'audit-demo-20260922/scenario'
URL = 'http://127.0.0.1:8766'


def main():
    # Réutiliser FFmpeg installé : le téléchargement Playwright est inaccessible.
    encodeur = shutil.which('ffmpeg')
    if not encodeur:
        raise SystemExit('FFmpeg local absent.')
    paquet = Path(playwright.__file__).parent / 'driver/package'
    versions = json.loads((paquet / 'browsers.json').read_text())['browsers']
    revision = next(v['revision'] for v in versions if v['name'] == 'ffmpeg')
    cache = RACINE / '.local/playwright-video'
    executable = cache / ('ffmpeg-' + revision) / 'ffmpeg-linux'
    executable.parent.mkdir(parents=True, exist_ok=True)
    if not executable.exists():
        executable.symlink_to(encodeur)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(cache)
    SORTIE.mkdir(exist_ok=True)
    with sync_playwright() as outil:
        navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True, slow_mo=180)
        contexte = navigateur.new_context(viewport={'width': 1440, 'height': 1080},
            record_video_dir=str(SORTIE / 'video-brute'), record_video_size={'width': 1440, 'height': 1080})
        page = contexte.new_page()
        page.set_default_timeout(15000)
        video = page.video
        erreurs = []
        page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))

        def montrer(selecteur, secondes):
            page.locator(selecteur).evaluate("e=>e.scrollIntoView({block:'start',behavior:'instant'})")
            page.wait_for_timeout(secondes * 1000)

        try:
            page.goto(URL + '/demo')
            page.wait_for_timeout(3500)
            page.locator('#exemple').click()
            page.locator('.proposition').first.wait_for()
            page.locator('[data-proposition="plafond_kw"] summary').click()
            montrer('[data-proposition="plafond_kw"]', 6)
            # L'incohérence de capacité contient les trois citations du même devis.
            anomalie = page.evaluate("dossier.audit_documentaire.anomalies.find(a=>a.code==='capacite_incoherente').id")
            montrer(f'[data-alerte="{anomalie}"]', 8)
            for champ in ('plafond_kw', 'duree_heures', 'ouverture_heure', 'echeance_heure'):
                page.locator(f'[data-proposition="{champ}"] .accepter-ia').check()
            page.locator('#hypotheses-demo').click()
            montrer('#v-puissance_kw', 3)
            for case in page.locator('.accord-alerte').all():
                case.check()
            page.locator('#preparer').click()
            page.locator('#validation').wait_for(state='visible')
            page.wait_for_timeout(2000)
            page.locator('#accord').check()
            page.locator('#calculer').click()
            page.locator('#resultat').wait_for(state='visible')
            assert '45,84 kWh' in page.locator('#chiffres').inner_text()
            montrer('#resultat', 8)
            page.locator('#v-echeance_heure').fill('17')
            page.locator('#s-echeance_heure').select_option('-1')
            page.locator('#l-echeance_heure').fill('0')
            page.locator('#m-echeance_heure').fill('Hypothèse : fin autorisée à 17 h au lieu de 16 h, accord opérationnel à obtenir.')
            montrer('[data-cle="echeance_heure"]', 5)
            page.locator('#preparer').click()
            page.locator('#validation').wait_for(state='visible')
            page.locator('#accord').check()
            page.locator('#calculer').click()
            page.locator('#resultat').wait_for(state='visible')
            assert page.evaluate('dossier.resultat.retenu.capacite_utile_kwh') == 0
            montrer('#resultat', 9)
            rapport = page.locator('#rapport-lisible').get_attribute('href')
            page.goto(URL + rapport)
            assert 'aucun appel IA en direct' in page.locator('main').inner_text()
            page.wait_for_timeout(5000)
            assert not erreurs, erreurs
        finally:
            contexte.close()
            video.save_as(str(SORTIE / 'contingency-demo.webm'))
            navigateur.close()
    print('Vidéo enregistrée : ' + str(SORTIE / 'contingency-demo.webm'))


if __name__ == '__main__':
    main()
