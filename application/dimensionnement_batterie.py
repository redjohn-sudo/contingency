"""Dimensionnement d'une batterie d'écrêtage : puissance et capacité choisies ensemble.

Le scan de flexibilité dimensionne la batterie avec la puissance minimale (pointe moins plafond), puis
demande au moteur cyclique la capacité utile qui tient le plafond avec cette puissance, et prend la
capacité nominale la plus grande des deux bornes : énergie (utile / profondeur de décharge) et puissance
(puissance / C-rate). Une batterie un peu plus puissante se recharge plus vite entre deux pointes
rapprochées : elle a besoin de moins d'énergie, et peut être moins chère quand la borne d'énergie domine.

Ce module cherche la puissance qui minimise la capacité nominale, c'est-à-dire le prix quand il est
donné en euros par kWh nominal. Il ne change rien au modèle physique (moteur cyclique vérifié,
optimisation/moteur.py) : il l'appelle seulement avec d'autres puissances.

Deux résultats sont toujours donnés côte à côte :
  reference   la méthode du scan (puissance minimale), pour comparer ;
  optimal     la puissance qui rend la batterie nominale la plus petite.

Le module donne aussi le choix exact des jours décisifs : quels K jours au-dessus du plafond, s'ils étaient
restés sous le plafond, réduiraient le plus la batterie. Le scan retire les jours dans l'ordre de leur poids
(choix glouton) ; ici, toutes les combinaisons de K jours parmi les N plus lourds sont évaluées.

Toutes les grandeurs sont des simulations sur le profil mesuré. Aucune ne dit qu'une pointe peut baisser.
"""
from __future__ import annotations

import itertools
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent / "optimisation"))

from moteur import capacite_rapide  # noqa: E402

PAS_H = 0.25
QUART = timedelta(minutes=15)
HYPOTHESES_DEFAUT = {"rendement_aller_retour": 0.90, "profondeur_decharge": 0.90, "puissance_sur_capacite_max": 1.0}
TOLERANCE_KW = 1e-6


def _hyp(hyp: dict[str, Any] | None) -> dict[str, float]:
    h = {**HYPOTHESES_DEFAUT, **(hyp or {})}
    for cle in ("rendement_aller_retour", "profondeur_decharge"):
        if not (isinstance(h[cle], (int, float)) and 0 < h[cle] <= 1):
            raise ValueError(f"{cle} : nombre dans ]0, 1] attendu, reçu {h[cle]!r}.")
    if not (isinstance(h["puissance_sur_capacite_max"], (int, float)) and h["puissance_sur_capacite_max"] > 0):
        raise ValueError("puissance_sur_capacite_max : nombre strictement positif attendu.")
    return h


def _controler(kw: list[float], plafond: float) -> None:
    if not kw:
        raise ValueError("Profil vide.")
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in kw):
        raise ValueError("Profil : valeurs non finies.")
    if any(x < 0 for x in kw):
        raise ValueError("Profil : valeurs négatives (injection) non prises en charge par ce dimensionnement.")
    if not (isinstance(plafond, (int, float)) and math.isfinite(plafond) and plafond > 0):
        raise ValueError("Plafond : nombre fini strictement positif attendu.")


def capacite_utile(kw: list[float], plafond: float, puissance_kw: float, hyp: dict[str, Any] | None = None,
                   pas_h: float = PAS_H) -> float | None:
    """Capacité utile (kWh) qui tient le plafond avec cette puissance de charge et de décharge, ou None si
    aucune capacité ne suffit (recharge impossible sur le cycle)."""
    h = _hyp(hyp)
    r = capacite_rapide(kw, plafond, rendement=math.sqrt(h["rendement_aller_retour"]), puissance_max=puissance_kw, pas_heures=pas_h)
    if r.get("statut") != 0:
        return None
    return float(r["capacite_utile_kwh"])


def nominale(utile_kwh: float, puissance_kw: float, hyp: dict[str, Any] | None = None) -> tuple[float, str]:
    """Capacité nominale : la plus grande des deux bornes, et laquelle domine (« energie » ou « puissance »)."""
    h = _hyp(hyp)
    par_energie = utile_kwh / h["profondeur_decharge"]
    par_puissance = puissance_kw / h["puissance_sur_capacite_max"]
    return max(par_energie, par_puissance), ("puissance" if par_puissance >= par_energie else "energie")


def dimensionner_reference(kw: list[float], plafond: float, hyp: dict[str, Any] | None = None, pas_h: float = PAS_H) -> dict[str, Any]:
    """La méthode du scan de flexibilité : puissance = pointe moins plafond, capacité par le moteur cyclique."""
    _controler(kw, plafond)
    besoin = max(kw) - plafond
    if besoin <= TOLERANCE_KW:
        return {"faisable": True, "puissance_kw": 0.0, "utile_kwh": 0.0, "nominale_kwh": 0.0, "dimension": "aucune"}
    utile = capacite_utile(kw, plafond, besoin, hyp, pas_h)
    if utile is None:
        return {"faisable": False, "puissance_kw": besoin, "utile_kwh": None, "nominale_kwh": None, "dimension": None}
    nom, dim = nominale(utile, besoin, hyp)
    return {"faisable": True, "puissance_kw": besoin, "utile_kwh": utile, "nominale_kwh": nom, "dimension": dim}


def dimensionner_optimal(kw: list[float], plafond: float, hyp: dict[str, Any] | None = None, pas_h: float = PAS_H,
                         precision_kw: float = 0.01, facteur_max: float = 64.0) -> dict[str, Any]:
    """Puissance qui minimise la capacité nominale.

    La capacité utile ne croît pas avec la puissance (une batterie plus puissante se recharge au moins aussi
    vite) ; la borne de puissance croît avec elle. La capacité nominale, maximum des deux, est donc minimale
    là où les deux bornes se croisent, ou à la puissance minimale si celle-ci est déjà bornée par la puissance.
    On cherche ce croisement par dichotomie entre la puissance minimale et une puissance où la borne de
    puissance domine. Les évaluations du moteur sont comptées (`evaluations`)."""
    _controler(kw, plafond)
    h = _hyp(hyp)
    reference = dimensionner_reference(kw, plafond, h, pas_h)
    resultat = {"reference": reference, "evaluations": 1 if reference["puissance_kw"] else 0}
    if not reference["faisable"] or reference["dimension"] in ("aucune", "puissance"):
        resultat.update({k: reference[k] for k in ("faisable", "puissance_kw", "utile_kwh", "nominale_kwh", "dimension")})
        resultat["gain_kwh"] = 0.0
        return resultat
    besoin = reference["puissance_kw"]
    dod, c_rate = h["profondeur_decharge"], h["puissance_sur_capacite_max"]
    excedent = lambda utile, p: utile / dod - p / c_rate  # > 0 : l'énergie domine encore  # noqa: E731

    def evaluer(p: float) -> float | None:
        resultat["evaluations"] += 1
        return capacite_utile(kw, plafond, p, h, pas_h)

    bas, utile_bas = besoin, reference["utile_kwh"]
    haut, utile_haut = None, None
    p = besoin
    while p < besoin * facteur_max:
        p *= 2
        u = evaluer(p)
        if u is None:  # une puissance plus grande ne peut pas rendre la recharge impossible : cas non attendu, on s'arrête
            break
        if excedent(u, p) <= 0:
            haut, utile_haut = p, u
            break
        bas, utile_bas = p, u
    if haut is None:
        # L'énergie domine même à très haute puissance (profil sans place pour recharger) : on garde la meilleure
        # puissance essayée, la nominale y est la plus petite.
        nom, dim = nominale(utile_bas, bas, h)
        resultat.update({"faisable": True, "puissance_kw": bas, "utile_kwh": utile_bas, "nominale_kwh": nom, "dimension": dim})
        resultat["gain_kwh"] = reference["nominale_kwh"] - nom
        return resultat
    # Dichotomie sur la puissance : à gauche l'énergie domine, à droite la puissance domine.
    while haut - bas > precision_kw:
        milieu = (bas + haut) / 2
        u = evaluer(milieu)
        if u is None:
            break
        if excedent(u, milieu) <= 0:
            haut, utile_haut = milieu, u
        else:
            bas, utile_bas = milieu, u
    candidats = [(nominale(utile_bas, bas, h), bas, utile_bas), (nominale(utile_haut, haut, h), haut, utile_haut)]
    (nom, dim), p_opt, u_opt = min(candidats, key=lambda c: c[0][0])
    resultat.update({"faisable": True, "puissance_kw": p_opt, "utile_kwh": u_opt, "nominale_kwh": nom, "dimension": dim})
    resultat["gain_kwh"] = max(0.0, reference["nominale_kwh"] - nom)
    # Jamais pire que la référence, et pas de « gain » de quelques grammes dû à la précision de la dichotomie : à gain
    # négligeable (moins de 1 Wh), la puissance minimale est gardée, c'est aussi l'onduleur le moins cher.
    if nom > reference["nominale_kwh"] - 1e-3:
        resultat.update({k: reference[k] for k in ("puissance_kw", "utile_kwh", "nominale_kwh", "dimension")})
        resultat["gain_kwh"] = 0.0
    return resultat


def simuler(kw: list[float], plafond: float, utile_kwh: float, puissance_kw: float, hyp: dict[str, Any] | None = None,
            pas_h: float = PAS_H) -> dict[str, Any]:
    """Batterie pleine au départ, décharge au-dessus du plafond, recharge au plus tôt sous le plafond, à
    puissance bornée dans les deux sens. Renvoie le profil vu du réseau, la décharge par pas et l'énergie
    stockée en fin de chaque pas. Même règle que le scan de flexibilité."""
    h = _hyp(hyp)
    eta = math.sqrt(h["rendement_aller_retour"])
    etat = utile_kwh
    reseau, decharge, etats = [], [], []
    for x in kw:
        if x > plafond:
            d = min(x - plafond, puissance_kw, etat * eta / pas_h)
            etat -= d * pas_h / eta
            reseau.append(x - d)
            decharge.append(d)
        else:
            c = min(plafond - x, puissance_kw, (utile_kwh - etat) / (eta * pas_h))
            etat += c * pas_h * eta
            reseau.append(x + c)
            decharge.append(0.0)
        etats.append(etat)
    return {"reseau": reseau, "decharge": decharge, "etats": etats, "pointe_reseau_kw": max(reseau),
            "tient": max(reseau) - plafond <= 1e-6 * max(1.0, plafond)}


# ---------------------------------------------------------------- jours décisifs, choix exact

def _jours_au_dessus(kw: list[float], fins: list[datetime], plafond: float, tolerance_kw: float = 0.05) -> list[dict[str, Any]]:
    par_jour: dict[Any, dict[str, Any]] = {}
    for i, x in enumerate(kw):
        if x > plafond + tolerance_kw:
            jour = (fins[i] - QUART).date()
            d = par_jour.setdefault(jour, {"jour": jour.isoformat(), "max_kw": 0.0, "quarts": 0, "energie_kwh": 0.0, "indices": []})
            d["max_kw"] = max(d["max_kw"], x)
            d["quarts"] += 1
            d["energie_kwh"] += (x - plafond) * PAS_H
            d["indices"].append(i)
    return list(par_jour.values())


def _poids(d: dict[str, Any], plafond: float, h: dict[str, float]) -> float:
    """Poids d'un jour pour la batterie : la capacité qu'il demanderait seul, sans recharge dans la journée."""
    return max(d["energie_kwh"] / h["profondeur_decharge"], (d["max_kw"] - plafond) / h["puissance_sur_capacite_max"])


def _sans_jours(kw: list[float], jours: list[dict[str, Any]], plafond: float, h: dict[str, float],
                puissance_reference: float, optimal: bool) -> float | None:
    profil = list(kw)
    for d in jours:
        for i in d["indices"]:
            profil[i] = plafond
    if max(profil) - plafond <= TOLERANCE_KW:
        return 0.0
    if optimal:
        r = dimensionner_optimal(profil, plafond, h)
        return r["nominale_kwh"] if r["faisable"] else None
    # Règle du scan : puissance réduite au dépassement restant, ou puissance de la référence ; la plus petite nominale.
    candidats = []
    for p in (max(profil) - plafond, puissance_reference):
        u = capacite_utile(profil, plafond, max(p, max(profil) - plafond), h)
        if u is not None:
            candidats.append(nominale(u, max(p, max(profil) - plafond), h)[0])
    return min(candidats) if candidats else None


def jours_decisifs(kw: list[float], fins: list[datetime], plafond: float, hyp: dict[str, Any] | None = None,
                   k_max: int = 3, candidats: int = 6, optimal: bool = False) -> dict[str, Any]:
    """Pour K = 1 à k_max : le choix glouton (les K jours les plus lourds) et le choix exact (la combinaison de K
    jours parmi les `candidats` plus lourds qui laisse la plus petite batterie). `optimal` applique aussi le
    dimensionnement à puissance optimisée. Renvoie la nominale de référence et, pour chaque K, les deux résultats."""
    _controler(kw, plafond)
    if len(kw) != len(fins):
        raise ValueError(f"{len(kw)} valeurs pour {len(fins)} horodatages.")
    h = _hyp(hyp)
    jours = sorted(_jours_au_dessus(kw, fins, plafond), key=lambda d: _poids(d, plafond, h), reverse=True)
    reference = dimensionner_optimal(kw, plafond, h) if optimal else dimensionner_reference(kw, plafond, h)
    nominale_ref = reference["nominale_kwh"] if reference["faisable"] else None
    puissance_ref = max(kw) - plafond
    tetes = jours[:candidats]
    resultat = {"jours_au_dessus": len(jours), "candidats": [d["jour"] for d in tetes], "nominale_kwh": nominale_ref,
                "par_k": [], "evaluations": 0}
    for k in range(1, min(k_max, len(tetes)) + 1):
        glouton = _sans_jours(kw, jours[:k], plafond, h, puissance_ref, optimal)
        resultat["evaluations"] += 1
        meilleur, choix = glouton, [d["jour"] for d in jours[:k]]
        for combinaison in itertools.combinations(range(len(tetes)), k):
            if combinaison == tuple(range(k)):
                continue  # déjà évaluée : c'est le choix glouton
            n = _sans_jours(kw, [tetes[i] for i in combinaison], plafond, h, puissance_ref, optimal)
            resultat["evaluations"] += 1
            if n is not None and (meilleur is None or n < meilleur - 1e-9):
                meilleur, choix = n, [tetes[i]["jour"] for i in combinaison]
        resultat["par_k"].append({"k": k, "glouton_kwh": glouton, "glouton_jours": [d["jour"] for d in jours[:k]],
                                  "exact_kwh": meilleur, "exact_jours": sorted(choix),
                                  "gain_exact_kwh": (glouton - meilleur) if (glouton is not None and meilleur is not None) else None})
    return resultat


# ---------------------------------------------------------------- utilitaires de profil

def profil_synthetique(jours: int = 14, debut: datetime = datetime(2021, 1, 4), base: float = 100.0,
                       pointes: list[tuple[int, int, float]] | None = None, ouvres_seulement: bool = True) -> tuple[list[float], list[datetime]]:
    """Profil au quart d'heure : `base` kW, plus des pointes (heure début, heure fin, kW) les jours ouvrés."""
    pointes = pointes if pointes is not None else [(8, 10, 200.0)]
    kw, fins = [], []
    for q in range(jours * 96):
        t = debut + timedelta(minutes=15 * q)
        valeur = base
        if not ouvres_seulement or t.weekday() < 5:
            for h1, h2, p in pointes:
                if h1 <= t.hour < h2:
                    valeur = p
        kw.append(valeur)
        fins.append(t + QUART)
    return kw, fins
