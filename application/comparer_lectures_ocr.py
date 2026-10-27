"""Comparer les réglages Tesseract sans changer ceux de l’application."""
import argparse,json,os,subprocess,time
from pathlib import Path
from evaluer_scans_degrades import mesurer
from ocr_local import lire_mots

def main():
    parser=argparse.ArgumentParser(description='Comparer trois réglages OCR sur les images déjà rendues du banc.')
    parser.add_argument('racine',type=Path)
    racine=parser.parse_args().racine
    resultats=[]
    environnement=os.environ.copy();environnement['OMP_THREAD_LIMIT']='2'
    for methode,psm,seuil in [('bloc_sauvola','3','2'),('epars_otsu','11','0'),('epars_sauvola','11','2')]:
     for cas in json.loads((racine/'resultats.json').read_text()):
      variante=cas['variante']; base=racine/variante
      initial=json.loads((base/'lecture.json').read_text());pages=[];textes=[]
      sortie=racine/'comparaisons'/methode/variante;sortie.mkdir(parents=True,exist_ok=True)
      debut=time.monotonic()
      for page in initial['lecture_ocr']['pages']:
       fichier=sortie/f"page-{page['page']}"
       subprocess.run(['tesseract',str(base/page['image_source']),str(fichier),'-l','fra+eng+nld','--psm',psm,'--dpi','300','-c','thresholding_method='+seuil,'txt','tsv'],env=environnement,capture_output=True,check=True,timeout=15)
       texte=fichier.with_suffix('.txt').read_text();textes.append(texte)
       pages.append({'mots_ocr':lire_mots(fichier.with_suffix('.tsv')),'a_verifier':True})
      lecture={'texte':'\n'.join(textes),'lecture_ocr':{'pages':pages,'avertissements':[]}}
      score=mesurer(lecture);score.update({'methode':methode,'variante':variante,'secondes':round(time.monotonic()-debut,3)})
      resultats.append(score)
      (racine/'comparaison-methodes.json').write_text(json.dumps(resultats,ensure_ascii=False,indent=2))
      print(json.dumps({k:score[k] for k in ['methode','variante','exacts','absents_ou_bloques','divergents','secondes']}),flush=True)

if __name__ == "__main__":
    main()
