"""Le rapport néerlandais ne laisse passer aucune phrase française et reprend les chiffres du moteur."""
import html
import json
import re
import sys
import tempfile
from pathlib import Path

import controles
import rapport_controles
import rapport_nl

EXEMPLE = Path(__file__).resolve().parent.parent / "exemple-rapport"
FRANCAIS = ["contrôle", "établi", "pièce", "capacité", "facturé", "évaluable", "fournir", "source :",
            "lu le", "période", "puissance", "règle", "gestionnaire", " le ", " la ", " les ", " des ",
            " du ", " une ", " est ", " pour ", " sur ", " avec ", " et ", " à ", "confiance"]


def texte(dossier):
    rapport = rapport_controles.composer(dossier, controles.executer_tous(dossier))
    return html.unescape(re.sub(r"<[^>]+>", " ", rapport_nl.en_html(rapport, "Test BV")))


def dossier_exemple():
    import diagnostic
    fiche = json.loads((EXEMPLE / "fiche.json").read_text())
    d = {c: e["valeur"] for c, e in fiche["valeurs"].items() if e.get("valeur") not in (None, "")}
    d["profil_brut"], d["profil_horodatages"] = diagnostic.lire_profil(EXEMPLE / fiche["export_profil"], None)
    return d


def main():
    echecs = []
    cas = {"complet": dossier_exemple()}
    cas["sans_facture"] = {k: v for k, v in cas["complet"].items() if k not in ("kwmax_facture", "kwh_facture")}
    faux = dict(cas["complet"]); faux["kwmax_facture"] = round(max(faux["profil_brut"]) * 4)
    cas["unite_fausse"] = faux
    cas["vide"] = {}
    for nom, dossier in cas.items():
        t = texte(dossier)
        fuites = [m for m in FRANCAIS if m in t]
        if fuites:
            echecs.append(f"{nom} : français détecté {fuites}")
    t = texte(cas["complet"])
    for attendu in ("92,8 kW", "207,2 kW", "63.135 kWh", "340,0 kW", "Liander", "01-08-2026"):
        if attendu not in t:
            echecs.append(f"complet : « {attendu} » absent")
    if "Metingen niet bevestigd" not in texte(cas["unite_fausse"]):
        echecs.append("unite_fausse : l'alerte sur les mesures manque")
    if "Aan te leveren" not in texte(cas["sans_facture"]):
        echecs.append("sans_facture : les pièces manquantes ne sont pas demandées")
    print(f"{8 - len(echecs)}/8 contrôles passés." if not echecs else "\n".join(echecs))
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
