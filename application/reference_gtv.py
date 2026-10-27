"""Référence de transport d'un diagnostic lorsque l'ATO et la facture divergent.

La confirmation est déclarée par le lecteur du dossier. Ce module vérifie
sa structure et sa cohérence ; il n'authentifie ni la personne ni la pièce.
"""
from datetime import date, datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from controles_contrat import nombre_non_negatif


CHAMP_CONFIRMATION = "confirmation_gtv_declare"
SOURCE = "https://www.acm.nl/nl/publicaties/uitspraak-cbb-northc-heeft-geen-recht-op-verhoging-van-transportvermogen-elektriciteit"


def _texte(valeur: Any) -> bool:
    return isinstance(valeur, str) and bool(valeur.strip())


def _date(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valeur):
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def etablir(dossier: dict[str, Any], *, aujourd_hui: date | None = None) -> dict[str, Any] | None:
    """Ne tranche une divergence qu'avec confirmation liée au chiffre déclaré."""
    ato, declare = dossier.get("gtv_kw"), dossier.get("gtv_declare_kw")
    if not nombre_non_negatif(ato) or declare in (None, "", []):
        return None  # Les contrôles d'entrée traitent la référence absente/invalide.
    if not nombre_non_negatif(declare):
        return {"statut": "bloque", "motif": "declaration_invalide", "gtv_ato_kw": ato,
                "gtv_declare_kw": None, "reference_kw": None}
    if ato == declare:
        return None  # Aucun désaccord entre les chiffres fournis.
    resultat = {"statut": "bloque", "motif": "confirmation_absente_ou_invalide",
                "gtv_ato_kw": ato, "gtv_declare_kw": declare, "reference_kw": None,
                "source_regle": SOURCE}
    confirmation = dossier.get(CHAMP_CONFIRMATION)
    if not isinstance(confirmation, dict):
        return resultat
    if (confirmation.get("confirme_actuel") is not True
            or not nombre_non_negatif(confirmation.get("valeur_kw"))
            or confirmation["valeur_kw"] != declare
            or not _texte(confirmation.get("source_document"))
            or not _texte(confirmation.get("verifie_par"))):
        return resultat
    document, verification = (_date(confirmation.get(c)) for c in ("date_document", "date_verification"))
    jour = aujourd_hui or datetime.now(ZoneInfo('Europe/Amsterdam')).date()
    if document is None or verification is None or not document <= verification <= jour:
        return resultat
    preuve = {c: confirmation[c] for c in ("valeur_kw", "confirme_actuel", "source_document", "verifie_par",
                                           "date_document", "date_verification")}
    return {**resultat, "statut": "confirme", "motif": "confirmation_humaine_declaree",
            "reference_kw": declare, "confirmation": preuve,
            "piece_authentifiee_par_application": False}


def bloque(entree: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """Deux chiffres visibles, aucune marge ou économie fabriquée."""
    if reference["gtv_declare_kw"] is None:
        constat = "La dernière déclaration de transport est invalide ; la puissance actuellement applicable reste à confirmer."
    else:
        constat = (f"L'ATO indique {reference['gtv_ato_kw']:.1f} kW et la dernière déclaration fournie "
                   f"{reference['gtv_declare_kw']:.1f} kW. La référence actuelle n'est pas confirmée "
                   "sur une pièce datée : aucun chiffrage de marge, dépassement ou économie contre l'ancien ATO.")
    return {"id": entree["id"], "titre": entree["titre"],
            "contraintes": list(dict.fromkeys([*entree["contraintes"], "RES-012", "RES-024"])),
            "statut": "bloque", "constat": constat,
            "valeurs": {"raison": "gtv_reference_non_confirmee", "gtv_ato_kw": reference["gtv_ato_kw"],
                        "gtv_declare_kw": reference["gtv_declare_kw"]},
            "reference_gtv": reference,
            "manque": [{"champ": CHAMP_CONFIRMATION,
                        "ou_le_trouver": "dernière facture ou accord du gestionnaire : valeur actuelle, source, date du document, nom du lecteur et date de vérification ; confirmer que la valeur est actuellement applicable"}]}
