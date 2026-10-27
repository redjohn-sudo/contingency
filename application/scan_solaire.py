"""Scan solaire : potentiel photovoltaïque d'un site à partir de sa courbe de charge, sous limite d'injection, avec ou
sans batterie. Quatre scénarios comparés avec les mêmes grandeurs : rien, PV seul, batterie seule, PV et batterie.

Même règle que les autres scans : chaque grandeur porte sa nature (mesure, simule, tarif, declare, hypothese,
a_chiffrer, a_completer). Rien n'est promis : ce sont des bilans d'énergie sur le profil mesuré et une année de
production de référence, pas une prévision.

Production : une année de référence PVGIS (JRC, base SARAH3 et ERA5, pertes système 14 %, inclinaison et orientation
optimales, 1 kWc) fournie dans docs/donnees/pvgis/ pour Paris et Amsterdam (2016), ou un CSV `heure_utc,p_w_par_kwc`
fourni par le client (production mesurée d'une installation voisine, ou PVGIS pour ses coordonnées et sa toiture).
La production horaire est appliquée par calendrier (mois, jour, heure UTC) sur l'année du profil : les deux années ne
sont pas synchrones. Les énergies et les euros sont cumulés sur la période du profil, jamais présentés comme une
économie mesurée. Seul le retour simple utilise une estimation moyenne annualisée sur une base de 365 jours,
si le profil couvre au moins 365 jours. Ce n'est pas une prévision.

Fiche (JSON) :
  identité       nom, exemple, source_profil, licence_profil
  pays           « FR » ou « NL » (règles d'injection et tarifs réseau)
  production     reference_pv : « paris », « amsterdam » ou chemin d'un CSV heure_utc,p_w_par_kwc ; kwc : liste de puissances
                 crête à étudier (par défaut 25 %, 50 % et 100 % de la pointe de soutirage) ; surface_toiture_m2 et
                 m2_par_kwc (hypothèse) bornent la puissance crête si fournis
  injection      limite_injection_kw : 0 (injection nulle), un nombre (capacité d'injection contractée ou physique), ou absent
                 (pas de limite) ; limite_injection_part_kwc : part du kWc étudié ajoutée à limite_injection_kw pour chaque
                 puissance (SDE++ : au plus 0,5, la capacité contractée EN PLUS pour la nouvelle installation ne dépasse pas
                 50 % du piekvermogen, docs/solaire/REGLES-INJECTION.md)
  réseau         NL : gestionnaire (liander, stedin, enexis, obligatoire avec categorie_tarifaire), categorie_tarifaire
                 (MS, TRAFO_MS_LS, TRAFO_HS_TS_MS ; MS_TRANSPORT chez Enexis), gtv_kw ; FR : domaine, option, puissances_souscrites
  prix           prix_achat_eur_kwh (fourniture, taxes comprises, à lire sur la facture), prix_vente_surplus_eur_kwh,
                 prix_pv_eur_kwc [bas, haut], prix_batterie_eur_kwh [bas, haut] ; absents : les euros restent « à compléter »
  batterie       kwh : liste de capacités nominales à étudier (par défaut un quart d'heure et une demi-heure de la pointe de
                 soutirage, soit 0,25 et 0,5 kWh par kW de pointe : 149 et 298 kWh pour 595 kW), hypotheses
                 rendement_aller_retour, profondeur_decharge, puissance_sur_capacite_max
Usage : python application/scan_solaire.py profil.csv fiche.json dossier_sortie/
"""
from __future__ import annotations

import csv
import io
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import profil_france as pf  # noqa: E402

VERSION = "scan-solaire-1"
NATURES = {"mesure", "lu", "simule", "tarif", "declare", "hypothese", "a_chiffrer", "a_completer"}  # lu : valeur du profil dont la qualité n'est pas documentée
REFERENCES_PV = {"paris": ICI.parent / "docs" / "donnees" / "pvgis" / "pvgis-paris-2016-1kwc.csv",
                 "amsterdam": ICI.parent / "docs" / "donnees" / "pvgis" / "pvgis-amsterdam-2016-1kwc.csv"}
HYPOTHESES_DEFAUT: dict[str, dict[str, Any]] = {
    "rendement_aller_retour": {"valeur": 0.90, "unite": ""},
    "profondeur_decharge": {"valeur": 0.90, "unite": ""},
    "puissance_sur_capacite_max": {"valeur": 1.0, "unite": "kW/kWh"},
    "m2_par_kwc": {"valeur": 6.0, "unite": "m²/kWc"},
    "degradation_pv_an": {"valeur": 0.0, "unite": "%/an"},
}
# Tarifs de transport néerlandais 2026 (kW contracté par an, kWmax par mois, en €/kW), un gestionnaire ne se mélange jamais
# avec un autre. Liander relu le 27/09/2026 dans le tarievenblad Liander 2026 publié par l'ACM (feuille 2a : MS 27,48 et 3,57 ;
# Trafo HS+TS/MS 47,88 et 6,24). Stedin et Enexis repris de scan_flex.TARIFS_2026 (nuit/claude, tarievenbladen ACM 2026 relus
# la nuit du 27/09 ; Enexis MS 28,91 et 3,66 confirmés par l'audit Astra sur le PDF Enexis grootzakelijk 01/01/2026).
TARIFS_NL_2026 = {
    "liander": {"TRAFO_MS_LS": {"kw_contrat_an": 44.88, "kwmax_mois": 3.57}, "MS": {"kw_contrat_an": 27.48, "kwmax_mois": 3.57},
                "TRAFO_HS_TS_MS": {"kw_contrat_an": 47.88, "kwmax_mois": 6.24}},
    "stedin": {"TRAFO_MS_LS": {"kw_contrat_an": 47.169, "kwmax_mois": 3.0966}, "MS": {"kw_contrat_an": 24.2737, "kwmax_mois": 3.0966},
               "TRAFO_HS_TS_MS": {"kw_contrat_an": 45.4508, "kwmax_mois": 5.2943}},
    "enexis": {"TRAFO_MS_LS": {"kw_contrat_an": 49.26, "kwmax_mois": 3.66}, "MS": {"kw_contrat_an": 28.91, "kwmax_mois": 3.66},
               "MS_TRANSPORT": {"kw_contrat_an": 27.37, "kwmax_mois": 3.06}, "TRAFO_HS_TS_MS": {"kw_contrat_an": 41.87, "kwmax_mois": 4.46}},
}


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


def _fourchette(v: Any, nom: str) -> None:
    if not (isinstance(v, list) and len(v) == 2 and all(nombre_fini(x) and x >= 0 for x in v) and v[0] <= v[1]):
        raise ValueError(f"Fiche : {nom}, fourchette [bas, haut] de nombres positifs attendue.")


def fiche_controlee(fiche: dict[str, Any]) -> None:
    if not isinstance(fiche, dict):
        raise ValueError("Fiche : objet attendu.")
    import scan_flex
    scan_flex.controle_ean(fiche)  # P2-AB : un EAN numérique a pu perdre des chiffres, refusé avant tout calcul
    if fiche.get("pays") not in ("FR", "NL"):
        raise ValueError("Fiche : pays « FR » ou « NL » obligatoire.")
    ref = fiche.get("reference_pv")
    if ref is not None and ref not in REFERENCES_PV and not Path(str(ref)).exists():
        raise ValueError(f"Fiche : reference_pv {ref!r} inconnue (paris, amsterdam ou chemin d'un CSV existant).")
    for nom in ("kwc", "kwh"):
        liste = fiche.get(nom)
        if liste is not None and not (isinstance(liste, list) and liste and all(nombre_fini(x) and x > 0 for x in liste)):
            raise ValueError(f"Fiche : {nom} doit être une liste de nombres strictement positifs.")
    for nom in ("limite_injection_kw", "surface_toiture_m2", "prix_achat_eur_kwh", "prix_vente_surplus_eur_kwh", "gtv_kw"):
        v = fiche.get(nom)
        if v is not None and not (nombre_fini(v) and v >= 0):
            raise ValueError(f"Fiche : {nom} doit être un nombre fini positif ou nul, reçu {str(v)[:40]!r}.")
    for nom in ("prix_pv_eur_kwc", "prix_batterie_eur_kwh"):
        if fiche.get(nom) is not None:
            _fourchette(fiche[nom], nom)
    gestionnaire = fiche.get("gestionnaire")
    if gestionnaire is not None and gestionnaire not in TARIFS_NL_2026:
        raise ValueError(f"Fiche : gestionnaire inconnu {str(gestionnaire)[:40]!r} ; connus : {', '.join(TARIFS_NL_2026)}.")
    if fiche.get("pays") == "NL" and fiche.get("categorie_tarifaire") is not None:
        if gestionnaire is None:
            raise ValueError(f"Fiche : gestionnaire NL obligatoire avec categorie_tarifaire, parmi {', '.join(TARIFS_NL_2026)}.")
        if fiche["categorie_tarifaire"] not in TARIFS_NL_2026[gestionnaire]:
            raise ValueError(f"Fiche : categorie_tarifaire inconnue chez {gestionnaire} ({', '.join(TARIFS_NL_2026[gestionnaire])}).")
    part = fiche.get("limite_injection_part_kwc")
    if part is not None and not (nombre_fini(part) and 0 <= part <= 1):
        raise ValueError(f"Fiche : limite_injection_part_kwc doit être une part de 0 à 1 du kWc, reçu {str(part)[:40]!r}.")
    for cle, valeur in (fiche.get("hypotheses") or {}).items():
        if cle not in HYPOTHESES_DEFAUT:
            raise ValueError(f"Hypothèse inconnue : {cle}")
        v = valeur["valeur"] if isinstance(valeur, dict) else valeur
        borne = 1.0 if cle in ("rendement_aller_retour", "profondeur_decharge") else math.inf
        if not (nombre_fini(v) and (0 <= v <= borne if cle == "degradation_pv_an" else 0 < v <= borne)):
            raise ValueError(f"Fiche : hypothèse {cle} invalide : {str(v)[:40]!r}.")


# ---------------------------------------------------------------- production de référence

def lire_reference(chemin: Path) -> dict[tuple[int, int, int], float]:
    """CSV heure_utc,p_w_par_kwc (PVGIS ou mesure) : puissance moyenne horaire en W par kWc, indexée par (mois, jour, heure UTC)."""
    lignes = list(csv.DictReader(io.StringIO(chemin.read_text(encoding="utf-8-sig"))))
    if not lignes or not {"heure_utc", "p_w_par_kwc"} <= set(lignes[0]):
        raise ValueError("Référence PV : colonnes heure_utc,p_w_par_kwc attendues.")
    table = {}
    for ligne in lignes:
        t = datetime.fromisoformat(ligne["heure_utc"].replace("Z", "+00:00"))
        p = float(ligne["p_w_par_kwc"])
        if not math.isfinite(p) or p < 0 or p > 1500:
            raise ValueError(f"Référence PV : puissance invalide {ligne['p_w_par_kwc']!r} (0 à 1 500 W par kWc).")
        table[(t.month, t.day, t.hour)] = p
    if len(table) < 8000:
        raise ValueError(f"Référence PV : {len(table)} heures lues, une année entière est attendue.")
    return table


def _reference_w(reference: dict[tuple[int, int, int], float], t: datetime) -> float:
    cle = (t.month, t.day, t.hour)
    if cle not in reference and cle[:2] == (2, 29):  # 29 février d'une année bissextile sans référence : le 28
        cle = (2, 28, t.hour)
    return reference[cle]


def production(reference: dict[tuple[int, int, int], float], fins_utc: list[datetime], pas_h: float, kwc: float) -> list[float]:
    """Production moyenne (kW) sur chaque intervalle du profil, par calendrier (mois, jour, heure UTC) de l'année de
    référence horaire : un intervalle à cheval sur deux heures (profil horaire fini à la demi-heure) prend la moyenne
    des deux, pondérée par le temps passé dans chacune."""
    sortie = []
    for f in fins_utc:
        t = f - timedelta(hours=pas_h)
        wh = 0.0
        while t < f:
            fin_heure = min(f, t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            wh += _reference_w(reference, t) * (fin_heure - t).total_seconds() / 3600
            t = fin_heure
        sortie.append(kwc * wh / pas_h / 1000)
    return sortie


# ---------------------------------------------------------------- bilans

def bilan(charge: list[float], prod: list[float], pas_h: float, limite_injection_kw: float | None, capacite_kwh: float = 0.0,
          puissance_kw: float = 0.0, hyp: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bilan d'énergie pas à pas. Batterie en autoconsommation : elle se charge sur le surplus (puissance et capacité
    utile bornées), se décharge quand la charge dépasse la production ; sans PV, elle ne sert qu'à l'écrêtage et
    reste inactive ici (voir scenario_batterie_seule). Injection limitée à `limite_injection_kw` : le reste est écrêté."""
    h = {k: v["valeur"] for k, v in HYPOTHESES_DEFAUT.items()}
    h.update(hyp or {})
    eta = math.sqrt(h["rendement_aller_retour"])
    utile = capacite_kwh * h["profondeur_decharge"]
    etat = 0.0
    e_charge = e_prod = e_auto = e_import = e_export = e_ecrete = e_batt_in = e_batt_out = 0.0
    pointe_import = 0.0
    importe = []
    for c, p in zip(charge, prod):
        e_charge += c * pas_h
        e_prod += p * pas_h
        direct = min(c, p)
        e_auto += direct * pas_h
        surplus, manque = p - direct, c - direct
        if utile > 0:
            ch = min(surplus, puissance_kw, (utile - etat) / (eta * pas_h))
            etat += ch * pas_h * eta
            surplus -= ch
            e_batt_in += ch * pas_h
            dech = min(manque, puissance_kw, etat * eta / pas_h)
            etat -= dech * pas_h / eta
            manque -= dech
            e_batt_out += dech * pas_h
            e_auto += dech * pas_h
        exporte = surplus if limite_injection_kw is None else min(surplus, limite_injection_kw)
        e_export += exporte * pas_h
        e_ecrete += (surplus - exporte) * pas_h
        e_import += manque * pas_h
        pointe_import = max(pointe_import, manque)
        importe.append(manque)
    return {"charge_kwh": e_charge, "production_kwh": e_prod, "autoconsommee_kwh": e_auto, "importee_kwh": e_import,
            "exportee_kwh": e_export, "ecretee_kwh": e_ecrete, "batterie_chargee_kwh": e_batt_in, "batterie_dechargee_kwh": e_batt_out,
            "taux_autoconsommation": (e_auto / e_prod) if e_prod else None, "taux_autoproduction": (e_auto / e_charge) if e_charge else None,
            "pointe_import_kw": pointe_import, "import_kw": importe}


def kwmax_mois(serie: list[float], fins: list[datetime], pas_h: float) -> float:
    """Somme des maxima mensuels (kW-mois), base du terme kWmax néerlandais ; un intervalle appartient au mois de son
    début (le quart qui finit le 1er du mois à 00:00 est du mois précédent)."""
    maxima: dict[str, float] = {}
    for x, f in zip(serie, fins):
        m = (f - timedelta(hours=pas_h)).strftime("%Y-%m")
        maxima[m] = max(maxima.get(m, 0.0), x)
    return sum(maxima.values())


# ---------------------------------------------------------------- scénarios

def _prix(fiche: dict[str, Any], cle: str) -> float | None:
    v = fiche.get(cle)
    return float(v) if v is not None else None


def valoriser(b: dict[str, Any], base: dict[str, Any], fiche: dict[str, Any], fins: list[datetime], pas_h: float, unite: str,
              tarif_kwmax: float | None, categorie: str | None, gestionnaire: str | None = None) -> dict[str, Any]:
    """Économies estimées sur la période du profil, face au scénario « rien » : achat évité, surplus vendu, kWmax (NL)."""
    achat, vente = _prix(fiche, "prix_achat_eur_kwh"), _prix(fiche, "prix_vente_surplus_eur_kwh")
    evitee = base["importee_kwh"] - b["importee_kwh"]
    resultat = {"energie_evitee_kwh": evitee,
                "economie_achat_eur": (grandeur(round(evitee * achat), unite, "simule", "src_eco_achat", prix=achat) if achat is not None
                                       else grandeur(None, unite, "a_completer", "src_prix_achat")),
                "recette_surplus_eur": (grandeur(round(b["exportee_kwh"] * vente), unite, "simule", "src_recette_surplus", prix=vente) if vente is not None
                                        else grandeur(None, unite, "a_completer", "src_prix_vente"))}
    if tarif_kwmax is not None:
        evites = kwmax_mois(base["import_kw"], fins, pas_h) - kwmax_mois(b["import_kw"], fins, pas_h)
        resultat["kwmax_evites"] = round(evites, 1)
        resultat["economie_reseau_eur"] = grandeur(round(evites * tarif_kwmax), unite, "simule", "src_kwmax", kw_mois=round(evites, 1), tarif=tarif_kwmax,
                                                   categorie=categorie, gestionnaire=(gestionnaire or "").capitalize())
    else:
        resultat["economie_reseau_eur"] = grandeur(None, unite, "a_completer", "src_reseau_fr" if fiche.get("pays") == "FR" else "src_reseau_nl")
    parties = [resultat["economie_achat_eur"], resultat["recette_surplus_eur"], resultat["economie_reseau_eur"]]
    if all(p["nature"] == "simule" for p in parties):
        resultat["economie_totale_eur"] = grandeur(sum(p["valeur"] for p in parties), unite, "simule", "src_eco_totale")
    elif any(p["nature"] == "simule" for p in parties):
        resultat["economie_totale_eur"] = grandeur(sum(p["valeur"] for p in parties if p["nature"] == "simule"), unite, "simule", "src_eco_partielle",
                                                   manque=", ".join(k for k, p in zip(("achat", "vente", "réseau"), parties) if p["nature"] != "simule"))
    else:
        resultat["economie_totale_eur"] = grandeur(None, unite, "a_completer", "src_prix_absents")
    return resultat


def investissement(fiche: dict[str, Any], kwc: float, kwh: float) -> dict[str, Any]:
    pv, bat = fiche.get("prix_pv_eur_kwc"), fiche.get("prix_batterie_eur_kwh")
    parties, manque = [0.0, 0.0], []
    if kwc > 0:
        if pv:
            parties = [parties[0] + kwc * pv[0], parties[1] + kwc * pv[1]]
        else:
            manque.append("PV")
    if kwh > 0:
        if bat:
            parties = [parties[0] + kwh * bat[0], parties[1] + kwh * bat[1]]
        else:
            manque.append("batterie")
    if manque:
        return grandeur(None, "€", "a_completer", "src_prix_invest", manque=" et ".join(manque))
    if kwc == 0 and kwh == 0:
        return grandeur(0, "€", "simule", "src_rien")
    return grandeur([round(parties[0], -2), round(parties[1], -2)], "€", "hypothese", "src_invest", kwc=kwc, kwh=kwh)


def retour(invest: dict[str, Any], economie: dict[str, Any], annee_complete: bool, duree_jours: float = 365.0) -> dict[str, Any]:
    if not annee_complete:
        return grandeur(None, "ans", "a_chiffrer", "src_retour_periode")
    if invest["nature"] != "hypothese" or economie["nature"] != "simule" or not economie["valeur"] or economie["valeur"] <= 0:
        return grandeur(None, "ans", "a_chiffrer", "src_retour_non_chiffre")
    bas, haut = invest["valeur"]
    economie_annuelle_estimee = economie["valeur"] * 365 / duree_jours
    return grandeur([round(bas / economie_annuelle_estimee, 1), round(haut / economie_annuelle_estimee, 1)],
                    "ans", "simule", "src_retour_simple", duree_jours=duree_jours, base_jours=365)


def verdict(sc: dict[str, Any]) -> str:
    r = sc["retour_ans"]
    if sc["kwc"] == 0 and sc["kwh"] == 0:
        return "reference"
    if r["nature"] != "simule":
        return "a_chiffrer"
    return "retenir" if r["valeur"][1] <= 10 else "etudier" if r["valeur"][0] <= 15 else "non_rentable"


def scanner(profil: dict[str, Any], fiche: dict[str, Any], reference: dict[tuple[int, int, int], float] | None = None) -> dict[str, Any]:
    fiche_controlee(fiche)
    valeurs, fins, fins_utc, pas_h = profil["valeurs"], profil["fins"], profil["fins_utc"], profil["pas_h"]
    if len(valeurs) < round(7 * 24 / pas_h) - 8:
        raise ValueError("Scan solaire : au moins une semaine de mesures horodatées.")
    charge, injection_mesuree = pf.separer(valeurs)
    hypotheses = {k: dict(v) for k, v in HYPOTHESES_DEFAUT.items()}
    for cle, valeur in (fiche.get("hypotheses") or {}).items():
        hypotheses[cle]["valeur"] = valeur["valeur"] if isinstance(valeur, dict) else valeur
        if isinstance(valeur, dict) and valeur.get("source"):
            hypotheses[cle]["source"] = valeur["source"]
        else:
            hypotheses[cle]["source_cle"] = "hyp_fiche_sans_source"
    hyp = {k: v["valeur"] for k, v in hypotheses.items()}
    duree_jours = len(charge) * pas_h / 24
    annee_complete = duree_jours >= 365
    unite = "€/periode"
    pointe = max(charge)
    ref_nom = fiche.get("reference_pv")
    if reference is None:
        if ref_nom is None:
            reference = None
        else:
            reference = lire_reference(REFERENCES_PV[ref_nom] if ref_nom in REFERENCES_PV else Path(str(ref_nom)))
    kwc_liste = list(fiche.get("kwc") or [round(pointe * part) for part in (0.25, 0.5, 1.0)])
    kwc_liste = [k for k in kwc_liste if k > 0]
    borne_toiture = None
    if fiche.get("surface_toiture_m2"):
        borne_toiture = fiche["surface_toiture_m2"] / hyp["m2_par_kwc"]
        kwc_liste = sorted({min(k, round(borne_toiture)) for k in kwc_liste if round(borne_toiture) > 0})
    kwh_liste = list(fiche.get("kwh") or [round(pointe * 0.25), round(pointe * 0.5)])
    limite, part_kwc = fiche.get("limite_injection_kw"), fiche.get("limite_injection_part_kwc")

    def limite_pour(kwc: float) -> float | None:
        """Capacité d'injection du scénario : la limite fixe de la fiche, plus la part du kWc étudié si elle est donnée."""
        if part_kwc is None:
            return limite
        return (limite or 0.0) + part_kwc * kwc

    tarif_kwmax, categorie, gestionnaire = None, None, None
    if fiche.get("pays") == "NL" and fiche.get("categorie_tarifaire"):
        categorie, gestionnaire = fiche["categorie_tarifaire"], fiche["gestionnaire"]
        tarif_kwmax = TARIFS_NL_2026[gestionnaire][categorie]["kwmax_mois"]
    hyp_b = {k: hyp[k] for k in ("rendement_aller_retour", "profondeur_decharge", "puissance_sur_capacite_max")}
    base = bilan(charge, [0.0] * len(charge), pas_h, limite_pour(0.0))
    scenarios = []

    def ajouter(nom: str, kwc: float, kwh: float, b: dict[str, Any]) -> dict[str, Any]:
        val = valoriser(b, base, fiche, fins, pas_h, unite, tarif_kwmax, categorie, gestionnaire)
        inv = investissement(fiche, kwc, kwh)
        lim = limite_pour(kwc)
        sc = {"scenario": nom, "kwc": kwc, "kwh": kwh, "puissance_batterie_kw": kwh * hyp["puissance_sur_capacite_max"] if kwh else 0.0,
              "limite_injection_kw": lim,
              "production_kwh": grandeur(round(b["production_kwh"]), "kWh" + unite[1:], "simule", "src_production", kwc=kwc),
              "autoconsommee_kwh": grandeur(round(b["autoconsommee_kwh"]), "kWh" + unite[1:], "simule", "src_bilan"),
              "importee_kwh": grandeur(round(b["importee_kwh"]), "kWh" + unite[1:], "simule", "src_bilan"),
              "exportee_kwh": grandeur(round(b["exportee_kwh"]), "kWh" + unite[1:], "simule", "src_bilan"),
              "ecretee_kwh": grandeur(round(b["ecretee_kwh"]), "kWh" + unite[1:], "simule", "src_ecretage" if lim is not None else "src_sans_limite", limite=lim),
              "taux_autoconsommation": b["taux_autoconsommation"], "taux_autoproduction": b["taux_autoproduction"],
              "pointe_import_kw": grandeur(round(b["pointe_import_kw"], 1), "kW", "simule", "src_bilan"),
              "cycles_batterie": round(b["batterie_dechargee_kwh"] / (kwh * hyp["profondeur_decharge"]), 1) if kwh else None,
              **val, "investissement_eur": inv}
        sc["retour_ans"] = retour(inv, sc["economie_totale_eur"], annee_complete, duree_jours)
        sc["verdict"] = verdict(sc)
        scenarios.append(sc)
        return sc

    ajouter("rien", 0.0, 0.0, base)
    if reference is not None:
        for kwc in kwc_liste:
            prod = production(reference, fins_utc, pas_h, kwc)
            ajouter("pv_seul", kwc, 0.0, bilan(charge, prod, pas_h, limite_pour(kwc)))
    # Batterie seule : écrêtage de la pointe de soutirage (plafond = pointe sans ses 8 h, batterie dimensionnée juste pour
    # le tenir, dimensionnement_batterie), pas d'autoconsommation.
    import dimensionnement_batterie as db
    tri = sorted(charge, reverse=True)
    plafond = tri[min(int(round(8 / pas_h)), len(tri) - 1)]
    if 0 < plafond < pointe:
        dim = db.dimensionner_optimal(charge, plafond, hyp_b, pas_h)
        if dim["faisable"] and dim["nominale_kwh"] > 0:
            sim = db.simuler(charge, plafond, dim["utile_kwh"] * (1 + 1e-6), dim["puissance_kw"], hyp_b, pas_h)
            b = bilan(sim["reseau"], [0.0] * len(charge), pas_h, limite_pour(0.0))
            b["batterie_dechargee_kwh"] = sum(sim["decharge"]) * pas_h
            sc = ajouter("batterie_seule", 0.0, round(dim["nominale_kwh"], 1), b)
            sc["plafond_kw"] = plafond
            sc["puissance_batterie_kw"] = round(dim["puissance_kw"], 1)
    if reference is not None:
        for kwc in kwc_liste:
            prod = production(reference, fins_utc, pas_h, kwc)
            for kwh in kwh_liste:
                ajouter("pv_batterie", kwc, kwh, bilan(charge, prod, pas_h, limite_pour(kwc), kwh, kwh * hyp["puissance_sur_capacite_max"], hyp_b))
    meilleur = None
    chiffres = [s for s in scenarios if s["retour_ans"]["nature"] == "simule"]
    if chiffres:
        meilleur = min(chiffres, key=lambda s: s["retour_ans"]["valeur"][1])
    jeu = pf.jeu_qualite(profil, fiche, VERSION, "Europe/Amsterdam" if fiche["pays"] == "NL" else "Europe/Paris")  # FB1
    nature = "lu" if jeu["reserve_valeurs"] else "mesure"  # P1-AA : une réserve ne prouve pas une mesure directe
    return {"version": VERSION, "jeu_qualite": jeu, "reserves": {"pointe": jeu["reserve_pointe"], "valeurs": jeu["reserve_valeurs"]},
            "site": {k: fiche.get(k) for k in ("nom", "exemple", "source_profil", "licence_profil")},
            "pays": fiche["pays"], "reference_pv": ref_nom, "limite_injection_kw": limite, "limite_injection_part_kwc": part_kwc,
            # Début calculé en UTC puis converti (profil_france.lire) : « fin locale moins le pas » est faux aux changements d'heure (P2-AD).
            "statistiques": {"debut": profil["debuts"][0].isoformat(), "fin": fins[-1].isoformat(), "intervalles": len(charge),
                             "pas_minutes": profil["pas_minutes"], "annee_complete": annee_complete, "duree_jours": duree_jours,
                             "charge_mwh": grandeur(round(sum(charge) * pas_h / 1000, 1), "MWh" + unite[1:], nature),
                             "pointe_kw": grandeur(pointe, "kW", nature), "injection_mwh": grandeur(round(sum(injection_mesuree) * pas_h / 1000, 2), "MWh" + unite[1:], nature)},
            "production_reference": ({"nom": ref_nom, "kwh_par_kwc": round(sum(reference.values()) / 1000, 1)} if reference else None),
            "borne_toiture_kwc": round(borne_toiture, 1) if borne_toiture else None,
            "kwc_etudies": kwc_liste, "kwh_etudies": kwh_liste, "tarif_kwmax": tarif_kwmax, "categorie_tarifaire": categorie, "gestionnaire": gestionnaire,
            "scenarios": scenarios, "meilleur": meilleur["scenario"] + (f" {meilleur['kwc']:g} kWc" if meilleur and meilleur["kwc"] else "") + (f" {meilleur['kwh']:g} kWh" if meilleur and meilleur["kwh"] else "") if meilleur else None,
            "hypotheses": hypotheses, "profil_kw": charge}


def allege(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k != "profil_kw"}


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
    r = scanner(profil, fiche)
    sortie = Path(argv[3])
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "scan-solaire.json").write_text(json.dumps(allege(r), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    import rapport_solaire
    (sortie / "rapport-solaire.html").write_text(rapport_solaire.rendre(r), encoding="utf-8")
    print(f"scan écrit dans {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
