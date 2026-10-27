"""CTRL-TRANSPORTRECHT (REG-003, REG-004, REG-005) : nature du droit de transport lue dans l'ATO.

Ferme, non ferme, lié à la durée (85 % des heures) et par blocs horaires, avec un bloc qui passe
minuit, une consommation hors bloc détectée au quart d'heure près, une nature inventée refusée,
et le rendu néerlandais.
"""
import json
import sys
import unittest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import controles  # noqa: E402
import diagnostic  # noqa: E402

droit = controles.REGISTRE["CTRL-TRANSPORTRECHT"]["fonction"]
echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    verifier(droit({"type_transportrecht": "vast"})["statut"] == "constat", "droit ferme : constat")
    verifier(droit({"type_transportrecht": "non_firm"})["statut"] == "alerte", "non ferme : alerte (REG-003)")
    r = droit({"type_transportrecht": "tijdsduurgebonden"})
    verifier(r["statut"] == "alerte" and round(r["valeurs"]["heures_coupables"]) == 1314,
             "lié à la durée : 1 314 heures coupables sur 8 760 (REG-004)")
    verifier(droit({"type_transportrecht": "flexibel"})["statut"] == "bloque", "nature inventée : refusée")

    # Une journée : bloc 22:00-06:00 (passe minuit), 50 kW partout sauf 08:00-08:15 à 80 kW.
    debut = datetime.fromisoformat("2026-08-01T00:00:00+02:00")
    horodatages = [(debut + timedelta(minutes=15 * (i + 1))).isoformat() for i in range(96)]
    profil = [80.0 if i == 32 else (50.0 if i < 24 or i >= 88 else 0.0) for i in range(96)]
    r = droit({"type_transportrecht": "tijdsblok", "blocs_transport": "22:00-06:00", "gtv_hors_bloc_kw": 0,
               "profil_kw": profil, "profil_horodatages": horodatages})
    verifier(r["valeurs"]["quarts_hors_bloc_au_dessus"] == 1 and r["valeurs"]["pointe_hors_bloc_kw"] == 80.0,
             "bloc de nuit 22:00-06:00 : seul le quart de 08:00 est hors bloc (REG-005)")
    r = droit({"type_transportrecht": "tijdsblok", "blocs_transport": "22:00-06:00", "gtv_hors_bloc_kw": 100,
               "profil_kw": profil, "profil_horodatages": horodatages})
    verifier(r["statut"] == "constat", "80 kW sous les 100 kW autorisés hors bloc : conforme")
    verifier(droit({"type_transportrecht": "tijdsblok", "blocs_transport": "nuit", "profil_kw": profil,
                    "profil_horodatages": horodatages})["statut"] == "bloque", "blocs illisibles : refusés")

    fiche = json.loads((ICI.parent / "exemple-rapport" / "fiche.json").read_text(encoding="utf-8"))
    fiche["export_profil"] = str(ICI.parent / "exemple-rapport" / "export-kwartierwaarden.csv")
    for champ, valeur in (("type_transportrecht", "tijdsblok"), ("blocs_transport", "07:00-19:00"),
                          ("gtv_hors_bloc_kw", 100)):
        fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "ATO, test"}
    with tempfile.TemporaryDirectory() as tmp:
        diagnostic.produire(fiche, Path(tmp))
        nl = (Path(tmp) / "rapport-nl.html").read_text(encoding="utf-8")
    verifier("Transportrecht in tijdsblokken (07:00-19:00)" in nl, "rapport néerlandais : droit par blocs rendu")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
