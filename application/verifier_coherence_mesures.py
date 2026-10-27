"""Contrôles de la cohérence profil / facture. Aucun réseau, aucun fichier."""
from __future__ import annotations

import sys
import unittest

import coherence_mesures as cm


def _dates(mesures: int = 96 * 30, annee: int = 2026, mois: int = 9) -> list[str]:
    """Fins de quart d'heure couvrant le mois, convention de l'application."""
    import datetime
    from zoneinfo import ZoneInfo
    t0 = datetime.datetime(annee, mois, 1, tzinfo=ZoneInfo("Europe/Amsterdam"))
    return [(t0 + datetime.timedelta(minutes=15 * (i + 1))).isoformat() for i in range(mesures)]


def _complet(d: dict) -> dict:
    return {**d, "profil_horodatages": _dates(len(d["profil_brut"])), "mois_facture": "2026-09"}


def _profil_kwh(pointe_kw: float, mesures: int = 96 * 30) -> list[float]:
    """Un mois de kWh par quart d'heure, avec une pointe connue."""
    base = pointe_kw / 2 / 4
    valeurs = [base] * mesures
    valeurs[500] = pointe_kw / 4
    return valeurs


def test_unite_absente_bloque():
    assert cm.controler_unite([1.0], None, 100.0)["statut"] == "bloque"


def test_kwh_declare_correctement_passe():
    r = cm.controler_unite(_profil_kwh(400.0), "kwh_par_quart", 400.0)
    assert r["statut"] == "constat", r


def test_kwh_lu_comme_kw_est_attrape():
    """L'erreur du facteur 4 : on dirait au client qu'il a de la marge."""
    r = cm.controler_unite(_profil_kwh(400.0), "kw", 400.0)
    assert r["statut"] == "bloque"
    assert "quart du kWmax" in r["constat"], r["constat"]


def test_kw_lu_comme_kwh_est_attrape():
    profil_kw = [200.0] * 96
    profil_kw[10] = 400.0
    r = cm.controler_unite(profil_kw, "kwh_par_quart", 400.0)
    assert r["statut"] == "bloque" and "quatre fois" in r["constat"]


def test_correction_de_pertes_acceptee_si_mesure_hors_livraison():
    """1,4 % de pertes (DAT-005) : accepté seulement si la mesure est côté BT."""
    r = cm.controler_unite(_profil_kwh(400.0), "kwh_par_quart", 400.0 * 1.014, False)
    assert r["statut"] == "constat" and r["valeurs"]["correspondance"] == "corrigée des pertes", r


def test_ecart_de_pertes_sans_information_bloque_et_le_dit():
    r = cm.controler_unite(_profil_kwh(400.0), "kwh_par_quart", 400.0 * 1.014, None)
    assert r["statut"] == "bloque" and "correction de pertes" in r["constat"]


def test_arrondi_de_facture_accepte_mais_pas_plus():
    """Meetcode 2.4.5 : même compteur, on retrouve le kWmax à l'arrondi près."""
    assert cm.controler_unite(_profil_kwh(400.0), "kwh_par_quart", 400.9)["statut"] == "constat"
    assert cm.controler_unite(_profil_kwh(400.0), "kwh_par_quart", 410.0)["statut"] == "bloque"


def test_energie_entre_precision_et_borne_alerte():
    kwh = _profil_kwh(400.0)
    kw = cm.en_kw(kwh, "kwh_par_quart")
    assert cm.controler_energie(kw, sum(kwh) * 1.03)["statut"] == "alerte"
    assert cm.controler_energie(kw, sum(kwh) * 1.07)["statut"] == "bloque"


def test_periode_de_facture_non_calendaire():
    """Facture du 15 au 14 : un mois calendaire donnerait un faux écart garanti."""
    import datetime
    from zoneinfo import ZoneInfo
    t0 = datetime.datetime(2026, 8, 15, tzinfo=ZoneInfo("Europe/Amsterdam"))
    dates = [(t0 + datetime.timedelta(minutes=15 * (i + 1))).isoformat() for i in range(96 * 31)]
    ok = cm.controler_periode(dates, ("2026-08-15", "2026-09-14"), len(dates))
    assert ok["statut"] == "constat", ok
    faux = cm.controler_periode(dates, ("2026-08-01", "2026-08-31"), len(dates))
    assert faux["statut"] == "bloque"


def test_sans_facture_l_unite_n_est_pas_verifiee():
    r = cm.controler_unite(_profil_kwh(400.0), "kwh_par_quart", None)
    assert r["statut"] == "bloque" and "facteur 4" in r["constat"]


def test_energie_coherente_avec_la_facture():
    kwh = _profil_kwh(400.0)
    kw = cm.en_kw(kwh, "kwh_par_quart")
    r = cm.controler_energie(kw, sum(kwh))
    assert r["statut"] == "constat", r


def test_mois_incomplet_bloque_sur_l_energie():
    kwh = _profil_kwh(400.0)
    kw = cm.en_kw(kwh, "kwh_par_quart")
    r = cm.controler_energie(kw[: len(kw) // 2], sum(kwh))
    assert r["statut"] == "bloque"


def test_puissance_non_fiable_tant_que_l_unite_n_est_pas_confirmee():
    d = _complet({"profil_brut": _profil_kwh(400.0), "unite_profil": "kw", "kwmax_facture": 400.0})
    assert not cm.puissance_fiable(cm.executer(d))
    d["unite_profil"] = "kwh_par_quart"
    assert cm.puissance_fiable(cm.executer(d))


def test_le_registre_refuse_la_marge_sur_une_unite_fausse():
    """Bout en bout : kWh lus comme kW, la marge ne doit JAMAIS sortir."""
    import controles
    d = _complet({"profil_brut": _profil_kwh(400.0), "unite_profil": "kw",
                  "kwmax_facture": 400.0, "gtv_kw": 350.0})
    marge = next(r for r in controles.executer_tous(d) if r["id"] == "CTRL-MARGE")
    assert marge["statut"] == "bloque", marge
    d["unite_profil"] = "kwh_par_quart"
    marge = next(r for r in controles.executer_tous(d) if r["id"] == "CTRL-MARGE")
    assert marge["statut"] == "alerte" and marge["valeurs"]["pointe_kw"] == 400.0, marge


def test_le_rapport_met_la_fiabilite_des_mesures_en_tete():
    import rapport_controles
    d = _complet({"profil_brut": _profil_kwh(400.0), "unite_profil": "kw",
                  "kwmax_facture": 400.0, "gtv_kw": 350.0})
    texte = rapport_controles.en_texte(rapport_controles.composer(d))
    assert "MESURES NON VÉRIFIÉES" in texte
    assert texte.index("FIABILITÉ DES MESURES") < texte.index("RACCORDEMENT ET CAPACITÉ")
    d["unite_profil"] = "kwh_par_quart"
    d["kwh_facture"] = sum(_profil_kwh(400.0))
    d["mesure_au_point_de_livraison"] = True
    texte = rapport_controles.en_texte(rapport_controles.composer(d))
    assert "MESURES NON VÉRIFIÉES" not in texte and "Unité confirmée" in texte


def test_mois_incomplet_bloque_avant_l_unite():
    """Un export de deux semaines rate la pointe : ce n'est PAS une erreur d'unite."""
    profil = _profil_kwh(400.0)[: 96 * 14]
    d = {"profil_brut": profil, "profil_horodatages": _dates(len(profil)),
         "mois_facture": "2026-09", "unite_profil": "kwh_par_quart", "kwmax_facture": 400.0}
    r = cm.executer(d)
    assert r[0]["id"] == "COH-PERIODE" and r[0]["statut"] == "bloque"
    assert not cm.puissance_fiable(r)
    assert "quart du kWmax" not in " ".join(x["constat"] for x in r)


def test_mois_d_un_autre_export_bloque():
    d = {"profil_brut": _profil_kwh(400.0), "profil_horodatages": _dates(96 * 30, 2026, 9),
         "mois_facture": "2026-08", "unite_profil": "kwh_par_quart", "kwmax_facture": 400.0}
    assert cm.executer(d)[0]["statut"] == "bloque"


def test_sans_dates_la_puissance_n_est_pas_fiable():
    d = {"profil_brut": _profil_kwh(400.0), "unite_profil": "kwh_par_quart", "kwmax_facture": 400.0}
    assert not cm.puissance_fiable(cm.executer(d))


def load_tests(chargeur, suite, motif):
    """Inclut aussi ces anciens tests fonctionnels dans la découverte unittest."""
    return unittest.TestSuite(unittest.FunctionTestCase(v) for k, v in sorted(globals().items()) if k.startswith("test_"))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    echecs = 0
    for test in tests:
        try:
            test()
            print(f"OK   {test.__name__}")
        except AssertionError as erreur:
            echecs += 1
            print(f"ECHEC {test.__name__} : {erreur}")
    print(f"\n{len(tests) - echecs}/{len(tests)} contrôles passés.")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
