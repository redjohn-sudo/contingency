"""Scan de flexibilité d'un site, sur le plan d'un flexibiliteitsscan néerlandais.

Plan suivi : données du site, congestion locale, profils annuel, mensuel, hebdomadaire et journalier au
quart d'heure, puis plusieurs options de flexibilité chiffrées avec les mêmes grandeurs (kW flexibles,
MWh par an, durée, disponibilité, investissement, retour sur investissement, profil après mesure), enfin
une comparaison et une recommandation. Sources du plan : docs/recherche/FLEXSCAN-FORMAT.md.

Règle de la maison : chaque grandeur porte sa nature.
  mesure       lu directement dans le profil ;
  simule       calculé sur le profil par un modèle décrit ici ;
  tarif        tiré d'une grille ou d'une règle publiée, source citée ;
  declare      fourni par l'entreprise dans la fiche (EAN, processus, horaires), non vérifié ici ;
  hypothese    paramètre choisi par le scan, modifiable dans la fiche, jamais présenté comme un fait ;
  a_chiffrer   rien ne permet de donner un nombre honnête : on dit ce qu'il faut pour le chiffrer ;
  a_completer  une information que l'entreprise, l'ATO ou la visite du site doivent fournir (EAN, processus).

Les sources, unités et textes sont des clés : rapport_flex.py les rend en français ou en néerlandais.

Champs de fiche reconnus (tous facultatifs ; un champ absent reste « à compléter » dans le rapport) :
  identité          nom, secteur, adresse, exemple (booléen),
                    traductions {nl: {nom, secteur, source_profil, licence_profil, note_congestion, croissance_description}}
  raccordement      gestionnaire (liander, stedin, enexis), ean, sbi, gtv_kw (dernière valeur déclarée au gestionnaire, pas
                    celle d'un ancien ATO si une baisse a été déclarée depuis : arrêt NorthC du CBb, 23/06/2026),
                    capacite_aansluiting_kva,
                    categorie_tarifaire (LS, TRAFO_MS_LS, MS, MS_TRANSPORT chez Enexis, TRAFO_HS_TS_MS),
                    transport_autres, changements_prevus, autres_energies,
                    type_transportrecht (seul « vast » est chiffré ; tijdsblok, tijdsduurgebonden, non_firm, ou
                    blocs_transport / gtv_hors_bloc_kw sans droit « vast » : scan refusé)
  activité          heures_activite_an, horaires_semaine, processus, production_propre
  congestion        statut_zone_afname, statut_zone_teruglevering, date_carte, annee_liberation_annoncee,
                    congestierapport, besoin_flexibilite_zone, note_congestion
  scan              plafond_cible_kw, preference_entreprise, annee_profil (année à garder si le CSV en couvre plusieurs),
                    croissance_prevue {kw, debut « HH:MM », fin « HH:MM », jours « ouvres » ou « tous », description},
                    hypotheses {nom: valeur ou {valeur, source}}, noms dans HYPOTHESES_DEFAUT,
                    tirages_confiance (années tirées pour le niveau de confiance, 100 par défaut, 0 pour ne pas le calculer)
  batterie          batterie_garantie {cycles, profondeur (0 à 1), annees, etat_fin (capacité restante garantie, 0 à 1),
                    source} : garantie du fabricant ; sans elle, durée de vie et capacité de fin de garantie restent
                    « à compléter », aucun taux de vieillissement n'étant supposé
  profil            source_profil, licence_profil
  congestion (suite) deelnameplicht_annoncee (booléen) : le gestionnaire a-t-il annoncé l'obligation de participer au
                    congestiemanagement ? Sans ce champ, l'obligation au-delà de 1 MW reste « à vérifier »
  groupe            contrat_groupe (booléen, posé par scan_groupe.py) : profil commun de plusieurs raccordements
  monétisation      prix_scan_eur (prix du scan hors TVA, pour l'aide Flex-e), cout_etude_eur (coût d'une étude de
                    faisabilité hors TVA) : sans eux, les deux aides restent « à compléter » ;
                    aide_batterie_eur (aide à l'investissement reçue sur la batterie, 0 si aucune) : retranchée de
                    l'assiette de l'EIA ; sans elle, l'EIA est calculée sans aide et le rapport le dit

Usage : python application/scan_flex.py profil.csv|reponse_kenter.json fiche.json dossier_sortie/ [--pdf]
Le profil est soit le CSV interne (fin_intervalle,puissance_kw), soit la réponse JSON de l'API Kenter
(canal 16180), lue par lecteur_kenter.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(ICI.parent / "optimisation"))

from controles import PART_HEURES_TDTR, SEUIL_CONGESTIEMANAGEMENT_KW  # noqa: E402
from functools import lru_cache  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

# Prix day-ahead de la zone NL en 2025 (Energy-Charts, CC BY 4.0, Bundesnetzagentur | SMARD.de), voir
# docs/donnees/README.md. Servent au revenu d'arbitrage théorique d'une batterie.
PRIX_DAY_AHEAD = ICI.parent / "docs" / "donnees" / "prix-day-ahead-nl-2025.csv"
AMSTERDAM = ZoneInfo("Europe/Amsterdam")

VERSION = "scan-flex-1"
PAS_H = 0.25
QUART = timedelta(minutes=15)
QUARTS_ANNEE_MIN = 365 * 96  # en dessous, énergies et économies valent pour la période lue, pas pour un an
# « lu » : valeur du profil dont la qualité n'est pas documentée comme mesure (revue d'Astra, P1-AA) ; les chiffres
# restent, seule la nature change. Même règle que les rapports France et solaire de Fable.
NATURES = {"mesure", "lu", "simule", "tarif", "declare", "hypothese", "a_chiffrer", "a_completer"}
# Tranches de la toelichting Flex-e 2026 pour l'eenvoudige terugverdientijd (Stct. 2026, 12853).
TRANCHES_ETVT = [(3, "moins_3"), (5, "3_5"), (7, "5_7"), (15, "7_15"), (math.inf, "plus_15")]
SEUIL_ACTIVITE = 0.25  # part de l'écart pointe - charge de base au-dessus de laquelle le site est « actif »

# Tarifs de transport 2026 des trois grands gestionnaires, lus le 27/09/2026 dans les tarievenbladen XLSX
# publiés par l'ACM avec chaque tarievenbesluit (acm.nl/system/files/documents/tarievenblad-<gestionnaire>-
# elektriciteit-2026.xlsx) : feuille 2a pour les tarifs, 2b pour les deelmarktgrenzen. Seuls les termes que la
# flexibilité peut changer sont repris : kW contracté par an et kWmax par mois. Les bornes de catégorie
# diffèrent d'un gestionnaire à l'autre (Trafo MS/LS jusqu'à 136 kW chez Liander, 150 chez Stedin, 125 chez
# Enexis) : on ne mélange jamais les grilles.
TARIFS_2026 = {
    "liander": {
        "LS": {"plage": "1-50 kW", "kw_contrat_an": None, "kwmax_mois": None},
        "TRAFO_MS_LS": {"plage": "> 50-136 kW", "kw_contrat_an": 44.88, "kwmax_mois": 3.57},
        "MS": {"plage": "> 136 kW-2 MW", "kw_contrat_an": 27.48, "kwmax_mois": 3.57},
        "TRAFO_HS_TS_MS": {"plage": "> 2 MW", "kw_contrat_an": 47.88, "kwmax_mois": 6.24},
        "bornes": [(50, "LS"), (136, "TRAFO_MS_LS"), (2000, "MS"), (math.inf, "TRAFO_HS_TS_MS")],
    },
    "stedin": {
        "LS": {"plage": "1-50 kW", "kw_contrat_an": None, "kwmax_mois": None},
        "TRAFO_MS_LS": {"plage": "51-150 kW", "kw_contrat_an": 47.169, "kwmax_mois": 3.0966},
        "MS": {"plage": "151-1 500 kW", "kw_contrat_an": 24.2737, "kwmax_mois": 3.0966},
        "TRAFO_HS_TS_MS": {"plage": "> 1,5 MW", "kw_contrat_an": 45.4508, "kwmax_mois": 5.2943},
        "bornes": [(50, "LS"), (150, "TRAFO_MS_LS"), (1500, "MS"), (math.inf, "TRAFO_HS_TS_MS")],
    },
    "enexis": {
        "LS": {"plage": "1-50 kW", "kw_contrat_an": None, "kwmax_mois": None},
        "TRAFO_MS_LS": {"plage": "> 50-125 kW", "kw_contrat_an": 49.26, "kwmax_mois": 3.66},
        "MS": {"plage": "> 125-1 500 kW (MS-distributie)", "kw_contrat_an": 28.91, "kwmax_mois": 3.66},
        "MS_TRANSPORT": {"plage": "> 1 500 kW, MS-transport", "kw_contrat_an": 27.37, "kwmax_mois": 3.06},
        "TRAFO_HS_TS_MS": {"plage": "> 1 500 kW, HS/MS", "kw_contrat_an": 41.87, "kwmax_mois": 4.46},
        # Au-delà de 1 500 kW, la catégorie Enexis dépend du mode de raccordement physique : sans l'ATO, on garde
        # MS-distributie, que la grille admet aussi au-dessus de 1 500 kW, et on le marque comme hypothèse.
        "bornes": [(50, "LS"), (125, "TRAFO_MS_LS"), (math.inf, "MS")],
    },
}
TARIFS_LIANDER_2026 = {k: v for k, v in TARIFS_2026["liander"].items() if k != "bornes"}

# Hypothèses par défaut : toutes modifiables dans la fiche (clé « hypotheses »), toutes affichées avec leur
# raison (clé de texte hyp_<nom> dans rapport_flex.py) ou la source fournie dans la fiche.
HYPOTHESES_DEFAUT: dict[str, dict[str, Any]] = {
    "heures_ecretees": {"valeur": 8, "unite": "h/an"},
    "rendement_aller_retour": {"valeur": 0.90, "unite": ""},
    "profondeur_decharge": {"valeur": 0.90, "unite": ""},
    "puissance_sur_capacite_max": {"valeur": 1.0, "unite": "kW/kWh"},
    # Prix indicatif publié par un installateur néerlandais (charge24.nl, « Zakelijke batterij », 10/08/2026, relu le
    # 27/09) : « circa € 400 tot € 700 per kWh opslagcapaciteit, inclusief installatie » ; au-delà de 100 kWh,
    # « richting € 350 per kWh ». Repère public : marché Aquafin (TED 863953-2025), 828 416,40 € hors TVA attribués
    # pour une batterie annoncée à 2 150 kWh par ailleurs, soit environ 385 €/kWh. À remplacer par deux devis.
    "prix_batterie_eur_kwh": {"valeur": [400, 700], "unite": "€/kWh"},
    "fenetre_decalage_h": {"valeur": 4, "unite": "h"},
}


def grandeur(valeur: Any, unite: str, nature: str, source: str = "", **parametres: Any) -> dict[str, Any]:
    """Une valeur, son unité (clé), sa nature, et la clé de sa source avec ses paramètres."""
    if nature not in NATURES:
        raise ValueError(f"nature inconnue : {nature}")
    if isinstance(valeur, float) and not math.isfinite(valeur):
        raise ValueError("grandeur non finie")
    if nature in ("a_chiffrer", "a_completer") and isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        raise ValueError("une grandeur à chiffrer ne porte pas de nombre")
    return {"valeur": valeur, "unite": unite, "nature": nature, "source": source, "parametres": parametres}


def par_periode(kw: list[float], unite: str, pas_minutes: int = 15) -> str:
    """« MWh/an » devient « MWh/periode » si le profil couvre moins d'un an (durée, quel que soit le pas)."""
    return unite if len(kw) * pas_minutes >= QUARTS_ANNEE_MIN * 15 else unite.replace("/an", "/periode")


# ---------------------------------------------------------------- lecture et statistiques du profil

def lire_profil_annee(chemin: Path, annee: int | None = None) -> tuple[list[float], list[datetime], dict[str, Any] | None]:
    """Flex-e demande « een representatief jaar van de afgelopen drie jaren ». Un gestionnaire livre souvent
    plusieurs années d'un coup (Liander : 2023, 2024 et 2025). Si le CSV dépasse une année, on garde l'année
    civile complète demandée dans la fiche, sinon la plus récente, et on dit laquelle parmi lesquelles."""
    if annee is not None and (type(annee) is not int or not 1900 <= annee <= 2100):
        raise ValueError(f"Fiche : annee_profil doit être une année entière (ex. 2025), reçu {str(annee)[:20]!r}.")
    if chemin.suffix.lower() == ".json":
        kw, fins = lire_profil(chemin)
        return kw, fins, None
    lignes = chemin.read_text(encoding="utf-8-sig").strip().splitlines()
    if len(lignes) - 1 <= 35140:
        kw, fins = lire_csv(chemin)
        return kw, fins, None
    import serveur
    entete, par_annee = lignes[0], defaultdict(list)
    for ligne in lignes[1:]:
        fin = datetime.fromisoformat(ligne.split(",", 1)[0].replace("Z", "+00:00"))
        # Années civiles d'Amsterdam, quel que soit le fuseau écrit dans le fichier (UTC compris).
        fin = fin.astimezone(AMSTERDAM).replace(tzinfo=None) if fin.tzinfo else fin
        par_annee[(fin - QUART).year].append((fin, ligne))
    completes = []
    for a, contenu in sorted(par_annee.items()):
        premiere, derniere = contenu[0][0] - QUART, contenu[-1][0]
        if premiere == datetime(a, 1, 1) and derniere == datetime(a + 1, 1, 1):
            completes.append(a)
    if not completes and annee is None:
        # Constat n°13 : un export glissant (du 25/09/2025 au 27/09/2026) n'a aucune année civile complète ;
        # on garde les 365 jours qui finissent au dernier horodatage, et le rapport le dit.
        tout = [x for _, contenu in sorted(par_annee.items()) for x in contenu]  # ordre du fichier : l'heure locale se répète en octobre
        depart = tout[-1][0] - timedelta(days=365)
        texte = entete + "\n" + "\n".join(l for f, l in tout if f > depart) + "\n"
        valeurs, horodatages = serveur._lire_profil_detaille(texte, jours_civils=True)
        return list(valeurs), [datetime.fromisoformat(h) for h in horodatages], {
            "annees": sorted(par_annee), "completes": [], "choisie": None, "regle": "glissante"}
    if not completes:
        raise ValueError(f"Année {annee} absente ou incomplète : le fichier n'a aucune année civile complète.")
    choisie = annee if annee is not None else max(completes)
    if choisie not in completes:
        raise ValueError(f"Année {choisie} absente ou incomplète ; années complètes : {', '.join(map(str, completes))}.")
    texte = entete + "\n" + "\n".join(l for _, l in par_annee[choisie]) + "\n"
    valeurs, horodatages = serveur._lire_profil_detaille(texte, jours_civils=True)
    selection = {"annees": sorted(par_annee), "completes": completes, "choisie": choisie,
                 "regle": "fiche" if annee is not None else "plus_recente"}
    return list(valeurs), [datetime.fromisoformat(h) for h in horodatages], selection


def lire_profil(chemin: Path) -> tuple[list[float], list[datetime]]:
    """CSV interne, ou réponse JSON de l'API Kenter (liste de canaux) convertie par lecteur_kenter."""
    if chemin.suffix.lower() == ".json":
        import lecteur_kenter
        import serveur
        lu = lecteur_kenter.lire_kenter(json.loads(chemin.read_text(encoding="utf-8")))
        valeurs, horodatages = serveur._lire_profil_detaille(lu["csv"], jours_civils=True)
        return list(valeurs), [datetime.fromisoformat(h) for h in horodatages]
    return lire_csv(chemin)


def lire_profil_qualifie(chemin: Path, annee: int | None = None) -> dict[str, Any]:
    """Profil, qualité de chaque quart et provenance (AF06, lot 1 du 30/09) : ce que le lecteur sait d'une valeur
    (mesurée, estimée, calculée, inconnue) arrive jusqu'au scan. Le CSV canonique ne porte aucun statut : qualites
    vaut None, et le scan le dira. Avant, la réponse Kenter perdait qualités, avertissements et provenance."""
    donnees = chemin.read_bytes()
    provenance = {"fichier": chemin.name, "sha256": hashlib.sha256(donnees).hexdigest(), "octets": len(donnees)}
    if chemin.suffix.lower() == ".json":
        import lecteur_kenter
        import serveur
        lu = lecteur_kenter.lire_kenter(json.loads(donnees.decode("utf-8")))
        valeurs, horodatages = serveur._lire_profil_detaille(lu["csv"], jours_civils=True)
        # Bilan des lignes (FB1, section 4) : mesures reçues sur le canal lu, doublons identiques réunis par le lecteur.
        doublons = lu["provenance"]["doublons_identiques"][lecteur_kenter.CANAL_KWARTIER]
        bilan = {"recues": len(valeurs) + doublons, "nature": "mesures_kenter", "ecartees": {}, "doublons_identiques": doublons}
        return {"kw": list(valeurs), "fins": [datetime.fromisoformat(h) for h in horodatages], "selection": None,
                "qualites": [q["qualite"] for q in lu["qualites"]], "details_qualite": lu["qualites"],
                "avertissements": lu["avertissements"],
                "provenance": {**provenance, **lu["provenance"], "bilan_lignes": bilan,
                               # kWmax de facturation (canal 18160), recoupé par qualite_jeu avec les quarts du mois.
                               "kwmax_facture_par_mois": lu["kwmax_facture_par_mois"],
                               "kwmax_qualites_par_mois": {m: q["qualite"] for m, q in lu["kwmax_qualites_par_mois"].items()}}}
    kw, fins, selection = lire_profil_annee(chemin, annee)
    # Le lecteur canonique refuse tout enregistrement illisible. Comptés avec le même module csv que lui, sans les
    # lignes vides qu'il saute : une cellule citée sur deux lignes reste un seul enregistrement. « Hors période »
    # seulement après une vraie sélection d'année (revue d'Astra de 26ba18b, P2-R).
    recues = sum(1 for enregistrement in csv.reader(io.StringIO(donnees.decode("utf-8-sig"))) if enregistrement) - 1
    bilan = {"recues": recues, "nature": "lignes", "doublons_identiques": 0,
             "ecartees": {"hors_periode_retenue": recues - len(kw)} if selection and recues > len(kw) else {}}
    return {"kw": kw, "fins": fins, "selection": selection, "qualites": None, "details_qualite": None, "avertissements": [],
            "provenance": {**provenance, "format": "csv_canonique", "quarts": len(kw), "bilan_lignes": bilan}}


def lire_csv(chemin: Path) -> tuple[list[float], list[datetime]]:
    """CSV interne fin_intervalle,puissance_kw ; délègue au lecteur du serveur (pas régulier vérifié)."""
    import serveur
    valeurs, horodatages = serveur._lire_profil_detaille(chemin.read_text(encoding="utf-8-sig"), jours_civils=True)
    return list(valeurs), [datetime.fromisoformat(h) for h in horodatages]


def _heure_locale(instant: datetime, zone: ZoneInfo = AMSTERDAM) -> datetime:
    return instant.astimezone(zone).replace(tzinfo=None) if instant.tzinfo else instant


def _debut_local(fin: datetime, pas: timedelta = QUART, zone: ZoneInfo = AMSTERDAM) -> datetime:
    """Début physique d'un intervalle : soustrait en UTC puis converti (revue d'Astra, France et solaire). Sur une heure
    locale sans fuseau, la soustraction reste locale, comme avant."""
    return (fin.astimezone(timezone.utc) - pas).astimezone(zone).replace(tzinfo=None) if fin.tzinfo else fin - pas


def couverture(fins: list[datetime], pas_minutes: int = 15, zone: ZoneInfo = AMSTERDAM) -> dict[str, Any]:
    """Période réellement couverte, en heure locale de ``zone`` (AF10, 30/09) : une année civile complète va du 1er
    janvier 0 h au 1er janvier suivant 0 h. Le nombre d'intervalles ne suffit pas (2024 sans son 31 décembre en compte
    35 040 quarts). Ne regarde que les bornes : à n'appeler que sur une série régulière, sans trou (les lecteurs le
    garantissent). ``pas_minutes`` : pas natif du profil (France : 5 à 60 minutes), jamais recadré."""
    debut, fin = _debut_local(fins[0], timedelta(minutes=pas_minutes), zone), _heure_locale(fins[-1], zone)
    jours = round(len(fins) * pas_minutes / 1440, 1)
    if debut == datetime(debut.year, 1, 1) and fin == datetime(debut.year + 1, 1, 1):
        return {"type": "annee_civile", "annee": debut.year, "jours": jours}
    return {"type": "periode_annuelle" if len(fins) * pas_minutes >= QUARTS_ANNEE_MIN * 15 else "partielle",
            "annee": None, "jours": jours}


def annee_representative(fins: list[datetime], aujourd_hui: datetime | None = None, pas_minutes: int = 15,
                         zone: ZoneInfo = AMSTERDAM) -> dict[str, Any]:
    """Flex-e (bijlage 4.12.1, art. 1 d et 4 a) : un « representatief jaar van de afgelopen drie jaren ». Une année
    future est un scénario et l'année en cours n'est pas encore l'une des trois dernières (AF10, 30/09)."""
    annee = (couverture(fins, pas_minutes, zone)["annee"]
             or _debut_local(fins[len(fins) // 2], timedelta(minutes=pas_minutes), zone).year)
    reference = (aujourd_hui or datetime.now()).year
    statut = ("future" if annee > reference else "en_cours" if annee == reference
              else "recente" if reference - annee <= 3 else "ancienne")
    return {"annee": annee, "dans_les_3_ans": statut == "recente", "statut": statut, "annee_scan": reference}


def statistiques(kw: list[float], fins: list[datetime], pas_minutes: int = 15, zone: ZoneInfo = AMSTERDAM,
                 nature: str = "mesure") -> dict[str, Any]:
    """``pas_minutes`` et ``zone`` : pas natif et fuseau du profil (défaut : quart d'heure, Amsterdam). Les dates rendues
    sont en heure locale de ``zone``, débuts d'intervalle calculés en UTC. ``nature`` : « lu » dès qu'une valeur n'est
    pas une mesure documentée (P1-AA)."""
    n, pas, pas_h = len(kw), timedelta(minutes=pas_minutes), pas_minutes / 60
    periode = couverture(fins, pas_minutes, zone)
    energie = sum(kw) * pas_h
    pointe = max(kw)
    i_pointe = kw.index(pointe)
    base = sorted(kw)[int(0.05 * (n - 1))]
    return {
        "debut": _debut_local(fins[0], pas, zone).isoformat(), "fin": _heure_locale(fins[-1], zone).isoformat(), "quarts": n,
        # Année civile complète (rubriques annuelles 1d et 4a) ; au moins 365 jours (grandeurs par an).
        "couverture": periode, "annee_complete": periode["type"] == "annee_civile",
        "duree_annuelle": n * pas_minutes >= QUARTS_ANNEE_MIN * 15,
        "representativite": annee_representative(fins, pas_minutes=pas_minutes, zone=zone),
        "selection_annee": None,
        "energie_mwh": grandeur(round(energie / 1000, 1), par_periode(kw, "MWh/an", pas_minutes), nature),
        "pointe_kw": grandeur(pointe, "kW", nature),
        "instant_pointe": _debut_local(fins[i_pointe], pas, zone).isoformat(),
        "moyenne_kw": grandeur(round(energie / (n * pas_h), 1), "kW", nature),
        "charge_de_base_kw": grandeur(base, "kW", nature, "src_centile5"),
        "heures_utilisation": grandeur(round(energie / pointe) if pointe else 0, par_periode(kw, "h/an", pas_minutes), nature,
                                       "src_utilisation"),
        "facteur_charge": grandeur(round(energie / (n * pas_h) / pointe, 3) if pointe else 0, "", nature),
    }


def profils(kw: list[float], fins: list[datetime]) -> dict[str, Any]:
    """Profils annuel (par jour), mensuel, hebdomadaire et journalier, et courbe monotone."""
    par_jour: dict[str, list[float]] = defaultdict(list)
    par_mois: dict[str, list[float]] = defaultdict(list)
    somme = [[0.0] * 96 for _ in range(7)]
    compte = [[0] * 96 for _ in range(7)]
    for x, fin in zip(kw, fins):
        debut = fin - QUART
        par_jour[debut.date().isoformat()].append(x)
        par_mois[debut.strftime("%Y-%m")].append(x)
        q, j = debut.hour * 4 + debut.minute // 15, debut.weekday()
        somme[j][q] += x
        compte[j][q] += 1
    moyenne = lambda jours, q: (round(sum(somme[j][q] for j in jours) / n, 1)
                                if (n := sum(compte[j][q] for j in jours)) else None)
    i_pointe = kw.index(max(kw))
    debut_pointe = fins[i_pointe] - QUART
    lundi = datetime.combine((debut_pointe - timedelta(days=debut_pointe.weekday())).date(), datetime.min.time())
    indices_semaine = [i for i, f in enumerate(fins) if lundi <= f - QUART < lundi + timedelta(days=7)]
    return {
        "annuel": [{"jour": j, "max_kw": max(v), "moyenne_kw": round(sum(v) / len(v), 1)} for j, v in par_jour.items()],
        "mensuel": [{"mois": m, "max_kw": max(v), "moyenne_kw": round(sum(v) / len(v), 1),
                     "energie_mwh": round(sum(v) * PAS_H / 1000, 1)} for m, v in par_mois.items()],
        "semaine_type": [[moyenne([j], q) for q in range(96)] for j in range(7)],
        "semaine_pointe": {"lundi": lundi.date().isoformat(), "debut": indices_semaine[0], "fin": indices_semaine[-1] + 1},
        "jour_ouvre_moyen": [moyenne(range(5), q) for q in range(96)],
        "jour_repos_moyen": [moyenne((5, 6), q) for q in range(96)],
        "jour_pointe": {"jour": debut_pointe.date().isoformat(), "kw": par_jour[debut_pointe.date().isoformat()]},
        "monotone": sorted(kw, reverse=True),
    }


def episodes(kw: list[float], plafond: float) -> dict[str, Any]:
    """Épisodes continus au-dessus du plafond : combien, combien de temps, combien d'énergie."""
    liste, en_cours = [], None
    for i, x in enumerate(kw):
        if x > plafond:
            if en_cours is None:
                en_cours = {"debut": i, "quarts": 0, "energie_kwh": 0.0, "depassement_max_kw": 0.0}
            en_cours["quarts"] += 1
            en_cours["energie_kwh"] += (x - plafond) * PAS_H
            en_cours["depassement_max_kw"] = max(en_cours["depassement_max_kw"], x - plafond)
        elif en_cours is not None:
            liste.append(en_cours)
            en_cours = None
    if en_cours is not None:
        liste.append(en_cours)
    return {"nombre": len(liste),
            "quarts": sum(e["quarts"] for e in liste),
            "duree_max_h": max((e["quarts"] for e in liste), default=0) * PAS_H,
            "energie_kwh": sum(e["energie_kwh"] for e in liste),
            "energie_max_episode_kwh": max((e["energie_kwh"] for e in liste), default=0.0),
            "liste": liste}


def plafond_heures(kw: list[float], heures: float) -> float:
    """Niveau qu'on ne dépasse pas plus de `heures` par an : la pointe sans ses N heures les plus hautes.
    Sur un profil plus court qu'un an, le nombre d'heures est ramené à la durée lue."""
    part = heures / 8760 if len(kw) < QUARTS_ANNEE_MIN else None
    rang = int(round(part * len(kw))) if part is not None else int(round(heures / PAS_H))
    tri = sorted(kw, reverse=True)
    return tri[min(rang, len(tri) - 1)]


def heures_au_dessus(kw: list[float], niveau: float) -> float:
    return sum(1 for x in kw if x > niveau) * PAS_H


def _declare_ou(fiche: dict[str, Any], champ: str, unite: str = "", source_manquante: str = "src_a_completer") -> dict[str, Any]:
    valeur = fiche.get(champ)
    if valeur in (None, "", []):
        return grandeur(None, unite, "a_completer", source_manquante)
    return grandeur(valeur, unite, "declare", "src_fiche")


def entreprise(fiche: dict[str, Any], kw: list[float], stats: dict[str, Any], prof: dict[str, Any]) -> dict[str, Any]:
    """Bijlage 4.12.1, article 1 : identité du raccordement, contrats, consommation, heures d'activité."""
    base = stats["charge_de_base_kw"]["valeur"]
    seuil = base + SEUIL_ACTIVITE * (max(kw) - base)
    heures = heures_au_dessus(kw, seuil)
    horaires = []
    for jour, valeurs in enumerate(prof["semaine_type"]):
        actifs = [q for q, v in enumerate(valeurs) if v is not None and v > seuil]
        horaires.append({"jour": jour, "debut": f"{actifs[0] // 4:02d}:{actifs[0] % 4 * 15:02d}" if actifs else None,
                         "fin": f"{(actifs[-1] + 1) // 4:02d}:{(actifs[-1] + 1) % 4 * 15:02d}" if actifs else None})
    return {
        "ean": _declare_ou(fiche, "ean"),
        "sbi": _declare_ou(fiche, "sbi"),
        "gtv_kw": _declare_ou(fiche, "gtv_kw", "kW", "src_ato"),
        "transport_autres": _declare_ou(fiche, "transport_autres", "", "src_ato"),
        "changements_prevus": _declare_ou(fiche, "changements_prevus", "", "src_ato"),
        "heures_activite": (grandeur(fiche["heures_activite_an"], "h/an", "declare", "src_fiche") if fiche.get("heures_activite_an")
                            else grandeur(round(heures), par_periode(kw, "h/an"), "simule", "src_activite_estimee",
                                          seuil=round(seuil), part=SEUIL_ACTIVITE)),
        "horaires_semaine": fiche.get("horaires_semaine") or horaires,
        "horaires_nature": "declare" if fiche.get("horaires_semaine") else "simule",
        "seuil_activite_kw": round(seuil, 1),
        "autres_energies": _declare_ou(fiche, "autres_energies"),
    }


def fenetre_circulaire(heures: list[int]) -> tuple[int, int]:
    """Début et fin (exclue) de la plus courte fenêtre sur 24 h qui contient toutes ces heures."""
    hs = sorted(set(heures))
    if len(hs) == 1:
        return hs[0], hs[0] + 1
    ecart, i = max(((hs[(k + 1) % len(hs)] - hs[k]) % 24, k) for k in range(len(hs)))
    return hs[(i + 1) % len(hs)], hs[i] + 1


def analyse_pics_creux(kw: list[float], fins: list[datetime], stats: dict[str, Any], prof: dict[str, Any]) -> dict[str, Any]:
    """Bijlage 4.12.1, article 4, a, 2° : « een analyse van de pieken en dalen van het profiel »."""
    debuts = [f - QUART for f in fins]
    par_jour: dict[str, tuple[float, datetime]] = {}
    for x, d in zip(kw, debuts):
        jour = d.date().isoformat()
        if jour not in par_jour or x > par_jour[jour][0]:
            par_jour[jour] = (x, d)
    top = sorted(par_jour.values(), key=lambda v: -v[0])[:10]
    n_top = max(1, len(kw) // 100)
    indices = sorted(range(len(kw)), key=lambda i: -kw[i])[:n_top]
    heures: dict[int, int] = defaultdict(int)
    for i in indices:
        heures[debuts[i].hour] += 1
    ouvres = sum(1 for i in indices if debuts[i].weekday() < 5)
    cumul, plage = 0, []
    for h, c in sorted(heures.items(), key=lambda v: -v[1]):
        plage.append(h)
        cumul += c
        if cumul >= 0.9 * n_top:
            break
    h1, h2 = fenetre_circulaire(plage)
    # La fenêtre couvre au moins 90 % de ces quarts d'heure : le rapport donne la part exacte, pas « toutes »
    # (troisième relecture, point 10 : 336 sur 351 dans la fenêtre affichée, soit 95,7 %).
    dans_fenetre = sum(1 for i in indices if (h1 <= debuts[i].hour < h2 if h1 < h2 else
                                              debuts[i].hour >= h1 or debuts[i].hour < h2 % 24 or h1 == h2 % 24))
    nuit = [x for x, d in zip(kw, debuts) if d.hour < 6]
    ouvre = [x for x, d in zip(kw, debuts) if d.weekday() < 5]
    repos = [x for x, d in zip(kw, debuts) if d.weekday() >= 5]
    mensuel = prof["mensuel"]
    return {
        "pics": [{"instant": d.isoformat(timespec="minutes"), "kw": x} for x, d in top],
        "quarts_top_1pct": n_top,
        "part_top_jours_ouvres": round(ouvres / n_top, 3),
        # Plus courte fenêtre circulaire qui couvre ces heures : des pointes de 23 h et de 0 h donnent 23 h à 1 h,
        # pas « 0 h à 24 h » (relecture de 05 h 50, mineur 17).
        "heures_top_min": h1, "heures_top_max": h2, "part_top_fenetre": round(dans_fenetre / n_top, 3),
        "mois_pointe_max": max(mensuel, key=lambda m: m["max_kw"]),
        "mois_pointe_min": min(mensuel, key=lambda m: m["max_kw"]),
        "moyenne_nuit_kw": round(sum(nuit) / len(nuit), 1) if nuit else None,
        "moyenne_jours_ouvres_kw": round(sum(ouvre) / len(ouvre), 1) if ouvre else None,
        "moyenne_week_end_kw": round(sum(repos) / len(repos), 1) if repos else None,
        "charge_de_base_kw": stats["charge_de_base_kw"]["valeur"],
        "minimum_kw": min(kw),
    }


def moments(avant: list[float], apres: list[float], fins: list[datetime]) -> dict[str, Any]:
    """Bijlage 4.12.1, article 5, d : quand la flexibilité est utilisée, en semaine et en journée au quart
    d'heure. On garde, pour chaque quart d'heure de la semaine et du jour, la baisse maximale vue sur la
    période (et la hausse, recharge ou report), et le nombre de jours où elle a servi."""
    semaine_baisse = [[0.0] * 96 for _ in range(7)]
    semaine_hausse = [[0.0] * 96 for _ in range(7)]
    jour_baisse, jour_hausse, activations = [0.0] * 96, [0.0] * 96, [0] * 96
    for a, b, f in zip(avant, apres, fins):
        d = f - QUART
        j, q = d.weekday(), d.hour * 4 + d.minute // 15
        if a - b > 1e-6:
            semaine_baisse[j][q] = max(semaine_baisse[j][q], a - b)
            jour_baisse[q] = max(jour_baisse[q], a - b)
            activations[q] += 1
        elif b - a > 1e-6:
            semaine_hausse[j][q] = max(semaine_hausse[j][q], b - a)
            jour_hausse[q] = max(jour_hausse[q], b - a)
    return {"semaine_baisse": [[round(v, 1) for v in jour] for jour in semaine_baisse],
            "semaine_hausse": [[round(v, 1) for v in jour] for jour in semaine_hausse],
            "jour_baisse": [round(v, 1) for v in jour_baisse], "jour_hausse": [round(v, 1) for v in jour_hausse],
            "quarts_actifs": sum(activations)}


# GOTORK, Netcode elektriciteit art. 7.13 (codebesluit ACM du 16/04/2024, Stcrt. 2024, 13531, paru le 25/04/2024,
# en vigueur le 26/04/2024, relu dans le XML officiel le 27/09/2026) : en zone de congestion, le gestionnaire peut
# baisser le GTV ferme si, sur les 12 mois précédents, au plus 50 % en a servi ou 1 MW ou plus est resté inutilisé
# (10 MW à partir de 110 kV), après notification écrite et concertation, pour la seule part qui ne servira pas dans
# un délai d'au moins 12 mois. Jamais automatique : le scan signale un risque, pas une perte.
GOTORK_PART_UTILISEE_MAX = 0.5
GOTORK_KW_INUTILISES_MIN = 1000.0


def marge_sous_gtv(gtv_kw: float | None, pointe_kw: float, groupe: bool = False) -> dict[str, Any]:
    """Marge entre le transport contracté et la pointe mesurée, et les deux règles ACM qui la rendent urgente :
    GOTORK (seuils ci-dessus) et la fin de l'augmentation automatique du GTV en cas de dépassement en zone de
    congestion (26/04/2025). Une marge sous les deux seuils GOTORK n'est pas signalée comme exposée."""
    if not gtv_kw:
        return {"kw": grandeur(None, "kW", "a_completer", "src_ato")}
    marge = gtv_kw - pointe_kw
    if groupe:
        # Audit O1 : GOTORK vaut par raccordement ; sur la somme des GTV d'un groupe, le foisonnement ferait franchir un
        # seuil qu'aucun site n'atteint.
        regle, cle = "groupe", "src_gotork_groupe"
    elif marge > 0:
        expose = pointe_kw <= GOTORK_PART_UTILISEE_MAX * gtv_kw or marge >= GOTORK_KW_INUTILISES_MIN
        regle, cle = ("gotork", "src_acm_gotork") if expose else ("marge", "src_acm_gotork_sous_seuil")
    else:
        regle, cle = ("limite", "src_acm_limite") if marge == 0 else ("depassement", "src_acm_depassement")
    return {"kw": grandeur(round(marge, 1), "kW", "simule", "src_marge_gtv", gtv=gtv_kw, pointe=pointe_kw),
            "part": round(marge / gtv_kw, 3), "regle": regle, "source": cle}


def croissance(pointe_kw: float, plafond_kw: float, gtv_kw: float | None) -> dict[str, Any]:
    """Ce que la mesure rend possible sans nouvelle demande au réseau : tenir le plafond libère (pointe - plafond)
    kW pour de nouveaux usages sans dépasser la pointe actuelle, plus la marge encore libre sous le GTV."""
    liberes = max(0.0, pointe_kw - plafond_kw)
    marge = max(0.0, gtv_kw - pointe_kw) if gtv_kw else None
    # Relecture de 05 h 50, défaut 1 : un site qui dépasse déjà son GTV ne dispose, sans nouvelle demande, que de
    # GTV - plafond (rien si le plafond reste au-dessus du GTV), pas de pointe - plafond.
    depassement = max(0.0, pointe_kw - gtv_kw) if gtv_kw else 0.0
    total = max(0.0, gtv_kw - plafond_kw) if gtv_kw else liberes
    return {"liberes_kw": round(liberes, 1), "marge_gtv_kw": None if marge is None else round(marge, 1),
            "depassement_kw": round(depassement, 1), "gtv_kw": gtv_kw,
            "total_kw": grandeur(round(total, 1), "kW", "simule", "src_croissance")}


def profil_croissance(fins: list[datetime], prevue: dict[str, Any]) -> list[float]:
    """Charge ajoutée par un projet (pompes à chaleur, bornes, ligne de production) : `kw` pendant la plage
    `debut`-`fin` (fin d'intervalle en heure locale, plage de nuit admise), les jours « ouvres » ou « tous »."""
    kw = float(prevue["kw"])
    if kw <= 0:
        raise ValueError("Croissance prévue : puissance ajoutée attendue positive.")
    minutes = lambda h: int(h.split(":")[0]) * 60 + int(h.split(":")[1])
    debut, fin = minutes(prevue.get("debut", "00:00")), minutes(prevue.get("fin", "24:00"))
    jours = prevue.get("jours", "tous")
    if jours not in ("ouvres", "tous"):
        raise ValueError("Croissance prévue : jours « ouvres » ou « tous ».")
    ajout = []
    for f in fins:
        d = f - QUART
        m = d.hour * 60 + d.minute
        dans_plage = debut <= m < fin if debut < fin else (m >= debut or m < fin)
        ajout.append(kw if dans_plage and (jours == "tous" or d.weekday() < 5) else 0.0)
    return ajout


def sensibilite(kw: list[float], plafond: float, hyp: dict[str, Any], batterie: dict[str, Any]) -> dict[str, Any]:
    """Robustesse des conclusions aux deux hypothèses les plus fragiles : la fenêtre de décalage que les process
    supportent, et le C-rate de la batterie. On recalcule seulement ce qui en dépend."""
    fenetres = []
    for heures in (1, 2, 4, 8):
        ligne = {"heures": heures, **_part_decalable(kw, plafond, heures)}
        if not ligne["faisable"]:
            ligne["batterie_complement"] = _complement_batterie(kw, plafond, heures, hyp)
        fenetres.append(ligne)
    c_rates = []
    utile = (batterie.get("capacite_utile_kwh") or {}).get("valeur")
    besoin = (batterie.get("flex_kw") or {}).get("valeur")
    if utile and besoin:
        prix = hyp.get("prix_batterie_eur_kwh")
        reference = (batterie.get("capacite_nominale_kwh") or {}).get("valeur")
        for c in (0.5, 1.0, 2.0):
            nominale = max(utile / hyp["profondeur_decharge"], besoin / c)
            dimension = "puissance" if besoin / c >= utile / hyp["profondeur_decharge"] else "energie"
            if reference and abs(c - hyp["puissance_sur_capacite_max"]) < 1e-9:
                # La batterie de l'option 5.1 : même capacité et même prix, pas un recalcul sur des valeurs arrondies
                # qui lui donnait un second prix (troisième relecture, point 3).
                nominale = reference
                dimension = batterie["capacite_nominale_kwh"]["source"].removeprefix("src_nominale_")
            ligne = {"c_rate": c, "nominale_kwh": round(nominale, 1), "dimension": dimension}
            if prix:
                ligne["investissement_eur"] = _invest_batterie(nominale, hyp)
            c_rates.append(ligne)
    return {"fenetres": fenetres, "c_rates": c_rates}


def _complement_batterie(kw: list[float], plafond: float, heures: float, hyp: dict[str, Any]) -> dict[str, Any] | None:
    """Combinaison de mesures (Flex-e, articles 6 et 7) : ce que le décalage laisse au-dessus du plafond, couvert
    par une batterie dimensionnée sur ce reste seulement."""
    from moteur import capacite_rapide
    reste, _, _ = decaler(kw, plafond, heures)
    besoin = max(reste) - plafond
    if besoin <= 1e-6:
        return None
    r = capacite_rapide(reste, plafond, rendement=math.sqrt(hyp["rendement_aller_retour"]), puissance_max=besoin, pas_heures=PAS_H)
    if r.get("statut") != 0:
        return {"faisable": False}
    utile = float(r["capacite_utile_kwh"])
    nominale = max(utile / hyp["profondeur_decharge"], besoin / hyp["puissance_sur_capacite_max"])
    return {"faisable": True, "puissance_kw": round(besoin, 1), "utile_kwh": round(utile, 1), "nominale_kwh": round(nominale, 1)}


def _nominale_batterie(profil: list[float], plafond: float, hyp: dict[str, Any], puissance: float | None = None) -> float | None:
    """Capacité nominale qui tient le plafond sur ce profil, par le même calcul que option_batterie ; 0 sans dépassement.
    `puissance` permet une batterie plus puissante que le dépassement, donc qui se recharge plus vite."""
    from moteur import capacite_rapide
    besoin = max(profil) - plafond
    if besoin <= 1e-6:
        return 0.0
    puissance = max(besoin, puissance or 0.0)
    r = capacite_rapide(profil, plafond, rendement=math.sqrt(hyp["rendement_aller_retour"]), puissance_max=puissance, pas_heures=PAS_H)
    if r.get("statut") != 0:
        return None
    return max(float(r["capacite_utile_kwh"]) / hyp["profondeur_decharge"], puissance / hyp["puissance_sur_capacite_max"])


def _invest_batterie(nominale: float, hyp: dict[str, Any]) -> list[float] | None:
    """Fourchette d'investissement de option_batterie pour une capacité nominale donnée (même prix, même règle)."""
    prix = hyp.get("prix_batterie_eur_kwh")
    if not prix or not nominale:
        return None if not prix else [0.0, 0.0]
    nominale = round(nominale, 1)  # la capacité que le rapport affiche
    bas, haut = (prix, prix) if isinstance(prix, (int, float)) else prix
    if prix == HYPOTHESES_DEFAUT["prix_batterie_eur_kwh"]["valeur"] and nominale > 100:
        # Audit F3 : 350 €/kWh sur la seule part au-delà de 100 kWh (« richting € 350 per kWh »), pour que la borne
        # basse ne baisse plus d'un coup de 5 000 € quand la batterie passe de 100 à 100,1 kWh.
        return [round(100 * bas + 350 * (nominale - 100), -2), round(nominale * haut, -2)]
    return [round(nominale * bas, -2), round(nominale * haut, -2)]


# Un dépassement de 0,05 kW au plus (la moitié de la précision affichée) ne fait pas un jour de pointe : sinon la
# synthèse et la section se contredisaient pour un jour à 150,04 kW sous un plafond de 150 (relecture de 05 h, 10 c).
TOLERANCE_JOUR_KW = 0.05


def quarts_decisifs(kw: list[float], fins: list[datetime], plafond: float, hyp: dict[str, Any]) -> dict[str, Any]:
    """Les quelques quarts d'heure qui fixent la capacité (la pointe) et la taille de la batterie, avec des
    contrefactuels calculés : ce que deviendrait chaque grandeur si ces quarts d'heure avaient été plus bas.
    Un calcul, pas une recommandation : dire s'ils peuvent baisser demande les données de process et l'avis
    de l'ingénieur du site (demande de Vincent, 27/09 à 3 h 27)."""
    ordre = sorted(range(len(kw)), key=kw.__getitem__, reverse=True)
    pointe = kw[ordre[0]]
    debut = lambda i: fins[i] - QUART  # noqa: E731
    capacite = []
    for k in (1, 4, 8, 16, 32):
        if k >= len(kw):
            break
        niveau = kw[ordre[k]]
        capacite.append({"quarts": k, "heures": k * PAS_H, "jours": len({debut(i).date() for i in ordre[:k]}),
                         "pointe_kw": round(niveau, 1), "baisse_kw": round(pointe - niveau, 1),
                         "baisse_part": round((pointe - niveau) / pointe, 4) if pointe else 0.0})
    par_jour: dict[Any, dict[str, Any]] = {}
    for i, x in enumerate(kw):
        if x > plafond + TOLERANCE_JOUR_KW:
            jour = debut(i).date()
            d = par_jour.setdefault(jour, {"jour": jour.isoformat(), "max_kw": 0.0, "quarts": 0, "energie_kwh": 0.0, "indices": []})
            d["max_kw"] = max(d["max_kw"], x)
            d["quarts"] += 1
            d["energie_kwh"] += (x - plafond) * PAS_H
            d["indices"].append(i)
    # Poids d'un jour pour la batterie : la capacité qu'il demanderait seul, sans recharge dans la journée.
    poids = lambda d: max(d["energie_kwh"] / hyp["profondeur_decharge"], (d["max_kw"] - plafond) / hyp["puissance_sur_capacite_max"])  # noqa: E731
    jours = sorted(par_jour.values(), key=poids, reverse=True)
    reference = _nominale_batterie(kw, plafond, hyp)  # même calcul que les contrefactuels, sans arrondi
    sans = []
    profil = list(kw)
    puissance_reference = max(kw) - plafond
    for rang, d in enumerate(jours[:3], 1):
        for i in d["indices"]:
            profil[i] = plafond
        # Relecture de 05 h, défaut 7 : réduire la puissance au dépassement restant ralentit la recharge et pouvait
        # donner une batterie plus grosse que la référence. On garde la plus petite des deux : puissance réduite,
        # ou puissance de la référence (qui ne peut pas demander plus d'énergie une fois des jours retirés).
        reduite = max(0.0, max(profil) - plafond)
        candidats = [(n, p) for n, p in ((_nominale_batterie(profil, plafond, hyp), reduite),
                                         (_nominale_batterie(profil, plafond, hyp, puissance_reference), puissance_reference))
                     if n is not None]
        if not candidats:
            break
        nominale, puissance = min(candidats)
        sans.append({"jours_retires": rang, "nominale_kwh": round(nominale, 1), "puissance_kw": round(puissance if nominale else 0.0, 1),
                     "aucune": max(profil) - plafond <= TOLERANCE_JOUR_KW,
                     # Bruit numérique du moteur ramené à 0 ; une vraie hausse resterait visible.
                     "baisse_part": (round(0.0 if -1e-3 < 1 - nominale / reference < 0 else 1 - nominale / reference, 4)
                                     if reference else None),
                     "investissement_eur": _invest_batterie(nominale, hyp)})
    liste = [{"jour": d["jour"], "max_kw": round(d["max_kw"], 1), "quarts": d["quarts"], "energie_kwh": round(d["energie_kwh"], 1),
              "baisse_necessaire": round((d["max_kw"] - plafond) / d["max_kw"], 4)} for d in jours]
    i_pointe = ordre[0]
    return {"pointe": {"debut": debut(i_pointe).isoformat(timespec="minutes"), "kw": round(pointe, 1),
                       "quarts": sum(1 for x in kw if x >= pointe - 1e-9)},
            "top": [{"debut": debut(i).isoformat(timespec="minutes"), "kw": round(kw[i], 1)} for i in ordre[:8]],
            "capacite": capacite,
            "jours_au_dessus": len(liste),
            "jours": liste[:5],
            "batterie_nominale_kwh": round(reference, 1) if reference is not None else None,
            "batterie_investissement_eur": _invest_batterie(reference, hyp) if reference is not None else None,
            "sans_jours": sans}


TIRAGES_CONFIANCE = 100


def confiance(kw: list[float], fins: list[datetime], plafond: float, hyp: dict[str, Any],
              tirages: int = TIRAGES_CONFIANCE, graine: int = 2026) -> dict[str, Any] | None:
    """Niveau de confiance par rééchantillonnage des jours de l'année mesurée (priorité 3 de Vincent, 27/09).
    Chaque jour complet (96 quarts) est remplacé par un jour mesuré du même mois et du même type (ouvré, samedi,
    dimanche), tiré au hasard avec une graine fixe ; les jours de changement d'heure et les jours incomplets
    restent tels quels. Limites, dites dans le rapport : aucune journée plus haute que la plus haute mesurée ne
    peut apparaître, donc l'intervalle sous-estime le risque de pointe ; les jours fériés comptent comme des jours
    ouvrés ; une année de croissance ou de météo plus rude n'est pas couverte."""
    if tirages <= 0:
        return None
    jours: dict[Any, list[int]] = defaultdict(list)
    for i, f in enumerate(fins):
        jours[(f - QUART).date()].append(i)
    blocs = []  # (début, longueur, strate) dans l'ordre du calendrier ; strate None = jour gardé tel quel
    for jour in sorted(jours):
        indices = jours[jour]
        complet = len(indices) == 96 and indices[-1] - indices[0] == 95
        type_jour = "ouvre" if jour.weekday() < 5 else "samedi" if jour.weekday() == 5 else "dimanche"
        blocs.append((indices[0], len(indices), (jour.month, type_jour) if complet else None))
    strates: dict[Any, list[int]] = defaultdict(list)
    for debut, _, strate in blocs:
        if strate is not None:
            strates[strate].append(debut)
    if len(strates) == 0 or sum(len(v) for v in strates.values()) < 14:
        return None
    alea = random.Random(graine)
    niveaux, heures, batteries, decalages = [], [], [], []
    for _ in range(tirages):
        serie: list[float] = []
        for debut, longueur, strate in blocs:
            source = alea.choice(strates[strate]) if strate is not None else debut
            serie.extend(kw[source:source + longueur])
        niveaux.append(plafond_heures(serie, hyp["heures_ecretees"]))
        heures.append(sum(1 for x in serie if x > plafond) * PAS_H)
        batteries.append(_nominale_batterie(serie, plafond, hyp))
        decalages.append(_part_decalable(serie, plafond, hyp["fenetre_decalage_h"])["faisable"])
    def bornes(valeurs):
        valeurs = [v for v in valeurs if v is not None]
        if len(valeurs) < 2:
            return None
        q = statistics.quantiles(valeurs, n=20, method="inclusive")  # jamais hors des valeurs tirées (relecture de 05 h)
        return {"p5": round(q[0], 1), "mediane": round(statistics.median(valeurs), 1), "p95": round(q[-1], 1)}
    return {"tirages": tirages, "graine": graine, "jours_reechantillonnes": sum(len(v) for v in strates.values()),
            "jours_gardes": sum(1 for _, _, strate in blocs if strate is None),
            "niveau_heures_kw": {"mesure": round(plafond_heures(kw, hyp["heures_ecretees"]), 1), **(bornes(niveaux) or {})},
            "heures_au_dessus": {"mesure": round(sum(1 for x in kw if x > plafond) * PAS_H, 2), **(bornes(heures) or {})},
            # None : aucune batterie ne tient le plafond (l'année mesurée ou un tirage), compté à part et jamais « 0 kWh ».
            "batterie_kwh": {"mesure": (round(mesure, 1) if (mesure := _nominale_batterie(kw, plafond, hyp)) is not None else None),
                             **(bornes(batteries) or {})},
            "batterie_impossible_part": round(sum(1 for b in batteries if b is None) / tirages, 3),
            "decalage_suffisant_part": round(sum(decalages) / tirages, 3)}


def _part_decalable(kw: list[float], plafond: float, heures: float) -> dict[str, Any]:
    _, reporte, non_reporte = decaler(kw, plafond, heures)
    total = reporte + non_reporte
    return {"part_reportee": round(reporte / total, 4) if total else 1.0, "faisable": non_reporte <= 1e-6}


def tranche_etvt(ans: float) -> str:
    return next(nom for borne, nom in TRANCHES_ETVT if ans < borne)


# ---------------------------------------------------------------- tarifs

def gestionnaire_tarifs(fiche: dict[str, Any]) -> tuple[str, str]:
    """Grille du gestionnaire de la fiche ; sans gestionnaire connu, grille Liander par défaut (hypothèse)."""
    nom = str(fiche.get("gestionnaire") or "").strip().lower()
    if nom in TARIFS_2026:
        return nom, "declare"
    return "liander", "hypothese"


def categorie_tarifaire(fiche: dict[str, Any], pointe_kw: float, gestionnaire: str = "liander") -> tuple[str, str]:
    """Catégorie du gestionnaire : lue dans la fiche si possible, sinon estimée d'après la puissance (hypothèse)."""
    grille = TARIFS_2026[gestionnaire]
    donnee = fiche.get("categorie_tarifaire")
    if donnee in grille and donnee != "bornes":
        return donnee, "tarif"
    reference = fiche.get("gtv_kw") or pointe_kw
    return next(nom for borne, nom in grille["bornes"] if reference <= borne), "hypothese"


def economie_kwmax(avant: list[float], apres: list[float], fins: list[datetime], tarif_mois: float | None,
                   gestionnaire: str = "liander") -> dict[str, Any]:
    """Seul levier tarifaire compté : la baisse du kWmax de chaque mois. Baisser le kW contracté n'est
    PAS compté : en zone saturée, une capacité rendue ne revient que sur nouvelle demande, si la capacité existe (affaire NorthC, RES-012 ; arrêt du
    CBb le 23/06/2026 : un GTV déclaré plus bas réduit aussi le droit ferme)."""
    pics_avant: dict[str, float] = defaultdict(float)
    pics_apres: dict[str, float] = defaultdict(float)
    for a, b, f in zip(avant, apres, fins):
        m = (f - QUART).strftime("%Y-%m")
        pics_avant[m] = max(pics_avant[m], a)
        pics_apres[m] = max(pics_apres[m], b)
    baisse = {m: round(pics_avant[m] - pics_apres[m], 1) for m in pics_avant}
    kw_mois = round(sum(baisse.values()), 1)
    unite = par_periode(avant, "€/an")
    if tarif_mois is None:
        return {"kw_mois_evites": kw_mois, "par_mois": baisse, "eur_an": grandeur(None, unite, "a_chiffrer", "src_pas_kwmax")}
    return {"kw_mois_evites": kw_mois, "par_mois": baisse,
            "eur_an": grandeur(round(kw_mois * tarif_mois), unite, "simule", "src_kwmax", tarif=tarif_mois, kw_mois=kw_mois,
                               gestionnaire=gestionnaire.capitalize())}


# ---------------------------------------------------------------- options

def simuler_batterie(kw: list[float], plafond: float, capacite_kwh: float, puissance_kw: float,
                     rendement_sens: float, etats: list[float] | None = None) -> tuple[list[float], list[float]]:
    """Batterie pleine au départ, décharge dès que la demande dépasse le plafond, recharge au plus tôt
    sous le plafond. Renvoie le profil vu du réseau et la puissance déchargée à chaque quart ; remplit
    `etats` (énergie stockée en kWh à la fin de chaque quart) si une liste est fournie."""
    etat = capacite_kwh
    reseau, decharge = [], []
    for x in kw:
        if x > plafond:
            d = min(x - plafond, puissance_kw, etat * rendement_sens / PAS_H)
            etat -= d * PAS_H / rendement_sens
            reseau.append(x - d)
            decharge.append(d)
        else:
            c = min(plafond - x, puissance_kw, (capacite_kwh - etat) / (rendement_sens * PAS_H))
            etat += c * PAS_H * rendement_sens
            reseau.append(x + c)
            decharge.append(0.0)
        if etats is not None:
            etats.append(etat)
    return reseau, decharge


def rainflow(serie: list[float]) -> list[tuple[float, float]]:
    """Comptage rainflow (méthode à trois points, ASTM E1049-85) : liste de (amplitude, nombre), nombre valant 1
    pour un cycle complet et 0,5 pour un demi-cycle."""
    pics: list[float] = []
    for x in serie:  # points de retournement seulement
        if len(pics) >= 2 and (pics[-1] - pics[-2]) * (x - pics[-1]) >= 0:
            pics[-1] = x
        elif not pics or x != pics[-1]:
            pics.append(x)
    cycles, pile = [], []
    for x in pics:
        pile.append(x)
        while len(pile) >= 3:
            recent, ancien = abs(pile[-1] - pile[-2]), abs(pile[-2] - pile[-3])
            if recent < ancien:
                break
            if len(pile) == 3:
                cycles.append((ancien, 0.5))
                pile.pop(0)
            else:
                cycles.append((ancien, 1.0))
                del pile[-3:-1]
    cycles.extend((abs(b - a), 0.5) for a, b in zip(pile, pile[1:]))
    return [c for c in cycles if c[0] > 0]


CLASSES_PROFONDEUR = ((0.0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0))
# Bornes de contrôle de la garantie fournie par la fiche (revue de 04 h 12) : des garde-fous contre une saisie
# absurde, pas des valeurs de vieillissement.
BORNES_GARANTIE = {"cycles": 1e6, "annees": 50, "profondeur": 1.0, "etat_fin": 1.0}


def garantie_controlee(garantie: Any) -> dict[str, Any] | None:
    """Garantie du fabricant lue dans la fiche : chaque champ présent doit être un nombre fini dans ]0, borne] ;
    profondeur et état final sont des fractions. Un champ absent laisse la durée de vie « à compléter »."""
    if garantie is None:
        return None
    if not isinstance(garantie, dict):
        raise ValueError("batterie_garantie : objet attendu (cycles, profondeur, annees, etat_fin, source).")
    for cle, borne in BORNES_GARANTIE.items():
        v = garantie.get(cle)
        if v is None:
            continue
        if not nombre_fini(v) or not 0 < v <= borne:
            raise ValueError(f"batterie_garantie.{cle} : nombre fini dans ]0, {borne:g}] attendu, reçu {str(v)[:40]!r}.")
    return garantie


def usure_batterie(kw: list[float], etats: list[float], nominale: float, profondeur_decharge: float,
                   arbitrage: dict[str, Any] | None, garantie: dict[str, Any] | None) -> dict[str, Any]:
    """Usure de la batterie (priorité 4 de Vincent, 27/09) : comptage rainflow de l'énergie stockée simulée, en part
    de la capacité nominale. Aucun taux de vieillissement n'est supposé. La durée de vie n'est calculée qu'avec la
    garantie du fabricant fournie par la fiche (cycles à une profondeur donnée, années, capacité restante en fin de
    garantie), en comptant l'usure comme l'énergie cumulée, comme le font les garanties exprimées en énergie."""
    profondeurs = [(amplitude / nominale, nombre) for amplitude, nombre in rainflow(etats)] if nominale else []
    classes = [{"de": de, "a": a, "cycles": round(sum(n for d, n in profondeurs if de <= d < a or (a == 1.0 and d >= 1.0)), 1)}
               for de, a in CLASSES_PROFONDEUR]
    equivalents = sum(d * n for d, n in profondeurs)
    unite = par_periode(kw, "cycles/an")
    resultat = {"classes": classes,
                "cycles_pleins": grandeur(round(equivalents, 1), unite, "simule", "src_rainflow"),
                "profondeur_max": grandeur(round(max((d for d, _ in profondeurs), default=0.0), 3), "%", "simule", "src_rainflow"),
                # L'arbitrage (borne haute) fait un cycle par jour de toute la capacité utile, nominale x profondeur de décharge.
                "cycles_arbitrage_an": (grandeur(round(365 * profondeur_decharge), "cycles/an", "simule", "src_cycles_arbitrage")
                                        if arbitrage else None)}
    if not garantie or not all(garantie.get(k) for k in ("cycles", "profondeur", "annees", "etat_fin")):
        resultat["duree_vie_ans"] = grandeur(None, "ans", "a_completer", "src_garantie_fabricant")
        resultat["nominale_fin_vie_kwh"] = grandeur(None, "kWh", "a_completer", "src_garantie_fabricant")
        return resultat
    if unite != "cycles/an":
        resultat["duree_vie_ans"] = grandeur(None, "ans", "a_chiffrer", "src_duree_courte")
    else:
        ans_cycles = garantie["cycles"] * garantie["profondeur"] / equivalents if equivalents else math.inf
        limite = "cycles" if ans_cycles < garantie["annees"] else "calendrier"
        resultat["duree_vie_ans"] = grandeur(round(min(garantie["annees"], ans_cycles), 1), "ans", "simule", "src_duree_garantie_" + limite,
                                             cycles=garantie["cycles"], profondeur=round(garantie["profondeur"] * 100),
                                             annees=garantie["annees"], garantie=garantie.get("source") or "")
    resultat["nominale_fin_vie_kwh"] = grandeur(round(nominale / garantie["etat_fin"], 1), "kWh", "simule", "src_fin_vie",
                                                etat=round(garantie["etat_fin"] * 100))
    return resultat


@lru_cache(maxsize=1)
def prix_day_ahead() -> tuple[tuple[str, float, float], ...]:
    """(jour local à Amsterdam, durée en heures, prix en €/MWh) ; vide si le fichier manque."""
    if not PRIX_DAY_AHEAD.exists():
        return ()
    creneaux = []
    for ligne in PRIX_DAY_AHEAD.read_text(encoding="utf-8").splitlines()[1:]:
        debut, duree, prix = ligne.split(",")
        jour = datetime.fromisoformat(debut + "+00:00").astimezone(AMSTERDAM).date().isoformat()
        creneaux.append((jour, int(duree) / 60, float(prix)))
    return tuple(creneaux)


def _remplir(creneaux: list[tuple[float, float]], energie_kwh: float, puissance_kw: float) -> float:
    """Coût (ou recette) en euros d'une énergie répartie sur les créneaux donnés, dans l'ordre, à puissance bornée."""
    reste, montant = energie_kwh, 0.0
    for prix, heures in creneaux:
        e = min(reste, puissance_kw * heures)
        montant += e * prix / 1000
        reste -= e
        if reste <= 1e-9:
            break
    return montant


def arbitrage_annuel(utile_kwh: float, puissance_kw: float, rendement_sens: float,
                     creneaux: tuple[tuple[str, float, float], ...] | None = None) -> dict[str, Any] | None:
    """Borne haute du revenu d'arbitrage day-ahead : un cycle par jour, prévision parfaite ; achat aux créneaux
    les moins chers, restitution aux plus chers, sans imposer l'ordre dans la journée. Suppose un contrat de
    fourniture indexé sur le day-ahead, ignore taxes, frais de réseau sur l'énergie et conflit avec l'écrêtage."""
    creneaux = prix_day_ahead() if creneaux is None else creneaux
    if not creneaux or utile_kwh <= 0 or puissance_kw <= 0:
        return None
    par_jour: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for jour, heures, prix in creneaux:
        par_jour[jour].append((prix, heures))
    total, jours = 0.0, 0
    for jour, liste in par_jour.items():
        if sum(h for _, h in liste) < 20:  # jour incomplet en bord de fichier
            continue
        cout = _remplir(sorted(liste), utile_kwh / rendement_sens, puissance_kw)
        recette = _remplir(sorted(liste, reverse=True), utile_kwh * rendement_sens, puissance_kw)
        total += max(0.0, recette - cout)
        jours += 1
    return {"eur_an": total * 365 / jours if jours else 0.0, "jours": jours}


def option_batterie(kw, fins, plafond, hyp, tarif_mois, gestionnaire="liander", garantie=None) -> dict[str, Any]:
    from moteur import capacite_rapide
    besoin_kw = max(kw) - plafond
    rendement_sens = math.sqrt(hyp["rendement_aller_retour"])
    r = capacite_rapide(kw, plafond, rendement=rendement_sens, puissance_max=besoin_kw, pas_heures=PAS_H)
    base = {"id": "batterie"}
    if r.get("statut") != 0:
        return {**base, "faisable": False, "raison": r.get("message", "dimensionnement impossible")}
    utile = float(r["capacite_utile_kwh"])
    # Deux bornes : l'énergie à stocker, et la puissance à fournir, qu'une batterie ne délivre qu'en
    # proportion de sa capacité. Sur une pointe courte, c'est souvent la puissance qui dimensionne.
    par_energie = utile / hyp["profondeur_decharge"]
    par_puissance = besoin_kw / hyp["puissance_sur_capacite_max"]
    nominale = max(par_energie, par_puissance)
    dimension = "puissance" if par_puissance >= par_energie else "energie"
    # Petite marge numérique : la capacité exacte du moteur laisse sinon des écarts de l'ordre de 1e-9 kW.
    etats: list[float] = []
    apres, decharge = simuler_batterie(kw, plafond, utile * (1 + 1e-6), besoin_kw, rendement_sens, etats)
    energie = sum(decharge) * PAS_H
    prix = hyp.get("prix_batterie_eur_kwh")
    if prix:
        # Montant calculé sur la capacité affichée, au dixième, par la même règle que _invest_batterie : la formule
        # écrite dans le rapport retombe sur le montant (troisième relecture, point 2).
        bas, haut = (prix, prix) if isinstance(prix, (int, float)) else prix
        palier = prix == HYPOTHESES_DEFAUT["prix_batterie_eur_kwh"]["valeur"] and round(nominale, 1) > 100
        invest = grandeur(_invest_batterie(nominale, hyp), "€", "hypothese", "src_invest_prix_palier" if palier else "src_invest_prix",
                          bas=bas, haut=haut, nominale=round(nominale, 1))
    else:
        invest = grandeur(None, "€", "a_chiffrer", "src_invest_a_demander")
    arbitrage = arbitrage_annuel(nominale * hyp["profondeur_decharge"], nominale * hyp["puissance_sur_capacite_max"], rendement_sens)
    arbitrage_g = (grandeur(round(arbitrage["eur_an"]), "€/an", "simule", "src_arbitrage", jours=arbitrage["jours"])
                   if arbitrage else grandeur(None, "€/an", "a_chiffrer", "src_arbitrage_absent"))
    return {**base, "faisable": max(apres) - plafond <= 1e-6 * max(1.0, plafond),
            "arbitrage_eur_an": arbitrage_g,
            "flex_kw": grandeur(round(besoin_kw, 1), "kW", "simule", "src_puissance_decharge"),
            "energie_mwh_an": grandeur(round(energie / 1000, 2), par_periode(kw, "MWh/an"), "simule", "src_energie_dechargee"),
            # Flex-e, article 5 c : combien de temps la mesure PEUT fournir sa flexibilité d'affilée, soit l'autonomie
            # de la batterie dimensionnée à pleine puissance ; la durée dont le site a BESOIN est donnée à part.
            "duree_h": grandeur(round(nominale * hyp["profondeur_decharge"] / besoin_kw, 2) if besoin_kw else 0, "h", "simule",
                                "src_autonomie_dimensionnee", dod=hyp["profondeur_decharge"]),
            "duree_besoin_h": grandeur(round(utile / besoin_kw, 2) if besoin_kw else 0, "h", "simule", "src_duree_batterie"),
            "disponibilite": grandeur("dispo_batterie", "", "hypothese", "src_prevision_parfaite"),
            "capacite_utile_kwh": grandeur(round(utile, 1), "kWh", "simule", "src_moteur"),
            "capacite_nominale_kwh": grandeur(round(nominale, 1), "kWh", "hypothese", "src_nominale_" + dimension,
                                              dod=hyp["profondeur_decharge"], crate=hyp["puissance_sur_capacite_max"]),
            "dimensionnement": dimension,
            "cycles_equivalents_an": grandeur(round(energie / utile, 1) if utile else 0, par_periode(kw, "cycles/an"), "simule"),
            "mise_en_route": grandeur("activation_batterie", "", "hypothese", "src_activation_batterie"),
            "moments": moments(kw, apres, fins),
            "investissement_eur": invest,
            "economie": economie_kwmax(kw, apres, fins, tarif_mois, gestionnaire),
            "profil_apres": apres,
            "usure": usure_batterie(kw, etats, nominale, hyp["profondeur_decharge"], arbitrage, garantie),
            "controle_moteur": {"methode": r.get("methode"), "erreur_physique_max": r.get("erreur_physique_max"),
                                "pic_simule_kw": round(max(apres), 3)}}


def decaler(kw: list[float], plafond: float, heures: float) -> tuple[list[float], float, float]:
    """Déplace la part au-dessus du plafond vers les quarts les plus proches restés sous le plafond, dans
    ± `heures`. Renvoie le profil après, l'énergie reportée et l'énergie qui n'a pas trouvé de place (kWh)."""
    fenetre = int(heures / PAS_H)
    apres = [min(x, plafond) for x in kw]
    reporte = non_reporte = 0.0
    for i, x in enumerate(kw):
        if x <= plafond:
            continue
        reste = (x - plafond) * PAS_H
        for dist in range(1, fenetre + 1):
            for j in (i + dist, i - dist):
                if reste > 1e-9 and 0 <= j < len(kw) and kw[j] <= plafond:
                    pris = min((plafond - apres[j]) * PAS_H, reste)
                    apres[j] += pris / PAS_H
                    reste -= pris
            if reste <= 1e-9:
                break
        reporte += (x - plafond) * PAS_H - reste
        non_reporte += reste
        apres[i] += reste / PAS_H
    return apres, reporte, non_reporte


def option_decalage(kw, fins, plafond, hyp, tarif_mois, gestionnaire="liander") -> dict[str, Any]:
    """Décaler la part au-dessus du plafond vers les quarts les plus proches sous le plafond, dans une
    fenêtre de ± N heures. Rien n'est perdu : l'énergie consommée reste la même."""
    apres, reporte, non_reporte = decaler(kw, plafond, hyp["fenetre_decalage_h"])
    ep = episodes(kw, plafond)
    total = reporte + non_reporte
    return {"id": "decalage",
            "faisable": non_reporte <= 1e-6,
            "part_reportee": round(reporte / total, 4) if total else 1.0,
            "flex_kw": grandeur(round(max(kw) - plafond, 1), "kW", "simule", "src_baisse_pic"),
            "energie_mwh_an": grandeur(round(reporte / 1000, 2), par_periode(kw, "MWh/an"), "simule", "src_energie_deplacee"),
            "duree_h": grandeur(ep["duree_max_h"], "h", "simule", "src_plus_long_episode"),
            "episodes": grandeur(ep["nombre"], par_periode(kw, "episodes/an"), "simule"),
            "part_charge_pic": grandeur(round((max(kw) - plafond) / max(kw), 4), "%", "simule", "src_part_charge_pic"),
            "disponibilite": grandeur("dispo_decalage", "", "hypothese", "src_confirmer_process", fenetre=hyp["fenetre_decalage_h"]),
            "mise_en_route": grandeur(None, "", "a_chiffrer", "src_activation_process"),
            "moments": moments(kw, apres, fins),
            "investissement_eur": grandeur(None, "€", "a_chiffrer", "src_invest_organisation"),
            "economie": economie_kwmax(kw, apres, fins, tarif_mois, gestionnaire),
            "profil_apres": apres}


def option_ecretage(kw, fins, plafond, hyp, tarif_mois, gestionnaire="liander") -> dict[str, Any]:
    """Réduire ou arrêter des usages au-dessus du plafond : l'énergie coupée n'est pas rattrapée."""
    apres = [min(x, plafond) for x in kw]
    ep = episodes(kw, plafond)
    energie_totale = sum(kw) * PAS_H
    return {"id": "ecretage",
            "faisable": True,
            "flex_kw": grandeur(round(max(kw) - plafond, 1), "kW", "simule", "src_puissance_couper"),
            "energie_mwh_an": grandeur(round(ep["energie_kwh"] / 1000, 2), par_periode(kw, "MWh/an"), "simule",
                                       "src_energie_non_consommee"),
            "part_energie": grandeur(round(ep["energie_kwh"] / energie_totale, 5) if energie_totale else 0, "%", "simule"),
            "duree_h": grandeur(ep["duree_max_h"], "h", "simule", "src_plus_long_episode"),
            "heures_an": grandeur(ep["quarts"] * PAS_H, par_periode(kw, "h/an"), "simule"),
            "episodes": grandeur(ep["nombre"], par_periode(kw, "episodes/an"), "simule"),
            "disponibilite": grandeur("dispo_ecretage", "", "hypothese"),
            "mise_en_route": grandeur(None, "", "a_chiffrer", "src_activation_usages"),
            "moments": moments(kw, apres, fins),
            "investissement_eur": grandeur(None, "€", "a_chiffrer", "src_invest_delestage"),
            "cout_perte": grandeur(None, par_periode(kw, "€/an"), "a_chiffrer", "src_cout_perte"),
            "economie": economie_kwmax(kw, apres, fins, tarif_mois, gestionnaire),
            "profil_apres": apres}


def remise_volledig_variabel(gtv: float | None, plafond: float | None, tarif_an: float | None,
                             gestionnaire: str = "liander", plafond_tenu: bool = True) -> dict[str, Any]:
    """Terme kW contracté ramené à zéro sur la part passée en volledig variabel (FAQ alternatieve transportrechten de
    Netbeheer Nederland, exemple NFA1.0), si la part ferme descend au plafond que la batterie ou le décalage tiennent.
    Montant tenu à part de l'économie, pour la même raison que dans economie_kwmax : le droit ferme cédé ne se
    récupère pas en zone saturée."""
    if gtv is None:
        return grandeur(None, "€/an", "a_completer", "src_remise_sans_gtv")
    if tarif_an is None:
        return grandeur(None, "€/an", "a_chiffrer", "src_pas_kw_contrat")
    kw_variable = round(gtv - plafond) if plafond is not None else 0
    if kw_variable <= 0:
        return grandeur(0, "€/an", "simule", "src_remise_gtv_sous_plafond", gtv=round(gtv), plafond=round(plafond or 0))
    if not plafond_tenu:  # relecture de 05 h : ne jamais chiffrer une remise qu'aucune mesure ne permet de tenir
        return grandeur(None, "€/an", "a_chiffrer", "src_remise_sans_mesure", plafond=round(plafond))
    return grandeur(round(kw_variable * tarif_an), "€/an", "simule", "src_remise_nfa", kw=kw_variable, plafond=round(plafond),
                    gtv=round(gtv), tarif=tarif_an, gestionnaire=gestionnaire.capitalize())


def option_contrat(kw, fins, fiche, plafond: float | None = None, tarif_kw_contrat_an: float | None = None,
                   gestionnaire: str = "liander", plafond_tenu: bool = True) -> dict[str, Any]:
    """Droits de transport alternatifs : quelle part de la charge vit avec un droit non ferme ou lié à la
    durée. On lit la courbe monotone à l'envers : durée au-dessus de chaque niveau."""
    pointe = max(kw)
    part_coupable = 1 - PART_HEURES_TDTR
    niveaux = []
    for part in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        niveau = pointe * part
        niveaux.append({"part_pointe": part, "niveau_kw": round(niveau, 1),
                        "heures_au_dessus": heures_au_dessus(kw, niveau),
                        "energie_au_dessus_mwh": round(sum(max(0.0, x - niveau) for x in kw) * PAS_H / 1000, 2)})
    tri = sorted(kw, reverse=True)
    niveau_tdtr = tri[min(int(part_coupable * len(kw)), len(tri) - 1)]
    energie_expo = sum(max(0.0, x - niveau_tdtr) for x in kw) * PAS_H
    au_niveau = [min(x, niveau_tdtr) for x in kw]
    # Droit par blocs horaires (réseaux régionaux) : pointe et énergie par bloc indicatif. Les blocs réels se
    # négocient avec le gestionnaire ; ceux-ci montrent seulement où se trouve la charge.
    # Chaque quart est rangé selon son DÉBUT en heure légale (fin - 15 min, sur des heures locales sans fuseau).
    # Aux changements d'heure, cette soustraction naïve se trompe pour les quarts de 1 h 45 à 3 h, qui restent
    # tous dans le bloc de nuit (0 h à 6 h) : sans effet ici. Un bloc plus étroit, bordé entre 1 h et 3 h, devra calculer
    # le début en UTC (convention partagée avec Codex, bus n°414).
    blocs = []
    # Nuit de 0 h à 6 h : le seul créneau Blokstroom proposé aujourd'hui (pages Enexis, Stedin et Liander lues le 27/09/2026).
    for nom, test in (("nuit", lambda d: d.hour < 6),
                      ("jour_ouvre", lambda d: d.weekday() < 5 and d.hour >= 6),
                      ("week_end_jour", lambda d: d.weekday() >= 5 and d.hour >= 6)):
        valeurs = [x for x, f in zip(kw, fins) if test(f - QUART)]
        if valeurs:
            blocs.append({"bloc": nom, "pointe_kw": round(max(valeurs), 1),
                          "energie_mwh": round(sum(valeurs) * PAS_H / 1000, 1),
                          "part_energie": round(sum(valeurs) / sum(kw), 3) if sum(kw) else 0.0})
    return {"id": "contrat",
            "faisable": None,
            "flex_kw": grandeur(round(pointe - niveau_tdtr, 1), "kW", "simule", "src_part_tdtr"),
            "energie_mwh_an": grandeur(round(energie_expo / 1000, 2), par_periode(kw, "MWh/an"), "simule", "src_energie_expo"),
            "duree_h": grandeur(round(part_coupable * 8760), "h/an", "tarif", "src_tdtr_85"),
            "droits": ["volledig_variabel", "tijdsblokgebonden", "tijdsduurgebonden"],
            "niveau_ferme_kw": grandeur(niveau_tdtr, "kW", "simule", "src_niveau_15"),
            "disponibilite": grandeur("dispo_contrat", "", "tarif", "src_reg003_004"),
            "mise_en_route": grandeur("preavis_contrat", "", "tarif", "src_acm_overzicht"),
            "moments": moments(kw, au_niveau, fins),
            "investissement_eur": grandeur(0, "€", "hypothese", "src_changement_contrat"),
            "remise": grandeur("remise_contrat", "", "tarif", "src_acm_faq_atr"),
            "remise_eur_an": remise_volledig_variabel(fiche.get("gtv_kw"), plafond, tarif_kw_contrat_an, gestionnaire, plafond_tenu),
            "niveaux": niveaux,
            "blocs": blocs,
            "gtv_kw": fiche.get("gtv_kw")}


SANCTION_SANS_OFFRE_CBC_EUR_MW_JOUR = 120.0  # ACM, Overzicht congestiemaatregelen du 30/04/2025, p. 15


def option_offre_gestionnaire(fiche, batterie, decalage) -> dict[str, Any]:
    """Offrir de la flexibilité au gestionnaire (congestiemanagement, contrat de limitation, GOPACS)."""
    gtv = fiche.get("gtv_kw")
    annoncee = fiche.get("deelnameplicht_annoncee")
    # Audit O2 : l'ACM ne fait naître l'obligation (et le montant dû) que si le gestionnaire la déclenche dans une zone de
    # congestion (« Netbeheerders kunnen de deelnameplicht inzetten in een congestiegebied », Overzicht, p. 10).
    # Audit O1 : elle vaut par raccordement de 1 MW ou plus, jamais pour la somme d'un groupe.
    if fiche.get("contrat_groupe"):
        obligation, nature, cle = None, "a_completer", "src_reg009_groupe"
        sanction = grandeur(None, "€/jour", "a_completer", "src_acm_sanction_groupe")
    elif gtv is None:
        obligation, nature, cle = None, "a_completer", "src_reg009"
        sanction = grandeur(None, "€/jour", "a_completer", "src_ato")
    elif gtv < SEUIL_CONGESTIEMANAGEMENT_KW:
        obligation, nature, cle = False, "tarif", "src_reg009"
        sanction = grandeur(0, "€/jour", "tarif", "src_acm_sanction_sans_objet")
    elif annoncee:
        obligation, nature, cle = True, "tarif", "src_reg009"
        sanction = grandeur(round(SANCTION_SANS_OFFRE_CBC_EUR_MW_JOUR * gtv / 1000), "€/jour", "tarif", "src_acm_sanction",
                            mw=round(gtv / 1000, 3))
    elif annoncee is False:
        obligation, nature, cle = False, "declare", "src_reg009_non_annoncee"
        sanction = grandeur(0, "€/jour", "declare", "src_acm_sanction_non_annoncee")
    else:
        obligation, nature, cle = None, "a_completer", "src_reg009_a_verifier"
        sanction = grandeur(None, "€/jour", "a_completer", "src_acm_sanction_si_annoncee",
                            montant=round(SANCTION_SANS_OFFRE_CBC_EUR_MW_JOUR * gtv / 1000), mw=round(gtv / 1000, 3))
    offres = [o["flex_kw"]["valeur"] for o in (batterie, decalage) if o.get("faisable") and o.get("flex_kw")]
    duree = batterie.get("duree_h", {}).get("valeur")
    return {"id": "offre_gestionnaire",
            "faisable": None,
            "flex_kw": (grandeur(max(offres), "kW", "simule", "src_offre_puissance") if offres
                        else grandeur(None, "kW", "a_chiffrer", "src_offre_puissance")),
            "energie_mwh_an": grandeur(None, "MWh/an", "a_chiffrer", "src_appels"),
            "duree_h": (grandeur(duree, "h", "simule", "src_autonomie") if duree is not None
                        else grandeur(None, "h", "a_chiffrer", "src_autonomie")),
            "obligation_1mw": grandeur(obligation, "", nature, cle),
            "sanction_sans_offre": sanction,
            "disponibilite": grandeur("dispo_offre", "", "a_chiffrer"),
            "mise_en_route": grandeur(None, "", "a_chiffrer", "src_activation_offre"),
            "investissement_eur": grandeur(0, "€", "hypothese", "src_aucun_invest"),
            "remuneration": grandeur(None, "€/an", "a_chiffrer", "src_remuneration")}


# ---------------------------------------------------------------- comparaison et recommandation

def retour(invest: dict[str, Any], economie: dict[str, Any]) -> dict[str, Any]:
    montant = invest.get("valeur")
    gain = economie.get("eur_an", {}).get("valeur")
    if economie.get("eur_an", {}).get("unite", "€/an") != "€/an":
        # Relecture de 05 h 50, défaut 2 : sur deux semaines, 178 € d'économie donnaient un retour de 230 à 460 ans.
        return grandeur(None, "ans", "a_chiffrer", "src_retour_periode")
    if gain is not None and gain < 0:
        # Constat n°12 de la relecture : la recharge peut relever le kWmax d'un mois ; un gain négatif donnait des
        # années négatives, rangées en « moins de 3 ans ».
        return grandeur(None, "ans", "a_chiffrer", "src_retour_negatif")
    if montant in (None, []) or not gain:
        return grandeur(None, "ans", "a_chiffrer", "src_retour_non_chiffre")
    bas, haut = (montant, montant) if isinstance(montant, (int, float)) else montant
    ans = [round(bas / gain, 1), round(haut / gain, 1)]
    tranches = sorted({tranche_etvt(ans[0]), tranche_etvt(ans[1])}, key=[n for _, n in TRANCHES_ETVT].index)
    return grandeur(ans, "ans", "simule", "src_retour_simple", tranches=tranches)


def recommander(options: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Ordre d'examen conseillé, tiré des chiffres. Jamais une promesse : chaque ligne dit sa condition."""
    dec, ecr, bat, off = (options[k] for k in ("decalage", "ecretage", "batterie", "offre_gestionnaire"))
    decalage = {"option": "decalage", "cle": "reco_decalage" if dec["faisable"] else "reco_decalage_partiel"}
    part = ecr["part_energie"]["valeur"]
    ecretage = {"option": "ecretage", "cle": "reco_ecretage" if part < 0.001 else "reco_ecretage_couteux"}
    ans = bat.get("retour_ans", {}).get("valeur")
    if not bat.get("faisable"):
        batterie = {"option": "batterie", "cle": "reco_batterie_impossible"}
    elif ans:
        batterie = {"option": "batterie", "cle": "reco_batterie_chiffree" if ans[0] <= 10 else "reco_batterie_longue"}
    elif (bat.get("investissement_eur") or {}).get("valeur"):
        batterie = {"option": "batterie", "cle": "reco_batterie_sans_retour"}  # prix connu, économie absente ou partielle
    else:
        batterie = {"option": "batterie", "cle": "reco_batterie_a_chiffrer"}
    # La première ligne est présentée comme « la mesure la plus prometteuse » : ce doit être une mesure qui tient la
    # limite (relecture de 05 h 50, défaut 5). Décalage s'il suffit, sinon batterie si elle tient, sinon écrêtage.
    # Une batterie qui ne se rembourse pas en 10 ans ne passe pas avant un écrêtage qui coûte moins de 0,1 % de la
    # consommation (troisième relecture, point 9 : retour de plus de 158 ans contre 0,04 MWh écrêtés).
    if dec["faisable"]:
        lignes = [decalage, ecretage, batterie]
    elif bat.get("faisable") and (batterie["cle"] == "reco_batterie_chiffree" or part >= 0.001):
        lignes = [batterie, decalage, ecretage]
    else:
        lignes = [ecretage, decalage, batterie]
    lignes.append({"option": "contrat", "cle": "reco_contrat"})
    obligation, raison = off["obligation_1mw"]["valeur"], off["obligation_1mw"]["source"]
    lignes.append({"option": "offre_gestionnaire",
                   "cle": "reco_offre_obligatoire" if obligation else "reco_offre_volontaire" if obligation is False
                   else {"src_reg009_a_verifier": "reco_offre_si_annoncee", "src_reg009_groupe": "reco_offre_groupe"}.get(raison, "reco_offre_a_verifier")})
    return lignes


def nombre_fini(valeur: Any) -> bool:
    """Nombre JSON fini, booléens exclus ; un entier géant (401 chiffres) ne doit pas lever OverflowError (audit de Codex)."""
    try:
        return type(valeur) in (int, float) and math.isfinite(valeur)
    except OverflowError:
        return False


def _nombre_fiche(valeur: Any, nom: str, borne: float = math.inf) -> None:
    if not nombre_fini(valeur) or not 0 < valeur <= borne:
        raise ValueError(f"Fiche : {nom} doit être un nombre fini dans ]0, {borne:g}], reçu {str(valeur)[:40]!r}.")


def controle_ean(fiche: dict[str, Any]) -> None:
    """La page qualité affirme l'EAN « conservé en texte » : un nombre JSON a déjà pu perdre des chiffres (8.7e+17), un
    str() au rendu ne les rendrait pas (revue d'Astra de 26ba18b, P2-S). Appelé aussi par qualite_jeu, pour tous ses
    appelants, rapports France et solaire compris (revue d'Astra de 674ad03, P2-AB)."""
    if fiche.get("ean") not in (None, "") and not isinstance(fiche["ean"], str):
        raise ValueError(f"Fiche : ean doit être écrit en texte, entre guillemets, tel qu'il figure sur l'ATO ; reçu le "
                         f"nombre {str(fiche['ean'])[:40]}, dont les chiffres ont pu être perdus. Reprendre le texte original.")


def fiche_controlee(fiche: dict[str, Any]) -> None:
    """Les nombres de la fiche sont contrôlés à l'entrée, avec un message qui nomme le champ, au lieu d'une erreur
    de type plus loin (même principe que la garantie de batterie, revue de 04 h 12)."""
    if not isinstance(fiche, dict):
        raise ValueError("Fiche : objet attendu.")
    # Relecture du 27/09, module manquant n°1 : la fiche imbriquée du diagnostic passait ici sans erreur et le GTV
    # disparaissait en silence (le scan ne lit que le premier niveau).
    if "valeurs" in fiche or any(isinstance(v, dict) and ("valeur" in v or "source_document" in v)
                                 for k, v in fiche.items() if k not in ("hypotheses", "traductions", "croissance_prevue",
                                                                        "batterie_garantie", "selection_annee")):
        raise ValueError("Fiche : format imbriqué du diagnostic ({valeur, source_document}) ; le scan lit une fiche plate. "
                         "Passer par application/dossier_client.py, qui la convertit sans perdre le GTV.")
    for nom in ("gtv_kw", "plafond_cible_kw", "capacite_aansluiting_kva", "prix_scan_eur", "cout_etude_eur"):
        if fiche.get(nom) is not None:
            _nombre_fiche(fiche[nom], nom)
    for nom in ("deelnameplicht_annoncee", "contrat_groupe"):
        if fiche.get(nom) is not None and not isinstance(fiche[nom], bool):
            raise ValueError(f"Fiche : {nom} doit valoir true ou false, reçu {str(fiche[nom])[:40]!r}.")
    # Aide reçue sur la batterie, retranchée de l'assiette de l'EIA : 0 est une réponse valable (aucune aide).
    aide = fiche.get("aide_batterie_eur")
    if aide is not None and (not nombre_fini(aide) or aide < 0):
        raise ValueError(f"Fiche : aide_batterie_eur doit être un nombre fini positif ou nul, reçu {str(aide)[:40]!r}.")
    if fiche.get("heures_activite_an") is not None:
        _nombre_fiche(fiche["heures_activite_an"], "heures_activite_an", 8784)
    if fiche.get("annee_profil") is not None and (type(fiche["annee_profil"]) is not int or not 1900 <= fiche["annee_profil"] <= 2100):
        raise ValueError(f"Fiche : annee_profil doit être une année entière (ex. 2025), reçu {str(fiche['annee_profil'])[:20]!r}.")
    horaires = fiche.get("horaires_semaine")
    if horaires is not None and not isinstance(horaires, str):
        heure = lambda h: h in (None, "") or (isinstance(h, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d|24:00", h))  # noqa: E731
        if not (isinstance(horaires, list) and all(isinstance(h, dict) and type(h.get("jour")) is int and 0 <= h["jour"] <= 6
                                                   and heure(h.get("debut")) and heure(h.get("fin")) for h in horaires)):
            raise ValueError("Fiche : horaires_semaine doit être un texte, ou une liste de {jour de 0 (lundi) à 6, debut « HH:MM », "
                             "fin « HH:MM »}.")
    controle_ean(fiche)
    confirmation = fiche.get("confirmation_grandeur")
    if confirmation is not None and not (isinstance(confirmation, str) and re.fullmatch(r"[0-9a-f]{64}", confirmation)):
        raise ValueError("Fiche : confirmation_grandeur doit reprendre l'identité de la série donnée par le refus du scan "
                         f"(64 caractères hexadécimaux), reçu {str(confirmation)[:40]!r}.")
    recoupe = fiche.get("unite_recoupee")
    if recoupe is not None and (not isinstance(recoupe, str) or not recoupe.strip()):
        raise ValueError("Fiche : unite_recoupee doit nommer la pièce qui recoupe l'unité (ex. « facture de janvier 2025 »).")
    if fiche.get("unite_recoupee_controle") not in (None, "coh_unite"):
        raise ValueError("Fiche : unite_recoupee_controle est réservé au contrôle interne coh_unite du dossier client.")
    tirages = fiche.get("tirages_confiance", TIRAGES_CONFIANCE)
    if type(tirages) is not int or not 0 <= tirages <= 1000:
        raise ValueError(f"Fiche : tirages_confiance doit être un entier de 0 à 1000, reçu {tirages!r}.")
    prevue = fiche.get("croissance_prevue")
    if prevue is not None:
        if not isinstance(prevue, dict):
            raise ValueError("Fiche : croissance_prevue doit être un objet {kw, debut, fin, jours}.")
        _nombre_fiche(prevue.get("kw"), "croissance_prevue.kw")
        for champ in ("debut", "fin"):
            h = prevue.get(champ)
            if h is not None and not (isinstance(h, str) and (re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h) or (champ == "fin" and h == "24:00"))):
                raise ValueError(f"Fiche : croissance_prevue.{champ} doit être une heure « HH:MM » de 00:00 à 23:59"
                                 f"{' (ou 24:00)' if champ == 'fin' else ''}, reçu {h!r}.")
    for cle, valeur in (fiche.get("hypotheses") or {}).items():
        if isinstance(valeur, dict) and "valeur" not in valeur:
            raise ValueError(f"Fiche : hypothèse {cle} donnée comme objet sans « valeur ».")
        v = valeur["valeur"] if isinstance(valeur, dict) else valeur
        if cle == "prix_batterie_eur_kwh" and v is None:
            continue  # prix inconnu : investissement et retour « à chiffrer », usage prévu
        if cle == "prix_batterie_eur_kwh" and isinstance(v, list):
            if len(v) != 2:
                raise ValueError("Fiche : hypothèse prix_batterie_eur_kwh, fourchette [bas, haut] attendue.")
            for x in v:
                _nombre_fiche(x, "hypothèse prix_batterie_eur_kwh")
            if v[0] > v[1]:
                raise ValueError("Fiche : hypothèse prix_batterie_eur_kwh, bas plus grand que haut.")
        elif cle in HYPOTHESES_DEFAUT:
            _nombre_fiche(v, f"hypothèse {cle}", 1.0 if cle in ("rendement_aller_retour", "profondeur_decharge") else math.inf)


# Version du contrôle de vraisemblance : une confirmation donnée à une version antérieure ne vaut pas pour celle-ci.
VERSION_VRAISEMBLANCE = "2026-09-30"


def identite_serie(kw: list[float], fins: list[datetime]) -> str:
    """Identité d'une série lue (valeurs, instants tels que lus) et de la version du contrôle : ce que confirme
    confirmation_grandeur (revue d'Astra de 143a896, P1-E ; même principe que l'heure répétée, CR07). Une autre série,
    un autre instant ou une autre conversion demandent une nouvelle confirmation."""
    empreinte = hashlib.sha256(f"vraisemblance {VERSION_VRAISEMBLANCE}\n".encode("utf-8"))
    for valeur, fin in zip(kw, fins):
        empreinte.update(f"{fin.isoformat()},{valeur!r}\n".encode("utf-8"))
    return empreinte.hexdigest()


def constats_vraisemblance(kw: list[float], fins: list[datetime], fiche: dict[str, Any]) -> list[dict[str, Any]]:
    """Vraisemblance de la grandeur lue (OF1, AF01, FB4 ; critères de phase 2 du 30/09). Jamais de rééchelonnement :
    une série qui ne fait que croître ressemble à un index cumulé (alerte) ; l'unité est dite recoupée avec la pièce
    nommée par la fiche, ou non recoupée. Ni une croissance ni un facteur 4 ne prouvent seuls une erreur d'unité."""
    constats = []
    if len(kw) >= 96 and kw[-1] > kw[0] and all(b >= a for a, b in zip(kw, kw[1:])):
        identite = identite_serie(kw, fins)
        constats.append({"code": "GRANDEUR_INDEX_POSSIBLE", "gravite": "alerte", "lignes": [],
                         "parametres": {"premier": kw[0], "dernier": kw[-1], "quarts": len(kw), "identite": identite,
                                        "confirmation": identite if fiche.get("confirmation_grandeur") == identite else None}})
    # codes_internes : paramètres qui portent un code de Contingency, traduit au rendu ; tout autre paramètre est une
    # référence littérale, même si elle ressemble à un code (revue d'Astra de fb1b673, P2-M).
    if fiche.get("unite_recoupee_controle"):
        constats.append({"code": "UNITE_RECOUPEE", "gravite": "info", "lignes": [], "codes_internes": ["source"],
                         "parametres": {"unite": "kW", "source": fiche["unite_recoupee_controle"]}})
    elif fiche.get("unite_recoupee"):
        constats.append({"code": "UNITE_RECOUPEE", "gravite": "info", "lignes": [],
                         "parametres": {"unite": "kW", "source": fiche["unite_recoupee"]}})
    else:
        constats.append({"code": "UNITE_NON_RECOUPEE", "gravite": "info", "lignes": [], "codes_internes": ["source"],
                         "parametres": {"unite": "kW", "source": "declaration_source"}})
    return constats


def constats_qualite(kw: list[float], fins: list[datetime], qualites: list[str] | None,
                     zone: ZoneInfo = AMSTERDAM, pas_minutes: int = 15) -> list[dict[str, Any]]:
    """Qualité par quart (ON1, ON3) : valeurs non mesurées comptées ; une pointe que seules des valeurs estimées,
    calculées ou inconnues atteignent est signalée, même si toutes les autres sont mesurées (point 3 d'Astra)."""
    constats = []
    if qualites is None:
        # Décision d'Astra du 30/09 (question de Fable) : sans statut, chaque valeur est d'origine inconnue. Mêmes
        # règles qu'une liste « inconnue », pour que l'absence d'audit ne rende jamais la conclusion plus affirmative ;
        # la raison reste tracée.
        constats.append({"code": "QUALITE_INCONNUE", "gravite": "info", "lignes": [], "codes_internes": ["raison"],
                         "parametres": {"raison": "aucun_statut_source"}})
        qualites = ["inconnue"] * len(kw)
    non_mesures = {q: qualites.count(q) for q in ("estime", "calcule", "inconnue") if q in qualites}
    if non_mesures:
        constats.append({"code": "QUALITE_VALEURS_NON_MESUREES", "gravite": "alerte", "lignes": [],
                         "parametres": {**non_mesures, "quarts": len(qualites)}})
    pointe = max(kw)
    a_la_pointe = [i for i, x in enumerate(kw) if x == pointe]
    if all(qualites[i] != "mesure" for i in a_la_pointe):
        i = a_la_pointe[0]
        # Hors quart d'heure, le constat nomme l'intervalle natif (catalogue d'Astra, 9ac563f).
        natif = {} if pas_minutes == 15 else {"pas_minutes": pas_minutes}
        constats.append({"code": "QUALITE_POINTE_INTERVALLE_NON_MESUREE" if natif else "QUALITE_POINTE_NON_MESUREE",
                         "gravite": "alerte", "lignes": [],
                         # En heure locale de la page, avec son décalage (fin de l'intervalle).
                         "parametres": {"instant": (fins[i].astimezone(zone) if fins[i].tzinfo else fins[i]).isoformat(),
                                        "pointe_kw": pointe, "qualite": qualites[i], **natif}})
    return constats


def qualite_jeu(kw: list[float], fins: list[datetime], fiche: dict[str, Any], qualites: list[str] | None = None,
                provenance: dict[str, Any] | None = None, details_qualite: list[dict[str, Any]] | None = None,
                avertissements: list[str] | None = None, pas_minutes: int = 15,
                zone: str = "Europe/Amsterdam") -> dict[str, Any]:
    """Ce qu'affiche la page « Qualité des données », sans le scan : le diagnostic l'ouvre aussi, même quand le scan
    est refusé (FB1). Seule source de ces constats et de la réserve sur la pointe ; le scanner s'appuie dessus.
    ``pas_minutes`` et ``zone`` : pas natif et fuseau du profil (France : 5 à 60 minutes, Europe/Paris), jamais recadrés
    pour la page ; jours particuliers comptés sur les débuts physiques, calculés en UTC puis convertis."""
    controle_ean(fiche)
    fuseau, pas = ZoneInfo(zone), timedelta(minutes=pas_minutes)
    from messages_fiabilite import CODES_POINTE
    constats = constats_vraisemblance(kw, fins, fiche) + constats_qualite(kw, fins, qualites, fuseau, pas_minutes)
    locales = [_heure_locale(f, fuseau) for f in fins]
    pics = (provenance or {}).get("kwmax_facture_par_mois")
    from horodatages import quarts_du_jour
    jours = []
    for jour, n in sorted(Counter(_debut_local(f, pas, fuseau).date() for f in fins).items()):
        attendus = quarts_du_jour(jour, fuseau, pas_minutes)
        if n != attendus:
            jours.append({"jour": jour.isoformat(), "intervalles": n, "motif": "partiel"})
        elif attendus != 1440 // pas_minutes:
            jours.append({"jour": jour.isoformat(), "intervalles": n, "motif": "ete" if attendus < 1440 // pas_minutes else "hiver"})
    # Pas de série d'horodatages dans le jeu : la page n'en a plus besoin et un export JSON allégé la recopiait.
    nature = "lu" if any(c["code"] == "QUALITE_VALEURS_NON_MESUREES" for c in constats) else "mesure"
    return {"version": VERSION, "statistiques": statistiques(kw, fins, pas_minutes, fuseau, nature),
            "entreprise": {"ean": _declare_ou(fiche, "ean")},
            "qualite_donnees": {"constats": constats, "provenance": provenance, "detail": detail_qualite(fins, details_qualite),
                                "avertissements_lecteur": list(avertissements or []),
                                "regles_vraisemblance": VERSION_VRAISEMBLANCE,
                                "pas_minutes": pas_minutes, "zone": zone, "jours_particuliers": jours,
                                **({"recoupement_18160": recoupement_18160(kw, locales, pics,
                                                                           provenance.get("kwmax_qualites_par_mois") or {})}
                                   if pics else {})},
            # Réserve sur la pointe et tout ce qui en dépend (marge sous le GTV, dimensionnement, recommandations) :
            # chiffres gardés à titre indicatif, jamais présentés comme confirmés ailleurs (décision d'Astra du 30/09).
            "reserve_pointe": next((c["parametres"] for c in constats if c["code"] in CODES_POINTE), None)}


def recoupement_18160(kw: list[float], locales: list[datetime], pics: dict[str, float],
                      qualites_pics: dict[str, str]) -> list[dict[str, Any]]:
    """kWmax de facturation Kenter (canal 18160, un par mois) contre la pointe des quarts du même mois (canal 16180,
    kWh × 4), en heure d'Amsterdam. Un mois que le profil ne couvre pas entièrement n'est jamais comparé : sa pointe
    partielle ne dit rien. Seuil : celui de COH-UNITE, seuil interne de rapprochement (revue d'Astra de 26ba18b)."""
    import coherence_mesures
    debut_serie, fin_serie = locales[0] - QUART, locales[-1]
    par_mois: dict[str, list[float]] = defaultdict(list)
    for x, fin in zip(kw, locales):
        par_mois[(fin - QUART).strftime("%Y-%m")].append(x)
    lignes = []
    for mois, facture in sorted(pics.items()):
        annee, numero = map(int, mois.split("-"))
        suivant = datetime(annee + numero // 12, numero % 12 + 1, 1)
        ligne = {"mois": mois, "facture_kw": facture, "qualite_facture": qualites_pics.get(mois)}
        if not (debut_serie <= datetime(annee, numero, 1) and fin_serie >= suivant):
            lignes.append({**ligne, "verdict": "mois_incomplet"})
            continue
        observe = max(par_mois[mois])
        lignes.append({**ligne, "profil_kw": observe, "ecart_kw": observe - facture,
                       "verdict": "concordant" if coherence_mesures._dans_arrondi(observe, facture) else "alerte"})
    return lignes


def detail_qualite(fins: list[datetime], details: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Détail par quart sans perte ni gonflement du résultat (revue d'Astra de 2c6a7d9, P2-G) : chaque combinaison
    fournie par la source (origine, statut, qualité) est comptée, et chaque quart qui diffère de la plus courante est
    listé avec son objet source et son instant. Rien n'est ajouté que la source n'ait fourni."""
    if details is None:
        return None
    cles = [json.dumps({k: v for k, v in d.items() if k not in ("fin_intervalle", "ligne_source")}, sort_keys=True,
                       ensure_ascii=False) for d in details]
    compte = Counter(cles)
    courante = compte.most_common(1)[0][0]
    detail = {"combinaisons": dict(compte), "combinaison_courante": json.loads(courante),
              "quarts_particuliers": [{**details[i], "fin": fins[i].isoformat()} for i, c in enumerate(cles) if c != courante]}
    lignes = [d.get("ligne_source") for d in details]
    if all(isinstance(n, int) for n in lignes):
        # Revue d'Astra de d5ec7f4 (P2-G) : la ligne source de chaque quart, combinaison courante comprise, en suites
        # [première, nombre, pas] ; un export filtré (lignes 2, 4, 6…) reste retrouvable.
        suites: list[list[int]] = []
        for n in lignes:
            if suites and suites[-1][1] == 1 and n > suites[-1][0]:
                suites[-1] = [suites[-1][0], 2, n - suites[-1][0]]
            elif suites and suites[-1][1] > 1 and n == suites[-1][0] + suites[-1][1] * suites[-1][2]:
                suites[-1][1] += 1
            else:
                suites.append([n, 1, 1])
        detail["lignes_source"] = suites
    return detail


def scanner(kw: list[float], fins: list[datetime], fiche: dict[str, Any], qualites: list[str] | None = None,
            provenance: dict[str, Any] | None = None, details_qualite: list[dict[str, Any]] | None = None,
            avertissements: list[str] | None = None) -> dict[str, Any]:
    fiche_controlee(fiche)
    if qualites is not None and (len(qualites) != len(kw) or not set(qualites) <= {"mesure", "estime", "calcule", "inconnue"}):
        raise ValueError("Scan de flexibilité : qualités attendues pour chaque quart (mesure, estime, calcule, inconnue).")
    if details_qualite is not None and len(details_qualite) != len(kw):
        raise ValueError("Scan de flexibilité : un détail de qualité attendu pour chaque quart.")
    # Audit Opus n°5 : le scan traite le GTV comme ferme toute l'année. Un droit par blocs horaires, lié à la durée
    # ou non ferme (REG-003 à REG-005) rendrait fausses la marge et la croissance annoncées : refus qui le nomme.
    nature = str(fiche.get("type_transportrecht") or "").strip().lower()
    if nature != "vast" and (nature or any(fiche.get(c) not in (None, "") for c in ("blocs_transport", "gtv_hors_bloc_kw"))):
        raise ValueError(f"Scan de flexibilité : droit de transport « {nature or 'non précisé, avec blocs horaires'} » non pris "
                         "en charge, le scan suppose un GTV ferme toute l'année (REG-003 à REG-005) ; voir le diagnostic, "
                         "CTRL-TRANSPORTRECHT.")
    if len(kw) != len(fins):
        raise ValueError(f"Scan de flexibilité : {len(kw)} valeurs pour {len(fins)} horodatages.")
    if len(kw) < 96 * 7 - 4:  # 668 quarts pour une semaine civile qui passe à l'heure d'été
        raise ValueError("Scan de flexibilité : au moins une semaine de quarts d'heure horodatés.")
    if any(x < 0 for x in kw):
        raise ValueError("Scan de flexibilité : valeurs négatives (injection) non prises en charge.")
    jeu = qualite_jeu(kw, fins, fiche, qualites, provenance, details_qualite, avertissements)
    qualite = jeu["qualite_donnees"]["constats"]
    index = next((c for c in qualite if c["code"] == "GRANDEUR_INDEX_POSSIBLE"), None)
    if index and index["parametres"]["confirmation"] is None:
        from horodatages import ErreurDonnees
        raise ErreurDonnees(f"Scan de flexibilité : la série ne fait que croître sur {len(kw)} quarts ({kw[0]:g} → {kw[-1]:g}). "
                            "Elle ressemble à un index cumulé (relevé de compteur), pas à une puissance moyenne par quart. "
                            "Vérifier la colonne choisie ; si c'est bien une puissance moyenne en kW, le confirmer dans la "
                            f"fiche : confirmation_grandeur = {index['parametres']['identite']} (identité de cette série ; "
                            + ("la confirmation fournie ne correspond pas à cette série ; " if fiche.get("confirmation_grandeur") else "")
                            + "une autre série en demande une nouvelle). Rien n'a été recalculé.", qualite)
    # Profils et moments se lisent en heure légale du site, comme un relevé de compteur : on convertit en heure
    # d'Amsterdam, puis on retire le fuseau. Sans conversion, un fichier en UTC décalait toutes les heures d'une
    # heure ou deux (relecture de 05 h) ; sans retrait, un export Kenter plantait la comparaison avec des dates
    # sans fuseau (27/09 vers 1 h 50).
    fins = [f.astimezone(AMSTERDAM).replace(tzinfo=None) if f.tzinfo else f for f in fins]
    hypotheses = {k: dict(v) for k, v in HYPOTHESES_DEFAUT.items()}
    for cle, valeur in (fiche.get("hypotheses") or {}).items():
        if cle not in hypotheses:
            raise ValueError(f"Hypothèse inconnue : {cle}")
        hypotheses[cle]["valeur"] = valeur["valeur"] if isinstance(valeur, dict) else valeur
        if isinstance(valeur, dict) and valeur.get("source"):
            hypotheses[cle]["source"] = valeur["source"]
        else:  # valeur changée sans source : ne pas garder la justification de la valeur par défaut (relecture, 14)
            hypotheses[cle]["source_cle"] = "hyp_fiche_sans_source"
    hyp = {k: v["valeur"] for k, v in hypotheses.items()}
    pointe = max(kw)
    plafond_fiche = fiche.get("plafond_cible_kw")
    # Scénario de croissance : les mesures portent sur le profil mesuré plus la charge prévue, avec pour limite
    # le transport contracté (ou, s'il n'est pas connu, la pointe actuelle : ne pas la dépasser évite toute
    # nouvelle demande). Les profils de l'article 4 restent ceux du profil mesuré, comme l'exige Flex-e.
    scenario, kw_mesures = None, kw
    if fiche.get("croissance_prevue"):
        prevue = fiche["croissance_prevue"]
        ajout = profil_croissance(fins, prevue)
        kw_scen = [a + b for a, b in zip(kw, ajout)]
        limite = float(fiche.get("gtv_kw") or pointe)
        # Constat n°11 : une cible de la fiche plus basse que cette limite est gardée, pas effacée en silence.
        cible = plafond_fiche is not None and float(plafond_fiche) < limite
        limite = float(plafond_fiche) if cible else limite
        scenario = {"kw": float(prevue["kw"]), "debut": prevue.get("debut", "00:00"), "fin": prevue.get("fin", "24:00"),
                    "jours": prevue.get("jours", "tous"), "description": prevue.get("description"),
                    "limite_kw": (grandeur(limite, "kW", "hypothese", "src_plafond_fiche") if cible else
                                  grandeur(limite, "kW", "declare" if fiche.get("gtv_kw") else "hypothese",
                                           "src_limite_gtv" if fiche.get("gtv_kw") else "src_limite_pointe")),
                    "pointe_scenario_kw": max(kw_scen), "tient_sans_mesure": max(kw_scen) <= limite,
                    "heures_au_dessus": heures_au_dessus(kw_scen, limite),
                    "energie_au_dessus_kwh": round(sum(max(0.0, x - limite) for x in kw_scen) * PAS_H, 1),
                    "energie_ajoutee_mwh": round(sum(ajout) * PAS_H / 1000, 1)}
        if not scenario["tient_sans_mesure"]:
            kw_mesures, plafond_fiche = kw_scen, limite
    plafond = float(plafond_fiche or plafond_heures(kw_mesures, hyp["heures_ecretees"]))
    palier = False
    if not plafond_fiche and plafond >= max(kw_mesures):
        # Pointe plate : la pointe dure plus que les N heures visées. On prend le premier palier sous la pointe
        # (5 sites VEA sur 5 358 étaient exclus pour cette raison avant le 27/09).
        niveaux = sorted(set(kw_mesures), reverse=True)
        if len(niveaux) > 1:
            plafond, palier = float(niveaux[1]), True
    if not 0 < plafond < max(kw_mesures):
        raise ValueError("Plafond visé hors de l'intervalle ]0, pointe[.")
    gestionnaire, nature_gest = gestionnaire_tarifs(fiche)
    categorie, nature_cat = categorie_tarifaire(fiche, pointe, gestionnaire)
    tarif = TARIFS_2026[gestionnaire][categorie]
    if fiche.get("contrat_groupe"):
        # Audits O6 et O13 : un contrat de transport de groupe n'a pas de grille publiée. Ni la catégorie tirée de la
        # somme des GTV, ni les tarifs d'un raccordement unique ne s'appliquent : ce qui en dépend reste à chiffrer.
        categorie, nature_cat, tarif = "GROUPE", "hypothese", {"plage": "", "kw_contrat_an": None, "kwmax_mois": None}
    batterie = option_batterie(kw_mesures, fins, plafond, hyp, tarif["kwmax_mois"], gestionnaire,
                               garantie_controlee(fiche.get("batterie_garantie")))
    decalage = option_decalage(kw_mesures, fins, plafond, hyp, tarif["kwmax_mois"], gestionnaire)
    ecretage = option_ecretage(kw_mesures, fins, plafond, hyp, tarif["kwmax_mois"], gestionnaire)
    contrat = option_contrat(kw_mesures, fins, fiche, plafond, tarif["kw_contrat_an"], gestionnaire,
                             plafond_tenu=bool(batterie.get("faisable") or decalage.get("faisable")))
    offre = option_offre_gestionnaire(fiche, batterie, decalage)
    if fiche.get("contrat_groupe"):
        for option in (batterie, decalage, ecretage):
            if isinstance(option.get("economie"), dict) and "eur_an" in option["economie"]:
                option["economie"]["eur_an"] = grandeur(None, option["economie"]["eur_an"]["unite"], "a_chiffrer", "src_tarif_groupe")
        contrat["remise_eur_an"] = grandeur(None, "€/an", "a_chiffrer", "src_tarif_groupe")
    for option in (batterie, decalage, ecretage):
        if "investissement_eur" in option:
            option["retour_ans"] = retour(option["investissement_eur"], option["economie"])
    if batterie.get("arbitrage_eur_an", {}).get("valeur"):
        cumul = {"eur_an": {"valeur": (batterie["economie"]["eur_an"].get("valeur") or 0) + batterie["arbitrage_eur_an"]["valeur"],
                            "unite": batterie["economie"]["eur_an"].get("unite", "€/an")}}
        batterie["retour_arbitrage_ans"] = retour(batterie["investissement_eur"], cumul)
        batterie["retour_arbitrage_ans"]["source"] = "src_retour_arbitrage"
    options = {o["id"]: o for o in (batterie, decalage, ecretage, contrat, offre)}
    decisifs = quarts_decisifs(kw_mesures, fins, plafond, hyp) if batterie.get("capacite_nominale_kwh") else None
    niveau_confiance = confiance(kw_mesures, fins, plafond, hyp, fiche.get("tirages_confiance", TIRAGES_CONFIANCE))
    ep = episodes(kw_mesures, plafond)
    # Revue d'Astra de 2adf522 (P1-AA) : sans qualité documentée comme mesure, les statistiques sont « lues », pas mesurées.
    stats = statistiques(kw, fins, nature=jeu["statistiques"]["pointe_kw"]["nature"])
    stats["selection_annee"] = fiche.get("selection_annee")
    prof = profils(kw, fins)
    resultat = {
        "version": VERSION,
        "site": {k: fiche.get(k) for k in ("nom", "secteur", "adresse", "gestionnaire", "source_profil", "licence_profil",
                                           "exemple", "traductions")},
        "marge_gtv": marge_sous_gtv(fiche.get("gtv_kw"), pointe, bool(fiche.get("contrat_groupe"))),
        "raccordement": {"gtv_kw": fiche.get("gtv_kw"), "capacite_aansluiting_kva": fiche.get("capacite_aansluiting_kva"),
                         "gestionnaire_tarifs": gestionnaire, "gestionnaire_nature": nature_gest,
                         "categorie": categorie, "categorie_nature": nature_cat, "categorie_plage": tarif["plage"],
                         "tarif_kw_contrat_an": tarif["kw_contrat_an"], "tarif_kwmax_mois": tarif["kwmax_mois"]},
        "congestion": {k: fiche.get(k) for k in ("statut_zone_afname", "statut_zone_teruglevering", "date_carte",
                                                 "annee_liberation_annoncee", "note_congestion", "congestierapport",
                                                 "besoin_flexibilite_zone")},
        "preference": _declare_ou(fiche, "preference_entreprise", "", "src_preference"),
        "entreprise": entreprise(fiche, kw, stats, prof),
        "processus": {"description": _declare_ou(fiche, "processus", "", "src_visite"),
                      "production_propre": _declare_ou(fiche, "production_propre", "", "src_visite")},
        "statistiques": stats,
        "profils": prof,
        "pics_creux": analyse_pics_creux(kw, fins, stats, prof),
        "quarts_decisifs": decisifs,
        "confiance": niveau_confiance,
        "horodatages": [f.isoformat() for f in fins],
        "profil_kw": kw,
        "profil_mesures_kw": kw_mesures,
        "scenario_croissance": scenario,
        "plafond_kw": (scenario["limite_kw"] if scenario and not scenario["tient_sans_mesure"]
                       else grandeur(plafond, "kW", "hypothese", "src_plafond_fiche") if plafond_fiche
                       else grandeur(plafond, "kW", "hypothese", "src_plafond_palier", heures=hyp["heures_ecretees"]) if palier
                       else grandeur(plafond, "kW", "hypothese", "src_plafond_heures", heures=hyp["heures_ecretees"])
                       if len(kw_mesures) >= QUARTS_ANNEE_MIN else
                       grandeur(plafond, "kW", "hypothese", "src_plafond_heures_periode", heures=hyp["heures_ecretees"],
                                h_periode=round(hyp["heures_ecretees"] * len(kw_mesures) * PAS_H / 8760, 2))),
        "episodes": {k: v for k, v in ep.items() if k != "liste"},
        "croissance": croissance(pointe, plafond, fiche.get("gtv_kw")),
        "sensibilite": sensibilite(kw_mesures, plafond, hyp, batterie),
        "hypotheses": hypotheses,
        "options": options,
        "recommandation": recommander(options),
    }
    # Économies par type de client (brief du 27/09/2026) : fourchettes tirées des options ci-dessus.
    from monetisation import calculer
    resultat["monetisation"] = calculer(resultat, fiche)
    # Constats de qualité des données, pour la page qualité en tête de rapport (FB1, lot 1 du 30/09).
    resultat["qualite_donnees"], resultat["reserve_pointe"] = jeu["qualite_donnees"], jeu["reserve_pointe"]
    return resultat


def allege(resultat: dict[str, Any]) -> dict[str, Any]:
    """Version JSON sans les séries longues (profil, horodatages, profils après mesure, monotone)."""
    sortie = {k: v for k, v in resultat.items() if k not in ("profil_kw", "profil_mesures_kw", "horodatages")}
    sortie["profils"] = {k: v for k, v in resultat["profils"].items() if k != "monotone"}
    sortie["options"] = {k: {c: w for c, w in o.items() if c != "profil_apres"} for k, o in resultat["options"].items()}
    return sortie


def main(argv: list[str]) -> int:
    pdf = "--pdf" in argv
    argv = [a for a in argv if a != "--pdf"]
    if len(argv) != 4:
        print(__doc__)
        return 2
    fiche = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    lu = lire_profil_qualifie(Path(argv[1]), fiche.get("annee_profil"))
    if lu["selection"]:
        fiche = {**fiche, "selection_annee": lu["selection"]}
    resultat = scanner(lu["kw"], lu["fins"], fiche, qualites=lu["qualites"], provenance=lu["provenance"],
                       details_qualite=lu["details_qualite"], avertissements=lu["avertissements"])
    sortie = Path(argv[3])
    sortie.mkdir(parents=True, exist_ok=True)
    import rapport_flex
    (sortie / "scan.json").write_text(json.dumps(allege(resultat), ensure_ascii=False, indent=1), encoding="utf-8")
    (sortie / "rapport-flex.html").write_text(rapport_flex.rendre(resultat, "fr"), encoding="utf-8")
    (sortie / "rapport-flex-nl.html").write_text(rapport_flex.rendre(resultat, "nl"), encoding="utf-8")
    if pdf:
        import rapport_pdf
        for nom in ("rapport-flex", "rapport-flex-nl"):
            rapport_pdf.html_vers_pdf(sortie / f"{nom}.html", sortie / f"{nom}.pdf")
    print(f"scan écrit dans {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
