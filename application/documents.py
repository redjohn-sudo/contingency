"""Deux lectures complémentaires d'un PDF, sans correction silencieuse des nombres."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from extraits_tableaux import construire

RACINE=Path(__file__).resolve().parent.parent
PYTHON=Path(os.environ.get('CONTINGENCY_PYTHON_DOCUMENTS', sys.executable))
SCRIPT=RACINE/'evaluation-rag/extraire_docling.py'
CACHE=RACINE/'evaluation-rag/.docling'
SCRIPT_OCR=RACINE/'application/ocr_local.py'
SOURCES=RACINE/'application/.local/sources'
LIMITE_PDF=5*1024*1024
DELAI_LECTURE_PDF=100


def lire_pdf(donnees, stockage=None):
    """Lecture locale complète ou erreur explicite, avec sources conservées.

    Le serveur peut ajouter directement ce dictionnaire au document importé.
    Les chemins de source sont relatifs à application/.local, jamais des URL.
    """
    if len(donnees) > LIMITE_PDF:
        raise ValueError('Limite de 5 Mio par document PDF.')
    if not donnees.startswith(b'%PDF-'):
        raise ValueError('PDF illisible : en-tête absent.')
    if not PYTHON.exists():
        raise ValueError('Lecteur PDF local indisponible : environnement Python documentaire absent.')
    empreinte=hashlib.sha256(donnees).hexdigest()
    racine_sources=Path(stockage)/'sources' if stockage is not None else SOURCES
    with tempfile.TemporaryDirectory() as travail:
        repertoire=Path(travail)/'sources'/empreinte
        repertoire.mkdir(parents=True)
        pdf=repertoire/'source.pdf'
        pdf.write_bytes(donnees)
        sortie=Path(travail)/'lecture.json'
        env=os.environ.copy()
        env.update({'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1',
                    'OMP_NUM_THREADS':'2','OMP_THREAD_LIMIT':'2'})
        donnees_ocr=RACINE/'.local/tessdata'
        if all((donnees_ocr/(langue+'.traineddata')).exists() for langue in ('fra','eng','nld')):
            env.setdefault('TESSDATA_PREFIX', str(donnees_ocr))
        try:
            processus=subprocess.Popen([str(PYTHON),str(SCRIPT_OCR),str(pdf),str(sortie)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,start_new_session=True)
            try:
                _,erreur=processus.communicate(timeout=DELAI_LECTURE_PDF)
            except subprocess.TimeoutExpired as cause:
                # Tesseract appartient au même groupe, aucun enfant ne doit continuer.
                try:
                    os.killpg(processus.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                processus.communicate()
                raise ValueError('Lecture PDF interrompue : limite de 100 secondes. Import incomplet refusé.') from cause
            if processus.returncode:
                message=erreur.decode('utf-8',errors='replace').strip()
                raise ValueError(message if message.startswith('Lecture PDF : ') else
                                 'Lecture PDF impossible. Import incomplet refusé.')
            resultat=json.loads(sortie.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError) as cause:
            raise ValueError('Lecture PDF locale indisponible. Import incomplet refusé.') from cause
        if resultat.get('source_pdf',{}).get('sha256')!=empreinte:
            raise ValueError('Empreinte de la source PDF incohérente.')
        conserver_sources(Path(travail)/'sources', racine_sources)
    return resultat


def conserver_sources(source, destination):
    """Conserve uniquement les sources d'une lecture ou d'un import accepté."""
    source, destination = Path(source), Path(destination)
    if not source.exists():
        return
    for fichier in source.rglob('*'):
        if not fichier.is_file():
            continue
        cible = destination / fichier.relative_to(source)
        cible.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cible.parent, delete=False) as temporaire:
            chemin = Path(temporaire.name)
            try:
                with fichier.open('rb') as entree:
                    shutil.copyfileobj(entree, temporaire)
                temporaire.flush()
                chemin.replace(cible)
            finally:
                chemin.unlink(missing_ok=True)

def comparer(brut,structure):
    nombres=lambda t:set(re.findall(r'(?<![\w.])\d+(?:\.\d+)?(?![\w.])',t))
    manquants=sorted(nombres(brut)-nombres(structure))
    return {'nombres_non_retrouves_dans_structure':manquants,
            'message':('Certains nombres du texte ne sont pas retrouvés tels quels dans la lecture structurée. Vérifier le PDF.' if manquants else 'Aucune différence détectée par ce contrôle de présence numérique. Cela ne valide pas les associations de cellules.')}

def completer(donnees,texte,cache=None):
    if not PYTHON.exists():return {'statut':'indisponible','message':'Lecture structurée non installée.'}
    source=hashlib.sha256(donnees).hexdigest()
    cle=hashlib.sha256((source+hashlib.sha256(SCRIPT.read_bytes()).hexdigest()+'docling-2.127.0').encode()).hexdigest()
    cache = CACHE if cache is None else Path(cache)
    cache.mkdir(parents=True,exist_ok=True)
    cible=cache/(cle+'.json')
    try:
        if cible.exists():resultat=json.loads(cible.read_text())
        else:
            with tempfile.TemporaryDirectory() as repertoire:
                pdf=Path(repertoire)/'source.pdf';pdf.write_bytes(donnees)
                sortie=Path(repertoire)/'extraction.json'
                env=os.environ.copy();env['HF_HUB_OFFLINE']='1'
                subprocess.run([str(PYTHON),str(SCRIPT),str(pdf),str(sortie)],capture_output=True,check=True,timeout=160,env=env)
                resultat=json.loads(sortie.read_text())
                cible.write_text(json.dumps(resultat,ensure_ascii=False))
        if resultat['sha256']!=source:raise ValueError('Empreinte de cache incohérente')
        tableaux=[]
        for t in resultat['structure']['tables']:
            tableaux.append({'page':t['prov'][0]['page_no'],'lignes':t['data']['num_rows'],
                'colonnes':t['data']['num_cols'],'cellules':t['data']['table_cells']})
        return {'statut':'extrait_a_verifier','version':resultat['version'],'tableaux':tableaux,
                'index_tableaux':construire(resultat),
                'texte':resultat['texte'],'controle':comparer(texte,resultat['texte']),
                'message':'Tableaux reconstitués automatiquement. Le texte original est conservé comme lecture complémentaire.'}
    except (subprocess.SubprocessError,ValueError,KeyError,OSError):
        return {'statut':'echec','message':'La lecture structurée n’a pas abouti. Le texte brut reste disponible et doit être vérifié.'}
