"""Contrôles des contrôles de contrat. Aucun réseau, aucun fichier."""
from __future__ import annotations

import sys

import catalogue
import controles_contrat as cc


def _plat(profil_kw: float, mesures: int = 96) -> list[float]:
    return [profil_kw] * mesures


def test_marge_bloque_sans_gtv():
    r = cc.marge_contractuelle(_plat(100), None)
    assert r["statut"] == "bloque"
    assert r["constat"] is None
    assert any("GTV" in m for m in r["manque"])


def test_marge_constat_sans_depassement():
    profil = _plat(100)
    profil[42] = 180.0
    r = cc.marge_contractuelle(profil, 200.0)
    assert r["statut"] == "constat"
    assert r["valeurs"]["pointe_kw"] == 180.0
    assert r["valeurs"]["marge_kw"] == 20.0
    assert r["valeurs"]["nombre_quarts_en_depassement"] == 0


def test_marge_alerte_avec_depassement():
    profil = _plat(100)
    profil[10] = 250.0
    r = cc.marge_contractuelle(profil, 200.0)
    assert r["statut"] == "alerte"
    assert r["valeurs"]["marge_kw"] == -50.0
    assert r["valeurs"]["nombre_quarts_en_depassement"] == 1


def test_gtv_maximal_applique_le_facteur_du_reglement():
    r = cc.gtv_maximal(1000.0, "soutirage")
    assert r["valeurs"]["gtv_max_kw"] == 850.0
    r = cc.gtv_maximal(1000.0, "injection")
    assert r["valeurs"]["gtv_max_kw"] == 1000.0


def test_gtv_maximal_bloque_sans_capacite():
    assert cc.gtv_maximal(None)["statut"] == "bloque"


def test_gtv_maximal_refuse_une_direction_inconnue():
    try:
        cc.gtv_maximal(1000.0, "stockage")
    except ValueError:
        return
    raise AssertionError("Une direction inconnue doit lever une erreur.")


def test_ecart_gtv_bloque_avec_un_seul_chiffre():
    assert cc.ecart_gtv_declare(15000.0, None)["statut"] == "bloque"
    assert cc.ecart_gtv_declare(None, 6500.0)["statut"] == "bloque"


def test_ecart_gtv_signale_la_capacite_perdue():
    r = cc.ecart_gtv_declare(15000.0, 6500.0)
    assert r["statut"] == "alerte"
    assert r["valeurs"]["ecart_kw"] == 8500.0
    assert r["valeurs"]["gtv_opposable_kw"] == 6500.0


def test_depassements_comptent_les_blocs_et_la_serie():
    profil = _plat(100, 96 * 4)
    profil[5] = 300.0           # bloc 1
    profil[96 + 5] = 300.0      # bloc 2
    profil[96 * 3 + 5] = 300.0  # bloc 4
    r = cc.depassements_par_bloc(profil, 200.0)
    assert r["valeurs"]["blocs_en_depassement"] == [1, 2, 4]
    assert r["valeurs"]["plus_longue_serie_blocs"] == 2
    assert r["seuil_contractuel_non_teste"]["manque"].startswith("horodatage")


def test_les_controles_citent_des_entrees_reelles_du_catalogue():
    connues = set(catalogue.charger())
    resultats = cc.executer(profil_kw=_plat(100), gtv_kw=200.0,
                            capacite_aansluiting_kva=1000.0, gtv_declare_kw=180.0)
    assert len(resultats) == 4
    for resultat in resultats:
        assert resultat["contraintes"], resultat["id"]
        for identifiant in resultat["contraintes"]:
            assert identifiant in connues, f"{resultat['id']} cite {identifiant}, absent du catalogue"


def test_executer_bloque_proprement_un_dossier_incomplet():
    resultats = cc.executer(profil_kw=_plat(100))
    assert [r["statut"] for r in resultats] == ["bloque"] * 4
    assert all(r["manque"] for r in resultats)


def test_aucune_entree_du_catalogue_sans_source():
    """Une contrainte sans source ne peut pas etre citee dans un rapport client."""
    entrees = catalogue.charger()
    sans = sorted(i for i, e in entrees.items() if not e.get("source"))
    assert not sans, f"{len(sans)} entree(s) sans source : {sans[:10]}"


def test_aucune_entree_du_catalogue_sans_juridiction():
    entrees = catalogue.charger()
    sans = sorted(i for i, e in entrees.items() if not e.get("juridiction"))
    assert not sans, f"{len(sans)} entree(s) sans juridiction : {sans[:10]}"


def test_le_registre_declare_des_besoins_pour_chaque_controle():
    import controles
    for identifiant, entree in controles.REGISTRE.items():
        assert entree["besoins"], f"{identifiant} ne declare aucun besoin"
        for champ, ou in entree["besoins"].items():
            assert len(ou) > 15, f"{identifiant}: le champ {champ} ne dit pas ou le trouver"


def test_un_dossier_presque_vide_ne_bloque_pas_tout_le_registre():
    """Contre-proposition appliquee : le blocage est par controle, pas par dossier."""
    import controles
    dossier = {"profil_kw": [100.0] * 96, "gtv_kw": 150.0}
    resultats = controles.executer_tous(dossier)
    evalues = [r for r in resultats if r["statut"] != "bloque"]
    assert evalues, "avec profil et GTV seuls, au moins un controle doit sortir un resultat"
    plan = controles.plan_de_deblocage(resultats)
    assert plan and plan[0]["ou_le_trouver"], "le plan de deblocage doit dire ou chercher"


def test_le_rapport_declare_sa_portee_reelle():
    """Un rapport qui se tait sur les regles non testees laisse croire qu'il a tout vu."""
    import couverture, rapport_controles
    bilan = couverture.etablir()
    assert sum(len(v) for v in bilan["par_categorie"].values()) == bilan["total"]
    assert bilan["testees"] < bilan["juridiques"]
    texte = rapport_controles.en_texte(rapport_controles.composer({"profil_kw": [1.0] * 96, "gtv_kw": 2.0}))
    assert "PORTÉE" in texte and "ne vaut pas conformité" in texte


def _avec_faux_champ(statut, **extra):
    """Injecte un champ_communal factice pour tester l'etage 1 sans le vrai module."""
    import types
    faux = types.ModuleType("champ_communal")
    faux.dans_le_champ = lambda dossier, commune: {"statut": statut, "raison": "raison test",
                                                   "citation": "« citation test »", **extra}
    sys.modules["champ_communal"] = faux


def _sans_faux_champ():
    sys.modules.pop("champ_communal", None)


def test_etage_un_hors_champ_ne_montre_pas_le_seuil():
    import controles
    _avec_faux_champ("hors_champ")
    try:
        d = {"profil_kw": [1.0] * 96, "gtv_kw": 2.0, "commune": "Hollands Kroon",
             "hauteur_installation_m": 9.0}
        r = next(x for x in controles.executer_tous(d) if x["id"] == "CTRL-HAUTEUR-COMMUNE")
        assert r["statut"] == "constat", r
        assert "n'y est pas soumis" in r["constat"]
        assert "3.5" not in r["constat"] and "3,5" not in r["constat"]
    finally:
        _sans_faux_champ()


def test_etage_un_indetermine_bloque_sans_chiffre():
    import controles
    _avec_faux_champ("indetermine", manque=[{"champ": "date_mise_en_service",
                                             "ou_le_trouver": "proces-verbal de mise en service"}])
    try:
        d = {"profil_kw": [1.0] * 96, "gtv_kw": 2.0, "commune": "Hollands Kroon",
             "hauteur_installation_m": 9.0}
        r = next(x for x in controles.executer_tous(d) if x["id"] == "CTRL-HAUTEUR-COMMUNE")
        assert r["statut"] == "bloque"
        assert r["manque"][0]["champ"] == "date_mise_en_service"
        assert "3.5" not in r["constat"]
    finally:
        _sans_faux_champ()


def test_etage_un_dans_le_champ_passe_au_seuil():
    import controles
    _avec_faux_champ("dans_le_champ")
    try:
        d = {"profil_kw": [1.0] * 96, "gtv_kw": 2.0, "commune": "Hollands Kroon",
             "hauteur_installation_m": 9.0}
        r = next(x for x in controles.executer_tous(d) if x["id"] == "CTRL-HAUTEUR-COMMUNE")
        assert r["statut"] == "alerte" and "3.50" in r["constat"]
    finally:
        _sans_faux_champ()


def test_lfp_et_li_ion_sont_du_lithium():
    """Regression : LFP sortait hors champ d'une regle qui vise le lithium."""
    import controles
    for chimie in ("LFP", "LiFePO4", "Li-ion", "NMC", "lithium-ion", "NCA"):
        assert controles.est_lithium(chimie) is True, chimie
    for chimie in ("sodium-ion", "flow vanadium", "plomb-acide"):
        assert controles.est_lithium(chimie) is False, chimie
    assert controles.est_lithium("chimie X inconnue") is None
    assert controles.est_lithium("") is None


def test_dordrecht_lfp_deux_mwh_est_dans_le_champ():
    import champ_communal
    d = {"chimie_batterie": "LFP", "capacite_kwh": 2000.0, "date_mise_en_service": None}
    v = champ_communal.dans_le_champ(d, "dordrecht")
    assert v["statut"] != "hors_champ" or "lithium" not in v["raison"], v


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
