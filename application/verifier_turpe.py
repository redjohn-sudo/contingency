"""TURPE 7 (turpe.py) : calendrier des classes, composantes, CMDPS et optimisation des puissances souscrites, chiffres
calculés à la main à partir des coefficients du 1er août 2026 (CRE n°2026-105, annexe 2)."""
import math
import sys
import unittest
from datetime import datetime, timedelta, date
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import turpe  # noqa: E402

echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def proche(a, b, tol=0.01):
    return abs(a - b) <= tol


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    c = turpe.classe_instant
    verifier(c(datetime(2026, 1, 15, 9, 30), "HTA", "cu_pointe_fixe") == "pointe", "jeudi 15/01 09:30, HTA pointe fixe : pointe")
    verifier(c(datetime(2026, 1, 15, 12, 0), "HTA", "cu_pointe_fixe") == "hph", "jeudi 15/01 12:00 : heures pleines saison haute")
    verifier(c(datetime(2026, 1, 15, 23, 0), "HTA", "cu_pointe_fixe") == "hch", "jeudi 15/01 23:00 : heures creuses saison haute (22 h à 6 h par défaut)")
    verifier(c(datetime(2026, 1, 15, 5, 59), "HTA", "cu_pointe_fixe") == "hch" and c(datetime(2026, 1, 15, 6, 0), "HTA", "cu_pointe_fixe") == "hph",
             "plage de nuit : 05:59 creuse, 06:00 pleine")
    verifier(c(datetime(2026, 1, 18, 10, 0), "HTA", "lu_pointe_fixe") == "hch", "dimanche 18/01 10:00, HTA : entièrement en heures creuses, pas de pointe")
    verifier(c(datetime(2026, 1, 18, 10, 0), "BT36", "cu") == "hph", "dimanche 18/01 10:00, BT > 36 kVA : heures pleines (pas de règle du dimanche)")
    verifier(c(datetime(2026, 7, 15, 10, 0), "HTA", "cu_pointe_fixe") == "hpb" and c(datetime(2026, 7, 15, 3, 0), "BT36", "lu") == "hcb",
             "juillet : saison basse, pleines le jour, creuses la nuit")
    verifier(c(datetime(2026, 11, 5, 10, 0), "HTA", "cu_pointe_fixe") == "hph", "5 novembre 10:00 : saison haute (défaut novembre à mars) mais pas de pointe (décembre à février)")
    verifier(c(datetime(2026, 12, 3, 18, 30), "HTA", "cu_pointe_mobile") == "hph", "pointe mobile sans jour fourni : jamais de pointe")
    cal = {"pointe_mobile_jours": ["2026-12-03"]}
    verifier(c(datetime(2026, 12, 3, 18, 30), "HTA", "cu_pointe_mobile", cal) == "pointe" and c(datetime(2026, 12, 3, 12, 0), "HTA", "cu_pointe_mobile", cal) == "hph",
             "jour de pointe mobile fourni : pointe de 17 h à 20 h, pas à midi")
    cal2 = {"heures_creuses": [[1, 5], [12, 16]]}
    verifier(c(datetime(2026, 7, 15, 13, 0), "BT36", "cu", cal2) == "hcb" and c(datetime(2026, 7, 15, 23, 0), "BT36", "cu", cal2) == "hpb",
             "heures creuses locales en deux périodes : 13 h creuse, 23 h pleine")
    for domaine, option in (("HTA", "cu"), ("BT36", "cu_pointe_fixe"), ("HTB", "cu")):
        try:
            c(datetime(2026, 1, 1), domaine, option)
            verifier(False, f"{domaine}/{option} refusé")
        except ValueError:
            verifier(True, f"{domaine}/{option} : combinaison refusée")

    # Composantes HTA, courte utilisation pointe fixe, grille du 1er août 2026.
    g = turpe.grille("HTA", "cu_pointe_fixe")
    verifier(g["b"] == [14.85, 14.85, 14.85, 12.93, 11.56] and g["cmdps"]["cp"] == 0.04 and g["en_vigueur"] == "2026-08-01",
             "grille HTA CU pointe fixe 2026 : b = 14,85 / 14,85 / 14,85 / 12,93 / 11,56 €/kW/an, CP = 0,04")
    verifier(turpe.grille("BT36", "lu")["cmdps"]["alpha_eur_h"] == 12.79 and turpe.grille("BT36", "lu", "2025-08")["cmdps"]["alpha_eur_h"] == 12.41,
             "BT > 36 kVA : α = 12,79 €/h au 1er août 2026, 12,41 €/h au 1er août 2025")
    ps = [100, 100, 120, 120, 150]
    verifier(proche(turpe.cout_puissance(ps, g["b"]), 14.85 * 100 + 14.85 * 20 + 11.56 * 30),
             "CS puissance : 14,85 x 100 + 14,85 x 20 + 11,56 x 30 = 2 128,80 €/an")
    verifier(proche(turpe.cout_energie([1000, 2000, 3000, 4000, 5000], g["c"]), 284.90), "CS énergie : 284,90 € pour 15 MWh répartis")
    for mauvais, attendu in (([100, 90, 120, 120, 150], "non croissantes"), ([100, 100, 120, 120], "5 puissances"), ([0, 1, 1, 1, 1], "au moins 1 kW")):
        try:
            turpe.controler_puissances(mauvais, "HTA")
            verifier(False, f"puissances {mauvais} refusées")
        except ValueError as erreur:
            verifier(attendu in str(erreur), f"puissances {mauvais} refusées : {attendu}")
    try:
        turpe.controler_puissances([36, 40, 40, 40], "BT36")
        verifier(False, "BT > 36 kVA : 36 kVA refusé")
    except ValueError as erreur:
        verifier("au moins 37" in str(erreur), "BT > 36 kVA : 36 kVA refusé, le domaine commence à 37 kVA")

    # CMDPS HTA : un mois, classe hph, trois pas de 10 minutes à 130, 120, 110 kW pour 100 kW souscrits.
    valeurs, classes, mois = [130, 120, 110, 90], [1, 1, 1, 1], ["2026-01"] * 4
    d = turpe.cmdps_mensuelle(valeurs, classes, mois, [100] * 5, "HTA", g["b"], g["cmdps"], 10)
    attendu = 0.04 * 14.85 * math.sqrt(900 + 400 + 100)
    verifier(proche(d["total_eur"], attendu) and d["par_mois"]["2026-01"]["hph"]["heures"] == 0.5 and d["par_mois"]["2026-01"]["hph"]["depassement_max"] == 30,
             f"CMDPS HTA au pas de 10 min : 0,04 x 14,85 x √1 400 = {attendu:.2f} €, 0,5 h de dépassement, 30 kW au plus")
    d15 = turpe.cmdps_mensuelle(valeurs, classes, mois, [100] * 5, "HTA", g["b"], g["cmdps"], 15)
    verifier(proche(d15["total_eur"], 0.04 * 14.85 * math.sqrt(1400 * 1.5)), "CMDPS HTA au pas de 15 min : chaque valeur compte pour 1,5 pas de 10 min dans la somme des carrés")
    gb = turpe.grille("BT36", "cu")
    db = turpe.cmdps_mensuelle(valeurs, [0] * 4, mois, [100] * 4, "BT36", gb["b"], gb["cmdps"], 10)
    verifier(proche(db["total_eur"], 12.79 * 0.5), "CMDPS BT > 36 kVA : 3 pas de 10 min au-dessus, 12,79 x 0,5 h = 6,40 €")
    db2 = turpe.cmdps_mensuelle(valeurs, [0] * 4, mois, [100] * 4, "BT36", gb["b"], gb["cmdps"], 10, facteur_puissance=0.8)
    verifier(proche(db2["total_eur"], 12.79 * 4 / 6), "BT > 36 kVA avec cos φ 0,8 : 90 kW valent 112,5 kVA, quatre pas dépassent, 12,79 x 0,667 h")

    # Optimisation : le mois de juillet 2026 au pas de 10 min, 100 kW le jour, 80 kW la nuit, un seul pas à 150 kW le 6 juillet
    # à 10 h. Les bi sont annuels : ramenés au mois (31/365), 50 kW de plus coûtent 12,93 x 50 x 31/365 = 54,91 €, contre une
    # CMDPS de 0,04 x 12,93 x √(50²) = 25,86 € pour ce seul dépassement : il vaut mieux garder 100 kW et payer le dépassement.
    debuts, valeurs = [], []
    t = datetime(2026, 7, 1)
    for i in range(31 * 144):
        d0 = t + timedelta(minutes=10 * i)
        nuit = d0.hour >= 22 or d0.hour < 6
        valeurs.append(80.0 if nuit else 150.0 if (d0.day == 6 and d0.hour == 10 and d0.minute == 0) else 100.0)
        debuts.append(d0)
    classes = turpe.classes_profil(debuts, "HTA", "cu_pointe_fixe")
    verifier(sorted(set(classes)) == [3, 4], "profil de juillet : seulement les classes hpb et hcb")
    mois = [d0.strftime("%Y-%m") for d0 in debuts]
    fraction = turpe.fraction_annee(len(valeurs), 10 / 60)
    verifier(proche(fraction, 31 / 365, 1e-9), "31 jours couverts : 31/365 de l'année")
    opt = turpe.optimiser_puissances(valeurs, classes, mois, "HTA", "cu_pointe_fixe", 10, fraction=fraction)
    verifier(opt["ps"] == [1, 1, 1, 100, 100] and opt["classes_sans_mesure"] == ["pointe", "hph", "hch"],
             f"optimum : {opt['ps']} (100 kW en saison basse, un dépassement de 10 min moins cher que 50 kW de plus) ; classes sans mesure signalées")
    cmdps_attendu = 0.04 * 12.93 * 50
    puissance_attendue = (14.85 + 12.93 * 99) * 31 / 365
    verifier(proche(opt["detail"]["cmdps_eur"], cmdps_attendu) and proche(opt["cout_puissance_cmdps_eur"], puissance_attendue + cmdps_attendu),
             f"coût puissance + CMDPS à l'optimum : (14,85 + 12,93 x 99) x 31/365 + {cmdps_attendu:.2f} = {puissance_attendue + cmdps_attendu:.2f} €")
    exact = min((turpe.cout_total(valeurs, classes, mois, [1, 1, 1, p, p], "HTA", "cu_pointe_fixe", 10, fraction=fraction)["total_eur"], p) for p in range(90, 152))
    verifier(exact[1] == 100 and proche(exact[0] - opt["detail"]["energie_eur"], opt["cout_puissance_cmdps_eur"]),
             "recherche exhaustive de 90 à 151 kW : même optimum que la programmation dynamique")
    sans = turpe.cout_total(valeurs, classes, mois, [1, 1, 1, 150, 150], "HTA", "cu_pointe_fixe", 10, fraction=fraction)
    verifier(sans["cmdps_eur"] == 0 and proche(sans["puissance_eur"] - opt["detail"]["puissance_eur"], 12.93 * 50 * 31 / 365),
             "150 kW souscrits : aucun dépassement, mais 54,91 € de puissance en plus sur le mois")
    borne = turpe.optimiser_puissances(valeurs, classes, mois, "HTA", "cu_pointe_fixe", 10, puissance_max=95, fraction=fraction)
    verifier(borne["ps"][3] == 95 and borne["ps"][4] == 95, "puissance de raccordement de 95 kW : l'optimum est borné à 95")
    comp = turpe.comparer_options(valeurs, debuts, "HTA", 10)
    # Sur un mois d'été, la longue utilisation gagne : c4 = 0,95 contre 1,04 c€/kWh sur 49,6 MWh (44,64 € de moins) pèse plus que
    # ses bi plus élevés (17,3 € de plus sur la puissance).
    cu, lu = comp["options"]["cu_pointe_fixe"]["detail"], comp["options"]["lu_pointe_fixe"]["detail"]
    # Énergies par classe : les 4 dimanches de juillet 2026 sont entièrement en heures creuses en HTA (4 x 16 h x 100 kW = 6 400 kWh
    # passent de hpb à hcb) : hpb = 27 x 16 x 100 + 10 min à 150 - 100 = 43 208,3 kWh, hcb = 31 x 8 x 80 + 6 400 = 26 240 kWh.
    e_hpb, e_hcb = cu["energies_kwh"][3], cu["energies_kwh"][4]
    verifier(proche(e_hpb, 27 * 16 * 100 + 50 / 6, 0.1) and proche(e_hcb, 31 * 8 * 80 + 6400, 0.1),
             f"énergies par classe avec la règle du dimanche : hpb {e_hpb:.1f} kWh, hcb {e_hcb:.1f} kWh")
    verifier(comp["meilleure"] == "lu_pointe_fixe" and not comp["options"]["cu_pointe_mobile"]["disponible"]
             and comp["options"]["cu_pointe_fixe"]["ps"] == [1, 1, 1, 100, 100] and comp["options"]["lu_pointe_fixe"]["ps"] == [1, 1, 1, 100, 100]
             and proche(cu["energie_eur"] - lu["energie_eur"], (1.04 - 0.95) / 100 * e_hpb + (0.71 - 0.70) / 100 * e_hcb, 0.05)
             and proche(lu["puissance_eur"] - cu["puissance_eur"], ((36.40 - 14.85) + (14.77 - 12.93) * 99) * 31 / 365, 0.05)
             and lu["total_eur"] < cu["total_eur"],
             "comparaison des options : longue utilisation la moins chère sur un mois d'été (41,51 € d'énergie en moins contre 17,30 € de puissance en plus), pointe mobile indisponible sans les jours RTE")
    bt = turpe.optimiser_puissances(valeurs, turpe.classes_profil(debuts, "BT36", "cu"), mois, "BT36", "cu", 10, fraction=fraction)
    verifier(bt["ps"] == [37, 37, 100, 100] and proche(bt["detail"]["cmdps_eur"], 12.79 / 6),
             f"BT > 36 kVA : optimum {bt['ps']}, 37 kVA minimum pour les classes sans mesure, CMDPS 12,79 x 1/6 h")
    try:
        turpe.optimiser_puissances(valeurs, classes, mois, "HTA", "cu_pointe_fixe", 10, fraction=0)
        verifier(False, "fraction nulle refusée")
    except ValueError:
        verifier(True, "fraction nulle refusée")
    verifier(turpe.date_grille(date(2026, 7, 31)) == "2025-08" and turpe.date_grille(date(2026, 8, 1)) == "2026-08" and turpe.date_grille() == "2026-08",
             "grille en vigueur : 2025-08 jusqu'au 31/07/2026, 2026-08 depuis le 1er août 2026")
    try:
        turpe.date_grille(date(2025, 7, 1))
        verifier(False, "date avant TURPE 7 refusée")
    except ValueError:
        verifier(True, "date avant le 1er août 2025 : aucune grille, refusé")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_pas_quinze_minutes_ne_borne_pas_la_facture(self):
        # Même signal physique, moyenné séparément à 10 et 15 min, pas de reconstruction inventée.
        for puissances, sens in (([200, 0, 200, 0, 200, 0], "surestime"),
                                 ([0, 0, 200, 200, 0, 0], "sous_estime")):
            montants = {}
            for pas in (10, 15):
                taille = pas // 5
                moyennes = [sum(puissances[i:i + taille]) / taille for i in range(0, 6, taille)]
                montants[pas] = turpe.cmdps_mensuelle(moyennes, [0] * len(moyennes),
                    ["2026-01"] * len(moyennes), [100] * 5, "HTA", [10] * 5, {"cp": 0.04}, pas)["total_eur"]
            if sens == "surestime":
                self.assertEqual(montants[10], 0)
                self.assertAlmostEqual(montants[15], 16.329931618554525)
            else:
                self.assertEqual(montants[15], 0)
                self.assertEqual(montants[10], 40)

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
