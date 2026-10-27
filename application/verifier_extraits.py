import json
import unittest
from pathlib import Path
from extraits_tableaux import construire, contexte_passage

class Extraits(unittest.TestCase):
    def test_cellule_fusionnee_et_note_liee_autre_page(self):
        def cellule(texte, ligne, colonne, fin, entete=False):
            return dict(text=texte, start_row_offset_idx=ligne, end_row_offset_idx=fin,
                        start_col_offset_idx=colonne, end_col_offset_idx=colonne+1, column_header=entete)
        table=dict(self_ref='#/tables/0', prov=[dict(page_no=1)], captions=[],
                   footnotes=[{'$ref':'#/texts/0'}], data=dict(num_rows=3, table_cells=[
                    cellule('Modèle',0,0,1,True), cellule('Puissance (kW)',0,1,1,True),
                    cellule('Machine A',1,0,3), cellule('7.5',1,1,2), cellule('8.2',2,1,3)]))
        texte=dict(self_ref='#/texts/0',text='Valeurs à pleine charge seulement.',prov=[dict(page_no=2)])
        index=construire(dict(sha256='abc',structure=dict(tables=[table],texts=[texte])))
        c=contexte_passage(index,index['passages'][2]['id'])
        self.assertIn('Machine A | 8.2',c['passage']['texte'])
        self.assertIn('Puissance (kW)',c['passage']['texte'])
        self.assertEqual(c['source']['contexte'][0]['relation'],'lien_docling')
        self.assertIn('pleine charge',c['texte'])
        with self.assertRaises(ValueError):contexte_passage(index,'inconnu')

    def test_atlas_reel_unite_modele_reserves_et_chiffre_non_corrige(self):
        chemin=Path(__file__).resolve().parent.parent/'evaluation-rag/.docling/atlas.json'
        if not chemin.exists():self.skipTest('Cache du PDF public absent')
        index=construire(json.loads(chemin.read_text()))
        p=next(p for p in index['passages'] if 'Total Package Input Power' in p['texte'])
        c=contexte_passage(index,p['id'])
        self.assertIn('7.3',p['texte']);self.assertIn('kW',p['texte'])
        self.assertIn('GA5-175',c['texte']);self.assertIn('Preliminary',c['texte'])
        self.assertIn('1 81',c['texte'])
        self.assertTrue(c['source']['contexte'])
        self.assertEqual(c['source']['statut'],'association_a_verifier')
        self.assertTrue(c['source']['cellules'][0]['bbox'])

if __name__=='__main__':unittest.main()
