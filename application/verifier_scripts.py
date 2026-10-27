"""Scripts de vérification sans TestCase, rejoués dans la suite unittest (constat n°20 de la relecture du 27/09).

Chacun tourne en sous-processus et doit sortir avec le code 0. Les scripts qui demandent un navigateur ou des
données externes restent hors de la suite : voir « Vérifier localement » dans le README.
"""
import subprocess
import sys
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
SCRIPTS = ["verifier_diagnostic", "verifier_controles_contrat", "verifier_champ_communal", "verifier_rapport_nl"]


class Scripts(unittest.TestCase):
    def test_scripts(self):
        for nom in SCRIPTS:
            with self.subTest(nom):
                r = subprocess.run([sys.executable, f"{nom}.py"], cwd=ICI, capture_output=True, text=True, timeout=600)
                self.assertEqual(r.returncode, 0, f"{nom} : {r.stdout[-800:]}{r.stderr[-800:]}")


if __name__ == "__main__":
    unittest.main()
