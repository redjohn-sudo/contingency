"""Relecture annuelle d'un profil afname, sans modification implicite de charge.

Le résultat financier est un coût annuel de référence HT aux tarifs fournis.
Ce n'est ni une facture future, ni un revenu garanti, ni un conseil de signature.
Les validations de pièces sont déclarées par le lecteur, pas authentifiées ici.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from horodatages import lire_fins_quarts
from regles_contrats_nl import admissibilite, date_iso, premiere_date_gtv, RISQUE_NORTHC, SOURCES
from pointes_ponderees import verifier_calendrier, maxima_mensuels_ponderes

ZONE = ZoneInfo('Europe/Amsterdam')
QUART = timedelta(minutes=15)
VERSION = 'contrats-nl-3'


def nombre(valeur, nom, maximum=1e12):
    if type(valeur) not in (int, float) or not 0 <= valeur <= maximum or not math.isfinite(valeur):
        raise ValueError(f'{nom} : nombre fini positif ou nul attendu.')
    return float(valeur)


def objet(valeur, nom):
    if not isinstance(valeur, dict):
        raise ValueError(f'{nom} : objet attendu.')
    return valeur


def fait(donnees, cle, manquants, traces):
    """Une hypothèse reste calculable mais bloque toute conclusion dominante."""
    fiche = donnees.get(cle)
    if fiche is None:
        manquants.append(cle + ' : valeur et pièce manquantes.')
        return None
    objet(fiche, cle)
    valeur = fiche.get('valeur')
    valide = (fiche.get('statut') == 'verifie'
              and isinstance(fiche.get('source'), str) and bool(fiche['source'].strip())
              and isinstance(fiche.get('verifie_par'), str) and bool(fiche['verifie_par'].strip())
              and isinstance(fiche.get('date_verification'), str))
    if valide:
        date_iso(fiche['date_verification'])
    if not valide or valeur is None:
        manquants.append(cle + ' : valeur, source et validation humaine à confirmer.')
    traces[cle] = {k: fiche.get(k) for k in ('source', 'statut', 'verifie_par', 'date_verification')}
    return valeur


def analyser_annee(puissances, horaires):
    if not isinstance(puissances, list) or not isinstance(horaires, list) or len(puissances) != len(horaires):
        raise ValueError('Deux listes de même longueur sont attendues pour le profil.')
    if not 35040 <= len(puissances) <= 35136:
        raise ValueError('Une année civile complète de quarts d’heure est requise, sans extrapolation.')
    valeurs = [nombre(p, 'Puissance kW', 1e7) for p in puissances]
    fins = [d.astimezone(timezone.utc) for d in lire_fins_quarts(horaires)]
    try:
        debuts = [(fin - QUART).astimezone(ZONE) for fin in fins]
    except (OverflowError, ValueError) as erreur:
        raise ValueError('Horodatage hors plage pour une année civile NL.') from erreur
    annee = debuts[0].year
    if not 1900 <= annee <= 9997:
        raise ValueError('Année de mesure hors plage.')
    debut = datetime(annee, 1, 1, tzinfo=ZONE).astimezone(timezone.utc)
    fin = datetime(annee + 1, 1, 1, tzinfo=ZONE).astimezone(timezone.utc)
    if fins[0] - QUART != debut or fins[-1] != fin or len(fins) != int((fin - debut).total_seconds() / 900):
        raise ValueError('Le profil doit couvrir exactement janvier à décembre en Europe/Amsterdam.')
    mensuel = {str(mois): {'pointe_kw': 0., 'energie_kwh': 0., 'quarts': 0} for mois in range(1, 13)}
    for p, instant in zip(valeurs, debuts):
        mesure = mensuel[str(instant.month)]
        mesure['pointe_kw'] = max(mesure['pointe_kw'], p)
        mesure['energie_kwh'] += p / 4
        mesure['quarts'] += 1
    contenu = {'fins_utc': [fin.isoformat() for fin in fins], 'puissances_kw': valeurs}
    empreinte = hashlib.sha256(json.dumps(contenu, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    resume = {'annee_mesuree': annee, 'quarts': len(valeurs), 'pointe_kw': max(valeurs),
              'energie_kwh': math.fsum(valeurs) / 4, 'mensuel': mensuel,
              'sha256': empreinte, 'fuseau': 'Europe/Amsterdam'}
    return resume, valeurs, debuts


def programme_annuel(programme, produit, gtv, variable, debuts, empreinte):
    """Plafonds totaux du site, jamais une soustraction de production supposée.

    Mode récurrent : heures civiles, début inclus, fin exclue, pas de plage
    traversant minuit (la découper explicitement en deux). Mode horodaté :
    un plafond total et un indicateur d'appel par quart, liés à l'empreinte.
    """
    objet(programme, 'programme')
    n = len(debuts)
    if programme.get('mode') == 'horodate':
        if produit == 'tijdsblok':
            raise ValueError('Tijdsblok : déclarer les blocs contractuels en heures entières.')
        if programme.get('sha256_profil') != empreinte:
            raise ValueError('Le programme horodaté ne correspond pas à l’empreinte du profil.')
        plafonds, actifs = programme.get('plafonds_kw'), programme.get('actifs')
        if not isinstance(plafonds, list) or not isinstance(actifs, list) or len(plafonds) != n or len(actifs) != n:
            raise ValueError('Un plafond et un indicateur actif sont requis pour chaque quart.')
        limites = [nombre(p, 'Plafond kW', 1e7) for p in plafonds]
        if any(type(a) is not bool for a in actifs):
            raise ValueError('Les indicateurs actifs doivent être des booléens.')
        maximum = gtv if produit == 'cbc' else gtv + variable
        if any(p > maximum for p in limites):
            raise ValueError('Un plafond dépasse la capacité contractuelle déclarée.')
        if produit != 'cbc' and any(p < gtv for p in limites):
            raise ValueError('Une allocation variable totale ne peut pas réduire le droit ferme déclaré.')
        if produit == 'cbc' and any(p != gtv and not a for p, a in zip(limites, actifs)):
            raise ValueError('Toute restriction CBC doit porter un indicateur actif.')
        return limites, actifs
    if programme.get('mode') != 'recurrent' or produit not in ('cbc', 'tijdsblok'):
        raise ValueError('Programme récurrent réservé au CBC et aux blocs ; sinon fournir les allocations horodatées.')
    plages = programme.get('plages')
    if not isinstance(plages, list) or not 1 <= len(plages) <= 100:
        raise ValueError('Entre une et cent plages sont requises.')
    regles = []
    for plage in plages:
        objet(plage, 'plage')
        a = nombre(plage.get('debut_heure'), 'Début de plage', 24)
        b = nombre(plage.get('fin_heure'), 'Fin de plage', 24)
        if not a < b or (a * 4) % 1 or (b * 4) % 1:
            raise ValueError('Plage croissante au quart d’heure, découper une plage traversant minuit.')
        if produit == 'tijdsblok' and (a % 1 or b % 1):
            raise ValueError('Tijdsblok : heures entières requises par la Systeemcode.')
        mois, jours = plage.get('mois'), plage.get('jours')
        for liste, maximum, minimum in ((mois, 12, 1), (jours, 6, 0)):
            if not isinstance(liste, list) or not liste or any(type(v) is not int or not minimum <= v <= maximum for v in liste):
                raise ValueError('Mois 1..12 et jours 0..6 explicites requis pour chaque plage.')
            if len(liste) != len(set(liste)):
                raise ValueError('Jour ou mois répété dans une plage.')
        plafond = nombre(plage.get('plafond_kw'), 'Plafond CBC', 1e7) if produit == 'cbc' else gtv + variable
        if produit == 'cbc' and plafond > gtv:
            raise ValueError('Un plafond CBC ne peut pas dépasser le GTV ferme.')
        regles.append((a, b, set(mois), set(jours), plafond))
    limites, actifs = [], []
    for instant in debuts:
        correspond = [p for a, b, mois, jours, p in regles if instant.month in mois
                      and instant.weekday() in jours and a <= instant.hour + instant.minute / 60 < b]
        # Un chevauchement CBC conserve la limite la plus restrictive, sans doublon.
        limites.append(min(correspond) if correspond else gtv)
        actifs.append(bool(correspond))
    return limites, actifs


def depassements(valeurs, debuts, limites, actifs=None):
    if len(valeurs) != len(debuts) or len(valeurs) != len(limites) or (actifs is not None and len(actifs) != len(valeurs)):
        raise ValueError('Les limites et le profil doivent couvrir les mêmes quarts.')
    ecarts = [(i, max(0., p - limite)) for i, (p, limite) in enumerate(zip(valeurs, limites))]
    ecarts = [(i, ecart) for i, ecart in ecarts if ecart > 1e-9 and (actifs is None or actifs[i])]
    jours = sorted({debuts[i].date().isoformat() for i, _ in ecarts})
    return {'quarts': len(ecarts), 'jours': jours, 'pointe_ecart_kw': max((e for _, e in ecarts), default=0.),
            'energie_au_dessus_kwh': math.fsum(e for _, e in ecarts) / 4,
            'premiers': [{'debut_local': debuts[i].isoformat(), 'puissance_kw': valeurs[i],
                          'plafond_kw': limites[i]} for i, _ in ecarts[:5]]}


def cout_transport(tarif, resume, valeurs, capacite_facturee, categorie, gestionnaire, annee, pointes_ponderees=None):
    objet(tarif, 'tarif')
    if (tarif.get('categorie') != categorie or tarif.get('gestionnaire') != gestionnaire
            or type(tarif.get('annee')) is not int or tarif['annee'] != annee):
        raise ValueError('Le tarif doit correspondre au gestionnaire, à la catégorie et à l’année déclarés.')
    termes = {k: nombre(tarif.get(k), k) for k in ('contrat_eur_kw_an', 'pointe_eur_kw_mois', 'fixe_transport_eur_an', 'autres_reseau_eur_an')}
    energie = tarif.get('energie_eur_kwh')
    if isinstance(energie, list):
        if len(energie) != len(valeurs) or tarif.get('sha256_profil') != resume['sha256']:
            raise ValueError('Les tarifs énergétiques par quart doivent correspondre à l’empreinte du profil.')
        energie_eur = math.fsum(p * nombre(t, 'Tarif énergie') / 4 for p, t in zip(valeurs, energie))
    else:
        energie_eur = resume['energie_kwh'] * nombre(energie, 'Tarif énergie')
    if tarif.get('assiette_pointes') == 'mensuelle_ponderee':
        if (pointes_ponderees is None or pointes_ponderees.get('sha256_profil') != resume['sha256']
                or set(pointes_ponderees.get('mensuel', {})) != {str(m) for m in range(1, 13)}):
            raise ValueError('Douze maxima pondérés liés au profil sont requis pour ce tarif.')
        somme_pointes = math.fsum(m['pointe_ponderee_kw'] for m in pointes_ponderees['mensuel'].values())
    else:
        somme_pointes = math.fsum(m['pointe_kw'] for m in resume['mensuel'].values())
    montants = {'capacite_eur': capacite_facturee * termes['contrat_eur_kw_an'],
                'pointes_eur': somme_pointes * termes['pointe_eur_kw_mois'],
                'energie_eur': energie_eur, 'fixe_transport_eur': termes['fixe_transport_eur_an'],
                'autres_reseau_eur': termes['autres_reseau_eur_an']}
    montants['total_eur'] = math.fsum(montants.values())
    return montants


def verifier_assiette_tarif(tarif, resume, produit, coefficient):
    """Le tarif n'est pas seulement un montant : il définit aussi quoi multiplier.

    Tarievencode 2026 art. 3.8 à 3.14. Pointes mensuelles ordinaires ou
    pondérées, régime hebdomadaire de courte utilisation encore exclu.
    """
    objet(tarif, 'tarif')
    manque = []
    categorie = tarif.get('categorie_code')
    assiette = tarif.get('assiette_pointes')
    if categorie not in tuple('abcdefgh'):
        manque.append('Tarif : lettre de catégorie nationale a à h à confirmer, indépendamment du nom commercial.')
    if assiette not in ('mensuelle_non_ponderee', 'mensuelle_ponderee', 'aucune'):
        manque.append('Tarif : assiette des pointes absente ou non prise en charge ; maxima hebdomadaires non calculés.')
    if categorie in ('a', 'b') and assiette != 'mensuelle_ponderee':
        manque.append('Catégorie EHS/HS : le maximum mensuel pondéré est requis, une pointe brute ne suffit pas.')
    if categorie not in ('a', 'b') and assiette == 'mensuelle_ponderee':
        manque.append('Pondération mensuelle : réservée aux catégories EHS/HS a et b dans ce module.')
    if categorie in ('a', 'b', 'c', 'd'):
        pointe = resume['pointe_kw']
        if pointe == 0 or resume['energie_kwh'] / pointe <= 600:
            manque.append('Catégorie EHS/HS, TS ou HS+TS/MS à courte utilisation : régime hebdomadaire à vérifier et non calculé ici.')
    if categorie in ('c', 'd', 'e', 'f') and assiette == 'aucune':
        manque.append('Cette catégorie comporte une pointe tarifaire ; elle ne peut pas être omise.')
    if categorie in ('g', 'h') and assiette != 'aucune':
        manque.append('Catégorie LS : vérifier l’absence de terme de pointe dans le barème applicable.')
    if assiette == 'aucune' and tarif.get('pointe_eur_kw_mois') != 0:
        manque.append('Absence de terme de pointe : le tarif de pointe doit être explicitement nul.')
    if produit in ('volledig_variabel', 'tijdsduur') and coefficient != 0:
        manque.append('Tarievencode 3.14 : pas de terme kW contract sur la partie variable ; coefficient nul à confirmer.')
    return manque


def remuneration_cbc(remuneration, debuts, actifs, defauts):
    objet(remuneration, 'remuneration')
    if remuneration.get('regle_defaut') != 'jour_entier':
        raise ValueError('CBC : cette formule applique la perte du jour entier. Une clause différente nécessite un calcul distinct.')
    jours = sorted({d.date().isoformat() for d, actif in zip(debuts, actifs) if actif})
    if remuneration.get('mode') == 'jour_actif':
        taux = nombre(remuneration.get('euros_par_jour'), 'Rémunération par jour')
        montants = {jour: taux for jour in jours}
    elif remuneration.get('mode') == 'jours_explicites':
        bruts = objet(remuneration.get('montants_eur'), 'Montants CBC par jour')
        if set(bruts) != set(jours):
            raise ValueError('La rémunération doit couvrir exactement les jours actifs, zéro explicite accepté.')
        montants = {j: nombre(v, 'Rémunération du jour') for j, v in bruts.items()}
    else:
        raise ValueError('Formule CBC non prise en charge : fournir les montants par jour issus de l’annexe.')
    perdus = sorted(set(jours) & set(defauts['jours']))
    brut = math.fsum(montants.values())
    perdu = math.fsum(montants[jour] for jour in perdus)
    return {'brute_eur': brut, 'perdue_eur': perdu, 'residuelle_eur': brut - perdu,
            'jours_actifs': len(jours), 'jours_perdus': perdus,
            'limite': 'Les responsabilités, pénalités supplémentaires et le risque de déconnexion ne sont pas valorisés.'}


def comparer_contrats(puissances, horaires, configuration):
    objet(configuration, 'configuration')
    try:
        json.dumps(configuration, allow_nan=False, ensure_ascii=False)
    except (ValueError, TypeError, OverflowError, RecursionError) as erreur:
        raise ValueError('La fiche doit être un objet JSON sans nombre non fini, objet cyclique ou imbrication excessive.') from erreur
    resume, valeurs, debuts = analyser_annee(puissances, horaires)
    communs, traces = [], {}
    provenance = fait(configuration, 'provenance', communs, traces)
    resume['provenance_declaree'] = provenance
    if provenance is not None:
        objet(provenance, 'provenance')
        if provenance.get('nature') != 'mesure_individuelle':
            communs.append('Un profil individuel mesuré est requis pour désigner un gagnant.')
        if provenance.get('sha256_profil') != resume['sha256']:
            communs.append('Relier la preuve de provenance à l’empreinte du profil analysé.')
        for cle in ('site_unique', 'qualites_controlees', 'fuseau_confirme'):
            if provenance.get(cle) is not True:
                communs.append('Provenance : ' + cle + ' à confirmer.')
        if provenance.get('canal') != 'afname':
            raise ValueError('Le comparateur traite uniquement la consommation afname.')
    site = fait(configuration, 'site', communs, traces)
    actuel = fait(configuration, 'contrat_actuel', communs, traces)
    if actuel is not None:
        objet(actuel, 'contrat_actuel')
        if actuel.get('produit') is None:
            communs.append('Contrat actuel : confirmer un droit entièrement fixe sans CBC actif ; aucune référence financière calculée sans cette nature.')
        elif actuel['produit'] != 'fixe':
            communs.append('Contrat actuel non fixe ou avec CBC : référence non prise en charge ; ses limites et sa rémunération ne peuvent pas être ignorées.')
    if site is None or actuel is None or actuel.get('produit') != 'fixe':
        return {'version': VERSION, 'profil': resume, 'options': [], 'dominante': None,
                'manquants': communs, 'traces': traces, 'risque_northc': RISQUE_NORTHC,
                'sources': SOURCES}
    objet(site, 'site'); objet(actuel, 'contrat_actuel')
    gtv_actuel = nombre(actuel.get('gtv_kw'), 'GTV actuel', 1e7)
    physique = nombre(site.get('puissance_raccordement_kw'), 'Puissance physique du raccordement', 1e7)
    if gtv_actuel > physique:
        raise ValueError('Le GTV actuel dépasse la capacité physique déclarée.')
    gestionnaire = site.get('gestionnaire')
    if gestionnaire not in ('liander', 'enexis', 'stedin', 'tennet'):
        communs.append('Gestionnaire non couvert : aucune conclusion dominante.')
    if not isinstance(actuel.get('categorie'), str) or not actuel['categorie'].strip():
        raise ValueError('Catégorie tarifaire actuelle manquante.')
    jour_comparaison = date_iso(configuration.get('date_comparaison'))
    annee_tarifaire = configuration.get('annee_tarifaire')
    if type(annee_tarifaire) is not int or annee_tarifaire != jour_comparaison.year:
        raise ValueError('L’année du tarif doit être celle de la date de comparaison.')
    options = configuration.get('options', [])
    if not isinstance(options, list) or len(options) > 20:
        raise ValueError('Au maximum vingt options sont acceptées.')
    identifiants = []
    for option in options:
        objet(option, 'option')
        identifiant = option.get('id')
        if not isinstance(identifiant, str) or not identifiant.strip() or identifiant == 'actuel' or identifiant in identifiants:
            raise ValueError('Identifiant unique non vide requis, actuel est réservé.')
        identifiants.append(identifiant)
    base = {'id': 'actuel', 'libelle': 'Contrat actuel', 'produit': 'fixe',
            'gtv_fixe_kw': {'valeur': gtv_actuel, **traces['contrat_actuel']},
            'categorie': {'valeur': actuel['categorie'], **traces['contrat_actuel']},
            'tarif': configuration.get('tarif_actuel'),
            'calendrier_ponderation': configuration.get('calendrier_ponderation_actuel'),
            'couts_complementaires_eur_an': configuration.get('couts_actuels_eur_an'),
            'cout_depassement_eur_an': configuration.get('cout_depassement_actuel_eur_an'),
            'couts_exhaustifs': configuration.get('couts_actuels_exhaustifs')}
    resultats = []
    for option in [base] + options:
        manque, preuves, refus = list(communs), {}, []
        identifiant = option['id']
        produit = option.get('produit')
        gtv = fait(option, 'gtv_fixe_kw', manque, preuves)
        categorie = fait(option, 'categorie', manque, preuves)
        if categorie is not None and (not isinstance(categorie, str) or not categorie.strip()):
            raise ValueError('La catégorie tarifaire doit être un texte non vide.')
        if gtv is not None:
            gtv = nombre(gtv, 'GTV fixe', 1e7)
        variable = 0.
        coefficient = 0.
        if produit in ('tijdsblok', 'volledig_variabel', 'tijdsduur'):
            variable = fait(option, 'gtv_variable_kw', manque, preuves)
            coefficient = fait(option, 'part_variable_facturee', manque, preuves)
            if variable is not None:
                variable = nombre(variable, 'GTV variable', 1e7)
            if coefficient is not None:
                coefficient = nombre(coefficient, 'Part facturée', 1)
        if gtv is not None and variable is not None and gtv + variable > physique:
            refus.append('La capacité demandée dépasse la puissance physique du raccordement.')
        public = admissibilite(produit, gestionnaire, reseau=site.get('reseau'),
                tension_kv=site.get('tension_kv'), grande_connexion=site.get('grande_connexion'),
                region=site.get('region'), congestion=site.get('congestion'),
                remplacement=gtv is not None and gtv < gtv_actuel)
        refus.extend(public['refus'])
        date_effet = None
        borne_date = None
        offre = None
        if identifiant != 'actuel' and gtv is not None and gtv != gtv_actuel and option.get('demande_gtv') is not None:
            demande = fait(option, 'demande_gtv', manque, preuves)
            if demande is not None:
                objet(demande, 'demande_gtv')
                borne_date = premiere_date_gtv(demande.get('date_demande'), demande.get('categorie_code'),
                    sens='baisse' if gtv < gtv_actuel else 'hausse',
                    derniere_hausse=demande.get('derniere_hausse'),
                    historique_12_mois_confirme=demande.get('historique_12_mois_confirme'),
                    exception_acceptee=demande.get('exception_acceptee'),
                    changement_deja_effectue=demande.get('changement_deja_effectue'))
                manque.extend('Demande GTV : ' + raison for raison in borne_date['manquants'])
        if identifiant != 'actuel':
            offre = fait(option, 'offre', manque, preuves)
            if offre is not None:
                objet(offre, 'offre')
                for cle, attendu in [('gestionnaire', gestionnaire), ('tension_kv', site.get('tension_kv')),
                                     ('produit', produit), ('categorie', categorie), ('gtv_fixe_kw', gtv),
                                     ('gtv_variable_kw', variable)]:
                    if attendu is None or offre.get(cle) != attendu or (isinstance(attendu, (int, float)) and type(offre.get(cle)) not in (int, float)):
                        manque.append('Offre : concordance de ' + cle + ' à vérifier.')
                for cle in ('admissibilite_confirmee', 'regles_actuelles_verifiees', 'conditions_verifiees'):
                    if offre.get(cle) is not True:
                        manque.append('Offre : ' + cle + ' à confirmer.')
                if gtv is not None and gtv < gtv_actuel and offre.get('baisse_gtv_acceptee') is not True:
                    manque.append('Baisse du droit ferme et date acceptées par le gestionnaire à confirmer.')
                if offre.get('date_effet') is None:
                    manque.append('Date d’effet confirmée manquante.')
                else:
                    date_effet = date_iso(offre['date_effet'])
                    if date_effet > jour_comparaison:
                        manque.append('Cette offre ne prend pas effet à la date de comparaison.')
                    if borne_date and borne_date['borne_reglementaire'] and date_effet < date_iso(borne_date['borne_reglementaire']):
                        manque.append('Date d’offre antérieure à la borne réglementaire calculée : vérifier l’exception et les pièces.')
                if offre.get('date_fin') is not None:
                    if date_iso(offre['date_fin']) < jour_comparaison:
                        manque.append('L’offre n’est plus valable à la date de comparaison.')
            else:
                manque.extend(public['manquants'])
        else:
            if site.get('tension_kv') is None or site.get('reseau') is None or site.get('grande_connexion') is None:
                manque.extend(public['manquants'])
        limites, actifs = None, None
        if gtv is not None and variable is not None:
            if produit == 'fixe':
                limites, actifs = [gtv] * len(valeurs), [False] * len(valeurs)
            else:
                programme = fait(option, 'programme', manque, preuves)
                if programme is not None:
                    limites, actifs = programme_annuel(programme, produit, gtv, variable, debuts, resume['sha256'])
                    if produit == 'tijdsblok' and gestionnaire in ('liander', 'enexis', 'stedin'):
                        plages = programme.get('plages', [])
                        standard = len(plages) == 1 and plages[0].get('debut_heure') == 0 and plages[0].get('fin_heure') == 6
                        standard = standard and set(plages[0].get('mois', [])) == set(range(1, 13)) and set(plages[0].get('jours', [])) == set(range(7))
                        if standard and coefficient is not None and abs(coefficient - .25) > 1e-9:
                            manque.append('Le bloc public quotidien 00:00 à 06:00 facture 25 % du terme de capacité ; vérifier le coefficient fourni.')
                        if not standard and (not offre or offre.get('horaire_particulier_confirme') is not True):
                            manque.append('Horaire distinct de la phase publique 00:00 à 06:00 : offre particulière et barème à confirmer.')
                    if produit in ('volledig_variabel', 'tijdsduur'):
                        manque.append('Allocations futures et continuité du transport non garanties par la relecture historique.')
        defauts = depassements(valeurs, debuts, limites) if limites is not None else None
        reference_depassee = identifiant == 'actuel' and defauts is not None and defauts['quarts'] > 0
        cout_depassement = 0.
        if reference_depassee:
            cout_depassement = fait(option, 'cout_depassement_eur_an', manque, preuves)
            if cout_depassement is not None:
                cout_depassement = nombre(cout_depassement, 'Coût du dépassement actuel')
        elif defauts and defauts['quarts']:
            refus.append('Le profil inchangé dépasse les limites : adaptation de process et coûts non démontrés.')
        couts = None
        tarif = fait(option, 'tarif', manque, preuves)
        if tarif is not None:
            objet(tarif, 'tarif')
        prix_manquants = []
        if tarif is not None:
            for cle_prix in ('contrat_eur_kw_an', 'pointe_eur_kw_mois', 'fixe_transport_eur_an',
                             'autres_reseau_eur_an', 'energie_eur_kwh'):
                prix = tarif.get(cle_prix)
                if prix is None or (cle_prix == 'energie_eur_kwh' and isinstance(prix, list) and any(p is None for p in prix)):
                    prix_manquants.append(f'Option {identifiant}, tarif : prix {cle_prix} à renseigner.')
                elif isinstance(prix, list) and cle_prix == 'energie_eur_kwh':
                    for element in prix:
                        nombre(element, f'Option {identifiant}, tarif {cle_prix}')
                else:
                    nombre(prix, f'Option {identifiant}, tarif {cle_prix}')
            manque.extend(prix_manquants)
        classement = None
        if produit == 'tijdsblok':
            classement = fait(option, 'classement_tarifaire', manque, preuves)
            if classement is not None:
                objet(classement, 'classement_tarifaire')
                capacite_classee = nombre(classement.get('puissance_totale_kw'), 'Puissance du classement tarifaire', 1e7)
                if gtv is None or variable is None or abs(capacite_classee - gtv - variable) > 1e-9:
                    manque.append('Catégorie Blokstroom : justifier le classement sur GTV fixe plus totalité du GTV variable, sans coefficient de 25 %.')
                if classement.get('categorie') != categorie or (tarif is not None and classement.get('categorie_code') != tarif.get('categorie_code')):
                    manque.append('Catégorie Blokstroom : le classement individuel doit correspondre au barème utilisé.')
        pointes_ponderees = None
        if tarif is not None and gtv is not None and variable is not None and coefficient is not None and categorie is not None:
            assiette_manquante = verifier_assiette_tarif(tarif, resume, produit, coefficient)
            manque.extend(assiette_manquante)
            if not assiette_manquante and tarif.get('assiette_pointes') == 'mensuelle_ponderee':
                calendrier = fait(option, 'calendrier_ponderation', manque, preuves)
                if calendrier is None:
                    assiette_manquante = ['calendrier_ponderation']
                else:
                    assiette_manquante = verifier_calendrier(calendrier, resume, site, tarif['categorie_code'], annee_tarifaire)
                    manque.extend(assiette_manquante)
                    if not assiette_manquante:
                        pointes_ponderees = maxima_mensuels_ponderes(valeurs, debuts, calendrier)
            if not assiette_manquante and not prix_manquants:
                couts = cout_transport(tarif, resume, valeurs, gtv + variable * coefficient, categorie, gestionnaire, annee_tarifaire, pointes_ponderees)
        remuneration = {'brute_eur': 0., 'perdue_eur': 0., 'residuelle_eur': 0.}
        defauts_cbc = None
        if produit == 'cbc':
            remuneration = None
            fiche_remuneration = fait(option, 'remuneration', manque, preuves)
            if fiche_remuneration is not None:
                objet(fiche_remuneration, 'remuneration')
                if fiche_remuneration.get('annexe1_verifiee') is not True:
                    manque.append('Annexe 1 CBC : formule, périodes et règle de défaut à confirmer ; rémunération conditionnelle seulement.')
            if fiche_remuneration is not None and actifs is not None and defauts is not None:
                defauts_cbc = depassements(valeurs, debuts, limites, actifs)
                remuneration = remuneration_cbc(fiche_remuneration, debuts, actifs, defauts_cbc)
        supplement = fait(option, 'couts_complementaires_eur_an', manque, preuves)
        if supplement is not None:
            supplement = nombre(supplement, 'Coûts complémentaires annuels')
        exhaustif = fait(option, 'couts_exhaustifs', manque, preuves)
        if exhaustif is not True:
            manque.append('Exhaustivité des coûts réseau, process, installation, financement, maintenance et CSP à confirmer.')
        total = None
        if couts is not None and supplement is not None and remuneration is not None and cout_depassement is not None:
            total = couts['total_eur'] + supplement + cout_depassement - remuneration['residuelle_eur']
        manque = list(dict.fromkeys(manque))
        statut = 'incompatible' if refus else ('reference_depassee' if reference_depassee else ('incomplet' if manque else 'comparable'))
        resultats.append({'id': identifiant, 'libelle': option.get('libelle', identifiant), 'produit': produit,
                          'statut': statut, 'manquants': manque, 'refus': refus,
                          'cout_transport': couts, 'couts_complementaires_eur_an': supplement,
                          'pointes_ponderees': pointes_ponderees,
                          'remuneration_cbc': remuneration if produit == 'cbc' else None,
                          'cout_annuel_reference_eur': total, 'depassements': defauts,
                          'depassements_cbc': defauts_cbc,
                          'date_effet_confirmee': date_effet.isoformat() if date_effet else None,
                          'reference_depassee': reference_depassee,
                          'cout_depassement_eur_an': cout_depassement,
                          'classement_tarifaire': classement,
                          'borne_date_gtv': borne_date,
                          'gtv_fixe_kw': gtv, 'gtv_variable_kw': variable,
                          'capacite_facturee_kw': gtv + variable * coefficient if None not in (gtv, variable, coefficient) else None,
                          'categorie': categorie, 'filtre_public': public,
                          'risque_northc': RISQUE_NORTHC if gtv is not None and gtv < gtv_actuel else None,
                          'traces': preuves})
    cout_actuel = resultats[0]['cout_annuel_reference_eur']
    for resultat in resultats:
        cout = resultat['cout_annuel_reference_eur']
        resultat['ecart_reference_eur'] = cout_actuel - cout if cout_actuel is not None and cout is not None else None
    # Un prix manquant dans une option interdit de prétendre avoir trouvé le
    # minimum de toutes les options. Une incompatibilité publique établie peut
    # exclure une option, mais pas une donnée simplement non renseignée.
    candidats = [r for r in resultats if r['statut'] == 'comparable' and r['cout_annuel_reference_eur'] is not None]
    incomplet = any(r['manquants'] and not r['filtre_public']['refus'] for r in resultats)
    dominante = None
    if candidats and len(resultats) > 1 and not incomplet and not communs:
        minimum = min(r['cout_annuel_reference_eur'] for r in candidats)
        premiers = [r for r in candidats if abs(r['cout_annuel_reference_eur'] - minimum) < .005]
        if len(premiers) == 1:
            dominante = premiers[0]['id']
    return {'version': VERSION, 'profil': resume, 'annee_tarifaire': annee_tarifaire,
            'date_comparaison': jour_comparaison.isoformat(), 'options': resultats,
            'dominante': dominante, 'manquants': communs, 'traces': traces,
            'portee': 'Moindre coût annuel de référence HT sur le profil inchangé, aux tarifs fournis. Aucun prorata de première année, aucune prévision de revenu ou de besoins futurs.',
            'validation': 'Sources et validations humaines déclarées ; le logiciel n’authentifie pas les pièces ni l’accord du gestionnaire.',
            'risque_northc': RISQUE_NORTHC, 'sources': SOURCES}
