"""Scan solaire (scan_solaire.py, rapport_solaire.py) : bilans connus d'avance avec une production de référence
synthétique (500 W par kWc de 10 h à 16 h UTC chaque jour, 0 sinon), puis le site VEA 2708 avec la référence PVGIS
Amsterdam, puis le rapport.

Charge constante de 100 kW, 100 kWc : 50 kW produits 6 h par jour, tout autoconsommé (109,5 MWh sur l'année 2025).
Charge constante de 30 kW, 100 kWc : 30 kW autoconsommés, 20 kW de surplus 6 h par jour (43,8 MWh) ; injection nulle :
tout écrêté ; limite 10 kW : la moitié injectée ; batterie de 200 kWh nominaux (180 utiles, 200 kW) : les 120 kWh de
surplus quotidiens entrent (113,8 kWh stockés au rendement √0,9), ressortent la nuit (108 kWh) : autoconsommation
totale 30 x 6 + 108 = 288 kWh par jour.
"""
import html
import json
import math
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import profil_france as pf  # noqa: E402
import rapport_solaire  # noqa: E402
import scan_solaire  # noqa: E402

EXEMPLE = ICI.parent / "docs" / "exemples" / "scan-solaire"
echecs = []
ETA = math.sqrt(0.9)


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def proche(a, b, tol=1.0):
    return a is not None and b is not None and abs(a - b) <= tol


def profil_constant(kw: float) -> dict:
    lignes = ["fin_intervalle,puissance_kw"]
    t = datetime(2025, 1, 1)
    for i in range(365 * 96):
        lignes.append(f"{(t + timedelta(minutes=15 * (i + 1))).isoformat()}+01:00,{kw}")
    return pf.lire("\n".join(lignes) + "\n")


REFERENCE = {(m, j, h): (500.0 if 10 <= h < 16 else 0.0) for m in range(1, 13) for j in range(1, 32) for h in range(24)}


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    p100 = profil_constant(100.0)
    r = scan_solaire.scanner(p100, {"pays": "FR", "kwc": [100], "kwh": [200], "limite_injection_kw": 0, "prix_achat_eur_kwh": 0.2,
                                     "prix_pv_eur_kwc": [1000, 1000], "prix_batterie_eur_kwh": [500, 500]}, reference=REFERENCE)
    sc = {(s["scenario"], s["kwc"], s["kwh"]): s for s in r["scenarios"]}
    pv = sc[("pv_seul", 100, 0.0)]
    verifier(proche(pv["production_kwh"]["valeur"], 50 * 6 * 365) and proche(pv["autoconsommee_kwh"]["valeur"], 50 * 6 * 365) and pv["taux_autoconsommation"] == 1.0,
             "charge 100 kW, 100 kWc : 109 500 kWh produits, tout autoconsommé")
    verifier(proche(pv["importee_kwh"]["valeur"], 100 * 8760 - 109500) and pv["ecretee_kwh"]["valeur"] == 0 and pv["pointe_import_kw"]["valeur"] == 100,
             "charge 100 kW : import réduit de la production, rien d'écrêté, pointe de nuit inchangée à 100 kW")
    verifier(pv["economie_achat_eur"]["valeur"] == round(109500 * 0.2) and pv["economie_reseau_eur"]["nature"] == "a_completer"
             and pv["economie_totale_eur"]["source"] == "src_eco_partielle",
             "économie : 21 900 € d'achat évité, réseau France à compléter, total signalé partiel")
    verifier(pv["investissement_eur"]["valeur"] == [100000.0, 100000.0] and pv["retour_ans"]["valeur"] == [4.6, 4.6] and pv["verdict"] == "retenir",
             "100 kWc à 1 000 €/kWc : 100 000 €, retour 4,6 ans, à retenir")
    rien = sc[("rien", 0.0, 0.0)]
    verifier(rien["importee_kwh"]["valeur"] == 100 * 8760 and rien["verdict"] == "reference" and rien["investissement_eur"]["valeur"] == 0,
             "scénario rien : 876 000 kWh importés, référence")
    verifier(("batterie_seule", 0.0, 0.0) not in sc and not any(s["scenario"] == "batterie_seule" for s in r["scenarios"]),
             "charge plate : pas de pointe à écrêter, aucun scénario batterie seule")

    p30 = profil_constant(30.0)
    fiche = {"pays": "NL", "kwc": [100], "kwh": [200], "limite_injection_kw": 0, "prix_achat_eur_kwh": 0.2, "prix_vente_surplus_eur_kwh": 0.05,
             "prix_pv_eur_kwc": [1000, 1000], "prix_batterie_eur_kwh": [500, 500], "gestionnaire": "liander", "categorie_tarifaire": "MS"}
    r = scan_solaire.scanner(p30, fiche, reference=REFERENCE)
    sc = {(s["scenario"], s["kwc"], s["kwh"]): s for s in r["scenarios"]}
    pv = sc[("pv_seul", 100, 0.0)]
    verifier(proche(pv["autoconsommee_kwh"]["valeur"], 30 * 6 * 365) and proche(pv["ecretee_kwh"]["valeur"], 20 * 6 * 365) and pv["exportee_kwh"]["valeur"] == 0,
             "charge 30 kW, injection nulle : 65 700 kWh autoconsommés, 43 800 kWh écrêtés")
    verifier(proche(pv["taux_autoconsommation"], 0.6, 1e-6) and proche(pv["taux_autoproduction"], 65700 / (30 * 8760), 1e-6),
             "taux d'autoconsommation 60 %, taux d'autoproduction 25 %")
    verifier(pv["kwmax_evites"] == 0 and pv["economie_reseau_eur"]["valeur"] == 0, "NL, charge plate : pointe de nuit inchangée, aucun kW-mois évité")
    r10 = scan_solaire.scanner(p30, {**fiche, "limite_injection_kw": 10}, reference=REFERENCE)
    pv10 = next(s for s in r10["scenarios"] if s["scenario"] == "pv_seul")
    verifier(proche(pv10["exportee_kwh"]["valeur"], 10 * 6 * 365) and proche(pv10["ecretee_kwh"]["valeur"], 10 * 6 * 365)
             and pv10["recette_surplus_eur"]["valeur"] == round(21900 * 0.05),
             "limite d'injection 10 kW : moitié injectée (21 900 kWh, 1 095 €), moitié écrêtée")
    pb = sc[("pv_batterie", 100, 200)]
    stocke = 20 * 6 * ETA  # 113,8 kWh par jour, sous les 180 kWh utiles
    verifier(proche(pb["autoconsommee_kwh"]["valeur"], (30 * 6 + stocke * ETA) * 365, 2) and proche(pb["ecretee_kwh"]["valeur"], 0, 1),
             f"PV + batterie 200 kWh : {(30 * 6 + stocke * ETA):.1f} kWh autoconsommés par jour, plus rien d'écrêté")
    verifier(proche(pb["cycles_batterie"], stocke * ETA * 365 / 180, 0.2), "batterie : environ 219 cycles pleins par an (108 kWh par jour sur 180 utiles)")
    verifier(pb["investissement_eur"]["valeur"] == [200000.0, 200000.0] and pb["retour_ans"]["valeur"][0] > pv["retour_ans"]["valeur"][0],
             "PV + batterie : 200 000 €, retour plus long que le PV seul sur ces prix")
    verifier(r["meilleur"] == "pv_seul 100 kWc", "meilleur scénario : PV seul")
    natures = {g["nature"] for g in _grandeurs(scan_solaire.allege(r))}
    verifier(natures <= scan_solaire.NATURES and "simule" in natures and "hypothese" in natures, f"natures connues : {', '.join(sorted(natures))}")

    # Sans prix ni référence : rien n'est inventé.
    r0 = scan_solaire.scanner(p30, {"pays": "FR"})
    verifier(all(s["scenario"] == "rien" for s in r0["scenarios"]) and r0["production_reference"] is None and r0["meilleur"] is None,
             "sans référence de production : seul le scénario rien, aucun meilleur")
    r1 = scan_solaire.scanner(p30, {"pays": "FR", "kwc": [50]}, reference=REFERENCE)
    s1 = next(s for s in r1["scenarios"] if s["scenario"] == "pv_seul")
    verifier(s1["economie_totale_eur"]["nature"] == "a_completer" and s1["investissement_eur"]["nature"] == "a_completer" and s1["verdict"] == "a_chiffrer",
             "sans prix : économie et investissement à compléter, verdict à chiffrer, bilans d'énergie calculés quand même")
    rt = scan_solaire.scanner(p30, {"pays": "FR", "surface_toiture_m2": 300}, reference=REFERENCE)
    verifier(rt["borne_toiture_kwc"] == 50 and max(rt["kwc_etudies"]) <= 50, "toiture de 300 m² à 6 m²/kWc : puissances bornées à 50 kWc")
    for mauvaise, attendu in (({"pays": "DE"}, "pays"), ({"pays": "FR", "kwc": [0]}, "kwc"), ({"pays": "FR", "reference_pv": "lyon"}, "reference_pv"),
                              ({"pays": "FR", "prix_pv_eur_kwc": [2, 1]}, "fourchette"), ({"pays": "NL", "gestionnaire": "liander", "categorie_tarifaire": "LS"}, "categorie"),
                              ({"pays": "FR", "hypotheses": {"profondeur_decharge": 2}}, "profondeur")):
        try:
            scan_solaire.scanner(p30, mauvaise, reference=REFERENCE)
            verifier(False, f"fiche refusée : {attendu}")
        except ValueError as erreur:
            verifier(attendu in str(erreur), f"fiche refusée avec le nom du champ : {attendu}")

    page = rapport_solaire.rendre(r)
    texte = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>|<svg.*?</svg>", " ", page, flags=re.S))).split())
    verifier("L'essentiel" in texte and "PV et batterie" in texte and "Hypothèses, règles et sources" in texte and not re.search(r"\b(src_|hyp_)\w+", texte) and "None" not in texte,
             "rapport : sections présentes, aucune clé brute, aucun None")
    verifier("65 700" in texte and "43 800" in texte and "à retenir" in texte, "rapport : bilans et verdicts affichés")

    csv = ICI.parent / "docs" / "exemples" / "scan-turpe" / "vea-2708-2016.csv"
    if csv.exists() and (EXEMPLE / "fiche.json").exists():
        p = pf.lire(csv.read_text(encoding="utf-8"))
        f = json.loads((EXEMPLE / "fiche.json").read_text(encoding="utf-8"))
        rv = scan_solaire.scanner(p, f)
        verifier(rv["production_reference"]["kwh_par_kwc"] == 989.1 and rv["statistiques"]["annee_complete"], "VEA 2708 : référence Amsterdam 989,1 kWh/kWc, année complète")
        bs = next((s for s in rv["scenarios"] if s["scenario"] == "batterie_seule"), None)
        verifier(bs is not None and bs["plafond_kw"] == 523 and bs["kwh"] == 72.0, "VEA 2708 : batterie seule dimensionnée à 72 kWh pour tenir 523 kW, comme le scan France")
        with tempfile.TemporaryDirectory() as tmp:
            code = scan_solaire.main(["scan_solaire.py", str(csv), str(EXEMPLE / "fiche.json"), tmp])
            fichiers = sorted(x.name for x in Path(tmp).iterdir())
        verifier(code == 0 and fichiers == ["rapport-solaire.html", "scan-solaire.json"], "ligne de commande : scan-solaire.json et rapport-solaire.html écrits")
    else:
        print("ignoré : exemple VEA 2708 absent")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


def _grandeurs(objet):
    if isinstance(objet, dict):
        if "nature" in objet and "valeur" in objet:
            yield objet
        for v in objet.values():
            yield from _grandeurs(v)
    elif isinstance(objet, list):
        for v in objet:
            yield from _grandeurs(v)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_periode_et_retour_sur_un_ou_deux_ans(self):
        reference = {(m, j, h): 500.0 for m in range(1, 13) for j in range(1, 32) for h in range(24)}
        fiche = {"pays": "FR", "kwc": [100], "kwh": [1], "prix_achat_eur_kwh": 0.2,
                 "prix_vente_surplus_eur_kwh": 0, "prix_pv_eur_kwc": [1000, 1000]}
        for jours in (7, 365, 366, 730):
            with self.subTest(jours=jours):
                csv = "fin_intervalle,puissance_kw\n" + "".join(
                    f"{datetime(2021, 1, 1) + timedelta(hours=i + 1)}Z,100\n" for i in range(jours * 24))
                resultat = scan_solaire.scanner(pf.lire(csv), fiche, reference=reference)
                pv = next(s for s in resultat["scenarios"] if s["scenario"] == "pv_seul")
                self.assertEqual(pv["economie_totale_eur"]["valeur"], 50 * 24 * jours * 0.2)
                self.assertEqual(pv["economie_totale_eur"]["unite"], "€/periode")
                self.assertEqual(pv["economie_totale_eur"]["nature"], "simule")
                self.assertEqual(pv["production_kwh"]["unite"], "kWh/periode")
                self.assertEqual(resultat["statistiques"]["charge_mwh"]["unite"], "MWh/periode")
                self.assertEqual(resultat["statistiques"]["charge_mwh"]["nature"], "lu")  # P1-AA : sans statut source, « lu », pas « mesuré »
                self.assertEqual(resultat["statistiques"]["duree_jours"], jours)
                self.assertEqual(pv["retour_ans"]["valeur"], [1.1, 1.1] if jours >= 365 else None)
                page = rapport_solaire.rendre(resultat)
                self.assertNotIn("€/an", page)
                self.assertIn("Économie estimée sur la période", page)
                self.assertIn("Aucun gain financier mesuré", page)
                self.assertIn("MWh sur la période", page)
                self.assertTrue(all(g["nature"] != "mesure" for s in resultat["scenarios"]
                                    for g in _grandeurs(s) if g["unite"].startswith("€")))

    def test_tarif_kwmax_du_gestionnaire_declare(self):
        # A4 : le tarif kWmax dépend du gestionnaire (Enexis MS 3,66, Stedin MS 3,0966, Liander 3,57 €/kW/mois) ;
        # un gestionnaire inconnu ou absent est refusé, jamais remplacé par Liander.
        p30 = profil_constant(30.0)
        attendus = {"liander": 3.57, "enexis": 3.66, "stedin": 3.0966}
        for g, tarif in attendus.items():
            with self.subTest(gestionnaire=g):
                r = scan_solaire.scanner(p30, {"pays": "NL", "gestionnaire": g, "categorie_tarifaire": "MS"}, reference=REFERENCE)
                self.assertEqual(r["tarif_kwmax"], tarif)
                self.assertEqual(r["gestionnaire"], g)
        for fiche, attendu in (({"pays": "NL", "gestionnaire": "invente", "categorie_tarifaire": "MS"}, "gestionnaire"),
                               ({"pays": "NL", "gestionnaire": "invente"}, "gestionnaire"),
                               ({"pays": "NL", "categorie_tarifaire": "MS"}, "gestionnaire"),
                               ({"pays": "NL", "gestionnaire": "liander", "categorie_tarifaire": "MS_TRANSPORT"}, "categorie")):
            with self.subTest(fiche=fiche):
                with self.assertRaises(ValueError) as cm:
                    scan_solaire.scanner(p30, fiche, reference=REFERENCE)
                self.assertIn(attendu, str(cm.exception))
        page = rapport_solaire.rendre(scan_solaire.scanner(p30, {"pays": "NL", "gestionnaire": "enexis", "categorie_tarifaire": "MS",
                                                                 "kwc": [100], "prix_achat_eur_kwh": 0.2}, reference=REFERENCE))
        self.assertIn("Enexis", page)
        self.assertNotIn("Liander", page)

    def test_kwmax_du_dernier_quart_du_mois(self):
        # A5 : le quart qui finit le 1er février à 00:00 appartient à janvier.
        fins = [datetime(2026, 1, 31, 23, 45), datetime(2026, 2, 1), datetime(2026, 2, 1, 0, 15)]
        self.assertEqual(scan_solaire.kwmax_mois([100, 200, 50], fins, 0.25), 250)

    def test_production_sur_intervalle_decale(self):
        # A8 : un intervalle horaire de 00:30 à 01:30 vaut la moyenne des deux heures de référence, pas l'heure du début.
        ref = {(1, 1, 0): 0.0, (1, 1, 1): 1000.0, (1, 1, 2): 400.0}
        self.assertEqual(scan_solaire.production(ref, [datetime(2026, 1, 1, 1, 30)], 1, 1), [0.5])
        self.assertEqual(scan_solaire.production(ref, [datetime(2026, 1, 1, 1, 15)], 0.25, 1), [1.0])
        # 01:50 à 02:20 : 10 min à 1 000 W et 20 min à 400 W par kWc, soit 600 W/kWc, x 2 kWc = 1,2 kW.
        self.assertAlmostEqual(scan_solaire.production(ref, [datetime(2026, 1, 1, 2, 20)], 0.5, 2)[0], 1.2)

    def test_limite_injection_en_part_du_kwc(self):
        # O11 : la règle SDE++ plafonne la capacité d'injection contractée EN PLUS à 50 % du kWc de la nouvelle
        # installation ; une seule limite en kW pour toutes les puissances étudiées ne peut pas la reproduire.
        p30 = profil_constant(30.0)
        r = scan_solaire.scanner(p30, {"pays": "NL", "kwc": [100, 200], "limite_injection_part_kwc": 0.1}, reference=REFERENCE)
        pv = {s["kwc"]: s for s in r["scenarios"] if s["scenario"] == "pv_seul"}
        self.assertEqual(pv[100]["limite_injection_kw"], 10)
        self.assertEqual(pv[200]["limite_injection_kw"], 20)
        self.assertTrue(proche(pv[100]["ecretee_kwh"]["valeur"], 10 * 6 * 365) and proche(pv[200]["ecretee_kwh"]["valeur"], 50 * 6 * 365))
        r2 = scan_solaire.scanner(p30, {"pays": "NL", "kwc": [100], "limite_injection_kw": 5, "limite_injection_part_kwc": 0.1}, reference=REFERENCE)
        self.assertEqual(next(s for s in r2["scenarios"] if s["scenario"] == "pv_seul")["limite_injection_kw"], 15)
        with self.assertRaises(ValueError):
            scan_solaire.scanner(p30, {"pays": "NL", "limite_injection_part_kwc": 1.5}, reference=REFERENCE)
        page = rapport_solaire.rendre(r)
        self.assertIn("10,0 % du kWc", " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split()))

    def test_page_qualite_et_reserves(self):
        # FB1 sur le rapport solaire : page en tête ; sans statut, verdicts, meilleur scénario et bilans sont « à confirmer ».
        p30 = profil_constant(30.0)
        fiche = {"pays": "NL", "gestionnaire": "liander", "categorie_tarifaire": "MS", "kwc": [100], "kwh": [200], "limite_injection_kw": 0,
                 "prix_achat_eur_kwh": 0.2, "prix_vente_surplus_eur_kwh": 0.05, "prix_pv_eur_kwc": [1000, 1000], "prix_batterie_eur_kwh": [500, 500]}
        r = scan_solaire.scanner(p30, fiche, reference=REFERENCE)
        self.assertNotIn("sha256", r["jeu_qualite"]["qualite_donnees"]["provenance"])  # P2-AC : appel direct, aucun octet reçu
        self.assertTrue(r["reserves"]["valeurs"] and r["reserves"]["pointe"])
        self.assertEqual(r["statistiques"]["charge_mwh"]["nature"], "lu")  # P1-AA
        self.assertEqual(r["statistiques"]["pointe_kw"]["nature"], "lu")
        with self.assertRaises(ValueError):  # P2-AB
            scan_solaire.scanner(p30, {**fiche, "ean": 8.7e17}, reference=REFERENCE)
        texte = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>|<svg.*?</svg>", " ", rapport_solaire.rendre(r), flags=re.S))).split())
        self.assertLess(texte.index("Qualité des données"), texte.index("L'essentiel"))
        self.assertIn("Profil lu", texte)
        self.assertNotIn("Profil mesuré", texte)
        self.assertNotIn("soutirage mesuré", texte)
        self.assertIn("à retenir, à confirmer", texte)
        self.assertIn("1. Les scénarios côte à côte (à confirmer)", texte)
        self.assertIn("Retour estimé le plus court, à confirmer", texte)
        self.assertIn("Intervalles : 35040", texte)

    def test_debut_aux_changements_d_heure(self):
        # P2-AD : le début de la période se calcule en UTC puis se convertit (02:50 n'existe pas le 30/03/2025).
        for premiere_fin, attendu in (("2025-03-30T01:00:00+00:00", "2025-03-30T01:50:00"), ("2025-10-26T01:00:00+00:00", "2025-10-26T02:50:00")):
            debut = datetime.fromisoformat(premiere_fin) - timedelta(minutes=10)
            csv = "fin_intervalle,puissance_kw\n" + "".join(f"{(debut + timedelta(minutes=10 * (i + 1))).isoformat()},100\n" for i in range(8 * 144))
            r = scan_solaire.scanner(pf.lire(csv), {"pays": "FR"})
            with self.subTest(premiere_fin=premiere_fin):
                self.assertEqual(r["statistiques"]["debut"], attendu)

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
