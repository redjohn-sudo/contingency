"""Rapport HTML du scan France (scan_turpe.py), en français, même plan et mêmes conventions que le rapport du scan de
flexibilité : chaque grandeur avec sa nature (Mesuré, Simulé, Publié, Déclaré, Hypothèse, À chiffrer, À compléter) et sa
source, graphiques SVG écrits ici (le rapport s'ouvre hors ligne), lisible sur téléphone et imprimable en A4.
"""
from __future__ import annotations

import html
import math
from datetime import date
from typing import Any

NATURES = {"mesure": "Mesuré", "lu": "Lu", "simule": "Simulé", "tarif": "Publié", "declare": "Déclaré", "hypothese": "Hypothèse",
           "a_chiffrer": "À chiffrer", "a_completer": "À compléter"}
UNITES = {"€/an": "€/an", "€/periode": "€ sur la période", "MWh/an": "MWh/an", "MWh/periode": "MWh sur la période", "h/an": "h/an",
          "h/periode": "h sur la période", "kW": "kW", "kVA": "kVA", "kWh": "kWh", "€": "€", "ans": "ans", "": "", "h": "h", "kW/kWh": "kW par kWh",
          "€/kWh": "€/kWh installé"}
CLASSES_NOMS = {"pointe": "Pointe", "hph": "Heures pleines saison haute", "hch": "Heures creuses saison haute",
                "hpb": "Heures pleines saison basse", "hcb": "Heures creuses saison basse"}
SOURCES = {
    "": "",
    "src_utilisation": "énergie divisée par la pointe",
    "src_lu": "valeur lue dans le profil ; une mesure directe n'est pas établie pour toutes les valeurs nécessaires, voir « Qualité des données »",
    "src_contrat": "option tarifaire et puissances souscrites à lire sur le contrat d'accès au réseau ou la facture",
    "src_cs_puissance": "b1 x P1 + Σ bi x (Pi − Pi−1), option {option}, coefficients en vigueur au {en_vigueur} ({grille})",
    "src_cs_energie": "Σ ci x Ei sur les énergies mesurées par classe, coefficients en vigueur au {en_vigueur} ({grille})",
    "src_cmdps_hta": "estimation : Σ 0,04 x bi x √(({pas}/10) x Σ max(P_moyenne − Pi, 0)²), par mois et classe au pas fourni de {pas} min ; la règle CRE n°2025-78, 5.2.1.5 utilise des mesures à 10 min, non reconstituées ici",
    "src_cmdps_bt36": "α = {alpha} € par heure de dépassement de la puissance apparente souscrite, par mois et par classe ({grille} ; formule CMDPS = α x h, CRE n°2025-78, 5.2.1.6) ; profil au pas de {pas} min",
    "src_total_turpe": "puissance + énergie + dépassements, hors composantes de gestion et de comptage (inchangées)",
    "src_heures_depassement": "durée totale des pas de temps au-dessus de la puissance souscrite de leur classe",
    "src_economie_ps": "coût actuel {actuel} € moins coût aux puissances optimales {optimal} €, même option, même profil",
    "src_economie_option": "coût actuel moins coût aux puissances optimales de l'option {option}",
    "src_cre78_12_mois": "la formule tarifaire d'acheminement se choisit pour 12 mois consécutifs (CRE n°2025-78) ; changement : prestation F160 du catalogue Enedis",
    "src_plafond_fiche": "plafond fixé dans la fiche",
    "src_plafond_heures": "pointe sans ses {heures} heures les plus hautes",
    "src_puissance_optimisee": "puissance qui rend la batterie nominale la plus petite (dimensionnement_batterie.py, dichotomie sur le moteur cyclique vérifié)",
    "src_puissance_minimale": "pointe moins plafond, méthode du scan de flexibilité",
    "src_moteur": "moteur cyclique vérifié (optimisation/moteur.py), puis simulation pas à pas",
    "src_nominale_puissance": "dimensionnée par la puissance : puissance / {crate} C, plus grand que utile / {dod}",
    "src_nominale_energie": "dimensionnée par l'énergie : utile / {dod}, plus grand que puissance / {crate} C",
    "src_nominale_reference": "capacité nominale avec la puissance minimale, pour comparaison",
    "src_energie_dechargee": "énergie déchargée par la batterie sur la période",
    "src_economie_batterie": "coût TURPE aux puissances optimales sans batterie moins coût aux puissances optimales avec batterie",
    "src_invest_prix": "{bas} à {haut} €/kWh installé (voir hypothèses) x {nominale} kWh nominaux",
    "src_invest_a_demander": "prix installé à demander à deux fournisseurs",
    "src_retour_simple": "retour simple, sans actualisation, sur la seule économie de TURPE ; profil de {annees} année(s) : économie de la période ramenée à l'année",
    "src_retour_periode": "profil de moins d'un an : l'économie ne couvre pas une année, retour non calculé",
    "src_retour_non_chiffre": "investissement ou économie non chiffrés",
    "regle_12_mois": "12 mois consécutifs par option, changement par la prestation F160",
    "hyp_heures_ecretees": "plafond visé pour la batterie : la pointe moins ses heures les plus hautes de l'année (nombre ci-contre)",
    "hyp_rendement_aller_retour": "batterie lithium-ion, ordre de grandeur courant, à remplacer par la fiche du fabricant",
    "hyp_profondeur_decharge": "part utilisable de la capacité nominale, à remplacer par la fiche du fabricant",
    "hyp_puissance_sur_capacite_max": "C-rate de décharge rapporté à la capacité nominale (1C : décharge en une heure)",
    "hyp_prix_batterie_eur_kwh": "fourchette du scan néerlandais (installateur charge24.nl, 10/08/2026, 400 à 700 €/kWh installé) : aucun prix français vérifié ne la remplace encore, à remplacer par deux devis",
    "hyp_facteur_puissance": "BT > 36 kVA : les kW mesurés sont divisés par ce facteur pour les comparer aux kVA souscrits ; 0,93 par défaut, car « la puissance souscrite active est égale à la puissance souscrite apparente multipliée par 0,93 » quand le contrôle des dépassements porte sur la puissance active (Enedis, brochure TURPE 7 HTA/BT en vigueur au 01/08/2026, p. 6) ; si le contrôle porte sur la puissance apparente, donner le cos φ du site (fiche : facteur_puissance) ; les moyennes ne restituent pas les dépassements internes aux intervalles",
    "hyp_fiche_sans_source": "valeur fournie dans la fiche sans source",
    "hyp_facteur_fiche": "cos φ fourni dans la fiche",
}
T = {
    "titre": "Scan France, puissances souscrites et dépassements (TURPE 7)",
    "sous_titre": "Courbe de charge {profil}, tarif d'utilisation du réseau public de distribution en vigueur au {en_vigueur}, chaque chiffre avec sa nature et sa source.",
    "exemple": "Exemple sur données publiques réelles avec un contrat fictif : pas un dossier client.",
    "reco_ps_gain": "Ajuster les puissances souscrites aux valeurs optimales : environ {eur} € par an d'économie estimée de TURPE sur le profil mesuré, sans investissement (prestation F170, sous réserve de la puissance de raccordement). Les dépassements sont estimés au pas de {pas} min sur des puissances moyennes, à confronter à la facture avant de changer le contrat.",
    "reco_ps_ok": "Les puissances souscrites actuelles sont déjà celles qui minimisent le TURPE sur ce profil : rien à changer.",
    "reco_ps_sans_contrat": "Fournir l'option tarifaire et les puissances souscrites du contrat pour chiffrer l'économie ; les puissances optimales sont calculées quand même.",
    "reco_option": "Changer d'option pour « {nom} » : {eur} € par an de moins, au prochain terme des 12 mois (prestation F160).",
    "reco_batterie_chiffree": "Une batterie d'écrêtage se rembourse en moins de dix ans sur la seule économie de TURPE : à chiffrer avec deux devis.",
    "reco_batterie_longue": "Une batterie ne se rembourse pas sur la seule économie de TURPE : elle ne se défend qu'avec d'autres revenus (autoconsommation, effacement, arbitrage), à étudier séparément.",
    "reco_batterie_a_chiffrer": "Batterie : investissement ou économie non chiffrés, voir la section correspondante.",
}
COULEURS = {"avant": "#8a8f98", "apres": "#c2410c", "moyenne": "#2563eb", "plafond": "#b91c1c", "ps": "#6d28d9"}
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def e(x: Any) -> str:
    return html.escape(str(x))


def nombre(x: Any, dec: int = 0) -> str:
    if x is None:
        return "–"
    if isinstance(x, bool):
        return "oui" if x else "non"
    if isinstance(x, (list, tuple)):
        return " à ".join(nombre(v, dec) for v in x)
    if not isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, int) or (float(x).is_integer() and abs(x) >= 100):
        dec = 0
    return f"{x:,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", " ")


def pourcent(x: float) -> str:
    return "0 %" if x == 0 else nombre(x * 100, 1) + " %"


def badge(nature: str | None) -> str:
    return f"<span class='n n-{nature}'>{e(NATURES[nature])}</span>" if nature else ""


def _nombre_source(v: Any) -> str:
    if isinstance(v, float):
        t = nombre(v, 4)
        return t.rstrip("0").rstrip(",") if "," in t else t
    return nombre(v) if type(v) is int else str(v)


def source(cle: str, parametres: dict[str, Any] | None) -> str:
    return SOURCES[cle].format(**{k: (_date_fr(v) if k == "en_vigueur" else _nombre_source(v)) for k, v in (parametres or {}).items()})


def valeur(g: dict[str, Any], dec: int = 0) -> str:
    v = g.get("valeur")
    if isinstance(v, str):
        return e(source(v, g.get("parametres")))
    if v is None:
        return "–"
    if isinstance(v, bool):
        return nombre(v)
    return f"{nombre(v, dec)} {e(UNITES.get(g.get('unite', ''), g.get('unite', '')))}".strip()


def ligne(libelle: str, contenu: str, nature: str | None, texte_source: str) -> str:
    return f"<tr><th>{e(libelle)}</th><td>{contenu}</td><td>{badge(nature)}</td><td class='src'>{e(texte_source)}</td></tr>"


def ligne_g(libelle: str, g: dict[str, Any], dec: int = 0) -> str:
    texte = source(g.get("source", ""), g.get("parametres")) or (SOURCES["src_lu"] if g.get("nature") == "lu" else "")
    return ligne(libelle, valeur(g, dec), g.get("nature"), texte)


def _profil_mot(r: dict[str, Any]) -> str:
    """« mesuré » seulement si la qualité de chaque valeur est documentée comme mesure, « lu » sinon (P1-AA)."""
    return "mesuré" if r["statistiques"]["pointe_kw"]["nature"] == "mesure" else "lu"


def tableau(lignes: list[str]) -> str:
    return f"<table class='g'><tr class='entete'><th>Grandeur</th><th>Valeur</th><th>Nature</th><th>Source</th></tr>{''.join(lignes)}</table>"


# ---------------------------------------------------------------- graphiques SVG

def _reduire(valeurs: list[float], cible: int) -> list[float]:
    if len(valeurs) <= cible:
        return valeurs
    taille = len(valeurs) / cible
    return [max(valeurs[int(i * taille):max(int((i + 1) * taille), int(i * taille) + 1)]) for i in range(cible)]


def _haut_rond(v: float) -> float:
    if v <= 0:
        return 1.0
    pas_brut = v / 4
    puissance = 10 ** math.floor(math.log10(pas_brut))
    pas = next(f * puissance for f in (1, 1.5, 2, 2.5, 5, 10) if pas_brut <= f * puissance + 1e-12)
    return 4 * pas


def courbe(series: list[tuple[list[float | None], str, str]], *, lignes: list[tuple[float, str, str]] = (), largeur: int = 760,
           hauteur: int = 230, graduations_x: list[tuple[float, str]] = (), titre: str = "", max_points: int = 900) -> str:
    g, d, h, b = 46, 10, 12, 26
    tous = [v for s, _, _ in series for v in s if v is not None] + [v for v, _, _ in lignes]
    haut = _haut_rond(max(tous) * 1.04 if tous else 1)
    L, H = largeur - g - d, hauteur - h - b
    parts = [f"<svg viewBox='0 0 {largeur} {hauteur}' role='img' aria-label='{e(titre)}' class='graph'>"]
    for k in range(5):
        y = h + H - H * k / 4
        parts.append(f"<line x1='{g}' x2='{g + L}' y1='{y:.1f}' y2='{y:.1f}' stroke='#e5e7eb'/><text x='{g - 6}' y='{y + 4:.1f}' text-anchor='end' class='ax'>{f'{haut * k / 4:g}'.replace('.', ',')}</text>")
    for fx, etiquette in graduations_x:
        parts.append(f"<text x='{g + L * fx:.1f}' y='{hauteur - 8}' text-anchor='middle' class='ax'>{e(etiquette)}</text>")
    for valeurs, couleur, _ in series:
        v = _reduire([x if x is not None else 0 for x in valeurs], max_points)
        if len(v) < 2:
            continue
        pts = " ".join(f"{g + L * i / (len(v) - 1):.1f},{h + H - H * x / haut:.1f}" for i, x in enumerate(v))
        parts.append(f"<polyline fill='none' stroke='{couleur}' stroke-width='1.3' points='{pts}'/>")
    for v, etiquette, couleur in lignes:
        y = h + H - H * v / haut
        parts.append(f"<line x1='{g}' x2='{g + L}' y1='{y:.1f}' y2='{y:.1f}' stroke='{couleur}' stroke-dasharray='5 4'/>"
                     f"<text x='{g + L - 4}' y='{y - 5:.1f}' text-anchor='end' class='ax' fill='{couleur}'>{e(etiquette)}</text>")
    parts.append("</svg>")
    legende = "".join(f"<span><i style='background:{c}'></i>{e(nom)}</span>" for _, c, nom in series)
    return f"<figure>{''.join(parts)}<figcaption>{legende}</figcaption></figure>"


def barres(etiquettes: list[str], series: list[tuple[list[float], str, str]], largeur: int = 760, hauteur: int = 210) -> str:
    g, d, h, b = 46, 10, 12, 26
    haut = _haut_rond(max(max(s) for s, _, _ in series) * 1.04 if any(s for s, _, _ in series) else 1)
    L, H = largeur - g - d, hauteur - h - b
    pas = L / max(1, len(etiquettes))
    parts = [f"<svg viewBox='0 0 {largeur} {hauteur}' class='graph' role='img'>"]
    for k in range(5):
        y = h + H - H * k / 4
        parts.append(f"<line x1='{g}' x2='{g + L}' y1='{y:.1f}' y2='{y:.1f}' stroke='#e5e7eb'/><text x='{g - 6}' y='{y + 4:.1f}' text-anchor='end' class='ax'>{f'{haut * k / 4:g}'.replace('.', ',')}</text>")
    w = pas * 0.7 / len(series)
    for i, et in enumerate(etiquettes):
        for j, (s, c, _) in enumerate(series):
            v = s[i]
            parts.append(f"<rect x='{g + pas * i + pas * 0.15 + j * w:.1f}' y='{h + H - H * v / haut:.1f}' width='{w:.1f}' height='{H * v / haut:.1f}' fill='{c}'/>")
        parts.append(f"<text x='{g + pas * i + pas / 2:.1f}' y='{hauteur - 8}' text-anchor='middle' class='ax'>{e(et)}</text>")
    parts.append("</svg>")
    legende = "".join(f"<span><i style='background:{c}'></i>{e(nom)}</span>" for _, c, nom in series)
    return f"<figure>{''.join(parts)}<figcaption>{legende}</figcaption></figure>"


# ---------------------------------------------------------------- sections

# ---------------------------------------------------------------- qualité des données (FB1) et réserves (P1-W, P1-V)

TITRES_RESERVES = ("3. Situation actuelle", "4. Redimensionner les puissances souscrites", "5. Batterie d'écrêtage",
                   "6. Les pas de temps qui décident", "7. Niveau de confiance")


def _page_qualite(r: dict[str, Any]) -> str:
    """Page « Qualité des données » rendue par rapport_flex._section_qualite depuis le jeu de profil_france.jeu_qualite
    (scan_flex.qualite_jeu au pas natif et dans la zone du profil), sans copie."""
    jeu = r.get("jeu_qualite")
    if not jeu:
        return ""
    import rapport_flex
    return rapport_flex._section_qualite(jeu, "fr")


def _reserve_textes(r: dict[str, Any]) -> dict[str, str]:
    """Textes des réserves, tirés du catalogue d'Astra (jamais réécrits) : valeurs non mesurées, pointe non mesurée."""
    constats = {c["code"]: c for c in (r.get("jeu_qualite") or {}).get("qualite_donnees", {}).get("constats", [])}
    if not constats:
        return {}
    import rapport_flex
    from messages_fiabilite import CODES_POINTE  # QUALITE_POINTE_NON_MESUREE au quart d'heure, _INTERVALLE_ hors 15 min
    textes = {"valeurs": constats["QUALITE_VALEURS_NON_MESUREES"]} if "QUALITE_VALEURS_NON_MESUREES" in constats else {}
    textes.update({"pointe": constats[code] for code in CODES_POINTE if code in constats})
    return {cle: rapport_flex._constat_texte(c, "fr") for cle, c in textes.items()}


def _reserver(r: dict[str, Any], section: str) -> str:
    """« À confirmer » dans le titre et sous le titre de chaque section dont les résultats dépendent de valeurs non
    mesurées ; la batterie porte aussi la réserve sur la pointe. Les chiffres restent, à titre indicatif."""
    textes = _reserve_textes(r)
    if not textes.get("valeurs"):
        return section
    for titre in TITRES_RESERVES:
        note = textes["valeurs"] + ((" " + textes["pointe"]) if titre.startswith("5.") and textes.get("pointe") else "")
        section = section.replace(f"<h2>{titre}</h2>", f"<h2>{titre} (à confirmer)</h2><p class='afaire'>À confirmer : {e(note)}</p>")
    return section


def _style_qualite() -> str:
    import rapport_flex
    return rapport_flex.STYLE_QUALITE


def _date_fr(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" + (f" à {iso[11:16]}" if len(iso) > 10 else "")


def _section_synthese(r: dict[str, Any]) -> str:
    st, a, o, b, rac = r["statistiques"], r["actuel"], r["optimisation"], r["batterie"], r["raccordement"]
    u = rac["unite_puissance"]
    points = [f"Profil {_profil_mot(r)} : pointe de {nombre(st['pointe_kw']['valeur'])} kW le {_date_fr(st['instant_pointe'])}, {valeur(st['energie_mwh'], 1)}, "
              f"{nombre(st['heures_utilisation']['valeur'])} h d'utilisation, au pas de {st['pas_minutes']} min."]
    if a.get("disponible"):
        points.append(f"Contrat actuel ({e(_nom_option(a['option']))}, {', '.join(nombre(p) for p in a['ps'])} {u}) : "
                      f"{valeur(a['total_eur'])} de TURPE dont {valeur(a['cmdps_eur'])} de dépassements sur {nombre(a['heures_depassement']['valeur'], 1)} h.")
        if o["economie_eur"]["valeur"] is not None:
            points.append(f"Puissances optimales {', '.join(nombre(p) for p in o['ps'])} {u} : {valeur(o['economie_eur'])} d'économie estimée, sans investissement (dépassements estimés au pas de {st['pas_minutes']} min). Simulé.")
    else:
        points.append(f"Puissances optimales calculées : {', '.join(nombre(p) for p in o['ps'])} {u} ({e(_nom_option(o['option']))}) ; fournir le contrat pour chiffrer l'économie.")
    if r["options"]["meilleure"] and r["options"]["gain_vs_actuel"] and (r["options"]["gain_vs_actuel"]["valeur"] or 0) > 0 and r["options"]["meilleure"] != (a.get("option")):
        points.append(f"Option la moins chère sur ce profil : {e(_nom_option(r['options']['meilleure']))}, {valeur(r['options']['gain_vs_actuel'])} de moins que le contrat actuel.")
    if b.get("faisable"):
        points.append(f"Batterie qui tient {nombre(b['plafond_kw']['valeur'])} kW : {nombre(b['puissance_kw']['valeur'])} kW et {nombre(b['capacite_nominale_kwh']['valeur'], 1)} kWh nominaux, "
                      f"{valeur(b['economie_supplementaire_eur'])} de TURPE en plus, retour {valeur(b['retour_ans'], 1)}. Simulé.")
    q = r.get("quarts_decisifs")
    if q and q["sans_jours"]:
        s = q["sans_jours"][-1]
        points.append(f"{nombre(q['jours_au_dessus'])} jours au-dessus des puissances optimales ; sans les {s['jours_retires']} plus lourds, "
                      f"les dépassements tomberaient à {nombre(s['cmdps_eur'])} €. Un calcul, pas une baisse réalisable sans l'ingénieur du site.")
    for cle in ("valeurs", "pointe"):
        if _reserve_textes(r).get(cle):
            points.append(f"À confirmer : {e(_reserve_textes(r)[cle])}")
    return f"<h2>L'essentiel</h2><ul class='syn'>{''.join(f'<li>{p}</li>' for p in points)}</ul>"


def _nom_option(option: str) -> str:
    import turpe
    return turpe.NOMS_OPTIONS.get(option, option)


def _section_site(r: dict[str, Any]) -> str:
    st, rac, site, prof = r["statistiques"], r["raccordement"], r["site"], r["profil"]
    lignes = [ligne("Domaine de tension", e("HTA" if rac["domaine"] == "HTA" else "BT > 36 kVA"), "declare", "fiche"),
              ligne("Option tarifaire", e(_nom_option(rac["option"])), rac["option_nature"], "fiche" if rac["option_nature"] == "declare" else "option prise par défaut, à confirmer sur le contrat"),
              ligne("Grille tarifaire", e(f"TURPE 7 HTA-BT, coefficients en vigueur au {_date_fr(rac['grille_en_vigueur'])}"), "tarif", rac["grille_source"]),
              ligne("Période lue", e(f"du {_date_fr(st['debut'])} au {_date_fr(st['fin'])}, {nombre(st['jours'])} jours, {nombre(st['intervalles'])} pas de {st['pas_minutes']} min"), st["pointe_kw"]["nature"], "courbe de charge fournie" + (" (horodatages avec décalage)" if prof["fuseau_lu"] == "offset" else " (horodatages lus en heure légale française)")),
              ligne_g("Consommation", st["energie_mwh"], 1), ligne_g("Pointe", st["pointe_kw"]), ligne_g("Puissance moyenne", st["moyenne_kw"], 1),
              ligne_g("Heures d'utilisation", st["heures_utilisation"])]
    if rac.get("puissance_raccordement_kw"):
        lignes.append(ligne("Puissance de raccordement", f"{nombre(rac['puissance_raccordement_kw'])} kW", "declare", "fiche : borne des puissances souscrites"))
    if st.get("injection_mwh"):
        lignes.append(ligne_g(f"Injection {'mesurée' if _profil_mot(r) == 'mesuré' else 'lue'} (non traitée ici)", st["injection_mwh"], 2))
    notes = []
    if _reserve_textes(r).get("pointe"):
        notes.append("À confirmer : " + _reserve_textes(r)["pointe"])
    if prof["approximation_10min"]:
        notes.append(f"Estimation de la CMDPS HTA au pas de {st['pas_minutes']} min : les carrés des dépassements des puissances moyennes fournies sont pondérés par {st['pas_minutes'] / 10:g}, puis sommés par mois et classe avant la racine carrée. Les mesures réglementaires à 10 minutes ne sont pas reconstituées. L'estimation peut surestimer ou sous-estimer le montant facturé ; aucun sens d'écart n'est garanti. Coûts, économies et puissances optimales héritent de cette approximation : à confronter aux mesures à 10 minutes et à la facture du site.")
    if not st["annee_complete"]:
        notes.append(f"Le profil couvre {pourcent(st['fraction_annee'])} d'une année : les coûts de puissance (annuels) sont ramenés à la période, les économies ne valent que pour elle.")
    elif st["fraction_annee"] > 1:
        notes.append(f"Le profil couvre {nombre(st['fraction_annee'], 2)} années : puissance, énergie et dépassements sont cumulés sur toute la période (montants « sur la période », pas par an) ; seul le retour de la batterie ramène l'économie à l'année.")
    cal = rac["calendrier"]
    notes.append(f"Calendrier appliqué : saison haute mois {', '.join(str(m) for m in cal['saison_haute_mois'])} ; heures creuses {', '.join(f'{a} h à {b} h' for a, b in cal['heures_creuses'])}"
                 + (f" ; pointe fixe {', '.join(f'{a} h à {b} h' for a, b in cal['pointe_fixe_plages'])} de décembre à février hors dimanche" if rac["domaine"] == "HTA" else "")
                 + (f" ; {len(cal['pointe_mobile_jours'])} jours de pointe mobile fournis" if cal["pointe_mobile_jours"] else "")
                 + ". " + ("Valeurs fournies dans la fiche : " + ", ".join(rac["calendrier_fourni"]) + " ; le reste par défaut." if rac["calendrier_fourni"] else "Toutes par défaut : les heures creuses et de pointe sont locales, à remplacer par celles publiées par Enedis pour le site."))
    return f"<h2>1. Site, contrat et mesure</h2>{tableau(lignes)}" + "".join(f"<p class='src'>{e(n)}</p>" for n in notes)


def _section_profils(r: dict[str, Any]) -> str:
    p, st, kw = r["profils"], r["statistiques"], r["profil_kw"]
    annuel = p["annuel"]
    positions: dict[str, list[int]] = {}
    for i, j in enumerate(annuel):
        positions.setdefault(j["jour"][:7], []).append(i)
    n = max(len(annuel) - 1, 1)
    grad_mois = [((sum(v) / len(v)) / n, MOIS[int(m[5:]) - 1]) for m, v in positions.items()]
    parts = [f"<h2>2. Profil {_profil_mot(r)}</h2><h3>Année : maximum et moyenne de chaque jour</h3>",
             courbe([([j["max_kw"] for j in annuel], COULEURS["avant"], "maximum du jour"), ([j["moyenne_kw"] for j in annuel], COULEURS["moyenne"], "moyenne du jour")],
                    graduations_x=grad_mois, titre="profil annuel")]
    npj = p["pas_par_jour"]
    semaine = [v for jour in p["semaine_type"] for v in jour]
    parts.append("<h3>Semaine type (moyenne par pas de temps)</h3>" + courbe([(semaine, COULEURS["moyenne"], "moyenne")], graduations_x=[((i + 0.5) / 7, j) for i, j in enumerate(JOURS)], titre="semaine type"))
    parts.append(f"<h3>Jour de la pointe ({_date_fr(p['jour_pointe']['jour'])})</h3>" + courbe([(p["jour_pointe"]["kw"], COULEURS["avant"], _profil_mot(r))], graduations_x=[(h / 24, f"{h:02d}:00") for h in range(0, 25, 3)], titre="jour de pointe"))
    heures = len(kw) * st["pas_minutes"] / 60
    pas_g = 1000 if heures > 3000 else 100 if heures > 300 else 10
    parts.append("<h3>Courbe monotone</h3>" + courbe([(p["monotone"], COULEURS["avant"], "puissance classée")], graduations_x=[(x / heures, f"{nombre(x)} h") for x in range(0, int(heures) + 1, pas_g * 2)], titre="monotone"))
    cl = r["classes"]
    lignes = "".join(f"<tr><td>{e(CLASSES_NOMS[c])}</td><td>{nombre(v['heures'])}</td><td>{nombre(v['energie_kwh'] / 1000, 1)}</td><td>{nombre(v['pointe_kw'])}</td></tr>" for c, v in cl.items())
    parts.append(f"<h3>Par classe temporelle</h3><div class='defile'><table class='num'><tr><th>Classe</th><th>Heures</th><th>MWh</th><th>Pointe kW</th></tr>{lignes}</table></div>")
    return "".join(parts)


def _section_actuel(r: dict[str, Any]) -> str:
    a, rac = r["actuel"], r["raccordement"]
    if not a.get("disponible"):
        return (f"<h2>3. Situation actuelle</h2><p class='afaire'>À compléter : {', '.join(a['manque'])}. Sans le contrat, les dépassements et l'économie ne peuvent pas être chiffrés ; "
                "les puissances optimales de la section 4 sont calculées pour l'option prise par défaut.</p>")
    u = rac["unite_puissance"]
    lignes = [ligne("Puissances souscrites", e(", ".join(f"{CLASSES_NOMS[c]} {nombre(p)} {u}" for c, p in zip(r["classes"], a["ps"]))), "declare", "contrat, fiche"),
              ligne_g("Composante de soutirage, puissance", a["puissance_eur"]), ligne_g("Composante de soutirage, énergie", a["energie_eur"]),
              ligne_g("Dépassements (CMDPS)", a["cmdps_eur"]), ligne_g("Heures de dépassement", a["heures_depassement"], 1), ligne_g("Total TURPE (hors gestion et comptage)", a["total_eur"])]
    mois = sorted(a["par_mois"])
    cmdps_mois = [sum(c["eur"] for c in a["par_mois"][m].values()) for m in mois]
    graphe = barres([MOIS[int(m[5:]) - 1] for m in mois], [(cmdps_mois, COULEURS["apres"], "CMDPS calculée (€)")]) if any(cmdps_mois) else "<p class='src'>Aucun dépassement sur la période.</p>"
    classes = "".join(f"<tr><td>{e(CLASSES_NOMS[c])}</td><td>{nombre(v['eur'])}</td><td>{nombre(v['heures'], 1)}</td><td>{nombre(v['depassement_max'], 1)}</td><td>{nombre(v['mois'])}</td></tr>" for c, v in a["par_classe"].items() if v["eur"] > 0)
    tableau_classes = (f"<div class='defile'><table class='num'><tr><th>Classe</th><th>CMDPS €</th><th>Heures</th><th>Dépassement max {u}</th><th>Mois concernés</th></tr>{classes}</table></div>" if classes else "")
    conf = a.get("confrontation_facture")
    texte_conf = ""
    if conf:
        texte_conf = (f"<p class='cle'>Confrontation à la facture : sur {nombre(len(conf['mois']))} mois communs, CMDPS calculée {nombre(conf['calcule_eur'])} € contre {nombre(conf['facture_eur'])} € facturés"
                      + (f", écart {pourcent(conf['ecart_part'])}." if conf["ecart_part"] is not None else ".")
                      + " Un écart au-delà de quelques pour cent signale un pas de temps, un calendrier local ou une puissance différents de ceux du calcul.</p>")
    return f"<h2>3. Situation actuelle</h2>{tableau(lignes)}<h3>Dépassements par mois</h3>{graphe}{tableau_classes}{texte_conf}"


def _section_optimisation(r: dict[str, Any]) -> str:
    o, a, rac, opts = r["optimisation"], r["actuel"], r["raccordement"], r["options"]
    u = rac["unite_puissance"]
    lignes = [ligne("Puissances optimales", e(", ".join(f"{CLASSES_NOMS[c]} {nombre(p)} {u}" for c, p in zip(r["classes"], o["ps"]))), "simule",
                    "programmation dynamique sur le profil : puissances entières, croissantes d'une classe à la suivante (Pi+1 ≥ Pi)" + (f", au plus {nombre(o['puissance_raccordement_kw'])} kW de raccordement" if o.get("puissance_raccordement_kw") else "")),
              ligne_g("Composante de soutirage, puissance", o["puissance_eur"]), ligne_g("Dépassements restants (CMDPS)", o["cmdps_eur"]),
              ligne_g("Total TURPE aux puissances optimales", o["total_eur"]), ligne_g("Économie par rapport au contrat actuel", o["economie_eur"])]
    if a.get("disponible") and o.get("ecarts_ps"):
        lignes.append(ligne("Écart par classe (optimal moins actuel)", e(", ".join(f"{CLASSES_NOMS[c]} {'+' if d > 0 else ''}{nombre(d)}" for c, d in zip(r["classes"], o["ecarts_ps"]))), "simule", "à demander par la prestation F170 du catalogue Enedis"))
    notes = ""
    if o["classes_sans_mesure"]:
        notes += f"<p class='afaire'>Classes sans aucune mesure sur la période : {', '.join(CLASSES_NOMS[c] for c in o['classes_sans_mesure'])}. Leur puissance optimale affichée est le minimum : garder la valeur actuelle.</p>"
    if rac["domaine"] == "HTA":
        notes += "<p class='src'>Un dépassement peut rester à l'optimum. Ordre de grandeur donné par la CRE pour la HTA : le coefficient 0,04 est calibré pour qu'au-delà d'une centaine d'heures de dépassement en ruban, souscrire la puissance coûte moins cher que la CMDPS (CRE n°2025-78, 4.3.3.3) ; cette calibration vaut pour des heures regroupées dans un même mois, la racine étant prise mois par mois. Le moteur ne s'appuie pas sur ce seuil : il compare les deux coûts mois par mois et classe par classe.</p>"
    else:
        notes += "<p class='src'>Un dépassement peut rester à l'optimum. En BT > 36 kVA, la CMDPS se paie par heure de dépassement (α = {alpha} €/h) alors qu'un kVA souscrit de plus coûte bi par an : dépasser d'un kVA plus de bi/α heures dans l'année, soit environ une à deux heures selon la classe, coûte déjà plus cher que le souscrire. Le moteur compare les deux coûts mois par mois et classe par classe.</p>".format(alpha=nombre(r['optimisation']['cmdps_eur']['parametres'].get('alpha'), 2))
    lignes_opt = "".join(
        (f"<tr><td>{e(l['nom'])}{' (actuelle)' if a.get('disponible') and l['option'] == a['option'] else ''}</td><td>{', '.join(nombre(p) for p in l['ps'])}</td><td>{nombre(l['puissance_eur'])}</td><td>{nombre(l['energie_eur'])}</td><td>{nombre(l['cmdps_eur'])}</td><td><b>{nombre(l['total_eur'])}</b></td></tr>"
         if l["disponible"] else f"<tr><td>{e(l['nom'])}</td><td colspan='5' class='src'>indisponible : {e(l['raison'])}</td></tr>") for l in opts["lignes"])
    tableau_opt = f"<div class='defile'><table class='num comp'><tr><th>Option</th><th>Puissances optimales ({u})</th><th>Puissance €</th><th>Énergie €</th><th>CMDPS €</th><th>Total €</th></tr>{lignes_opt}</table></div>"
    gain = ligne_g("Gain de la meilleure option sur le contrat actuel", opts["gain_vs_actuel"]) if opts.get("gain_vs_actuel") else ""
    regle = ligne_g("Règle de changement", opts["regle"])
    return f"<h2>4. Redimensionner les puissances souscrites</h2>{tableau(lignes)}{notes}<h3>Les options tarifaires, chacune à ses puissances optimales</h3>{tableau_opt}{tableau([gain, regle]) if gain else tableau([regle])}"


def _section_batterie(r: dict[str, Any]) -> str:
    b = r["batterie"]
    if not b.get("faisable"):
        return f"<h2>5. Batterie d'écrêtage</h2><p class='src'>Non calculée : {e(b.get('raison', ''))}.</p>"
    u = r["raccordement"]["unite_puissance"]
    lignes = [ligne_g("Plafond tenu par la batterie", b["plafond_kw"]), ligne_g("Puissance de la batterie", b["puissance_kw"], 1), ligne_g("Puissance minimale (méthode du scan)", b["puissance_minimale_kw"], 1),
              ligne_g("Capacité utile", b["capacite_utile_kwh"], 1), ligne_g("Capacité nominale", b["capacite_nominale_kwh"], 1), ligne_g("Capacité nominale à puissance minimale", b["nominale_reference_kwh"], 1),
              ligne_g("Énergie déchargée", b["energie_dechargee_mwh"], 2),
              ligne("Puissances souscrites avec la batterie", e(", ".join(f"{CLASSES_NOMS[c]} {nombre(p)} {u}" for c, p in zip(r["classes"], b["ps"]))), "simule", "ré-optimisées sur le profil vu du réseau"),
              ligne_g("Dépassements restants", b["cmdps_eur"]), ligne_g("Total TURPE avec batterie", b["total_eur"]), ligne_g("Économie en plus du redimensionnement", b["economie_supplementaire_eur"]),
              ligne_g("Investissement", b["investissement_eur"]), ligne_g("Retour simple", b["retour_ans"], 1)]
    kw, apres = r["profil_kw"], b["profil_apres"]
    i = kw.index(max(kw))
    npj = r["profils"]["pas_par_jour"]
    debut = i - i % npj
    graphe = courbe([(kw[debut:debut + npj], COULEURS["avant"], _profil_mot(r)), (apres[debut:debut + npj], COULEURS["apres"], "avec batterie")],
                    lignes=[(b["plafond_kw"]["valeur"], "plafond", COULEURS["plafond"])], graduations_x=[(h / 24, f"{h:02d}:00") for h in range(0, 25, 3)], titre="jour de pointe avec batterie")
    note = ("<p class='src'>La batterie est dimensionnée en choisissant sa puissance avec sa capacité : une puissance un peu plus grande que la pointe moins le plafond recharge plus vite entre deux pointes et peut rendre la batterie plus petite"
            + (f" (ici {nombre(b['gain_dimensionnement_kwh'], 1)} kWh de moins)" if b["gain_dimensionnement_kwh"] > 0.05 else " (ici sans effet : la puissance minimale est déjà optimale)") + ". Le calcul suppose une prévision parfaite des pointes : borne optimiste. Le retour ne compte que l'économie de TURPE, pas l'autoconsommation, l'effacement ni l'arbitrage.</p>")
    return f"<h2>5. Batterie d'écrêtage</h2>{tableau(lignes)}<h3>Jour de la pointe</h3>{graphe}{note}"


def _section_decisifs(r: dict[str, Any]) -> str:
    q = r.get("quarts_decisifs")
    if not q:
        return "<h2>6. Les pas de temps qui décident</h2><p class='src'>Aucun dépassement aux puissances optimales : rien ne décide.</p>"
    u = r["raccordement"]["unite_puissance"]
    top = "".join(f"<tr><td>{e(_date_fr(t['debut']))}</td><td>{nombre(t['kw'], 1)}</td><td>{e(CLASSES_NOMS[t['classe']])}</td><td>{nombre(t['depassement_kw'], 1)}</td></tr>" for t in q["top"])
    jours = "".join(f"<tr><td>{e(_date_fr(j['jour']))}</td><td>{pourcent(j['part'])}</td></tr>" for j in q["jours"])
    sans = "".join(f"<tr><td>{nombre(s['jours_retires'])}</td><td>{nombre(s['cmdps_eur'])}</td><td>{', '.join(nombre(p) for p in s['ps'])}</td><td>{nombre(s['total_eur'])}</td></tr>" for s in q["sans_jours"])
    return (f"<h2>6. Les pas de temps qui décident</h2><p>{nombre(q['jours_au_dessus'])} jours dépassent les puissances optimales. Les plus lourds, par leur part de la somme des carrés des dépassements (HTA) ou des heures (BT) :</p>"
            f"<div class='defile'><table class='num'><tr><th>Jour</th><th>Part des dépassements</th></tr>{jours}</table></div>"
            f"<h3>Les huit pas de temps les plus hauts au-dessus de leur puissance souscrite</h3><div class='defile'><table class='num'><tr><th>Début</th><th>kW</th><th>Classe</th><th>Dépassement {u}</th></tr>{top}</table></div>"
            f"<h3>Si ces jours étaient restés sous les puissances souscrites</h3><div class='defile'><table class='num'><tr><th>Jours retirés</th><th>CMDPS €</th><th>Puissances optimales</th><th>Total TURPE €</th></tr>{sans}</table></div>"
            "<p class='afaire'>Ces calculs ne disent pas qu'une pointe peut baisser. Décaler ou réduire un usage demande l'examen des process et la validation de l'ingénieur du site. Simulé.</p>")


def _section_confiance(r: dict[str, Any]) -> str:
    c = r.get("confiance")
    if not c:
        return "<h2>7. Niveau de confiance</h2><p class='src'>Non calculé (moins de 14 jours complets, ou tirages à 0 dans la fiche).</p>"
    t = c["total_eur"]
    ps = " ; ".join(f"{CLASSES_NOMS[cl]} {nombre(b['p5'])} à {nombre(b['p95'])} (médiane {nombre(b['mediane'])})" for cl, b in zip(r["classes"], c["ps"]))
    return (f"<h2>7. Niveau de confiance</h2><p>{nombre(c['tirages'])} années tirées jour par jour parmi les {nombre(c['jours_reechantillonnes'])} jours mesurés (même mois, même type de jour, graine {c['graine']}). "
            f"Total TURPE aux puissances optimales : {nombre(t['p5'])} à {nombre(t['p95'])} € (médiane {nombre(t['mediane'])} €). Puissances optimales : {ps}.</p>"
            "<p class='src'>Limites : aucune journée plus haute que la plus haute mesurée ne peut apparaître, donc l'intervalle sous-estime le risque de pointe ; les jours fériés comptent comme des jours ouvrés ; une année de croissance ou de météo plus rude n'est pas couverte. Simulé.</p>")


def _section_recommandation(r: dict[str, Any]) -> str:
    lignes = []
    for l in r["recommandation"]:
        prefixe = "À confirmer : " if _reserve_textes(r).get("valeurs") else ""
        lignes.append(f"<li>{e(prefixe + T[l['cle']].format(eur=nombre(l.get('eur')), nom=l.get('nom', ''), pas=r['statistiques']['pas_minutes']))}</li>")
    return f"<h2>8. Recommandation</h2><ol>{''.join(lignes)}</ol>"


def _section_hypotheses(r: dict[str, Any]) -> str:
    lignes = []
    for cle, h in r["hypotheses"].items():
        texte = h.get("source") or SOURCES.get(h.get("source_cle", "hyp_" + cle), "")
        lignes.append(ligne(cle.replace("_", " "), f"{nombre(h['valeur'], 2)} {e(UNITES.get(h.get('unite', ''), h.get('unite', '')))}".strip(), "hypothese", texte))
    return f"<h2>9. Hypothèses et sources</h2>{tableau(lignes)}<p class='src'>Règles et coefficients : docs/france/TURPE-REGLES.md (délibérations de la CRE, brochure Enedis, catalogue des prestations) ; grille appliquée : {e(r['raccordement']['grille_source'])}. Le TURPE seul est calculé : ni fourniture, ni taxes, ni composantes de gestion et de comptage.</p>"


STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:58rem;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#1f2328;background:#fff}"
    "h1{font-size:1.6rem;margin-bottom:.2rem}h2{font-size:1.15rem;margin-top:2.4rem;border-bottom:1px solid #d0d7de;padding-bottom:.3rem}"
    "h3{font-size:1rem;margin-top:1.6rem}table{border-collapse:collapse;width:100%;margin:.6rem 0;font-size:.9rem}th,td{text-align:left;padding:.35rem .5rem;"
    "border-bottom:1px solid #eaeef2;vertical-align:top}th{font-weight:600}table.num td{font-variant-numeric:tabular-nums}"
    ".src{color:#57606a;font-size:.8rem}.n{display:inline-block;font-size:.72rem;padding:.05rem .4rem;border-radius:3px;border:1px solid;white-space:nowrap}"
    ".n-mesure{color:#1f2328;border-color:#1f2328}.n-simule{color:#b45309;border-color:#b45309}.n-tarif{color:#57606a;border-color:#8c959f}"
    ".n-hypothese{color:#6d28d9;border-color:#6d28d9}.n-a_chiffrer,.n-a_completer{color:#b91c1c;border-color:#b91c1c}.n-declare{color:#0e7490;border-color:#0e7490}"
    ".afaire{border-left:3px solid #b91c1c;padding:.4rem .8rem;background:#fff5f5}.exemple{border:1px solid #d0d7de;background:#f6f8fa;padding:.6rem .9rem}"
    ".cle{border-left:3px solid #1f2328;padding:.4rem .8rem;background:#f6f8fa}.syn{background:#f6f8fa;border:1px solid #d0d7de;padding:.8rem 1rem .8rem 2rem}.syn li{margin:.3rem 0}"
    "figure{margin:.4rem 0 1rem}.graph{width:100%;height:auto}.ax{font-size:10px;fill:#57606a}figcaption{font-size:.8rem;color:#57606a;display:flex;gap:1rem;flex-wrap:wrap}"
    "figcaption i{display:inline-block;width:14px;height:3px;margin-right:.35rem;vertical-align:middle}.defile{overflow-x:auto}table.comp{min-width:44rem}ol li{margin:.5rem 0}"
    "footer{margin-top:2.5rem;color:#57606a;font-size:.85rem;border-top:1px solid #d0d7de;padding-top:1rem}td,th{overflow-wrap:anywhere}table.num td,table.num th,table.g th,table.g td:not(.src){overflow-wrap:normal}"
    "@media (max-width:40rem){body{margin:1rem auto}table{font-size:.84rem}th,td{padding:.3rem}table.g,table.g tbody{display:block}table.g tr{display:grid;grid-template-columns:1fr auto;gap:.15rem .6rem;"
    "padding:.45rem 0;border-bottom:1px solid #eaeef2}table.g th,table.g td{border:0;padding:0}table.g th{grid-column:1/-1}table.g td.src{grid-column:1/-1}table.g tr.entete{display:none}table.g td:empty{display:none}}"
    "@media print{body{max-width:none;margin:0;font-size:10.5pt}h2{break-after:avoid}figure,tr{break-inside:avoid}.defile{overflow:visible}table.comp{min-width:0;font-size:8pt}.syn,.cle,.afaire,.exemple{break-inside:avoid}}"
)


def rendre(r: dict[str, Any]) -> str:
    site = r["site"]
    entete = f"<h1>{e(T['titre'])} : {e(site.get('nom') or '')}</h1><p class='src'>{e(T['sous_titre'].format(en_vigueur=_date_fr(r['raccordement']['grille_en_vigueur']), profil='mesurée' if _profil_mot(r) == 'mesuré' else "lue (une mesure directe n'est pas établie pour toutes les valeurs nécessaires)"))}</p>"
    if site.get("exemple"):
        entete += f"<p class='exemple'>{e(T['exemple'])}</p>"
    corps = [entete, _page_qualite(r), _section_synthese(r), _section_site(r), _section_profils(r)]
    corps += [_reserver(r, s) for s in (_section_actuel(r), _section_optimisation(r), _section_batterie(r), _section_decisifs(r), _section_confiance(r))]
    corps += [_section_recommandation(r), _section_hypotheses(r),
             f"<p class='src'>{e(site.get('source_profil') or '')} {e(site.get('licence_profil') or '')}</p>",
             f"<footer>Rapport généré le {date.today().strftime('%d/%m/%Y')} par Contingency, {e(r['version'])}. Chaque chiffre porte sa nature ; un chiffre sans source n'y entre pas.</footer>"]
    return (f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(T['titre'])}</title><style>{STYLE}{_style_qualite()}</style></head><body>{''.join(corps)}</body></html>")
