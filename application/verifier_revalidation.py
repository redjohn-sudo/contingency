import unittest

import catalogue
import controles
from revalidation import revalider


class RevalidationTest(unittest.TestCase):
    def dossier(self, empreinte=None):
        return {
            "profil": [100.0] * 96,
            "faits": {},
            "catalogue": {"empreinte": empreinte or catalogue.empreinte()},
            "gtv_kw": 150.0,
            "profil_kw": [100.0] * 96,
        }

    def test_archive_a_jour(self):
        resultat = revalider(self.dossier())
        self.assertEqual(resultat["statut"], "a_jour")
        self.assertEqual(resultat["empreinte_modifiee"], False)
        self.assertEqual(len(resultat["resultats"]), len(controles.REGISTRE))

    def test_catalogue_modifie_declenche_revalidation(self):
        resultat = revalider(self.dossier("ancienne-empreinte"))
        self.assertEqual(resultat["statut"], "a_revalider")
        self.assertTrue(resultat["empreinte_modifiee"])
        self.assertTrue(resultat["plan_de_deblocage"])

    def test_reformulation_separee_sans_fausse_alerte(self):
        dossier = self.dossier()
        anciens = controles.executer_tous({"profil_kw": dossier["profil_kw"], "gtv_kw": 150.0})
        anciens[0]["constat"] = "Même verdict, constat reformulé."
        resultat = revalider(dossier, anciens)
        self.assertEqual(resultat["statut"], "a_jour")
        self.assertEqual(resultat["changements"], [])
        self.assertEqual([r["id"] for r in resultat["reformulations"]], [anciens[0]["id"]])

    def test_controle_nouveau_est_signale(self):
        dossier = self.dossier()
        courants = controles.executer_tous({"profil_kw": dossier["profil_kw"], "gtv_kw": 150.0})
        self.assertEqual(len(courants), len(controles.REGISTRE))
        resultat = revalider(dossier, courants[:-1])
        nouveaux = [c for c in resultat["changements"] if c["type"] == "nouveau_controle"]
        self.assertEqual([c["id"] for c in nouveaux], [courants[-1]["id"]])
        self.assertEqual(resultat["statut"], "a_revalider")

    def test_controle_retire_est_signale(self):
        dossier = self.dossier()
        courants = controles.executer_tous({"profil_kw": dossier["profil_kw"], "gtv_kw": 150.0})
        anciens = courants + [{"id": "CTRL-RETIRE", "statut": "alerte", "valeurs": {}}]
        resultat = revalider(dossier, anciens)
        retires = [c for c in resultat["changements"] if c["type"] == "controle_retire"]
        self.assertEqual([c["id"] for c in retires], ["CTRL-RETIRE"])

    def test_changement_de_verdict_est_signale(self):
        dossier = self.dossier()
        anciens = controles.executer_tous({"profil_kw": dossier["profil_kw"], "gtv_kw": 150.0})
        anciens[0]["valeurs"]["marge_kw"] = 49.0
        resultat = revalider(dossier, anciens)
        changements = [c for c in resultat["changements"] if c["type"] == "verdict_change"]
        self.assertEqual([c["id"] for c in changements], [anciens[0]["id"]])

    def test_empreinte_absente_est_distinguee(self):
        resultat = revalider({"profil_kw": [100.0] * 96, "gtv_kw": 150.0})
        self.assertEqual(resultat["statut"], "a_revalider")
        self.assertTrue(resultat["empreinte_inconnue"])
        self.assertIsNone(resultat["empreinte_modifiee"])
        self.assertEqual(resultat["raison_catalogue"], "empreinte_archive_inconnue")


if __name__ == "__main__":
    unittest.main()
