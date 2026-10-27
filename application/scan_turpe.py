"""Scan France : dépassements de puissance souscrite (TURPE 7), redimensionnement et batterie, sur la courbe de charge.

Même plan que le scan de flexibilité néerlandais (scan_flex.py) : profil mesuré, situation actuelle, mesures chiffrées
avec les mêmes grandeurs, quarts d'heure qui décident, niveau de confiance, recommandation conditionnelle. Chaque
grandeur porte sa nature : mesure, simule, tarif (règle ou coefficient publié), declare (fiche), hypothese, a_chiffrer,
a_completer. Les règles et coefficients viennent de turpe.py (sources dans docs/france/TURPE-REGLES.md).

Fiche (JSON, tous les champs facultatifs sauf domaine) :
  identité         nom, adresse, secteur, exemple (booléen), source_profil, licence_profil
  raccordement     domaine (HTA ou BT36), option (cu_pointe_fixe, lu_pointe_fixe, cu_pointe_mobile, lu_pointe_mobile ; cu, lu),
                   puissances_souscrites {pointe, hph, hch, hpb, hcb} en kW (HTA) ou {hph, hch, hpb, hcb} en kVA (BT > 36),
                   puissance_raccordement_kw, facteur_puissance (cos φ, BT > 36 seulement), grille (« 2026-08 » par défaut)
  calendrier       heures_creuses [[22, 6]], pointe_fixe_plages [[9, 11], [18, 20]], saison_haute_mois, pointe_mobile_jours [dates ISO]
  facture          cmdps_facturee_eur {« AAAA-MM » : montant} pour confronter le calcul à la facture
  scan             plafond_cible_kw, hypotheses {heures_ecretees, rendement_aller_retour, profondeur_decharge,
                   puissance_sur_capacite_max, prix_batterie_eur_kwh}, tirages_confiance (100 par défaut, 0 pour sauter)

Usage : python application/scan_turpe.py profil.csv fiche.json dossier_sortie/
"""
from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import dimensionnement_batterie as db  # noqa: E402
import profil_france as pf  # noqa: E402
import turpe  # noqa: E402

VERSION = "scan-turpe-1"
NATURES = {"mesure", "lu", "simule", "tarif", "declare", "hypothese", "a_chiffrer", "a_completer"}  # lu : valeur du profil dont la qualité n'est pas documentée
TIRAGES_CONFIANCE = 100
HYPOTHESES_DEFAUT: dict[str, dict[str, Any]] = {
    "heures_ecretees": {"valeur": 8, "unite": "h/an"},
    "rendement_aller_retour": {"valeur": 0.90, "unite": ""},
    "profondeur_decharge": {"valeur": 0.90, "unite": ""},
    "puissance_sur_capacite_max": {"valeur": 1.0, "unite": "kW/kWh"},
    # Fourchette du scan néerlandais (installateur charge24.nl, 10/08/2026, 400 à 700 €/kWh installé) : aucun prix français
    # vérifié ne la remplace encore, elle est marquée hypothèse et à remplacer par deux devis.
    "prix_batterie_eur_kwh": {"valeur": [400, 700], "unite": "€/kWh"},
    # BT > 36 kVA : « Pour les points de connexion raccordés en BT > 36 kVA et dont le contrôle des dépassements de la
    # puissance souscrite est effectué sur la puissance souscrite active, celle-ci est égale à la puissance souscrite
    # apparente multipliée par 0,93. » (Enedis, brochure TURPE 7 HTA/BT du 01/08/2026, p. 6). Les kW mesurés sont donc
    # comparés à 0,93 × Pi ; si le contrôle porte sur la puissance apparente, la fiche donne le cos φ du site.
    "facteur_puissance": {"valeur": 0.93, "unite": ""},
}


def _unite(fraction: float, base: str) -> str:
    """« /an » seulement quand le profil couvre exactement une année (fraction 1), « /periode » sinon."""
    return base + ("/an" if fraction == 1 else "/periode")


def grandeur(valeur: Any, unite: str, nature: str, source: str = "", **parametres: Any) -> dict[str, Any]:
    if nature not in NATURES:
        raise ValueError(f"nature inconnue : {nature}")
    if isinstance(valeur, float) and not math.isfinite(valeur):
        raise ValueError("grandeur non finie")
    if nature in ("a_chiffrer", "a_completer") and isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        raise ValueError("une grandeur à chiffrer ne porte pas de nombre")
    return {"valeur": valeur, "unite": unite, "nature": nature, "source": source, "parametres": parametres}


def nombre_fini(v: Any) -> bool:
    try:
        return type(v) in (int, float) and math.isfinite(v)
    except OverflowError:
        return False


def fiche_controlee(fiche: dict[str, Any]) -> None:
    if not isinstance(fiche, dict):
        raise ValueError("Fiche : objet attendu.")
    import scan_flex
    scan_flex.controle_ean(fiche)  # P2-AB : un EAN numérique a pu perdre des chiffres, refusé avant tout calcul
    domaine = fiche.get("domaine")
    if domaine not in turpe.CLASSES:
        raise ValueError("Fiche : domaine « HTA » ou « BT36 » obligatoire.")
    option = fiche.get("option")
    if option is not None and option not in turpe.OPTIONS[domaine]:
        raise ValueError(f"Fiche : option {option!r} inconnue pour {domaine} ; options : {', '.join(turpe.OPTIONS[domaine])}.")
    ps = fiche.get("puissances_souscrites")
    if ps is not None:
        if not isinstance(ps, dict) or set(ps) != set(turpe.CLASSES[domaine]):
            raise ValueError(f"Fiche : puissances_souscrites doit donner les classes {', '.join(turpe.CLASSES[domaine])}.")
        turpe.controler_puissances([ps[c] for c in turpe.CLASSES[domaine]], domaine)
    for nom, borne in (("puissance_raccordement_kw", math.inf), ("plafond_cible_kw", math.inf), ("facteur_puissance", 1.0)):
        v = fiche.get(nom)
        if v is not None and not (nombre_fini(v) and 0 < v <= borne):
            raise ValueError(f"Fiche : {nom} doit être un nombre fini dans ]0, {borne:g}], reçu {str(v)[:40]!r}.")
    if fiche.get("grille") is not None and fiche["grille"] not in turpe.GRILLES:
        raise ValueError(f"Fiche : grille inconnue {fiche['grille']!r}.")
    tirages = fiche.get("tirages_confiance", TIRAGES_CONFIANCE)
    if type(tirages) is not int or not 0 <= tirages <= 1000:
        raise ValueError(f"Fiche : tirages_confiance doit être un entier de 0 à 1000, reçu {tirages!r}.")
    facture = fiche.get("cmdps_facturee_eur")
    if facture is not None and not (isinstance(facture, dict) and all(isinstance(k, str) and len(k) == 7 and nombre_fini(v) and v >= 0 for k, v in facture.items())):
        raise ValueError("Fiche : cmdps_facturee_eur doit être un objet {« AAAA-MM » : montant ≥ 0}.")
    cal = fiche.get("calendrier")
    if cal is not None:
        if not isinstance(cal, dict) or not set(cal) <= set(turpe.CALENDRIER_DEFAUT):
            raise ValueError(f"Fiche : calendrier, clés admises : {', '.join(turpe.CALENDRIER_DEFAUT)}.")
        for cle in ("heures_creuses", "pointe_fixe_plages", "pointe_mobile_plages"):
            plages = cal.get(cle)
            if plages is not None and not (isinstance(plages, list) and all(isinstance(p, list) and len(p) == 2 and all(type(h) is int and 0 <= h <= 24 for h in p) for p in plages)):
                raise ValueError(f"Fiche : calendrier.{cle} doit être une liste de [heure début, heure fin].")
        for cle in ("saison_haute_mois", "pointe_fixe_mois"):
            mois = cal.get(cle)
            if mois is not None and not (isinstance(mois, list) and all(type(m) is int and 1 <= m <= 12 for m in mois)):
                raise ValueError(f"Fiche : calendrier.{cle} doit être une liste de mois de 1 à 12.")
        jours = cal.get("pointe_mobile_jours")
        if jours is not None:
            if not isinstance(jours, list):
                raise ValueError("Fiche : calendrier.pointe_mobile_jours doit être une liste de dates ISO.")
            for j in jours:
                try:
                    datetime.fromisoformat(j)
                except (TypeError, ValueError) as erreur:
                    raise ValueError(f"Fiche : jour de pointe mobile illisible {str(j)[:20]!r}.") from erreur
    for cle, valeur in (fiche.get("hypotheses") or {}).items():
        if cle not in HYPOTHESES_DEFAUT:
            raise ValueError(f"Hypothèse inconnue : {cle}")
        v = valeur["valeur"] if isinstance(valeur, dict) else valeur
        if cle == "prix_batterie_eur_kwh":
            if v is None:
                continue
            if not (isinstance(v, list) and len(v) == 2 and all(nombre_fini(x) and x > 0 for x in v) and v[0] <= v[1]):
                raise ValueError("Fiche : hypothèse prix_batterie_eur_kwh, fourchette [bas, haut] attendue.")
        elif not (nombre_fini(v) and 0 < v <= (1.0 if cle in ("rendement_aller_retour", "profondeur_decharge", "facteur_puissance") else math.inf)):
            raise ValueError(f"Fiche : hypothèse {cle} invalide : {str(v)[:40]!r}.")


# ---------------------------------------------------------------- profil

def statistiques(kw: list[float], fins: list[datetime], debuts: list[datetime], pas_h: float, injection: list[float], fraction: float,
                 nature: str = "mesure") -> dict[str, Any]:
    """`nature` : « mesure » si chaque valeur est une mesure validée, « lu » sinon (P1-AA : une réserve ne prouve pas une mesure).
    `debuts` : débuts d'intervalle calculés en UTC puis convertis (profil_france.lire) ; « fin locale moins le pas » donne
    une heure fausse aux changements d'heure (P2-AD)."""
    n = len(kw)
    energie = sum(kw) * pas_h
    pointe = max(kw)
    i_pointe = kw.index(pointe)
    unite_an = _unite(fraction, "")
    jours = {d.date() for d in debuts}
    return {"debut": debuts[0].isoformat(), "fin": fins[-1].isoformat(), "intervalles": n, "jours": len(jours),
            "pas_minutes": round(pas_h * 60), "annee_complete": fraction >= 1, "fraction_annee": fraction,
            "energie_mwh": grandeur(round(energie / 1000, 1), "MWh" + unite_an, nature),
            "pointe_kw": grandeur(pointe, "kW", nature), "instant_pointe": debuts[i_pointe].isoformat(),
            "moyenne_kw": grandeur(round(energie / (n * pas_h), 1), "kW", nature),
            "heures_utilisation": grandeur(round(energie / pointe) if pointe else 0, "h" + unite_an, nature, "src_utilisation"),
            "injection_mwh": grandeur(round(sum(injection) * pas_h / 1000, 2), "MWh" + unite_an, nature) if any(injection) else None}


def profils(kw: list[float], debuts: list[datetime], pas_h: float) -> dict[str, Any]:
    par_jour: dict[str, list[float]] = defaultdict(list)
    par_mois: dict[str, list[float]] = defaultdict(list)
    n_pas = round(24 / pas_h)
    somme = [[0.0] * n_pas for _ in range(7)]
    compte = [[0] * n_pas for _ in range(7)]
    for x, d in zip(kw, debuts):
        par_jour[d.date().isoformat()].append(x)
        par_mois[d.strftime("%Y-%m")].append(x)
        q = min(n_pas - 1, int((d.hour * 60 + d.minute) / (pas_h * 60)))
        somme[d.weekday()][q] += x
        compte[d.weekday()][q] += 1
    moyenne = lambda jours, q: (round(sum(somme[j][q] for j in jours) / n, 1) if (n := sum(compte[j][q] for j in jours)) else None)  # noqa: E731
    i_pointe = kw.index(max(kw))
    return {"annuel": [{"jour": j, "max_kw": max(v), "moyenne_kw": round(sum(v) / len(v), 1)} for j, v in par_jour.items()],
            "mensuel": [{"mois": m, "max_kw": max(v), "moyenne_kw": round(sum(v) / len(v), 1), "energie_mwh": round(sum(v) * pas_h / 1000, 1)}
                        for m, v in par_mois.items()],
            "semaine_type": [[moyenne([j], q) for q in range(n_pas)] for j in range(7)],
            "jour_ouvre_moyen": [moyenne(range(5), q) for q in range(n_pas)],
            "jour_pointe": {"jour": debuts[i_pointe].date().isoformat(), "kw": par_jour[debuts[i_pointe].date().isoformat()]},
            "monotone": sorted(kw, reverse=True), "pas_par_jour": n_pas}


def plafond_heures(kw: list[float], heures: float) -> float:
    """Valeur dépassée pendant `heures` par an : le rang est proportionnel à la longueur du profil (une année entière
    au quart d'heure donne heures / 0,25 ; deux années, le double)."""
    rang = int(round(heures / 8760 * len(kw)))
    tri = sorted(kw, reverse=True)
    return tri[min(rang, len(tri) - 1)]


# ---------------------------------------------------------------- situation, optimisation, batterie

def _ps_liste(fiche: dict[str, Any]) -> list[float] | None:
    ps = fiche.get("puissances_souscrites")
    return [ps[c] for c in turpe.CLASSES[fiche["domaine"]]] if ps else None


def situation_actuelle(kw, classes, mois, fiche, pas_minutes, fraction, facteur) -> dict[str, Any]:
    domaine, option, ps = fiche["domaine"], fiche.get("option"), _ps_liste(fiche)
    if not option or ps is None:
        return {"disponible": False, "manque": [x for x, ok in (("option", option), ("puissances_souscrites", ps)) if not ok],
                "total_eur": grandeur(None, "€/an", "a_completer", "src_contrat")}
    detail = turpe.cout_total(kw, classes, mois, ps, domaine, option, pas_minutes, fiche.get("grille", turpe.GRILLE_DEFAUT), facteur, fraction)
    g = turpe.grille(domaine, option, fiche.get("grille", turpe.GRILLE_DEFAUT))
    unite = _unite(fraction, "€")
    depassements = detail["cmdps"]
    heures = sum(c["heures"] for m in depassements["par_mois"].values() for c in m.values())
    par_classe = {}
    for m in depassements["par_mois"].values():
        for nom, c in m.items():
            d = par_classe.setdefault(nom, {"eur": 0.0, "heures": 0.0, "depassement_max": 0.0, "mois": 0})
            d["eur"] += c["eur"]
            d["heures"] += c["heures"]
            d["depassement_max"] = max(d["depassement_max"], c["depassement_max"])
            d["mois"] += 1 if c["eur"] > 0 else 0
    facture = fiche.get("cmdps_facturee_eur") or {}
    confrontation = None
    if facture:
        communs = [m for m in facture if m in depassements["par_mois"]]
        if communs:
            calcule = sum(sum(c["eur"] for c in depassements["par_mois"][m].values()) for m in communs)
            facturee = sum(facture[m] for m in communs)
            confrontation = {"mois": communs, "calcule_eur": round(calcule, 2), "facture_eur": round(facturee, 2),
                             "ecart_part": round((calcule - facturee) / facturee, 3) if facturee else None}
    return {"disponible": True, "option": option, "ps": ps,
            "puissance_eur": grandeur(round(detail["puissance_eur"]), unite, "tarif", "src_cs_puissance", option=turpe.NOMS_OPTIONS[option], en_vigueur=g["en_vigueur"], grille=g["source"]),
            "energie_eur": grandeur(round(detail["energie_eur"]), unite, "simule", "src_cs_energie", en_vigueur=g["en_vigueur"], grille=g["source"]),
            "cmdps_eur": grandeur(round(detail["cmdps_eur"]), unite, "simule", "src_cmdps_" + domaine.lower(), pas=pas_minutes, alpha=g["cmdps"].get("alpha_eur_h"), grille=g["source"]),
            "total_eur": grandeur(round(detail["total_eur"]), unite, "simule", "src_total_turpe"),
            "heures_depassement": grandeur(round(heures, 2), _unite(fraction, "h"), "simule", "src_heures_depassement"),
            "par_classe": par_classe, "par_mois": depassements["par_mois"], "energies_kwh": detail["energies_kwh"],
            "confrontation_facture": confrontation}


def optimisation(kw, classes, mois, fiche, pas_minutes, fraction, facteur, actuel) -> dict[str, Any]:
    domaine = fiche["domaine"]
    option = fiche.get("option") or turpe.OPTIONS[domaine][0]
    opt = turpe.optimiser_puissances(kw, classes, mois, domaine, option, pas_minutes, fiche.get("grille", turpe.GRILLE_DEFAUT),
                                     fiche.get("puissance_raccordement_kw"), facteur, fraction)
    g = turpe.grille(domaine, option, fiche.get("grille", turpe.GRILLE_DEFAUT))
    unite = _unite(fraction, "€")
    resultat = {"option": option, "option_nature": "declare" if fiche.get("option") else "hypothese",
                "ps": opt["ps"], "classes_sans_mesure": opt["classes_sans_mesure"],
                "puissance_eur": grandeur(round(opt["detail"]["puissance_eur"]), unite, "simule", "src_cs_puissance", option=turpe.NOMS_OPTIONS[option], en_vigueur=g["en_vigueur"], grille=g["source"]),
                "cmdps_eur": grandeur(round(opt["detail"]["cmdps_eur"]), unite, "simule", "src_cmdps_" + domaine.lower(), pas=pas_minutes, alpha=g["cmdps"].get("alpha_eur_h"), grille=g["source"]),
                "total_eur": grandeur(round(opt["detail"]["total_eur"]), unite, "simule", "src_total_turpe"),
                "puissance_raccordement_kw": fiche.get("puissance_raccordement_kw"), "detail": opt["detail"]}
    if actuel.get("disponible") and actuel["option"] == option:
        eco = actuel["total_eur"]["valeur"] - resultat["total_eur"]["valeur"]
        resultat["economie_eur"] = grandeur(round(eco), unite, "simule", "src_economie_ps", actuel=actuel["total_eur"]["valeur"], optimal=resultat["total_eur"]["valeur"])
        resultat["ecarts_ps"] = [round(o - a) for o, a in zip(opt["ps"], actuel["ps"])]
    else:
        resultat["economie_eur"] = grandeur(None, unite, "a_completer", "src_contrat")
    return resultat


def comparaison_options(kw, debuts, fiche, pas_minutes, facteur, actuel) -> dict[str, Any]:
    domaine = fiche["domaine"]
    comp = turpe.comparer_options(kw, debuts, domaine, pas_minutes, fiche.get("grille", turpe.GRILLE_DEFAUT), fiche.get("calendrier"),
                                  fiche.get("puissance_raccordement_kw"), facteur)
    fraction = turpe.fraction_annee(len(kw), pas_minutes / 60)
    unite = _unite(fraction, "€")
    lignes = []
    for option, r in comp["options"].items():
        if not r["disponible"]:
            lignes.append({"option": option, "nom": turpe.NOMS_OPTIONS[option], "disponible": False, "raison": r["raison"]})
            continue
        lignes.append({"option": option, "nom": turpe.NOMS_OPTIONS[option], "disponible": True, "ps": r["ps"],
                       "puissance_eur": round(r["detail"]["puissance_eur"]), "energie_eur": round(r["detail"]["energie_eur"]),
                       "cmdps_eur": round(r["detail"]["cmdps_eur"]), "total_eur": round(r["detail"]["total_eur"])})
    meilleure = comp["meilleure"]
    gain = None
    if meilleure and actuel.get("disponible"):
        gain = grandeur(round(actuel["total_eur"]["valeur"] - comp["options"][meilleure]["detail"]["total_eur"]), unite, "simule", "src_economie_option",
                        option=turpe.NOMS_OPTIONS[meilleure])
    return {"lignes": lignes, "meilleure": meilleure, "gain_vs_actuel": gain, "regle": grandeur("regle_12_mois", "", "tarif", "src_cre78_12_mois")}


def scenario_batterie(kw, fins, classes, mois, fiche, pas_h, pas_minutes, fraction, facteur, hyp, opt_sans) -> dict[str, Any]:
    """Batterie qui tient un plafond (pointe sans ses N heures les plus hautes, ou plafond de la fiche), puis puissances
    souscrites ré-optimisées sur le profil vu du réseau. L'économie supplémentaire est celle par rapport aux puissances
    optimales sans batterie, sur la même option."""
    domaine, option = fiche["domaine"], opt_sans["option"]
    plafond = float(fiche.get("plafond_cible_kw") or plafond_heures(kw, hyp["heures_ecretees"]))
    if not 0 < plafond < max(kw):
        return {"faisable": False, "raison": "plafond hors de ]0, pointe[", "plafond_kw": grandeur(plafond, "kW", "hypothese", "src_plafond_fiche")}
    dim = db.dimensionner_optimal(kw, plafond, {k: hyp[k] for k in ("rendement_aller_retour", "profondeur_decharge", "puissance_sur_capacite_max")}, pas_h)
    plafond_g = (grandeur(plafond, "kW", "hypothese", "src_plafond_fiche") if fiche.get("plafond_cible_kw")
                 else grandeur(plafond, "kW", "hypothese", "src_plafond_heures", heures=hyp["heures_ecretees"]))
    if not dim["faisable"]:
        return {"faisable": False, "raison": "aucune batterie ne tient ce plafond (recharge impossible)", "plafond_kw": plafond_g}
    sim = db.simuler(kw, plafond, dim["utile_kwh"] * (1 + 1e-6), dim["puissance_kw"], hyp, pas_h)
    apres = sim["reseau"]
    opt_avec = turpe.optimiser_puissances(apres, classes, mois, domaine, option, pas_minutes, fiche.get("grille", turpe.GRILLE_DEFAUT),
                                          fiche.get("puissance_raccordement_kw"), facteur, fraction)
    g = turpe.grille(domaine, option, fiche.get("grille", turpe.GRILLE_DEFAUT))
    unite = _unite(fraction, "€")
    eco = opt_sans["detail"]["total_eur"] - opt_avec["detail"]["total_eur"]
    prix = hyp.get("prix_batterie_eur_kwh")
    nominale = round(dim["nominale_kwh"], 1)
    if prix:
        invest = grandeur([round(nominale * prix[0], -2), round(nominale * prix[1], -2)], "€", "hypothese", "src_invest_prix", bas=prix[0], haut=prix[1], nominale=nominale)
    else:
        invest = grandeur(None, "€", "a_chiffrer", "src_invest_a_demander")
    if fraction < 1:
        retour = grandeur(None, "ans", "a_chiffrer", "src_retour_periode")
    elif invest["valeur"] and eco > 0:
        eco_an = eco / fraction  # économie de la période ramenée à l'année (fraction = durée en années)
        retour = grandeur([round(invest["valeur"][0] / eco_an, 1), round(invest["valeur"][1] / eco_an, 1)], "ans", "simule", "src_retour_simple", annees=fraction)
    else:
        retour = grandeur(None, "ans", "a_chiffrer", "src_retour_non_chiffre")
    return {"faisable": True, "plafond_kw": plafond_g,
            "puissance_kw": grandeur(round(dim["puissance_kw"], 1), "kW", "simule", "src_puissance_optimisee"),
            "puissance_minimale_kw": grandeur(round(dim["reference"]["puissance_kw"], 1), "kW", "simule", "src_puissance_minimale"),
            "capacite_utile_kwh": grandeur(round(dim["utile_kwh"], 1), "kWh", "simule", "src_moteur"),
            "capacite_nominale_kwh": grandeur(nominale, "kWh", "hypothese", "src_nominale_" + dim["dimension"], dod=hyp["profondeur_decharge"], crate=hyp["puissance_sur_capacite_max"]),
            "nominale_reference_kwh": grandeur(round(dim["reference"]["nominale_kwh"], 1), "kWh", "simule", "src_nominale_reference"),
            "gain_dimensionnement_kwh": round(dim["gain_kwh"], 1),
            "energie_dechargee_mwh": grandeur(round(sum(sim["decharge"]) * pas_h / 1000, 2), _unite(fraction, "MWh"), "simule", "src_energie_dechargee"),
            "ps": opt_avec["ps"], "total_eur": grandeur(round(opt_avec["detail"]["total_eur"]), unite, "simule", "src_total_turpe"),
            "cmdps_eur": grandeur(round(opt_avec["detail"]["cmdps_eur"]), unite, "simule", "src_cmdps_" + domaine.lower(), pas=pas_minutes, alpha=g["cmdps"].get("alpha_eur_h"), grille=g["source"]),
            "economie_supplementaire_eur": grandeur(round(eco), unite, "simule", "src_economie_batterie"),
            "investissement_eur": invest, "retour_ans": retour, "pointe_reseau_kw": round(max(apres), 1), "profil_apres": apres}


def quarts_decisifs(kw, debuts, classes, mois, ps, domaine, option, pas_minutes, pas_h, fraction, grille_version, facteur) -> dict[str, Any]:
    """Les pas de temps qui font la CMDPS aux puissances optimales : part de la somme des carrés (HTA) ou des heures (BT)
    par mois, et les jours qui pèsent le plus. Contrefactuel : CMDPS et puissances optimales si les k jours les plus lourds
    étaient restés sous les puissances souscrites."""
    noms = turpe.CLASSES[domaine]
    contributions: dict[str, float] = defaultdict(float)
    par_pas = []
    for i, (x, k, m) in enumerate(zip(kw, classes, mois)):
        seuil = ps[k] * (facteur if domaine == "BT36" else 1)
        if x > seuil:
            poids = (x - seuil) ** 2 if domaine == "HTA" else 1.0
            contributions[debuts[i].date().isoformat()] += poids
            par_pas.append((poids, i))
    jours = sorted(contributions.items(), key=lambda kv: -kv[1])
    total = sum(contributions.values())
    top = sorted(par_pas, reverse=True)[:8]
    liste_top = [{"debut": debuts[i].isoformat(timespec="minutes"), "kw": round(kw[i], 1), "classe": noms[classes[i]],
                  "depassement_kw": round(kw[i] - ps[classes[i]] * (facteur if domaine == "BT36" else 1), 1)} for _, i in top]
    sans = []
    profil = list(kw)
    for rang, (jour, _) in enumerate(jours[:3], 1):
        for i in range(len(kw)):
            if debuts[i].date().isoformat() == jour:
                seuil = ps[classes[i]] * (facteur if domaine == "BT36" else 1)
                profil[i] = min(profil[i], seuil)
        opt = turpe.optimiser_puissances(profil, classes, mois, domaine, option, pas_minutes, grille_version, None, facteur, fraction)
        sans.append({"jours_retires": rang, "cmdps_eur": round(opt["detail"]["cmdps_eur"]), "ps": opt["ps"], "total_eur": round(opt["detail"]["total_eur"])})
    return {"jours_au_dessus": len(jours), "jours": [{"jour": j, "part": round(p / total, 3) if total else 0.0} for j, p in jours[:5]],
            "top": liste_top, "sans_jours": sans}


def confiance(kw, debuts, classes, mois, fiche, pas_minutes, pas_h, fraction, facteur, option, tirages, graine=2026) -> dict[str, Any] | None:
    """Rééchantillonnage des jours (même mois, même type de jour, graine fixe), comme le scan néerlandais : puissances
    optimales et coût total recalculés sur chaque année tirée. Mêmes limites : aucune journée plus haute que la plus haute
    mesurée, jours fériés comptés comme ouvrés, année de croissance non couverte."""
    if tirages <= 0:
        return None
    n_jour = round(24 / pas_h)
    par_jour: dict[Any, list[int]] = defaultdict(list)
    for i, d in enumerate(debuts):
        par_jour[d.date()].append(i)
    blocs, strates = [], defaultdict(list)
    for jour in sorted(par_jour):
        idx = par_jour[jour]
        complet = len(idx) == n_jour and idx[-1] - idx[0] == n_jour - 1
        strate = (jour.month, "ouvre" if jour.weekday() < 5 else "samedi" if jour.weekday() == 5 else "dimanche") if complet else None
        blocs.append((idx[0], len(idx), strate))
        if strate:
            strates[strate].append(idx[0])
    if sum(len(v) for v in strates.values()) < 14:
        return None
    alea = random.Random(graine)
    totaux, ps_tires = [], []
    domaine = fiche["domaine"]
    for _ in range(tirages):
        serie = []
        for debut, longueur, strate in blocs:
            source = alea.choice(strates[strate]) if strate else debut
            serie.extend(kw[source:source + longueur])
        opt = turpe.optimiser_puissances(serie, classes, mois, domaine, option, pas_minutes, fiche.get("grille", turpe.GRILLE_DEFAUT),
                                         fiche.get("puissance_raccordement_kw"), facteur, fraction)
        totaux.append(opt["detail"]["total_eur"])
        ps_tires.append(opt["ps"])

    def bornes(valeurs):
        q = statistics.quantiles(valeurs, n=20, method="inclusive")
        return {"p5": round(q[0], 1), "mediane": round(statistics.median(valeurs), 1), "p95": round(q[-1], 1)}
    return {"tirages": tirages, "graine": graine, "jours_reechantillonnes": sum(len(v) for v in strates.values()),
            "total_eur": bornes(totaux), "ps": [bornes([p[k] for p in ps_tires]) for k in range(len(turpe.CLASSES[domaine]))]}


def recommander(actuel, opt, options, batterie, fraction) -> list[dict[str, Any]]:
    lignes = []
    if actuel.get("disponible"):
        eco = opt["economie_eur"]["valeur"] or 0
        lignes.append({"option": "puissances", "cle": "reco_ps_gain" if eco > 0 else "reco_ps_ok", "eur": round(eco)})
    else:
        lignes.append({"option": "puissances", "cle": "reco_ps_sans_contrat"})
    if options["meilleure"] and actuel.get("disponible") and options["meilleure"] != actuel["option"] and (options["gain_vs_actuel"] or {}).get("valeur", 0) > 0:
        lignes.append({"option": "option", "cle": "reco_option", "eur": options["gain_vs_actuel"]["valeur"], "nom": turpe.NOMS_OPTIONS[options["meilleure"]]})
    if batterie.get("faisable"):
        r = batterie["retour_ans"]["valeur"]
        cle = "reco_batterie_chiffree" if r and r[0] <= 10 else "reco_batterie_longue" if r else "reco_batterie_a_chiffrer"
        lignes.append({"option": "batterie", "cle": cle})
    return lignes


# ---------------------------------------------------------------- scan

def scanner(profil: dict[str, Any], fiche: dict[str, Any]) -> dict[str, Any]:
    fiche_controlee(fiche)
    valeurs, fins, pas_h, pas_minutes = profil["valeurs"], profil["fins"], profil["pas_h"], profil["pas_minutes"]
    if len(valeurs) != len(fins):
        raise ValueError(f"Scan France : {len(valeurs)} valeurs pour {len(fins)} horodatages.")
    if len(valeurs) < round(7 * 24 / pas_h) - 8:
        raise ValueError("Scan France : au moins une semaine de mesures horodatées.")
    kw, injection = pf.separer(valeurs)
    hypotheses = {k: dict(v) for k, v in HYPOTHESES_DEFAUT.items()}
    for cle, valeur in (fiche.get("hypotheses") or {}).items():
        hypotheses[cle]["valeur"] = valeur["valeur"] if isinstance(valeur, dict) else valeur
        if isinstance(valeur, dict) and valeur.get("source"):
            hypotheses[cle]["source"] = valeur["source"]
        else:
            hypotheses[cle]["source_cle"] = "hyp_fiche_sans_source"
    if fiche.get("facteur_puissance") is not None:
        hypotheses["facteur_puissance"]["valeur"] = fiche["facteur_puissance"]
        hypotheses["facteur_puissance"]["source_cle"] = "hyp_facteur_fiche"
    hyp = {k: v["valeur"] for k, v in hypotheses.items()}
    domaine = fiche["domaine"]
    facteur = float(hyp["facteur_puissance"]) if domaine == "BT36" else 1.0
    debuts = profil["debuts"]  # calculés en UTC : justes aux changements d'heure (pf.debuts ne l'est pas)
    option = fiche.get("option") or turpe.OPTIONS[domaine][0]
    classes = turpe.classes_profil(debuts, domaine, option, fiche.get("calendrier"))
    mois = [d.strftime("%Y-%m") for d in debuts]
    fraction = turpe.fraction_annee(len(kw), pas_h)
    grille_version = fiche.get("grille", turpe.GRILLE_DEFAUT)
    jeu = pf.jeu_qualite(profil, fiche, VERSION)  # FB1 : page qualité et réserves (valeurs non mesurées, pointe)
    stats = statistiques(kw, fins, debuts, pas_h, injection, fraction, "lu" if jeu["reserve_valeurs"] else "mesure")
    prof = profils(kw, debuts, pas_h)
    noms = turpe.CLASSES[domaine]
    par_classe = {noms[k]: {"energie_kwh": 0.0, "pointe_kw": 0.0, "heures": 0.0} for k in range(len(noms))}
    for x, k in zip(kw, classes):
        c = par_classe[noms[k]]
        c["energie_kwh"] += x * pas_h
        c["pointe_kw"] = max(c["pointe_kw"], x)
        c["heures"] += pas_h
    actuel = situation_actuelle(kw, classes, mois, fiche, pas_minutes, fraction, facteur)
    opt = optimisation(kw, classes, mois, fiche, pas_minutes, fraction, facteur, actuel)
    options = comparaison_options(kw, debuts, fiche, pas_minutes, facteur, actuel)
    batterie = scenario_batterie(kw, fins, classes, mois, fiche, pas_h, pas_minutes, fraction, facteur, hyp, opt)
    decisifs = quarts_decisifs(kw, debuts, classes, mois, opt["ps"], domaine, option, pas_minutes, pas_h, fraction, grille_version, facteur) if opt["detail"]["cmdps_eur"] > 0 else None
    conf = confiance(kw, debuts, classes, mois, fiche, pas_minutes, pas_h, fraction, facteur, option, fiche.get("tirages_confiance", TIRAGES_CONFIANCE))
    g = turpe.grille(domaine, option, grille_version)
    return {"version": VERSION, "jeu_qualite": jeu, "reserves": {"pointe": jeu["reserve_pointe"], "valeurs": jeu["reserve_valeurs"]},
            "site": {k: fiche.get(k) for k in ("nom", "adresse", "secteur", "exemple", "source_profil", "licence_profil")},
            "raccordement": {"domaine": domaine, "option": option, "option_nature": "declare" if fiche.get("option") else "hypothese",
                             "unite_puissance": turpe.UNITE_PUISSANCE[domaine], "puissance_raccordement_kw": fiche.get("puissance_raccordement_kw"),
                             "facteur_puissance": facteur, "grille": grille_version, "grille_en_vigueur": g["en_vigueur"], "grille_source": g["source"], "b": g["b"], "c": g["c"],
                             "calendrier": {**turpe.CALENDRIER_DEFAUT, **(fiche.get("calendrier") or {})},
                             "calendrier_fourni": sorted(fiche.get("calendrier") or {})},
            "profil": {"pas_minutes": pas_minutes, "fuseau_lu": profil.get("fuseau_lu"), "injection": bool(any(injection)),
                       "approximation_10min": pas_minutes != 10 and domaine == "HTA"},
            "statistiques": stats, "profils": prof, "classes": par_classe,
            "actuel": actuel, "optimisation": opt, "options": options, "batterie": batterie,
            "quarts_decisifs": decisifs, "confiance": conf, "hypotheses": hypotheses,
            "recommandation": recommander(actuel, opt, options, batterie, fraction),
            "profil_kw": kw, "horodatages": [f.isoformat() for f in fins]}


def allege(r: dict[str, Any]) -> dict[str, Any]:
    sortie = {k: v for k, v in r.items() if k not in ("profil_kw", "horodatages")}
    sortie["profils"] = {k: v for k, v in r["profils"].items() if k != "monotone"}
    sortie["batterie"] = {k: v for k, v in r["batterie"].items() if k != "profil_apres"}
    sortie["optimisation"] = {k: v for k, v in r["optimisation"].items() if k != "detail"}
    return sortie


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    fiche = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    octets = Path(argv[1]).read_bytes()
    profil = pf.lire(octets.decode("utf-8"))
    # Provenance du fichier tel que reçu (FB1) : le lecteur n'a vu que le texte.
    import hashlib
    profil["provenance"].update(fichier=Path(argv[1]).name, octets=len(octets), sha256=hashlib.sha256(octets).hexdigest())
    resultat = scanner(profil, fiche)
    sortie = Path(argv[3])
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "scan-turpe.json").write_text(json.dumps(allege(resultat), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    import rapport_turpe
    (sortie / "rapport-turpe.html").write_text(rapport_turpe.rendre(resultat), encoding="utf-8")
    print(f"scan écrit dans {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
