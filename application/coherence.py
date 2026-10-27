"""Conclusions déterministes liées au planning réellement retenu et recalculé."""
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'optimisation'))
import numpy as np
from moteur import capacite_rapide

# Même valeur que planning_solveur.TOLERANCE_OPTIMALITE_KWH, qui ne publie 'optimal' que sur ce critère.
# Recopiée plutôt qu'importée : le serveur peut tourner sans OR-Tools. Égalité contrôlée par
# optimisation/verifier_corrections_revue.py.
TOLERANCE_OPTIMALITE_KWH=1e-4

def proche(a,b,tolerance=1e-4):
    return all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in (a,b)) and abs(a-b)<=tolerance

def controler(dossier,revision_attendue):
    r=dossier['resultat']; anomalies=[]; optimal=False; calcul=None; certificat=None
    if r.get('revision')!=revision_attendue or dossier.get('revision')!=revision_attendue:
        anomalies.append('La révision du résultat ne correspond pas aux données courantes.')
    try:
        v={k:f['valeur'] for k,f in dossier['faits'].items()}
        charge=np.array(dossier['profil'],dtype=float).reshape(-1,96)
        departs=r['debuts_heures'];duree=int(v['duree_heures']*4)
        if len(departs)!=len(charge):raise ValueError('Nombre de départs incohérent.')
        for j,h in enumerate(departs):
            if not isinstance(h,(int,float)) or not math.isfinite(h) or h*4!=int(h*4) or not v['ouverture_heure']<=h<=v['echeance_heure']-v['duree_heures']:
                raise ValueError('Départ hors fenêtre autorisée.')
            debut=int(h*4);charge[j,debut:debut+duree]+=v['puissance_kw']
        try:
            calcul=capacite_rapide(charge.ravel(),v['plafond_kw'],rendement=v['rendement'],puissance_max=v['puissance_max_kw'])
        except (ValueError,OverflowError,ArithmeticError) as erreur:
            return dict(statut='bloque' if anomalies else 'non_resolu',
                        conclusion='Conclusion suspendue.' if anomalies else 'Calcul non résolu. Motif du moteur : « '+str(erreur)+' »',
                        anomalies=anomalies,revision=revision_attendue,source='controle_deterministe',
                        calcul_verification={'statut':4,'message':str(erreur)},
                        limite='Le moteur ne permet pas de conclure avec ces entrées.')
        retenu=r['retenu']
        if retenu.get('statut')!=calcul['statut']:anomalies.append('Le statut conservé contredit le recalcul du planning.')
        if calcul['statut']==0:
            if not proche(retenu.get('capacite_utile_kwh'),calcul['capacite_utile_kwh']):anomalies.append('La capacité conservée contredit le recalcul.')
            for champ in ['erreur_physique_max','charge_decharge_simultanee_max_kw']:
                if not proche(calcul.get(champ),0,1e-5):anomalies.append('Contrôle physique non satisfait : '+champ)
        preuve=r.get('preuve_solveur',{})
        if preuve.get('type_echec')=='controle_physique':
            anomalies.append('Contradiction interne signalée par le contrôle physique du solveur.')
        base=np.asarray(dossier['profil'],dtype=float)
        if np.max(base)>v['plafond_kw']+v['puissance_max_kw']+1e-6:
            certificat='La demande de base dépasse le plafond réseau augmenté de la puissance maximale de décharge.'
        elif float(base.sum())*.25+len(charge)*v['puissance_kw']*v['duree_heures']>v['plafond_kw']*len(base)*.25+1e-6:
            certificat='L’énergie demandée dépasse l’apport maximal du réseau sur le cycle, même sans pertes.'
        elif preuve.get('statut')=='infaisable':
            certificat='Le solveur déclare le modèle discret infaisable, aux tolérances numériques.'
        if preuve.get('statut')=='infaisable' and calcul['statut']==0:
            anomalies.append('Le solveur annonce une impossibilité malgré un planning réalisable.')
        if preuve.get('statut')=='optimal':
            candidat=preuve.get('calcul',{})
            optimal=(calcul['statut']==0 and candidat.get('statut')==0 and
                preuve.get('debuts_pas')==[int(h*4) for h in departs] and
                proche(candidat.get('capacite_utile_kwh'),calcul.get('capacite_utile_kwh')) and
                proche(preuve.get('objectif_kwh'),calcul.get('capacite_utile_kwh'),TOLERANCE_OPTIMALITE_KWH) and
                proche(preuve.get('borne_inferieure_kwh'),preuve.get('objectif_kwh'),TOLERANCE_OPTIMALITE_KWH))
            if not optimal:anomalies.append('La preuve d’optimalité ne concorde pas avec le planning retenu.')
    except (ValueError,KeyError,TypeError,OverflowError) as erreur:
        anomalies.append('Vérification impossible : '+str(erreur))
    if anomalies:
        statut='bloque';texte='Conclusion suspendue : les résultats doivent être recalculés ou vérifiés.'
    elif calcul['statut']==0:
        statut='optimal' if optimal else 'realisable'
        texte=('Planning optimal dans le modèle déclaré, aux tolérances numériques.' if optimal else
               'Planning réalisable dans le modèle déclaré ; optimalité non prouvée.')
        texte+=' Capacité utile minimale pour le planning retenu : %.2f kWh.'%calcul['capacite_utile_kwh']
    elif calcul['statut']==2 and certificat:
        statut='infaisable_dans_modele';texte='Infaisabilité établie dans le modèle déclaré : '+certificat
    elif calcul['statut']==2:
        statut='planning_infaisable';texte='Le planning testé est infaisable dans le modèle déclaré. Cela ne démontre pas que tous les plannings sont impossibles.'
    else:
        statut='non_resolu';texte='Calcul non résolu : aucune conclusion de faisabilité ou d’impossibilité. Motif du moteur : '+str(calcul.get('message','non fourni'))
    return dict(statut=statut,conclusion=texte,anomalies=anomalies,revision=revision_attendue,
                source='controle_deterministe',calcul_verification=calcul,
                limite='Recalcul du planning par le moteur existant ; ni audit indépendant du modèle physique ni certification métier.')
