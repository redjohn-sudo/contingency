"""Repérage GOTORK et préparation de la concertation, décision ACM du 16/04/2024.

Les pièces sont déclarées par le lecteur, jamais authentifiées par ce module.
Une courbe complète sert au repérage des seuils, pas à décider du nouveau GTV.
"""
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
import hashlib
import json
import re

from controles_contrat import nombre_non_negatif
from horodatages import lire_fins_quarts

SOURCE = 'https://zoek.officielebekendmakingen.nl/stcrt-2024-13531.html'
SOURCE_ACM = 'https://www.acm.nl/nl/publicaties/codebesluit-niet-gebruikte-transportrechten-gotork'
VERSION = 'gotork-2024-1'
AMSTERDAM = ZoneInfo('Europe/Amsterdam')


def _date(texte):
    if not isinstance(texte, str):
        raise ValueError('Date attendue au format AAAA-MM-JJ.')
    resultat = date.fromisoformat(texte)
    if resultat.isoformat() != texte:
        raise ValueError('Date attendue au format AAAA-MM-JJ.')
    return resultat


def _decaler_mois(jour, mois):
    indice = jour.year * 12 + jour.month - 1 + mois
    annee, mois_zero = divmod(indice, 12)
    return jour.replace(year=annee, month=mois_zero + 1,
                        day=min(jour.day, monthrange(annee, mois_zero + 1)[1]))


def _texte(valeur):
    return isinstance(valeur, str) and bool(valeur.strip())


def texte_markdown(valeur):
    """Une donnée du dossier reste du texte, sans lien, image ou tableau injecté."""
    from html import escape
    texte = escape(str(valeur))
    texte = re.sub(r'[\x00-\x1f\x7f]', ' ', texte)
    return re.sub(r'([\\`*_\[\]()!|])', r'\\\1', texte)


def modele():
    return {
        'site': '', 'pays': 'NL', 'date_analyse': None,
        'reseau': None, 'tension_kv': None, 'direction': 'soutirage',
        'congestion_confirmee': None, 'source_congestion': '',
        'contrat_ferme': None, 'gtv_kw': None, 'source_gtv': '',
        'gtv_constant_sur_periode': None, 'source_mesures': '',
        'date_notification': None, 'source_notification': '',
        'pointe_24_mois_kw': None, 'source_pointe_24_mois': '',
        'besoins_futurs': [], 'justificatifs_exception': [],
    }


def analyser(profil_kw, horodatages, fiche):
    """MT, HT <110 kV : 1 MW ; HT >=110 kV : 10 MW ; seuil relatif <=50 %.

    On exige les douze mois immédiatement précédant date_analyse, à minuit
    Amsterdam. Une année ancienne ou une simple moyenne ne suffit pas.
    """
    if not isinstance(fiche, dict):
        raise ValueError('La fiche GOTORK doit être un objet JSON.')
    if fiche.get('site') is not None and not isinstance(fiche['site'], str):
        raise ValueError('site : texte attendu.')
    manques = []
    resultat = {
        'version': VERSION, 'date_decision': '2024-04-16',
        'date_entree_vigueur': '2024-04-26', 'site': fiche.get('site'),
        'statut': 'indetermine', 'constat': 'Les informations ne permettent pas de conclure.',
        'perte_certaine': False, 'nouveau_gtv_kw': None,
        'pieces_authentifiees': False, 'sources': [SOURCE, SOURCE_ACM],
        'manques': manques, 'mesures': None,
        'conditions': ['Raccordement MT ou HT, transport ferme et congestion dans le sens étudié.',
                       'Sous-utilisation sur les douze mois précédents, puis examen des besoins futurs.',
                       'Notification écrite et possibilité de concertation avant toute décision.'],
        'procedure': [
            'Le gestionnaire notifie le constat par écrit et laisse deux mois pour entrer en concertation.',
            'Il transmet le compte rendu sous dix jours ouvrés après la concertation ; le site a dix jours ouvrés pour répondre.',
            'Il apprécie les besoins à un horizon d’au moins douze mois depuis la notification, avec les pointes disponibles sur vingt-quatre mois et les projets justifiés.',
            'La réduction éventuelle exige une modification de l’ATO et une information écrite ; ce repérage ne la prononce pas.',
        ],
        'dossier_defense': _defense(fiche),
    }
    try:
        jour = _date(fiche.get('date_analyse'))
        debut = _decaler_mois(jour, -12)
        if jour < date(2024, 4, 26):
            raise ValueError('Date antérieure à l’entrée en vigueur de GOTORK.')
    except (ValueError, OverflowError) as erreur:
        manques.append('date_analyse : ' + str(erreur))
        return resultat
    resultat['date_analyse'] = jour.isoformat()
    resultat['periode_attendue'] = {'debut_inclus': debut.isoformat(),
                                    'fin_exclue': jour.isoformat(), 'fuseau': 'Europe/Amsterdam'}
    notification = fiche.get('date_notification')
    if notification is not None:
        try:
            date_notification = _date(notification)
            if not date(2024, 4, 26) <= date_notification <= jour or not _texte(fiche.get('source_notification')):
                raise ValueError('Notification hors période applicable ou sans pièce de référence.')
            resultat['concertation_avant_date_indicative'] = _decaler_mois(date_notification, 2).isoformat()
            resultat['note_delai'] = 'Date calendaire indicative ; confirmer le délai exact sur la notification, notamment en cas de jour non ouvré.'
        except (ValueError, OverflowError) as erreur:
            manques.append('date_notification : ' + str(erreur))

    pays, reseau = fiche.get('pays'), fiche.get('reseau')
    if (_texte(pays) and pays != 'NL') or reseau == 'BT' or fiche.get('contrat_ferme') is False or fiche.get('congestion_confirmee') is False:
        resultat.update(statut='hors_champ_declare', constat='Une condition du champ GOTORK est déclarée absente. Cette déclaration reste à documenter.')
        return resultat
    for champ, valide in (
        ('pays', pays == 'NL'), ('reseau', reseau in ('MT', 'HT')),
        ('direction', fiche.get('direction') in ('soutirage', 'injection')),
        ('contrat_ferme', fiche.get('contrat_ferme') is True),
        ('congestion_confirmee', fiche.get('congestion_confirmee') is True),
        ('source_congestion', _texte(fiche.get('source_congestion'))),
        ('source_gtv', _texte(fiche.get('source_gtv'))),
        ('source_mesures', _texte(fiche.get('source_mesures'))),
        ('gtv_constant_sur_periode', fiche.get('gtv_constant_sur_periode') is True),
    ):
        if not valide:
            manques.append(champ)
    tension = fiche.get('tension_kv')
    if reseau == 'HT' and (not nombre_non_negatif(tension) or tension == 0):
        manques.append('tension_kv : nécessaire pour distinguer le seuil 1 MW du seuil 10 MW')
    if tension is not None and (not nombre_non_negatif(tension) or tension == 0
                                or (reseau == 'MT' and tension >= 110)):
        manques.append('tension_kv : valeur invalide ou contradictoire avec le réseau déclaré')
    gtv = fiche.get('gtv_kw')
    if not nombre_non_negatif(gtv) or not 0 < gtv <= 1e7:
        manques.append('gtv_kw : puissance positive finie au plus égale à 10 millions de kW')
    try:
        if not isinstance(profil_kw, (list, tuple)) or not isinstance(horodatages, (list, tuple)):
            raise ValueError('Profil et horodatages attendus sous forme de listes.')
        if not profil_kw or len(profil_kw) != len(horodatages) or len(profil_kw) > 35140:
            raise ValueError('Profil absent, trop long ou de longueur différente des horodatages.')
        if not all(nombre_non_negatif(v) and v <= 1e7 for v in profil_kw):
            raise ValueError('Le canal mesuré doit contenir uniquement des puissances finies et positives ou nulles en kW.')
        dates = lire_fins_quarts(horodatages)
        debut_attendu = datetime.combine(debut, time(), AMSTERDAM).astimezone(timezone.utc)
        fin_attendue = datetime.combine(jour, time(), AMSTERDAM).astimezone(timezone.utc)
        if (dates[0].astimezone(timezone.utc) - timedelta(minutes=15) != debut_attendu
                or dates[-1].astimezone(timezone.utc) != fin_attendue):
            raise ValueError('Il faut les douze mois immédiatement précédant la date d’analyse, sans trou, avec fuseau explicite.')
    except (ValueError, OverflowError) as erreur:
        manques.append('profil : ' + str(erreur))
    if manques:
        return resultat
    pointe = max(profil_kw)
    puissance = Decimal(str(gtv))
    maximum = Decimal(str(pointe))
    seuil = 10000 if reseau == 'HT' and tension >= 110 else 1000
    relatif = maximum <= puissance / 2
    absolu = puissance - maximum >= seuil
    resultat['mesures'] = {
        'gtv_kw': gtv, 'pointe_12_mois_kw': pointe,
        'inutilise_kw': float(max(Decimal(0), puissance - maximum)),
        'seuil_absolu_kw': seuil, 'seuil_relatif_atteint': relatif,
        'seuil_absolu_atteint': absolu, 'nombre_quarts': len(profil_kw),
        'sha256': hashlib.sha256(json.dumps([profil_kw, horodatages], default=str,
                                          allow_nan=False, separators=(',', ':')).encode()).hexdigest(),
    }
    if relatif or absolu:
        resultat.update(statut='risque_conditionnel', constat='Le seuil de sous-utilisation est atteint. Une réduction peut être examinée par le gestionnaire après concertation et examen des besoins justifiés.')
    else:
        resultat.update(statut='seuil_non_atteint', constat='Aucun des deux seuils de sous-utilisation n’est atteint sur la période fournie. Refaire le calcul si les mesures ou le contrat changent.')
    return resultat


def _defense(fiche):
    pieces = [
        ('contrat', 'ATO actuel et historique du GTV dans le sens étudié', fiche.get('source_gtv')),
        ('congestion', 'Publication du gestionnaire identifiant la zone et le sens de congestion', fiche.get('source_congestion')),
        ('mesures', 'Courbe des douze mois précédents et maxima disponibles sur vingt-quatre mois', fiche.get('source_mesures')),
        ('notification', 'Notification écrite, compte rendu et observations du site', fiche.get('source_notification')),
    ]
    defense = {'pieces': [{'id': identifiant, 'objet': objet,
                           'reference': valeur if _texte(valeur) else None,
                           'statut': 'reference_declaree' if _texte(valeur) else 'a_fournir'}
                          for identifiant, objet, valeur in pieces],
               'besoins_futurs': [], 'exceptions_a_examiner': [],
               'pointe_24_mois': None,
               'consigne': 'Décrire chaque besoin en kW avec date de mise en service, planning, commande ou devis et justification. Une affirmation seule ne démontre pas le besoin.'}
    maximum = fiche.get('pointe_24_mois_kw')
    reference = fiche.get('source_pointe_24_mois')
    if nombre_non_negatif(maximum) and _texte(reference):
        defense['pointe_24_mois'] = {'kw': maximum, 'reference': reference, 'statut': 'declaree_a_revoir'}
    else:
        defense['pieces'].append({'id': 'pointe_24_mois', 'objet': 'Maximum disponible sur vingt-quatre mois et sa pièce de calcul', 'reference': None, 'statut': 'a_fournir'})
    projets = fiche.get('besoins_futurs')
    if projets is not None and not isinstance(projets, list):
        raise ValueError('besoins_futurs : liste d’objets attendue.')
    if isinstance(projets, list):
        for projet in projets:
            if not isinstance(projet, dict):
                raise ValueError('Chaque besoin futur doit être un objet avec description, puissance, date et référence.')
            complet = all(_texte(projet.get(c)) for c in ('description', 'date_mise_service', 'reference'))
            complet = complet and nombre_non_negatif(projet.get('puissance_kw'))
            try:
                _date(projet.get('date_mise_service'))
            except (ValueError, OverflowError):
                complet = False
            # Une erreur de saisie doit rester visible sans transmettre NaN/Inf
            # au JSON du dossier ou fabriquer une puissance à partir du texte.
            entree = {c: projet.get(c) if _texte(projet.get(c)) else None
                      for c in ('description', 'date_mise_service', 'reference')}
            entree['puissance_kw'] = projet.get('puissance_kw') if nombre_non_negatif(projet.get('puissance_kw')) else None
            defense['besoins_futurs'].append(entree | {'statut': 'a_examiner' if complet else 'incomplet'})
    exceptions = fiche.get('justificatifs_exception')
    if exceptions is not None and (not isinstance(exceptions, list) or not all(_texte(p) for p in exceptions)):
        raise ValueError('justificatifs_exception : liste de références textuelles non vides attendue.')
    if isinstance(exceptions, list):
        defense['exceptions_a_examiner'] = [p for p in exceptions if _texte(p)]
    defense['regle_exceptions'] = 'Article 7.13(7) : documenter le risque pour un processus vital, le fonctionnement direct d’un service social concerné, ou une charge imprévisible indispensable à la sécurité technique. Aucune exemption automatique par étiquette d’activité.'
    return defense


def rapport(resultat):
    """Dossier de travail en français, avec bordereau des pièces et étapes à suivre."""
    texte = texte_markdown
    statuts = {'indetermine': 'Données insuffisantes pour conclure',
               'hors_champ_declare': 'Une condition du champ est déclarée absente',
               'risque_conditionnel': 'Risque conditionnel à examiner avec le gestionnaire',
               'seuil_non_atteint': 'Seuil de sous-utilisation non atteint sur la période'}
    lignes = ['# GOTORK : alerte et dossier de concertation', '',
              f"Site : {texte(resultat.get('site') or 'à renseigner')}", '',
              f"Statut : {statuts.get(resultat['statut'], resultat['statut'])}", '', resultat['constat'], '',
              'Décision ACM du 16 avril 2024, entrée en vigueur le 26 avril 2024.',
              'Ce dossier ne prononce aucune perte de droit ni nouveau GTV. Les pièces citées restent à relire.', '']
    periode = resultat.get('periode_attendue')
    if periode:
        titre = 'Période mesurée' if resultat['mesures'] else 'Période nécessaire au calcul'
        lignes += [f"{titre} : du {periode['debut_inclus']} inclus au {periode['fin_exclue']} exclu, {periode['fuseau']}.", '']
    if resultat['mesures']:
        libelles = {'gtv_kw': 'GTV déclaré (kW)', 'pointe_12_mois_kw': 'Pointe sur douze mois (kW)',
                    'inutilise_kw': 'Puissance inutilisée (kW)', 'seuil_absolu_kw': 'Seuil absolu applicable (kW)',
                    'seuil_relatif_atteint': 'Utilisation au plus égale à 50 % du GTV',
                    'seuil_absolu_atteint': 'Seuil absolu atteint', 'nombre_quarts': 'Quarts d’heure mesurés',
                    'sha256': 'Empreinte SHA-256 des mesures et horodatages'}
        lignes += ['## Mesures', '', '| Indicateur | Valeur |', '| --- | --- |']
        for cle, valeur in resultat['mesures'].items():
            valeur = ('Oui' if valeur else 'Non') if type(valeur) is bool else valeur
            lignes.append(f'| {libelles.get(cle, cle)} | {texte(valeur)} |')
    if resultat.get('concertation_avant_date_indicative'):
        lignes += ['', 'Concertation, date indicative : ' + resultat['concertation_avant_date_indicative'], resultat['note_delai']]
    if resultat['manques']:
        lignes += ['', '## Données à compléter', ''] + ['- ' + texte(m) for m in resultat['manques']]
    lignes += ['', '## Procédure', ''] + ['- ' + p for p in resultat['procedure']]
    defense = resultat['dossier_defense']
    lignes += ['', '## Pièces et besoins à défendre', '', defense['consigne'], '']
    for piece in defense['pieces']:
        lignes.append(f"- {texte(piece['objet'])} : {texte(piece['reference'] or 'à fournir')}.")
    if defense['pointe_24_mois']:
        pointe = defense['pointe_24_mois']
        lignes += ['', f"Pointe déclarée sur vingt-quatre mois : {texte(pointe['kw'])} kW. Pièce : {texte(pointe['reference'])}. Valeur à relire."]
    for projet in defense['besoins_futurs']:
        puissance = 'à préciser' if projet.get('puissance_kw') is None else f"{texte(projet['puissance_kw'])} kW"
        lignes.append(f"- {texte(projet.get('description') or 'Besoin à décrire')}. Puissance : {puissance} ; mise en service : {texte(projet.get('date_mise_service') or 'à préciser')} ; pièce : {texte(projet.get('reference') or 'à fournir')}. "
                      + ('À examiner avec le gestionnaire.' if projet['statut'] == 'a_examiner' else 'Justification incomplète.'))
    if not defense['besoins_futurs']:
        lignes.append('- Besoins futurs : aucun justificatif fourni.')
    lignes += ['', defense['regle_exceptions'], '']
    lignes += ['- ' + texte(p) for p in defense['exceptions_a_examiner']]
    lignes += ['', '## Sources', ''] + [f'- [Source officielle]({url})' for url in resultat['sources']]
    return '\n'.join(lignes) + '\n'
