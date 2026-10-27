"""Maximum de puissance après pondération de CHAQUE quart, annexe 5 de 2026.

Source : Tarievencode 2026, Stcrt 4090, article 3.9(5), annexe 5.
Le calendrier férié et le régime du raccordement restent des pièces à fournir.
Ce module n'extrapole pas de consommation et ne calcule aucun tarif en euros.
"""
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from regles_contrats_nl import date_iso, SOURCES

ZONE = ZoneInfo('Europe/Amsterdam')
# Dixièmes entiers, colonnes officielles uur 1 à uur 24.
HIVER = (7,) * 6 + (8, 9) + (10,) * 14 + (9, 8)
INTERSAISON = (7,) * 6 + (8, 9) + (9,) * 9 + (10,) * 4 + (9, 8, 8)
ETE = (7, 7, 6, 6, 6, 6, 7, 8, 8, 7, 6, 6, 6, 6, 6, 6, 7, 8, 8, 8, 8, 8, 8, 8)
FACTEURS_MOIS = {mois: HIVER if mois in (1, 2, 12) else INTERSAISON if mois in (3, 10, 11) else ETE
                for mois in range(1, 13)}
REGIMES = ('transmission_terrestre', 'mer_art_3_8_2_f')


def verifier_calendrier(calendrier, resume, site, categorie, annee_tarifaire):
    """Séparer pièces absentes et saisies incohérentes, sans valider les sources."""
    if not isinstance(calendrier, dict):
        raise ValueError('Calendrier de pondération : objet attendu.')
    manque = []
    if calendrier.get('version_grille') != 'stcrt-2026-4090-annexe5' or calendrier.get('grille_verifiee') is not True:
        manque.append('Pondération : confirmer que la grille de l’annexe 5 publiée en février 2026 s’applique au dossier.')
    if calendrier.get('sha256_profil') != resume['sha256']:
        raise ValueError('Le calendrier de pondération doit correspondre à l’empreinte du profil.')
    if type(calendrier.get('annee_mesuree')) is not int or calendrier['annee_mesuree'] != resume['annee_mesuree']:
        raise ValueError('L’année du calendrier de pondération doit être celle du profil mesuré.')
    if annee_tarifaire != 2026:
        manque.append('Pondération : grille publiée pour 2026 seulement ; vérifier la version applicable aux autres années tarifaires.')
    if site.get('gestionnaire') != 'tennet' or site.get('reseau') != 'transmission':
        manque.append('Pondération : cette grille est prise en charge pour le réseau de transmission TenneT seulement ; justifier le régime des autres raccordements.')
    regime = calendrier.get('regime')
    if regime not in REGIMES:
        manque.append('Pondération : confirmer le régime terrestre ou le régime en mer de l’article 3.8(2)f.')
    if regime == 'mer_art_3_8_2_f' and categorie != 'a':
        manque.append('Pondération en mer : le régime de l’article 3.8(2)f exige la catégorie a.')
    if calendrier.get('convention_heure') != 'debut_quart_local':
        manque.append('Pondération : confirmer que chaque heure tarifaire correspond au début local du quart en Europe/Amsterdam.')
    feries = calendrier.get('jours_feries')
    if not isinstance(feries, list) or len(feries) > 366:
        raise ValueError('Pondération : liste explicite de jours fériés requise.')
    dates = [date_iso(jour) for jour in feries]
    if any(jour.year != resume['annee_mesuree'] for jour in dates) or len(set(dates)) != len(dates):
        raise ValueError('Pondération : jours fériés uniques dans l’année du profil requis.')
    if regime == 'transmission_terrestre' and calendrier.get('jours_feries_exhaustifs') is not True:
        manque.append('Pondération : confirmer la liste exhaustive des jours fériés tarifaires de l’année mesurée.')
    return manque


def facteur(instant, regime, feries):
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('Pondération : début du quart avec fuseau requis.')
    local = instant.astimezone(ZONE)
    if local.minute % 15 or local.second or local.microsecond:
        raise ValueError('Pondération : début aligné sur un quart d’heure requis.')
    if regime not in REGIMES:
        raise ValueError('Régime de pondération inconnu.')
    if regime == 'mer_art_3_8_2_f':
        return .9
    ligne = ETE if local.weekday() >= 5 or local.date().isoformat() in feries else FACTEURS_MOIS[local.month]
    return ligne[local.hour] / 10


def maxima_mensuels_ponderes(valeurs, debuts, calendrier):
    """Entrées annuelles et calendrier préalablement contrôlés par le comparateur.

    On conserve le premier quart décisif en cas d'égalité. Les valeurs brutes
    restent inchangées ; un maximum pondéré n'est jamais une limite de GTV.
    """
    if not isinstance(valeurs, list) or not isinstance(debuts, list) or not valeurs or len(valeurs) != len(debuts):
        raise ValueError('Pondération : puissances et débuts de même longueur requis.')
    feries = set(calendrier['jours_feries'])
    maxima = {}
    for position, (puissance, instant) in enumerate(zip(valeurs, debuts)):
        if type(puissance) not in (int, float) or not math.isfinite(puissance) or puissance < 0:
            raise ValueError('Pondération : puissance finie positive ou nulle requise.')
        coefficient = facteur(instant, calendrier['regime'], feries)
        local = instant.astimezone(ZONE)
        if local.year != calendrier['annee_mesuree']:
            raise ValueError('Pondération : quart hors de l’année du calendrier.')
        mois = str(local.month)
        ponderee = puissance * coefficient
        if mois not in maxima or ponderee > maxima[mois]['pointe_ponderee_kw']:
            maxima[mois] = {'pointe_ponderee_kw': ponderee, 'puissance_brute_kw': puissance,
                            'facteur': coefficient, 'debut_local': local.isoformat(),
                            'position_quart': position}
    return {'mensuel': maxima, 'somme_maxima_kw': math.fsum(m['pointe_ponderee_kw'] for m in maxima.values()),
            'regime': calendrier['regime'], 'annee_calendrier': calendrier['annee_mesuree'],
            'sha256_profil': calendrier['sha256_profil'], 'source_grille': SOURCES['tarievencode']}
