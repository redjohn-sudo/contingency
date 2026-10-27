import copy
import unittest
from unittest.mock import patch
import coherence

class Coherence(unittest.TestCase):
    def setUp(self):
        valeurs=dict(plafond_kw=70,puissance_max_kw=100,rendement=.9,puissance_kw=10,
                     duree_heures=1,ouverture_heure=8,echeance_heure=10)
        self.d=dict(revision='r',profil=[60]*96,faits={k:dict(valeur=v) for k,v in valeurs.items()},
                    resultat=dict(revision='r',debuts_heures=[8],retenu=dict(statut=0,capacite_utile_kwh=0),
                                  methode='Texte non vérifié : optimum mondial',preuve_solveur=dict(statut='inconnu')))
    def controle(self):return coherence.controler(self.d,'r')
    def test_faisable_sans_optimum(self):
        c=self.controle();self.assertEqual(c['statut'],'realisable')
        self.assertNotIn('mondial',c['conclusion'])
    def test_revision_perimee(self):
        self.d['resultat']['revision']='ancienne';self.assertEqual(self.controle()['statut'],'bloque')
    def test_capacite_alteree(self):
        self.d['resultat']['retenu']['capacite_utile_kwh']=12
        self.assertEqual(self.controle()['statut'],'bloque')
    def test_planning_hors_fenetre(self):
        self.d['resultat']['debuts_heures']=[22];self.assertEqual(self.controle()['statut'],'bloque')
    def test_statut_non_resolu_ne_devient_pas_infaisable(self):
        self.d['resultat']['retenu']['statut']=4
        with patch.object(coherence,'capacite_rapide',return_value=dict(statut=4)):
            self.assertEqual(self.controle()['statut'],'non_resolu')
    def test_preuve_contradictoire(self):
        self.d['resultat']['preuve_solveur']={'statut':'infaisable'}
        self.assertEqual(self.controle()['statut'],'bloque')
    def test_optimum_lie_au_planning_et_a_la_borne(self):
        p=dict(statut='optimal',calcul=dict(statut=0,capacite_utile_kwh=0),debuts_pas=[32],objectif_kwh=0,borne_inferieure_kwh=0)
        self.d['resultat']['preuve_solveur']=p
        self.assertEqual(self.controle()['statut'],'optimal')
        p['debuts_pas']=[36];self.assertEqual(self.controle()['statut'],'bloque')
        p['debuts_pas']=[32];p['borne_inferieure_kwh']=-10
        self.assertEqual(self.controle()['statut'],'bloque')
    def test_tolerance_optimalite_commune(self):
        # Constat 18 : même tolérance que planning_solveur pour l'écart objectif moins borne.
        t=coherence.TOLERANCE_OPTIMALITE_KWH
        p=dict(statut='optimal',calcul=dict(statut=0,capacite_utile_kwh=0),debuts_pas=[32],objectif_kwh=0,borne_inferieure_kwh=-.5*t)
        self.d['resultat']['preuve_solveur']=p
        self.assertEqual(self.controle()['statut'],'optimal')
        p['borne_inferieure_kwh']=-2*t;self.assertEqual(self.controle()['statut'],'bloque')
        p['borne_inferieure_kwh']=0;p['objectif_kwh']=2*t
        self.assertEqual(self.controle()['statut'],'bloque')
    def test_impossibilite_limitee_et_brut_conserve(self):
        self.d['faits']['plafond_kw']['valeur']=20
        self.d['resultat']['retenu']={'statut':2}
        avant=copy.deepcopy(self.d)
        self.assertEqual(self.controle()['statut'],'infaisable_dans_modele')
        self.assertEqual(self.d,avant)

    def test_echec_heuristique_ne_prouve_pas_impossibilite_globale(self):
        self.d['profil']=[0]*96
        self.d['faits']['plafond_kw']['valeur']=5
        self.d['faits']['puissance_max_kw']['valeur']=1
        self.d['resultat']['retenu']={'statut':2}
        self.assertEqual(self.controle()['statut'],'planning_infaisable')

    def test_certificat_puissance_de_base(self):
        self.d['profil'][0]=171
        self.d['resultat']['retenu']={'statut':2}
        c=self.controle()
        self.assertEqual(c['statut'],'infaisable_dans_modele')
        self.assertIn('puissance maximale',c['conclusion'])

    def test_echec_controle_physique_solveur_bloque(self):
        self.d['resultat']['preuve_solveur']={'statut':'echec','type_echec':'controle_physique'}
        self.assertEqual(self.controle()['statut'],'bloque')

    def test_erreur_moteur_non_resolue(self):
        with patch.object(coherence,'capacite_rapide',side_effect=ValueError('Échelle non finie')):
            c=self.controle()
            self.assertEqual(c['statut'],'non_resolu')
            self.assertIn('Échelle non finie',c['conclusion'])
            self.assertNotIn('infaisable',c['conclusion'])

    def test_conclusion_deterministe_et_pas_optimum_invente(self):
        a=self.controle();b=self.controle()
        self.assertEqual(a['conclusion'].encode(),b['conclusion'].encode())
        for mot in ['Planning optimal','garanti','infaisable','impossible']:
            self.assertNotIn(mot,a['conclusion'])

if __name__=='__main__':unittest.main()
