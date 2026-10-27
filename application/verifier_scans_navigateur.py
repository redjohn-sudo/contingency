"""Import OCR réel et ouverture de la preuve PDF, fournisseur simulé, navigateur isolé."""
import argparse
import base64
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import controle_documentaire as controle
import extraction_nebius as extraction
import protocole_structure
import serveur

URL = 'http://127.0.0.1:8766'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dossier', type=Path)
    parser.add_argument('--sortie', type=Path, required=True)
    args = parser.parse_args()
    args.sortie.mkdir(parents=True, exist_ok=True)
    pdf = args.dossier.read_bytes()
    profil = 'fin_intervalle,puissance_kw\n' + ''.join(
        f'{(datetime(2026,1,1)+timedelta(minutes=15*(i+1))).isoformat()}Z,200\n' for i in range(96))
    with tempfile.TemporaryDirectory() as temporaire, patch.object(serveur, 'DOSSIERS', Path(temporaire)), \
            patch.object(serveur, 'completer', return_value={'statut': 'non_teste', 'message': 'Lecture Docling non exécutée dans ce test OCR.'}), \
            TestClient(serveur.app) as client:
        requete = client.post('/api/importer', json={'documents': [{'nom': 'atelier-lierre.pdf', 'base64': base64.b64encode(pdf).decode()}], 'profil': profil})
        requete.raise_for_status()
        dossier = requete.json()
        identifiant = dossier['id']
        doc = dossier['documents'][0]
        assert len(doc['lecture_ocr']['pages']) == 3
        index = protocole_structure.indexer_lignes([doc])
        repere, entree = next((r,e) for r,e in index.items() if controle.valeurs_ligne('plafond_kw', e['texte']) == [275.5])
        reponse = {'resume':'Réponse simulée, preuve OCR réelle.', 'champs':{c:None for c in extraction.REQUETES},
                   'preuves':{c:[] for c in extraction.REQUETES}, 'alertes':[], 'decision':'demander_information'}
        reponse['champs']['plafond_kw'] = 275.5
        reponse['preuves']['plafond_kw'] = [{'repere':repere,'citation':entree['texte']}]
        # La puissance absente du scan flou ne doit pas être « complétée » par le modèle.
        assert not any(controle.valeurs_ligne('puissance_kw', e['texte']) for e in index.values())
        repere_duree, ligne_duree = next((r,e) for r,e in index.items() if controle.valeurs_ligne('duree_heures', e['texte']) == [3.25])
        reponse['champs']['puissance_kw'] = 62.8
        reponse['preuves']['puissance_kw'] = [{'repere':repere_duree,'citation':ligne_duree['texte']}]
        brut = {'model':extraction.MODELE_DEFAUT,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(reponse)}}],'usage':{'total_tokens':0}}
        with patch.object(extraction,'charger_cle',return_value='factice'), patch.object(extraction,'appeler',return_value=(brut,0)):
            extrait=extraction.extraire([doc])
        assert extrait['propositions']['plafond_kw']['valeur'] == 275.5
        assert extrait['propositions']['puissance_kw']['valeur'] is None
        stocke=serveur.charger(identifiant)
        stocke['extraction_ia']=extrait
        serveur.sauver(stocke)
        dossier=serveur.public(stocke)
        assert client.get(f'/api/{identifiant}/source/0').content == pdf
        assert client.post(f'/api/{identifiant}/calculer',json={'validation':True,'revision':None}).status_code == 422
        assert client.post(f'/api/{identifiant}/preparer',json={'faits':dossier['faits'],'revue_documentaire':{}}).status_code == 422
        erreurs=[]
        with sync_playwright() as outil:
            navigateur=outil.chromium.launch(executable_path='/usr/bin/brave-browser',headless=True)
            try:
                contexte=navigateur.new_context(viewport={'width':1400,'height':1000})
                def servir(route):
                    r=route.request
                    assert r.url.startswith(URL+'/'),r.url
                    adresse=urlsplit(r.url)
                    reponse=client.request(r.method,adresse.path+('?' + adresse.query if adresse.query else ''),content=r.post_data_buffer,
                        headers={'content-type':r.headers.get('content-type','application/json')})
                    route.fulfill(status=reponse.status_code,body=reponse.content,
                        headers={k:v for k,v in reponse.headers.items() if k.lower() not in {'content-length','content-encoding','transfer-encoding'}})
                contexte.route('**/*',servir)
                p=contexte.new_page()
                p.on('pageerror',lambda e:erreurs.append(str(e)))
                for langue in ['fr','en']:
                    p.goto(URL+'/?lang='+langue)
                    p.evaluate('d=>afficher(d)',dossier)
                    p.locator('[data-proposition="plafond_kw"]').wait_for()
                    preuve=p.locator('[data-proposition="plafond_kw"] .source-originale')
                    assert preuve.get_attribute('href')==f'/api/{identifiant}/source/0#page=1'
                    assert preuve.is_visible()
                    assert p.locator('.accepter-ia:checked').count()==0
                    assert p.locator('[data-proposition="puissance_kw"] .accepter-ia').is_disabled()
                    assert p.locator('[data-proposition="plafond_kw"] .alerte-ia').is_visible()
                    p.locator('#sources').evaluate("e=>{for(let n=e.parentElement;n;n=n.parentElement)if(n.tagName==='DETAILS')n.open=true;e.querySelector('details').open=true}")
                    assert p.locator('#sources .source-originale').is_visible()
                    assert p.locator('#sources a').count() == 1
                    attendu='Entire lines can be missing' if langue=='en' else 'Des lignes entières peuvent manquer'
                    p.wait_for_function('(s)=>document.getElementById("sources").innerText.includes(s)',arg=attendu)
                    # Le lien vise le PDF authentique, pas une reconstruction du texte OCR.
                    octets=p.evaluate('async u=>Array.from(new Uint8Array(await (await fetch(u)).arrayBuffer()))',preuve.get_attribute('href'))
                    assert bytes(octets)==pdf
                    for largeur in [600,2000]:
                        p.set_viewport_size({'width':largeur,'height':1100})
                        p.locator('#sources').scroll_into_view_if_needed()
                        assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        p.screenshot(path=str(args.sortie/f'preuve-{langue}-{largeur}.png'))
                assert not erreurs,erreurs
            finally:
                navigateur.close()
        resultat={'import_pdf_reel':True,'pages':3,'pdf_sha256':hashlib.sha256(pdf).hexdigest(),
                  'fournisseur_simule':True,'nouvel_appel_ia':False,'lien_pdf_original':True,'octets_source_conserves':True,
                  'revue_non_prevalidee':True,'parametres_manquants_bloquent':True,'langues':['fr','en'],
                  'valeur_absente_non_justifiee_par_citation_voisine':True,
                  'largeurs':[600,2000],'erreurs_js':erreurs}
        (args.sortie/'verification.json').write_text(json.dumps(resultat,ensure_ascii=False,indent=2))
        print(json.dumps(resultat,ensure_ascii=False))


if __name__=='__main__':
    main()
