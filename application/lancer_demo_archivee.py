"""Démonstration locale archivée, ou analyse directe avec l'option --live.

Le repli ouvre une étude archivée distincte, sans remplacer les pièces de l'étude
initiale. Aucun appel de modèle en mode archivé. Études locales persistantes.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
import serveur
import extraction_nebius
import protocole_structure

RACINE = Path(__file__).resolve().parent.parent
ARCHIVE = RACINE / 'audit-structure-20260924/essai-reel.json'


def documents_archives():
    repertoire = RACINE / 'evaluation-dossier-long/v2'
    manifeste = json.loads((repertoire / 'manifeste.json').read_text())
    if not all((repertoire / 'texte' / (entree['id'] + '.txt')).exists() for entree in manifeste):
        # Les extractions tierces séparées restent hors de Git. Le rapport audité
        # conserve déjà les neuf textes utilisés pour cette réponse enregistrée.
        archive = RACINE / 'audit-demo-20260922/scenario/donnees-initiales.json'
        documents = copy.deepcopy(json.loads(archive.read_text())['documents'])
        if len(documents) != len(manifeste):
            raise ValueError('Archive de démonstration incomplète.')
        for entree, document in zip(manifeste, documents):
            if document['nom'] != entree['fichier'] or hashlib.sha256(document['texte'].encode()).hexdigest() != document['sha256']:
                raise ValueError('Texte ou identité documentaire différents de l’archive.')
        return documents
    documents = []
    for entree in manifeste:
        lignes, pages = [], {}
        for ligne in (repertoire / 'texte' / (entree['id'] + '.txt')).read_text().splitlines():
            repere = re.fullmatch(r'D\d+:P(\d+):L\d+\s*(?:\|\s*)?(.*)', ligne)
            if not repere:
                raise ValueError('Texte archivé sans référence valide.')
            lignes.append(repere[2])
            pages.setdefault(int(repere[1]), []).append({'debut': len(lignes), 'fin': len(lignes)})
        texte = '\n'.join(lignes)
        documents.append({'nom': entree['fichier'], 'texte': texte,
                          'sha256': hashlib.sha256(texte.encode()).hexdigest(),
                          'lecture_ocr': {'pages': [{'page': page, 'plages_lignes': plages}
                                                    for page, plages in pages.items()]}})
    return documents


def interdire_appel(*arguments, **options):
    raise HTTPException(503, 'Mode démonstration archivée : aucun nouvel appel IA autorisé.')


def configurer(repertoire, live=False):
    serveur.DOSSIERS = Path(repertoire)
    serveur.extraire_avec_nebius = extraction_nebius.extraire if live else interdire_appel
    serveur.app.state.live_ai = live
    archive = json.loads(ARCHIVE.read_text())
    documents = documents_archives()
    # Archive du 24/09 produite avec la formule d'empreinte actuelle : on la recalcule
    # avec la configuration enregistrée, pas celle de l'environnement du moment.
    configuration_courante = extraction_nebius.configuration
    extraction_nebius.configuration = lambda: archive['extraction']['configuration']
    try:
        empreinte_historique = extraction_nebius.empreinte_extraction(documents)
    finally:
        extraction_nebius.configuration = configuration_courante
    if not live and empreinte_historique != archive['extraction']['empreinte']:
        raise ValueError('Le corpus ou la configuration diffère de la réponse archivée. Rejeu refusé.')
    for anomalie in archive['extraction']['audit_documentaire']['anomalies']:
        for preuve in anomalie['preuves']:
            document = documents[preuve['document']]
            if document['nom'] != preuve['nom'] or document['sha256'] != preuve['sha256']:
                raise ValueError('Métadonnées des preuves différentes de l’archive.')

    def creer_demo(analyse_directe):
        if not analyse_directe and empreinte_historique != archive['extraction']['empreinte']:
            raise HTTPException(503, 'Les documents de démonstration ne correspondent plus à la réponse enregistrée.')
        debut = datetime(2026, 1, 5, tzinfo=timezone.utc)
        profil = 'fin_intervalle,puissance_kw\n' + ''.join(
            f'{(debut + timedelta(minutes=15*(i+1))).isoformat()},{620 if 36 <= i < 52 else 480}\n'
            for i in range(96))
        public = serveur.creer(copy.deepcopy(documents), profil,
            'DÉMONSTRATION : vraie réponse DeepSeek enregistrée le 24 septembre, aucun appel IA en direct. '
            'Textes archivés de quatre PDF publics et cinq pièces fictives ; profil fictif. '
            'Les hypothèses de démonstration ne constituent pas une validation métier.')
        dossier = serveur.charger(public['id'])
        dossier['extraction_ia'] = copy.deepcopy(archive['extraction'])
        dossier['extraction_ia']['resume'] = ('REJEU DE RÉPONSE ENREGISTRÉE, PAS UN APPEL EN DIRECT. '
                                            + dossier['extraction_ia']['resume'])
        dossier['extraction_ia']['execution'] = 'recorded'
        if analyse_directe:
            grid = archive['extraction']['propositions']['plafond_kw']
            dossier['faits']['plafond_kw'] = {k: grid[k] for k in ('valeur', 'document', 'ligne')}
            dossier['faits']['plafond_kw']['motif'] = ''
            dossier['extraction_ia'] = None
            dossier['nature'] = 'Sample factory: public and constructed documents; simulated demand. Document analysis uses live Nebius inference.'
        else:
            dossier['mode_extraction'] = 'demo_archivee'
            dossier['empreinte_documents_demo'] = serveur.empreinte(dossier['documents'])
        serveur.sauver(dossier)
        return serveur.public(dossier)

    @serveur.app.post('/api/demo/archive')
    def ouvrir_archive():
        return creer_demo(live)

    @serveur.app.post('/api/{identifiant}/demo-repli')
    def ouvrir_repli(identifiant: str):
        # Charger aussi l'étude source : le service public y contrôle la session.
        # Ne jamais lui appliquer la réponse enregistrée d'un autre corpus.
        serveur.charger(identifiant)
        public = creer_demo(False)
        dossier = serveur.charger(public['id'])
        dossier['repli_de'] = identifiant
        dossier['origine_demo'] = dossier['id']
        serveur.sauver(dossier)
        return serveur.public(dossier)

    @serveur.app.get('/demo')
    def page_demo():
        page = (serveur.RACINE / 'index.html').read_text()
        notice = ('<p id="mode-demo" style="border-bottom:2px solid #356355;padding-bottom:1rem">'
                  '<strong>Contingency, démonstration hors ligne.</strong> Réponse DeepSeek réelle enregistrée le '
                  '24 septembre. Aucun appel IA en direct. Dossier construit et profil fictif. '
                  'Validation et calcul exécutés localement.</p>')
        page = page.replace('<main>', '<main>' + notice, 1)
        script = '''<script>
        document.querySelector('h1').textContent='Contingency : vérifier les contraintes avant de calculer.';
        $('exemple').textContent='Ouvrir le dossier de démonstration';
        $('exemple').onclick=()=>action(async()=>afficher(await appel('/api/demo/archive')));
        $('extraire').textContent='Revoir la réponse DeepSeek enregistrée';
        $('extraire').onclick=()=>afficherPropositions();
        $('extraire').nextElementSibling.textContent='Réponse déjà enregistrée. Aucun envoi externe dans ce mode.';
        $('importer').disabled=true;
        $('documents').disabled=true;
        $('profil').disabled=true;
        const ouverture=$('exemple').closest('section');
        ouverture.querySelector('h2').textContent='1. Ouvrir le dossier de démonstration';
        ouverture.querySelector('p').textContent='Neuf pièces : textes archivés de quatre PDF publics et cinq pièces de site fictives. Le profil de consommation est simulé.';
        ouverture.querySelector('.grille').hidden=true;
        $('importer').hidden=true;
        ouverture.querySelector('small').textContent='La réponse DeepSeek est enregistrée. Les calculs seront exécutés sur cette machine.';
        const aide=document.createElement('div');
        aide.innerHTML='<button id="hypotheses-demo" class="secondaire">Préremplir les hypothèses de démonstration</button><small>Trois valeurs de simulation et les motifs de revue sont préparés. Aucune proposition ni alerte n’est validée par ce bouton.</small>';
        $('faits').before(aide);
        $('hypotheses-demo').onclick=()=>{
          if(!dossier) return;
          let filled=0;
          for(let [champ,valeur,motif] of [
            ['puissance_max_kw',100,'Demonstration assumption: battery limited to 100 kW; mandatory backup reserve is not modelled.'],
            ['puissance_kw',73,'Demonstration assumption: ten compressors at 7.3 kW; applicability of the datasheet to the site is not validated.'],
            ['rendement',Math.sqrt(.88),'Demonstration assumption: symmetric losses; per-direction efficiency equals the square root of 0.88.']]){
            if($('v-'+champ).value!=='')continue;
            if(champ==='puissance_kw' && window.factory?.machine){
              valeur=window.factory.machine.power;
              motif='User-entered machine scenario; power has not been verified against the documents.';
            }
            filled++;
            $('v-'+champ).value=valeur;
            $('s-'+champ).value='-1';
            $('l-'+champ).value='0';
            $('m-'+champ).value=motif;
            $('v-'+champ).closest('.fait').dispatchEvent(new Event('input',{bubbles:true}));
          }
          const status=$('message');status.className='';
          status.textContent=filled?`${filled} missing ${filled===1?'value filled':'values filled'}. Review before continuing.`:'No missing demo values to fill.';
          status.setAttribute('role','status');
          invalider();
          window.parcours?.sync();
        };
        </script>'''
        # Le document source omet volontairement la balise body, permise en HTML.
        # Ajouter le script avant la fermeture html réellement présente.
        if '</html>' not in page:
            raise ValueError('Page de démonstration incomplète.')
        if live:
            page = page.replace('<head>', '<head><script>window.CONTINGENCY_LIVE_AI=true;</script>', 1)
            script += '''<script>
            $('extraire').onclick=()=>action(async()=>{dossier=await appel(`/api/${dossier.id}/extraire`);afficher(dossier)});
            $('extraire').textContent='Analyze documents';
            $('extraire').nextElementSibling.textContent='';
            </script>'''
        return HTMLResponse(page.replace('</html>', script + '</html>'))


if __name__ == '__main__':
    import uvicorn
    import argparse
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=RACINE / '.local/demo-state', help='Directory for persistent local demo studies.')
    parser.add_argument('--live', action='store_true', help='Analyze documents through Nebius instead of replaying archived responses.')
    parser.add_argument('--model', help='Nebius model ID for live analysis.')
    args = parser.parse_args()
    if args.model:
        if not args.live:
            parser.error('--model requires --live')
        os.environ['NEBIUS_CHAT_MODEL'] = args.model
    args.data_dir.mkdir(parents=True, exist_ok=True)
    configurer(args.data_dir, live=args.live)
    uvicorn.run(serveur.app, host='127.0.0.1', port=8766)
