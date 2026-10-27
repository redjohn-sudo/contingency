"""Dossier Flex-e et EIA 2026 : fourchettes conditionnelles, pièces et sources.

Préparation locale seulement. Les conditions sont déclarées, pas authentifiées.
Les aides ponctuelles ne sont jamais ajoutées aux économies annuelles.
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from controles_contrat import nombre_non_negatif
from gotork import _date, _decaler_mois, texte_markdown

VERSION = 'aides-nl-2026-2'
SOURCES = {
    'scan': 'https://www.rvo.nl/subsidies-financiering/flex-e/flexibiliteitsscan',
    'faisabilite': 'https://www.rvo.nl/subsidies-financiering/flex-e/haalbaarheidsstudie',
    'conditions_scan': 'https://www.rvo.nl/subsidies-financiering/flex-e/flexibiliteitsscan/voorwaarden-scan',
    'conditions_faisabilite': 'https://www.rvo.nl/subsidies-financiering/flex-e/haalbaarheidsstudie/voorwaarden-haalbaarheidsstudie',
    'faq_flex': 'https://www.rvo.nl/subsidies-financiering/flex-e/veelgestelde-vragen',
    'eia': 'https://www.rvo.nl/subsidies-financiering/eia/ondernemers',
    'conditions_eia': 'https://www.rvo.nl/subsidies-financiering/eia/ondernemers/voorwaarden',
    'cumul_eia': 'https://www.rvo.nl/subsidies-financiering/eia/veelgestelde-vragen',
    'report_eia': 'https://www.rvo.nl/subsidies-financiering/eia/ondernemers/belastingaangifte',
    '251118': 'https://www.rvo.nl/milieu-en-energielijst-2026/251118',
    '260101': 'https://www.rvo.nl/milieu-en-energielijst-2026/260101',
    'is': 'https://www.belastingdienst.nl/wps/wcm/connect/bldcontentnl/belastingdienst/zakelijk/winst/vennootschapsbelasting/veranderingen-vennootschapsbelasting-2026/',
}
CONDITIONS_FLEX = {
    'raccordement_nl': 'Le raccordement concerné se situe aux Pays-Bas.',
    'inscription_kvk': 'Le demandeur dispose de sa propre inscription KvK.',
    'grand_raccordement': 'Raccordement supérieur à 3 × 80 A.',
    'contrat_comptage': 'Contrat avec une entreprise de comptage.',
    'ato_au_nom_demandeur': 'ATO au nom du demandeur ; justificatif ATO ou facture récente acceptée par RVO.',
    'congestion_soutirage': 'Code postal en zone de congestion de soutirage selon le gestionnaire.',
    'activite_principale_admise': 'La production, le stockage, le négoce d’énergie ou l’équilibrage ne sont pas l’activité principale.',
    'structure_admise': 'Vérifier les exclusions de structure, notamment collectivités exclues et groupements sans demandeur propre.',
    'conseiller_independant': 'Conseiller compétent et indépendant, hors groupe du demandeur ; impartialité documentée.',
    'conseiller_fourniture_conforme': 'Respect de la règle RVO excluant les fournisseurs de mesures de flexibilité de la réalisation de l’étude ; liens commerciaux et fourniture des mesures recommandées vérifiés.',
    'aucune_autre_aide_memes_couts': 'Aucune autre subvention pour la même activité ou les mêmes dépenses.',
    'aucun_autre_volet_en_cours': 'Un seul volet Flex-e demandé à la fois ; le précédent doit être achevé.',
    'mission_non_realisee': 'La prestation pour laquelle l’aide est demandée n’est pas déjà réalisée.',
    'devis_sous_condition_aide': 'Devis signé dont l’engagement dépend de l’accord RVO, coûts et heures détaillés.',
    'entreprise_hors_difficulte': 'Déclaration et schéma attestant l’absence de difficulté au sens du dispositif.',
    'obligations_execution_acceptees': 'Contenu RVO, achèvement sous un an, conservation quatre ans et coopération à l’évaluation.',
}
CONDITIONS_EIA = {
    'entreprise_imposee_nl': 'Entreprise soumise à l’impôt néerlandais, hors particulier.',
    'materiel_neuf': 'Matériel non utilisé auparavant.',
    'usage_stationnaire': 'Stockage stationnaire, hors batterie de véhicule pour le code 251118.',
    'hors_plomb_ouvert': 'Batterie autre qu’une batterie ouverte au plomb.',
    'assiette_revue': 'Coûts éligibles documentés, TVA récupérable exclue, aides sur ces mêmes coûts déduites.',
    'absence_mia_isde_memes_couts': 'Pas de cumul incompatible MIA ou ISDE sur les mêmes coûts.',
    'conditions_fiscales_revues': 'Comptable : plafond annuel disponible, paiements, mise en service, permis et autres restrictions applicables.',
}


def _texte(valeur):
    return isinstance(valeur, str) and bool(valeur.strip())


def _montant(valeur, champ):
    if not nombre_non_negatif(valeur) or valeur > 1e12:
        raise ValueError(f'{champ} : nombre fini positif ou nul, au maximum 10^12, sans booléen.')
    return Decimal(str(valeur))


def _plage(valeur, champ):
    if valeur is None:
        return None
    if not isinstance(valeur, dict):
        raise ValueError(f'{champ} : objet min/max attendu.')
    bas, haut = (_montant(valeur.get(c), champ + '.' + c) for c in ('min', 'max'))
    if bas > haut:
        raise ValueError(f'{champ} : min ne peut pas dépasser max.')
    return bas, haut


def _euros(valeur):
    return float(valeur.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def _fourchette(bas, haut):
    return {'min': _euros(bas), 'max': _euros(haut), 'unite': 'EUR', 'periode': 'ponctuel'}


def _controler_conditions(fiche, attendues):
    controles = []
    declarees = fiche.get('conditions', {})
    if not isinstance(declarees, dict):
        raise ValueError('conditions doit être un objet JSON.')
    for champ, explication in attendues.items():
        valeur = declarees.get(champ)
        if valeur is not None and type(valeur) is not bool:
            raise ValueError(champ + ' : true, false ou null attendu.')
        controles.append({'champ': champ, 'condition': explication,
                          'statut': 'declaree_satisfaite' if valeur is True else 'non_satisfaite' if valeur is False else 'a_confirmer'})
    return controles


def _ajouter(controles, champ, explication, conforme):
    controles.append({'champ': champ, 'condition': explication,
                      'statut': 'a_confirmer' if conforme is None else 'declaree_satisfaite' if conforme else 'non_satisfaite'})


def _etat(controles):
    if any(c['statut'] == 'non_satisfaite' for c in controles):
        return 'non_eligible_selon_declarations'
    if any(c['statut'] == 'a_confirmer' for c in controles):
        return 'a_completer'
    return 'conditions_declarees_a_revoir'


def _pieces(fiche, attendues):
    pieces = fiche.get('pieces', {})
    if not isinstance(pieces, dict):
        raise ValueError('pieces doit être un objet JSON de références documentaires.')
    return [{'id': identifiant, 'objet': objet,
             'reference': pieces[identifiant] if _texte(pieces.get(identifiant)) else None,
             'statut': 'reference_declaree' if _texte(pieces.get(identifiant)) else 'a_fournir'}
            for identifiant, objet in attendues.items()]


def flex_e(fiche):
    if not isinstance(fiche, dict):
        raise ValueError('flex_e doit être un objet JSON.')
    volet = fiche.get('volet')
    if volet not in ('scan', 'faisabilite'):
        raise ValueError('Choisir un seul volet : scan ou faisabilite.')
    attendues = dict(CONDITIONS_FLEX)
    if volet == 'scan':
        attendues['conseiller_fourniture_conforme'] += ' La FAQ admet le conseiller proposant des mesures sur projet s’il maîtrise plusieurs solutions et ne fournit pas lui-même les mesures conseillées pour lesquelles une aide Flex-e est demandée. Cette situation doit être documentée.'
        attendues.update(hors_peche_aquaculture='Demandeur hors pêche et aquaculture.',
                        visite_site_prevue='Au moins une visite du site par le conseiller prévue.')
    else:
        attendues['conseiller_fourniture_conforme'] += ' Un fournisseur spécialisé peut seulement être consulté pour une partie de la conception technique ; il ne réalise pas l’étude.'
        attendues['mesures_admises'] = 'Pas de mesures de cogénération ou de limitation de production renouvelable dans l’étude.'
    controles = _controler_conditions(fiche, attendues)
    instant = fiche.get('date_demande')
    dans_fenetre = None
    if instant is not None:
        try:
            instant = datetime.fromisoformat(instant.replace('Z', '+00:00'))
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError('Fuseau requis.')
            instant = instant.astimezone(ZoneInfo('Europe/Amsterdam'))
            dans_fenetre = (datetime(2026, 5, 6, 9, tzinfo=instant.tzinfo) <= instant
                           <= datetime(2026, 10, 15, 17, tzinfo=instant.tzinfo))
        except (ValueError, TypeError, AttributeError, OverflowError) as erreur:
            raise ValueError('date_demande : date et heure ISO avec fuseau requises.') from erreur
    _ajouter(controles, 'fenetre_2026', 'Dépôt du 6 mai 2026 à 09:00 au 15 octobre 2026 à 17:00, heure néerlandaise, sous réserve du budget.', dans_fenetre)
    couts = _plage(fiche.get('couts_eligibles_ht_eur'), 'couts_eligibles_ht_eur')
    plafond = Decimal(10000 if volet == 'scan' else 125000)
    conditionnelle = None
    hypotheses = ['Estimation à confirmer par RVO ; aucun accord ni budget disponible présumé.',
                  '50 % des coûts éligibles HT, sans financer deux fois les mêmes dépenses.',
                  f'Plafond du volet sélectionné : {int(plafond)} EUR.',
                  'Le scan et la faisabilité sont des demandes distinctes et successives.']
    if volet == 'faisabilite':
        hypotheses.append('Aide de faisabilité au moins égale à 10 000 EUR : coûts éligibles au moins égaux à 20 000 EUR ; aucun arrondi au minimum.')
    if couts is None:
        _ajouter(controles, 'couts_eligibles_ht_eur', 'Devis avec assiette HT min/max documentée.', None)
    else:
        bas, haut = [min(c * Decimal('.5'), plafond) for c in couts]
        if volet == 'faisabilite':
            _ajouter(controles, 'minimum_faisabilite', 'Le budget éligible doit permettre une aide d’au moins 10 000 EUR.',
                     False if haut < 10000 else True if bas >= 10000 else None)
            if bas < 10000:
                bas = Decimal(0)
            if haut < 10000:
                haut = Decimal(0)
        conditionnelle = _fourchette(bas, haut)
    statut = _etat(controles)
    if statut == 'non_eligible_selon_declarations':
        conditionnelle = _fourchette(Decimal(0), Decimal(0))
    prudente = None if conditionnelle is None else _fourchette(Decimal(0), Decimal(str(conditionnelle['max'])))
    pieces = _pieces(fiche, {
        'identite': 'KvK, établissement, SBI, coordonnées du demandeur et contact.',
        'raccordement': 'EAN, ATO au nom du demandeur ou facture admise de deux mois au plus, contrat de comptage.',
        'congestion': 'Carte de congestion de soutirage et dernier rapport du gestionnaire.',
        'devis': 'Devis signé, condition suspensive RVO, heures, tarifs HT, méthode et planning.',
        'conseiller': 'Identité KvK, compétence, indépendance et liens de fourniture du conseiller ; conformité à la règle RVO et éventuelle situation admise par la FAQ documentées.',
        'difficulte': 'Schéma et déclaration signée sur les entreprises en difficulté.',
        'energie': 'Année représentative parmi les trois dernières, quarts d’heure, autres énergies et horaires.',
        'contenu_etude': 'Options de flexibilité, hypothèses économiques, croissance à cinq ans ; pour faisabilité, conception technique et plan de réalisation.',
    })
    return {'dispositif': 'Flex-e', 'volet': volet, 'statut': statut,
            'couts_eligibles_ht_eur': _fourchette(*couts) if couts is not None else None,
            'avantage_prudent_eur': prudente, 'si_conditions_remplies_eur': conditionnelle,
            'hypotheses': hypotheses, 'controles': controles, 'pieces': pieces,
            'sources': [SOURCES[volet], SOURCES['conditions_' + volet], SOURCES['faq_flex']],
            'nature': 'Subvention ponctuelle de prestation, pas une économie annuelle ni un prix de batterie.'}


def eia(fiche, batterie):
    if not isinstance(fiche, dict):
        raise ValueError('eia doit être un objet JSON.')
    if batterie is not None and type(batterie) is not bool:
        raise ValueError('batterie : true, false ou null attendu.')
    controles = _controler_conditions(fiche, CONDITIONS_EIA)
    regime_is = fiche.get('regime_is')
    if regime_is is not None and type(regime_is) is not bool:
        raise ValueError('regime_is : true, false ou null attendu.')
    _ajouter(controles, 'regime_is', 'Les taux de 19 à 25,8 % supposent l’impôt sur les sociétés ; un autre régime nécessite un calcul distinct.', True if regime_is is True else None)
    _ajouter(controles, 'batterie', 'Cette estimation EIA porte sur une batterie réellement envisagée.', batterie)
    code = fiche.get('code')
    if code not in (None, '251118', '260101'):
        raise ValueError('Code EIA pris en charge : 251118 ou 260101, Energielijst 2026.')
    _ajouter(controles, 'code', 'Choisir et justifier le code EIA 2026 applicable.', True if code else None)
    for champ, minimum in (('puissance_kw', 5), ('capacite_kwh', 15)):
        valeur = fiche.get(champ)
        _ajouter(controles, champ, f'{champ} au moins égal à {minimum}.',
                 None if valeur is None else _montant(valeur, champ) >= minimum)
    details = {}
    if code == '251118':
        details = {'production_renouvelable': 'Stockage d’électricité produite par une installation renouvelable.',
                   'meme_raccordement': 'Batterie et production renouvelable sur le même raccordement.'}
        crete = fiche.get('production_crete_kw')
        _ajouter(controles, 'production_crete_kw', 'Installation de production renouvelable de puissance crête strictement supérieure à 15 kW.',
                 None if crete is None else _montant(crete, 'production_crete_kw') > 15)
    elif code == '260101':
        details = {'pilotage_automatique_marche': 'Mise en marche et arrêt automatiques selon un sous-marché de l’électricité.',
                   'logiciel_connecte_marche': 'Batterie reliée au sous-marché via un logiciel d’optimisation.'}
    controles += _controler_conditions(fiche, details)
    acquisition, depot = fiche.get('date_engagement'), fiche.get('date_declaration')
    engagement = _date(acquisition) if acquisition is not None else None
    declaration = _date(depot) if depot is not None else None
    echeance = None
    if engagement is not None:
        echeance = _decaler_mois(engagement, 3)
        _ajouter(controles, 'annee_2026', 'Le millésime des codes et taux utilisés est 2026.', engagement.year == 2026)
        if declaration is not None and declaration < engagement:
            raise ValueError('La date de déclaration ne peut pas précéder la commande renseignée.')
        conforme = declaration <= echeance if declaration is not None else None
        _ajouter(controles, 'delai_declaration', 'Acquisition : déclaration RVO dans les trois mois de la commande ou de l’engagement, pas de la facture.', conforme)
    else:
        _ajouter(controles, 'date_engagement', 'Date de commande ou d’engagement nécessaire pour déterminer le millésime et le délai.', None)
    couts = _plage(fiche.get('couts_eligibles_avant_aides_eur'), 'couts_eligibles_avant_aides_eur')
    aides = _plage(fiche.get('aides_sur_memes_couts_eur'), 'aides_sur_memes_couts_eur')
    utilisable = fiche.get('deduction_integralement_utilisable')
    if utilisable is not None and type(utilisable) is not bool:
        raise ValueError('deduction_integralement_utilisable : true, false ou null attendu.')
    _ajouter(controles, 'fiscalite_utilisable', 'Faire confirmer l’impôt réellement économisable et le calendrier d’utilisation de la déduction.', True if utilisable is True else None)
    hypotheses = ['40 % de déduction du bénéfice imposable ; aucun remboursement de 40 % du prix.',
                  'Économie théorique si toute la déduction est utilisable : assiette nette × 40 % × IS de 19 à 25,8 %, soit 7,6 à 10,32 %.',
                  'Les subventions sur ces mêmes coûts diminuent l’assiette ; aucune addition automatique avec Flex-e.',
                  'Sans bénéfice actuel, un report fiscal peut être possible ; son montant et son calendrier restent à vérifier.',
                  'Aucun avantage retenu après la date limite indicative. Une éventuelle prorogation doit être examinée séparément avec RVO.',
                  'Estimation pour une acquisition de batterie soumise à l’IS ; production propre et impôt sur le revenu exigent un calcul distinct.']
    conditionnelle, assiette, deduction = None, None, None
    if couts is not None and aides is not None:
        if aides[1] > couts[1] or aides[0] > couts[0]:
            raise ValueError('Aides sur mêmes coûts supérieures aux coûts déclarés : revoir les fourchettes.')
        bas = max(Decimal(0), couts[0] - aides[1])
        haut = max(Decimal(0), couts[1] - aides[0])
        assiette = _fourchette(bas, haut)
        deduction = _fourchette(bas * Decimal('.4') if bas >= 2500 else Decimal(0),
                                haut * Decimal('.4') if haut >= 2500 else Decimal(0))
        _ajouter(controles, 'minimum_assiette', 'Assiette déclarable minimale : 2 500 EUR par déclaration (RVO, page Voorwaarden Energie-investeringsaftrek, état au 29/09/2026). '
                 'À confirmer seulement si l’investissement est déclaré avec d’autres : le seuil porte alors sur le total.',
                 False if haut < 2500 else True if bas >= 2500 else None)
        conditionnelle = _fourchette(bas * Decimal('.076') if bas >= 2500 else Decimal(0),
                                     haut * Decimal('.1032') if haut >= 2500 else Decimal(0))
    else:
        _ajouter(controles, 'assiette_nette', 'Coûts et aides sur les mêmes coûts doivent tous deux être chiffrés ; saisir min=max=0 pour une absence d’aide documentée.', None)
    statut = _etat(controles)
    if statut == 'non_eligible_selon_declarations':
        conditionnelle = _fourchette(Decimal(0), Decimal(0))
        deduction = _fourchette(Decimal(0), Decimal(0))
    prudente = None if conditionnelle is None else _fourchette(Decimal(0), Decimal(str(conditionnelle['max'])))
    if regime_is is False and batterie is not False and statut != 'non_eligible_selon_declarations':
        statut = 'hors_champ_calcul_fiscal'
        conditionnelle, prudente = None, None
    if engagement is not None and engagement.year != 2026 and batterie is not False:
        # Le millésime non couvert n'est pas une preuve d'inéligibilité à l'EIA.
        statut = 'hors_champ_millesime'
        conditionnelle, prudente, deduction = None, None, None
    if batterie is False:
        statut = 'sans_batterie'
    pieces = _pieces(fiche, {
        'commande': 'Commande ou engagement daté, prix, coûts éligibles, état neuf et date de mise en service.',
        'technique': 'Fiche fabricant : kW, kWh, chimie et usage stationnaire.',
        'code': '251118 : renouvelable, puissance crête et raccordement commun ; 260101 : pilotage et logiciel reliés au marché.',
        'fiscalite': 'Comptable : assiette nette, autres aides, régime fiscal, capacité à utiliser la déduction et plafond annuel.',
        'declaration': 'Accusé de déclaration RVO dans les délais puis déclaration EIA et déclaration fiscale.',
    })
    return {'dispositif': 'EIA', 'code': code, 'statut': statut,
            'annee_investissement': engagement.year if engagement is not None else None,
            'couts_avant_aides_eur': _fourchette(*couts) if couts is not None else None,
            'aides_deduites_eur': _fourchette(*aides) if aides is not None else None,
            'avantage_prudent_eur': prudente, 'si_conditions_remplies_eur': conditionnelle,
            'assiette_nette_eur': assiette, 'deduction_base_imposable_eur': deduction,
            'deduction_integralement_utilisable': utilisable,
            'date_limite_indicative': echeance.isoformat() if echeance else None,
            'hypotheses': hypotheses, 'controles': controles, 'pieces': pieces,
            'sources': [SOURCES[c] for c in ('eia', 'conditions_eia', 'cumul_eia', 'report_eia', 'is')] + ([SOURCES[code]] if code else []),
            'nature': 'Avantage fiscal ponctuel conditionnel ; déduction et économie d’impôt sont deux montants différents.'}


def modele():
    return {'site': '', 'batterie_envisagee': None,
            'flex_e': {'volet': 'scan', 'date_demande': None,
                       'couts_eligibles_ht_eur': None,
                       'conditions': dict.fromkeys([*CONDITIONS_FLEX, 'hors_peche_aquaculture', 'visite_site_prevue']),
                       'pieces': {}},
            'eia': {'code': None, 'regime_is': None, 'puissance_kw': None, 'capacite_kwh': None,
                    'production_crete_kw': None, 'date_engagement': None, 'date_declaration': None,
                    'couts_eligibles_avant_aides_eur': None, 'aides_sur_memes_couts_eur': None,
                    'deduction_integralement_utilisable': None,
                    'conditions': dict.fromkeys([*CONDITIONS_EIA, 'production_renouvelable', 'meme_raccordement',
                                                'pilotage_automatique_marche', 'logiciel_connecte_marche']),
                    'pieces': {}}}


def preparer(fiche):
    if not isinstance(fiche, dict):
        raise ValueError('Fiche attendue sous forme d’objet JSON.')
    if fiche.get('site') is not None and not isinstance(fiche['site'], str):
        raise ValueError('site : texte attendu.')
    batterie = fiche.get('batterie_envisagee')
    if batterie is not None and type(batterie) is not bool:
        raise ValueError('batterie_envisagee : true, false ou null attendu.')
    return {'version': VERSION, 'site': fiche.get('site'), 'batterie_envisagee': batterie,
            'sources_relues_le': '2026-09-27', 'pieces_authentifiees': False,
            'flex_e': flex_e(fiche.get('flex_e')), 'eia': eia(fiche.get('eia'), batterie),
            'total_gain_eur': None,
            'lecture': 'Les plafonds légaux ne sont pas des promesses. La fourchette prudente part de zéro tant que l’aide ou l’usage fiscal n’est pas acquis. La fourchette conditionnelle suppose les dépenses et conditions citées.',
            'scenarios': {
                'sans_batterie': ['Investissement évité : devis de la solution écartée, ponctuel, à documenter.',
                                 'Optimisation du contrat : économie annuelle distincte, à calculer sur le tarif et le profil du site.',
                                 'Flex-e : aide ponctuelle de scan ou étude, possible sous conditions même sans achat de batterie.',
                                 'EIA batterie et revenus de cette batterie : 0 à 0 EUR.'],
                'avec_batterie': ['Bon dimensionnement : comparer deux devis de même périmètre, gain ponctuel à documenter.',
                                  'EIA : avantage fiscal conditionnel calculé ci-dessus, jamais 40 % remboursés.',
                                  'Flexibilité : revenus annuels séparés à calculer avec l’agrégateur ; nuls sans activations rentables.',
                                  'Un même quart d’heure ne doit pas produire deux revenus comptés en imbalance et redispatch.'],
            }}


def rapport(resultat):
    statuts = {'a_completer': 'À compléter', 'a_confirmer': 'À confirmer',
               'declaree_satisfaite': 'Déclarée satisfaite, pièces à relire',
               'non_satisfaite': 'Condition non satisfaite selon la déclaration',
               'conditions_declarees_a_revoir': 'Conditions déclarées, dossier à relire',
               'non_eligible_selon_declarations': 'Conditions non remplies selon les déclarations',
               'sans_batterie': 'Sans batterie, aucun avantage EIA batterie',
               'hors_champ_millesime': 'Millésime hors calcul : consulter les règles de l’année d’investissement',
               'hors_champ_calcul_fiscal': 'Régime fiscal nécessitant un calcul distinct'}
    texte = texte_markdown
    def plage(valeur):
        if valeur is None:
            return 'Non chiffrable avec les données fournies'
        return f"{valeur['min']:,.2f} à {valeur['max']:,.2f} EUR".replace(',', ' ')
    lignes = ['# Dossier d’aides Pays-Bas 2026', '',
              'Site : ' + texte(resultat.get('site') or 'à renseigner'), '',
              resultat['lecture'], '',
              'Dossier préparatoire. Aucun dépôt effectué, aucune pièce authentifiée. Pas de total mêlant investissement ponctuel, aides et économies annuelles.']
    for cle in ('flex_e', 'eia'):
        bloc = resultat[cle]
        lignes += ['', '## ' + bloc['dispositif'], '',
                   'Statut : ' + statuts.get(bloc['statut'], bloc['statut']), '', bloc['nature'], '',
                   '| Estimation | Fourchette |', '| --- | --- |',
                   '| Avantage prudent | ' + plage(bloc['avantage_prudent_eur']) + ' |',
                   '| Si les conditions sont remplies | ' + plage(bloc['si_conditions_remplies_eur']) + ' |']
        if cle == 'eia':
            lignes += ['| Coûts avant aides retenus dans la fiche | ' + plage(bloc.get('couts_avant_aides_eur')) + ' |',
                       '| Aides sur ces mêmes coûts | ' + plage(bloc.get('aides_deduites_eur')) + ' |',
                       '| Assiette nette | ' + plage(bloc['assiette_nette_eur']) + ' |',
                       '| Déduction théorique du bénéfice si admissible | ' + plage(bloc['deduction_base_imposable_eur']) + ' |']
            if bloc['date_limite_indicative']:
                lignes += ['', 'Acquisition, déclaration avant le : ' + bloc['date_limite_indicative'] + ' (date indicative à confirmer).']
            lignes += ['', 'Code EIA : ' + (bloc['code'] or 'à déterminer')]
        else:
            lignes += ['| Coûts HT éligibles retenus dans la fiche | ' + plage(bloc.get('couts_eligibles_ht_eur')) + ' |']
            lignes += ['', 'Volet : ' + ('Scan de flexibilité' if bloc['volet'] == 'scan' else 'Étude de faisabilité')]
        lignes += ['', '### Hypothèses', ''] + ['- ' + h for h in bloc['hypotheses']]
        lignes += ['', '### Conditions déclarées', '']
        lignes += [f"- {texte(c['condition']).rstrip('.')} : {statuts.get(c['statut'], c['statut'])}." for c in bloc['controles']]
        lignes += ['', '### Pièces à réunir', '']
        lignes += [f"- {texte(p['objet'])} Référence : {texte(p['reference'] or 'à fournir')}." for p in bloc['pieces']]
        lignes += ['', '### Sources officielles', ''] + [f'- [Source]({s})' for s in bloc['sources']]
    lignes += ['', '## Deux réponses possibles à la batterie', '']
    for cle, titre in (('sans_batterie', 'Sans batterie'), ('avec_batterie', 'Avec batterie')):
        lignes += ['### ' + titre, ''] + ['- ' + p for p in resultat['scenarios'][cle]] + ['']
    return '\n'.join(lignes) + '\n'
