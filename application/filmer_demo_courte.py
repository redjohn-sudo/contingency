"""Capture automatisée de l'application réelle, extraction archivée, calculs locaux."""
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import lancer_demo_archivee as demo
import serveur

SORTIE = Path(__file__).resolve().parent.parent / 'audit-revue-20260922'
URL = 'http://127.0.0.1:8766'


def main():
    SORTIE.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporaire:
        demo.configurer(temporaire)
        with TestClient(serveur.app) as client, sync_playwright() as outil:
            navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
            try:
                contexte = navigateur.new_context(viewport={'width': 1440, 'height': 1000},
                    reduced_motion='reduce', record_video_dir=str(SORTIE/'video-brute'),
                    record_video_size={'width': 1440, 'height': 1000})

                def servir(route):
                    requete = route.request
                    if not requete.url.startswith(URL+'/'):
                        raise AssertionError('Requête externe interdite dans cette capture.')
                    adresse = urlsplit(requete.url)
                    reponse = client.request(requete.method, adresse.path+('?' + adresse.query if adresse.query else ''),
                        content=requete.post_data_buffer,
                        headers={'content-type': requete.headers.get('content-type', 'application/json')})
                    route.fulfill(status=reponse.status_code, body=reponse.content,
                                  headers={k: v for k, v in reponse.headers.items()
                                           if k.lower() not in {'content-length', 'content-encoding', 'transfer-encoding'}})

                contexte.route('**/*', servir)
                page = contexte.new_page()
                erreurs=[]
                page.on('pageerror',lambda erreur:erreurs.append(str(erreur)))
                page.goto(URL+'/demo?lang=en')
                page.add_style_tag(content='''
                  html{scroll-behavior:auto!important}body{padding-bottom:100px}
                  #legende-capture{position:fixed;bottom:0;left:0;right:0;z-index:99;background:#fff;border-top:2px solid #2c6252;padding:14px 32px;color:#1f2926;font:17px/1.4 system-ui}
                  #legende-capture strong{font-size:24px;display:block}#legende-capture small{font-size:14px}
                ''')
                page.evaluate('''()=>{const e=document.createElement('div');e.id='legende-capture';e.innerHTML='<strong></strong><small>Recorded Kimi extraction | Constructed scenario | Automated, time-compressed walkthrough</small>';document.body.append(e)}''')

                def plan(texte, selecteur, pause):
                    page.locator('#legende-capture strong').evaluate('(e,t)=>e.textContent=t', texte)
                    page.locator(selecteur).first.evaluate("e=>window.scrollTo({top:e.getBoundingClientRect().top+scrollY-32,behavior:'instant'})")
                    page.wait_for_timeout(pause)

                page.locator('#exemple').click()
                page.locator('.proposition').first.wait_for()
                page.locator('[data-proposition="plafond_kw"] details summary').click()
                plan('1. Proposed values, with their sources', '#propositions-ia', 3500)
                for champ in ('plafond_kw','duree_heures','ouverture_heure','echeance_heure'):
                    page.locator(f'[data-proposition="{champ}"] .accepter-ia').check()
                page.locator('#hypotheses-demo').click()
                plan('2. Conflicting quote: explicit review required', '#audit-documentaire', 3000)
                assert page.locator('.accord-alerte:checked').count()==0
                for case in page.locator('.accord-alerte').all():
                    case.check()
                page.locator('#preparer').click()
                page.locator('#validation').wait_for(state='visible')
                page.locator('#accord').check()
                page.locator('#calculer').click()
                page.locator('#resultat').wait_for(state='visible')
                page.wait_for_function("document.getElementById('chiffres').textContent.includes('45.84 kWh')")
                plan('3. First validated simulation', '#resultat', 2500)
                page.locator('[data-cle="echeance_heure"] .edition-fait summary').click()
                page.locator('#v-echeance_heure').fill('17')
                page.locator('#s-echeance_heure').select_option('-1')
                page.locator('#l-echeance_heure').fill('0')
                page.locator('#m-echeance_heure').fill('Hypothèse : fin à 17 h au lieu de 16 h ; accord opérationnel à obtenir.')
                plan('4. Change the end time, then validate again', '[data-cle="echeance_heure"]', 2500)
                page.locator('#preparer').click()
                page.locator('#validation').wait_for(state='visible')
                assert page.locator('#calculer').is_disabled()
                page.locator('#accord').check()
                page.locator('#calculer').click()
                page.locator('#comparaison-variantes').wait_for(state='visible')
                assert abs(page.evaluate('dossier.resultat.retenu.capacite_utile_kwh'))<1e-6
                page.wait_for_function("document.getElementById('comparaison-variantes').textContent.includes('45.84')")
                plan('5. Same machine. Peak-smoothing need: 45.84 to 0 kWh', '#resultat', 5000)
                page.screenshot(path=str(SORTIE/'moment-fort.png'))
                assert not erreurs,erreurs
                brut=Path(page.video.path())
                contexte.close()
            finally:
                navigateur.close()
    duree=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration',
                                         '-of','default=noprint_wrappers=1:nokey=1',str(brut)]))
    cible=SORTIE/'contingency-demo-courte.webm'
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(brut),
                    '-vf',f'setpts={20/duree:.8f}*PTS','-r','30','-an','-c:v','libvpx-vp9','-cpu-used','4',
                    '-crf','30','-b:v','0','-pix_fmt','yuv420p',str(cible)],check=True)
    finale=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration',
                                          '-of','default=noprint_wrappers=1:nokey=1',str(cible)]))
    resultat={'nature':'Capture automatisée, temps compressé, vraie extraction Kimi archivée, calculs locaux.',
              'nouvel_appel_ia':False,'secondes_brutes':duree,'secondes_video':finale,
              'fichier':cible.name,'octets':cible.stat().st_size,'valeur_initiale':45.84,'valeur_variante':0,
              'portee':'Besoin de lissage seulement ; réserve hors modèle ; hypothèses validées par le banc de capture.'}
    (SORTIE/'video.json').write_text(json.dumps(resultat,ensure_ascii=False,indent=2))
    print(json.dumps(resultat,ensure_ascii=False))


if __name__=='__main__':
    main()
