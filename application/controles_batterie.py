"""Cohérence des caractéristiques déclarées d'une batterie, côté courant continu.

Aucune valeur de fabricant, fenêtre de charge ou dégradation n'est supposée.
Ces calculs contrôlent une fiche ; ils ne valident ni un matériel ni sa sécurité.
Sources et limites : docs/contraintes/CONTROLES-BATTERIE.md.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

SOURCE_CAPACITE = 'https://samrepo.nlr.gov/help/battery_dispatch_btm.html'
SOURCE_PUISSANCE = 'https://samrepo.nlr.gov/help/battery_storage_btm.html'

BESOINS_COMMUNS = {
    'batterie_nominale_dc_kwh': 'fiche fabricant : capacité nominale côté courant continu en kWh, avant réserve et vieillissement',
    'batterie_source': 'référence datée de la fiche fabricant et des conditions de fonctionnement retenues',
}
BESOINS_SOC = {
    **BESOINS_COMMUNS,
    'batterie_soc_min_pct': 'réglage du système de gestion : état de charge minimal en pourcentage de la capacité restante',
    'batterie_soc_max_pct': 'réglage du système de gestion : état de charge maximal en pourcentage de la capacité restante',
    'batterie_soh_pct': 'garantie ou mesure : capacité restante en pourcentage de la capacité nominale, à la date étudiée',
    'batterie_utile_dc_annoncee_kwh': 'devis ou étude : capacité exploitable annoncée en kWh côté courant continu, dans la même fenêtre',
}
BESOINS_PUISSANCE = {
    **BESOINS_COMMUNS,
    'batterie_c_rate_decharge_max': 'fiche fabricant : taux maximal continu de décharge en h^-1, rapporté à la capacité nominale DC',
    'batterie_puissance_dc_demandee_kw': 'étude : puissance de décharge demandée en kW côté courant continu, avant conversion',
}
BESOINS_ENGAGEMENTS = {
    **{cle: valeur for cle, valeur in BESOINS_SOC.items() if cle != 'batterie_utile_dc_annoncee_kwh'},
    'batterie_soc_instant_pct': 'état de charge à l’instant étudié, en pourcentage de la capacité restante',
    'batterie_instant_engagements': 'date et heure ISO avec décalage UTC auxquelles tous les engagements déclarés doivent pouvoir être tenus',
    'batterie_nature_etat': 'mesure ou hypothese, pour distinguer un état observé d’un scénario',
    'batterie_source_etat': 'référence datée de la mesure ou justification de l’hypothèse d’état de charge',
    'batterie_charge_max_dc_kw': 'puissance continue de charge disponible côté batterie à cet instant, en kW DC',
    'batterie_decharge_max_dc_kw': 'puissance continue de décharge disponible côté batterie à cet instant, en kW DC',
    'batterie_engagements_simultanes': 'liste complète des services simultanés : nom, source, puissances et énergies réservées en charge et en décharge, toutes côté DC ; zéro explicite si absent',
}
AXES_ENGAGEMENTS = ('puissance_decharge_dc_kw', 'puissance_charge_dc_kw',
                    'energie_decharge_dc_kwh', 'energie_charge_dc_kwh')


class DonneeInvalide(ValueError):
    def __init__(self, champ: str, raison: str):
        self.champ = champ
        super().__init__(raison)


def nombre(dossier: dict[str, Any], champ: str, *, minimum: float = 0,
           maximum: float | None = None, positif: bool = False) -> float:
    valeur = dossier.get(champ)
    # Les booléens ne sont pas des puissances, même si Python accepte float(True).
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float, str)):
        raise DonneeInvalide(champ, 'un nombre explicite est nécessaire')
    try:
        valeur = float(valeur)
    except (ValueError, OverflowError):
        raise DonneeInvalide(champ, 'nombre illisible') from None
    if (not math.isfinite(valeur) or valeur < minimum or positif and valeur == 0
            or maximum is not None and valeur > maximum):
        raise DonneeInvalide(champ, 'valeur hors domaine ou non finie')
    return valeur


def reference(dossier: dict[str, Any]) -> str:
    source = dossier.get('batterie_source')
    if not isinstance(source, str) or not source.strip():
        raise DonneeInvalide('batterie_source', 'référence documentaire absente')
    return source.strip()


def bloque(entete: dict[str, Any], besoins: dict[str, str], erreur: DonneeInvalide) -> dict[str, Any]:
    return {**entete, 'statut': 'bloque',
            'constat': f'Non évaluable : {erreur.champ}, {erreur}.',
            'manque': [{'champ': erreur.champ, 'ou_le_trouver': besoins[erreur.champ]}]}


def depasse(valeur: float, plafond: float) -> bool:
    # Tolérance numérique seulement, sans marge commerciale ou technique implicite.
    return valeur > plafond and not math.isclose(valeur, plafond, rel_tol=1e-9, abs_tol=1e-9)


def fenetre(dossier: dict[str, Any]) -> dict[str, float]:
    nominale = nombre(dossier, 'batterie_nominale_dc_kwh', positif=True)
    minimum = nombre(dossier, 'batterie_soc_min_pct', maximum=100)
    maximum = nombre(dossier, 'batterie_soc_max_pct', maximum=100)
    sante = nombre(dossier, 'batterie_soh_pct', maximum=100)
    if minimum >= maximum:
        raise DonneeInvalide('batterie_soc_max_pct', 'la borne supérieure doit dépasser la borne inférieure')
    return {'nominale_dc_kwh': nominale, 'soc_min_pct': minimum, 'soc_max_pct': maximum,
            'soh_pct': sante, 'exploitable_dc_kwh': nominale * ((maximum - minimum) / 100) * (sante / 100)}


def capacite_exploitable(dossier: dict[str, Any]) -> dict[str, Any]:
    entete = {'id': 'CTRL-BAT-SOC', 'titre': 'Capacité exploitable dans la fenêtre de charge',
              'contraintes': ['BAT-004'], 'source_methode': SOURCE_CAPACITE,
              'nature': 'controle_coherence', 'perimetre': 'courant_continu'}
    try:
        source = reference(dossier)
        valeurs = fenetre(dossier)
        annoncee = nombre(dossier, 'batterie_utile_dc_annoncee_kwh')
    except DonneeInvalide as erreur:
        return bloque(entete, BESOINS_SOC, erreur)
    exploitable = valeurs['exploitable_dc_kwh']
    valeurs.update(annoncee_dc_kwh=annoncee, surestimation_dc_kwh=max(0., annoncee - exploitable))
    return {**entete, 'statut': 'alerte' if depasse(annoncee, exploitable) else 'constat',
            'source_donnees': source, 'valeurs': valeurs,
            'constat': (f"{exploitable:.3f} kWh DC exploitables d'après la capacité nominale, "
                        f"la fenêtre de charge et l'état de santé déclarés ; {annoncee:.3f} kWh DC annoncés."),
            'consequence_contractuelle': (
                "Borne de cohérence à tension nominale. Les pertes de conversion, auxiliaires, "
                "température et état de charge initial ne sont pas simulés. Un résultat sans alerte "
                "ne garantit pas cette énergie au point de livraison.")}


def puissance_decharge(dossier: dict[str, Any]) -> dict[str, Any]:
    entete = {'id': 'CTRL-BAT-PUISSANCE', 'titre': 'Puissance demandée et taux de décharge',
              'contraintes': ['BAT-008'], 'source_methode': SOURCE_PUISSANCE,
              'nature': 'controle_coherence', 'perimetre': 'courant_continu'}
    try:
        source = reference(dossier)
        nominale = nombre(dossier, 'batterie_nominale_dc_kwh', positif=True)
        taux = nombre(dossier, 'batterie_c_rate_decharge_max', positif=True)
        demande = nombre(dossier, 'batterie_puissance_dc_demandee_kw')
        limite = nominale * taux
        if not math.isfinite(limite) or not math.isfinite(demande / nominale):
            raise DonneeInvalide('batterie_nominale_dc_kwh', 'échelle numérique incompatible avec le calcul')
    except DonneeInvalide as erreur:
        return bloque(entete, BESOINS_PUISSANCE, erreur)
    return {**entete, 'statut': 'alerte' if depasse(demande, limite) else 'constat',
            'source_donnees': source,
            'valeurs': {'nominale_dc_kwh': nominale, 'c_rate_max': taux,
                        'puissance_max_dc_kw': limite, 'demande_dc_kw': demande,
                        'c_rate_demande': demande / nominale, 'depassement_dc_kw': max(0., demande - limite)},
            'constat': (f"{demande:.3f} kW DC demandés pour une limite déclarée de {limite:.3f} kW DC "
                        f"({nominale:.3f} kWh nominaux × {taux:g} h^-1)."),
            'consequence_contractuelle': (
                "Comparaison avec le taux continu rapporté à la capacité nominale, selon la fiche citée. "
                "Les limites de l'onduleur, de température et de tension restent à vérifier. "
                "Cette puissance DC ne vaut pas une puissance garantie au réseau.")}


def engagements_simultanes(dossier: dict[str, Any]) -> dict[str, Any]:
    """Bilan de réserves à un instant déclaré, sans simulation de trajectoire."""
    entete = {'id': 'CTRL-BAT-ENGAGEMENTS', 'titre': 'Engagements simultanés de batterie',
              'contraintes': ['ECO-010'], 'nature': 'regle_conception_interne',
              'perimetre': 'courant_continu'}
    try:
        source = reference(dossier)
        valeurs = fenetre(dossier)
        soc = nombre(dossier, 'batterie_soc_instant_pct', maximum=100)
        if not valeurs['soc_min_pct'] <= soc <= valeurs['soc_max_pct']:
            raise DonneeInvalide('batterie_soc_instant_pct', 'état de charge hors de la fenêtre déclarée')
        instant = dossier.get('batterie_instant_engagements')
        try:
            date = datetime.fromisoformat(instant) if isinstance(instant, str) else None
            if date is None or date.tzinfo is None or date.utcoffset() is None:
                raise ValueError
        except ValueError:
            raise DonneeInvalide('batterie_instant_engagements', 'date ISO avec décalage UTC explicite nécessaire') from None
        nature = dossier.get('batterie_nature_etat')
        if nature not in ('mesure', 'hypothese'):
            raise DonneeInvalide('batterie_nature_etat', 'déclarer mesure ou hypothese')
        source_etat = dossier.get('batterie_source_etat')
        if not isinstance(source_etat, str) or not source_etat.strip():
            raise DonneeInvalide('batterie_source_etat', 'origine de l’état de charge absente')
        restante = valeurs['nominale_dc_kwh'] * (valeurs['soh_pct'] / 100)
        plafonds = {
            'puissance_decharge_dc_kw': nombre(dossier, 'batterie_decharge_max_dc_kw'),
            'puissance_charge_dc_kw': nombre(dossier, 'batterie_charge_max_dc_kw'),
            'energie_decharge_dc_kwh': restante * ((soc - valeurs['soc_min_pct']) / 100),
            'energie_charge_dc_kwh': restante * ((valeurs['soc_max_pct'] - soc) / 100),
        }
        liste = dossier.get('batterie_engagements_simultanes')
        if not isinstance(liste, list) or not 1 <= len(liste) <= 100:
            raise DonneeInvalide('batterie_engagements_simultanes', 'déclarer entre 1 et 100 services, sans valeur implicite')
        noms, services = set(), []
        for position, service in enumerate(liste, 1):
            if not isinstance(service, dict):
                raise DonneeInvalide('batterie_engagements_simultanes', f'service {position} illisible')
            nom, origine = service.get('nom'), service.get('source')
            if (not isinstance(nom, str) or not nom.strip() or nom.strip() in noms
                    or not isinstance(origine, str) or not origine.strip()):
                raise DonneeInvalide('batterie_engagements_simultanes', f'service {position} : nom distinct et source obligatoires')
            noms.add(nom.strip())
            try:
                chiffres = {axe: nombre(service, axe) for axe in AXES_ENGAGEMENTS}
            except DonneeInvalide as erreur:
                raise DonneeInvalide('batterie_engagements_simultanes', f'service {position}, {erreur.champ} : {erreur}') from None
            services.append({'nom': nom.strip(), 'source': origine.strip(), **chiffres})
        try:
            totaux = {axe: math.fsum(service[axe] for service in services) for axe in AXES_ENGAGEMENTS}
        except OverflowError:
            raise DonneeInvalide('batterie_engagements_simultanes', 'somme hors domaine numérique') from None
        if any(not math.isfinite(v) for v in [*totaux.values(), *plafonds.values()]):
            raise DonneeInvalide('batterie_engagements_simultanes', 'échelle numérique incompatible avec le calcul')
    except DonneeInvalide as erreur:
        return bloque(entete, BESOINS_ENGAGEMENTS, erreur)
    deficits = {axe: max(0., totaux[axe] - plafonds[axe]) for axe in AXES_ENGAGEMENTS}
    violes = [axe for axe in AXES_ENGAGEMENTS if depasse(totaux[axe], plafonds[axe])]
    return {**entete, 'statut': 'alerte' if violes else 'constat',
            'source_donnees': source + ' ; ' + source_etat.strip(),
            'valeurs': {**valeurs, 'soc_instant_pct': soc, 'instant': date.isoformat(), 'nature_etat': nature,
                        'nombre_services': len(services), 'services': services, 'engage': totaux,
                        'disponible': plafonds, 'deficits': deficits, 'axes_depasses': violes},
            'constat': (
                f"À {date.isoformat()}, {len(services)} services simultanés déclarés ({nature}). "
                f"Décharge : {totaux['puissance_decharge_dc_kw']:.3f}/{plafonds['puissance_decharge_dc_kw']:.3f} kW DC "
                f"et {totaux['energie_decharge_dc_kwh']:.3f}/{plafonds['energie_decharge_dc_kwh']:.3f} kWh DC réservés/disponibles. "
                f"Charge : {totaux['puissance_charge_dc_kw']:.3f}/{plafonds['puissance_charge_dc_kw']:.3f} kW DC "
                f"et {totaux['energie_charge_dc_kwh']:.3f}/{plafonds['energie_charge_dc_kwh']:.3f} kWh DC réservés/disponibles."),
            'consequence_contractuelle': (
                "Règle interne de cohérence, sans portée juridique. Les engagements de chaque sens sont additionnés "
                "sans compensation entre charge et décharge. L’instant, les réserves et leur simultanéité sont déclarés. "
                "Aucune trajectoire de charge, stratégie de recharge, activation réelle, conversion AC ou recette annuelle "
                "n’est validée. Répéter ce bilan à chaque instant critique ; une liste incomplète peut masquer un conflit.")}
