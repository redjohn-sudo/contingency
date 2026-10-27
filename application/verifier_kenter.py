"""Vérifie le lecteur Kenter contre le format publié dans la Handleiding Meetdata API v1.5.

1. L'exemple du manuel (p. 25) : 90 kWh dans un quart d'heure = 360 kW pour le netbeheerder.
2. Aller-retour : l'export de l'exemple (Voorbeeld BV, août 2026) mis au format Kenter
   (Unix UTC, fin de période, kWh par quart), relu, doit redonner exactement le même profil,
   puis produire le rapport complet avec le kWmax pris dans le canal 18160.
3. Refus : statut Invalid, canal 16180 absent (10180 seul), trou dans les quarts.
"""
import csv
import json
import sys
import unittest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import diagnostic  # noqa: E402
import lecteur_kenter  # noqa: E402

EXEMPLE = ICI.parent / "exemple-rapport"
echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    def canal(ident, mesures):
        return {"channelId": ident, "Measurements": mesures}


    def mesure(t, valeur, origin="Measured", status="Valid"):
        return {"origin": origin, "status": status, "timestamp": int(t), "value": valeur}


    # 1. Exemple du manuel, p. 25
    t0 = int(datetime.fromisoformat("2026-03-02T07:15:00+01:00").timestamp())
    lu = lecteur_kenter.lire_kenter([canal("16180", [mesure(t0, 90.0)])])
    verifier(lu["csv"].splitlines()[1] == "2026-03-02T07:15:00+01:00,360", "90 kWh par quart = 360 kW (exemple p. 25)")

    # 2. Aller-retour sur l'export de l'exemple
    with (EXEMPLE / "export-kwartierwaarden.csv").open(encoding="utf-8") as fichier:
        lignes = list(csv.DictReader(fichier))
    quarts = [mesure(datetime.fromisoformat(l["fin_intervalle"]).timestamp(), float(l["puissance_kw"]) / 4)
              for l in lignes]
    fin_mois = datetime.fromisoformat(lignes[-1]["fin_intervalle"]) - timedelta(minutes=15)
    pic = max(float(l["puissance_kw"]) for l in lignes)
    reponse = [canal("16180", quarts), canal("16280", [dict(m, value=0.0) for m in quarts]),
               canal("18160", [mesure(fin_mois.timestamp(), pic)])]
    lu = lecteur_kenter.lire_kenter(json.dumps(reponse))
    relu = list(csv.DictReader(lu["csv"].splitlines()))
    verifier(len(relu) == len(lignes), f"{len(lignes)} quarts relus")
    verifier(all(abs(float(a["puissance_kw"]) - float(b["puissance_kw"])) < 1e-6
                 and datetime.fromisoformat(a["fin_intervalle"]) == datetime.fromisoformat(b["fin_intervalle"])
                 for a, b in zip(relu, lignes)), "profil identique à l'export d'origine (heure et kW)")
    verifier(lu["kwmax_facture_par_mois"] == {"2026-08": pic}, f"kWmax facturé d'août lu sur 18160 : {pic} kW")

    fiche = json.loads((EXEMPLE / "fiche.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        export = Path(tmp) / "kenter.csv"
        export.write_text(lu["csv"], encoding="utf-8")
        fiche["export_profil"] = str(export)
        fiche["valeurs"]["unite_profil"] = {"valeur": lu["unite"], "source_document": lu["source"]}
        fiche["valeurs"]["kwmax_facture"] = {"valeur": lu["kwmax_facture_par_mois"]["2026-08"],
                                              "source_document": "Kenter, canal 18160 (piekvermogen tbv facturatie)"}
        texte = diagnostic.produire(fiche, Path(tmp) / "sortie").with_name("rapport.txt").read_text(encoding="utf-8")
    verifier("Unité confirmée" in texte, "rapport produit, unité confirmée par le kWmax du canal 18160")

    # 2 bis. Mois avec passage à l'heure d'été (29 mars 2026 : 92 quarts ce jour-là)
    debut_mars = datetime.fromisoformat("2026-03-01T00:00:00+01:00").timestamp()
    fin_mars = datetime.fromisoformat("2026-04-01T00:00:00+02:00").timestamp()
    n = int((fin_mars - debut_mars) // 900)
    mars = [mesure(debut_mars + 900 * (i + 1), 25.0 if i % 96 else 30.0) for i in range(n)]
    lu = lecteur_kenter.lire_kenter([canal("16180", mars), canal("18160", [mesure(fin_mars - 86400, 120.0)])])
    fiche_mars = json.loads((EXEMPLE / "fiche.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        export = Path(tmp) / "mars.csv"
        export.write_text(lu["csv"], encoding="utf-8")
        fiche_mars["export_profil"] = str(export)
        for champ, valeur in (("unite_profil", "kw"), ("kwmax_facture", lu["kwmax_facture_par_mois"]["2026-03"]),
                              ("kwh_facture", round(sum(m["value"] for m in mars))),
                              ("periode_facture_debut", "2026-03-01"), ("periode_facture_fin", "2026-03-31")):
            fiche_mars["valeurs"][champ] = {"valeur": valeur, "source_document": "test heure d'été"}
        try:
            texte = diagnostic.produire(fiche_mars, Path(tmp) / "s").with_name("rapport.txt").read_text(encoding="utf-8")
            verifier("Unité confirmée" in texte and "COH-PERIODE" in texte,
                     f"mars 2026 lu ({n} quarts, jour de 92) et rapport produit")
        except SystemExit as erreur:
            verifier(False, f"mars 2026 refusé : {erreur}")

    # 3. Refus
    for nom, rep in (("statut Invalid", [canal("16180", [mesure(t0, 1.0, status="Invalid")])]),
                     ("canal 10180 seul", [canal("10180", [mesure(t0, 1.0)])]),
                     ("trou d'un quart", [canal("16180", [mesure(t0, 1.0), mesure(t0 + 1800, 1.0)])])):
        try:
            lecteur_kenter.lire_kenter(rep)
            verifier(False, f"refus : {nom}")
        except ValueError as erreur:
            verifier(True, f"refus : {nom} ({str(erreur)[:60]}…)")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
