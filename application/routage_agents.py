"""Décide quand demander un second avis, sans appel réseau implicite."""
from __future__ import annotations

import os


def planifier(extraction: dict | None, audit: dict | None = None,
              contraintes: list | None = None) -> dict:
    extraction = extraction or {}
    raisons = []
    propositions = extraction.get("propositions", {})
    if extraction.get("alertes"):
        raisons.append("alertes_extraction")
    if any(p.get("valeur") is None for p in propositions.values() if isinstance(p, dict)):
        raisons.append("champ_sans_valeur")
    if any(not preuve.get("valide", False)
           for p in propositions.values() if isinstance(p, dict)
           for preuve in p.get("preuves", [])):
        raisons.append("preuve_invalide")
    if (audit or {}).get("anomalies"):
        raisons.append("anomalie_documentaire")
    if any(c.get("statut") == "a_revoir" for c in (contraintes or []) if isinstance(c, dict)):
        raisons.append("contrainte_a_revoir")
    return {
        "agent_principal": extraction.get("modele", os.environ.get(
            "NEBIUS_CHAT_MODEL", "deepseek-ai/DeepSeek-V4.1-Flash")),
        "agent_second_avis": os.environ.get("NEBIUS_REVIEW_MODEL", "zai-org/GLM-5.3"),
        "second_avis_requis": bool(raisons),
        "raisons": raisons,
        "appel_second_avis": "a_la_demande" if raisons else "inutile_pour_l_instant",
    }
