"""Contrôles de contrat réseau, dérivés du catalogue des contraintes.

Quatre contrôles seulement, ceux dont la règle a une forme mesurable exacte et
une source primaire lue. Chacun cite l'entrée du catalogue dont il vient.

Deux principes tenus dans tout le module :

1. Un contrôle ne conclut jamais à la place de l'ingénieur. Il produit un
   constat chiffré et la conséquence contractuelle telle qu'elle est écrite
   dans la source, pas une recommandation.
2. Une donnée manquante bloque. Le contrôle renvoie ``statut = "bloque"`` et la
   liste de ce qui manque. Il ne choisit aucune valeur par défaut (TRA-005).
"""
from __future__ import annotations

from typing import Any
import math


MESURES_PAR_BLOC = 96  # un bloc de 24 heures au pas de 15 minutes

# Facteurs de puissance usuels bornant le transport contractable à partir de la
# capacité de raccordement (RES-023, Stedin, règlement tarifaire grootverbruik
# 2026, article 5 alinéa 7).
COS_PHI_USUEL = {"soutirage": 0.85, "injection": 1.00}


def nombre_non_negatif(valeur: Any) -> bool:
    """Une puissance est un nombre fini ; un booléen n'est pas une mesure."""
    try:
        return type(valeur) in (int, float) and math.isfinite(valeur) and valeur >= 0
    except OverflowError:
        return False


def profil_puissance_valide(profil: Any) -> bool:
    return isinstance(profil, (list, tuple)) and bool(profil) and all(nombre_non_negatif(v) for v in profil)


def _profil_absent(profil: Any) -> bool:
    return profil is None or isinstance(profil, (list, tuple)) and not profil


def entree_invalide(identifiant: str, contraintes: list[str], champ: str,
                    ou_le_trouver: str, *, calcul: bool = False) -> dict[str, Any]:
    """Blocage exploitable également par le registre et les rapports."""
    return {"id": identifiant, "contraintes": contraintes, "statut": "bloque",
            "constat": (f"Calcul non représentable avec {champ} : vérifier la valeur fournie."
                        if calcul else f"Valeur invalide pour {champ} : fournir des nombres finis, non négatifs, sans booléen."),
            "valeurs": {"raison": "calcul_contrat_non_fini" if calcul else "entree_contrat_invalide", "champ": champ},
            "manque": [{"champ": champ, "ou_le_trouver": ou_le_trouver}]}


def _bloque(identifiant: str, contraintes: list[str], manque: list[str],
            pourquoi: str) -> dict[str, Any]:
    return {
        "id": identifiant,
        "contraintes": contraintes,
        "statut": "bloque",
        "constat": None,
        "manque": manque,
        "pourquoi": pourquoi,
    }


def marge_contractuelle(profil_kw: list[float], gtv_kw: float | None) -> dict[str, Any]:
    """Ce qu'il reste dans le contrat actuel, avant de dimensionner quoi que ce soit.

    C'est le premier résultat que doit sortir une étude (OPE-007) : sur la zone
    d'activité de Veendam, plusieurs entreprises se croyaient bloquées alors
    qu'elles avaient de la marge dans leur propre contrat et l'ignoraient.

    Le test porte sur la série quart-horaire, jamais sur une moyenne (DAT-001).
    """
    contraintes = ["RES-001", "DAT-001", "OPE-007"]
    manque = []
    if gtv_kw is None:
        manque.append("gecontracteerd transportvermogen (GTV) en kW, à lire dans l'ATO")
    if _profil_absent(profil_kw):
        manque.append("profil de puissance au pas de 15 minutes")
    if manque:
        return _bloque("CTRL-MARGE", contraintes, manque,
                       "La marge ne se déduit d'aucune autre donnée du dossier.")

    if not nombre_non_negatif(gtv_kw):
        return entree_invalide("CTRL-MARGE", contraintes, "gtv_kw", "ATO, transport contracté en kW")
    if not profil_puissance_valide(profil_kw):
        return entree_invalide("CTRL-MARGE", contraintes, "profil_kw", "export compteur, puissances au quart d'heure")

    pointe = max(profil_kw)
    marge = gtv_kw - pointe
    utilisation = pointe / gtv_kw if gtv_kw else None
    if utilisation is not None and (not math.isfinite(utilisation) or not math.isfinite(utilisation * 100)):
        return entree_invalide("CTRL-MARGE", contraintes, "gtv_kw", "ATO, transport contracté en kW", calcul=True)
    depassements = [i for i, v in enumerate(profil_kw) if v > gtv_kw]
    return {
        "id": "CTRL-MARGE",
        "contraintes": contraintes,
        "statut": "alerte" if depassements else "constat",
        "constat": (
            # « du profil » et non « mesurée » : la qualité de ce quart n'est pas toujours une mesure documentée (revue
            # d'Astra de 69800f2) ; la réserve éventuelle est portée par le contrôle.
            f"Pointe quart-horaire du profil {pointe:.1f} kW pour un transport "
            f"contracté de {gtv_kw:.1f} kW."
        ),
        "valeurs": {
            "pointe_kw": pointe,
            "gtv_kw": gtv_kw,
            "marge_kw": marge,
            "taux_utilisation": utilisation,
            "nombre_quarts_en_depassement": len(depassements),
            "nombre_quarts_mesures": len(profil_kw),
        },
        "consequence_contractuelle": (
            "La facturation dépend de la catégorie tarifaire : maxima de puissance mensuels "
            "ou hebdomadaires, éventuellement pondérés, et autres termes (ECO-001). "
            "La marge physique ne détermine pas à elle seule le montant de la facture."
        ),
    }


def gtv_maximal(capacite_aansluiting_kva: float | None,
                direction: str = "soutirage") -> dict[str, Any]:
    """Transport contractable au maximum, à partir de la capacité de raccordement.

    RES-023 : « Het gecontracteerd transportvermogen wordt begrensd door de
    capaciteit van de aansluiting rekening houdend met een gebruikelijke waarde
    voor de arbeidsfactor (cos phi). De gebruikelijke waarde is 0,85 voor afname
    en 1,00 voor teruglevering. »

    C'est la formule qui sépare la capacité de raccordement du droit de
    transport (RES-002), les deux valeurs que les dossiers confondent.
    """
    contraintes = ["RES-023", "RES-002"]
    if not isinstance(direction, str) or direction not in COS_PHI_USUEL:
        raise ValueError("Direction attendue : soutirage ou injection.")
    if capacite_aansluiting_kva is None:
        return _bloque("CTRL-GTV-MAX", contraintes,
                       ["capacité de raccordement en kVA"],
                       "La capacité de raccordement ne se déduit pas du profil mesuré.")
    if not nombre_non_negatif(capacite_aansluiting_kva):
        return entree_invalide("CTRL-GTV-MAX", contraintes, "capacite_aansluiting_kva", "ATO, capacité de raccordement en kVA")

    facteur = COS_PHI_USUEL[direction]
    plafond = capacite_aansluiting_kva * facteur
    return {
        "id": "CTRL-GTV-MAX",
        "contraintes": contraintes,
        "statut": "constat",
        "constat": (
            f"Avec une capacité de raccordement de {capacite_aansluiting_kva:.1f} kVA, "
            f"le transport contractable en {direction} plafonne à {plafond:.1f} kW "
            f"(facteur usuel {facteur})."
        ),
        "valeurs": {
            "capacite_kva": capacite_aansluiting_kva,
            "direction": direction,
            "facteur_cos_phi": facteur,
            "gtv_max_kw": plafond,
        },
        "consequence_contractuelle": (
            "Le facteur usuel est celui du règlement tarifaire ; une valeur "
            "différente doit être écrite dans le contrat du site pour être opposable."
        ),
    }


def ecart_gtv_declare(gtv_contrat_kw: float | None,
                      gtv_declare_kw: float | None) -> dict[str, Any]:
    """Écart entre le GTV écrit dans l'ATO et le dernier vermogen déclaré.

    RES-012, décision ACM NorthC contre Liander : le droit de transport porte
    sur le DERNIER vermogen déclaré, pas sur celui du contrat d'origine. Un site
    qui a baissé sa déclaration pour économiser a perdu la capacité, et cela ne
    se voit qu'en croisant le contrat avec les factures.
    """
    contraintes = ["RES-012", "RES-024"]
    manque = []
    if gtv_contrat_kw is None:
        manque.append("GTV écrit dans l'aansluit- en transportovereenkomst")
    if gtv_declare_kw is None:
        manque.append("dernier vermogen déclaré au gestionnaire, à lire sur les factures")
    if manque:
        return _bloque("CTRL-GTV-DECLARE", contraintes, manque,
                       "Un seul des deux chiffres ne permet aucune conclusion : "
                       "c'est leur écart qui porte l'information.")

    for champ, valeur in (("gtv_kw", gtv_contrat_kw), ("gtv_declare_kw", gtv_declare_kw)):
        if not nombre_non_negatif(valeur):
            return entree_invalide("CTRL-GTV-DECLARE", contraintes, champ, "ATO ou facture, transport contracté ou dernier déclaré en kW")

    ecart = gtv_contrat_kw - gtv_declare_kw
    return {
        "id": "CTRL-GTV-DECLARE",
        "contraintes": contraintes,
        "statut": "alerte" if ecart > 0 else "constat",
        "constat": (
            f"Contrat {gtv_contrat_kw:.1f} kW, dernier vermogen déclaré "
            f"{gtv_declare_kw:.1f} kW, écart {ecart:.1f} kW."
        ),
        "valeurs": {
            "gtv_contrat_kw": gtv_contrat_kw,
            "gtv_declare_kw": gtv_declare_kw,
            "ecart_kw": ecart,
            "gtv_opposable_kw": gtv_declare_kw,
        },
        "consequence_contractuelle": (
            "Le droit opposable est le dernier vermogen déclaré. Le retour au "
            "chiffre du contrat est une demande d'augmentation, soumise à la "
            "capacité disponible dans la zone, et refusable en congestion."
        ),
    }


def depassements_par_bloc(profil_kw: list[float], gtv_kw: float | None) -> dict[str, Any]:
    """Blocs de 24 heures comportant au moins un quart d'heure au-dessus du GTV.

    RES-026, Stedin, règlement tarifaire grootverbruik 2026, article 4 alinéa 14 :
    si le dépassement se produit pendant deux mois de consommation CONSÉCUTIFS ou
    plus, même après mesures, le gestionnaire peut suspendre le raccordement.

    Le seuil contractuel porte sur des mois de consommation. Le dossier ne
    conserve que des valeurs, sans horodatage, donc ce contrôle s'arrête au
    comptage par bloc de 24 heures et refuse de conclure sur le seuil des deux
    mois. C'est un manque de donnée à corriger en amont, pas une approximation
    à accepter.
    """
    contraintes = ["RES-026", "REG-014"]
    manque = []
    if gtv_kw is None:
        manque.append("gecontracteerd transportvermogen (GTV) en kW")
    if _profil_absent(profil_kw):
        manque.append("profil de puissance au pas de 15 minutes")
    if manque:
        return _bloque("CTRL-DEPASSEMENT", contraintes, manque,
                       "Le comptage des dépassements suppose les deux valeurs.")

    if not nombre_non_negatif(gtv_kw):
        return entree_invalide("CTRL-DEPASSEMENT", contraintes, "gtv_kw", "ATO, transport contracté en kW")
    if not profil_puissance_valide(profil_kw):
        return entree_invalide("CTRL-DEPASSEMENT", contraintes, "profil_kw", "export compteur, puissances au quart d'heure")

    blocs = [profil_kw[i:i + MESURES_PAR_BLOC]
             for i in range(0, len(profil_kw), MESURES_PAR_BLOC)]
    touches = [numero for numero, bloc in enumerate(blocs, 1) if any(v > gtv_kw for v in bloc)]
    serie = 0
    plus_longue = 0
    for numero in range(1, len(blocs) + 1):
        serie = serie + 1 if numero in touches else 0
        plus_longue = max(plus_longue, serie)

    return {
        "id": "CTRL-DEPASSEMENT",
        "contraintes": contraintes,
        "statut": "alerte" if touches else "constat",
        "constat": (
            f"{len(touches)} bloc(s) de 24 heures sur {len(blocs)} comportent au "
            f"moins un quart d'heure au-dessus du transport contracté, la plus "
            f"longue série consécutive étant de {plus_longue} bloc(s)."
        ),
        "valeurs": {
            "blocs_en_depassement": touches,
            "nombre_blocs": len(blocs),
            "plus_longue_serie_blocs": plus_longue,
        },
        "seuil_contractuel_non_teste": {
            "regle": "deux mois de consommation consécutifs en dépassement",
            "consequence": "suspension possible du raccordement par le gestionnaire",
            "manque": "horodatage du profil, non conservé dans le dossier",
        },
        "consequence_contractuelle": (
            "Le dépassement est facturé selon la Tarievencode. Au-delà, il peut "
            "être interdit sous astreinte par un juge (REG-014) et le raccordement "
            "peut être suspendu après deux mois consécutifs (RES-026)."
        ),
    }


def executer(*, profil_kw: list[float], gtv_kw: float | None = None,
             capacite_aansluiting_kva: float | None = None,
             gtv_declare_kw: float | None = None,
             direction: str = "soutirage") -> list[dict[str, Any]]:
    """Passe les quatre contrôles et renvoie leurs résultats dans l'ordre de lecture."""
    return [
        marge_contractuelle(profil_kw, gtv_kw),
        gtv_maximal(capacite_aansluiting_kva, direction),
        ecart_gtv_declare(gtv_kw, gtv_declare_kw),
        depassements_par_bloc(profil_kw, gtv_kw),
    ]
