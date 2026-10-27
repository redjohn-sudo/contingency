"""Dimensionnement de batterie à puissance optimisée (dimensionnement_batterie.py) : chiffres connus d'avance.

Cas A : une pointe de 2 h par jour ouvré, recharge complète entre deux pointes. La puissance ne change
rien à l'énergie : l'optimum est la méthode de référence, gain nul.
Cas B : deux pointes d'une heure séparées d'une heure, avec peu de place pour recharger. La puissance
minimale (50 kW) laisse la batterie à moitié rechargée avant la seconde pointe : 57,98 kWh utiles, soit
64,42 kWh nominaux. À 58,56 kW, la recharge est complète et la nominale tombe à 58,56 kWh (moins 9,1 %),
là où la borne d'énergie et la borne de puissance se croisent.
Cas C : deux jours au-dessus du plafond dont le classement par poids (sans rendement) se trompe : le choix
exact des jours décisifs trouve une batterie plus petite que le choix glouton.
"""
import math
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import dimensionnement_batterie as db  # noqa: E402

echecs = []
ETA = math.sqrt(0.90)


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def proche(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()

    # Cas A : pointe de 8 h à 10 h les jours ouvrés, 200 kW sur une base de 100 kW, plafond 150 kW.
    kw, fins = db.profil_synthetique()
    ref = db.dimensionner_reference(kw, 150)
    verifier(ref["faisable"] and ref["puissance_kw"] == 50.0 and proche(ref["utile_kwh"], 100 / ETA),
             f"cas A, référence : 50 kW, {ref['utile_kwh']:.2f} kWh utiles (attendu {100 / ETA:.2f})")
    verifier(proche(ref["nominale_kwh"], 100 / ETA / 0.9) and ref["dimension"] == "energie",
             f"cas A, référence : {ref['nominale_kwh']:.2f} kWh nominaux, bornés par l'énergie")
    opt = db.dimensionner_optimal(kw, 150)
    verifier(opt["gain_kwh"] == 0.0 and proche(opt["nominale_kwh"], ref["nominale_kwh"], 1e-6) and opt["puissance_kw"] == 50.0,
             "cas A, optimal : recharge déjà complète, aucune puissance ne réduit la batterie, référence gardée")
    verifier(opt["evaluations"] <= 40, f"cas A : {opt['evaluations']} évaluations du moteur (au plus 40)")

    # Cas B : pointes 8-9 h et 10-11 h à 200 kW, creux à 50 kW entre les deux, base 100 kW, plafond 150 kW.
    kw_b, fins_b = [], []
    for q in range(14 * 96):
        t = datetime(2021, 1, 4) + timedelta(minutes=15 * q)
        v = 100.0
        if t.weekday() < 5:
            v = 200.0 if t.hour in (8, 10) else 50.0 if t.hour == 9 else 100.0
        kw_b.append(v)
        fins_b.append(t + timedelta(minutes=15))
    ref_b = db.dimensionner_reference(kw_b, 150)
    attendu_utile = 2 * 50 / ETA - 50 * ETA  # deux pointes, une heure de recharge à 50 kW entre les deux
    verifier(proche(ref_b["utile_kwh"], attendu_utile) and proche(ref_b["nominale_kwh"], attendu_utile / 0.9),
             f"cas B, référence : {ref_b['utile_kwh']:.2f} kWh utiles, {ref_b['nominale_kwh']:.2f} nominaux (attendu {attendu_utile:.2f} et {attendu_utile / 0.9:.2f})")
    opt_b = db.dimensionner_optimal(kw_b, 150)
    attendu_opt = 50 / ETA / 0.9  # recharge complète : énergie d'une seule pointe, borne d'énergie = borne de puissance
    verifier(proche(opt_b["nominale_kwh"], attendu_opt) and proche(opt_b["puissance_kw"], attendu_opt, 0.05),
             f"cas B, optimal : {opt_b['nominale_kwh']:.2f} kWh nominaux à {opt_b['puissance_kw']:.2f} kW (attendu {attendu_opt:.2f} pour les deux)")
    verifier(proche(opt_b["gain_kwh"], attendu_utile / 0.9 - attendu_opt) and opt_b["gain_kwh"] / ref_b["nominale_kwh"] > 0.09,
             f"cas B : gain de {opt_b['gain_kwh']:.2f} kWh, soit {opt_b['gain_kwh'] / ref_b['nominale_kwh']:.1%} de la batterie de référence")
    verifier(opt_b["reference"] == ref_b, "cas B : la référence est renvoyée telle quelle à côté de l'optimum")
    sim = db.simuler(kw_b, 150, opt_b["utile_kwh"] * (1 + 1e-6), opt_b["puissance_kw"])
    verifier(sim["tient"] and len(sim["reseau"]) == len(kw_b), "cas B : la batterie optimale tient le plafond en simulation pas à pas")
    sim_ref = db.simuler(kw_b, 150, ref_b["utile_kwh"] * (1 + 1e-6), ref_b["puissance_kw"])
    verifier(sim_ref["tient"], "cas B : la batterie de référence tient aussi le plafond (le moteur reste le même)")
    trop_petite = db.simuler(kw_b, 150, opt_b["utile_kwh"] * 0.9, opt_b["puissance_kw"])
    verifier(not trop_petite["tient"], "cas B : 10 % de capacité en moins, le plafond n'est plus tenu")

    # Cas C : jours décisifs. Jour X (lundi) : 250 kW de 8 h à 9 h puis 260 kW un quart d'heure (127,5 kWh au-dessus, 110 kW
    # de dépassement). Jour Y (mardi) : 295 kW un quart d'heure puis 220 kW une heure (106,25 kWh, 145 kW). Le poids sans
    # rendement classe Y devant X ; la batterie réelle de X (149,3 kWh) dépasse celle de Y (145 kWh).
    kw_c, fins_c = [], []
    for q in range(14 * 96):
        t = datetime(2021, 1, 4) + timedelta(minutes=15 * q)
        v = 100.0
        if t.date() == datetime(2021, 1, 4).date():
            v = 250.0 if t.hour == 8 else 260.0 if (t.hour, t.minute) == (9, 0) else 100.0
        elif t.date() == datetime(2021, 1, 5).date():
            v = 295.0 if (t.hour, t.minute) == (8, 0) else 220.0 if (8, 15) <= (t.hour, t.minute) <= (9, 0) else 100.0
        kw_c.append(v)
        fins_c.append(t + timedelta(minutes=15))
    jd = db.jours_decisifs(kw_c, fins_c, 150, k_max=2, candidats=2)
    verifier(jd["jours_au_dessus"] == 2 and jd["candidats"] == ["2021-01-05", "2021-01-04"],
             "cas C : deux jours au-dessus du plafond, Y classé devant X par le poids")
    k1 = jd["par_k"][0]
    verifier(proche(k1["glouton_kwh"], 127.5 / ETA / 0.9) and proche(k1["exact_kwh"], 145.0) and k1["exact_jours"] == ["2021-01-04"],
             f"cas C, K=1 : glouton {k1['glouton_kwh']:.1f} kWh (retire Y), exact {k1['exact_kwh']:.1f} kWh (retire X), gain {k1['gain_exact_kwh']:.1f}")
    k2 = jd["par_k"][1]
    verifier(k2["glouton_kwh"] == 0.0 and k2["exact_kwh"] == 0.0 and k2["gain_exact_kwh"] == 0.0,
             "cas C, K=2 : les deux jours retirés, plus aucune batterie, gain nul")
    verifier(proche(jd["nominale_kwh"], 149.3, 0.1), f"cas C : batterie de référence {jd['nominale_kwh']:.1f} kWh")

    # Garde-fous.
    for profil, plafond, attendu in (([], 150, "vide"), ([100, -5, 100], 50, "négatives"), ([100, 200], 0, "Plafond"),
                                     ([100, float("nan")], 50, "non finies")):
        try:
            db.dimensionner_reference(profil, plafond)
            verifier(False, f"garde-fou : {attendu}")
        except ValueError as erreur:
            verifier(attendu in str(erreur), f"garde-fou : {attendu} refusé avec un message clair")
    sous = db.dimensionner_optimal([100.0] * 96, 150)
    verifier(sous["nominale_kwh"] == 0.0 and sous["dimension"] == "aucune" and sous["gain_kwh"] == 0.0,
             "profil sous le plafond : batterie nulle, aucune évaluation inutile")
    impossible = db.dimensionner_optimal([200.0] * 96, 150)
    verifier(not impossible["faisable"] and impossible["nominale_kwh"] is None,
             "profil toujours au-dessus du plafond : aucune batterie ne tient, dit tel quel")
    try:
        db.dimensionner_optimal(kw, 150, {"profondeur_decharge": 1.5})
        verifier(False, "hypothèse hors bornes refusée")
    except ValueError as erreur:
        verifier("profondeur_decharge" in str(erreur), "hypothèse hors bornes refusée avec le nom du champ")
    try:
        db.jours_decisifs(kw[:-1], fins, 150)
        verifier(False, "longueurs différentes refusées")
    except ValueError as erreur:
        verifier("horodatages" in str(erreur), "longueurs différentes refusées avec les deux longueurs")

    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
