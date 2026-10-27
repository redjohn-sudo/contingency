"""Scan France (scan_turpe.py, rapport_turpe.py) : chiffres connus d'avance sur une année synthétique, puis le site VEA 2708
avec un contrat fictif, puis le rapport (aucune grandeur sans nature, aucune clé de texte affichée brute).

Année synthétique 2025 au quart d'heure : 300 kW les jours ouvrés de 7 h à 19 h, 120 kW sinon ; 420 kW pendant l'heure de 9 h
les jours ouvrés dont le numéro est multiple de 9 en janvier, février et décembre (6 événements : 9 et 27 janvier, 18 et 27
février, 9 et 18 décembre). Contrat HTA longue utilisation pointe fixe, 320 kW sur les cinq classes.
  CMDPS : chaque événement tombe en pointe fixe (9 h à 11 h, b1 = 36,40) ; ΔP = 100 kW sur 4 quarts d'heure, soit 6 pas de 10 min :
  par mois √(2 x 6 x 100²) = 346,41, x 0,04 x 36,40 = 504,37 €, trois mois = 1 513 €.
  Puissance : 36,40 x 320 = 11 648 €/an. Optimum : 300 kW sur les cinq classes (les dépassements de 120 kW une heure six fois
  par an coûtent moins que 20 kW souscrits toute l'année). Batterie : plafond 300 kW (pointe sans ses 8 heures), 120 kW,
  4 x 120 x 0,25 / √0,9 = 126,49 kWh utiles, 140,5 kWh nominaux, retour de 31 à 54 ans.
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
import rapport_turpe  # noqa: E402
import scan_turpe  # noqa: E402
import turpe  # noqa: E402

EXEMPLE = ICI.parent / "docs" / "exemples" / "scan-turpe"
echecs = []
ETA = math.sqrt(0.9)


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def proche(a, b, tol=1.0):
    return a is not None and b is not None and abs(a - b) <= tol


def annee_synthetique(jours: int = 365) -> str:
    lignes = ["fin_intervalle,puissance_kw"]
    t = datetime(2025, 1, 1)
    for i in range(jours * 96):
        d = t + timedelta(minutes=15 * i)
        v = 120.0
        if d.weekday() < 5 and 7 <= d.hour < 19:
            v = 300.0
            if d.month in (1, 2, 12) and d.hour == 9 and d.day % 9 == 0:
                v = 420.0
        lignes.append(f"{(d + timedelta(minutes=15)).isoformat()}+01:00,{v}")
    return "\n".join(lignes) + "\n"


def grandeurs(objet):
    if isinstance(objet, dict):
        if "nature" in objet and "valeur" in objet:
            yield objet
        for v in objet.values():
            yield from grandeurs(v)
    elif isinstance(objet, list):
        for v in objet:
            yield from grandeurs(v)


def texte_visible(page):
    sans = re.sub(r"<style.*?</style>|<svg.*?</svg>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", sans))


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    profil = pf.lire(annee_synthetique())
    fiche = {"nom": "essai", "domaine": "HTA", "option": "lu_pointe_fixe", "puissances_souscrites": {c: 320 for c in turpe.CLASSES["HTA"]},
             "puissance_raccordement_kw": 600, "tirages_confiance": 5}
    r = scan_turpe.scanner(profil, fiche)
    a, o, b, q = r["actuel"], r["optimisation"], r["batterie"], r["quarts_decisifs"]
    cmdps_mois = 0.04 * 36.40 * math.sqrt(2 * 6 * 100 ** 2)
    verifier(a["heures_depassement"]["valeur"] == 6.0 and proche(a["cmdps_eur"]["valeur"], 3 * cmdps_mois),
             f"actuel : 6 h de dépassement, CMDPS 3 x {cmdps_mois:.2f} = {3 * cmdps_mois:.0f} €")
    verifier(a["puissance_eur"]["valeur"] == round(36.40 * 320), "actuel : puissance 36,40 x 320 = 11 648 €/an")
    verifier(a["par_classe"]["pointe"]["mois"] == 3 and a["par_classe"]["pointe"]["depassement_max"] == 100 and set(k for k, v in a["par_classe"].items() if v["eur"] > 0) == {"pointe"},
             "actuel : les six dépassements tombent tous en pointe fixe, 100 kW au plus, sur trois mois")
    verifier(a["total_eur"]["valeur"] == a["puissance_eur"]["valeur"] + a["energie_eur"]["valeur"] + a["cmdps_eur"]["valeur"] and a["total_eur"]["unite"] == "€/an",
             "actuel : total = puissance + énergie + CMDPS, en €/an sur une année complète")
    verifier(o["ps"] == [300] * 5 and o["classes_sans_mesure"] == [], "optimum : 300 kW sur les cinq classes, toutes mesurées")
    cmdps_opt = 3 * 0.04 * 36.40 * math.sqrt(2 * 6 * 120 ** 2)
    verifier(proche(o["cmdps_eur"]["valeur"], cmdps_opt) and o["puissance_eur"]["valeur"] == round(36.40 * 300),
             f"optimum : CMDPS {cmdps_opt:.0f} € (ΔP = 120 kW), puissance 10 920 €/an")
    eco_attendue = (36.40 * 20) - (cmdps_opt - 3 * cmdps_mois)
    verifier(proche(o["economie_eur"]["valeur"], eco_attendue, 2) and o["ecarts_ps"] == [-20] * 5,
             f"économie du redimensionnement : 728 € de puissance en moins, {cmdps_opt - 3 * cmdps_mois:.0f} € de CMDPS en plus, soit {eco_attendue:.0f} €/an")
    plats = min((turpe.cout_total(r["profil_kw"], turpe.classes_profil(pf.debuts(profil["fins"], profil["pas_h"]), "HTA", "lu_pointe_fixe"),
                                  [d.strftime("%Y-%m") for d in pf.debuts(profil["fins"], profil["pas_h"])], [p] * 5, "HTA", "lu_pointe_fixe", 15)["total_eur"], p) for p in range(280, 341, 5))
    verifier(plats[1] == 300 and o["total_eur"]["valeur"] <= round(plats[0]) + 1, "recherche sur des puissances plates de 280 à 340 kW : même optimum que la programmation dynamique")
    verifier(r["options"]["meilleure"] == "lu_pointe_fixe" and not r["options"]["lignes"][2]["disponible"],
             "options : longue utilisation pointe fixe reste la moins chère, pointe mobile indisponible sans les jours RTE")
    verifier(b["faisable"] and b["plafond_kw"]["valeur"] == 300 and b["puissance_kw"]["valeur"] == 120 and b["puissance_minimale_kw"]["valeur"] == 120,
             "batterie : plafond 300 kW (pointe sans ses 8 h), 120 kW, puissance minimale déjà optimale (pointes isolées)")
    utile = 4 * 120 * 0.25 / ETA
    verifier(proche(b["capacite_utile_kwh"]["valeur"], utile, 0.1) and proche(b["capacite_nominale_kwh"]["valeur"], utile / 0.9, 0.1) and b["gain_dimensionnement_kwh"] == 0,
             f"batterie : {utile:.1f} kWh utiles, {utile / 0.9:.1f} kWh nominaux, aucun gain de dimensionnement")
    verifier(b["ps"] == [300] * 5 and b["cmdps_eur"]["valeur"] == 0 and proche(b["economie_supplementaire_eur"]["valeur"], cmdps_opt, 2),
             "batterie : plus aucun dépassement, l'économie supplémentaire est la CMDPS restante à l'optimum")
    nominale = b["capacite_nominale_kwh"]["valeur"]
    verifier(b["investissement_eur"]["valeur"] == [round(nominale * 400, -2), round(nominale * 700, -2)] and b["retour_ans"]["valeur"][0] > 25,
             "batterie : investissement 400 à 700 €/kWh (hypothèse), retour de plus de 25 ans sur le seul TURPE")
    verifier(q["jours_au_dessus"] == 6 and all(proche(j["part"], 1 / 6, 0.001) for j in q["jours"]) and len(q["sans_jours"]) == 3,
             "jours décisifs : six jours à parts égales, contrefactuels pour 1, 2 et 3 jours retirés")
    verifier(q["sans_jours"][2]["cmdps_eur"] < q["sans_jours"][0]["cmdps_eur"] < o["cmdps_eur"]["valeur"] and all(s["ps"] == [300] * 5 for s in q["sans_jours"]),
             "jours décisifs : la CMDPS baisse à chaque jour retiré, les puissances optimales restent à 300 kW")
    verifier(r["confiance"] and r["confiance"]["tirages"] == 5 and r["confiance"]["ps"][0]["mediane"] == 300, "niveau de confiance : 5 tirages, puissance de pointe médiane 300 kW")
    verifier(any(l["cle"] == "reco_ps_gain" for l in r["recommandation"]) and any(l["cle"] == "reco_batterie_longue" for l in r["recommandation"]),
             "recommandation : ajuster les puissances, batterie non rentable sur le seul TURPE")
    natures = {g["nature"] for g in grandeurs(scan_turpe.allege(r))}
    verifier(natures <= scan_turpe.NATURES and "lu" in natures and "mesure" not in natures and "simule" in natures and "tarif" in natures,
             f"toutes les grandeurs portent une nature connue : {', '.join(sorted(natures))}")

    # Sans contrat : les puissances optimales sortent, l'économie reste à compléter ; BT > 36 kVA avec cos φ.
    r2 = scan_turpe.scanner(profil, {"domaine": "HTA", "tirages_confiance": 0})
    verifier(not r2["actuel"]["disponible"] and r2["optimisation"]["economie_eur"]["nature"] == "a_completer" and r2["optimisation"]["ps"] == [300] * 5
             and r2["confiance"] is None and any(l["cle"] == "reco_ps_sans_contrat" for l in r2["recommandation"]),
             "sans contrat : puissances optimales calculées, économie à compléter, confiance non calculée à 0 tirage")
    r3 = scan_turpe.scanner(profil, {"domaine": "BT36", "option": "cu", "puissances_souscrites": {"hph": 340, "hch": 340, "hpb": 340, "hcb": 340},
                                     "facteur_puissance": 0.9, "tirages_confiance": 0})
    verifier(r3["actuel"]["cmdps_eur"]["source"] == "src_cmdps_bt36" and r3["actuel"]["heures_depassement"]["valeur"] == 6.0
             and proche(r3["actuel"]["cmdps_eur"]["valeur"], 12.79 * 6, 1) and r3["optimisation"]["ps"] == [334, 334, 334, 334],
             "BT > 36 kVA, cos φ 0,9 : 300 kW valent 333,3 kVA, 6 h de dépassement à 340 kVA (76,74 €), optimum 334 kVA")
    for mauvaise, attendu in (({"domaine": "HTB"}, "HTA"), ({"domaine": "HTA", "option": "cu"}, "option"),
                              ({"domaine": "HTA", "puissances_souscrites": {"pointe": 1}}, "classes"),
                              ({"domaine": "HTA", "puissances_souscrites": {"pointe": 500, "hph": 400, "hch": 400, "hpb": 400, "hcb": 400}}, "croissantes"),
                              ({"domaine": "HTA", "calendrier": {"heures_creuses": [[22]]}}, "heure début"),
                              ({"domaine": "HTA", "cmdps_facturee_eur": {"2025-01": -1}}, "cmdps_facturee"),
                              ({"domaine": "HTA", "hypotheses": {"inconnue": 1}}, "inconnue"),
                              ({"domaine": "HTA", "tirages_confiance": 5000}, "tirages")):
        try:
            scan_turpe.scanner(profil, mauvaise)
            verifier(False, f"fiche refusée : {attendu}")
        except ValueError as erreur:
            verifier(attendu in str(erreur), f"fiche refusée avec le nom du champ : {attendu}")
    facture = scan_turpe.scanner(profil, {**fiche, "tirages_confiance": 0, "cmdps_facturee_eur": {"2025-01": 500.0, "2025-02": 510.0, "2025-06": 0.0}})
    conf = facture["actuel"]["confrontation_facture"]
    verifier(conf["mois"] == ["2025-01", "2025-02", "2025-06"] and proche(conf["calcule_eur"], 2 * cmdps_mois, 0.1) and conf["facture_eur"] == 1010.0 and abs(conf["ecart_part"]) < 0.01,
             "confrontation à la facture : 1 008,7 € calculés contre 1 010 € facturés sur trois mois, écart sous 1 %")

    # Rapport.
    page = rapport_turpe.rendre(r)
    texte = " ".join(texte_visible(page).split())
    verifier("L'essentiel" in texte and "Recommandation" in texte and "Hypothèses et sources" in texte and "Les pas de temps qui décident" in texte,
             "rapport : sections de l'essentiel à la recommandation présentes")
    verifier(not re.search(r"\b(src_|hyp_|reco_)\w+", texte) and "None" not in texte and "nan" not in texte.lower().split(),
             "rapport : aucune clé de texte brute, aucun None")
    verifier("11 648" in texte and "Simulé" in texte and "Publié" in texte and "Hypothèse" in texte and "Déclaré" in texte,
             "rapport : puissance actuelle affichée, badges de nature présents")
    verifier("borne basse" not in texte and "pas de 15 min" in texte
             and "surestimer ou sous-estimer" in texte and "ne sont pas reconstituées" in texte,
             "rapport : estimation à 15 min, aucune garantie de minoration et aucune mesure à 10 min reconstituée")
    verifier(page.count("<svg") >= 5 and "viewport" in page, "rapport : au moins cinq graphiques SVG, lisible sur téléphone")

    # Site VEA 2708 (données publiques réelles, contrat fictif) et ligne de commande.
    csv = EXEMPLE / "vea-2708-2016.csv"
    if csv.exists():
        p = pf.lire(csv.read_text(encoding="utf-8"))
        f = json.loads((EXEMPLE / "fiche.json").read_text(encoding="utf-8"))
        rv = scan_turpe.scanner(p, {**f, "tirages_confiance": 5})
        verifier(rv["statistiques"]["pointe_kw"]["valeur"] == 595 and rv["statistiques"]["annee_complete"] and p["pas_minutes"] == 15,
                 "VEA 2708 : pointe 595 kW, année 2016 complète au quart d'heure")
        verifier(rv["actuel"]["disponible"] and rv["optimisation"]["total_eur"]["valeur"] <= rv["actuel"]["total_eur"]["valeur"],
                 "VEA 2708 : le total aux puissances optimales ne dépasse jamais le total du contrat fictif")
        verifier(rv["batterie"]["faisable"] and rv["batterie"]["plafond_kw"]["valeur"] == 523, "VEA 2708 : plafond 523 kW (pointe sans ses 8 heures, comme le scan néerlandais)")
        with tempfile.TemporaryDirectory() as tmp:
            code = scan_turpe.main(["scan_turpe.py", str(csv), str(EXEMPLE / "fiche.json"), tmp])
            fichiers = sorted(x.name for x in Path(tmp).iterdir())
        verifier(code == 0 and fichiers == ["rapport-turpe.html", "scan-turpe.json"], "ligne de commande : scan-turpe.json et rapport-turpe.html écrits")
    else:
        print("ignoré : docs/exemples/scan-turpe/vea-2708-2016.csv absent")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_deux_annees_ne_sont_pas_facturees_comme_une(self):
        # A2 (partie TURPE) : sur deux ans, la puissance était plafonnée à un an alors que l'énergie et la CMDPS
        # couvraient deux ans ; les composantes ne portaient plus sur la même période.
        fiche = {"domaine": "HTA", "option": "cu_pointe_fixe", "puissances_souscrites": {c: 100 for c in turpe.CLASSES["HTA"]},
                 "tirages_confiance": 0}
        totaux = {}
        for jours in (365, 730):
            csv = "fin_intervalle,puissance_kw\n" + "".join(f"{datetime(2021, 1, 1) + timedelta(hours=i + 1)}Z,100\n" for i in range(jours * 24))
            r = scan_turpe.scanner(pf.lire(csv), fiche)
            a = r["actuel"]
            totaux[jours] = a["total_eur"]["valeur"]
            with self.subTest(jours=jours):
                self.assertEqual(a["puissance_eur"]["valeur"], round(14.85 * 100 * jours / 365))
                self.assertEqual(a["total_eur"]["unite"], "€/an" if jours == 365 else "€/periode")
                self.assertEqual(r["statistiques"]["energie_mwh"]["unite"], "MWh/an" if jours == 365 else "MWh/periode")
                self.assertEqual(r["statistiques"]["fraction_annee"], jours / 365)
        self.assertEqual(totaux[730], 2 * totaux[365])
        self.assertEqual(turpe.fraction_annee(366 * 24, 1.0), 1.0)  # année bissextile : une année, pas 1,003
        self.assertEqual(turpe.fraction_annee(364 * 96, 0.25), 364 / 365)

    def test_batterie_et_plafond_sur_deux_annees(self):
        # A2, cas limite : sur deux ans, le retour de la batterie ramène l'économie à l'année et le plafond « pointe
        # sans ses 8 h » compte 8 h par année de profil (64 quarts d'heure, pas 32).
        profil = pf.lire(annee_synthetique(730))
        self.assertEqual(profil["fins_utc"][-1] - profil["fins_utc"][0], timedelta(days=730) - timedelta(minutes=15))
        fiche = {"domaine": "HTA", "option": "lu_pointe_fixe", "puissances_souscrites": {c: 320 for c in turpe.CLASSES["HTA"]}, "tirages_confiance": 0}
        r = scan_turpe.scanner(profil, fiche)
        b, o, a = r["batterie"], r["optimisation"], r["actuel"]
        self.assertEqual(r["statistiques"]["fraction_annee"], 2.0)
        self.assertEqual(a["puissance_eur"]["valeur"], round(36.40 * 320 * 2))
        self.assertEqual(a["total_eur"]["unite"], "€/periode")
        self.assertEqual(o["ps"], [300] * 5)
        self.assertEqual(scan_turpe.plafond_heures(r["profil_kw"], 8), sorted(r["profil_kw"], reverse=True)[64])
        eco_an = b["economie_supplementaire_eur"]["valeur"] / 2
        inv = b["investissement_eur"]["valeur"]
        self.assertEqual(b["retour_ans"]["valeur"], [round(inv[0] / eco_an, 1), round(inv[1] / eco_an, 1)])
        self.assertEqual(b["retour_ans"]["parametres"]["annees"], 2.0)
        self.assertIn("2,00 années", texte_visible(rapport_turpe.rendre(r)))

    def test_bt36_controle_sur_la_puissance_active_0_93(self):
        # O9 : Enedis, brochure TURPE 7 du 01/08/2026, p. 6 : puissance souscrite active = 0,93 x puissance apparente.
        profil = pf.lire(annee_synthetique())
        r = scan_turpe.scanner(profil, {"domaine": "BT36", "option": "cu", "tirages_confiance": 0,
                                        "puissances_souscrites": {"hph": 315, "hch": 315, "hpb": 315, "hcb": 315}})
        self.assertEqual(r["raccordement"]["facteur_puissance"], 0.93)
        self.assertEqual(r["hypotheses"]["facteur_puissance"]["valeur"], 0.93)
        # 300 kW valent 322,6 kVA à 0,93 : les 300 kW des jours ouvrés dépassent 315 kVA (cos φ = 1 n'y verrait rien).
        self.assertGreater(r["actuel"]["heures_depassement"]["valeur"], 1000)
        texte = texte_visible(rapport_turpe.rendre(r))
        self.assertIn("0,93", texte)
        self.assertIn("p. 6", texte)

    def test_grille_2025_08_citee_avec_ses_propres_tarifs(self):
        # O10 : avec la grille 2025-08 le calcul applique 12,41 €/h, le rapport ne doit plus citer 12,79 € ni 2026.
        profil = pf.lire(annee_synthetique())
        r = scan_turpe.scanner(profil, {"domaine": "BT36", "option": "cu", "grille": "2025-08", "tirages_confiance": 0,
                                        "puissances_souscrites": {"hph": 400, "hch": 400, "hpb": 400, "hcb": 400}})
        texte = " ".join(texte_visible(rapport_turpe.rendre(r)).split())
        self.assertIn("12,41", texte)
        self.assertNotIn("12,79", texte)
        self.assertIn("coefficients en vigueur au 01/08/2025", texte)
        self.assertNotIn("2026-105", texte)
        self.assertNotIn("1er août 2026", texte)
        r2 = scan_turpe.scanner(profil, {"domaine": "HTA", "option": "cu_pointe_fixe", "grille": "2025-08", "tirages_confiance": 0,
                                         "puissances_souscrites": {c: 400 for c in turpe.CLASSES["HTA"]}})
        texte2 = " ".join(texte_visible(rapport_turpe.rendre(r2)).split())
        self.assertIn("2025-78", texte2)
        self.assertNotIn("2026-105", texte2)

    def test_note_centaine_d_heures_reservee_a_la_hta(self):
        # O19 : la phrase de la CRE (4.3.3.3, coefficient 0,04) porte sur la HTA ; en BT > 36 kVA la CMDPS se paie à
        # l'heure et dépasser plus d'une à deux heures par kVA coûte déjà plus cher que souscrire.
        profil = pf.lire(annee_synthetique())
        bt = " ".join(texte_visible(rapport_turpe.rendre(scan_turpe.scanner(profil, {"domaine": "BT36", "tirages_confiance": 0}))).split())
        hta = " ".join(texte_visible(rapport_turpe.rendre(scan_turpe.scanner(profil, {"domaine": "HTA", "tirages_confiance": 0}))).split())
        self.assertNotIn("centaine d'heures", bt)
        self.assertIn("par heure de dépassement", bt)
        self.assertIn("centaine d'heures", hta)
        self.assertIn("mois par mois", hta)

    def test_debut_d_intervalle_au_changement_d_heure(self):
        # O20 : le quart 00:45-01:00 UTC du 25/10/2026 commence à 02:45 heure d'été ; retirer le pas à la fin locale
        # (02:00, heure d'hiver) donnait 01:45 et classait ce quart en heures pleines au lieu de creuses (2 h à 7 h).
        debut = datetime(2026, 10, 19, tzinfo=pf.ZoneInfo("UTC"))
        cible = datetime(2026, 10, 25, 1, 0, tzinfo=pf.ZoneInfo("UTC"))
        lignes = ["fin_intervalle,puissance_kw"]
        for i in range(7 * 96):
            fin = debut + timedelta(minutes=15 * (i + 1))
            lignes.append(f"{fin.isoformat()},{1000 if fin == cible else 100}")
        profil = pf.lire("\n".join(lignes) + "\n")
        i = profil["fins_utc"].index(datetime(2026, 10, 25, 1, 0))
        self.assertEqual(profil["debuts"][i], datetime(2026, 10, 25, 2, 45))
        r = scan_turpe.scanner(profil, {"domaine": "BT36", "option": "cu", "tirages_confiance": 0, "calendrier": {"heures_creuses": [[2, 7], [13, 16]]}})
        self.assertEqual(r["classes"]["hcb"]["pointe_kw"], 1000)
        self.assertEqual(r["classes"]["hpb"]["pointe_kw"], 100)

    def test_economie_presentee_comme_estimation(self):
        # O25 : l'économie du redimensionnement dépend d'une CMDPS estimée au pas fourni ; le rapport ne la donne
        # plus comme une valeur unique et ferme.
        profil = pf.lire(annee_synthetique())
        fiche = {"domaine": "HTA", "option": "lu_pointe_fixe", "puissances_souscrites": {c: 320 for c in turpe.CLASSES["HTA"]}, "tirages_confiance": 0}
        texte = " ".join(texte_visible(rapport_turpe.rendre(scan_turpe.scanner(profil, fiche))).split())
        self.assertIn("d'économie estimée de TURPE", texte)
        self.assertIn("à confronter à la facture", texte)
        self.assertNotIn("d'économie de TURPE sur le profil mesuré, sans investissement", texte)

    def test_page_qualite_et_reserves(self):
        # FB1 sur le rapport France : page en tête depuis scan_flex.qualite_* et rapport_flex._section_qualite (sans copie) ;
        # sans colonne de statut, la qualité est inconnue et chaque résultat qui dépend des valeurs est « à confirmer ».
        profil = pf.lire(annee_synthetique())
        fiche = {"domaine": "HTA", "option": "lu_pointe_fixe", "puissances_souscrites": {c: 320 for c in turpe.CLASSES["HTA"]}, "tirages_confiance": 0}
        r = scan_turpe.scanner(profil, fiche)
        jeu = r["jeu_qualite"]
        codes = {c["code"] for c in jeu["qualite_donnees"]["constats"]}
        self.assertIn("QUALITE_POINTE_NON_MESUREE", codes)
        self.assertIn("QUALITE_VALEURS_NON_MESUREES", codes)
        self.assertTrue(r["reserves"]["pointe"] and r["reserves"]["valeurs"])
        page = rapport_turpe.rendre(r)
        texte = " ".join(texte_visible(page).split())
        self.assertLess(texte.index("Qualité des données"), texte.index("L'essentiel"))
        self.assertIn("Q4. Bilan des lignes", texte)
        self.assertIn("3. Situation actuelle (à confirmer)", texte)
        self.assertIn("5. Batterie d'écrêtage (à confirmer)", texte)
        self.assertIn("Intervalles : 35040", texte)  # texte du catalogue d'Astra, jamais réécrit
        reco = texte[texte.index("8. Recommandation"):texte.index("9. Hypothèses")]
        self.assertGreaterEqual(reco.count("À confirmer"), 2)
        # Pas de 10 minutes en heure de Paris, autour du passage à l'heure d'été : la page suit le pas natif et la zone.
        debut = datetime(2025, 3, 29, tzinfo=pf.ZoneInfo("UTC")) - timedelta(hours=1)
        dix = pf.lire("fin_intervalle,puissance_kw\n" + "".join(f"{(debut + timedelta(minutes=10 * (i + 1))).isoformat()},100\n" for i in range(8 * 144)))
        r10 = scan_turpe.scanner(dix, {"domaine": "HTA", "tirages_confiance": 0})
        self.assertIn({"jour": "2025-03-30", "intervalles": 138, "motif": "ete"}, r10["jeu_qualite"]["qualite_donnees"]["jours_particuliers"])
        page10 = " ".join(texte_visible(rapport_turpe.rendre(r10)).split())
        qualite = page10[page10.index("Qualité des données"):page10.index("L'essentiel")]
        self.assertIn("intervalle de 10 minutes", qualite)
        self.assertIn("heure de Paris", qualite)
        self.assertIn("30/03/2025", qualite)
        self.assertNotIn("15 minutes", qualite)
        # Hors 15 min, le constat de pointe est QUALITE_POINTE_INTERVALLE_NON_MESUREE : la réserve de pointe reste (revue d'Astra).
        self.assertTrue(r10["reserves"]["pointe"])
        self.assertIn("pointe", rapport_turpe._reserve_textes(r10))
        self.assertIn("5. Batterie d'écrêtage (à confirmer)", page10)
        # P1-AA : sans statut source, énergie, pointe et moyenne sont « lues », pas « mesurées » ; le texte le dit.
        for cle in ("energie_mwh", "pointe_kw", "moyenne_kw", "heures_utilisation"):
            self.assertEqual(r["statistiques"][cle]["nature"], "lu", cle)
        self.assertIn("Profil lu", texte)
        self.assertNotIn("Profil mesuré", texte)
        self.assertIn("Courbe de charge lue", texte)
        self.assertNotIn("Courbe de charge mesurée", texte)
        self.assertIn("une mesure directe n'est pas établie pour toutes les valeurs nécessaires", texte)  # texte d'Astra, valable aussi pour des valeurs estimées ou calculées
        self.assertNotIn("non documentée", texte[texte.index("L'essentiel"):])
        self.assertIn("Lu", texte)
        # P2-AC : en appel direct, aucune empreinte d'octets n'est affirmée ; le lecteur nomme la sienne « texte ».
        prov = r["jeu_qualite"]["qualite_donnees"]["provenance"]
        self.assertNotIn("sha256", prov)
        self.assertEqual(prov["sha256_texte"], profil["provenance"]["sha256_texte"])
        self.assertIn("non transmis au scan", texte)
        # P2-AB : un EAN numérique est refusé avant tout calcul.
        with self.assertRaises(ValueError) as cm:
            scan_turpe.scanner(profil, {**fiche, "ean": 8.71234567890123456e17})
        self.assertIn("ean", str(cm.exception))

    def test_debut_et_pointe_aux_changements_d_heure(self):
        # P2-AD (revue d'Astra) : le début et l'instant de pointe se calculent en UTC puis se convertissent ; retirer le
        # pas à une fin locale donne 02:50 le 30/03/2025 (heure inexistante) et 01:50 le 26/10/2025 (mauvaise occurrence).
        for premiere_fin, attendu in (("2025-03-30T01:00:00+00:00", "2025-03-30T01:50:00"), ("2025-10-26T01:00:00+00:00", "2025-10-26T02:50:00")):
            debut = datetime.fromisoformat(premiere_fin) - timedelta(minutes=10)
            # 60 jours : sur 8 jours, souscrire les 500 kW coûterait moins que la CMDPS et aucun jour ne serait décisif.
            csv = "fin_intervalle,puissance_kw\n" + "".join(f"{(debut + timedelta(minutes=10 * (i + 1))).isoformat()},{500 if i == 0 else 100}\n" for i in range(60 * 144))
            r = scan_turpe.scanner(pf.lire(csv), {"domaine": "HTA", "option": "cu_pointe_fixe", "tirages_confiance": 0,
                                                  "puissances_souscrites": {c: 100 for c in turpe.CLASSES["HTA"]}})
            with self.subTest(premiere_fin=premiere_fin):
                self.assertEqual(r["statistiques"]["debut"], attendu)
                self.assertEqual(r["statistiques"]["instant_pointe"], attendu)
                self.assertEqual(r["profils"]["jour_pointe"]["jour"], attendu[:10])
                self.assertEqual(r["quarts_decisifs"]["top"][0]["debut"], attendu[:16])

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
