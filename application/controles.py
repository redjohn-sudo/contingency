"""Registre des contrôles du catalogue, avec dépendances déclarées.

Choix de conception arrêté le 24/09/2026, contre la proposition d'un palier de
champs obligatoires au niveau du dossier.

Aucun champ n'est obligatoire au niveau du dossier. Chaque contrôle DÉCLARE les
données dont il a besoin et bloque tout seul si elles manquent. Deux raisons :

1. Le premier résultat utile du produit est la marge restante dans le contrat
   actuel (OPE-007, cas de De Zwaaikom à Veendam). Il ne demande que le profil et
   le transport contracté. Bloquer le dossier entier parce que la commune n'est
   pas renseignée tuerait ce résultat pour une donnée qui ne sert qu'aux
   contrôles d'implantation.
2. La liste des manques devient un chemin de progression au lieu d'un mur :
   ``plan_de_deblocage`` classe les données manquantes par le nombre de contrôles
   qu'elles ouvriraient.

Le principe « l'ambigu bloque, il n'est jamais avalé » est respecté, appliqué à
la bonne granularité : le contrôle, pas le dossier.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
import re
from zoneinfo import ZoneInfo
from typing import Any, Callable

import controles_contrat as base
import controles_batterie as batterie
import reference_gtv
from horodatages import lire_fins_quarts

REGISTRE: dict[str, dict[str, Any]] = {}


def enregistrer(identifiant: str, *, contraintes: list[str], besoins: dict[str, str],
                titre: str) -> Callable:
    """Déclare un contrôle, les entrées du catalogue qu'il applique et ses besoins.

    ``besoins`` associe le nom du champ attendu dans le dossier à la phrase qui
    dit à l'ingénieur où aller le chercher. Cette phrase se retrouve telle quelle
    dans le rapport : nommer la donnée ne suffit pas, il faut dire où elle est.
    """
    def decorateur(fonction: Callable) -> Callable:
        if identifiant in REGISTRE:
            raise ValueError(f"Contrôle déjà enregistré : {identifiant}")
        REGISTRE[identifiant] = {
            "id": identifiant,
            "titre": titre,
            "contraintes": contraintes,
            "besoins": besoins,
            "fonction": fonction,
        }
        return fonction
    return decorateur


def _manques(dossier: dict[str, Any], besoins: dict[str, str]) -> list[dict[str, str]]:
    return [{"champ": champ, "ou_le_trouver": ou}
            for champ, ou in besoins.items()
            if dossier.get(champ) in (None, "", [], ())]


def _entree_numerique_invalide(dossier: dict[str, Any], entree: dict[str, Any]) -> dict[str, Any] | None:
    """Chaque contrôle consommant ces grandeurs valide les mêmes données."""
    for champ, ou in entree["besoins"].items():
        valide = True
        if champ in ("gtv_kw", "gtv_declare_kw", "capacite_aansluiting_kva", "tarif_kw_mois_eur", "mois_factures",
                     "capacite_kwh", "puissance_kw", "hauteur_installation_m", "puissance_pointe_parc_pv_kw"):
            valide = base.nombre_non_negatif(dossier.get(champ))
        elif champ == "profil_kw":
            valide = base.profil_puissance_valide(dossier.get(champ))
        if not valide:
            return {"titre": entree["titre"], **base.entree_invalide(entree["id"], entree["contraintes"], champ, ou)}
    return None


def _bloque(entree: dict[str, Any], manques: list[dict[str, str]]) -> dict[str, Any]:
    champs = ", ".join(m["champ"] for m in manques)
    return {
        "id": entree["id"],
        "titre": entree["titre"],
        "contraintes": entree["contraintes"],
        "statut": "bloque",
        "constat": f"Non évaluable, donnée manquante : {champs}.",
        "manque": manques,
    }


def _jour_iso(valeur: Any, champ: str) -> date:
    if type(valeur) is date:
        return valeur
    try:
        jour = date.fromisoformat(valeur)
        if jour.isoformat() != valeur:
            raise ValueError
        return jour
    except (ValueError, TypeError):
        raise ValueError(f'{champ} : date valide au format AAAA-MM-JJ attendue.') from None


def _dates_invalides(dossier, entree, champs):
    for champ in champs:
        if dossier.get(champ) is not None:
            try:
                _jour_iso(dossier[champ], champ)
            except ValueError as erreur:
                return _bloque(entree, [{'champ': champ, 'ou_le_trouver': str(erreur)}])
    return None


# ---------------------------------------------------------------------------
# Contrôles de contrat, adossés aux fonctions pures déjà testées.
# ---------------------------------------------------------------------------

@enregistrer("CTRL-MARGE", contraintes=["RES-001", "DAT-001", "OPE-007"],
             titre="Marge restante dans le contrat actuel",
             besoins={"profil_kw": "profil de puissance au pas de 15 minutes, export du gestionnaire ou du meetbedrijf",
                      "gtv_kw": "transport contracté, page des puissances de l'aansluit- en transportovereenkomst"})
def marge(dossier: dict[str, Any]) -> dict[str, Any]:
    return base.marge_contractuelle(dossier["profil_kw"], dossier["gtv_kw"])


@enregistrer("CTRL-GTV-MAX", contraintes=["RES-023", "RES-002"],
             titre="Transport contractable au maximum",
             besoins={"capacite_aansluiting_kva": "capacité de raccordement en kVA, première page de l'ATO"})
def gtv_max(dossier: dict[str, Any]) -> dict[str, Any]:
    direction = dossier.get("direction", "soutirage")
    if not isinstance(direction, str) or direction not in base.COS_PHI_USUEL:
        return {"id": "CTRL-GTV-MAX", "contraintes": ["RES-023", "RES-002"], "statut": "bloque",
                "constat": "Direction invalide : préciser soutirage ou injection.",
                "valeurs": {"raison": "direction_invalide"},
                "manque": [{"champ": "direction", "ou_le_trouver": "ATO, sens du transport : soutirage ou injection"}]}
    return base.gtv_maximal(dossier["capacite_aansluiting_kva"],
                            direction)


@enregistrer("CTRL-GTV-DECLARE", contraintes=["RES-012", "RES-024"],
             titre="Capacité perdue entre le contrat et la dernière déclaration",
             besoins={"gtv_kw": "transport contracté écrit dans l'ATO",
                      "gtv_declare_kw": "dernier vermogen déclaré, à lire sur une facture de transport du gestionnaire"})
def gtv_declare(dossier: dict[str, Any]) -> dict[str, Any]:
    reference = reference_gtv.etablir(dossier)
    if reference and reference["statut"] == "bloque":
        return reference_gtv.bloque(REGISTRE["CTRL-GTV-DECLARE"], reference)
    resultat = base.ecart_gtv_declare(dossier["gtv_kw"], dossier["gtv_declare_kw"])
    if reference:
        resultat["reference_gtv"] = reference
    return resultat


# Légende officielle de la capaciteitskaart (Netbeheer Nederland), relevée le 25/09/2026 ; cinquième entrée
# « Kleur wordt later toegevoegd » relue sur la page le 27/09/2026 : zone pas encore évaluée, ni libre ni saturée.
STATUTS_ZONE = {
    "beschikbaar": "transportcapaciteit beschikbaar zonder wachtrij",
    "beperkt": "transportcapaciteit beperkt beschikbaar zonder wachtrij",
    "onderzoek": "gebied is in onderzoek met wachtrij",
    "tekort": "tekort aan transportcapaciteit met wachtrij",
    "a_evaluer": "kleur wordt later toegevoegd",
}
GLISSEMENT_LIBERATION_ANS = 4


@enregistrer("CTRL-ZONE", contraintes=["RES-005", "RES-006", "RES-021"],
             titre="État de la zone sur la carte publique, par direction",
             besoins={"statut_zone_afname": "capaciteitskaart.netbeheernederland.nl, couche Afname, à l'adresse du site",
                      "statut_zone_teruglevering": "capaciteitskaart.netbeheernederland.nl, couche Teruglevering",
                      "date_carte": "date de consultation de la capaciteitskaart"})
def zone(dossier: dict[str, Any]) -> dict[str, Any]:
    """RES-005 : l'état de la zone vaut à la date de l'étude. RES-006 : afname et teruglevering
    sont deux états distincts, aucun ne se déduit de l'autre. RES-021 : une année de fin de
    congestion annoncée se teste à N + 4, les dates glissent par blocs d'années."""
    afname = str(dossier["statut_zone_afname"]).strip().lower()
    retour = str(dossier["statut_zone_teruglevering"]).strip().lower()
    inconnus = [s for s in (afname, retour) if s not in STATUTS_ZONE]
    if inconnus:
        return {"id": "CTRL-ZONE", "titre": "État de la zone sur la carte publique, par direction",
                "contraintes": ["RES-005", "RES-006", "RES-021"], "statut": "bloque",
                "constat": f"Statut non reconnu : {', '.join(inconnus)}. Attendu : {', '.join(STATUTS_ZONE)}.",
                "manque": [{"champ": "statut_zone_afname", "ou_le_trouver": "légende de la capaciteitskaart"}]}
    file_afname = afname in ("onderzoek", "tekort")
    non_evaluee = "a_evaluer" in (afname, retour)
    annee = dossier.get("annee_liberation_annoncee")
    if annee not in (None, ""):
        if isinstance(annee, str) and re.fullmatch(r"[0-9]{4}", annee):
            annee = int(annee)
        valide = False
        if type(annee) in (int, float):
            try:
                valide = math.isfinite(annee) and 1 <= annee <= 9995 and annee == int(annee)
            except OverflowError:
                pass
        if not valide:
            return {
                "id": "CTRL-ZONE", "titre": "État de la zone sur la carte publique, par direction",
                "contraintes": ["RES-005", "RES-006", "RES-021"], "statut": "bloque",
                "constat": "Année de libération invalide : fournir une année entière entre 1 et 9995, afin de pouvoir aussi examiner quatre ans plus tard.",
                "valeurs": {"raison": "annee_liberation_invalide"},
                "manque": [{"champ": "annee_liberation_annoncee", "ou_le_trouver": "annonce du gestionnaire : année entière, sans booléen ni fraction ; valeur texte au format AAAA"}],
            }
        annee = int(annee)
    valeurs = {"statut_afname": afname, "statut_teruglevering": retour, "date_carte": str(dossier["date_carte"]),
               "file_afname": file_afname, "asymetrique": afname != retour}
    constat = (f"Carte du {dossier['date_carte']} : afname « {STATUTS_ZONE[afname]} », teruglevering "
               f"« {STATUTS_ZONE[retour]} ».")
    if afname != retour:
        constat += " Les deux directions diffèrent : chacune se traite séparément."
    if non_evaluee:
        valeurs["non_evaluee"] = True
        constat += (" Couleur pas encore attribuée : la zone n'est pas évaluée, rien ne permet de conclure à une "
                    "capacité disponible ; l'état se demande au gestionnaire.")
    if annee not in (None, ""):
        valeurs["annee_annoncee"] = int(annee)
        valeurs["annee_a_tester"] = int(annee) + GLISSEMENT_LIBERATION_ANS
        constat += (f" Fin de congestion annoncée en {int(annee)} : tout plan qui en dépend se teste "
                    f"aussi en {int(annee) + GLISSEMENT_LIBERATION_ANS}.")
    return {
        "id": "CTRL-ZONE", "titre": "État de la zone sur la carte publique, par direction",
        "contraintes": ["RES-005", "RES-006", "RES-021"],
        "statut": "alerte" if file_afname or non_evaluee else "constat",
        "constat": constat, "valeurs": valeurs,
        "consequence_contractuelle": (
            "Toute puissance supplémentaire en afname passe par la file d'attente : la marge du contrat "
            "actuel est la seule capacité disponible sans attente." if file_afname else None),
    }


TYPES_TRANSPORTRECHT = ("vast", "tijdsduurgebonden", "tijdsblok", "non_firm")
PART_HEURES_TDTR = 0.85


def _minutes(heure: str) -> int:
    if not re.fullmatch(r'\d{1,2}:\d{2}', heure.strip()):
        raise ValueError(heure)
    h, m = heure.strip().split(":")
    if not (0 <= int(h) <= 24 and 0 <= int(m) < 60) or (int(h) == 24 and int(m) != 0) or int(m) % 15:
        raise ValueError(heure)
    return int(h) * 60 + int(m)


def _dans_blocs(debut_quart: datetime, blocs: list[tuple[int, int]]) -> bool:
    minute = debut_quart.hour * 60 + debut_quart.minute
    return any((a <= minute < b) if a < b else (minute >= a or minute < b) for a, b in blocs)


@enregistrer("CTRL-TRANSPORTRECHT", contraintes=["REG-003", "REG-004", "REG-005"],
             titre="Nature du droit de transport",
             besoins={"type_transportrecht": "ATO, nature du droit de transport (vast, tijdsduurgebonden, "
                                             "tijdsblok, non_firm)"})
def transportrecht(dossier: dict[str, Any]) -> dict[str, Any]:
    """REG-003 : un droit non ferme n'est jamais disponible en continu. REG-004 : un droit lié à la
    durée garantit 85 % des heures de l'année, le reste peut être coupé. REG-005 : un droit par blocs
    horaires n'autorise rien hors des blocs, au-delà du transport prévu hors bloc."""
    base_id = {"id": "CTRL-TRANSPORTRECHT", "titre": "Nature du droit de transport",
               "contraintes": ["REG-003", "REG-004", "REG-005"]}
    nature = str(dossier["type_transportrecht"]).strip().lower()
    if nature not in TYPES_TRANSPORTRECHT:
        return {**base_id, "statut": "bloque",
                "constat": f"Nature « {nature} » non reconnue : attendu {', '.join(TYPES_TRANSPORTRECHT)}.",
                "manque": [{"champ": "type_transportrecht", "ou_le_trouver": "ATO, clause du droit de transport"}]}
    if nature == "vast":
        return {**base_id, "statut": "constat", "valeurs": {"nature": nature},
                "constat": "Droit de transport ferme : disponible toute l'année dans la limite du transport contracté."}
    if nature == "non_firm":
        return {**base_id, "statut": "alerte", "valeurs": {"nature": nature},
                "constat": ("Droit de transport non ferme : le contrat doit décrire les circonstances de "
                            "disponibilité, la méthode de constatation et l'annonce de la libération."),
                "consequence_contractuelle": "Aucune étude ne peut supposer une disponibilité continue."}
    if nature == "tijdsduurgebonden":
        heures = PART_HEURES_TDTR * 8760
        return {**base_id, "statut": "alerte",
                "valeurs": {"nature": nature, "heures_garanties": heures, "heures_coupables": 8760 - heures},
                "constat": (f"Droit lié à la durée : {heures:.0f} heures garanties sur 8 760, jusqu'à "
                            f"{8760 - heures:.0f} heures peuvent être coupées."),
                "consequence_contractuelle": ("Toute marge, production ou écrêtage se recalcule sur 85 % des "
                                              "heures, pas sur l'année entière.")}
    # tijdsblok
    manque = [{"champ": c, "ou_le_trouver": o} for c, o in (
        ("blocs_transport", "ATO, blocs horaires du droit de transport"),
        ("gtv_hors_bloc_kw", "ATO, transport autorisé hors bloc en kW ; déclarer zéro si aucun droit"),
        ("profil_kw", "profil de puissance au pas de 15 minutes"),
        ("profil_horodatages", "horodatages de l'export")) if dossier.get(c) in (None, "", [])]
    if manque:
        return {**base_id, "statut": "bloque", "manque": manque,
                "constat": "Droit par blocs horaires : blocs ou profil horodaté manquants, conformité non évaluable."}
    try:
        blocs = [(_minutes(a), _minutes(b)) for a, b in
                 (morceau.split("-") for morceau in str(dossier["blocs_transport"]).split(","))]
        if any(a == b or a == 1440 for a, b in blocs):
            raise ValueError('Bornes identiques ou début à 24:00.')
    except ValueError:
        return {**base_id, "statut": "bloque",
                "valeurs": {"nature": nature, "raison": "blocs_invalides"},
                "constat": f"Blocs horaires illisibles ou ambigus : « {dossier['blocs_transport']} ». Attendu « 22:00-06:00 », bornes distinctes au quart d'heure ; 24:00 seulement en fin de bloc.",
                "manque": [{"champ": "blocs_transport", "ou_le_trouver": "ATO, blocs horaires"}]}
    try:
        dates_brutes = dossier['profil_horodatages']
        puissances_brutes = dossier['profil_kw']
        if not isinstance(dates_brutes, (list, tuple)) or not isinstance(puissances_brutes, (list, tuple)):
            raise ValueError('Profil et horodatages doivent être des listes.')
        if not dates_brutes or len(dates_brutes) != len(puissances_brutes):
            raise ValueError('Chaque puissance doit avoir exactement un horodatage.')
        dates = lire_fins_quarts(dates_brutes)
        if any(isinstance(v, bool) for v in [dossier['gtv_hors_bloc_kw'], *puissances_brutes]):
            raise ValueError('Une puissance ne peut pas être un booléen.')
        hors_bloc_kw = float(dossier['gtv_hors_bloc_kw'])
        puissances = [float(v) for v in puissances_brutes]
        if any(not math.isfinite(v) or not 0 <= v <= 1e7 for v in [hors_bloc_kw, *puissances]):
            raise ValueError('Puissances attendues entre zéro et dix millions de kW, sans valeur non finie.')
    except (ValueError, TypeError, OverflowError) as erreur:
        return {**base_id, "statut": "bloque",
                "valeurs": {"nature": nature, "raison": "profil_ou_limite_invalide"},
                "constat": f"Profil ou transport hors bloc invalide : {erreur}",
                "manque": [{"champ": "profil_horodatages", "ou_le_trouver": "export afname complet avec fins de quarts et décalages UTC"},
                           {"champ": "gtv_hors_bloc_kw", "ou_le_trouver": "ATO, puissance autorisée hors des blocs"}]}
    zone = ZoneInfo('Europe/Amsterdam')
    depassements = []
    for fin, kw in zip(dates, puissances):
        # Soustraire en UTC avant de retrouver l'heure civile, surtout au retour d'hiver.
        try:
            debut_local = (fin.astimezone(timezone.utc) - timedelta(minutes=15)).astimezone(zone)
            fin_locale = fin.astimezone(zone)
        except OverflowError:
            return {**base_id, 'statut': 'bloque', 'valeurs': {'nature': nature, 'raison': 'profil_ou_limite_invalide'},
                    'constat': 'La fin ou le début du quart sort de la plage de dates prise en charge.',
                    'manque': [{'champ': 'profil_horodatages', 'ou_le_trouver': 'horodatages du relevé compteur'}]}
        if not _dans_blocs(debut_local, blocs) and kw > hors_bloc_kw:
            depassements.append({'debut_local': debut_local.isoformat(),
                                 'fin_locale': fin_locale.isoformat(), 'puissance_kw': kw})
    valeurs = {"nature": nature, "blocs": str(dossier["blocs_transport"]), "transport_hors_bloc_kw": hors_bloc_kw,
               "quarts_hors_bloc_au_dessus": len(depassements),
               "pointe_hors_bloc_kw": max((d['puissance_kw'] for d in depassements), default=0.0),
               "fuseau_plages": 'Europe/Amsterdam', "quarts_evalues": len(dates),
               "premiers_depassements": depassements[:5]}
    return {**base_id, "statut": "alerte" if depassements else "constat", "valeurs": valeurs,
            "constat": (f"Droit par blocs ({dossier['blocs_transport']}, heure Europe/Amsterdam) : {len(depassements)} quart(s) d'heure "
                        f"hors bloc au-dessus de {hors_bloc_kw:.0f} kW"
                        + (f", pointe hors bloc {valeurs['pointe_hors_bloc_kw']:.1f} kW." if depassements else ".")),
            "consequence_contractuelle": ("Hors des blocs, le site n'est pas conforme : ces consommations doivent "
                                          "être déplacées dans les blocs ou couvertes par un autre droit."
                                          if depassements else None)}


SEUIL_CONGESTIEMANAGEMENT_KW = 1000.0


@enregistrer("CTRL-CM-1MW", contraintes=["REG-009"],
             titre="Participation possible au congestiemanagement dès 1 MW",
             besoins={"gtv_declare_kw": "dernier vermogen déclaré, à lire sur une facture de transport du gestionnaire"})
def congestiemanagement_1mw(dossier: dict[str, Any]) -> dict[str, Any]:
    """REG-009 : à partir d'un transport contracté de 1 MW, le gestionnaire PEUT imposer la
    participation au congestiemanagement (Stedin, deelnameverplichting). Le seuil déclenche une
    vérification, jamais une réduction supposée : la direction et le contrat restent à lire."""
    gtv = float(dossier["gtv_declare_kw"])
    concerne = gtv >= SEUIL_CONGESTIEMANAGEMENT_KW
    return {
        "id": "CTRL-CM-1MW",
        "titre": "Participation possible au congestiemanagement dès 1 MW",
        "contraintes": ["REG-009"],
        "statut": "alerte" if concerne else "constat",
        "constat": (f"Transport contracté de {gtv:.0f} kW, "
                    + ("au-dessus du seuil de 1 MW : une obligation de participer au congestiemanagement "
                       "est possible et doit être vérifiée auprès du gestionnaire."
                       if concerne else "sous le seuil de 1 MW : pas d'obligation de participation à ce titre.")),
        "valeurs": {"gtv_kw": gtv, "seuil_kw": SEUIL_CONGESTIEMANAGEMENT_KW, "concerne": concerne},
        "consequence_contractuelle": (
            "Une sollicitation peut demander de consommer moins ou plus selon la direction de la congestion ; "
            "l'étude doit chiffrer la capacité à y répondre et le manque à gagner. Rien n'est réduit sans "
            "contrat ou instruction applicable." if concerne else None),
    }


@enregistrer("CTRL-DEPASSEMENT", contraintes=["RES-026", "REG-014"],
             titre="Dépassements du transport contracté",
             besoins={"profil_kw": "profil de puissance au pas de 15 minutes",
                      "gtv_kw": "transport contracté écrit dans l'ATO"})
def depassement(dossier: dict[str, Any]) -> dict[str, Any]:
    return base.depassements_par_bloc(dossier["profil_kw"], dossier["gtv_kw"])


# ---------------------------------------------------------------------------
# Contrat et calendrier.
# ---------------------------------------------------------------------------

@enregistrer("CTRL-CAPACITE-DORMANTE", contraintes=["ECO-005", "ECO-006"],
             titre="Coût de la capacité réservée et non utilisée",
             besoins={"profil_kw": "profil de puissance au pas de 15 minutes",
                      "gtv_kw": "transport contracté écrit dans l'ATO",
                      "tarif_kw_mois_eur": "tarif du kW contracté par mois, règlement tarifaire du gestionnaire de l'année en cours",
                      "mois_factures": "nombre de mois déjà facturés sur ce contrat"})
def capacite_dormante(dossier: dict[str, Any]) -> dict[str, Any]:
    """Le kW contracté se paie dès la signature, même s'il n'est jamais utilisé.

    ECO-005, College van Beroep voor het bedrijfsleven, Vogelweg HV Station
    contre Liander, 10/02/2026, ECLI:NL:CBB:2026:47.
    """
    if invalide := _entree_numerique_invalide(dossier, REGISTRE['CTRL-CAPACITE-DORMANTE']):
        return invalide
    pointe = max(dossier["profil_kw"])
    dormant = max(0.0, dossier["gtv_kw"] - pointe)
    cout = dormant * dossier["tarif_kw_mois_eur"] * dossier["mois_factures"]
    if not base.nombre_non_negatif(cout):
        return base.entree_invalide('CTRL-CAPACITE-DORMANTE', ['ECO-005', 'ECO-006'],
                                   'tarif_kw_mois_eur', 'factures : GTV, tarif et nombre de mois à vérifier', calcul=True)
    return {
        "id": "CTRL-CAPACITE-DORMANTE",
        "titre": "Coût de la capacité réservée et non utilisée",
        "contraintes": ["ECO-005", "ECO-006"],
        "statut": "alerte" if dormant > 0 else "constat",
        "constat": (
            f"{dormant:.1f} kW contractés jamais atteints sur la période mesurée, "
            f"valorisés à {cout:.0f} euros sur {dossier['mois_factures']} mois déclarés, "
            "à GTV et tarif inchangés. Montant indicatif de ce seul poste, pas une économie garantie."
        ),
        "valeurs": {"kw_dormants": dormant, "cout_eur": cout,
                    "tarif_kw_mois_eur": dossier['tarif_kw_mois_eur'], "mois_factures": dossier['mois_factures'],
                    "hypothese_gtv_et_tarif_constants": True},
        "consequence_contractuelle": (
            "Le tarif de transport se paie sur le kW contracté dès la signature, "
            "utilisé ou non. Une baisse peut réduire ce poste, sous réserve des conditions "
            "du contrat et des dates d'application ; elle réduit aussi le droit opposable. Une hausse ultérieure demande "
            "un nouvel accord, soumis à la capacité disponible (RES-012)."
        ),
    }


@enregistrer("CTRL-DELAI-OFFRE", contraintes=["OPE-004", "RES-011"],
             titre="Deux compteurs de délai, pas un seul",
             besoins={"date_demande": "date de dépôt de la demande de raccordement",
                      "date_offre": "date de l'offre du gestionnaire",
                      "date_signature": "date de signature de l'offre"})
def delai_offre(dossier: dict[str, Any]) -> dict[str, Any]:
    """Le délai officiel court depuis la SIGNATURE, pas depuis la demande.

    OPE-004, décision ACM Gasterij van Balveren contre Liander : dix semaines pour
    obtenir l'offre, quarante-cinq semaines après signature jugées raisonnables.
    Comptées depuis la demande, cela fait cinquante-sept semaines.
    """
    champs = ('date_demande', 'date_offre', 'date_signature')
    entree = REGISTRE['CTRL-DELAI-OFFRE']
    if invalide := _dates_invalides(dossier, entree, champs):
        return invalide
    demande, offre, signature = (_jour_iso(dossier[c], c) for c in champs)
    if not demande <= offre <= signature:
        return _bloque(entree, [{'champ': c, 'ou_le_trouver': 'Ordre requis : demande, offre, puis signature.'} for c in champs])
    avant = (offre - demande).days
    attente = (signature - offre).days
    return {
        "id": "CTRL-DELAI-OFFRE",
        "titre": "Deux compteurs de délai, pas un seul",
        "contraintes": ["OPE-004", "RES-011"],
        "statut": "constat",
        "constat": (
            f"{avant} jours entre la demande et l'offre, puis {attente} jours "
            f"avant signature. Le délai contractuel ne court qu'à partir de la signature."
        ),
        "valeurs": {"jours_demande_offre": avant, "jours_offre_signature": attente,
                    "jours_perdus_hors_compteur": avant},
        "consequence_contractuelle": (
            "Un planning qui part de la date de demande sous-estime le délai réel. "
            "Une offre non signée dans le délai imparti fait perdre la place en file."
        ),
    }


@enregistrer("CTRL-REGIME-DEPOT", contraintes=["TRA-008", "RES-022"],
             titre="Régime applicable selon la date de dépôt",
             besoins={"date_depot": "date de dépôt du dossier auprès du gestionnaire",
                      "gestionnaire": "nom du gestionnaire de réseau régional"})
def regime_depot(dossier: dict[str, Any]) -> dict[str, Any]:
    """La date de dépôt fige le régime applicable, elle n'est pas une formalité.

    TRA-008 : chez Enexis, les demandes déposées avant le 01/07/2026 gardent
    l'ancien régime pendant une période transitoire qui court jusqu'au 01/01/2027.
    """
    from datetime import date

    if invalide := _dates_invalides(dossier, REGISTRE['CTRL-REGIME-DEPOT'], ('date_depot',)):
        return invalide
    depot = _jour_iso(dossier['date_depot'], 'date_depot')
    gestionnaire = str(dossier["gestionnaire"]).strip().lower()
    if gestionnaire not in ('enexis', 'liander'):
        return _bloque(REGISTRE['CTRL-REGIME-DEPOT'], [{'champ': 'regime_depot_gestionnaire',
                       'ou_le_trouver': 'Aucune bascule de régime documentée ici pour ce gestionnaire ; vérifier sa règle et la catégorie du raccordement.'}])
    bascule = date(2026, 7, 1)
    ancien = depot < bascule
    transitoire = gestionnaire == "enexis" and ancien
    return {
        "id": "CTRL-REGIME-DEPOT",
        "titre": "Régime applicable selon la date de dépôt",
        "contraintes": ["TRA-008", "RES-022"],
        "statut": "constat",
        "constat": (
            f"Dépôt du {depot.isoformat()} chez {dossier['gestionnaire']} : "
            + ("avant le repère du 01/07/2026." if ancien else "à partir du repère du 01/07/2026.")
            + (" Enexis annonce une transition du 01/07/2026 au 01/01/2027."
               if gestionnaire == 'enexis' else " Liander distingue les nouvelles demandes en zone saturée.")
            + " Le traitement individuel dépend du type de demande et du raccordement ; il reste à confirmer."
        ),
        "valeurs": {"date_depot": depot.isoformat(), "regime_anterieur": ancien,
                    "transitoire_enexis": transitoire, 'gestionnaire': gestionnaire,
                    'regime_individuel_confirme': False},
        "consequence_contractuelle": (
            "Deux dossiers identiques déposés à un jour d'écart ne suivent pas les "
            "mêmes règles. La date de dépôt est une donnée d'entrée de l'étude."
        ),
    }


# ---------------------------------------------------------------------------
# Implantation : règles communales, toutes lues en source primaire par hermes.
# ---------------------------------------------------------------------------

def _cle_commune(nom: Any) -> str:
    """Normalise un nom de commune : casse, tirets et espaces multiples.

    Signale par hermes le 24/09 : « Hendrik-Ido-Ambacht » s'ecrit aussi
    « Hendrik Ido Ambacht ». Sans normalisation, on bloque en disant « aucune
    regle lue » sur une commune dont on a pourtant lu le texte, ce qui est un
    faux blocage, aussi grave qu'une fausse conclusion.
    """
    import unicodedata
    sans_accent = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode()
    brut = sans_accent.strip().lower().replace("-", " ")
    return " ".join(brut.split())


# Chimies de cellules contenant du lithium. Chercher le mot « lithium » dans la
# chimie déclarée est FAUX : « LFP », « Li-ion » ou « NMC » ne le contiennent pas,
# et LFP est la chimie dominante des batteries industrielles. Erreur trouvée le
# 24/09 en passant le cas type sur Dordrecht : une batterie LFP sortait « hors
# champ » d'une règle qui vise justement les accumulateurs « lithiumhoudende ».
_LITHIUM = ("lithium", "li-ion", "li ion", "liion", "lfp", "lifepo", "nmc", "nca",
            "lto", "lmo", "lco", "li-po", "lipo", "li-polymere", "li-polymer")
_SANS_LITHIUM = ("sodium", "na-ion", "na ion", "flow", "redox", "vanadium", "plomb",
                 "lead", "zinc", "nickel-fer", "nife", "fer-air", "iron-air", "hydrogene",
                 "supercondensateur")


def est_lithium(chimie: Any) -> bool | None:
    """Vrai, faux, ou None si la chimie déclarée n'est pas reconnue.

    None doit être traité comme indéterminé : on bloque et on demande la fiche
    technique, on ne devine pas.
    """
    texte = " ".join(str(chimie or "").strip().lower().split())
    if not texte:
        return None
    if any(motif in texte for motif in _SANS_LITHIUM):
        return False
    if any(motif in texte for motif in _LITHIUM):
        return True
    return None


REGLES_COMMUNALES = {
    "hollands kroon": {
        "hauteur_max_m": 3.5,
        "hauteur_max_m_pres_380kv": 7.0,
        "installations_max_par_bouwvlak": 1,
        # Relu par hermes sur le brut : la hauteur n'est PAS un plafond de droit.
        "hauteur_derogeable": True,
        "citation_derogation": "« tenzij gemotiveerd hiervan wordt afgeweken »",
        "note_380kv": ("les 7 m près d'un poste 380 kV sont une dérogation assortie d'une "
                       "limite de SURFACE, au plus la moitié du poste, pas un plafond de droit"),
        "condition_accessoire": ("l'installation doit rester « ondergeschikt aan de "
                                 "bedrijfsvoering », donc accessoire à l'activité du site "
                                 "(recoupe REG-018)"),
        "source": "Beleidslijn Batterijopslagsystemen, CVDR764372, en vigueur depuis le 14/07/2026",
    },
    "dordrecht": {
        "permis_des_mwh": 1.0,
        "bruit_db_jour": 45.0, "bruit_db_soir": 40.0, "bruit_db_nuit": 35.0,
        "bruit_creneaux": "L_Ar,LT ; jour 07-19, soir 19-23, nuit 23-07 (tableau 1.7)",
        "bruit_exception": "geluidsgezoneerd industrieterrein",
        "citation_seuil": "« een energieopslagsysteem met een capaciteit van 1 MWh of meer » (art. 1.5)",
        "chimie_visee": "lithiumhoudende",
        "piece_exigee": "rapport acoustique « inclusief het rekenbestand »",
        "source": "modèle Drechtsteden, CVDR739938, 30/05/2025",
    },
    "zwijndrecht": {
        "permis_des_mwh": 1.0,
        "bruit_db_jour": 45.0, "bruit_db_soir": 40.0, "bruit_db_nuit": 35.0,
        "bruit_creneaux": "L_Ar,LT ; jour 07-19, soir 19-23, nuit 23-07",
        "bruit_exception": "geluidsgezoneerd industrieterrein",
        "chimie_visee": "lithiumhoudende",
        "piece_exigee": "rapport acoustique « inclusief het rekenbestand »",
        "source": "modèle Drechtsteden, CVDR749139, 05/12/2025",
    },
    "hendrik ido ambacht": {
        "permis_des_mwh": 1.0,
        "bruit_db_jour": 45.0, "bruit_db_soir": 40.0, "bruit_db_nuit": 35.0,
        "bruit_creneaux": "L_Ar,LT ; jour 07-19, soir 19-23, nuit 23-07",
        "bruit_exception": "geluidsgezoneerd industrieterrein",
        "chimie_visee": "lithiumhoudende",
        "piece_exigee": "rapport acoustique « inclusief het rekenbestand »",
        "source": "modèle Drechtsteden, CVDR745351, 10/10/2025",
    },
    "tiel": {
        "implantations_admises": ("couplee_a_production", "adjacent_poste_150kv", "bedrijventerrein"),
        "demarrage_max_mois_apres_permis": 12,
        # Relu par hermes : 12 mois confirme pour le stockage, ligne 575 du brut ;
        # les 5 ans du meme document visent le solaire et l'eolien.
        "depart_du_delai": "permis onherroepelijk, pas la délivrance",
        "bedrijventerrein_inclut": "« direct naastgelegen » à une zone d'activité",
        "piece_exigee": "« Goedkeuring van Brandweer », seule des huit communes à l'exiger",
        "source": "CVDR736212, 05/03/2025",
    },
    "oosterhout": {
        "usages_admis": ("propre_activite", "batiment_unique_liste_b_bbl", "nutsbedrijf"),
        "usage_exige_sur_site": True,
        "citation_usage": ("« ten dienste van uitsluitend de eigen bedrijfsvoering van een "
                           "bedrijf en ... op de locatie van dat bedrijf » (exception a)"),
        "derogation_possible": ("dérogation du college possible si le projet est conforme à "
                                "l'Energievisie (lid 4)"),
        # Relu par hermes : le texte ne vise que les activites qui ne sont pas encore
        # en place a son entree en vigueur.
        "en_vigueur_le": "2026-06-20",
        "hors_champ_si_deja_en_service": True,
        "citation_champ": "« nog niet plaatsvinden op het moment van de inwerkingtreding »",
        "zones_hors_interdiction": ("Everdenberg-Oost", "Energiepark A59", "Zonnepark Dorst"),
        "source": "CVDR756415, 20/06/2026",
    },
    "best": {
        "plafond_par_pointe_parc_pv": True,
        "zone_concernee": "buitengebied",
        "citation": ("« een batterijpakket bij een zonnepark maximaal dezelfde capaciteit mag "
                     "hebben als de maximale piekcapaciteit van het zonnepark »"),
        "portee": ("présenté comme un uitgangspunt, pas une interdiction, et annoncé « in lijn "
                   "met de richtlijn die de provincie Noord-Brabant hiervoor hanteert » : "
                   "règle potentiellement PROVINCIALE, à confirmer dans le texte de la province"),
        "source": "Best, 730220, 2024",
    },
}


@enregistrer("CTRL-HAUTEUR-COMMUNE", contraintes=["SIT-015", "SIT-002"],
             titre="Hauteur autorisée par la commune",
             besoins={"commune": "commune d'implantation du site",
                      "hauteur_installation_m": "hauteur hors tout de l'installation, fondation comprise"})
def hauteur_commune(dossier: dict[str, Any]) -> dict[str, Any]:
    """La commune peut être plus sévère que le Besluit bouwwerken leefomgeving.

    SIT-015 : le Bbl place ses seuils à 5 m et 20 m, Hollands Kroon plafonne à
    3,5 m, porté à 7 m seulement près d'un poste 380 kV. Deux conteneurs empilés
    sont légaux à Dordrecht et interdits à Hollands Kroon.
    """
    if invalide := _entree_numerique_invalide(dossier, REGISTRE['CTRL-HAUTEUR-COMMUNE']):
        return invalide
    commune = _cle_commune(dossier["commune"])
    hauteur = float(dossier["hauteur_installation_m"])
    regle = REGLES_COMMUNALES.get(commune)
    if not regle or "hauteur_max_m" not in regle:
        return {
            "id": "CTRL-HAUTEUR-COMMUNE",
            "titre": "Hauteur autorisée par la commune",
            "contraintes": ["SIT-015", "SIT-002"],
            "statut": "bloque",
            "constat": (
                f"Non évaluable, aucune règle de hauteur lue en source primaire pour "
                f"la commune de {dossier['commune']}."
            ),
            "manque": [{"champ": "regle_communale",
                        "ou_le_trouver": "beleidslijn batterijopslag de la commune sur "
                                         "lokaleregelgeving.overheid.nl, à lire avant de conclure"}],
        }
    pres_380 = dossier.get("adjacent_poste_380kv")
    if pres_380 is not None and type(pres_380) is not bool:
        return {
            "id": "CTRL-HAUTEUR-COMMUNE", "titre": "Hauteur autorisée par la commune",
            "contraintes": ["SIT-015", "SIT-002"], "statut": "bloque",
            "constat": "Adjacence au poste 380 kV invalide : fournir oui ou non, sans texte ni valeur numérique.",
            "valeurs": {"raison": "adjacence_380kv_invalide"},
            "manque": [{"champ": "adjacent_poste_380kv", "ou_le_trouver": "plan cadastral : installation adjacente au poste 380 kV, oui ou non"}],
        }
    pres_380 = pres_380 is True
    plafond = regle["hauteur_max_m_pres_380kv"] if pres_380 else regle["hauteur_max_m"]
    conforme = hauteur <= plafond
    complement = ""
    if not conforme and regle.get("hauteur_derogeable"):
        complement = (" Le plafond est dérogeable sur motivation "
                      + str(regle.get("citation_derogation", "")) +
                      " : c'est un point à motiver, pas un refus automatique.")
    if pres_380 and regle.get("note_380kv"):
        complement += " " + regle["note_380kv"] + "."
    return {
        "id": "CTRL-HAUTEUR-COMMUNE",
        "titre": "Hauteur autorisée par la commune",
        "contraintes": ["SIT-015", "SIT-002"],
        "statut": "constat" if conforme else "alerte",
        "constat": (
            f"{hauteur:.2f} m pour un plafond communal de {plafond:.2f} m à "
            f"{dossier['commune']}" + (" (adjacent à un poste 380 kV)." if pres_380 else ".")
            + complement
        ),
        "valeurs": {"hauteur_m": hauteur, "plafond_m": plafond, "conforme": conforme,
                    "installations_max_par_bouwvlak": regle.get("installations_max_par_bouwvlak")},
        "source_communale": regle["source"],
        "condition_accessoire": regle.get("condition_accessoire"),
        "consequence_contractuelle": (
            "Hors plafond, l'implantation telle que dessinée doit être motivée. "
            "Le Bbl national n'y change rien : la commune peut être plus sévère, "
            "et elle peut aussi déroger à sa propre règle."
        ),
    }


@enregistrer("CTRL-BRUIT-COMMUNE", contraintes=["SIT-016", "SIT-004"],
             titre="Bruit en façade sensible",
             besoins={"commune": "commune d'implantation du site",
                      "bruit_facade_db": "niveau prévu en façade du bâtiment sensible le plus proche, "
                                         "rapport acoustique, valeurs jour, soir et nuit",
                      "terrain_industriel_zone": "le site est-il dans un geluidsgezoneerd industrieterrein ? "
                                                 "à lire dans l'omgevingsplan ou auprès de la commune"})
def bruit_commune(dossier: dict[str, Any]) -> dict[str, Any]:
    """Seul jeu de valeurs chiffrées trouvé côté bruit, modèle Drechtsteden.

    SIT-016 : refus automatique au-delà de 45 dB(A) le jour, 40 le soir et 35 la
    nuit en façade d'un bâtiment sensible. Ailleurs, le niveau admissible est
    renvoyé à l'omgevingsplan sans chiffre.
    """
    commune = _cle_commune(dossier["commune"])
    regle = REGLES_COMMUNALES.get(commune)
    mesures = dossier.get("bruit_facade_db")
    if not regle or "bruit_db_jour" not in regle:
        return {
            "id": "CTRL-BRUIT-COMMUNE",
            "titre": "Bruit en façade sensible",
            "contraintes": ["SIT-016", "SIT-004"],
            "statut": "bloque",
            "constat": (
                f"Non évaluable, aucune valeur chiffrée de bruit lue en source primaire "
                f"pour la commune de {dossier['commune']} ; le niveau admissible est "
                f"renvoyé à l'omgevingsplan."
            ),
            "manque": [{"champ": "regle_bruit_communale",
                        "ou_le_trouver": "omgevingsplan de la commune, règle de niveau "
                                         "acceptable en façade sensible"}],
        }
    chimie = str(dossier.get("chimie_batterie", "")).strip().lower()
    if chimie and regle.get("chimie_visee") and est_lithium(chimie) is False:
        # Relu par hermes : la definition Drechtsteden vise les energiedragers
        # « lithiumhoudende ». Une batterie sodium ou flow est hors champ.
        return {
            "id": "CTRL-BRUIT-COMMUNE",
            "titre": "Bruit en façade sensible",
            "contraintes": ["SIT-016", "SIT-004"],
            "statut": "constat",
            "constat": (
                f"Le seuil communal chiffré ne s'applique pas : le texte vise les "
                f"accumulateurs « {regle['chimie_visee']} » et la chimie déclarée est "
                f"« {chimie} ». Le niveau acceptable reste renvoyé à l'omgevingsplan."
            ),
            "valeurs": {"chimie": chimie, "chimie_visee": regle["chimie_visee"]},
            "source_communale": regle["source"],
        }
    terrain = dossier.get("terrain_industriel_zone")
    if type(terrain) is not bool:
        return {
            "id": "CTRL-BRUIT-COMMUNE", "titre": "Bruit en façade sensible",
            "contraintes": ["SIT-016", "SIT-004"], "statut": "bloque",
            "constat": "Le classement du terrain doit être confirmé par oui ou non avant de comparer les niveaux de bruit.",
            "valeurs": {"raison": "terrain_bruit_invalide"},
            "manque": [{"champ": "terrain_industriel_zone", "ou_le_trouver": "omgevingsplan ou confirmation de la commune : oui ou non, sans valeur numérique ni texte équivalent"}],
        }
    if terrain is True and regle.get("bruit_exception"):
        # Signale par hermes le 24/09 sur le texte brut Drechtsteden :
        # « De aanvraagvereisten voor het aspect geluid geldt niet in geval de EOS
        # is geprojecteerd binnen een geluidsgezoneerd industrieterrein. »
        # Sans cette exception, le cas type de Contingency, un site industriel zone,
        # passait en alerte a tort.
        return {
            "id": "CTRL-BRUIT-COMMUNE",
            "titre": "Bruit en façade sensible",
            "contraintes": ["SIT-016", "SIT-004"],
            "statut": "constat",
            "constat": (
                "Le seuil communal chiffré ne s'applique pas : le site est dans un "
                "geluidsgezoneerd industrieterrein. Le niveau acceptable est renvoyé "
                "à l'omgevingsplan, sans valeur chiffrée opposable."
            ),
            "valeurs": {"exception": regle["bruit_exception"]},
            "source_communale": regle["source"],
            "consequence_contractuelle": (
                "L'absence de seuil chiffré n'est pas une absence de contrainte : "
                "c'est un arbitrage communal au cas par cas (SIT-003)."
            ),
        }
    periodes = ("jour", "soir", "nuit")
    absentes = [moment for moment in periodes
                if not isinstance(mesures, dict) or moment not in mesures or mesures[moment] is None]
    invalides = []
    if not absentes:
        for moment in periodes:
            valeur = mesures[moment]
            try:
                valide = type(valeur) in (int, float) and math.isfinite(valeur)
            except OverflowError:
                valide = False
            if not valide:
                invalides.append(moment)
    if absentes or invalides:
        incomplet = bool(absentes)
        return {
            "id": "CTRL-BRUIT-COMMUNE", "titre": "Bruit en façade sensible",
            "contraintes": ["SIT-016", "SIT-004"], "statut": "bloque",
            "constat": ("Mesures de bruit incomplètes : fournir les niveaux de jour, de soir et de nuit."
                        if incomplet else "Mesures de bruit invalides : chaque période exige un nombre fini, sans booléen ni texte."),
            "valeurs": {"raison": "mesures_bruit_incompletes" if incomplet else "mesures_bruit_invalides",
                        "periodes": absentes or invalides},
            "manque": [{"champ": "bruit_facade_db", "ou_le_trouver": "rapport acoustique : trois niveaux numériques en dB(A), pour jour, soir et nuit"}],
        }
    # Les dB peuvent être négatifs. Seules les trois mesures utilisées entrent
    # dans le résultat ; les annotations restent dans le dossier d'origine.
    mesures = {moment: mesures[moment] for moment in periodes}
    depassements = {
        moment: (mesures[moment], regle[f"bruit_db_{moment}"])
        for moment in periodes
        if mesures[moment] > regle[f"bruit_db_{moment}"]
    }
    return {
        "id": "CTRL-BRUIT-COMMUNE",
        "titre": "Bruit en façade sensible",
        "contraintes": ["SIT-016", "SIT-004"],
        "statut": "alerte" if depassements else "constat",
        "constat": (
            "Dépassement du seuil communal : "
            + "; ".join(f"{m} {v:.1f} dB(A) contre {s:.1f}" for m, (v, s) in depassements.items())
            if depassements else
            "Niveaux prévus sous les seuils communaux jour, soir et nuit."
        ),
        "valeurs": {"mesures_db": mesures, "creneaux": regle.get("bruit_creneaux"),
                    "seuils_db": {m: regle[f"bruit_db_{m}"] for m in ("jour", "soir", "nuit")}},
        "piece_exigee": regle.get("piece_exigee"),
        "source_communale": regle["source"],
        "consequence_contractuelle": (
            "Le dépassement entraîne un refus automatique dans ce modèle communal, "
            "sauf terrain classé zone industrielle."
        ),
    }


@enregistrer("CTRL-USAGE-COMMUNE", contraintes=["REG-018", "REG-007"],
             titre="Qualification de l'usage par la commune",
             besoins={"commune": "commune d'implantation du site",
                      "qualification_usage": "usage de la batterie : propre_activite, service_local ou arbitrage",
                      "sur_site_de_l_entreprise": "l'installation est-elle sur le site de l'entreprise "
                                                  "qu'elle dessert ? plan cadastral ou bail"})
def usage_commune(dossier: dict[str, Any]) -> dict[str, Any]:
    """Certaines communes jugent l'usage de la batterie, pas son implantation.

    REG-018 : Oosterhout interdit tout actif énergétique sauf au service exclusif
    de la propre activité de l'entreprise sur son site. À signaler avec la tension
    juridique de REG-007 : l'article 6.12 lid 1 de l'Energiewet retire aux
    communes la compétence de lier par des règles le stockage d'électricité dans
    l'intérêt de l'approvisionnement énergétique.
    """
    commune = _cle_commune(dossier["commune"])
    usage = str(dossier["qualification_usage"]).strip().lower()
    regle = REGLES_COMMUNALES.get(commune)
    if not regle or "usages_admis" not in regle:
        return {
            "id": "CTRL-USAGE-COMMUNE",
            "titre": "Qualification de l'usage par la commune",
            "contraintes": ["REG-018", "REG-007"],
            "statut": "bloque",
            "constat": (
                f"Non évaluable, aucune règle d'usage lue en source primaire pour la "
                f"commune de {dossier['commune']}."
            ),
            "manque": [{"champ": "regle_usage_communale",
                        "ou_le_trouver": "beleidslijn de la commune sur lokaleregelgeving.overheid.nl"}],
        }
    mise_en_service = dossier.get("date_mise_en_service")
    if mise_en_service and regle.get("hors_champ_si_deja_en_service"):
        if invalide := _dates_invalides(dossier, REGISTRE['CTRL-USAGE-COMMUNE'], ('date_mise_en_service',)):
            return invalide
        jour = _jour_iso(mise_en_service, 'date_mise_en_service')
        if jour < date.fromisoformat(regle["en_vigueur_le"]):
            # Relu par hermes : le texte ne vise que les activites
            # « nog niet plaatsvinden op het moment van de inwerkingtreding ».
            return {
                "id": "CTRL-USAGE-COMMUNE",
                "titre": "Qualification de l'usage par la commune",
                "contraintes": ["REG-018", "REG-007"],
                "statut": "constat",
                "constat": (
                    f"Hors champ : l'installation est en service depuis le "
                    f"{jour.isoformat()}, avant l'entrée en vigueur du texte le "
                    f"{regle['en_vigueur_le']}. {regle.get('citation_champ', '')}"
                ),
                "valeurs": {"date_mise_en_service": jour.isoformat(),
                            "en_vigueur_le": regle["en_vigueur_le"]},
                "source_communale": regle["source"],
            }
    admis = usage in regle["usages_admis"]
    sur_site = dossier.get("sur_site_de_l_entreprise")
    if admis and regle.get("usage_exige_sur_site") and sur_site is not True:
        # Signale par hermes : l'exception d'Oosterhout a DEUX conditions cumulatives.
        # Une batterie d'une entreprise posee sur le terrain du voisin n'est pas exemptee.
        admis = False
    return {
        "id": "CTRL-USAGE-COMMUNE",
        "titre": "Qualification de l'usage par la commune",
        "contraintes": ["REG-018", "REG-007"],
        "statut": "constat" if admis else "alerte",
        "constat": (
            f"Usage déclaré « {usage} » "
            + ("admis" if admis else "hors des usages admis")
            + f" à {dossier['commune']}, qui n'admet que "
            + ", ".join(regle["usages_admis"]) + "."
            + ("" if admis else " Interdit SAUF dérogation : " + str(regle.get("derogation_possible", "")))
            + ("" if sur_site is not False else
               " La condition « sur le site de l'entreprise desservie » n'est pas remplie.")
        ),
        "valeurs": {"usage": usage, "usages_admis": list(regle["usages_admis"]),
                    "sur_site_de_l_entreprise": sur_site, "admis": admis},
        "citation_communale": regle.get("citation_usage"),
        "derogation": regle.get("derogation_possible"),
        "zones_hors_interdiction": list(regle.get("zones_hors_interdiction", ())) or None,
        "source_communale": regle["source"],
        "tension_juridique": (
            "L'article 6.12 lid 1 de l'Energiewet retire aux provinces et aux communes "
            "la compétence de lier par des règles le stockage d'électricité dans "
            "l'intérêt de l'approvisionnement énergétique. Juger l'usage énergétique "
            "d'une batterie semble relever de cette interdiction, sauf requalification "
            "en règle spatiale ou passage par le lid 2. Point à porter devant "
            "l'ingénieur, pas à trancher par le logiciel."
        ),
    }


@enregistrer("CTRL-SEUIL-PERMIS", contraintes=["PER-012", "PER-004", "PER-010"],
             titre="Seuils qui déclenchent une obligation",
             besoins={"capacite_kwh": "capacité utile de l'installation en kWh",
                      "puissance_kw": "puissance de l'installation en kW"})
def seuil_permis(dossier: dict[str, Any]) -> dict[str, Any]:
    """Quatre seuils coexistent et ne mesurent pas la même grandeur.

    PER-004 : PGS 37-1 s'applique dès 20 kWh de lithium.
    PER-012 : permis communal dès 1 MWh dans le modèle Drechtsteden.
    PER-010 : obligation de déclaration au gestionnaire à partir de 800 kW.
    """
    if invalide := _entree_numerique_invalide(dossier, REGISTRE['CTRL-SEUIL-PERMIS']):
        return invalide
    capacite = float(dossier["capacite_kwh"])
    puissance = float(dossier["puissance_kw"])
    commune = _cle_commune(dossier.get("commune", ""))
    regle = REGLES_COMMUNALES.get(commune, {})
    franchis, manques = [], []
    lithium = est_lithium(dossier.get('chimie_batterie'))
    pgs = 'sous_seuil'
    if capacite > 20:
        if lithium is None:
            pgs = 'a_confirmer'
            manques.append({'champ': 'chimie_batterie', 'ou_le_trouver': 'Fiche fabricant : présence de lithium et exclusions PGS 37-1.'})
        elif not lithium:
            pgs = 'hors_champ_chimie'
        elif capacite > 400000:
            pgs = 'sur_mesure'
            franchis.append('Au-delà de 400 MWh : analyse de risque sur mesure et concertation avec la région de sécurité, en cohérence avec PGS 37-1 (PER-004).')
        else:
            pgs = 'dans_plage'
            franchis.append('PGS 37-1 : lithium et capacité dans la plage supérieure à 20 kWh et au plus 400 MWh ; exclusions d’usage et prescriptions à confirmer (PER-004).')
    champ_permis = None
    permis = None
    if 'permis_des_mwh' in regle:
        import champ_communal
        champ_permis = champ_communal.dans_le_champ(dossier, commune)
        if champ_permis['statut'] == 'dans_le_champ':
            permis = capacite >= regle['permis_des_mwh'] * 1000
            if permis:
                franchis.append(f"Permis communal requis selon le champ déclaré dès {regle['permis_des_mwh']} MWh ({regle['source']}).")
        elif champ_permis['statut'] == 'hors_champ':
            permis = False
        else:
            manques.extend(champ_permis['manque'])
    if puissance >= 800:
        franchis.append("obligation de déclaration au gestionnaire à partir de 800 kW "
                        "(PER-010, source sectorielle à confirmer dans le code)")
    return {
        "id": "CTRL-SEUIL-PERMIS",
        "titre": "Seuils qui déclenchent une obligation",
        "contraintes": ["PER-012", "PER-004", "PER-010"],
        "statut": 'bloque' if manques else "alerte" if franchis else "constat",
        "constat": ("Seuils franchis : " + " ; ".join(franchis)) if franchis
                   else "Aucune obligation établie par les seuls seuils renseignés ; le champ et les règles applicables restent à vérifier.",
        "valeurs": {"capacite_kwh": capacite, "puissance_kw": puissance,
                    "seuils_franchis": franchis, 'pgs37_1': pgs,
                    'permis_communal_requis': permis, 'declaration_800_kw': puissance >= 800},
        'champ_permis_communal': champ_permis, 'manque': manques,
        "consequence_contractuelle": (
            "Ces seuils portent sur des grandeurs différentes, kWh pour PGS 37-1 et "
            "le permis, kW pour la déclaration. Les confondre en fait rater un."
        ),
    }



@enregistrer("CTRL-PLAFOND-PARC-PV", contraintes=["SIT-011", "SIT-017"],
             titre="Batterie plafonnée par la pointe du parc de production",
             besoins={"commune": "commune d'implantation du site",
                      "puissance_kw": "puissance de la batterie en kW",
                      "puissance_pointe_parc_pv_kw": "puissance de pointe du parc photovoltaïque "
                                                     "auquel la batterie est adossée, fiche technique du parc"})
def plafond_parc_pv(dossier: dict[str, Any]) -> dict[str, Any]:
    """Une batterie adossée à un parc peut être plafonnée par la pointe de ce parc.

    Relu par hermes sur le texte de Best (730220, 2024) : ce n'est ni la règle de
    Tiel, qui dit OÙ implanter, ni une interdiction. Le texte dit COMBIEN, en
    buitengebied seulement, et il est présenté comme un uitgangspunt annoncé « in
    lijn met de richtlijn die de provincie Noord-Brabant hiervoor hanteert ».
    Donc : alerte, jamais refus, et la portée provinciale reste à confirmer dans
    le texte de la province.
    """
    commune = _cle_commune(dossier["commune"])
    regle = REGLES_COMMUNALES.get(commune, {})
    if not regle.get("plafond_par_pointe_parc_pv"):
        return {
            "id": "CTRL-PLAFOND-PARC-PV",
            "titre": "Batterie plafonnée par la pointe du parc de production",
            "contraintes": ["SIT-011", "SIT-017"],
            "statut": "constat",
            "constat": (
                f"Aucune règle de plafonnement par la pointe du parc n'a été lue en "
                f"source primaire pour {dossier['commune']}."
            ),
            "valeurs": {"regle_lue": False},
        }
    if invalide := _entree_numerique_invalide(dossier, REGISTRE['CTRL-PLAFOND-PARC-PV']):
        return invalide
    puissance = float(dossier["puissance_kw"])
    pointe_parc = float(dossier["puissance_pointe_parc_pv_kw"])
    depasse = puissance > pointe_parc
    return {
        "id": "CTRL-PLAFOND-PARC-PV",
        "titre": "Batterie plafonnée par la pointe du parc de production",
        "contraintes": ["SIT-011", "SIT-017"],
        "statut": "alerte" if depasse else "constat",
        "constat": (
            f"Batterie {puissance:.0f} kW pour un parc de pointe {pointe_parc:.0f} kW"
            + (", au-dessus du plafond communal." if depasse else ", sous le plafond communal.")
        ),
        "valeurs": {"puissance_kw": puissance, "pointe_parc_kw": pointe_parc,
                    "depasse": depasse, "zone_concernee": regle.get("zone_concernee")},
        "citation_communale": regle.get("citation"),
        "portee": regle.get("portee"),
        "source_communale": regle["source"],
        "consequence_contractuelle": (
            "Le texte est un uitgangspunt, pas une interdiction : le dépassement se "
            "négocie, il ne se refuse pas automatiquement. La règle vise le "
            "buitengebied et pourrait être d'origine provinciale."
        ),
    }


# ---------------------------------------------------------------------------
# Batterie : vérifications techniques, sans seuil fabricant implicite.
# ---------------------------------------------------------------------------

@enregistrer('CTRL-BAT-SOC', contraintes=['BAT-004'],
             titre='Capacité exploitable dans la fenêtre de charge', besoins=batterie.BESOINS_SOC)
def capacite_batterie(dossier: dict[str, Any]) -> dict[str, Any]:
    return batterie.capacite_exploitable(dossier)


@enregistrer('CTRL-BAT-PUISSANCE', contraintes=['BAT-008'],
             titre='Puissance demandée et taux de décharge', besoins=batterie.BESOINS_PUISSANCE)
def puissance_batterie(dossier: dict[str, Any]) -> dict[str, Any]:
    return batterie.puissance_decharge(dossier)


@enregistrer('CTRL-BAT-ENGAGEMENTS', contraintes=['ECO-010'],
             titre='Engagements simultanés de batterie', besoins=batterie.BESOINS_ENGAGEMENTS)
def engagements_batterie(dossier: dict[str, Any]) -> dict[str, Any]:
    return batterie.engagements_simultanes(dossier)


# ---------------------------------------------------------------------------
# Exécution.
# ---------------------------------------------------------------------------

# Contrôles dont la règle vient d'un texte communal. Règle des deux étages,
# établie par hermes le 24/09 après relecture des six textes : six communes sur
# six ont une clause de champ d'application (toepassingsbereik, overgangsrecht,
# vergunningsvrij, chimie visée, régime de lieu) qui précède le seuil chiffré.
# Le chiffre n'est jamais la première question.
COMMUNAUX = {"CTRL-HAUTEUR-COMMUNE", "CTRL-BRUIT-COMMUNE",
             "CTRL-USAGE-COMMUNE", "CTRL-PLAFOND-PARC-PV"}


def _etage_champ(dossier: dict[str, Any], entree: dict[str, Any],
                 verdict: dict[str, Any]) -> dict[str, Any] | None:
    """Étage 1 : le texte communal s'applique-t-il à CE site ?

    Renvoie un résultat final si l'étage 1 tranche seul (hors champ) ou bloque
    (indéterminé), ou ``None`` pour passer à l'étage 2, le seuil chiffré.
    Si l'étage 1 est indéterminé, le chiffre n'est JAMAIS affiché : sinon
    l'ingénieur retient « 3,5 m » pour un site que la règle ne vise même pas.
    """
    base_resultat = {"id": entree["id"], "titre": entree["titre"],
                     "contraintes": entree["contraintes"],
                     "champ_d_application": verdict}
    if verdict["statut"] == "hors_champ":
        return {**base_resultat, "statut": "constat",
                "constat": (f"La règle communale de {dossier['commune']} existe, mais ce site "
                            f"n'y est pas soumis : {verdict['raison']}"),
                "citation_communale": verdict.get("citation")}
    if verdict["statut"] == "indetermine":
        return {**base_resultat, "statut": "bloque",
                "constat": ("Non évaluable : on ne sait pas encore si la règle communale "
                            "s'applique à ce site. Le seuil n'est pas affiché tant que ce "
                            "point n'est pas établi."),
                "manque": verdict.get("manque", [])}
    if (verdict.get("variante") == "hors_regimes_admis"
            or verdict.get("condition_lieu_remplie") is False):
        return {**base_resultat, "statut": "alerte",
                "constat": ("Le texte s'applique, mais le lieu déclaré n'est pas dans un "
                            "régime admis. Le contrôle du seuil chiffré est suspendu, "
                            "la règle de localisation doit être résolue."),
                "citation_communale": verdict.get("citation_variante") or verdict.get("citation"),
                "source_communale": f"{verdict.get('reference')} en vigueur depuis {verdict.get('en_vigueur_le')}"}
    if verdict.get("statut") != "dans_le_champ":
        return {**base_resultat, "statut": "bloque",
                "constat": "Non évaluable : résultat inconnu du contrôle de champ d'application.",
                "manque": [{"champ": "champ_d_application",
                            "ou_le_trouver": "rejouer le contrôle local de champ communal"}]}
    return None


def executer_tous(dossier: dict[str, Any]) -> list[dict[str, Any]]:
    """Passe tous les contrôles du registre. Un contrôle bloqué n'arrête rien.

    Si le dossier vient d'un vrai export (``profil_brut``), la cohérence profil /
    facture passe d'abord. Tant que l'unité n'est pas confirmée contre le kWmax
    facturé, aucun contrôle qui lit le profil ne conclut : une erreur kWh / kW
    diviserait la pointe par quatre et inventerait une marge.
    """
    resultats = []
    fiabilite = None
    reference = reference_gtv.etablir(dossier)
    if "profil_brut" in dossier:
        import coherence_mesures
        coherence = coherence_mesures.executer(dossier)
        resultats.extend(coherence)
        if coherence_mesures.puissance_fiable(coherence):
            unite_confirmee = next(r for r in coherence if r["id"] == "COH-UNITE")
            # Audit Opus n°4 : unité confirmée sur la période facturée ; si tout l'export est fourni
            # (dossier_client), les contrôles de puissance le lisent, comme le scan du même dossier.
            brut, horodatages = dossier.get("profil_export", (dossier["profil_brut"], dossier["profil_horodatages"]))
            dossier = {**dossier, "profil_kw": coherence_mesures.profil_comparable(
                brut, dossier["unite_profil"], unite_confirmee), "profil_horodatages": horodatages}
        else:
            fiabilite = next(r for r in coherence if r["id"] == "COH-UNITE")
    for entree in REGISTRE.values():
        utilise_profil = ("profil_kw" in entree["besoins"] or
                          (entree['id'] == 'CTRL-TRANSPORTRECHT' and
                           str(dossier.get('type_transportrecht', '')).strip().lower() == 'tijdsblok'))
        if fiabilite is not None and utilise_profil:
            resultats.append({
                "id": entree["id"], "titre": entree["titre"],
                "contraintes": entree["contraintes"], "statut": "bloque",
                "constat": ("Non évaluable : l'unité du profil n'est pas confirmée contre "
                            "la facture. " + fiabilite["constat"]),
                "manque": fiabilite.get("manque", []),
            })
            continue
        manques = _manques(dossier, entree["besoins"])
        champs_dates = [c for c in entree['besoins'] if c.startswith('date_')]
        if entree['id'] in COMMUNAUX:
            champs_dates.append('date_mise_en_service')
        if invalide := _dates_invalides(dossier, entree, champs_dates):
            resultats.append(invalide)
            continue
        verdict_champ = None
        if entree["id"] in COMMUNAUX and dossier.get("commune"):
            import champ_communal
            verdict_champ = champ_communal.dans_le_champ(dossier, _cle_commune(dossier["commune"]))
            tranche = _etage_champ(dossier, entree, verdict_champ)
            if tranche is not None:
                resultats.append(tranche)
                continue
        if manques:
            resultat = _bloque(entree, manques)
            if verdict_champ is not None:
                resultat["champ_d_application"] = verdict_champ
            resultats.append(resultat)
            continue
        if invalide := _entree_numerique_invalide(dossier, entree):
            resultats.append(invalide)
            continue
        utilise_gtv_actuel = (("gtv_kw" in entree["besoins"] and entree["id"] != "CTRL-GTV-DECLARE")
                              or entree["id"] == "CTRL-CM-1MW")
        if utilise_gtv_actuel and reference and reference["statut"] == "bloque":
            resultats.append(reference_gtv.bloque(entree, reference))
            continue
        if reference and entree['id'] == 'CTRL-CAPACITE-DORMANTE':
            resultats.append({"id": entree['id'], "titre": entree['titre'],
                              "contraintes": [*entree['contraintes'], 'RES-012'], "statut": "bloque",
                              "constat": "L'ATO et la dernière déclaration diffèrent. La confirmation du GTV actuel ne prouve pas qu'il s'appliquait à tous les mois facturés : coût de capacité inutilisée non calculé sans reconstitution des périodes.",
                              "valeurs": {"raison": "gtv_cout_periode_non_confirmee"},
                              "reference_gtv": reference,
                              "manque": [{"champ": "periodes_gtv_facturees", "ou_le_trouver": "factures successives : GTV, tarif et dates d'application sur chaque période ; reconstitution manuelle nécessaire"}]})
            continue
        dossier_calcul = dossier
        if utilise_gtv_actuel and reference:
            dossier_calcul = {**dossier, "gtv_kw": reference["reference_kw"]}
        try:
            resultat = entree["fonction"](dossier_calcul)
        except (ValueError, TypeError) as erreur:
            resultat = _bloque(entree, [{'champ': 'donnees_du_controle',
                                        'ou_le_trouver': 'Corriger la donnée invalide : ' + str(erreur)}])
        if utilise_gtv_actuel and reference:
            resultat["reference_gtv"] = reference
            resultat["contraintes"] = list(dict.fromkeys([*resultat["contraintes"], "RES-012", "RES-024"]))
        resultat.setdefault("titre", entree["titre"])
        if verdict_champ is not None:
            resultat["champ_d_application"] = verdict_champ
        resultats.append(resultat)
    return resultats


def plan_de_deblocage(resultats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classe les données manquantes par nombre de contrôles qu'elles ouvriraient.

    C'est ce qui transforme la liste des manques en chemin de progression :
    l'ingénieur voit « fournissez ce seul chiffre et trois contrôles s'ouvrent »
    au lieu d'un mur de champs vides.
    """
    compte: dict[str, dict[str, Any]] = {}
    for resultat in resultats:
        for manque in resultat.get("manque", []):
            fiche = compte.setdefault(manque["champ"], {
                "champ": manque["champ"],
                "ou_le_trouver": manque["ou_le_trouver"],
                "debloque": [],
            })
            fiche["debloque"].append(resultat["id"])
    return sorted(compte.values(), key=lambda f: (-len(f["debloque"]), f["champ"]))


def compter(resultats: list[dict[str, Any]]) -> dict[str, int]:
    compte = {"constat": 0, "alerte": 0, "bloque": 0}
    for resultat in resultats:
        compte[resultat["statut"]] = compte.get(resultat["statut"], 0) + 1
    return compte
