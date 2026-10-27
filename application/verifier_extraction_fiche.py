"""Contrôle de l'extraction de fiche, sans appel payant : réponses du modèle simulées sur le texte
réel du modèle de facture Stedin (archivé dans docs/contraintes/terrain/brut).

Une bonne réponse est acceptée ; une citation déplacée, un nombre absent de la ligne, une nature
hors vocabulaire sont refusés ; la période « maart 2018 » devient 2018-03-01 / 2018-03-31 ; le
total kWh est calculé par le programme ; le modèle est signalé par le programme même si le LLM se tait.
"""
import sys
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import extraction_fiche as ef  # noqa: E402

BRUT = ICI.parent / "docs/contraintes/terrain/brut"
texte = next(BRUT.glob("www_stedin_net_*stedin_voorbeeld.txt")).read_text(encoding="utf-8")
documents = [{"nom": "Stedin, Voorbeeldnota met toelichting", "texte": texte}]
index = ef.indexer(documents)
echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    def repere(contenu):
        return next(r for r, t in index.items() if contenu in t)


    def reponse(**remplacements):
        champs = {c: None for c in ef.CHAMPS}
        preuves = {c: [] for c in ef.CHAMPS}
        base = {"gtv_declare_kw": (347, "Gecontracteerd transportvermogen 31/31 maa 347 kW"),
                "kwmax_facture": (344, "Afgenomen belasting 31/31 maa 344 kW"),
                "kwh_afname_laag": (50137, "31-03-2018 Verbruik laag 50.137 kWh laag"),
                "kwh_afname_hoog": (46155, "31-03-2018 Verbruik normaal 46.155 kWh normaal"),
                "verbruiksperiode": ("maart 2018", "Periode maart 2018")}
        base.update(remplacements)
        for champ, (valeur, ligne) in base.items():
            champs[champ] = valeur
            preuves[champ] = [{"repere": repere(ligne) if ligne in texte.replace("  ", " ") or any(
                ligne in t for t in index.values()) else "D1:L9999", "citation": ligne}]
        return {"resume": "", "champs": champs, "preuves": preuves, "alertes": []}


    r = ef.controler(reponse(), documents, index)
    v = r["valeurs"]
    verifier(v["gtv_declare_kw"]["valeur"] == 347 and v["kwmax_facture"]["valeur"] == 344, "GTV 347 et kWmax 344 acceptés")
    verifier(v["kwh_facture"]["valeur"] == 96292, "kWh du mois calculé par le programme : 50 137 + 46 155 = 96 292")
    verifier(v["periode_facture_debut"]["valeur"] == "2018-03-01" and v["periode_facture_fin"]["valeur"] == "2018-03-31",
             "« maart 2018 » converti en 2018-03-01 / 2018-03-31")
    verifier("D1:L" in v["gtv_declare_kw"]["source_document"], "chaque valeur garde son repère et sa citation")
    verifier("document_generique" in r["alertes"], "modèle signalé par le programme alors que le LLM s'est tu")

    r = ef.controler(reponse(kwmax_facture=(331, "Afgenomen belasting 31/31 maa 344 kW")), documents, index)
    verifier("kwmax_facture" not in r["valeurs"] and "absent" in r["refus"]["kwmax_facture"],
             "331 kW (mois précédent) cité sur la ligne de mars : refusé")

    r = ef.controler(reponse(gtv_declare_kw=(347, "Gecontracteerd transportvermogen 347 kW, ligne inventée")), documents, index)
    verifier("gtv_declare_kw" not in r["valeurs"], "citation inventée : refusée")

    r = ef.controler(reponse(type_transportrecht=("flexibel", "Periode maart 2018")), documents, index)
    verifier("type_transportrecht" not in r["valeurs"] and "vocabulaire" in r["refus"]["type_transportrecht"],
             "nature de droit hors vocabulaire : refusée")

    ato = [{"nom": "ATO de test", "texte": "2.2 Transport voor afname is toegestaan in het tijdsblok van 22:00 tot 06:00 uur.\n"}]
    ia = ef.indexer(ato)
    rep = {"resume": "", "alertes": [], "champs": {c: None for c in ef.CHAMPS}, "preuves": {c: [] for c in ef.CHAMPS}}
    rep["champs"]["blocs_transport"] = "22:00-06:00"
    rep["preuves"]["blocs_transport"] = [{"repere": "D1:L1", "citation": "tijdsblok van 22:00 tot 06:00 uur"}]
    verifier(ef.controler(rep, ato, ia)["valeurs"].get("blocs_transport", {}).get("valeur") == "22:00-06:00",
             "blocs « 22:00-06:00 » acceptés contre « van 22:00 tot 06:00 uur »")
    rep["champs"]["blocs_transport"] = "20:00-06:00"
    verifier("blocs_transport" not in ef.controler(rep, ato, ia)["valeurs"], "heure absente de la ligne (20:00) : refusée")

    verifier(ef._nombres_nl("TOTAAL 1.590,96") == [1590.96] and ef._nombres_nl("Max 344 kW") == [344.0],
             "format néerlandais : « 1.590,96 » = 1590,96")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
