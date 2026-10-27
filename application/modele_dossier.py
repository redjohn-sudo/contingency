"""Contrat de données partagé par les étapes v1 à v4.

Le reste de l'application conserve ses champs historiques pour rendre les
archives compatibles. Ce module ajoute les espaces v4 sans appliquer de valeur
ni de conclusion automatiquement.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "contingency-dossier-1"

# Champs métier facultatifs. Un contrôle déclare ses dépendances et bloque
# seulement lui-même si l'un de ces champs manque.
CHAMPS_METIER_OPTIONNELS = (
    "capacite_aansluiting_kva", "gtv_declare_kw", "confirmation_gtv_declare", "tarif_kw_mois_eur",
    "mois_factures", "date_demande", "date_offre", "date_signature",
    "date_depot", "gestionnaire", "commune", "hauteur_installation_m",
    "bruit_facade_db", "qualification_usage", "capacite_kwh",
    "adjacent_poste_380kv", "poste_et_netdeel", "veiligheidsregio",
    "direction", "terrain_industriel_zone", "sur_site_de_l_entreprise",
    "implantation_type", "distance_batiment_tiers_m",
    "puissance_pointe_parc_pv_kw", "eos_en_toiture", "date_expiration_offre",
)


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def nouveau_dossier(*, identifiant: str, documents: list[dict[str, Any]],
                    profil: list[float], profil_sha256: str, nature: str,
                    faits: dict[str, Any],
                    profil_horodatages: list[str] | None = None,
                    metadonnees: dict[str, Any] | None = None,
                    source_document: dict[str, str] | None = None) -> dict[str, Any]:
    """Construit l'enveloppe commune sans changer les faits extraits."""
    maintenant = _maintenant()
    dossier = {
        "id": identifiant,
        "schema_version": SCHEMA_VERSION,
        "created_at": maintenant,
        "updated_at": maintenant,
        "documents": documents,
        "profil": profil,
        "profil_horodatages": profil_horodatages or [],
        "profil_sha256": profil_sha256,
        "nature": nature,
        "faits": faits,
        "extraction_ia": None,
        "revision": None,
        "resultat": None,
        "contraintes": [],
        "validations": [],
        "scenarios": [],
        "suivi": {"evenements": []},
        "catalogue": None,
        "source_document": source_document or {},
    }
    for champ in CHAMPS_METIER_OPTIONNELS:
        dossier[champ] = (metadonnees or {}).get(champ)
    return dossier


def normaliser(dossier: dict[str, Any]) -> dict[str, Any]:
    """Ajoute les champs v4 à une archive v1 existante, sans la muter."""
    resultat = deepcopy(dossier)
    maintenant = _maintenant()
    resultat.setdefault("schema_version", SCHEMA_VERSION)
    resultat.setdefault("created_at", maintenant)
    resultat.setdefault("updated_at", maintenant)
    resultat.setdefault("contraintes", [])
    resultat.setdefault("validations", [])
    resultat.setdefault("scenarios", [])
    resultat.setdefault("suivi", {"evenements": []})
    resultat["suivi"].setdefault("evenements", [])
    resultat.setdefault("catalogue", None)
    resultat.setdefault("profil_horodatages", [])
    resultat.setdefault("source_document", {})
    for champ in CHAMPS_METIER_OPTIONNELS:
        resultat.setdefault(champ, None)
    return resultat


def evenement(dossier: dict[str, Any], type_evenement: str,
              detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ajoute un événement de suivi explicite et retourne un nouveau dossier."""
    resultat = normaliser(dossier)
    resultat["suivi"]["evenements"].append({
        "type": type_evenement,
        "at": _maintenant(),
        "detail": detail or {},
    })
    resultat["updated_at"] = _maintenant()
    return resultat


def verifier(dossier: dict[str, Any]) -> list[str]:
    """Retourne les erreurs de structure, sans juger le contenu métier."""
    erreurs = []
    for cle in ("id", "documents", "profil", "profil_horodatages", "faits", "contraintes",
                "validations", "scenarios", "suivi"):
        if cle not in dossier:
            erreurs.append(f"champ_absent:{cle}")
    if not isinstance(dossier.get("documents"), list):
        erreurs.append("documents_non_liste")
    if not isinstance(dossier.get("profil"), list):
        erreurs.append("profil_non_liste")
    if not isinstance(dossier.get("profil_horodatages"), list):
        erreurs.append("profil_horodatages_non_liste")
    if not isinstance(dossier.get("suivi"), dict):
        erreurs.append("suivi_non_objet")
    return erreurs
