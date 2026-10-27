"""Dossier client (dossier_client.py) : une fiche du diagnostic, l'export VEA 2708 de 2016, diagnostic et scan.

La facture fictive est celle de janvier 2016, le mois de la pointe annuelle (595 kW le 05/01). fiche_juin
prend une facture de juin (pointe 421 kW) : l'unité se confirme sur juin, mais la marge du diagnostic et
celle du scan se lisent toutes deux sur l'année entière.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import diagnostic  # noqa: E402
import dossier_client  # noqa: E402
import scan_flex  # noqa: E402

EXPORT = ICI.parent / "docs" / "exemples" / "scan-flex" / "vea-2708-2016.csv"


def fiche_remplie() -> dict:
    fiche = diagnostic.modele("liander")
    fiche["client"] = "Locatie VEA 2708 (voorbeeld)"
    for champ, valeur, source in (
            ("gtv_kw", 700, "ATO p. 3, « Gecontracteerd transportvermogen 700 kW »"),
            ("capacite_aansluiting_kva", 1000, "ATO p. 1, « Aansluitcapaciteit 1000 kVA »"),
            ("gtv_declare_kw", 700, "facture de janvier 2016, « Gecontracteerd transportverm. 700 »"),
            ("kwmax_facture", 595, "facture de janvier 2016, « Maximale belasting 595 KW »"),
            ("kwh_facture", 178278.5, "facture de janvier 2016, afn. laag + afn. hoog"),
            ("periode_facture_debut", "2016-01-01", "facture de janvier 2016, Verbruiksperiode"),
            ("periode_facture_fin", "2016-01-31", "facture de janvier 2016, Verbruiksperiode"),
            ("mesure_au_point_de_livraison", True, "ATO p. 2, meetpunt = overdrachtspunt"),
            ("commune", "Apeldoorn", "ATO p. 1, adresse"),
            ("unite_profil", "kw", "en-tête de l'export : puissance_kw"),
            ("meetbedrijf", "meetbedrijf (voorbeeld)", "facture, Meetverantwoordelijke"),
            ("prix_scan_eur", 2500, "devis Contingency du 27/09/2026")):
        fiche["valeurs"][champ] = {"valeur": valeur, "source_document": source}
    fiche["valeurs"]["ean"] = {"valeur": "871687400000000000", "source_document": "ATO p. 1, EAN-code"}
    return fiche


def fiche_juin() -> dict:
    """Facture de juin 2016 : pointe du mois 421 kW, loin de la pointe annuelle (595 kW le 05/01)."""
    fiche = fiche_remplie()
    for champ, valeur in (("kwmax_facture", 421), ("kwh_facture", 118171.2),
                          ("periode_facture_debut", "2016-06-01"), ("periode_facture_fin", "2016-06-30")):
        fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "facture de juin 2016"}
    return fiche


class DossierClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.sortie = Path(cls._tmp.name) / "sortie"
        cls.index = dossier_client.produire(fiche_remplie(), EXPORT, cls.sortie)
        cls.scan = json.loads((cls.sortie / "scan.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_gtv_present_dans_le_scan(self):
        self.assertEqual(self.scan["raccordement"]["gtv_kw"], 700)
        self.assertEqual(self.scan["marge_gtv"]["kw"]["valeur"], 105)
        self.assertEqual(self.scan["raccordement"]["gestionnaire_nature"], "declare")
        self.assertEqual(self.scan["site"]["nom"], "Locatie VEA 2708 (voorbeeld)")

    def test_meme_pointe_diagnostic_et_scan(self):
        d, s = self.index["diagnostic"], self.index["scan"]
        self.assertTrue(d["puissance_fiable"])
        self.assertEqual(d["pointe_periode_facturee_kw"], 595)
        self.assertEqual(s["pointe_periode_facturee_kw"], d["pointe_periode_facturee_kw"])
        self.assertEqual(s["pointe_kw"], 595)
        self.assertEqual(self.index["profil"]["quarts_periode_facturee"], 31 * 96)
        self.assertEqual({r["id"]: r["statut"] for r in d["controles"]}["COH-PERIODE"], "constat")

    def test_index_complet(self):
        fichiers = {f["fichier"] for f in self.index["fichiers"]}
        self.assertEqual(fichiers, {"rapport.html", "rapport.txt", "rapport-nl.html", "scan.json",
                                    "rapport-flex.html", "rapport-flex-nl.html", "index.json"})
        for f in fichiers:
            self.assertTrue((self.sortie / f).is_file(), f)
        self.assertIn("monetisation", self.scan)
        valeurs = {v["champ"]: v for v in self.index["valeurs"]}
        self.assertIn("Gecontracteerd transportvermogen 700", valeurs["scan.gtv_kw"]["source"])
        self.assertEqual(valeurs["gtv_kw"]["lu_par"], ["diagnostic", "scan"])
        self.assertEqual(valeurs["kwh_facture"]["lu_par"], ["diagnostic"])
        self.assertTrue(all(v["source"] for v in self.index["valeurs"]))
        md = (self.sortie / "index.md").read_text(encoding="utf-8")
        self.assertIn("# Klantdossier", md)
        self.assertIn("# Dossier client", md)

    def test_champ_manquant_signale(self):
        manquants = {m["champ"] for m in self.index["manquants"]}
        self.assertIn("categorie_tarifaire", manquants)
        self.assertIn("cout_etude_eur", manquants)
        self.assertNotIn("prix_scan_eur", manquants)
        self.assertIn("categorie_tarifaire", (self.sortie / "index.md").read_text(encoding="utf-8"))

    def test_source_du_gabarit_signalee(self):
        fiche = fiche_remplie()
        fiche["valeurs"]["commune"]["source_document"] = diagnostic.CHAMPS_FICHE["commune"][0]
        with tempfile.TemporaryDirectory() as d:
            index = dossier_client.produire(fiche, EXPORT, Path(d))
        self.assertTrue({v["champ"]: v for v in index["valeurs"]}["commune"]["source_gabarit"])

    def test_valeur_illisible_refusee_avec_son_nom(self):
        for champ, valeur, nom in (("gtv_kw", "700", "gtv_kw"), ("prix_scan_eur", 0, "prix_scan_eur"),
                                   ("gestionnaire", "westland", "gestionnaire"),
                                   ("categorie_tarifaire", "HS", "categorie_tarifaire"),
                                   ("plafond_cible", 400, "plafond_cible")):
            fiche = fiche_remplie()
            fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "pièce"}
            with self.assertRaises(ValueError, msg=champ) as refus:
                dossier_client.fiche_plate(fiche)
            self.assertIn(nom, str(refus.exception))
        with tempfile.TemporaryDirectory() as d:  # refus avant toute écriture
            fiche["valeurs"]["gtv_kw"]["valeur"] = "700"
            with self.assertRaises(ValueError):
                dossier_client.produire(fiche, EXPORT, Path(d) / "s")
            self.assertFalse((Path(d) / "s").exists())

    def test_gtv_divergent_non_confirme_jamais_repris(self):
        fiche = fiche_remplie()
        fiche["valeurs"]["gtv_declare_kw"]["valeur"] = 650
        plate, _, manquants = dossier_client.fiche_plate(fiche)
        self.assertNotIn("gtv_kw", plate)
        self.assertIn("bloquée", next(m for m in manquants if m["champ"] == "gtv_kw")["ou_le_trouver"])

    def test_dossier_reutilise_sans_ancien_scan(self):
        """Audit Astra n°1 : un dossier refait dans le même répertoire, scan refusé, ne garde ni n'annonce
        le scan ou le PDF d'une production précédente."""
        with tempfile.TemporaryDirectory() as d:
            sortie = Path(d)
            fiche = fiche_remplie()
            self.assertTrue(dossier_client.produire(fiche, EXPORT, sortie)["scan"]["produit"])
            (sortie / "rapport-flex.pdf").write_text("ancien PDF", encoding="utf-8")
            fiche["valeurs"]["unite_profil"]["valeur"] = "kwh"
            index = dossier_client.produire(fiche, EXPORT, sortie)
            self.assertFalse(index["scan"]["produit"])
            anciens = {"scan.json", "rapport-flex.html", "rapport-flex-nl.html", "rapport-flex.pdf"}
            self.assertFalse(anciens & {f["fichier"] for f in index["fichiers"]})
            self.assertFalse([f for f in anciens if (sortie / f).exists()])
            self.assertEqual(json.loads((sortie / "index.json").read_text(encoding="utf-8"))["fichiers"], index["fichiers"])

    def test_une_seule_marge_diagnostic_et_scan(self):
        """Audit Opus n°4 : facture de juin, pointe annuelle en janvier. L'unité se confirme sur juin ; la marge
        du diagnostic se lit, comme celle du scan, sur tout l'export : une seule pointe, une seule marge."""
        with tempfile.TemporaryDirectory() as d:
            index = dossier_client.produire(fiche_juin(), EXPORT, Path(d))
            nl = (Path(d) / "rapport-nl.html").read_text(encoding="utf-8")
        self.assertEqual(index["diagnostic"]["pointe_periode_facturee_kw"], 421)
        self.assertEqual(index["scan"]["marge_gtv"]["kw"]["valeur"], 105)
        marge = next(c for c in index["diagnostic"]["controles"] if c["id"] == "CTRL-MARGE")
        self.assertIn("du profil 595.0 kW", marge["constat"])
        self.assertIn("Ruimte binnen het huidige contract: 105,0 kW", nl)
        self.assertIn("Profiel van 35136 kwartierwaarden, hoogste waarde 595,0 kW", nl)
        self.assertNotIn("279,0 kW", nl)

    def test_droit_non_ferme_refuse_par_le_scan(self):
        """Audit Opus n°5 : le scan suppose un GTV ferme toute l'année. Il reçoit la nature du droit de transport
        et refuse en la nommant un droit par blocs, lié à la durée ou non ferme, au lieu d'annoncer une marge."""
        for nature in ("tijdsblok", "non_firm", "tijdsduurgebonden", "vast"):
            fiche = fiche_remplie()
            fiche["valeurs"]["type_transportrecht"] = {"valeur": nature, "source_document": "ATO p. 2"}
            if nature == "tijdsblok":
                for champ, valeur in (("blocs_transport", "22:00-06:00"), ("gtv_hors_bloc_kw", 0)):
                    fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "ATO p. 2"}
            with tempfile.TemporaryDirectory() as d:
                index = dossier_client.produire(fiche, EXPORT, Path(d))
                scan_ecrit = (Path(d) / "scan.json").exists()
            self.assertEqual(index["scan"]["produit"], nature == "vast", nature)
            self.assertEqual(scan_ecrit, nature == "vast", nature)
            if nature == "vast":
                lu = {v["champ"]: v["lu_par"] for v in index["valeurs"]}
                self.assertEqual(lu["type_transportrecht"], ["diagnostic", "scan"])
            else:
                self.assertIn(f"« {nature} »", index["scan"]["motif"])
        kw, fins = scan_flex.lire_csv(EXPORT)
        for fiche in ({"type_transportrecht": "non_firm"}, {"blocs_transport": "22:00-06:00"}):
            with self.assertRaises(ValueError, msg=fiche) as refus:
                scan_flex.scanner(kw, fins, {"gtv_kw": 700, **fiche})
            self.assertIn("GTV ferme", str(refus.exception))

    def test_gtv_confirme_lu_sur_la_facture(self):
        """Audit Opus n°12 : ATO 650 kW, facture 700 kW confirmée. Le scan lit la facture : l'index marque
        gtv_declare_kw lu par le scan, pas la ligne de l'ATO."""
        fiche = fiche_remplie()
        fiche["valeurs"]["gtv_kw"]["valeur"] = 650
        fiche["valeurs"]["confirmation_gtv_declare"] = {"valeur": {
            "valeur_kw": 700, "confirme_actuel": True, "source_document": "facture de janvier 2016",
            "verifie_par": "lecteur de test", "date_document": "2016-02-05", "date_verification": "2026-09-27"},
            "source_document": "facture de janvier 2016, relue le 27/09/2026"}
        with tempfile.TemporaryDirectory() as d:
            index = dossier_client.produire(fiche, EXPORT, Path(d))
        self.assertEqual(index["scan"]["gtv_kw"], 700)
        lu = {v["champ"]: v["lu_par"] for v in index["valeurs"]}
        self.assertEqual(lu["gtv_declare_kw"], ["diagnostic", "scan"])
        self.assertEqual(lu["gtv_kw"], ["diagnostic"])

    def test_champs_communaux_acceptes(self):
        """Audit Astra n°7 : les conditions de champ lues par champ_communal.py sont acceptées, et lues par le
        diagnostic ; la liste suit la documentation du module."""
        import re
        import champ_communal
        documentes = set(re.findall(r"^- ``(\w+)``", champ_communal.__doc__, re.M))
        self.assertIn("couplee_parc_pv", documentes)
        self.assertTrue(documentes <= dossier_client.CONNUS, documentes - dossier_client.CONNUS)
        fiche = fiche_remplie()
        for champ, valeur in (("soumis_a_permis", True), ("conforme_plan_temporaire", True), ("zone_nommee", "Weststad"),
                              ("regime_lieu", "bedrijfsmatig"), ("grootschalig", True), ("couplee_parc_pv", True)):
            fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "pièce contrôlée"}
        dossier_client.fiche_plate(fiche)
        with tempfile.TemporaryDirectory() as d:
            index = dossier_client.produire(fiche, EXPORT, Path(d))
        lu = {v["champ"]: v["lu_par"] for v in index["valeurs"]}
        self.assertEqual(lu["soumis_a_permis"], ["diagnostic"])

    def test_scan_recoit_toute_l_annee(self):
        """Audit Opus n°24 : facture de janvier (mois de la pointe), le scan lit pourtant toute l'année 2016 :
        un scan limité au mois facturé ferait échouer ce test."""
        with tempfile.TemporaryDirectory() as d:
            dossier_client.produire(fiche_remplie(), EXPORT, Path(d))
            scan = json.loads((Path(d) / "scan.json").read_text(encoding="utf-8"))
        self.assertEqual(scan["statistiques"]["quarts"], 366 * 96)

    def test_periode_non_couverte_dite_dans_l_index(self):
        """Audit Opus n°23 : facture de 2017 sur un export de 2016 : 0 quart dans la période, pas 35 136."""
        fiche = fiche_remplie()
        fiche["valeurs"]["periode_facture_debut"]["valeur"] = "2017-01-01"
        fiche["valeurs"]["periode_facture_fin"]["valeur"] = "2017-01-31"
        with tempfile.TemporaryDirectory() as d:
            index = dossier_client.produire(fiche, EXPORT, Path(d))
        self.assertEqual(index["profil"]["quarts_periode_facturee"], 0)

    def test_titre_protege(self):
        """Audit Astra n°9 : un nom de client sur plusieurs lignes ne crée pas de section dans l'index."""
        texte = dossier_client.en_markdown({"client": "Client\n\n## CONCLUSION VALIDEE",
                                            "profil": {"fichier": "a.csv\n## X", "quarts": 2, "quarts_periode_facturee": 2},
                                            "fichiers": [], "scan": {"produit": False}, "valeurs": [], "manquants": []})
        self.assertFalse(any(l.startswith("## CONCLUSION") or l.startswith("## X") for l in texte.splitlines()))

    def test_fiche_imbriquee_refusee_par_le_scan(self):
        kw, fins = scan_flex.lire_csv(EXPORT)
        for fiche in (fiche_remplie(), {"gtv_kw": {"valeur": 700, "source_document": "ATO"}}):
            with self.assertRaises(ValueError) as refus:
                scan_flex.scanner(kw, fins, fiche)
            self.assertIn("dossier_client.py", str(refus.exception))


if __name__ == "__main__":
    unittest.main()
