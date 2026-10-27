import base64
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient
import serveur
import documents
import extraction_nebius
from moteur import dimensionner

class Parcours(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ancien = serveur.DOSSIERS
        serveur.DOSSIERS = Path(self.temp.name)
        self.client = TestClient(serveur.app)
        self.d = self.client.post('/api/exemple').json()
    def tearDown(self):
        serveur.DOSSIERS = self.ancien
        self.temp.cleanup()
    def preparer(self):
        r=self.client.post(f"/api/{self.d['id']}/preparer",json={'faits':self.d['faits']})
        self.assertEqual(r.status_code,200,r.text)
        self.d=r.json()
    def test_parcours_et_controle_lp(self):
        self.preparer()
        r=self.client.post(f"/api/{self.d['id']}/calculer",json={'revision':self.d['revision'],'validation':True})
        self.assertEqual(r.status_code,200,r.text)
        resultat=r.json()['resultat']
        self.assertEqual(resultat['preuve_solveur']['statut'],'optimal')
        charge=np.array(serveur.charger(self.d['id'])['profil'])
        debut=int(resultat['debuts_heures'][0]*4)
        charge[debut:debut+16]+=40
        lp=dimensionner(charge,150,rendement=.9,puissance_max=120,pas_heures=.25)
        self.assertEqual(lp['statut'],0)
        self.assertAlmostEqual(lp['capacite_utile_kwh'],resultat['retenu']['capacite_utile_kwh'],places=6)
        rapport=self.client.get(f"/api/{self.d['id']}/rapport")
        self.assertIn(self.d['revision'],rapport.text)
        self.assertIn('ligne 2',rapport.text)
        self.assertIn('fictif',rapport.text)
        self.assertIn('Résultat SHA-256',rapport.text)
        lignes=rapport.text.splitlines()
        position=lignes.index('| :--- | ---: | :--- |')
        self.assertTrue(lignes[position+1].startswith('| '))
        self.assertEqual(rapport.content,self.client.get(f"/api/{self.d['id']}/rapport").content)
    def test_rapport_bloque_resultat_altere_et_export_conserve_brut(self):
        self.preparer()
        self.client.post(f"/api/{self.d['id']}/calculer",json={'revision':self.d['revision'],'validation':True})
        dossier=serveur.charger(self.d['id'])
        dossier['resultat']['retenu']['capacite_utile_kwh']+=123
        serveur.sauver(dossier)
        rapport=self.client.get(f"/api/{self.d['id']}/rapport")
        self.assertIn('Conclusion suspendue',rapport.text)
        self.assertNotIn('Capacité utile minimale pour le planning retenu :',rapport.text)
        export=self.client.get(f"/api/{self.d['id']}/donnees").json()
        self.assertEqual(export['controle_rapport']['statut'],'bloque')
        self.assertEqual(export['resultat'],dossier['resultat'])

    def test_validation_et_revision(self):
        url=f"/api/{self.d['id']}/calculer"
        self.assertEqual(self.client.post(url,json={'validation':True}).status_code,422)
        self.preparer();ancienne=self.d['revision']
        self.assertEqual(self.client.post(url,json={'revision':ancienne,'validation':False}).status_code,422)
        self.d['faits']['puissance_kw']['valeur']=50
        self.d['faits']['puissance_kw']['motif']='Simulation de variante explicitement ajoutée'
        self.preparer()
        self.assertNotEqual(ancienne,self.d['revision'])
        self.assertEqual(self.client.post(url,json={'revision':ancienne,'validation':True}).status_code,422)
    def test_sources_et_hypotheses(self):
        self.d['faits']['plafond_kw']['valeur']=151
        self.assertEqual(self.client.post(f"/api/{self.d['id']}/preparer",json={'faits':self.d['faits']}).status_code,422)
        self.d['faits']['plafond_kw']['valeur']=150
        self.d['faits']['plafond_kw']['ligne']=900
        self.assertEqual(self.client.post(f"/api/{self.d['id']}/preparer",json={'faits':self.d['faits']}).status_code,422)
        self.d['faits']['plafond_kw'].update(document=-1,motif='')
        self.assertEqual(self.client.post(f"/api/{self.d['id']}/preparer",json={'faits':self.d['faits']}).status_code,422)
    def test_calendrier_et_unites(self):
        for t in ['fin_intervalle,puissance_kw\n2026-01-01T00:15:00,50\n','fin_intervalle,energie_kwh\n2026-01-01T00:15:00,50\n']:
            with self.assertRaises(ValueError):serveur.lire_profil(t)
        self.d['faits']['duree_heures']['valeur']=20
        self.assertEqual(self.client.post(f"/api/{self.d['id']}/preparer",json={'faits':self.d['faits']}).status_code,422)
    # Constat n°22 : il faut le PDF ET un Python documentaire où Docling s'importe, sinon le test échouait.
    @unittest.skipUnless((serveur.RACINE.parent/'evaluation-rag/sources/atlas.pdf').exists() and
                         subprocess.run([str(documents.PYTHON),'-c','import docling'],capture_output=True).returncode==0,
                         'PDF Atlas GA5-175 ou Docling absent (CONTINGENCY_PYTHON_DOCUMENTS) : voir « Vérifier localement » du README.')
    def test_import_pdf_et_conflit(self):
        from datetime import datetime,timedelta
        profil='fin_intervalle,puissance_kw\n'+''.join(f'{(datetime(2026,1,1)+timedelta(minutes=15*(i+1))).isoformat()}Z,60\n' for i in range(96))
        source=serveur.RACINE.parent/'evaluation-rag/sources/atlas.pdf'
        documents=[{'nom':'atlas.pdf','base64':base64.b64encode(source.read_bytes()).decode()}]
        r=self.client.post('/api/importer',json={'documents':documents,'profil':profil})
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn('GA5-175',r.json()['documents'][0]['texte'])
        lecture=r.json()['documents'][0]['lecture_structuree']
        self.assertEqual(lecture['statut'],'extrait_a_verifier')
        self.assertEqual(len(lecture['tableaux']),2)
        self.assertEqual(len(lecture['index_tableaux']['sources']),2)
        self.assertTrue(lecture['index_tableaux']['passages'])
        self.assertIn('181',lecture['controle']['nombres_non_retrouves_dans_structure'])
        self.assertIsNone(r.json()['faits']['puissance_kw']['valeur'])
        texte='plafond_kw = 150\nplafond_kw = 200\n'
        d=serveur.creer([{'nom':'conflit.txt','texte':texte,'sha256':'test'}],profil,'test')
        self.assertIsNone(d['faits']['plafond_kw']['valeur'])

    def test_import_accepte_un_dossier_de_neuf_pieces(self):
        from datetime import datetime,timedelta
        profil='fin_intervalle,puissance_kw\n'+''.join(f'{(datetime(2026,1,1)+timedelta(minutes=15*(i+1))).isoformat()}Z,60\n' for i in range(96))
        documents=[]
        for numero in range(9):
            contenu=f'Pièce {numero + 1}, document de test.\n'.encode()
            documents.append({'nom':f'piece-{numero + 1}.txt','base64':base64.b64encode(contenu).decode()})
        r=self.client.post('/api/importer',json={'documents':documents,'profil':profil})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(r.json()['documents']),9)
    def test_origine(self):
        self.assertEqual(self.client.post('/api/exemple',headers={'Origin':'https://externe.example'}).status_code,403)

    def test_extraction_nebius_reste_une_proposition(self):
        extraction={'version':extraction_nebius.VERSION,'modele':'modele-test','methode_recherche':'lexical','resume':'test',
                    'propositions':{},'alertes':[],'contextes':[],'journal_api':[],
                    'empreinte':extraction_nebius.empreinte_extraction(serveur.charger(self.d['id'])['documents'])}
        faits_avant=self.d['faits']
        with patch.object(serveur,'extraire_avec_nebius',return_value=extraction) as appel_ia:
            r=self.client.post(f"/api/{self.d['id']}/extraire")
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['faits'],faits_avant)
            self.assertEqual(r.json()['extraction_ia']['modele'],'modele-test')
            self.client.post(f"/api/{self.d['id']}/extraire")
            self.assertEqual(appel_ia.call_count,1)

    def test_citation_nebius_invalide_bloque_la_valeur(self):
        documents=[{'texte':'Le plafond contractuel est de 150 kW.\nLe rendement est de 90 %.'}]
        propositions=[]
        for champ in extraction_nebius.REQUETES:
            propositions.append({'champ':champ,'valeur':None,'source':'','citation':'',
                                 'confiance':'faible','alerte':'absent'})
        propositions[0].update(valeur=150,source='D1:L1',citation='150 kW',confiance='haute',alerte='')
        propositions[1].update(valeur=120,source='D1:L1',citation='120 kW',confiance='haute',alerte='')
        controles,alertes=extraction_nebius.controler_propositions(
            {'propositions':propositions,'alertes':[]},documents)
        self.assertEqual(controles['plafond_kw']['valeur'],150)
        self.assertIsNone(controles['puissance_max_kw']['valeur'])
        self.assertTrue(any('citation non retrouvée' in alerte for alerte in alertes))

    def test_rendement_aller_retour_ne_devient_pas_un_rendement_par_sens(self):
        documents=[{'texte':'Rendement heen en terug (round-trip) volgens leverancier: 88 %.'}]
        propositions=[]
        for champ in extraction_nebius.REQUETES:
            propositions.append({'champ':champ,'valeur':None,'source':'','citation':'',
                                 'confiance':'faible','alerte':'absent'})
        propositions[2].update(valeur=.88,source='D1:L1',citation='Rendement heen en terug (round-trip)',
                               confiance='haute',alerte='')
        controles,alertes=extraction_nebius.controler_propositions(
            {'propositions':propositions,'alertes':[]},documents)
        self.assertIsNone(controles['rendement']['valeur'])
        self.assertEqual(controles['rendement']['controle'],'rendement aller-retour bloqué')
        self.assertTrue(any('incompatible' in alerte for alerte in alertes))

class VerificationRapportLisible(unittest.TestCase):
    def test_texte_documentaire_ne_devient_pas_du_html(self):
        from rapport_html import rendre_rapport
        page = rendre_rapport('# Rapport\n## Preuve\n<script>alert(1)</script>\n| Nom | Source |\n| :--- | ---: |\n| Devis | <img src=x onerror=alert(1)> |', 'a' * 32)
        self.assertNotIn('<script>', page)
        self.assertNotIn('<img ', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', page)
        self.assertIn('<h2>Preuve</h2>', page)
        self.assertIn('<th>Source</th>', page)

if __name__=='__main__':unittest.main()
