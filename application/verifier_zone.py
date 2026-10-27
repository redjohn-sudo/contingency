"""CTRL-ZONE (RES-005, RES-006, RES-021) : état de la zone relevé sur la capaciteitskaart publique.

Vérifie les quatre statuts de la légende officielle, l'asymétrie afname / teruglevering,
le test à N + 4 d'une année de fin de congestion annoncée, le refus d'un statut inventé,
et le rendu néerlandais sans français.
"""
import json
import sys
import unittest
import tempfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import controles  # noqa: E402
import diagnostic  # noqa: E402

zone = controles.REGISTRE["CTRL-ZONE"]["fonction"]
echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    r = zone({"statut_zone_afname": "tekort", "statut_zone_teruglevering": "beschikbaar",
              "date_carte": "2026-09-25", "annee_liberation_annoncee": 2029})
    verifier(r["statut"] == "alerte", "afname en tekort : alerte")
    verifier(r["valeurs"]["asymetrique"], "afname tekort et teruglevering beschikbaar : asymétrie signalée (RES-006)")
    verifier(r["valeurs"]["annee_a_tester"] == 2033, "fin annoncée en 2029 : plan testé aussi en 2033 (RES-021)")

    r = zone({"statut_zone_afname": "beschikbaar", "statut_zone_teruglevering": "beschikbaar", "date_carte": "2026-09-25"})
    verifier(r["statut"] == "constat" and not r["valeurs"]["asymetrique"], "zone libre dans les deux sens : constat")

    r = zone({"statut_zone_afname": "a_evaluer", "statut_zone_teruglevering": "beschikbaar", "date_carte": "2026-09-27"})
    verifier(r["statut"] == "alerte" and r["valeurs"].get("non_evaluee") and "pas encore attribuée" in r["constat"],
             "cinquième statut de la légende (« Kleur wordt later toegevoegd ») : reconnu, aucune capacité supposée")
    import rapport_nl
    phrase, _ = rapport_nl._zin(r)
    verifier("Kleur nog niet toegekend" in phrase and "kleur wordt later toegevoegd" in phrase,
             "rapport néerlandais : zone non évaluée dite en néerlandais")

    r = zone({"statut_zone_afname": "rood", "statut_zone_teruglevering": "beschikbaar", "date_carte": "2026-09-25"})
    verifier(r["statut"] == "bloque", "statut hors légende (« rood ») : refusé, jamais interprété")

    fiche = json.loads((ICI.parent / "exemple-rapport" / "fiche.json").read_text(encoding="utf-8"))
    fiche["export_profil"] = str(ICI.parent / "exemple-rapport" / "export-kwartierwaarden.csv")
    for champ, valeur in (("statut_zone_afname", "onderzoek"), ("statut_zone_teruglevering", "beperkt"),
                          ("date_carte", "2026-09-25"), ("annee_liberation_annoncee", 2028)):
        fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "capaciteitskaart, test"}
    with tempfile.TemporaryDirectory() as tmp:
        diagnostic.produire(fiche, Path(tmp))
        nl = (Path(tmp) / "rapport-nl.html").read_text(encoding="utf-8")
    verifier("gebied is in onderzoek met wachtrij" in nl and "2032" in nl, "rapport néerlandais : statut et année N + 4 rendus")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
