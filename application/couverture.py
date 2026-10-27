"""Registre de couverture : ce que le produit teste, et ce qu'il ne teste pas.

Décidé le 24/09/2026 à la place du codage immédiat des contrôles restants.

Un rapport qui teste douze règles et se tait sur les cent quarante autres
laisse croire qu'il a tout vu. C'est une fausse conclusion par omission, la
plus difficile à repérer parce que rien d'écrit n'est faux. Ce module range
chaque entrée du catalogue dans une catégorie, pour que le rapport dise
exactement ce qu'il a vérifié et ce qu'il n'a pas vérifié.
"""
from __future__ import annotations

from typing import Any

import catalogue
import controles

CATEGORIES = {
    "testee": "testée automatiquement par un contrôle",
    "codable": "forme mesurable et source vérifiée, pas encore codée",
    "a_verifier": "source à vérifier avant tout usage client",
    "procedure": "règle de procédure ou de méthode, à vérifier par l'ingénieur",
    "conception": "règle de conception interne du produit, sans portée juridique",
}


def _categorie(identifiant: str, entree: dict[str, Any], testees: set[str]) -> str:
    confiance = entree.get("confiance", "").lower()
    # Coder une règle interne ne lui donne pas de portée juridique.
    if "regle de conception" in confiance:
        return "conception"
    if identifiant in testees:
        return "testee"
    if entree.get("juridiction") == "transversal":
        return "conception"
    if "a verifier" in confiance or "non lu" in entree.get("source", "").lower():
        return "a_verifier"
    if entree.get("forme_mesurable") and confiance.startswith("verifie"):
        return "codable"
    return "procedure"


def etablir() -> dict[str, Any]:
    """Classe toutes les entrées du catalogue et renvoie le bilan chiffré."""
    entrees = catalogue.charger()
    testees = {c for e in controles.REGISTRE.values() for c in e["contraintes"]}
    par_categorie: dict[str, list[str]] = {cle: [] for cle in CATEGORIES}
    for identifiant, entree in entrees.items():
        par_categorie[_categorie(identifiant, entree, testees)].append(identifiant)
    juridiques = len(entrees) - len(par_categorie["conception"])
    return {
        "total": len(entrees),
        "juridiques": juridiques,
        "testees": len(par_categorie["testee"]),
        "conception_testees": sorted(testees.intersection(par_categorie["conception"])),
        "total_testees": len(testees.intersection(entrees)),
        "taux_juridique": len(par_categorie["testee"]) / juridiques if juridiques else 0.0,
        "par_categorie": {cle: sorted(ids) for cle, ids in par_categorie.items()},
        "libelles": CATEGORIES,
        "controles": len(controles.REGISTRE),
    }


def phrase(bilan: dict[str, Any]) -> str:
    """La phrase que le rapport imprime, sans arrondi flatteur."""
    return (
        f"Ce rapport applique {bilan['controles']} contrôles, qui testent "
        f"{bilan['testees']} des {bilan['juridiques']} règles juridiques ou "
        f"techniques du catalogue. Les {bilan['juridiques'] - bilan['testees']} "
        f"autres n'ont PAS été vérifiées automatiquement : "
        f"{len(bilan['par_categorie']['codable'])} sont codables et en attente, "
        f"{len(bilan['par_categorie']['procedure'])} relèvent de la procédure et "
        f"restent à vérifier par l'ingénieur, "
        f"{len(bilan['par_categorie']['a_verifier'])} ont une source encore à "
        f"confirmer. {len(bilan.get('conception_testees', []))} règle(s) interne(s) "
        f"de conception sont testées séparément, sans portée juridique. "
        f"L'absence d'alerte sur une règle non testée ne vaut pas conformité."
    )
