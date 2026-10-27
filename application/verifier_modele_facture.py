"""Un modèle de facture est reconnu par le programme, sans compter sur le LLM.

Cas réel du 25/09 : sur la « Maandfactuur Netbeheer Elektra » officielle de Liander (un modèle),
DeepSeek a extrait 6/6 valeurs justes mais n'a pas levé document_generique.
Extrait fidèle des lignes du modèle (pdftotext -layout), sans rien d'autre.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import controle_documentaire as c  # noqa: E402

MODELE = """    Postbus 50, 6920 AB Duiven (PBC P100)
    Bedrijf
3   Verbruiksperiode:                xxxxx
    Maak het genoemde bedrag voor DD/MM/JJJJ over op IBAN nummer xxxx xxxx xxxx xxxx xx ten name van Alliander N.V.
11   Gecontracteerd transportvermogen:                  xxxxxxxxx
      Gecontracteerd transportverm.       500 KW                                €               2,02         €          1.010,00      21%
18    Maximale belasting                  400 KW                                €             2,8775         €          1.151,00      21%
"""
ANONYMISEE = """Liander N.V.   Factuurdatum: 02-09-2026
Verbruiksperiode: 01-08-2026 t/m 31-08-2026
EAN-code: 8716xxxxxxxxxx
Gecontracteerd transportverm.       300 KW
Maximale belasting                  207 KW
"""
echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    modele = [{"nom": "Maandfactuur Netbeheer Elektra", "texte": MODELE}]
    codes = [a["code"] for a in c.auditer_documents(modele)["anomalies"]]
    verifier(c.qualificatifs(modele[0])["generique"], "gabarit DD/MM/JJJJ : modèle reconnu comme générique")
    verifier("document_generique" in codes, "alerte document_generique levée par le programme")
    verifier("valeur_masquee" in codes, "valeurs xxxxx signalées comme masquées")

    stedin = [{"nom": "Maandfactuur", "texte": "Retouradres: postbus 49, 3000 AA Rotterdam\nVOORBEELDKLANT BV\n"
                                               "Voorbeeldstraat 1\nPeriode maart 2018\n"}]
    verifier(c.qualificatifs(stedin[0])["generique"], "modèle Stedin (VOORBEELDKLANT BV) reconnu comme générique")
    bijv = [{"nom": "Factuur", "texte": "Bijvoorbeeld bij teruglevering geldt een ander tarief.\nPeriode maart 2026\n"}]
    verifier(not c.qualificatifs(bijv[0])["generique"], "« bijvoorbeeld » dans une vraie facture : pas un modèle")

    vraie = [{"nom": "Factuur augustus 2026", "texte": ANONYMISEE}]
    codes = [a["code"] for a in c.auditer_documents(vraie)["anomalies"]]
    verifier(not c.qualificatifs(vraie[0])["generique"], "facture réelle anonymisée : PAS prise pour un modèle")
    verifier("valeur_masquee" in codes, "EAN anonymisé signalé comme masqué, sans bloquer la facture")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
