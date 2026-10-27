"""Contrôles de l'étage 1 communal (champ_communal.py). Aucun réseau, aucun fichier.

Chaque test correspond à une clause lue dans un texte brut. Le cas type de
Contingency (batterie lithium derrière le compteur, site industriel déjà en
activité) doit sortir HORS CHAMP ou INDÉTERMINÉ, jamais avec un chiffre.
"""
from __future__ import annotations

import sys

import champ_communal as cc


def _hk(**champs):
    base = {"soumis_a_permis": True, "regime_lieu": "bedrijfsmatig"}
    base.update(champs)
    return cc.dans_le_champ(base, "Hollands Kroon")


def _drecht(commune="Dordrecht", **champs):
    base = {"chimie_batterie": "lithium-ion", "capacite_kwh": 2000.0, "date_mise_en_service": None}
    base.update(champs)
    return cc.dans_le_champ(base, commune)


def test_commune_inconnue_est_indeterminee():
    r = cc.dans_le_champ({}, "Veendam")
    assert r["statut"] == "indetermine"
    assert r["manque"][0]["champ"] == "regle_communale"


def test_normalisation_du_nom_via_controles():
    a = cc.dans_le_champ({"chimie_batterie": "sodium"}, "Hendrik-Ido-Ambacht")
    b = cc.dans_le_champ({"chimie_batterie": "sodium"}, "hendrik ido ambacht")
    assert a["statut"] == b["statut"] == "hors_champ"
    assert a["reference"] == "CVDR745351"


def test_hollands_kroon_vergunningsvrij_hors_champ():
    r = _hk(soumis_a_permis=False)
    assert r["statut"] == "hors_champ"
    assert "nadrukkelijk niet van toepassing" in r["citation"]


def test_hollands_kroon_permis_inconnu_bloque_sans_chiffre():
    r = cc.dans_le_champ({"regime_lieu": "bedrijfsmatig"}, "Hollands Kroon")
    assert r["statut"] == "indetermine"
    assert [m["champ"] for m in r["manque"]] == ["soumis_a_permis"]
    assert "3,5" not in str(r) and "3.5" not in str(r)


def test_hollands_kroon_bedrijfsmatig_dans_le_champ():
    r = _hk()
    assert r["statut"] == "dans_le_champ"
    assert r["variante"] == "bedrijfsmatig"
    assert r["en_vigueur_le"] == "2026-07-14"
    assert "achter de meter" in r["citation"]


def test_hollands_kroon_energyhub_non_designe():
    r = _hk(regime_lieu="energyhub", energyhub_designe=False)
    assert r["statut"] == "dans_le_champ"
    assert r["condition_lieu_remplie"] is False
    # depuis d7c7a9a (codex) : la citation du regime est dans citation_variante,
    # et l'etage 2 suspend le seuil (le texte dit « alleen op locaties ... »)
    assert "aangewezen energyhubs" in r["citation_variante"]
    r2 = _hk(regime_lieu="energyhub")
    assert r2["statut"] == "indetermine"
    assert r2["manque"][0]["champ"] == "energyhub_designe"


def test_hollands_kroon_380kv_non_attenant():
    r = _hk(regime_lieu="380kv", perceel_attenant_380kv=False)
    assert r["statut"] == "dans_le_champ" and r["variante"] == "380kv"
    assert r["condition_lieu_remplie"] is False
    assert "op verzoek van de netbeheerder" in r["citation_variante"]


def test_hollands_kroon_regime_inconnu():
    r = _hk(regime_lieu="buitengebied")
    assert r["statut"] == "dans_le_champ"
    assert r["variante"] == "hors_regimes_admis"


def test_drechtsteden_sodium_hors_champ_permis_et_bruit():
    r = _drecht(chimie_batterie="sodium-ion")
    assert r["statut"] == "hors_champ"
    assert "lithiumhoudende" in r["citation"]
    assert "bruit" in r["porte_aussi_sur"]


def test_drechtsteden_sous_1_mwh_hors_champ():
    r = _drecht(capacite_kwh=800.0)
    assert r["statut"] == "hors_champ"
    assert "ondergrens van 1 MWh" in r["citation"]


def test_drechtsteden_dates_d_effet_distinctes():
    dates = {"Dordrecht": "2025-05-30", "Hendrik-Ido-Ambacht": "2025-10-10", "Zwijndrecht": "2025-12-05"}
    for commune, effet in dates.items():
        r = _drecht(commune)
        assert r["statut"] == "dans_le_champ", commune
        assert r["en_vigueur_le"] == effet, commune


def test_drechtsteden_anteriorite_deux_conditions():
    # En service le 01/11/2025 : avant Zwijndrecht (05/12), après Hendrik-Ido-Ambacht (10/10).
    r = _drecht("Zwijndrecht", date_mise_en_service="2025-11-01")
    assert r["statut"] == "indetermine"
    assert r["manque"][0]["champ"] == "conforme_plan_temporaire"
    r = _drecht("Zwijndrecht", date_mise_en_service="2025-11-01", conforme_plan_temporaire=True)
    assert r["statut"] == "hors_champ" and "Overgangsrecht" in r["citation"]
    r = _drecht("Zwijndrecht", date_mise_en_service="2025-11-01", conforme_plan_temporaire=False)
    assert r["statut"] == "dans_le_champ"
    r = _drecht("Hendrik-Ido-Ambacht", date_mise_en_service="2025-11-01", conforme_plan_temporaire=True)
    assert r["statut"] == "dans_le_champ"


def test_drechtsteden_chimie_inconnue_bloque():
    r = cc.dans_le_champ({"capacite_kwh": 2000.0, "date_mise_en_service": None}, "Dordrecht")
    assert r["statut"] == "indetermine"
    assert [m["champ"] for m in r["manque"]] == ["chimie_batterie"]
    assert "45" not in str(r["raison"])


def test_oosterhout_zone_exclue():
    r = cc.dans_le_champ({"date_mise_en_service": None, "zone_nommee": "Everdenberg-Oost"}, "Oosterhout")
    assert r["statut"] == "hors_champ"
    assert "Everdenberg-Oost" in r["citation"]


def test_oosterhout_anteriorite():
    r = cc.dans_le_champ({"date_mise_en_service": "2026-01-15", "zone_nommee": "aucune"}, "Oosterhout")
    assert r["statut"] == "hors_champ"
    assert "nog niet plaatsvinden" in r["citation"]
    r = cc.dans_le_champ({"date_mise_en_service": "2026-06-20", "zone_nommee": "aucune"}, "Oosterhout")
    assert r["statut"] == "dans_le_champ"


def test_oosterhout_manques():
    r = cc.dans_le_champ({}, "Oosterhout")
    assert r["statut"] == "indetermine"
    assert {m["champ"] for m in r["manque"]} == {"date_mise_en_service", "zone_nommee"}


def test_tiel_non_grootschalig_hors_champ():
    r = cc.dans_le_champ({"grootschalig": False}, "Tiel")
    assert r["statut"] == "hors_champ"
    assert "Aucun seuil chiffré" in r["citation"]
    assert cc.dans_le_champ({}, "Tiel")["statut"] == "indetermine"
    assert cc.dans_le_champ({"grootschalig": True}, "Tiel")["statut"] == "dans_le_champ"


def test_best_hors_buitengebied_ou_sans_parc():
    assert cc.dans_le_champ({"zone": "bedrijventerrein", "couplee_parc_pv": True}, "Best")["statut"] == "hors_champ"
    assert cc.dans_le_champ({"zone": "buitengebied", "couplee_parc_pv": False}, "Best")["statut"] == "hors_champ"
    assert cc.dans_le_champ({"zone": "buitengebied", "couplee_parc_pv": True}, "Best")["statut"] == "dans_le_champ"
    r = cc.dans_le_champ({}, "Best")
    assert r["statut"] == "indetermine" and len(r["manque"]) == 2


def test_cas_type_contingency_jamais_un_chiffre():
    """Batterie lithium 500 kWh derrière le compteur, site industriel en activité depuis 2019."""
    cas = {"soumis_a_permis": None, "chimie_batterie": "LFP", "capacite_kwh": 500.0,
           "date_mise_en_service": "2019-03-01", "conforme_plan_temporaire": True,
           "zone_nommee": "aucune", "grootschalig": None, "zone": "bedrijventerrein",
           "couplee_parc_pv": False}
    attendu = {"Hollands Kroon": "indetermine", "Dordrecht": "hors_champ",
               "Hendrik-Ido-Ambacht": "hors_champ", "Zwijndrecht": "hors_champ",
               "Tiel": "indetermine", "Oosterhout": "hors_champ", "Best": "hors_champ"}
    for commune, statut in attendu.items():
        r = cc.dans_le_champ(cas, commune)
        assert r["statut"] == statut, (commune, r["statut"], r["raison"])
        assert r["citation"] and r["reference"]


def test_chaque_ligne_de_la_table_a_reference_et_date():
    for cle, regle in cc.CHAMPS_COMMUNAUX.items():
        assert regle["reference"] and regle["en_vigueur_le"] and regle["citation_date"], cle
        assert regle["brut"].endswith(".txt"), cle


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
