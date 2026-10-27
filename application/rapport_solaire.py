"""Rapport HTML du scan solaire (scan_solaire.py), en français : quatre familles de scénarios avec les mêmes grandeurs,
chaque chiffre avec sa nature et sa source. Reprend le style et les aides du rapport France (rapport_turpe.py)."""
from __future__ import annotations

from datetime import date
from typing import Any

from rapport_turpe import STYLE, _page_qualite, _profil_mot, _reserve_textes, _style_qualite, badge, courbe, e, ligne, nombre, pourcent, tableau

NOMS = {"rien": "Rien (référence)", "pv_seul": "PV seul", "batterie_seule": "Batterie seule (écrêtage)", "pv_batterie": "PV et batterie"}
VERDICTS = {"reference": "référence", "retenir": "à retenir", "etudier": "à étudier", "non_rentable": "non rentable sur ces seuls revenus", "a_chiffrer": "à chiffrer"}
SOURCES = {
    "": "",
    "src_production": "{kwc} kWc x production horaire de référence, appliquée par calendrier sur l'année du profil",
    "src_bilan": "bilan d'énergie pas à pas sur le profil mesuré",
    "src_ecretage": "surplus au-delà de la capacité d'injection du scénario ({limite} kW), non injecté",
    "src_sans_limite": "aucune limite d'injection déclarée : rien n'est écrêté",
    "src_eco_achat": "énergie non achetée x {prix} €/kWh (fiche)",
    "src_recette_surplus": "énergie injectée x {prix} €/kWh (fiche)",
    "src_kwmax": "{kw_mois} kW-mois évités x {tarif} €/kW/mois, tarievenblad {gestionnaire} 2026 ({categorie}), ACM",
    "src_reseau_fr": "économie de TURPE : passer le profil net dans le scan France (scan_turpe.py) avec le contrat",
    "src_reseau_nl": "terme kWmax non chiffré : indiquer gestionnaire et catégorie tarifaire dans la fiche",
    "src_prix_achat": "prix d'achat de l'électricité à lire sur la facture (fiche : prix_achat_eur_kwh)",
    "src_prix_vente": "prix de vente du surplus (fiche : prix_vente_surplus_eur_kwh ; France : tarif S21 ou contrat, Pays-Bas : contrat de fourniture)",
    "src_eco_totale": "achat évité + surplus vendu + réseau",
    "src_eco_partielle": "somme des postes chiffrés seulement ; manque : {manque}",
    "src_prix_absents": "aucun prix dans la fiche",
    "src_prix_invest": "prix installé à fournir dans la fiche ({manque}), deux devis",
    "src_rien": "aucun investissement",
    "src_invest": "{kwc} kWc et {kwh} kWh aux prix de la fiche (fourchettes)",
    "src_retour_simple": "retour simple estimé, sans actualisation : investissement / (économie estimée sur {duree_jours} jours x {base_jours} / {duree_jours}), hors postes non chiffrés ; aucune économie mesurée",
    "src_retour_periode": "profil de moins d'un an : retour non calculé",
    "src_retour_non_chiffre": "investissement ou économie non chiffrés",
    "hyp_rendement_aller_retour": "batterie lithium-ion, ordre de grandeur courant, à remplacer par la fiche du fabricant",
    "hyp_profondeur_decharge": "part utilisable de la capacité nominale, à remplacer par la fiche du fabricant",
    "hyp_puissance_sur_capacite_max": "C-rate de charge et de décharge rapporté à la capacité nominale (1C)",
    "hyp_m2_par_kwc": "surface de toiture par kWc, ordre de grandeur pour borner la puissance crête ; à remplacer par le plan de calepinage",
    "hyp_degradation_pv_an": "non appliquée dans ce bilan sur la période, même si elle couvre plusieurs années",
    "hyp_fiche_sans_source": "valeur fournie dans la fiche sans source",
}


def source(cle: str, p: dict[str, Any] | None) -> str:
    return SOURCES[cle].format(**{k: (nombre(v, 2) if isinstance(v, float) else v) for k, v in (p or {}).items()})


def val(g: dict[str, Any], dec: int = 0) -> str:
    v = g.get("valeur")
    if v is None:
        return "–"
    u = g.get("unite", "")
    u = {"€/an": "€/an", "€/periode": "€ sur la période", "kWh/an": "kWh/an", "kWh/periode": "kWh sur la période", "MWh/periode": "MWh sur la période", "ans": "ans", "€": "€", "kW": "kW"}.get(u, u)
    return f"{nombre(v, dec)} {e(u)}".strip()


def lg(libelle: str, g: dict[str, Any], dec: int = 0) -> str:
    return ligne(libelle, val(g, dec), g.get("nature"), source(g.get("source", ""), g.get("parametres")))


def _suffixe(r: dict[str, Any]) -> str:
    """« , à confirmer » sur chaque verdict et titre quand les valeurs nécessaires ne sont pas des mesures (P1-V)."""
    return ", à confirmer" if _reserve_textes(r).get("valeurs") else ""


def _synthese(r: dict[str, Any]) -> str:
    st = r["statistiques"]
    pts = [f"Période du profil : du {st['debut']} au {st['fin']} ({nombre(st['duree_jours'], 2)} jours).",
           f"Profil {_profil_mot(r)} : {val(st['charge_mwh'], 1)} de soutirage, pointe {nombre(st['pointe_kw']['valeur'])} kW, au pas de {st['pas_minutes']} min."]
    if r["production_reference"]:
        pts.append(f"Production de référence {(r['production_reference']['nom'] or 'fournie').capitalize()} : {nombre(r['production_reference']['kwh_par_kwc'])} kWh par kWc et par an ; "
                   f"puissances étudiées {', '.join(nombre(k) for k in r['kwc_etudies'])} kWc" + (f", bornées par la toiture à {nombre(r['borne_toiture_kwc'])} kWc" if r.get("borne_toiture_kwc") else "") + ".")
    else:
        pts.append("Aucune référence de production fournie : seuls les scénarios sans PV sont chiffrés.")
    lim, part = r["limite_injection_kw"], r.get("limite_injection_part_kwc")
    if part is not None:
        pts.append(f"Injection : capacité contractée en plus de {pourcent(part)} du kWc étudié" + (f", plus {nombre(lim)} kW déjà contractés" if lim else "")
                   + " (règle SDE++ : au plus 50 % du piekvermogen, docs/solaire/REGLES-INJECTION.md) ; chaque scénario a sa limite.")
    else:
        pts.append("Injection : " + ("nulle (tout surplus écrêté)." if lim == 0 else f"limitée à {nombre(lim)} kW." if lim is not None else "sans limite déclarée."))
    for s in r["scenarios"]:
        if s["scenario"] == "rien":
            continue
        pts.append(f"{NOMS[s['scenario']]}" + (f" {nombre(s['kwc'])} kWc" if s["kwc"] else "") + (f" {nombre(s['kwh'], 1)} kWh" if s["kwh"] else "")
                   + f" : {val(s['autoconsommee_kwh'])} autoconsommés" + (f" ({pourcent(s['taux_autoconsommation'])} de la production)" if s["taux_autoconsommation"] is not None else "")
                   + f", {val(s['ecretee_kwh'])} écrêtés, économie estimée {val(s['economie_totale_eur'])}, retour simple estimé {val(s['retour_ans'], 1)} : {VERDICTS[s['verdict']]}{_suffixe(r)}.")
    if r["meilleur"]:
        pts.append(f"Retour estimé le plus court{_suffixe(r)} : {NOMS[r['meilleur'].split()[0]]} {' '.join(r['meilleur'].split()[1:])}. Économies simulées sur la période puis ramenées à 365 jours pour ce retour, pas une prévision.")
    for cle in ("valeurs", "pointe"):
        if _reserve_textes(r).get(cle):
            pts.append("À confirmer : " + _reserve_textes(r)[cle])
    return f"<h2>L'essentiel</h2><ul class='syn'>{''.join(f'<li>{e(p)}</li>' for p in pts)}</ul>"


def _tableau_scenarios(r: dict[str, Any]) -> str:
    entete = "<tr><th>Scénario</th><th>kWc</th><th>kWh</th><th>Production</th><th>Autoconsommé</th><th>Importé</th><th>Injecté</th><th>Écrêté</th><th>Pointe import</th><th>Économie estimée sur la période</th><th>Investissement estimé</th><th>Retour simple estimé</th><th>Verdict</th></tr>"
    lignes = []
    for s in r["scenarios"]:
        lignes.append(f"<tr><td>{e(NOMS[s['scenario']])}</td><td>{nombre(s['kwc'])}</td><td>{nombre(s['kwh'], 1)}</td><td>{nombre(s['production_kwh']['valeur'])}</td>"
                      f"<td>{nombre(s['autoconsommee_kwh']['valeur'])}" + (f" ({pourcent(s['taux_autoconsommation'])})" if s["taux_autoconsommation"] is not None else "") + "</td>"
                      f"<td>{nombre(s['importee_kwh']['valeur'])}</td><td>{nombre(s['exportee_kwh']['valeur'])}</td><td>{nombre(s['ecretee_kwh']['valeur'])}</td>"
                      f"<td>{nombre(s['pointe_import_kw']['valeur'])}</td><td>{val(s['economie_totale_eur'])}</td><td>{val(s['investissement_eur'])}</td><td>{val(s['retour_ans'], 1)}</td>"
                      f"<td>{e(VERDICTS[s['verdict']] + _suffixe(r))}</td></tr>")
    return f"<div class='defile'><table class='num comp'>{entete}{''.join(lignes)}</table></div><p class='src'>Énergies en kWh sur la période. Simulé, sauf mention.</p>"


def _detail(s: dict[str, Any], suffixe: str = "") -> str:
    lignes = [lg("Production", s["production_kwh"]), lg("Autoconsommée", s["autoconsommee_kwh"]), lg("Importée", s["importee_kwh"]), lg("Injectée", s["exportee_kwh"]),
              lg("Écrêtée", s["ecretee_kwh"]), lg("Pointe de soutirage après", s["pointe_import_kw"], 1), lg("Achat évité", s["economie_achat_eur"]),
              lg("Surplus vendu estimé", s["recette_surplus_eur"]), lg("Économie réseau estimée", s["economie_reseau_eur"]), lg("Économie estimée (postes chiffrés)", s["economie_totale_eur"]),
              lg("Investissement estimé", s["investissement_eur"]), lg("Retour simple estimé", s["retour_ans"], 1)]
    if s.get("cycles_batterie") is not None:
        lignes.append(ligne("Cycles pleins de la batterie", nombre(s["cycles_batterie"], 1), "simule", "énergie déchargée / capacité utile"))
    if s.get("plafond_kw"):
        lignes.append(ligne("Plafond tenu", f"{nombre(s['plafond_kw'])} kW", "hypothese", "pointe sans ses 8 heures les plus hautes ; batterie dimensionnée pour le tenir (dimensionnement_batterie.py)"))
    titre = NOMS[s["scenario"]] + (f", {nombre(s['kwc'])} kWc" if s["kwc"] else "") + (f", {nombre(s['kwh'], 1)} kWh" if s["kwh"] else "")
    return f"<h3>{e(titre)} : {e(VERDICTS[s['verdict']] + suffixe)}</h3>{tableau(lignes)}"


def _hypotheses(r: dict[str, Any]) -> str:
    lignes = []
    for cle, h in r["hypotheses"].items():
        texte = h.get("source") or SOURCES.get(h.get("source_cle", "hyp_" + cle), "")
        lignes.append(ligne(cle.replace("_", " "), f"{nombre(h['valeur'], 2)} {e(h.get('unite', ''))}".strip(), "hypothese", texte))
    return (f"<h2>4. Hypothèses, règles et sources</h2>{tableau(lignes)}"
            "<p class='src'>Production : PVGIS © Union européenne, JRC, séries horaires 2016 (docs/donnees/pvgis/README.md). Règles d'injection et de "
            "valorisation par pays : docs/solaire/REGLES-INJECTION.md. Les prix (achat, vente du surplus, PV, batterie) viennent de la fiche du client, "
            "jamais du moteur. La production de référence est appliquée par calendrier sur la période de charge lue, sans synchronisation météo. "
            "Les économies sont estimées par simulation sur cette période, jamais mesurées. Le retour simple utilise leur moyenne ramenée à 365 jours, "
            "uniquement si le profil couvre au moins 365 jours ; il ne constitue pas une prévision et exclut les postes non chiffrés.</p>")


def rendre(r: dict[str, Any]) -> str:
    site = r["site"]
    entete = f"<h1>Scan solaire : {e(site.get('nom') or '')}</h1><p class='src'>Courbe de charge {'mesurée' if _profil_mot(r) == 'mesuré' else "lue (une mesure directe n'est pas établie pour toutes les valeurs nécessaires)"} ; production, économies et retour sur investissement estimés par simulation. Aucun gain financier mesuré. Montants cumulés sur la période indiquée.</p>"
    if site.get("exemple"):
        entete += "<p class='exemple'>Exemple sur données publiques réelles avec des prix et une limite d'injection fictifs : pas un dossier client.</p>"
    kw = r["profil_kw"]
    npj = round(24 * 60 / r["statistiques"]["pas_minutes"])
    i = kw.index(max(kw)); d = i - i % npj
    graphe = courbe([(kw[d:d + npj], "#8a8f98", f"soutirage {_profil_mot(r)}, jour de la pointe")], graduations_x=[(h / 24, f"{h:02d}:00") for h in range(0, 25, 3)], titre="jour de pointe")
    textes, suffixe = _reserve_textes(r), _suffixe(r)
    note = f"<p class='afaire'>À confirmer : {e(textes['valeurs'])}{(' ' + e(textes['pointe'])) if textes.get('pointe') else ''}</p>" if textes.get("valeurs") else ""
    titre_ac = (" (à confirmer)" if suffixe else "")
    corps = [entete, _page_qualite(r), _synthese(r), f"<h2>1. Les scénarios côte à côte{titre_ac}</h2>{note}" + _tableau_scenarios(r),
             f"<h2>2. Détail par scénario{titre_ac}</h2>{note}" + "".join(_detail(s, suffixe) for s in r["scenarios"]),
             f"<h2>3. Profil {_profil_mot(r)}</h2>" + graphe, _hypotheses(r),
             f"<p class='src'>{e(site.get('source_profil') or '')} {e(site.get('licence_profil') or '')}</p>",
             f"<footer>Rapport généré le {date.today().strftime('%d/%m/%Y')} par Contingency, {e(r['version'])}. Un chiffre sans source n'y entre pas.</footer>"]
    return (f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Scan solaire</title><style>{STYLE}{_style_qualite()}</style></head><body>{''.join(corps)}</body></html>")
