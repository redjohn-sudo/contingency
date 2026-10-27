"""The English view must preserve limits and source text and fail closed."""
import copy
import unittest
from rapport_anglais import render, LABELS

class EnglishReport(unittest.TestCase):
    def setUp(self):
        self.d = {
            'id': 'a'*32, 'revision':'validated', 'profil_sha256':'profile',
            'documents':[{'nom':'source.txt','sha256':'source-hash'}],
            'faits':{k:{'valeur':1,'document':0,'ligne':1,'citation':'Original <script>alert(1)</script> & source','motif':'Reviewed'} for k in LABELS},
            'resultat':{'retenu':{'capacite_utile_kwh':45.84},'debuts_heures':[12],'moteur':'engine','preuve_solveur':{'statut':'optimal'}},
        }
        self.control={'statut':'optimal','anomalies':[],'audit_documentaire':{'anomalies':[{'id':'reserve','code':'reserve_prioritaire','preuves':[]}]}}
    def test_source_text_escaped_and_data_unchanged(self):
        original=copy.deepcopy(self.d)
        html=render(self.d,self.control,'result-hash')
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
        self.assertEqual(self.d,original)
    def test_suspended_result_does_not_display_capacity(self):
        self.control['statut']='bloque'
        html=render(self.d,self.control,'result-hash')
        self.assertIn('Result suspended',html)
        self.assertNotIn('45.84 kWh',html)
    def test_backup_limit_and_traceability_remain_visible(self):
        html=render(self.d,self.control,'result-hash')
        self.assertIn('45.84 kWh',html)
        self.assertIn('Zero capacity for peak smoothing does not mean the site needs no battery',html)
        self.assertIn('REVIEW MISSING',html)
        self.assertIn('result-hash',html)
        self.assertIn('<html lang="en">',html)

if __name__=='__main__':unittest.main()
