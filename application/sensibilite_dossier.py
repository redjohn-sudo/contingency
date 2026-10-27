"""Variantes explicites d'un planning validé, sans appel IA ni replanification."""
import math
import numpy as np
from moteur import capacite_rapide, VERSION as VERSION_MOTEUR

VERSION = 'sensibilite-planning-fixe-v1'
PORTEE = ('Planning machine conservé. Variation uniforme du profil de base seulement, '
          'la machine ajoutée ne varie pas. Plafond constant par scénario. '
          'Commande batterie recalculée séparément avec demande connue à l’avance et '
          'état initial libre et cyclique. Ni politique commune robuste, ni probabilité '
          'de dépassement, ni réserve de secours modélisée.')


def analyser(dossier, parametres):
    if not isinstance(parametres, dict) or set(parametres) != {'variation_charge_pct', 'variation_plafond_kw', 'motif', 'validation'}:
        raise ValueError('Paramètres de sensibilité incomplets ou inconnus.')
    if parametres['validation'] is not True:
        raise ValueError('Acceptez explicitement les hypothèses de sensibilité.')
    for cle, maximum in [('variation_charge_pct', 50), ('variation_plafond_kw', 1e7)]:
        valeur = parametres[cle]
        if type(valeur) not in (int, float) or not math.isfinite(valeur) or not 0 <= valeur <= maximum:
            raise ValueError('Variations finies et positives requises ; charge limitée à 50 %.')
    motif = parametres['motif']
    if not isinstance(motif, str) or not 15 <= len(motif.strip()) <= 2000:
        raise ValueError('Expliquez le choix des variations (15 à 2000 caractères).')
    variation, delta = parametres['variation_charge_pct'], parametres['variation_plafond_kw']
    if variation == delta == 0:
        raise ValueError('Choisissez au moins une variation non nulle.')
    valeurs = {cle: fait['valeur'] for cle, fait in dossier['faits'].items()}
    plafond = valeurs['plafond_kw']
    if delta > plafond:
        raise ValueError('La variation ne peut pas rendre le plafond négatif.')
    profil = np.asarray(dossier['profil'], dtype=float).reshape(-1, 96)
    machine = np.zeros_like(profil)
    duree = round(valeurs['duree_heures'] * 4)
    for jour, debut in enumerate(dossier['resultat']['debuts_heures']):
        depart = round(debut * 4)
        machine[jour, depart:depart + duree] = valeurs['puissance_kw']
    variantes = [('reference', 0, 0)]
    if variation:
        variantes += [('charge_basse', -variation, 0), ('charge_haute', variation, 0)]
    if delta:
        variantes += [('plafond_bas', 0, -delta), ('plafond_haut', 0, delta)]
    reference = dossier['resultat']['retenu']['capacite_utile_kwh']
    scenarios = []
    for nom, pourcentage, ecart in variantes:
        charge = (profil * (1 + pourcentage / 100) + machine).ravel()
        calcul = capacite_rapide(charge, plafond + ecart, rendement=valeurs['rendement'],
                                puissance_max=valeurs['puissance_max_kw'])
        scenario = {'nom': nom, 'variation_charge_pct': pourcentage, 'plafond_kw': plafond + ecart,
                    'calcul': calcul, 'ecart_capacite_kwh': None, 'capacite_reference_suffisante': None}
        if calcul['statut'] == 0:
            besoin = calcul['capacite_utile_kwh']
            scenario['ecart_capacite_kwh'] = besoin - reference
            scenario['capacite_reference_suffisante'] = besoin <= reference + 1e-5
        elif calcul['statut'] == 2:
            scenario['capacite_reference_suffisante'] = False
        scenarios.append(scenario)
    nominal = scenarios[0]['calcul']
    if nominal['statut'] != 0 or abs(nominal['capacite_utile_kwh'] - reference) > 1e-5:
        raise ValueError('Le calcul de référence a changé : nouvelle validation requise.')
    return {'version': VERSION, 'moteur': VERSION_MOTEUR, 'revision': dossier['revision'],
            'hypotheses': parametres | {'motif': motif.strip()}, 'portee': PORTEE,
            'debuts_heures': dossier['resultat']['debuts_heures'], 'scenarios': scenarios}


def lignes_rapport(analyse):
    lignes = ['', '## Sensibilité du planning validé', '', analyse['portee'], '',
              'Hypothèse utilisateur : ' + analyse['hypotheses']['motif'].replace('\n', ' ').replace('\r', ' '), '',
              '| Scénario | Variation du profil | Plafond kW | Besoin de lissage kWh | Capacité de référence suffisante |',
              '| :--- | ---: | ---: | ---: | :--- |']
    for scenario in analyse['scenarios']:
        calcul = scenario['calcul']
        besoin = f"{calcul['capacite_utile_kwh']:.2f}" if calcul['statut'] == 0 else ('Irréalisable pour ce planning' if calcul['statut'] == 2 else 'Non résolu')
        if calcul['statut'] == 2:
            besoin += ' : ' + calcul['message'].replace('|', '/')
        suffisant = {True: 'Oui, commande adaptée', False: 'Non', None: 'Non résolu'}[scenario['capacite_reference_suffisante']]
        lignes.append(f"| {scenario['nom']} | {scenario['variation_charge_pct']:+g} % | {scenario['plafond_kw']:g} | {besoin} | {suffisant} |")
    lignes += ['', 'Variations isolées, sans combinaison des incertitudes. Un planning impossible ne prouve pas que tous les plannings sont impossibles.',
               'Révision de référence : ' + analyse['revision'], 'Analyse SHA-256 : ' + analyse['empreinte']]
    return lignes
