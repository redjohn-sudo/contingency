"""TURPE 7 HTA-BT (France, Enedis) : classes temporelles, composantes de soutirage et de dépassement, optimisation
des puissances souscrites.

Sources relues le 27/09/2026 (textes intégraux sauvegardés hors dépôt, extraits dans docs/france/TURPE-REGLES.md) :
  [CRE-78]   Délibération CRE n°2025-78 du 13 mars 2025, TURPE 7 HTA-BT, parties 4.3.3.3 (CMDPS), 5.2.1.5 (HTA) et
             5.2.1.6 (BT > 36 kVA). En vigueur depuis le 1er août 2025.
  [CRE-105]  Délibération CRE n°2026-105 du 21 mai 2026, évolution au 1er août 2026 (+3,04 %), annexe 2 : coefficients
             applicables au 1er août 2026.
  [ENEDIS]   Enedis, « Tarifs d'utilisation des réseaux publics de distribution d'électricité, tarifs en vigueur au
             1er août 2026 », TURPE 7 HTA/BT, p. 6 (puissance souscrite active en BT > 36 kVA), 10-11 (HTA),
             14-15 (BT > 36 kVA), 22 (heures de pointe).
  [CAT]      Enedis, catalogue des prestations, version en vigueur au 1er août 2026, fiches F160 (modification de formule
             tarifaire d'acheminement) et F170 (modification de la puissance souscrite).

Ce que dit le tarif (formules copiées des sources) :
  HTA, 5 classes temporelles i : pointe (1), heures pleines saison haute (2), heures creuses saison haute (3), heures
  pleines saison basse (4), heures creuses saison basse (5). Puissances souscrites Pi par multiples de 1 kW, Pi+1 ≥ Pi.
     CS    = b1·P1 + Σ(i=2..5) bi·(Pi − Pi−1) + Σ(i=1..5) ci·Ei                       [CRE-78 5.2.1.5]
     CMDPS = Σ(classes i du mois) 0,04 · bi · √(Σ ΔP²), ΔP en kW par pas de 10 minutes  [CRE-78 5.2.1.5, ENEDIS p. 11]
  BT > 36 kVA, 4 classes : HPH (1), HCH (2), HPB (3), HCB (4). Puissances souscrites apparentes Pi en kVA, Pi+1 ≥ Pi.
     CS    = b1·P1 + Σ(i=2..4) bi·(Pi − Pi−1) + Σ ci·Ei                                 [CRE-78 5.2.1.6]
     CMDPS = α · h par plage temporelle et par mois, h = durée de dépassement en heures, α = 12,79 €/h au 1er août 2026
             [CRE-105 annexe 2, ENEDIS p. 15]. Plafonnement sur demande si la CMDPS dépasse à la fois 30 % de la facture
             TURPE mensuelle et 25 fois le tarif de la puissance supplémentaire nécessaire [CRE-78 5.2.1.6].
             « Pour les points de connexion raccordés en BT > 36 kVA et dont le contrôle des dépassements de la puissance
             souscrite est effectué sur la puissance souscrite active, celle-ci est égale à la puissance souscrite
             apparente multipliée par 0,93. » [ENEDIS p. 6] : les kW mesurés sont comparés à 0,93 × Pi (facteur 0,93
             par défaut dans scan_turpe) ; si le contrôle porte sur la puissance apparente, la fiche donne le cos φ du site.
  Calendrier : saison haute = décembre à février plus 61 jours, par défaut novembre à mars ; heures de pointe fixe
  (HTA) de décembre à février inclus, 2 h le matin entre 8 h et 12 h et 2 h le soir entre 17 h et 21 h, hors dimanche ;
  dimanches entièrement en heures creuses en HTA ; 8 heures creuses par jour fixées localement par le GRD ; pointe mobile
  (HTA) : jours publiés la veille par RTE, au plus 22 par an de novembre à mars, plages 7 h-10 h et 17 h-20 h
  [ENEDIS p. 10 et 22, CRE-78 5.2.1.5]. Les heures exactes sont locales : celles-ci sont des hypothèses par défaut à
  remplacer par les heures publiées pour le site.
  Changement : la formule tarifaire d'acheminement est choisie pour 12 mois consécutifs [CRE-78] ; la modification de
  puissance souscrite est la prestation F170 du catalogue, possible tant que la puissance reste disponible sur le
  raccordement (au-delà de la puissance de raccordement : devis) [CAT].

La CMDPS HTA réglementaire utilise des mesures à 10 minutes. Le moteur conserve le pas fourni et calcule, par mois
et classe, 0,04 × bi × sqrt((pas_minutes/10) × somme(max(P_moyenne − Pi, 0)²)). Hors pas de 10 minutes, c'est une
estimation conventionnelle : aucune mesure à 10 minutes n'est reconstituée. L'écart avec la facturation peut aller
dans les deux sens ; aucune garantie de minoration ou de majoration, notamment au pas de 15 minutes.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np

CLASSES = {"HTA": ["pointe", "hph", "hch", "hpb", "hcb"], "BT36": ["hph", "hch", "hpb", "hcb"]}
UNITE_PUISSANCE = {"HTA": "kW", "BT36": "kVA"}
OPTIONS = {"HTA": ["cu_pointe_fixe", "lu_pointe_fixe", "cu_pointe_mobile", "lu_pointe_mobile"], "BT36": ["cu", "lu"]}
NOMS_OPTIONS = {"cu_pointe_fixe": "courte utilisation, pointe fixe", "lu_pointe_fixe": "longue utilisation, pointe fixe",
                "cu_pointe_mobile": "courte utilisation, pointe mobile", "lu_pointe_mobile": "longue utilisation, pointe mobile",
                "cu": "courte utilisation", "lu": "longue utilisation"}
PUISSANCE_MIN = {"HTA": 1, "BT36": 37}  # BT > 36 kVA : le domaine commence strictement au-dessus de 36 kVA

# Coefficients bi en €/kW/an (HTA) ou €/kVA/an (BT > 36 kVA), ci en c€/kWh, dans l'ordre des classes.
GRILLES = {
    "2026-08": {
        "en_vigueur": "2026-08-01", "source": "CRE n°2026-105, annexe 2 ; Enedis, brochure du 01/08/2026",
        "HTA": {"cu_pointe_fixe": {"b": [14.85, 14.85, 14.85, 12.93, 11.56], "c": [5.91, 4.36, 2.05, 1.04, 0.71]},
                "lu_pointe_fixe": {"b": [36.40, 33.28, 21.01, 14.77, 11.91], "c": [2.73, 2.16, 1.51, 0.95, 0.70]},
                "cu_pointe_mobile": {"b": [14.85, 14.85, 14.85, 12.93, 11.56], "c": [7.22, 4.17, 2.05, 1.04, 0.71]},
                "lu_pointe_mobile": {"b": [39.43, 35.34, 21.01, 14.77, 11.91], "c": [3.25, 1.93, 1.51, 0.95, 0.70]}},
        "BT36": {"cu": {"b": [18.15, 16.45, 15.00, 12.34], "c": [7.12, 4.34, 2.19, 1.57]},
                 "lu": {"b": [31.08, 21.82, 17.15, 12.75], "c": [5.86, 3.58, 2.07, 1.54]}},
        "cmdps": {"HTA": {"cp": 0.04}, "BT36": {"alpha_eur_h": 12.79}},
        "gestion_eur_an": {"HTA": 264.96, "BT36": 132.47},  # composante annuelle de gestion hors Rf et Ccard [CRE-105 annexe 2]
    },
    "2025-08": {
        "en_vigueur": "2025-08-01", "source": "CRE n°2025-78, 5.2.1.5 et 5.2.1.6",
        "HTA": {"cu_pointe_fixe": {"b": [14.41, 14.41, 14.41, 12.55, 11.22], "c": [5.74, 4.23, 1.99, 1.01, 0.69]},
                "lu_pointe_fixe": {"b": [35.33, 32.30, 20.39, 14.33, 11.56], "c": [2.65, 2.10, 1.47, 0.92, 0.68]},
                "cu_pointe_mobile": {"b": [14.41, 14.41, 14.41, 12.55, 11.22], "c": [7.01, 4.05, 1.99, 1.01, 0.69]},
                "lu_pointe_mobile": {"b": [38.27, 34.30, 20.39, 14.33, 11.56], "c": [3.15, 1.87, 1.47, 0.92, 0.68]}},
        "BT36": {"cu": {"b": [17.61, 15.96, 14.56, 11.98], "c": [6.91, 4.21, 2.13, 1.52]},
                 "lu": {"b": [30.16, 21.18, 16.64, 12.37], "c": [5.69, 3.47, 2.01, 1.49]}},
        "cmdps": {"HTA": {"cp": 0.04}, "BT36": {"alpha_eur_h": 12.41}},
        "gestion_eur_an": {"HTA": None, "BT36": None},
    },
}
GRILLE_DEFAUT = "2026-08"

# Calendrier par défaut : les valeurs marquées « hypothèse » sont locales chez Enedis et doivent venir du site.
CALENDRIER_DEFAUT: dict[str, Any] = {
    "saison_haute_mois": [11, 12, 1, 2, 3],          # défaut de la délibération [CRE-78] ; 61 jours placés localement
    "heures_creuses": [[22, 6]],                       # hypothèse : 8 heures creuses consécutives, à remplacer par les heures locales
    "pointe_fixe_mois": [12, 1, 2],                    # [CRE-78, ENEDIS p. 22]
    "pointe_fixe_plages": [[9, 11], [18, 20]],         # hypothèse : 2 h dans 8 h-12 h et 2 h dans 17 h-21 h, placées localement
    "pointe_mobile_plages": [[7, 10], [17, 20]],       # [ENEDIS p. 10 et 22]
    "pointe_mobile_jours": [],                         # dates ISO publiées par RTE, à fournir dans la fiche
}


def _dans_plages(heure: int, plages: list[list[int]]) -> bool:
    for debut, fin in plages:
        if debut < fin and debut <= heure < fin:
            return True
        if debut >= fin and (heure >= debut or heure < fin):  # plage de nuit, 22 h à 6 h
            return True
    return False


def classe_instant(debut: datetime, domaine: str, option: str, calendrier: dict[str, Any] | None = None) -> str:
    """Classe temporelle de l'intervalle qui commence à `debut` (heure légale française, sans fuseau)."""
    cal = {**CALENDRIER_DEFAUT, **(calendrier or {})}
    mois, heure, dimanche = debut.month, debut.hour, debut.weekday() == 6
    if domaine == "HTA":
        if option.endswith("pointe_fixe"):
            if mois in cal["pointe_fixe_mois"] and not dimanche and _dans_plages(heure, cal["pointe_fixe_plages"]):
                return "pointe"
        elif option.endswith("pointe_mobile"):
            if debut.date().isoformat() in cal["pointe_mobile_jours"] and _dans_plages(heure, cal["pointe_mobile_plages"]):
                return "pointe"
        else:
            raise ValueError(f"Option HTA inconnue : {option}")
        creuse = dimanche or _dans_plages(heure, cal["heures_creuses"])
    elif domaine == "BT36":
        if option not in OPTIONS["BT36"]:
            raise ValueError(f"Option BT > 36 kVA inconnue : {option}")
        creuse = _dans_plages(heure, cal["heures_creuses"])  # « tous les jours comprennent 8 heures creuses » [CRE-78 5.2.1.6]
    else:
        raise ValueError(f"Domaine inconnu : {domaine} (HTA ou BT36).")
    haute = mois in cal["saison_haute_mois"]
    return ("hch" if creuse else "hph") if haute else ("hcb" if creuse else "hpb")


def classes_profil(debuts: list[datetime], domaine: str, option: str, calendrier: dict[str, Any] | None = None) -> list[int]:
    """Indice de classe (dans CLASSES[domaine]) de chaque intervalle."""
    noms = CLASSES[domaine]
    return [noms.index(classe_instant(d, domaine, option, calendrier)) for d in debuts]


def controler_puissances(ps: list[float], domaine: str) -> None:
    n = len(CLASSES[domaine])
    if len(ps) != n:
        raise ValueError(f"{n} puissances souscrites attendues pour {domaine}, reçu {len(ps)}.")
    for i, p in enumerate(ps):
        if not isinstance(p, (int, float)) or isinstance(p, bool) or not math.isfinite(p) or p < PUISSANCE_MIN[domaine]:
            raise ValueError(f"Puissance souscrite de la classe {CLASSES[domaine][i]} invalide : {p!r} (au moins {PUISSANCE_MIN[domaine]} {UNITE_PUISSANCE[domaine]}).")
        if i and p < ps[i - 1]:
            raise ValueError(f"Puissances souscrites non croissantes : {CLASSES[domaine][i]} ({p}) < {CLASSES[domaine][i - 1]} ({ps[i - 1]}) ; la règle est Pi+1 ≥ Pi.")


def grille(domaine: str, option: str, version: str = GRILLE_DEFAUT) -> dict[str, Any]:
    if version not in GRILLES:
        raise ValueError(f"Grille inconnue : {version} ; connues : {', '.join(GRILLES)}.")
    if domaine not in CLASSES:
        raise ValueError(f"Domaine inconnu : {domaine}.")
    if option not in GRILLES[version][domaine]:
        raise ValueError(f"Option {option} inconnue pour {domaine} ; options : {', '.join(OPTIONS[domaine])}.")
    g = GRILLES[version]
    return {"b": g[domaine][option]["b"], "c": g[domaine][option]["c"], "cmdps": g["cmdps"][domaine],
            "gestion_eur_an": g["gestion_eur_an"][domaine], "version": version, "en_vigueur": g["en_vigueur"], "source": g["source"]}


def cout_puissance(ps: list[float], b: list[float]) -> float:
    """b1·P1 + Σ bi·(Pi − Pi−1), €/an."""
    return b[0] * ps[0] + sum(b[i] * (ps[i] - ps[i - 1]) for i in range(1, len(ps)))


def energies_par_classe(valeurs: list[float], classes: list[int], n_classes: int, pas_h: float) -> list[float]:
    e = [0.0] * n_classes
    for v, k in zip(valeurs, classes):
        e[k] += max(v, 0.0) * pas_h
    return e


def cout_energie(energies_kwh: list[float], c: list[float]) -> float:
    return sum(ci / 100 * e for ci, e in zip(c, energies_kwh))


def cmdps_mensuelle(valeurs: list[float], classes: list[int], mois: list[str], ps: list[float], domaine: str,
                    b: list[float], cmdps: dict[str, float], pas_minutes: int, facteur_puissance: float = 1.0) -> dict[str, Any]:
    """Estimation par mois et classe. HTA : 0,04·bi·√((pas_minutes/10)·Σ max(P_moyenne−Pi,0)²), au pas fourni.
    Hors pas de 10 minutes : ni reconstitution des mesures réglementaires, ni garantie sur le sens de l'écart.
    BT > 36 kVA : α·h, h = durée des intervalles dont la puissance moyenne apparente (kW / cos φ) dépasse Pi.
    Cette durée issue de moyennes n'est pas une mesure du temps réel de dépassement à l'intérieur des intervalles."""
    if not (0 < facteur_puissance <= 1):
        raise ValueError("facteur_puissance : cos φ dans ]0, 1] attendu.")
    par_mois: dict[str, list[list[float]]] = {}
    for v, k, m in zip(valeurs, classes, mois):
        par_mois.setdefault(m, [[] for _ in ps])[k].append(v)
    resultat, total = {}, 0.0
    for m, listes in par_mois.items():
        resultat[m] = {}
        for k, vals in enumerate(listes):
            if domaine == "HTA":
                somme = sum((v - ps[k]) ** 2 for v in vals if v > ps[k]) * (pas_minutes / 10)
                montant = cmdps["cp"] * b[k] * math.sqrt(somme)
                heures = sum(1 for v in vals if v > ps[k]) * pas_minutes / 60
            else:
                heures = sum(1 for v in vals if v / facteur_puissance > ps[k]) * pas_minutes / 60
                montant = cmdps["alpha_eur_h"] * heures
            resultat[m][CLASSES[domaine][k]] = {"eur": montant, "heures": heures,
                                                "depassement_max": max((v / (facteur_puissance if domaine == "BT36" else 1) - ps[k] for v in vals), default=0.0)}
            total += montant
    return {"par_mois": resultat, "total_eur": total, "mois": len(par_mois)}


def fraction_annee(n_intervalles: int, pas_h: float) -> float:
    """Durée du profil en années (n × pas / 365 jours) : les coefficients bi sont annuels, la CMDPS est mensuelle et
    l'énergie est cumulée ; pour que les trois portent sur la même période, la puissance est multipliée par cette
    fraction, inférieure à 1 sur un profil partiel, supérieure à 1 sur plusieurs années. Une année de 365 ou 366 jours
    vaut exactement 1 (seul cas où les montants sont des €/an)."""
    if n_intervalles <= 0 or pas_h <= 0:
        raise ValueError("fraction_annee : profil vide.")
    jours = n_intervalles * pas_h / 24
    return 1.0 if 365 <= jours <= 366 else jours / 365


def cout_total(valeurs: list[float], classes: list[int], mois: list[str], ps: list[float], domaine: str, option: str,
               pas_minutes: int, version: str = GRILLE_DEFAUT, facteur_puissance: float = 1.0, fraction: float = 1.0) -> dict[str, Any]:
    """Composantes de soutirage (puissance et énergie) et de dépassement pour des puissances souscrites données, sur la
    période du profil : la puissance (annuelle) est multipliée par `fraction` (durée du profil en années), l'énergie et
    la CMDPS sont celles de la période. Sur un an, fraction vaut 1 et tout est annuel ; sur deux ans, tout est cumulé."""
    controler_puissances(ps, domaine)
    if not fraction > 0:
        raise ValueError("fraction : durée du profil en années, strictement positive, attendue.")
    g = grille(domaine, option, version)
    energies = energies_par_classe(valeurs, classes, len(ps), pas_minutes / 60)
    depassements = cmdps_mensuelle(valeurs, classes, mois, ps, domaine, g["b"], g["cmdps"], pas_minutes, facteur_puissance)
    puissance = cout_puissance(ps, g["b"]) * fraction
    energie = cout_energie(energies, g["c"])
    return {"puissance_eur": puissance, "energie_eur": energie, "cmdps_eur": depassements["total_eur"],
            "total_eur": puissance + energie + depassements["total_eur"], "energies_kwh": energies,
            "cmdps": depassements, "ps": list(ps), "option": option, "grille": g["version"], "fraction_annee": fraction}


# ---------------------------------------------------------------- optimisation des puissances souscrites

def _cmdps_par_puissance(vals: np.ndarray, grille_p: np.ndarray, domaine: str, b_i: float, cmdps: dict[str, float],
                         pas_minutes: int, facteur_puissance: float) -> np.ndarray:
    """CMDPS d'un mois et d'une classe pour chaque puissance souscrite de `grille_p` (vectorisé)."""
    if vals.size == 0:
        return np.zeros_like(grille_p, dtype=float)
    if domaine == "BT36":
        vals = vals / facteur_puissance
    tri = np.sort(vals)
    k = vals.size - np.searchsorted(tri, grille_p, side="right")  # nombre de valeurs strictement au-dessus de P
    if domaine == "BT36":
        return cmdps["alpha_eur_h"] * k * pas_minutes / 60
    s1 = np.concatenate(([0.0], np.cumsum(tri[::-1])))          # sommes des k plus grandes valeurs
    s2 = np.concatenate(([0.0], np.cumsum((tri[::-1]) ** 2)))
    somme = s2[k] - 2 * grille_p * s1[k] + k * grille_p ** 2
    somme = np.maximum(somme, 0.0) * (pas_minutes / 10)
    return cmdps["cp"] * b_i * np.sqrt(somme)


def optimiser_puissances(valeurs: list[float], classes: list[int], mois: list[str], domaine: str, option: str, pas_minutes: int,
                         version: str = GRILLE_DEFAUT, puissance_max: float | None = None, facteur_puissance: float = 1.0,
                         fraction: float = 1.0) -> dict[str, Any]:
    """Puissances souscrites entières, croissantes, qui minimisent puissance + CMDPS sur la période (l'énergie ne dépend pas
    des puissances). Programmation dynamique classe par classe : f_i(P) = bi·P + CMDPS_i(P) + min(P' ≤ P) [f_i−1(P') − bi·P'].
    `puissance_max` : puissance de raccordement, borne haute. `fraction` : durée du profil en années, appliquée aux bi
    annuels (voir fraction_annee). Les classes sans aucune mesure sont signalées : leur puissance optimale (le minimum)
    n'a pas de sens, garder la valeur actuelle."""
    g = grille(domaine, option, version)
    if not fraction > 0:
        raise ValueError("fraction : durée du profil en années, strictement positive, attendue.")
    b = [x * fraction for x in g["b"]]
    n = len(CLASSES[domaine])
    if not valeurs or len(valeurs) != len(classes) or len(valeurs) != len(mois):
        raise ValueError("Profil, classes et mois doivent avoir la même longueur non nulle.")
    haut = int(math.ceil(max(max(valeurs) / (facteur_puissance if domaine == "BT36" else 1), PUISSANCE_MIN[domaine]))) + 1
    if puissance_max is not None:
        if puissance_max < PUISSANCE_MIN[domaine]:
            raise ValueError("puissance_max sous le minimum du domaine.")
        haut = min(haut, int(math.floor(puissance_max)))
    grille_p = np.arange(PUISSANCE_MIN[domaine], haut + 1, dtype=float)
    valeurs_np, classes_np = np.asarray(valeurs, dtype=float), np.asarray(classes)
    mois_np = np.asarray(mois)
    couts_classe = []
    sans_mesure = []
    for k in range(n):
        masque = classes_np == k
        if not masque.any():
            sans_mesure.append(CLASSES[domaine][k])
        total = np.zeros_like(grille_p)
        for m in np.unique(mois_np[masque]):
            total += _cmdps_par_puissance(valeurs_np[masque & (mois_np == m)], grille_p, domaine, g["b"][k], g["cmdps"], pas_minutes, facteur_puissance)
        couts_classe.append(total)
    f = b[0] * grille_p + couts_classe[0]
    choix = []  # pour chaque classe i ≥ 1, l'indice de P_i−1 retenu pour chaque P_i
    for k in range(1, n):
        gk = f - b[k] * grille_p
        prefixe = np.minimum.accumulate(gk)
        indices = np.arange(gk.size)
        pos = np.maximum.accumulate(np.where(gk <= prefixe, indices, 0))
        choix.append(pos)
        f = b[k] * grille_p + couts_classe[k] + prefixe
    i_fin = int(np.argmin(f))
    ps = [0] * n
    ps[n - 1] = int(grille_p[i_fin])
    i = i_fin
    for k in range(n - 1, 0, -1):
        i = int(choix[k - 1][i])
        ps[k - 1] = int(grille_p[i])
    detail = cout_total(valeurs, classes, mois, ps, domaine, option, pas_minutes, version, facteur_puissance, fraction)
    return {"ps": ps, "cout_puissance_cmdps_eur": float(f[i_fin]), "detail": detail, "classes_sans_mesure": sans_mesure,
            "puissance_max": puissance_max, "grille_points": int(grille_p.size), "fraction_annee": fraction}


def comparer_options(valeurs: list[float], debuts: list[datetime], domaine: str, pas_minutes: int, version: str = GRILLE_DEFAUT,
                     calendrier: dict[str, Any] | None = None, puissance_max: float | None = None, facteur_puissance: float = 1.0,
                     options: list[str] | None = None) -> dict[str, Any]:
    """Pour chaque option du domaine : puissances optimales et coût total (puissance, énergie, dépassements) sur la période."""
    mois = [d.strftime("%Y-%m") for d in debuts]
    fraction = fraction_annee(len(valeurs), pas_minutes / 60)
    resultats = {}
    for option in options or OPTIONS[domaine]:
        if option.endswith("pointe_mobile") and not (calendrier or {}).get("pointe_mobile_jours"):
            resultats[option] = {"disponible": False, "raison": "jours de pointe mobile non fournis (publiés par RTE)"}
            continue
        classes = classes_profil(debuts, domaine, option, calendrier)
        opt = optimiser_puissances(valeurs, classes, mois, domaine, option, pas_minutes, version, puissance_max, facteur_puissance, fraction)
        resultats[option] = {"disponible": True, **opt}
    disponibles = {k: v for k, v in resultats.items() if v["disponible"]}
    meilleure = min(disponibles, key=lambda k: disponibles[k]["detail"]["total_eur"]) if disponibles else None
    return {"options": resultats, "meilleure": meilleure}


def date_grille(jour: date | None = None) -> str:
    """Version de grille en vigueur à une date (par défaut la plus récente)."""
    if jour is None:
        return GRILLE_DEFAUT
    candidates = [v for v, g in GRILLES.items() if date.fromisoformat(g["en_vigueur"]) <= jour]
    if not candidates:
        raise ValueError(f"Aucune grille connue en vigueur au {jour.isoformat()} (TURPE 7 commence le 01/08/2025).")
    return max(candidates, key=lambda v: GRILLES[v]["en_vigueur"])
