"""Contrôles de la chaîne du diagnostic gratuit, sur un export écrit en local."""
from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path

import diagnostic
import serveur


def _fiche(dossier: Path, unite: str) -> dict:
    from zoneinfo import ZoneInfo
    t0 = datetime.datetime(2026, 8, 1, tzinfo=ZoneInfo("Europe/Amsterdam"))
    valeurs = [50.0] * (96 * 31)
    valeurs[700] = 100.0  # 100 kWh sur un quart d'heure = 400 kW
    lignes = ["fin_intervalle,puissance_kw"] + [
        f"{(t0 + datetime.timedelta(minutes=15 * (i + 1))).isoformat()},{v}"
        for i, v in enumerate(valeurs)]
    export = dossier / "export.csv"
    export.write_text("\n".join(lignes))
    fiche = diagnostic.modele()
    fiche["export_profil"] = str(export)
    for champ, valeur in {"gtv_kw": 350, "gtv_declare_kw": 350, "kwmax_facture": 400,
                          "kwh_facture": sum(valeurs), "unite_profil": unite,
                          "meetbedrijf": "Fudura",
                          "periode_facture_debut": "2026-08-01",
                          "periode_facture_fin": "2026-08-31"}.items():
        fiche["valeurs"][champ]["valeur"] = valeur
    return fiche


def test_fiche_sans_origine_refusee():
    with tempfile.TemporaryDirectory() as d:
        fiche = _fiche(Path(d), "kwh_par_quart")
        fiche["valeurs"]["gtv_kw"]["source_document"] = ""
        assert any("de quel document" in p for p in diagnostic.valider(fiche))


def test_rapport_juste_avec_la_bonne_unite():
    with tempfile.TemporaryDirectory() as d:
        texte = (diagnostic.produire(_fiche(Path(d), "kwh_par_quart"), Path(d) / "sortie")
                 .with_suffix(".txt").read_text())
        assert "pointe 400.0 kW" in texte and "MESURES NON VÉRIFIÉES" not in texte
        assert "profil_brut" not in texte


def test_mauvaise_unite_aucune_marge_annoncee():
    """La promesse faite au client : jamais de marge inventée."""
    with tempfile.TemporaryDirectory() as d:
        texte = (diagnostic.produire(_fiche(Path(d), "kw"), Path(d) / "sortie")
                 .with_suffix(".txt").read_text())
        assert "MESURES NON VÉRIFIÉES" in texte
        assert "Pointe quart-horaire du profil" not in texte


def test_periode_facture_sans_source_refusee():
    with tempfile.TemporaryDirectory() as d:
        fiche = _fiche(Path(d), "kwh_par_quart")
        fiche["valeurs"]["periode_facture_fin"]["source_document"] = " "
        assert any("periode_facture_fin" in p for p in diagnostic.valider(fiche))


def test_export_generique_nl_colonnes_decimal_comma_et_marqueur_debut():
    texte = "tijd;afname\n2026-08-01T00:00:00+02:00;1,25\n2026-08-01T00:15:00+02:00;2,50"
    valeurs, dates = serveur.lire_export(texte, {
        "colonne_temps": "tijd", "colonne_valeur": "afname", "format_temps": "ISO8601", "separateur": ";",
        "decimal": ",", "milliers": ".", "fuseau": "Europe/Amsterdam",
        "horodatage_marque": "debut", "meetbedrijf": "Fudura", "kanaal": "afname"})
    assert valeurs == [1.25, 2.5]
    assert dates[0] == "2026-08-01T00:15:00+02:00"


def test_export_refuse_heure_locale_ambigue_au_retour_heure_hiver():
    texte = "tijd;afname\n2026-10-25T02:00:00;1"
    try:
        serveur.lire_export(texte, {
            "colonne_temps": "tijd", "colonne_valeur": "afname", "format_temps": "ISO8601", "separateur": ";",
            "decimal": ".", "milliers": "aucun", "fuseau": "Europe/Amsterdam",
            "horodatage_marque": "fin", "meetbedrijf": "Fudura", "kanaal": "afname"})
    except ValueError as erreur:
        assert "ambiguë" in str(erreur)
    else:
        raise AssertionError("Une heure répétée ne doit jamais être devinée")


def test_export_reel_non_configure_n_est_pas_reconnu():
    try:
        serveur.lire_export("timestamp;Verbruik\n2026-08-01T00:15:00+02:00;1,25")
    except ValueError as erreur:
        assert "Déclarer les colonnes" in str(erreur)
    else:
        raise AssertionError("Aucun format fournisseur n'est confirmé par une fixture réelle")


def test_export_dst_neerlandais_accepte_92_quarts():
    import datetime as dt
    from zoneinfo import ZoneInfo
    depart = dt.datetime(2026, 3, 28, 23, 15, tzinfo=dt.timezone.utc)
    lignes = ["tijd;afname"]
    for i in range(92):
        instant = depart + dt.timedelta(minutes=15 * i)
        local = instant.astimezone(ZoneInfo("Europe/Amsterdam"))
        lignes.append(f"{local.isoformat()};1,25")
    valeurs, dates = serveur.lire_export("\n".join(lignes), {
        "colonne_temps": "tijd", "colonne_valeur": "afname", "format_temps": "ISO8601", "separateur": ";",
        "decimal": ",", "milliers": "aucun", "fuseau": "Europe/Amsterdam",
        "horodatage_marque": "fin", "meetbedrijf": "Fudura", "kanaal": "afname"})
    assert len(valeurs) == 92 and dates[8].endswith("+02:00")
    depart = dt.datetime(2026, 10, 24, 22, 15, tzinfo=dt.timezone.utc)
    lignes = ["tijd;afname"]
    for i in range(100):
        local = (depart + dt.timedelta(minutes=15 * i)).astimezone(ZoneInfo("Europe/Amsterdam"))
        lignes.append(f"{local.isoformat()};1,25")
    valeurs, _ = serveur.lire_export("\n".join(lignes), {
        "colonne_temps": "tijd", "colonne_valeur": "afname", "format_temps": "ISO8601", "separateur": ";",
        "decimal": ",", "milliers": "aucun", "fuseau": "Europe/Amsterdam",
        "horodatage_marque": "fin", "meetbedrijf": "Fudura", "kanaal": "afname"})
    assert len(valeurs) == 100


def test_debut_d_intervalle_normalise_apres_le_saut_d_heure():
    texte = ("tijd;afname\n2026-03-29T01:45:00+01:00;1,25\n"
             "2026-03-29T03:00:00+02:00;2,50")
    valeurs, dates = serveur.lire_export(texte, {
        "colonne_temps": "tijd", "colonne_valeur": "afname", "format_temps": "ISO8601",
        "separateur": ";", "decimal": ",", "milliers": "aucun",
        "fuseau": "Europe/Amsterdam", "horodatage_marque": "debut",
        "meetbedrijf": "Fudura", "kanaal": "afname"})
    assert dates == ["2026-03-29T03:00:00+02:00", "2026-03-29T03:15:00+02:00"]
    assert valeurs == [1.25, 2.5]


def test_export_valeur_avec_milliers_declaree():
    valeurs, _ = serveur.lire_export("tijd;afname\n2026-08-01T00:00:00+02:00;1.234,50", {
        "colonne_temps": "tijd", "colonne_valeur": "afname", "format_temps": "ISO8601", "separateur": ";",
        "decimal": ",", "milliers": ".", "fuseau": "Europe/Amsterdam",
        "horodatage_marque": "fin", "meetbedrijf": "Fudura", "kanaal": "afname"})
    assert valeurs == [1234.5]


def test_fiche_enexis_pointe_le_maximum_du_mois_pas_de_la_semaine():
    fiche = diagnostic.modele("Enexis")
    assert "vermogen maand" in fiche["valeurs"]["kwmax_facture"]["source_document"]
    assert "JAMAIS" in fiche["valeurs"]["kwmax_facture"]["source_document"]
    assert "HEBDOMADAIRE" in fiche["avertissement"]


def test_fiche_stedin_additionne_laag_et_normaal():
    fiche = diagnostic.modele("stedin")
    assert "Verbruik normaal" in fiche["valeurs"]["kwh_facture"]["source_document"]


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
