"""Économies par type de client, patron de site et bureau d'études, tirées d'un scan de flexibilité.

Brief de Vincent du 27/09/2026. Règle de sortie : chaque montant est une fourchette avec ses hypothèses citées,
jamais une promesse. Un investissement évité ou une aide (une fois) et une économie ou un revenu (par an) ne
s'additionnent jamais : aucun total n'est calculé. Les deux réponses à la question « faut-il une batterie ? » sont
chiffrées :
  non  investissement évité, optimisation du contrat, aides Flex-e au scan et à l'étude de faisabilité ;
  oui  bon dimensionnement, EIA, revenus de flexibilité.
Le bureau d'études a sa ligne : le temps gagné par scan.

Sources relues le 27/09/2026 :
- Flex-e, flexibiliteitsscan : 50 % du coût, au plus 10 000 € (RVO, page flexibiliteitsscan) ;
- Flex-e, haalbaarheidsstudie : « 50% van de kosten », « Het minimale subsidiebedrag is € 10.000 en het maximale
  bedrag is € 125.000 » (RVO) : une étude de moins de 20 000 € n'atteint pas l'aide minimale ;
- EIA : « 40% van de investeringskosten aftrekken van de fiscale winst » ; sans bénéfice, la déduction se reporte
  sur les années antérieures et suivantes (RVO). Batteries : code 260101, « niet met software aan een elektrische
  deelmarkt gekoppeld » exclu, et code 251118, production renouvelable de plus de 15 kW sur le même raccordement ;
  5 kW et 15 kWh au moins dans les deux cas (Energielijst 2026) ; une aide à l'investissement reçue se retranche de
  l'assiette (RVO, questions fréquentes sur l'EIA) : champ de fiche aide_batterie_eur ; sans lui, le calcul est
  fait sans aide et le dit ;
- impôt sur les sociétés 2026 : 19 % jusqu'à 200 000 €, 25,8 % au-delà (Belastingdienst). L'EIA vaut donc 7,6 %
  à 10,32 % de l'investissement éligible ;
- contrat : la remise de l'option 5.4 du scan (grille du gestionnaire, ou grille par défaut dite hypothèse). Le tarif
  de référence Enexis MS-D du brief (28,91 €/kW/an) n'est plus appliqué ici : il contredisait l'option 5.4.
Hypothèses du brief, sans source publique relue :
- revenus de flexibilité : 5 300 à 8 600 €/an pour 100 kWh et 50 kW, 26 000 à 43 000 €/an pour 500 kWh et
  250 kW ; 0 € sans batterie, sans agrégateur ou sans activation rentable ; jamais les mêmes quarts d'heure
  vendus à la fois en déséquilibre et en redispatch ;
- bureau d'études : 8 à 16 h gagnées par scan, à environ 90 €/h HT.
"""
from __future__ import annotations

from typing import Any

from scan_flex import grandeur

FLEX_E_SCAN_PART, FLEX_E_SCAN_PLAFOND_EUR = 0.5, 10_000
FLEX_E_ETUDE_PART, FLEX_E_ETUDE_AIDE_MIN_EUR, FLEX_E_ETUDE_AIDE_MAX_EUR = 0.5, 10_000, 125_000
EIA_TAUX = 0.40
IS_TAUX = (0.19, 0.258)
EIA_MIN_KW, EIA_MIN_KWH = 5.0, 15.0
# Minimum de l'EIA : 2 500 € par déclaration (RVO, page Voorwaarden Energie-investeringsaftrek, relue le 29/09 :
# « per melding ten minste € 2.500 »), appliqué à la batterie déclarée seule (audit A10). Avec d'autres investissements
# dans la même déclaration, le seuil porte sur le total : le rapport le dit « à confirmer ».
EIA_ASSIETTE_MIN_EUR = 2500
# Deux points du brief, batteries de 0,5 C : (capacité en kWh, (revenu bas, revenu haut) en €/an).
REVENUS_FLEX = ((100.0, (5_300.0, 8_600.0)), (500.0, (26_000.0, 43_000.0)))
BUREAU_HEURES, BUREAU_TARIF_EUR_H = (8, 16), 90


def _centaine(x: float) -> float:
    return float(round(x, -2))


def _conditionnel(g: dict[str, Any]) -> dict[str, Any]:
    """Montant qui vaut 0 € si sa condition manque (éligibilité, agrégateur, jours évitables) : le rapport écrit
    « 0 € ou … » dans la colonne des valeurs, pas seulement dans la source."""
    g["conditionnel"] = True
    return g


def aide_scan(prix_scan_eur: float | None) -> dict[str, Any]:
    if prix_scan_eur is None:
        return grandeur(None, "€", "a_completer", "src_mon_scan_prix")
    return grandeur(round(min(FLEX_E_SCAN_PART * prix_scan_eur, FLEX_E_SCAN_PLAFOND_EUR)), "€", "hypothese",
                    "src_mon_flex_e_scan", prix=prix_scan_eur)


def aide_etude(cout_etude_eur: float | None) -> dict[str, Any]:
    """Aide à l'étude de faisabilité : jamais le maximum de 125 000 € par défaut, seulement sur un coût fourni."""
    if cout_etude_eur is None:
        return grandeur(None, "€", "a_completer", "src_mon_etude_cout")
    aide = FLEX_E_ETUDE_PART * cout_etude_eur
    if aide < FLEX_E_ETUDE_AIDE_MIN_EUR:
        return grandeur(0, "€", "hypothese", "src_mon_etude_sous_minimum", cout=cout_etude_eur)
    return grandeur(round(min(aide, FLEX_E_ETUDE_AIDE_MAX_EUR)), "€", "hypothese", "src_mon_etude", cout=cout_etude_eur)


def eia(investissement: list[float] | None, nominale_kwh: float, puissance_kw: float,
        aide_eur: float | None = None) -> dict[str, Any]:
    """Impôt en moins par l'EIA : 40 % de l'assiette déduits du bénéfice, au taux d'impôt de 19 % (bas de fourchette)
    ou 25,8 % (haut). L'assiette est l'investissement moins l'aide à l'investissement reçue (FAQ EIA de RVO) : sans
    aide déclarée, le calcul le dit sur sa ligne (relecture de Codex, bus n°484). L'éligibilité (code 260101 ou
    251118) n'est pas vérifiée par le scan : 0 € reste possible, et c'est écrit."""
    if not investissement or not investissement[1]:
        return grandeur(None, "€", "a_chiffrer", "src_mon_eia_sans_prix")
    if nominale_kwh < EIA_MIN_KWH or puissance_kw < EIA_MIN_KW:
        return grandeur(0, "€", "hypothese", "src_mon_eia_trop_petite")
    if aide_eur is None:
        assiette, cle, parametres = investissement, "src_mon_eia", {}
    else:
        assiette = [max(0.0, investissement[0] - aide_eur), max(0.0, investissement[1] - aide_eur)]
        if not assiette[1]:
            return grandeur(0, "€", "hypothese", "src_mon_eia_aide_totale", aide=aide_eur)
        cle, parametres = "src_mon_eia_aide", {"aide": aide_eur}
    if assiette[1] < EIA_ASSIETTE_MIN_EUR:
        return grandeur(0, "€", "hypothese", "src_mon_eia_sous_seuil")
    assiette = [a if a >= EIA_ASSIETTE_MIN_EUR else 0.0 for a in assiette]
    return _conditionnel(grandeur([_centaine(assiette[0] * EIA_TAUX * IS_TAUX[0]), _centaine(assiette[1] * EIA_TAUX * IS_TAUX[1])],
                                  "€", "hypothese", cle, **parametres))


def revenus_flex(nominale_kwh: float, puissance_kw: float) -> dict[str, Any]:
    """Revenus de flexibilité supposés, ramenés à la batterie du scan. Les deux points du brief sont des batteries
    de 0,5 C : la batterie compte pour min(capacité, 2 x puissance) kWh équivalents, la ressource la plus rare.
    Entre les deux points, interpolation linéaire ; en dehors, proportionnel au point le plus proche, dit extrapolé."""
    equivalent = min(nominale_kwh, 2 * puissance_kw)
    (k1, (b1, h1)), (k2, (b2, h2)) = REVENUS_FLEX
    if equivalent <= k1:
        bas, haut = b1 * equivalent / k1, h1 * equivalent / k1
    elif equivalent < k2:
        f = (equivalent - k1) / (k2 - k1)
        bas, haut = b1 + f * (b2 - b1), h1 + f * (h2 - h1)
    else:
        bas, haut = b2 * equivalent / k2, h2 * equivalent / k2
    cle = "src_mon_revenus_flex" if k1 <= equivalent <= k2 else "src_mon_revenus_flex_extrapole"
    return _conditionnel(grandeur([_centaine(bas), _centaine(haut)], "€/an", "hypothese", cle, kwh=round(equivalent, 1)))


def bon_dimensionnement(decisifs: dict[str, Any] | None, investissement: list[float] | None) -> dict[str, Any]:
    """Investissement en moins si les jours les plus lourds sont traités autrement (section des quarts d'heure qui
    décident) : de 0 € si aucun ne peut l'être, à la baisse calculée en retirant les jours classés un à un (audit F5 :
    choix glouton, pas toujours la meilleure combinaison)."""
    lignes = [l for l in (decisifs or {}).get("sans_jours", []) if l.get("investissement_eur")]
    if not investissement or not lignes:
        return grandeur(None, "€", "a_chiffrer", "src_mon_dimensionnement_absent")
    meilleure = min(lignes, key=lambda l: (l["investissement_eur"][1], l["jours_retires"]))
    baisse = [max(0.0, investissement[0] - meilleure["investissement_eur"][0]),
              max(0.0, investissement[1] - meilleure["investissement_eur"][1])]
    cle = "src_mon_dimensionnement_un" if meilleure["jours_retires"] == 1 else "src_mon_dimensionnement"
    return _conditionnel(grandeur(baisse, "€", "hypothese", cle, jours=meilleure["jours_retires"],
                                  reference=decisifs["batterie_nominale_kwh"], nominale=meilleure["nominale_kwh"]))


def optimisation_contrat(resultat: dict[str, Any]) -> dict[str, Any]:
    """La remise de l'option 5.4, en fourchette : même kW, même tarif de grille, même statut quand elle n'est pas
    chiffrable. 0 € si le gestionnaire ne propose pas le droit non ferme dans la zone. Un tarif propre à cette ligne
    contredisait l'option 5.4 et chiffrait un terme absent en LS (constat n°10 de la relecture du 27/09)."""
    remise = resultat["options"]["contrat"]["remise_eur_an"]
    v = remise["valeur"]
    if not v or isinstance(v, bool):
        return remise
    p = remise["parametres"]
    return grandeur([0, v], "€/an", "hypothese", "src_mon_contrat", kw=p["kw"], tarif=p["tarif"], gestionnaire=p["gestionnaire"])


def investissement_evite(batterie: dict[str, Any], mesure: str) -> dict[str, Any]:
    nominale = (batterie.get("capacite_nominale_kwh") or {}).get("valeur")
    if not batterie.get("faisable"):
        return grandeur(None, "€", "a_chiffrer", "src_mon_batterie_impossible")
    if not nominale:
        return grandeur(0, "€", "hypothese", "src_mon_batterie_inutile")
    investissement = (batterie.get("investissement_eur") or {}).get("valeur")
    if not investissement:
        return grandeur(None, "€", "a_chiffrer", "src_mon_batterie_sans_prix")
    return grandeur(investissement, "€", "hypothese", "src_mon_invest_evite_" + mesure, nominale=nominale)


def calculer(resultat: dict[str, Any], fiche: dict[str, Any]) -> dict[str, Any]:
    o = resultat["options"]
    batterie = o["batterie"]
    # La limite sans batterie : le décalage s'il suffit, sinon l'écrêtage, qui la tient toujours au prix de la
    # production coupée.
    mesure = "decalage" if o["decalage"]["faisable"] else "ecretage"
    nominale = (batterie.get("capacite_nominale_kwh") or {}).get("valeur") or 0.0
    puissance = nominale * resultat["hypotheses"]["puissance_sur_capacite_max"]["valeur"]
    investissement = (batterie.get("investissement_eur") or {}).get("valeur")
    if not batterie.get("faisable"):
        oui = {c: grandeur(None, u, "a_chiffrer", "src_mon_batterie_impossible")
               for c, u in (("bon_dimensionnement", "€"), ("eia", "€"), ("revenus_flex", "€/an"))}
    elif not nominale:
        oui = {c: grandeur(0, u, "hypothese", "src_mon_batterie_inutile")
               for c, u in (("bon_dimensionnement", "€"), ("eia", "€"), ("revenus_flex", "€/an"))}
    else:
        oui = {"bon_dimensionnement": bon_dimensionnement(resultat.get("quarts_decisifs"), investissement),
               "eia": eia(investissement, nominale, puissance, fiche.get("aide_batterie_eur")),
               "revenus_flex": revenus_flex(nominale, puissance)}
    return {
        "sans_batterie": {"mesure": mesure,
                          "investissement_evite": investissement_evite(batterie, mesure),
                          "optimisation_contrat": optimisation_contrat(resultat),
                          "aide_scan": aide_scan(fiche.get("prix_scan_eur")),
                          "aide_etude": aide_etude(fiche.get("cout_etude_eur"))},
        "avec_batterie": oui,
        "bureau_etudes": {"heures": grandeur(list(BUREAU_HEURES), "h", "hypothese", "src_mon_bureau_heures"),
                          "valeur": grandeur([BUREAU_HEURES[0] * BUREAU_TARIF_EUR_H, BUREAU_HEURES[1] * BUREAU_TARIF_EUR_H], "€",
                                             "hypothese", "src_mon_bureau_valeur", tarif=BUREAU_TARIF_EUR_H)},
    }
