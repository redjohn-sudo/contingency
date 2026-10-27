"""Fins de quarts explicites : aucun fuseau deviné, continuité en UTC."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

AMSTERDAM = ZoneInfo('Europe/Amsterdam')
QUART = timedelta(minutes=15)


def lire_fin_quart(valeur):
    """Renvoie l'instant avec son décalage d'origine, après validation."""
    try:
        if isinstance(valeur, datetime):
            instant = valeur
        elif isinstance(valeur, str):
            instant = datetime.fromisoformat(valeur.strip().replace('Z', '+00:00'))
        else:
            raise ValueError('Horodatage attendu sous forme de date et heure ISO.')
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError('Horodatage sans fuseau : préciser le décalage UTC ou utiliser l’import configuré.')
        utc = instant.astimezone(timezone.utc)
        if utc.minute % 15 or utc.second or utc.microsecond:
            raise ValueError('Horodatage hors d’un quart d’heure exact.')
        return instant
    except (TypeError, OverflowError) as erreur:
        raise ValueError('Horodatage hors de la plage de dates prise en charge.') from erreur


class ErreurDonnees(ValueError):
    """Refus motivé : le message dit quoi et où ; constats garde chaque anomalie (code, lignes, paramètres) pour la
    page qualité des données."""

    def __init__(self, message, constats):
        super().__init__(message)
        self.constats = constats


def anomalies_pas(instants, lignes):
    """Retours en arrière dans l'ordre du fichier, puis doublons et vrais trous parmi les instants triés (UTC), chacun
    avec ses lignes. Un trou n'est annoncé que si l'instant manque dans tout le fichier : deux lignes interverties sont
    un défaut d'ordre, pas une absence (revue d'Astra de 393def5, P2-A)."""
    lignes = list(lignes)
    constats = [{'code': 'ANOMALIE_ORDRE', 'gravite': 'bloquant', 'lignes': [la, lb],
                 'parametres': {'de': a.isoformat(), 'vers': b.isoformat()}}
                for (a, la), (b, lb) in zip(zip(instants, lignes), zip(instants[1:], lignes[1:])) if b < a]
    tries = sorted(zip(instants, lignes))
    for (a, la), (b, lb) in zip(tries, tries[1:]):
        ecart = round((b - a).total_seconds())
        if ecart == 0:
            constats.append({'code': 'ANOMALIE_DOUBLON', 'gravite': 'bloquant', 'lignes': [la, lb],
                             'parametres': {'instant': a.isoformat()}})
        elif ecart > 900:
            constats.append({'code': 'ANOMALIE_TROU', 'gravite': 'bloquant', 'lignes': [la, lb],
                             'parametres': {'apres': a.isoformat(), 'avant': b.isoformat(), 'quarts': ecart // 900 - 1}})
    return sorted(constats, key=lambda c: min(c['lignes']))


def _pluriel(n, mot, pluriel=None):
    return f"{n} {mot if n == 1 else pluriel or mot + 's'}"


def resume_anomalies(constats):
    """Texte provisoire en français, en attendant le catalogue FR/NL d'Astra (messages_fiabilite)."""
    trous = [c for c in constats if c['code'] == 'ANOMALIE_TROU']
    doublons = sum(c['code'] == 'ANOMALIE_DOUBLON' for c in constats)
    retours = sum(c['code'] == 'ANOMALIE_ORDRE' for c in constats)
    parties = ([f"{_pluriel(len(trous), 'trou')} ({sum(c['parametres']['quarts'] for c in trous)} quarts manquants au total)"]
               if trous else []) + ([_pluriel(doublons, 'doublon')] if doublons else []) + (
               [_pluriel(retours, 'retour en arrière', 'retours en arrière')] if retours else [])
    cas = []
    for c in constats[:3]:
        la, lb = c['lignes']
        p = c['parametres']
        cas.append(f"trou de {p['quarts']} quarts entre les lignes {la} et {lb}, après {p['apres']}" if c['code'] == 'ANOMALIE_TROU'
                   else f"doublon aux lignes {la} et {lb} ({p['instant']})" if c['code'] == 'ANOMALIE_DOUBLON'
                   else f"retour en arrière entre les lignes {la} et {lb} ({p['de']} puis {p['vers']})")
    reste = f" ; {_pluriel(len(constats) - 3, 'autre cas', 'autres cas')}" if len(constats) > 3 else ''
    conseil = ("corriger l'export ou fournir la période manquante." if trous
               else "corriger l'ordre ou les doublons de l'export.")
    return (f"Trouvé : {', '.join(parties)}. {'Premiers cas' if len(constats) > 1 else 'Cas'} : {' ; '.join(cas)}{reste}. "
            f"Rien n'a été comblé ni supprimé : {conseil}")


def refuser_si_irregulier(instants, lignes, entete='Le profil doit avoir un pas régulier de 15 minutes, sans trou ni doublon, dans l’ordre UTC.'):
    constats = anomalies_pas(instants, lignes)
    if constats:
        raise ErreurDonnees(f'{entete} {resume_anomalies(constats)}', constats)


def lire_fins_quarts(valeurs, lignes=None):
    """Refuse trous, doublons et inversions, même au changement d'heure, en les listant tous avec leurs lignes
    (lignes : numéros de ligne physiques dans le fichier ; à défaut, rang de chaque valeur)."""
    dates = []
    for numero, valeur in enumerate(valeurs, 1):
        try:
            dates.append(lire_fin_quart(valeur))
        except ValueError as erreur:
            raise ValueError(f'Horodatage {numero} invalide : {erreur}') from erreur
    refuser_si_irregulier([d.astimezone(timezone.utc) for d in dates], lignes if lignes is not None else range(1, len(dates) + 1))
    return dates


def quarts_du_jour(jour, zone=AMSTERDAM, pas_minutes=15):
    """Quarts d'une journée civile : 92 au passage à l'heure d'été, 100 au retour, 96 sinon (revue d'Astra de
    fb1b673, P2-J : un jour n'est dit « changement d'heure » que s'il a exactement ce nombre). Avec ``pas_minutes``,
    intervalles natifs de ce pas (France : 5 à 60 minutes)."""
    debut = datetime(jour.year, jour.month, jour.day, tzinfo=zone)
    fin = datetime.combine(jour + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    return round((fin.astimezone(timezone.utc) - debut.astimezone(timezone.utc)).total_seconds() / (60 * pas_minutes))


def controle_import(puissances, horodatages, unite, zone=AMSTERDAM):
    """FB5 : ce qui fait voir une erreur avant usage, sans rien choisir à la place de l'utilisateur. Jours de contrôle
    (premier jour, un jour d'été, jours particuliers qualifiés par le calendrier) et pointe de chaque mois sous l'unité
    déclarée ET sous l'autre unité possible : un facteur 4 se voit avant l'import (critère 2 de Fable)."""
    par_jour, pointes = Counter(), {}
    for puissance, fin in zip(puissances, horodatages):
        debut = (lire_fin_quart(fin) - QUART).astimezone(zone)
        par_jour[debut.date()] += 1
        mois = debut.strftime('%Y-%m')
        pointes[mois] = max(pointes.get(mois, puissance), puissance)
    jours = [{'jour': j.isoformat(), 'quarts': n, 'attendus': quarts_du_jour(j, zone),
              'motif': ('ete' if n == quarts_du_jour(j, zone) == 92 else 'hiver' if n == quarts_du_jour(j, zone) == 100
                        else 'partiel')}
             for j, n in sorted(par_jour.items()) if not n == quarts_du_jour(j, zone) == 96]
    premier = min(par_jour)
    ete = min((j for j in par_jour if j.month == 7), default=None)
    autre, facteur = ('kw', 0.25) if unite == 'kwh_par_quart' else ('kwh_par_quart', 4)
    return {'jours': jours, 'reference': {'premier': {'jour': premier.isoformat(), 'quarts': par_jour[premier]},
                                          'ete': {'jour': ete.isoformat(), 'quarts': par_jour[ete]} if ete else None},
            'unite_declaree': unite, 'autre_unite': autre,
            'pointes_mensuelles': [{'mois': m, 'pointe_kw': round(v, 3), 'pointe_kw_autre_unite': round(v * facteur, 3)}
                                   for m, v in sorted(pointes.items())]}
