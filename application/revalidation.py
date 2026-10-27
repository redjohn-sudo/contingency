"""Revalidation locale d'un dossier quand le catalogue évolue.

Cette étape ne contacte aucune source externe et ne prétend pas vérifier le
droit. Elle rejoue les contrôles déterministes avec le catalogue présent sur la
machine et expose les résultats qui ont changé.
"""
from __future__ import annotations

import json
import math
from typing import Any

import catalogue
import controles


def _json(objet: Any) -> str:
    return json.dumps(objet, ensure_ascii=False, sort_keys=True, default=str)


def _valeurs_numeriques(objet: Any, chemin: str = "") -> dict[str, Any]:
    """Extrait les nombres par chemin, sans confondre booléens et nombres."""
    if isinstance(objet, bool) or objet is None:
        return {}
    if isinstance(objet, (int, float)):
        if isinstance(objet, float) and not math.isfinite(objet):
            return {chemin: str(objet)}
        return {chemin: objet}
    if isinstance(objet, dict):
        return {
            sous_chemin: valeur
            for cle, element in objet.items()
            for sous_chemin, valeur in _valeurs_numeriques(
                element, f"{chemin}.{cle}" if chemin else str(cle)
            ).items()
        }
    if isinstance(objet, list):
        return {
            sous_chemin: valeur
            for index, element in enumerate(objet)
            for sous_chemin, valeur in _valeurs_numeriques(element, f"{chemin}[{index}]").items()
        }
    return {}


def _verdict(resultat: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Compare le statut et les valeurs chiffrées, jamais la prose."""
    return resultat.get("statut"), _valeurs_numeriques(resultat)


def _entree_controles(dossier: dict[str, Any]) -> dict[str, Any]:
    """Construit l'entrée du registre à partir d'une archive de serveur."""
    entree = dict(dossier)
    entree.setdefault("profil_kw", dossier.get("profil", []))
    for champ, fait in (dossier.get("faits") or {}).items():
        if champ not in entree and isinstance(fait, dict):
            entree[champ] = fait.get("valeur")
    return entree


def revalider(dossier: dict[str, Any], anciens_resultats: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Rejoue les contrôles et indique si l'archive doit être revue."""
    courant = catalogue.resume()
    archive = dossier.get("catalogue") or {}
    ancienne_empreinte = archive.get("empreinte") or archive.get("empreinte_catalogue")
    resultats = controles.executer_tous(_entree_controles(dossier))
    controles_archives = anciens_resultats if anciens_resultats is not None else dossier.get("controles")
    controles_archives_connus = controles_archives is not None
    anciens = {r.get("id"): r for r in (controles_archives or [])}
    anciens_ids = set(anciens)
    resultats_ids = {r.get("id") for r in resultats}
    nouveaux = [
        {"type": "nouveau_controle", "id": r["id"], "apres": r}
        for r in resultats
        if controles_archives_connus and r.get("id") not in anciens_ids
    ]
    retires = [
        {"type": "controle_retire", "id": identifiant, "avant": ancien}
        for identifiant, ancien in anciens.items()
        if controles_archives_connus and identifiant not in resultats_ids
    ]
    changements = nouveaux + retires
    reformulations = []
    for resultat in resultats:
        precedent = anciens.get(resultat.get("id"))
        if precedent is None or _json(precedent) == _json(resultat):
            continue
        element = {"id": resultat["id"], "avant": precedent, "apres": resultat}
        if _verdict(precedent) != _verdict(resultat):
            changements.append({"type": "verdict_change", **element})
        else:
            reformulations.append(element)
    empreinte_inconnue = ancienne_empreinte is None
    empreinte_modifiee = (
        None if empreinte_inconnue else ancienne_empreinte != courant["empreinte"]
    )
    raison_catalogue = (
        "empreinte_archive_inconnue" if empreinte_inconnue
        else "empreinte_modifiee" if empreinte_modifiee
        else "empreinte_identique"
    )
    return {
        "statut": "a_revalider" if empreinte_inconnue or empreinte_modifiee or changements else "a_jour",
        "catalogue_avant": ancienne_empreinte,
        "catalogue_courant": courant,
        "empreinte_inconnue": empreinte_inconnue,
        "empreinte_modifiee": empreinte_modifiee,
        "raison_catalogue": raison_catalogue,
        "changements": changements,
        "reformulations": reformulations,
        "resultats": resultats,
        "plan_de_deblocage": controles.plan_de_deblocage(resultats),
    }
