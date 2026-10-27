"""Lecture stricte du catalogue Markdown, sans appliquer de règle implicitement."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any


RACINE = Path(__file__).resolve().parent.parent
SOURCE = RACINE / "docs" / "contraintes" / "CATALOGUE.md"
ENTETE = re.compile(r"^###\s+([A-Z]+-\d+)\s+[—-]\s*(.+)$")

CHAMPS_MULTIPLES = {"famille", "impose_par", "confiance", "juridiction", "contributeur"}


def _multichamp(contenu: str) -> bool:
    """Vrai si la ligne enchaine plusieurs champs connus separes par une barre.

    On ne decoupe pas les lignes de prose qui contiennent une barre par hasard :
    seule une ligne dont chaque morceau porte un champ connu est decoupee.
    """
    morceaux = [m.strip() for m in contenu.split("|")]
    if len(morceaux) < 2:
        return False
    for morceau in morceaux:
        if ":" not in morceau:
            return False
        cle = morceau.split(":", 1)[0].strip().lower().replace(" ", "_")
        if cle not in CHAMPS_MULTIPLES:
            return False
    return True



def charger(source: Path = SOURCE) -> dict[str, dict[str, Any]]:
    """Retourne les entrées indexées. Les doublons sont une erreur bloquante."""
    lignes = source.read_text(encoding="utf-8").splitlines()
    entrees: dict[str, dict[str, Any]] = {}
    courante: dict[str, Any] | None = None
    champ = None
    for numero, ligne in enumerate(lignes, 1):
        match = ENTETE.match(ligne)
        if match:
            identifiant, nom = match.groups()
            if identifiant in entrees:
                raise ValueError(f"Identifiant de contrainte en double : {identifiant}")
            courante = {"id": identifiant, "nom": nom.strip(), "ligne": numero}
            entrees[identifiant] = courante
            champ = None
            continue
        if ligne.startswith("## "):
            # Une section hors entree ferme l'entree courante : sinon ses puces
            # de bas de page se collent a la derniere contrainte lue.
            courante = None
            champ = None
            continue
        if courante is None or not ligne.startswith("-"):
            continue
        contenu = ligne[1:].strip()
        if ":" in contenu:
            # Une ligne peut porter plusieurs champs separes par une barre verticale,
            # par exemple : famille, impose par, confiance, juridiction, contributeur.
            morceaux = [m.strip() for m in contenu.split("|")] if _multichamp(contenu) else [contenu]
            for morceau in morceaux:
                if ":" not in morceau:
                    continue
                cle, valeur = morceau.split(":", 1)
                champ = cle.strip().lower().replace(" ", "_")
                courante[champ] = valeur.strip()
        elif champ:
            courante[champ] = str(courante.get(champ, "")) + " " + contenu
    if not entrees:
        raise ValueError("Catalogue vide ou format inconnu")
    return entrees


def empreinte(source: Path = SOURCE) -> str:
    return hashlib.sha256(source.read_bytes()).hexdigest()


def resume(source: Path = SOURCE) -> dict[str, Any]:
    entrees = charger(source)
    return {"source": str(source.relative_to(RACINE)), "empreinte": empreinte(source),
            "nombre_entrees": len(entrees)}


def selectionner(identifiants: list[str], source: Path = SOURCE) -> list[dict[str, Any]]:
    """Prépare des contraintes à revoir, sans les déclarer applicables."""
    entrees = charger(source)
    resultat = []
    for identifiant in identifiants:
        if identifiant not in entrees:
            raise ValueError(f"Contrainte inconnue : {identifiant}")
        entree = entrees[identifiant]
        resultat.append({
            "id": identifiant,
            "nom": entree["nom"],
            "statut": "a_revoir",
            "source": entree.get("source", ""),
            "confiance": entree.get("confiance", "a_verifier"),
            "ligne_catalogue": entree["ligne"],
            "empreinte_catalogue": empreinte(source),
        })
    return resultat


def personnalisees(entrees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Valide les contraintes de l'ingénieur sans les faire passer pour une loi."""
    resultat = []
    for position, entree in enumerate(entrees, 1):
        if not isinstance(entree, dict):
            raise ValueError(f"Contrainte personnalisée {position} invalide.")
        nom = str(entree.get("nom", "")).strip()
        forme = str(entree.get("forme_mesurable", "")).strip()
        source = str(entree.get("source", "")).strip()
        consequence = str(entree.get("consequence", "")).strip()
        confiance = str(entree.get("confiance", "a_verifier")).strip()
        if not nom or not forme or not source or not consequence:
            raise ValueError("Une contrainte personnalisée doit préciser nom, règle mesurable, source et conséquence.")
        if confiance not in {"verifie", "a_verifier", "temoignage", "hypothese"}:
            raise ValueError("Confiance personnalisée invalide.")
        brut = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().upper()
        suffixe = re.sub(r"[^A-Z0-9]+", "-", brut).strip("-")[:32] or f"REGLE-{position}"
        resultat.append({
            "id": f"CUSTOM-{suffixe}-{position:02d}",
            "nom": nom,
            "forme_mesurable": forme,
            "source": source,
            "consequence": consequence,
            "confiance": confiance,
            "statut": "a_revoir",
            "origine": "ingenieur",
        })
    return resultat


def exporter(destination: Path | None = None, source: Path = SOURCE) -> Path:
    """Ecrit le catalogue en JSON pour que le code le lise sans reparser le Markdown.

    L'export ne transforme rien : il ajoute seulement l'empreinte du fichier source
    et la date de generation, pour qu'un resultat puisse citer la version exacte
    du catalogue sur laquelle il a ete produit.
    """
    import json
    from datetime import datetime, timezone

    destination = destination or (RACINE / "docs" / "contraintes" / "catalogue.json")
    entrees = charger(source)
    sans_juridiction = sorted(i for i, e in entrees.items() if not e.get("juridiction"))
    contenu = {
        "source": str(source.relative_to(RACINE)),
        "empreinte_source": empreinte(source),
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nombre_entrees": len(entrees),
        "entrees_sans_juridiction": sans_juridiction,
        "entrees": entrees,
    }
    destination.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")
    return destination
