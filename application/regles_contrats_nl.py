"""Repères publics NL relus le 27/09/2026, sans présumer d'une offre au site.

Les dates calculées sont des bornes réglementaires, jamais une acceptation du
gestionnaire. La tension ne permet pas de déduire le gestionnaire ou le tarif.
"""
from datetime import date
import math

SOURCES = {
    'code': 'https://zoek.officielebekendmakingen.nl/stcrt-2026-4089.html',
    'tarievencode': 'https://zoek.officielebekendmakingen.nl/stcrt-2026-4090.html',
    'liander': 'https://www.liander.nl/grootzakelijk/energietransitie/transportovereenkomsten/blokstroom',
    'enexis': 'https://www.enexis.nl/zakelijk/netcapaciteit/flexibiliteitsoplossingen/blokstroom',
    'enexis_atr': 'https://www.enexis.nl/zakelijk/netcapaciteit/transportcapaciteit/alternatieve-transportrechten',
    'stedin': 'https://www.stedin.net/zakelijk/energietransitie/beschikbare-netcapaciteit/flexoplossingen/transportrechten',
    'cbc': 'https://edsn-cms.files.svdcdn.com/production/Congestiemanagement/20241003-Capaciteitsbeperkingscontract-V3.pdf',
    'northc': 'https://www.acm.nl/nl/publicaties/uitspraak-cbb-northc-heeft-geen-recht-op-verhoging-van-transportvermogen-elektriciteit',
}
DATE_RELECTURE = '2026-09-27'
RISQUE_NORTHC = (
    'Baisser le GTV peut réduire le droit ferme disponible. Le rétablissement '
    'ultérieur peut être refusé en congestion. NorthC, CBb du 23 juin 2026 : '
    'la dernière valeur déclarée compte. Une économie de tarif ne conserve '
    'pas à elle seule la capacité abandonnée.'
)


def date_iso(valeur):
    if not isinstance(valeur, str) or len(valeur) != 10:
        raise ValueError('Date attendue au format AAAA-MM-JJ.')
    try:
        resultat = date.fromisoformat(valeur)
    except ValueError as erreur:
        raise ValueError('Date civile invalide.') from erreur
    if resultat.isoformat() != valeur or not 1900 <= resultat.year <= 9997:
        raise ValueError('Date civile hors plage (1900 à 9997).')
    return resultat


def mois_suivant(jour):
    return date(jour.year + (jour.month == 12), jour.month % 12 + 1, 1)


def anniversaire(jour):
    # Un 29 février atteint douze mois calendaires le dernier jour de février.
    try:
        return jour.replace(year=jour.year + 1)
    except ValueError:
        return jour.replace(year=jour.year + 1, day=28)


def premiere_date_gtv(demande, categorie_code, *, sens='baisse',
                      derniere_hausse=None, historique_12_mois_confirme=None,
                      exception_acceptee=None, changement_deja_effectue=None):
    """Systeemcode publiée en février 2026, art. 7.25 et 7.26.

    categorie_code : lettre a..f de la Tarievencode 2026, art. 3.8(1),
    à relever sur les documents du raccordement, pas à déduire de la pointe.
    L'exception signifie motifs raisonnables acceptés par le gestionnaire.
    """
    jour = date_iso(demande)
    if sens not in ('baisse', 'hausse'):
        raise ValueError('Sens attendu : baisse ou hausse.')
    for valeur in (historique_12_mois_confirme, exception_acceptee, changement_deja_effectue):
        if valeur is not None and type(valeur) is not bool:
            raise ValueError('Confirmation attendue : booléen ou null.')
    hausse = date_iso(derniere_hausse) if derniere_hausse is not None else None
    if hausse and hausse > jour:
        raise ValueError('La dernière hausse ne peut pas suivre la demande.')
    manque, conditions = [], ['Date effective à confirmer par le gestionnaire.']
    if jour < date(2026, 2, 21):
        manque.append('Cette publication entre en vigueur le 21 février 2026 ; rechercher les règles applicables à la date antérieure.')
    borne = mois_suivant(jour)
    if categorie_code in ('a', 'b', 'c', 'd'):
        if exception_acceptee is not True:
            manque.append('Motifs raisonnables de changement acceptés par le gestionnaire.')
        if changement_deja_effectue is not False:
            manque.append('Confirmer qu’aucun changement sur demande n’a déjà été effectué cette année.')
        conditions.append('Article 7.25 : au maximum une modification sur demande par an, sur motifs raisonnables.')
    elif categorie_code in ('e', 'f'):
        if sens == 'baisse' and exception_acceptee is not True:
            if hausse:
                borne = max(borne, anniversaire(hausse))
            elif historique_12_mois_confirme is not True:
                manque.append('Date de dernière hausse ou absence de hausse depuis douze mois confirmée.')
        conditions.append('Article 7.26 : une nouvelle pointe dans les douze mois suivant la baisse peut entraîner une correction rétroactive.')
    else:
        manque.append('Borne nationale non établie pour cette catégorie : a à d = EHS, HS, TS, HS+TS/MS ; e/f = MS et MS/LS. Pour LS (g/h), vérifier les conditions du gestionnaire.')
    if sens == 'hausse':
        conditions.append('Capacité réseau disponible et accord du gestionnaire requis, aucune hausse automatique en congestion.')
    return {'borne_reglementaire': None if manque else borne.isoformat(),
            'date_confirmee': None, 'manquants': manque, 'conditions': conditions,
            'source': SOURCES['code'], 'version_source': 'Publication du 20 février 2026, articles 7.25 et 7.26',
            'limite_source': 'La consolidation au 27 septembre n’a pas été accessible ; vérifier les modifications applicables au dossier.'}


def admissibilite(produit, gestionnaire, *, reseau=None, tension_kv=None,
                  grande_connexion=None, region=None, remplacement=False,
                  congestion=None):
    """Filtre public conservateur. Aucun résultat ne vaut offre au raccordement."""
    if produit not in ('fixe', 'cbc', 'tijdsblok', 'volledig_variabel', 'tijdsduur'):
        raise ValueError('Produit contractuel inconnu.')
    if not isinstance(gestionnaire, str):
        raise ValueError('Gestionnaire attendu sous forme de texte.')
    operateur = gestionnaire.strip().lower()
    if reseau not in (None, 'distribution', 'transmission'):
        raise ValueError('Réseau attendu : distribution ou transmission.')
    if tension_kv is not None and (type(tension_kv) not in (int, float)
            or not 0 < tension_kv <= 1000 or not math.isfinite(tension_kv)):
        raise ValueError('Tension invalide, unité kV.')
    for valeur in (grande_connexion, congestion):
        if valeur is not None and type(valeur) is not bool:
            raise ValueError('Confirmation attendue : booléen ou null.')
    if type(remplacement) is not bool:
        raise ValueError('Remplacement attendu sous forme de booléen.')
    manque, refus, remarques = [], [], []
    sources = [SOURCES['code']]
    if operateur not in ('liander', 'enexis', 'stedin', 'tennet'):
        manque.append('Offre et règles du gestionnaire non couvert par cette veille.')
    if tension_kv is None:
        manque.append('Tension de raccordement en kV, relevée sur l’ATO.')
    if reseau is None:
        manque.append('Nature du réseau de raccordement : distribution ou transmission.')
    if grande_connexion is None:
        manque.append('Statut de grande connexion à confirmer.')
    elif grande_connexion is False:
        refus.append('Ce comparateur traite les grandes connexions seulement.')
    if operateur == 'tennet' and reseau == 'distribution':
        refus.append('Gestionnaire TenneT incompatible avec un réseau déclaré de distribution.')
    if operateur in ('liander', 'enexis', 'stedin') and reseau == 'transmission':
        refus.append('Gestionnaire régional incompatible avec un réseau déclaré de transmission.')
    if produit == 'tijdsduur' and reseau == 'distribution':
        refus.append('Tijdsduur : réservé au réseau de transmission, article 7.6.')
    if produit == 'tijdsblok' and reseau == 'transmission':
        refus.append('Tijdsblok : grandes connexions de distribution, article 7.7.')
    if produit == 'tijdsblok' and operateur in ('liander', 'stedin', 'enexis'):
        sources.append(SOURCES[operateur])
        remarques.append('Offre publique actuelle : consommation entre 00:00 et 06:00, capacité locale et amont à confirmer.')
        if operateur == 'liander':
            if remplacement:
                refus.append('Liander n’autorise pas l’échange du GTV fixe contre Blokstroom sur la page actuelle.')
            if region not in ('Friesland', 'Noordoostpolder'):
                manque.append('Phase Liander publiée : Friesland et Noordoostpolder ; disponibilité ailleurs non établie.')
        elif operateur == 'stedin':
            if region != 'Zeeland':
                manque.append('Phase Stedin publiée : Zeeland ; disponibilité ailleurs non établie.')
            if remplacement:
                manque.append('Possibilité de remplacer le GTV fixe chez Stedin à vérifier dans l’offre.')
        else:
            remarques.append('Enexis permet l’échange total ou partiel du GTV fixe, sur demande acceptée.')
        remarques.append('Le prix de 25 % porte sur le terme kW contract du bloc de six heures, pas sur toute la facture.')
    if produit == 'volledig_variabel':
        if congestion is False:
            refus.append('Volledig variabel : grande connexion en zone de congestion, article 7.5.')
        elif congestion is None:
            manque.append('Zone de congestion pour le sens concerné à confirmer.')
        if operateur in ('stedin', 'enexis'):
            sources.append(SOURCES['stedin'] if operateur == 'stedin' else SOURCES['enexis_atr'])
            manque.append('Reststroom non disponible comme offre générale sur la page actuelle : offre individuelle indispensable.')
        remarques.append('Aucune capacité garantie ; un historique des allocations ne garantit pas celles de demain.')
    if produit == 'tijdsduur':
        remarques.append('85 % des heures de l’année selon le contrat et les restrictions du gestionnaire ; le client ne choisit pas ses meilleurs quarts.')
    if produit == 'cbc':
        sources.append(SOURCES['cbc'])
        remarques.append('CBC V3 : montant, périodes et date figurent dans l’annexe 1, qui prime. Un défaut peut annuler la rémunération du jour entier.')
    manque.append('Admissibilité individuelle, tension, catégorie et date à confirmer dans l’offre du gestionnaire.')
    return {'statut': 'incompatible' if refus else 'a_confirmer', 'refus': refus,
            'manquants': manque, 'remarques': remarques, 'sources': list(dict.fromkeys(sources)),
            'relecture': DATE_RELECTURE}
