"""Scan de flexibilité (scan_flex.py, rapport_flex.py) : chiffres connus d'avance et rapport complet.

Profil synthétique de deux semaines : 100 kW en continu, 200 kW de 8 h à 10 h les jours ouvrés. Avec un
plafond de 150 kW, tout se calcule à la main : 10 épisodes de 2 h, 1 000 kWh au-dessus du plafond,
une batterie de 50 kW qui doit stocker 100 kWh divisés par le rendement de décharge. Puis le vrai
site VEA 2708 (2016), dont les chiffres sont ceux publiés dans docs/preuves (pointe 595 kW, 72 kW
au-dessus du plafond des 8 heures). Enfin le rapport : neuf sections, les deux langues, aucune
grandeur sans nature, aucun français dans le rapport néerlandais.
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
from unittest import mock

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import rapport_flex  # noqa: E402
import scan_flex  # noqa: E402

EXEMPLE = ICI.parent / "docs" / "exemples" / "scan-flex"
echecs = []
PDF_IGNORE = []  # raison pour laquelle l'export PDF n'a pas été vérifié (aucun navigateur ici)


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def navigateur_indisponible():
    """Raison pour laquelle aucun navigateur ne peut imprimer ici, ou None s'il y en a un.

    Même choix que rapport_pdf (CONTINGENCY_NAVIGATEUR, sinon Brave, sinon le Chromium de Playwright),
    lancé puis refermé à vide. Seules l'absence de Playwright et l'échec de ce lancement comptent comme
    « indisponible » : toute autre erreur remonte et fait échouer la vérification (constat n°23).
    """
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        return "Playwright n'est pas installé"
    import rapport_pdf
    chemin = rapport_pdf.navigateur()
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch(executable_path=chemin, args=["--headless=new"]) if chemin else p.chromium.launch()
            nav.close()
    except Error as erreur:
        detail = (str(erreur).strip().splitlines() or [type(erreur).__name__])[0]
        return f"lancement impossible de {chemin or 'Chromium de Playwright'} : {detail}"
    return None


def verifier_export_pdf(page_html):
    """Export PDF A4 du rapport (dépôt Flex-e). Ignoré, et dit, seulement si aucun navigateur n'est disponible."""
    raison = navigateur_indisponible()
    if raison:
        PDF_IGNORE.append(raison)
        print(f"ignoré : export PDF, aucun navigateur disponible ici ({raison})")
        return
    import rapport_pdf
    try:
        with tempfile.TemporaryDirectory() as tmp:
            html_fr = Path(tmp) / "r.html"
            html_fr.write_text(page_html, encoding="utf-8")
            pdf = rapport_pdf.html_vers_pdf(html_fr, Path(tmp) / "r.pdf")
            entete, taille = pdf.read_bytes()[:5], pdf.stat().st_size
    except Exception as erreur:  # noqa: BLE001 : un navigateur est là, toute erreur est une régression de l'export
        verifier(False, f"export PDF A4 du rapport : {type(erreur).__name__} : {erreur}")
        return
    verifier(entete == b"%PDF-" and taille > 100_000, f"export PDF A4 du rapport ({taille // 1000} ko)")


def profil_synthetique(jours=14, debut=datetime(2021, 1, 4)):
    """Du lundi 4 au dimanche 17 janvier 2021 : un seul mois, deux semaines entières."""
    kw, fins = [], []
    for q in range(jours * 96):
        t = debut + timedelta(minutes=15 * q)
        pic = t.weekday() < 5 and 8 <= t.hour < 10
        kw.append(200.0 if pic else 100.0)
        fins.append(t + timedelta(minutes=15))
    return kw, fins


def grandeurs(objet):
    """Toutes les grandeurs (dictionnaires avec une nature) d'un résultat, à toute profondeur."""
    if isinstance(objet, dict):
        if "nature" in objet and "valeur" in objet:
            yield objet
        for v in objet.values():
            yield from grandeurs(v)
    elif isinstance(objet, list):
        for v in objet:
            yield from grandeurs(v)


def texte_visible(page):
    sans_style = re.sub(r"<style.*?</style>|<svg.*?</svg>|<code>.*?</code>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", sans_style))


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    PDF_IGNORE.clear()
    kw, fins = profil_synthetique()
    fiche = {"nom": "essai", "gtv_kw": 1200, "categorie_tarifaire": "MS", "plafond_cible_kw": 150}
    r = scan_flex.scanner(kw, fins, fiche)
    o = r["options"]

    ep = r["episodes"]
    verifier(ep["nombre"] == 10 and ep["duree_max_h"] == 2.0, "10 épisodes de 2 h au-dessus de 150 kW")
    verifier(abs(ep["energie_kwh"] - 1000) < 1e-9, "1 000 kWh au-dessus du plafond")
    verifier(r["statistiques"]["energie_mwh"]["unite"] == "MWh/periode", "profil de deux semaines : énergie « sur la période », pas « par an »")

    bat = o["batterie"]
    attendu = 100 / math.sqrt(0.90)
    verifier(bat["faisable"] and abs(bat["capacite_utile_kwh"]["valeur"] - round(attendu, 1)) < 0.11,
             f"batterie : capacité utile {bat['capacite_utile_kwh']['valeur']} kWh, attendu {attendu:.1f}")
    verifier(bat["flex_kw"]["valeur"] == 50.0, "batterie : 50 kW de décharge")
    verifier(max(bat["profil_apres"]) <= 150 + 1e-6, "batterie : profil après mesure sous le plafond sur toute la période")
    verifier(bat["dimensionnement"] == "energie" and abs(bat["capacite_nominale_kwh"]["valeur"] - round(attendu / 0.9, 1)) < 0.11,
             "batterie : 2 h de pointe, c'est l'énergie qui dimensionne (utile / 0,9)")
    nominale = bat["capacite_nominale_kwh"]["valeur"]
    verifier(bat["investissement_eur"]["nature"] == "hypothese"
             and bat["investissement_eur"]["valeur"] == [round(100 * 400 + (nominale - 100) * 350, -2), round(nominale * 700, -2)]
             and bat["investissement_eur"]["source"] == "src_invest_prix_palier",
             "prix par défaut : 400 €/kWh jusqu'à 100 kWh puis 350 €/kWh au-delà, 700 €/kWh en haut, marquée hypothèse")
    # Audit F3 : le prix ne baisse plus d'un coup au seuil de 100 kWh
    hyp_def = {k: v["valeur"] for k, v in scan_flex.HYPOTHESES_DEFAUT.items()}
    bornes = [scan_flex._invest_batterie(n, hyp_def)[0] for n in (95, 100, 100.1, 105)]
    verifier(bornes == sorted(bornes) and bornes[2] >= bornes[1],
             f"prix de batterie continu au seuil de 100 kWh : bornes basses {bornes} croissantes")
    sans_prix = scan_flex.scanner(kw, fins, {**fiche, "hypotheses": {"prix_batterie_eur_kwh": None}})["options"]["batterie"]
    verifier(sans_prix["investissement_eur"]["nature"] == "a_chiffrer" and sans_prix["retour_ans"]["nature"] == "a_chiffrer",
             "prix retiré dans la fiche : investissement et retour restent à chiffrer, aucun nombre inventé")

    dec = o["decalage"]
    verifier(dec["faisable"] and dec["part_reportee"] == 1.0, "décalage : toute l'énergie trouve place dans ± 4 h")
    verifier(max(dec["profil_apres"]) <= 150 + 1e-9, "décalage : profil après mesure sous le plafond")
    verifier(abs(sum(dec["profil_apres"]) - sum(kw)) < 1e-6, "décalage : l'énergie consommée ne change pas")

    ecr = o["ecretage"]
    verifier(abs(ecr["energie_mwh_an"]["valeur"] - 1.0) < 1e-9 and ecr["heures_an"]["valeur"] == 20.0,
             "écrêtage : 1 MWh coupé sur 20 h")

    eco = bat["economie"]
    verifier(eco["kw_mois_evites"] == 50.0 and eco["eur_an"]["valeur"] == round(50 * 3.57),
             "économie : 50 kW-mois évités x 3,57 €/kW/mois (MS, Liander 2026)")
    # Audit O2 : au-delà de 1 MW, l'obligation n'existe que si le gestionnaire l'a annoncée en zone de congestion.
    off = o["offre_gestionnaire"]
    verifier(off["obligation_1mw"]["valeur"] is None and off["obligation_1mw"]["source"] == "src_reg009_a_verifier"
             and off["sanction_sans_offre"]["valeur"] is None and off["sanction_sans_offre"]["parametres"]["montant"] == 144
             and any(l["cle"] == "reco_offre_si_annoncee" for l in r["recommandation"]),
             "GTV de 1 200 kW, annonce inconnue : obligation « à vérifier », aucun montant affirmé (144 €/jour seulement si annoncée)")
    annonce = scan_flex.scanner(kw, fins, {**fiche, "deelnameplicht_annoncee": True})["options"]["offre_gestionnaire"]
    verifier(annonce["obligation_1mw"]["valeur"] is True and annonce["sanction_sans_offre"]["valeur"] == 144
             and annonce["sanction_sans_offre"]["nature"] == "tarif",
             "GTV 1,2 MW, obligation annoncée : 144 € par jour dus sans offre (120 €/MW/jour, ACM)")
    non = scan_flex.scanner(kw, fins, {**fiche, "deelnameplicht_annoncee": False})
    verifier(non["options"]["offre_gestionnaire"]["obligation_1mw"]["valeur"] is False
             and non["options"]["offre_gestionnaire"]["sanction_sans_offre"]["valeur"] == 0
             and any(l["cle"] == "reco_offre_volontaire" for l in non["recommandation"]),
             "GTV 1,2 MW, obligation déclarée non annoncée : pas d'obligation, pas de montant dû")
    try:
        scan_flex.fiche_controlee({"deelnameplicht_annoncee": "oui"})
        refus_annonce = False
    except ValueError as erreur:
        refus_annonce = "deelnameplicht_annoncee" in str(erreur)
    verifier(refus_annonce, "fiche : deelnameplicht_annoncee en texte refusé avec le nom du champ")
    verifier(r["marge_gtv"]["kw"]["valeur"] == 1000.0 and r["marge_gtv"]["regle"] == "gotork",
             "GTV 1 200 kW pour une pointe de 200 kW : 1 000 kW de marge, signalée comme exposée au GOTORK")
    depasse = scan_flex.scanner(kw, fins, {**fiche, "gtv_kw": 180})
    verifier(depasse["marge_gtv"]["regle"] == "depassement" and depasse["options"]["offre_gestionnaire"]["obligation_1mw"]["valeur"] is False,
             "pointe au-dessus du GTV : dépassement signalé (plus d'augmentation automatique), pas d'obligation sous 1 MW")
    try:
        scan_flex.scanner(kw[:-1], fins, fiche)
        verifier(False, "une valeur de moins que d'horodatages : refusé avec les deux longueurs")
    except ValueError as erreur:
        verifier(f"{len(kw) - 1} valeurs pour {len(fins)} horodatages" in str(erreur),
                 "une valeur de moins que d'horodatages : refusé avec les deux longueurs")
    # Remise volledig variabel (FAQ ATR Netbeheer Nederland) : terme kW contracté à zéro entre le plafond visé et le GTV.
    remise = o["contrat"]["remise_eur_an"]
    verifier(remise["valeur"] == round(1050 * 27.48) and remise["nature"] == "simule" and remise["parametres"]["kw"] == 1050,
             "remise volledig variabel : (1 200 - 150) kW x 27,48 €/kW/an (MS, Liander 2026) = 28 854 €/an")
    verifier(depasse["options"]["contrat"]["remise_eur_an"]["valeur"] == round(30 * 27.48), "GTV 180 kW, plafond 150 kW : 30 kW x 27,48 = 824 €/an")
    sans_gtv = scan_flex.scanner(kw, fins, {k: v for k, v in fiche.items() if k != "gtv_kw"})["options"]["contrat"]["remise_eur_an"]
    sous = scan_flex.scanner(kw, fins, {**fiche, "gtv_kw": 140})["options"]["contrat"]["remise_eur_an"]
    verifier(sans_gtv["nature"] == "a_completer" and sous["valeur"] == 0 and sous["source"] == "src_remise_gtv_sous_plafond",
             "remise : à compléter sans GTV, nulle quand le GTV ne dépasse pas le plafond visé")
    page_fr, page_nl = rapport_flex.rendre(r, "fr"), rapport_flex.rendre(r, "nl")
    mille_fr = rapport_flex.nombre(1050, "fr")
    verifier(f"{mille_fr} kW entre le plafond visé (150 kW)" in page_fr and f"{rapport_flex.nombre(28854, 'fr')} €/an" in page_fr
             and "1.050 kW tussen de beoogde grens (150 kW)" in page_nl and "28.854 €/jaar" in page_nl,
             "remise rendue en FR et en NL avec son calcul et sa condition")

    # Grilles 2026 par gestionnaire (tarievenbladen ACM) : jamais de mélange, bornes propres à chacun.
    verifier(scan_flex.categorie_tarifaire({"gtv_kw": 130}, 0, "liander")[0] == "TRAFO_MS_LS"
             and scan_flex.categorie_tarifaire({"gtv_kw": 130}, 0, "enexis")[0] == "MS"
             and scan_flex.categorie_tarifaire({"gtv_kw": 130}, 0, "stedin")[0] == "TRAFO_MS_LS",
             "130 kW : Trafo MS/LS chez Liander (jusqu'à 136) et Stedin (jusqu'à 150), MS chez Enexis (au-delà de 125)")
    stedin = scan_flex.scanner(kw, fins, {**fiche, "gestionnaire": "Stedin"})
    verifier(stedin["raccordement"]["gestionnaire_tarifs"] == "stedin"
             and stedin["options"]["batterie"]["economie"]["eur_an"]["valeur"] == round(50 * 3.0966),
             "gestionnaire Stedin : kWmax MS à 3,0966 €/kW/mois")
    stedin_fr = " ".join(texte_visible(rapport_flex.rendre(stedin, "fr")).split())
    verifier("3,0966 €/kW/mois" in stedin_fr and "3,10 €/kW/mois" not in stedin_fr,
             "nombres des sources à pleine précision : tarif Stedin 3,0966 €/kW/mois, pas « 3,10 »")
    verifier(stedin["options"]["contrat"]["remise_eur_an"]["valeur"] == round(1050 * 24.2737),
             "gestionnaire Stedin : remise au terme kW contracté MS de 24,2737 €/kW/an")
    inconnu = scan_flex.scanner(kw, fins, {**fiche, "gestionnaire": "Westland Infra"})
    verifier(inconnu["raccordement"]["gestionnaire_tarifs"] == "liander" and inconnu["raccordement"]["gestionnaire_nature"] == "hypothese",
             "gestionnaire sans grille connue : Liander par défaut, marqué comme hypothèse")
    con = o["contrat"]
    blocs = {b["bloc"]: b for b in con["blocs"]}
    verifier(blocs["nuit"]["pointe_kw"] == 100.0 and blocs["jour_ouvre"]["pointe_kw"] == 200.0 and blocs["week_end_jour"]["pointe_kw"] == 100.0
             and abs(sum(b["part_energie"] for b in con["blocs"]) - 1) < 0.002,
             "blocs horaires : pointe de 200 kW en journée de semaine seulement, parts d'énergie qui somment à 1")
    verifier(con["remise"]["nature"] == "tarif" and con["mise_en_route"]["valeur"] == "preavis_contrat",
             "contrat : remise d'environ 50 % et préavis de la veille, sourcés ACM (30/04/2025)")
    niveau_90 = next(n for n in con["niveaux"] if n["part_pointe"] == 0.9)
    verifier(niveau_90["heures_au_dessus"] == 20.0, "contrat : 20 h au-dessus de 180 kW")

    fiche_prix = {**fiche, "hypotheses": {"prix_batterie_eur_kwh": {"valeur": [300, 500], "source": "essai"}}}
    rp = scan_flex.scanner(kw, fins, fiche_prix)
    inv = rp["options"]["batterie"]["investissement_eur"]
    verifier(inv["nature"] == "hypothese" and inv["valeur"][0] < inv["valeur"][1], "prix fourni : investissement en fourchette, nature hypothèse")
    # Relecture de 05 h 50, défaut 2 : deux semaines d'économie ne font pas une année, pas de retour calculé.
    verifier(rp["options"]["batterie"]["retour_ans"]["nature"] == "a_chiffrer" and rp["options"]["batterie"]["retour_ans"]["source"] == "src_retour_periode",
             "profil de deux semaines : retour sur investissement non calculé (l'économie ne couvre pas une année)")
    verifier(rp["hypotheses"]["prix_batterie_eur_kwh"]["source"] == "essai", "la source d'une hypothèse de la fiche est conservée")

    for mauvaise, message in (({**fiche, "plafond_cible_kw": 250}, "plafond au-dessus de la pointe refusé"),
                              ({**fiche, "hypotheses": {"inventee": 1}}, "hypothèse inconnue refusée")):
        try:
            scan_flex.scanner(kw, fins, mauvaise)
            verifier(False, message)
        except ValueError:
            verifier(True, message)
    try:
        scan_flex.scanner([-5.0] + kw[1:], fins, fiche)
        verifier(False, "valeurs négatives (injection) refusées")
    except ValueError:
        verifier(True, "valeurs négatives (injection) refusées")

    verifier(not scan_flex.annee_representative(fins, datetime(2026, 9, 27))["dans_les_3_ans"]
             and scan_flex.annee_representative(fins, datetime(2024, 1, 1))["dans_les_3_ans"],
             "profil 2021 : trop ancien pour un scan Flex-e en 2026 (plus de trois ans), acceptable en 2024")
    # Horodatages avec fuseau (format Kenter, heure d'Amsterdam) sur une semaine de passage à l'heure d'été.
    from zoneinfo import ZoneInfo
    utc, ams = ZoneInfo("UTC"), ZoneInfo("Europe/Amsterdam")
    fins_ams = [(datetime(2021, 3, 22, tzinfo=utc) + timedelta(minutes=15 * (q + 1))).astimezone(ams) for q in range(14 * 96)]
    kw_ams = [200.0 if (f - timedelta(minutes=15)).weekday() < 5 and 8 <= (f - timedelta(minutes=15)).hour < 10 else 100.0
              for f in fins_ams]
    try:
        r_ams = scan_flex.scanner(kw_ams, fins_ams, {"plafond_cible_kw": 150})
        rapport_flex.rendre(r_ams, "nl")
        verifier(r_ams["episodes"]["nombre"] == 10, "horodatages avec fuseau et passage à l'heure d'été : scan et rapport sans erreur")
    except Exception as erreur:  # noqa: BLE001
        verifier(False, f"horodatages avec fuseau : {type(erreur).__name__} {erreur}")
    verifier(r["croissance"]["liberes_kw"] == 50.0 and r["croissance"]["marge_gtv_kw"] == 1000.0 and r["croissance"]["total_kw"]["valeur"] == 1050.0,
             "capacité de croissance : 50 kW libérés par le plafond plus 1 000 kW libres sous le GTV")
    page_fr = rapport_flex.rendre(r, "fr")
    verifier("Capacité de croissance sans nouvelle demande au réseau" in page_fr and "Financement Flex-e" in page_fr,
             "rapport : capacité de croissance et financement Flex-e affichés")
    # Chemin d'un vrai client : réponse de l'API Kenter (canal 16180, kWh par quart, horodatage Unix UTC de fin
    # de période) -> lecteur_kenter -> CSV interne -> lire_csv -> scan. Deux semaines dont le passage à l'heure
    # d'hiver du 25/10/2026 : 1 348 quarts d'heure.
    import lecteur_kenter
    depart = int(datetime(2026, 10, 18, 22, 0, tzinfo=utc).timestamp())
    mesures = []
    for q in range(14 * 96 + 4):
        fin_ams = datetime.fromtimestamp(depart + 900 * (q + 1), utc).astimezone(ams)
        debut_ams = fin_ams - timedelta(minutes=15)
        kw_q = 200.0 if debut_ams.weekday() < 5 and 8 <= debut_ams.hour < 10 else 100.0
        mesures.append({"origin": "Measured", "status": "Valid", "timestamp": depart + 900 * (q + 1), "value": kw_q / 4})
    lu = lecteur_kenter.lire_kenter([{"channelId": "16180", "Measurements": mesures}])
    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "kenter.csv"
        chemin.write_text(lu["csv"], encoding="utf-8")
        kw_k, fins_k = scan_flex.lire_csv(chemin)
        (Path(tmp) / "kenter.json").write_text(json.dumps([{"channelId": "16180", "Measurements": mesures}]), encoding="utf-8")
        kw_j, fins_j = scan_flex.lire_profil(Path(tmp) / "kenter.json")
    verifier(kw_j == kw_k and fins_j == fins_k, "réponse JSON Kenter passée directement au scan : même profil que le CSV interne")
    # Export de plusieurs années (Liander livre 2023, 2024 et 2025) : fin d'intervalle en heure d'Amsterdam avec
    # fuseau, du 01/01/2023 00:15 au 15/03/2026. Années civiles complètes : 2023, 2024, 2025 ; 2026 incomplète.
    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "trois-ans.csv"
        t0 = datetime(2023, 1, 1, tzinfo=ams).astimezone(utc)
        t_fin = datetime(2026, 3, 15, tzinfo=ams).astimezone(utc)
        n = int((t_fin - t0).total_seconds() // 900)
        lignes = ["fin_intervalle,puissance_kw"]
        for q in range(n):
            fin = (t0 + timedelta(minutes=15 * (q + 1))).astimezone(ams)
            debut = fin - timedelta(minutes=15)
            lignes.append(f"{fin.isoformat()},{200.0 if debut.weekday() < 5 and 8 <= debut.hour < 10 else 100.0}")
        chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        kw3, fins3, sel = scan_flex.lire_profil_annee(chemin)
        kw4, fins4, sel4 = scan_flex.lire_profil_annee(chemin, 2024)
        try:
            scan_flex.lire_profil_annee(chemin, 2026)
            refus_2026 = False
        except ValueError:
            refus_2026 = True
    verifier(sel["completes"] == [2023, 2024, 2025] and sel["choisie"] == 2025 and len(kw3) == 35040,
             "export de trois ans et demi : l'année civile complète la plus récente (2025) est gardée, 35 040 quarts")
    verifier(sel4["choisie"] == 2024 and len(kw4) == 35136 and refus_2026,
             "année imposée par la fiche (2024, bissextile : 35 136 quarts) ; 2026 incomplète refusée")
    r3 = scan_flex.scanner(kw3, fins3, {"plafond_cible_kw": 150, "selection_annee": sel})
    verifier("choisie parmi 2023, 2024, 2025, 2026" in rapport_flex.rendre(r3, "fr"),
             "rapport : année choisie et années disponibles dites")
    r_k = scan_flex.scanner(kw_k, fins_k, {"plafond_cible_kw": 150, "gestionnaire": "liander"})
    verifier(len(kw_k) == 14 * 96 + 4 and r_k["episodes"]["nombre"] == 10 and r_k["episodes"]["duree_max_h"] == 2.0,
             "relevé Kenter (heure d'hiver comprise) -> lecteur -> scan : 10 épisodes de 2 h retrouvés")
    etats = dict(rapport_flex.conformite(r))
    verifier(etats["0"] == "a_faire" and etats["1a"] == "a_completer" and etats["4b"] == "calcule",
             "conformité Flex-e : visite à faire, EAN à compléter, analyse des pics calculée")
    complet = scan_flex.scanner(kw, fins, {**fiche, "ean": "871687400000000000", "sbi": "52.10", "changements_prevus": "aucun",
                                           "processus": "entrepôt frigorifique", "production_propre": "aucune",
                                           "statut_zone_afname": "tekort", "congestierapport": "Liander, 2026",
                                           "autres_energies": "aucune", "preference_entreprise": "décalage",
                                           "heures_activite_an": 6000,
                                           "hypotheses": {"prix_batterie_eur_kwh": {"valeur": [400, 600], "source": "essai"}}})
    etats_complet = dict(rapport_flex.conformite(complet))
    verifier(etats_complet["1a"] == "fourni" and etats_complet["3"] == "fourni" and etats_complet["7p"] == "fourni",
             "conformité Flex-e : fiche complète, les éléments déclarés passent à « fourni »")
    verifier("Où en est ce scan par rapport au format Flex-e" in rapport_flex.rendre(r, "fr")
             and "Stand van deze scan" in rapport_flex.rendre(r, "nl"), "rapport : bilan de conformité Flex-e en tête, FR et NL")
    # Scénario de croissance : +60 kW les jours ouvrés de 7 h à 19 h, GTV 250 kW. La pointe passe à 260 kW :
    # 10 kW de trop chaque jour ouvré entre 8 h et 10 h, soit 10 épisodes de 2 h et 200 kWh au total.
    projet = {**fiche, "gtv_kw": 250, "plafond_cible_kw": None,
              "croissance_prevue": {"kw": 60, "debut": "07:00", "fin": "19:00", "jours": "ouvres", "description": "pompes à chaleur"}}
    rc = scan_flex.scanner(kw, fins, projet)
    sc = rc["scenario_croissance"]
    verifier(not sc["tient_sans_mesure"] and sc["pointe_scenario_kw"] == 260.0 and sc["heures_au_dessus"] == 20.0
             and sc["energie_au_dessus_kwh"] == 200.0, "croissance : 260 kW pour 250, dépassement 20 h et 200 kWh")
    verifier(rc["plafond_kw"]["valeur"] == 250 and rc["options"]["batterie"]["flex_kw"]["valeur"] == 10.0
             and rc["options"]["decalage"]["faisable"], "croissance : les mesures visent la limite du GTV, 10 kW à décaler ou stocker")
    verifier(rc["statistiques"]["pointe_kw"]["valeur"] == 200.0, "croissance : les profils de l'article 4 restent ceux du profil mesuré")
    page_c = rapport_flex.rendre(rc, "fr")
    verifier("Scénario de croissance étudié" in page_c and "avec le projet, avant mesure" in page_c
             and "Onderzocht groeiscenario" in rapport_flex.rendre(rc, "nl"), "croissance : scénario et courbes « avec le projet » rendus, FR et NL")
    traduit = scan_flex.scanner(kw, fins, {**projet, "traductions": {"nl": {"croissance_description": "warmtepompen"}}})
    nl_c = texte_visible(rapport_flex.rendre(traduit, "nl"))
    verifier("warmtepompen" in nl_c and "pompes" not in nl_c, "croissance : description du projet traduite dans le rapport néerlandais")
    synthese = texte_visible(rapport_flex._section_synthese(rc, "fr"))
    verifier("Pointe actuelle de 200 kW" in synthese and "ne dépasse" not in synthese and "260 kW" in synthese,
             "synthèse en mode croissance : profil mesuré d'un côté, projet de l'autre, sans mélange")
    petit = scan_flex.scanner(kw, fins, {**projet, "croissance_prevue": {**projet["croissance_prevue"], "kw": 40}})
    verifier(petit["scenario_croissance"]["tient_sans_mesure"] and "tient déjà sous la limite" in rapport_flex.rendre(petit, "fr"),
             "croissance de 40 kW : tient sous 250 kW sans mesure, et le rapport le dit")
    verifier(petit["plafond_kw"]["source"] == "src_plafond_palier" and petit["plafond_kw"]["valeur"] == 100.0,
             "pointe plate (200 kW pendant 20 h) : plafond au premier palier sous la pointe, source dite")
    sens = r["sensibilite"]
    verifier([f["faisable"] for f in sens["fenetres"]] == [False, True, True, True],
             "sensibilité : pics de 2 h, le décalage de ± 1 h ne suffit pas, ± 2 h et plus suffisent")
    combo = sens["fenetres"][0].get("batterie_complement")
    verifier(combo and combo["faisable"] and combo["puissance_kw"] == 50.0 and combo["utile_kwh"] < bat["capacite_utile_kwh"]["valeur"],
             "combinaison : décalage de ± 1 h plus une batterie pour le reste, plus petite que la batterie seule")
    verifier([c["nominale_kwh"] for c in sens["c_rates"]] == [117.1] * 3 and all(c["dimension"] == "energie" for c in sens["c_rates"]),
             "sensibilité : pics de 2 h, l'énergie dimensionne la batterie à 0,5C, 1C et 2C (117,1 kWh nominaux)")
    verifier("Sensibilité des conclusions" in rapport_flex.rendre(r, "fr") and "Gevoeligheid van de conclusies" in rapport_flex.rendre(r, "nl"),
             "rapport : sensibilité rendue en FR et NL")
    # Cas limites : très petit site (catégorie LS, sans terme kWmax) et grand site de plusieurs MW.
    petit_site = [x * 0.2 for x in kw]            # 20 à 40 kW
    grand_site = [x * 25 for x in kw]             # 2,5 à 5 MW
    rp_ = scan_flex.scanner(petit_site, fins, {"plafond_cible_kw": 30})
    verifier(rp_["raccordement"]["categorie"] == "LS" and rp_["options"]["batterie"]["economie"]["eur_an"]["nature"] == "a_chiffrer"
             and rp_["options"]["batterie"]["retour_ans"]["nature"] == "a_chiffrer",
             "petit site (40 kW) : catégorie LS, pas de terme kWmax, économie et retour à chiffrer sans erreur")
    rp_gtv = scan_flex.scanner(petit_site, fins, {"plafond_cible_kw": 30, "gtv_kw": 45})
    verifier(rp_gtv["options"]["contrat"]["remise_eur_an"]["nature"] == "a_chiffrer", "petit site LS : pas de terme kW contracté, remise à chiffrer")
    rg_ = scan_flex.scanner(grand_site, fins, {"plafond_cible_kw": 3750, "gestionnaire": "stedin", "gtv_kw": 6000,
                                               "deelnameplicht_annoncee": True})
    page_g = rapport_flex.rendre(rg_, "fr")
    verifier(rg_["raccordement"]["categorie"] == "TRAFO_HS_TS_MS" and rg_["options"]["offre_gestionnaire"]["sanction_sans_offre"]["valeur"] == 720
             and "1,250 MW" in page_g, "grand site (5 MW, Stedin, GTV 6 MW) : catégorie HS, 720 € par jour sans offre, MW affichés")
    # Arbitrage day-ahead : deux jours à 10 €/MWh la nuit et 110 €/MWh le jour, batterie 10 kWh, 10 kW, sans
    # pertes : 0,10 € d'achat, 1,10 € de vente, 1 € par jour, soit 365 € ramenés à l'année.
    creneaux = tuple((f"2025-01-0{j}", 1.0, 10.0 if h < 12 else 110.0) for j in (1, 2) for h in range(24))
    arb = scan_flex.arbitrage_annuel(10, 10, 1.0, creneaux)
    verifier(arb["jours"] == 2 and abs(arb["eur_an"] - 365.0) < 1e-9, "arbitrage : 1 € par jour sur une série connue, 365 € par an")
    arb_bat = o["batterie"].get("arbitrage_eur_an", {})
    verifier(arb_bat.get("nature") == "simule" and arb_bat.get("valeur", 0) > 0 and o["batterie"].get("retour_arbitrage_ans"),
             "batterie : arbitrage day-ahead NL 2025 calculé (borne haute) et retour avec arbitrage donné à part")
    verifier(rapport_flex.etapes(r)[0] == "etape_visite" and "etape_1mw" in rapport_flex.etapes(r)
             and "Prochaines étapes" in rapport_flex.rendre(r, "fr") and "Volgende stappen" in rapport_flex.rendre(r, "nl"),
             "prochaines étapes : visite d'abord, obligations au-delà de 1 MW quand le GTV dépasse 1 MW, FR et NL")
    tout = list(grandeurs(r))
    verifier(all(g["nature"] in scan_flex.NATURES for g in tout), f"{len(tout)} grandeurs, toutes avec une nature connue")
    verifier(all(not isinstance(g["valeur"], (int, float)) or isinstance(g["valeur"], bool)
                 for g in tout if g["nature"] in ("a_chiffrer", "a_completer")),
             "aucune grandeur « à chiffrer » ou « à compléter » ne porte de nombre")
    json.dumps(scan_flex.allege(r))
    verifier(True, "résultat allégé sérialisable en JSON")

    # Bijlage 4.12.1 (Flex-e) : articles 1 à 7, dans l'ordre, dans les deux langues.
    for langue, titres in (("fr", ["1. Entreprise et raccordement", "2. Congestion", "3. Processus principaux",
                                   "4. Profil de consommation", "5. Mesures de flexibilité", "6. Analyse financière",
                                   "7. Avantages, inconvénients et conclusion", "8. Hypothèses", "9. Sources"]),
                           ("nl", ["1. Gegevens over de onderneming", "2. Congestieproblematiek", "3. Hoofdprocessen",
                                   "4. Energievraagprofiel", "5. Realistische flexibiliteitsmaatregelen", "6. Financiële analyse",
                                   "7. Voor- en nadelen en conclusie", "8. Aannames", "9. Bronnen"])):
        page = rapport_flex.rendre(r, langue)
        positions = [page.find(t) for t in titres]
        verifier(all(p > 0 for p in positions) and positions == sorted(positions),
                 f"rapport {langue} : les articles 1 à 7 de la bijlage 4.12.1, puis hypothèses et sources, dans l'ordre")
        verifier(page.count("Flex-e, bijlage 4.12.1, art.") == 7, f"rapport {langue} : chaque article renvoie à la bijlage 4.12.1")
        # 5 profils + analyse ; par mesure : 2 graphiques de moments (d) et 4 profils après (f) pour 3 mesures,
        # 2 graphiques de moments pour le contrat.
        verifier(page.count("<svg") >= 5 + 3 * (2 + 4) + 2, f"rapport {langue} : moments (d) et quatre profils après mesure (f) dessinés")
    fr = rapport_flex.rendre(r, "fr")
    verifier("Analyse des pics et des creux" in fr and "entre 08:00 et 10:00" in fr,
             "analyse des pics et creux : les pointes du profil d'essai tombent entre 8 h et 10 h")
    verifier("visite le site" in fr or "visite du site" in fr, "limite : la visite obligatoire du site par l'energieadviseur est dite")
    verifier(r["entreprise"]["ean"]["nature"] == "a_completer" and r["processus"]["description"]["nature"] == "a_completer",
             "EAN et processus non fournis : à compléter, rien d'inventé")
    rp_fr = " ".join(texte_visible(rapport_flex.rendre(rp, "fr")).split())
    verifier("l'économie ne couvre pas une année, retour non calculé" in rp_fr and "€ sur la période" in rp_fr and "€ par an" not in rp_fr,
             "profil de deux semaines : « sur la période » et retour non calculé, jamais « € par an »")
    verifier(scan_flex.tranche_etvt(2.9) == "moins_3" and scan_flex.tranche_etvt(3) == "3_5" and scan_flex.tranche_etvt(16) == "plus_15",
             "tranches ETVT : moins de 3, 3 à 5, 5 à 7, 7 à 15, plus de 15 ans")
    # Fiche complète avec tous les champs déclarés en texte (relecture de 05 h : le rendu plantait sur un EAN).
    complete = {**fiche, "ean": "871687400000000000", "sbi": "52.10", "processus": "froid et quais", "production_propre": "aucune",
                "changements_prevus": "recharge de camions en 2027", "autres_energies": "gaz naturel", "transport_autres": "aucun",
                "preference_entreprise": "décalage d'abord", "tirages_confiance": 0}
    rendus = [" ".join(texte_visible(rapport_flex.rendre(scan_flex.scanner(kw, fins, complete), l)).split()) for l in ("fr", "nl")]
    try:
        scan_flex.scanner(kw, fins, {**complete, "ean": 871687400000000000})
        ean_nombre = "accepté"
    except ValueError as erreur:
        ean_nombre = str(erreur)
    verifier("ean doit être écrit en texte" in ean_nombre,
             "EAN en nombre refusé : ses chiffres ont pu être perdus, la page qualité le dit conservé en texte (Astra, P2-S)")
    liste = " ".join(texte_visible(rapport_flex.rendre(scan_flex.scanner(kw, fins, {**complete, "processus": ["froid", "quais"]}), "fr")).split())
    verifier("froid, quais" in liste and "froid à quais" not in liste, "processus déclarés en liste : énumération, pas fourchette")
    verifier(all("871687400000000000" in t and "52.10" in t and "recharge de camions en 2027" in t for t in rendus),
             "fiche complète, champs déclarés en texte : rapport rendu en FR et NL, saisies affichées telles quelles")
    declaree = scan_flex.scanner(kw, fins, {**fiche, "ean": "871687400000000000", "processus": "froid et quais de chargement"})
    verifier(declaree["entreprise"]["ean"]["nature"] == "declare" and declaree["processus"]["description"]["nature"] == "declare",
             "EAN et processus fournis par l'entreprise : nature « déclaré », jamais « mesuré »")
    mom = o["batterie"]["moments"]
    verifier(max(mom["jour_baisse"][32:40]) == 50.0 and max(mom["jour_baisse"][:32] + mom["jour_baisse"][40:]) == 0.0,
             "moments d'utilisation : la batterie ne décharge qu'entre 8 h et 10 h")
    verifier(max(mom["semaine_baisse"][5] + mom["semaine_baisse"][6]) == 0.0, "moments d'utilisation : rien le week-end")
    visible_nl = texte_visible(rapport_flex.rendre(r, "nl"))
    francais = [m for m in ("Mesuré", "Simulé", "Hypothèse", "À chiffrer", "puissance", "période", "énergie", "plafond", "l'année")
                if m in visible_nl]
    verifier(not francais, f"rapport néerlandais sans français visible {francais}")

    # Les quarts d'heure qui décident (demande de Vincent, 27/09 à 3 h 27) : chiffres connus d'avance.
    q = r["quarts_decisifs"]
    court = " ".join(texte_visible(rapport_flex.rendre(r, "fr")).split())
    verifier("est atteinte 80 quarts d'heure sur la période" in court and "dans l'année. Mesuré" not in court,
             "profil de deux semaines : « sur la période », pas « dans l'année »")
    verifier(q["pointe"] == {"debut": "2021-01-04T08:00", "kw": 200.0, "quarts": 80} and all(c["baisse_kw"] == 0 for c in q["capacite"]),
             "quarts décisifs : pointe de 200 kW atteinte 80 quarts d'heure, aucune baisse en retirant les plus hauts")
    verifier(q["jours_au_dessus"] == 10 and all(j["quarts"] == 8 and j["energie_kwh"] == 100.0 and j["baisse_necessaire"] == 0.25 for j in q["jours"])
             and all(x["baisse_part"] == 0 and x["nominale_kwh"] == 117.1 for x in q["sans_jours"]),
             "10 jours identiques au-dessus du plafond : en retirer 3 ne réduit pas la batterie (117,1 kWh)")
    un_jour = [x if i < 96 else min(x, 100.0) for i, x in enumerate(kw)]
    r1 = scan_flex.scanner(un_jour, fins, fiche)
    q1 = r1["quarts_decisifs"]
    verifier(q1["jours_au_dessus"] == 1 and q1["sans_jours"][0]["nominale_kwh"] == 0 and q1["sans_jours"][0]["baisse_part"] == 1.0,
             "un seul jour de pointe : sans lui, aucune batterie")
    fr1, nl1 = texte_visible(rapport_flex.rendre(r1, "fr")), texte_visible(rapport_flex.rendre(r1, "nl"))
    verifier("Aucune batterie ne serait nécessaire pour tenir 150 kW si la pointe du 04/01/2021 était 25,0 % plus basse" in fr1
             and "un seul jour au-dessus du plafond, le 04/01/2021" in fr1
             and "Er zou geen batterij nodig zijn om onder 150 kW te blijven als de piek van 04-01-2021 25,0 % lager was" in nl1,
             "contrefactuel « aucune batterie si la pointe du jour était 25 % plus basse », en FR et en NL")
    fr1_, nl1_ = " ".join(fr1.split()), " ".join(nl1.split())
    verifier("25,0 % plus basse. Simulé" in fr1_ and "25,0 % lager was. Gesimuleerd" in nl1_ and "Mesuré" not in fr1_.split("Aucune batterie")[1][:120],
             "revue de 03 h 41 : la conclusion contrefactuelle porte « Simulé », pas « Mesuré »")
    francais1 = [m for m in ("Mesuré", "Simulé", "puissance", "énergie", "plafond", "l'année", "jour") if m in nl1]
    verifier(not francais1, f"section des quarts décisifs en néerlandais sans français visible {francais1}")
    deux_jours = [x if i < 96 else (180.0 if x == 200.0 and i < 192 else min(x, 100.0)) for i, x in enumerate(kw)]
    q2 = scan_flex.scanner(deux_jours, fins, fiche)["quarts_decisifs"]
    verifier([x["nominale_kwh"] for x in q2["sans_jours"]] == [round(60 / math.sqrt(0.9) / 0.9, 1), 0.0]
             and q2["jours"][0]["jour"] == "2021-01-04",
             "deux jours (200 et 180 kW) : sans le plus lourd, 70,3 kWh au lieu de 117,1 ; sans les deux, aucune batterie")
    # Quatre jours de pointe (200, 180, 170, 170 kW) : sans les deux plus lourds, la batterie tombe au besoin des
    # jours à 170 kW, et retirer le troisième n'y change rien. La synthèse doit parler de 2 jours, pas de 3.
    quatre = [({0: 200.0, 1: 180.0, 2: 170.0, 3: 170.0}.get(i // 96, 100.0) if x == 200.0 else x) for i, x in enumerate(kw)]
    syn4 = " ".join(texte_visible(rapport_flex.rendre(scan_flex.scanner(quatre, fins, fiche), "fr")).split())
    verifier("4 jours au-dessus du plafond. Si les 2 plus lourds étaient restés sous 150 kW" in syn4,
             "synthèse : le plus petit nombre de jours qui donne la plus forte baisse (2, pas 3)")
    verifier(q2["batterie_investissement_eur"] == o["batterie"]["investissement_eur"]["valeur"]
             and q2["sans_jours"][0]["investissement_eur"] == [round(70.3 * 400, -2), round(70.3 * 700, -2)] == [28100.0, 49200.0]
             and q2["sans_jours"][1]["investissement_eur"] == [0.0, 0.0],
             "contrefactuels chiffrés en euros avec le prix de l'option batterie : 28 100 à 49 200 € sans le jour le plus lourd")

    # Niveau de confiance (priorité 3 de Vincent) : jours ouvrés identiques, donc intervalle réduit à la valeur mesurée.
    c = r["confiance"]
    verifier(c["tirages"] == 100 and c["jours_reechantillonnes"] == 14 and c["jours_gardes"] == 0
             and c["batterie_kwh"] == {"mesure": 117.1, "p5": 117.1, "mediane": 117.1, "p95": 117.1}
             and c["heures_au_dessus"]["p5"] == c["heures_au_dessus"]["p95"] == 20.0 and c["decalage_suffisant_part"] == 1.0,
             "confiance : jours ouvrés identiques, batterie 117,1 kWh et 20 h au-dessus du plafond dans toutes les années tirées")
    verifier(scan_flex.scanner(kw, fins, fiche)["confiance"] == c, "confiance : graine fixe, même résultat à chaque scan")
    sans_conf = scan_flex.scanner(kw, fins, {**fiche, "tirages_confiance": 0})
    verifier(sans_conf["confiance"] is None and "Niveau de confiance" not in rapport_flex.rendre(sans_conf, "fr"),
             "confiance désactivable par la fiche (tirages_confiance = 0), section absente")
    c2 = scan_flex.scanner(deux_jours, fins, fiche)["confiance"]
    verifier(all(c2[k]["p5"] <= c2[k]["mediane"] <= c2[k]["p95"] for k in ("niveau_heures_kw", "heures_au_dessus", "batterie_kwh"))
             and c2["batterie_kwh"]["p95"] <= 117.1 + 1e-9,
             "confiance, deux jours de pointe différents : intervalles ordonnés, batterie jamais au-dessus du pire jour mesuré")
    verifier("remplacé 100 fois" in texte_visible(rapport_flex.rendre(r, "fr")) and "100 keer vervangen" in texte_visible(rapport_flex.rendre(r, "nl")),
             "confiance rendue en FR et en NL, avec la méthode")
    # Relecture de 05 h, défauts 3, 4 et 6 : batterie impossible sur l'année mesurée, peu de tirages, texte des limites.
    lourds = {0, 1, 2, 3, 4, 7, 8, 9}
    dur = [(100.0 if (f - timedelta(minutes=15)).weekday() >= 5 else 160.0 if i // 96 in lourds else 20.0) for i, f in enumerate(fins)]
    rd = scan_flex.scanner(dur, fins, {"nom": "essai", "gtv_kw": 400, "categorie_tarifaire": "MS", "plafond_cible_kw": 150})
    td = " ".join(texte_visible(rapport_flex.rendre(rd, "fr")).split())
    verifier(rd["options"]["batterie"]["faisable"] is False and rd["confiance"]["batterie_kwh"]["mesure"] is None
             and rd["confiance"]["batterie_impossible_part"] > 0 and "(capacité nominale) impossible" in td
             and "Aucune batterie ne tient 150 kW" in td and "ne dépasse pas la valeur mesurée" not in td,
             "confiance : batterie impossible dite « impossible » (jamais « 0,0 kWh »), part des années tirées sans batterie affichée")
    nl_d = texte_visible(rapport_flex.rendre(rd, "nl"))
    verifier("Énergie de recharge" not in nl_d and "Geen batterij kan de beoogde grens het hele jaar vasthouden" in nl_d,
             "batterie impossible : raison du moteur en français remplacée par une phrase néerlandaise dans le rapport NL")
    remise_d = rd["options"]["contrat"]["remise_eur_an"]
    verifier(remise_d["nature"] == "a_chiffrer" and remise_d["source"] == "src_remise_sans_mesure"
             and "que la batterie ou le décalage tiennent" not in td,
             "remise volledig variabel : non chiffrée quand ni la batterie ni le décalage ne tiennent le plafond")
    # Relecture de 05 h, défaut 7 : une pointe isolée à 350 kW sur des journées à 160 kW. Retirer ce jour réduisait la
    # puissance, donc la recharge, et donnait une batterie plus grosse (498,9 contre 231,3 kWh) affichée « 0 % ».
    isole = [(100.0 if (f - timedelta(minutes=15)).weekday() >= 5 else
              350.0 if i // 96 == 0 and (f - timedelta(minutes=15)).hour == 12 and (f - timedelta(minutes=15)).minute == 0 else
              160.0 if 5 <= (f - timedelta(minutes=15)).hour < 20 else 50.0) for i, f in enumerate(fins)]
    qi = scan_flex.scanner(isole, fins, {"nom": "essai", "gtv_kw": 400, "categorie_tarifaire": "MS", "plafond_cible_kw": 150,
                                         "tirages_confiance": 0})["quarts_decisifs"]
    verifier(all(x["nominale_kwh"] <= qi["batterie_nominale_kwh"] and x["baisse_part"] >= 0 for x in qi["sans_jours"])
             and qi["sans_jours"][0]["baisse_part"] > 0,
             "contrefactuel jamais plus gros que la référence ; sans la pointe isolée, la batterie baisse vraiment")
    # Un jour à 200 kW et neuf à 170 kW : retirer le plus lourd donne toute la baisse, les suivants n'y changent rien.
    un_jour_lourd = [((200.0 if i // 96 == 0 else 170.0) if x == 200.0 else x) for i, x in enumerate(kw)]
    un_seul = " ".join(texte_visible(rapport_flex.rendre(scan_flex.scanner(un_jour_lourd, fins, {**fiche, "tirages_confiance": 0}),
                                                         "fr")).split())
    verifier("Si le plus lourd était resté sous 150 kW" in un_seul and "Si les 1 plus lourds" not in un_seul,
             "synthèse au singulier quand un seul jour donne toute la baisse")
    # Relecture de 05 h, défaut 8 : les mêmes instants écrits en heure d'Amsterdam ou en UTC donnent le même scan.
    fins_ams = [f.replace(tzinfo=ams) for f in fins]
    fins_utc = [f.astimezone(utc) for f in fins_ams]
    ra_, ru_ = (scan_flex.scanner(kw, ff, {**fiche, "tirages_confiance": 0}) for ff in (fins_ams, fins_utc))
    verifier(ra_["options"]["contrat"]["blocs"] == ru_["options"]["contrat"]["blocs"]
             and ra_["options"]["batterie"]["moments"] == ru_["options"]["batterie"]["moments"]
             and ra_["quarts_decisifs"]["pointe"] == ru_["quarts_decisifs"]["pointe"],
             "mêmes instants en heure d'Amsterdam ou en UTC : blocs, moments et pointe identiques")
    c3 = scan_flex.scanner(deux_jours, fins, {**fiche, "tirages_confiance": 3})["confiance"]
    verifier(c3["batterie_kwh"]["p95"] <= 117.1 and c3["niveau_heures_kw"]["p95"] <= 200.0,
             "confiance avec 3 tirages : centiles dans l'intervalle des valeurs tirées (batterie <= 117,1 kWh, niveau <= 200 kW)")

    # Usure (priorité 4 de Vincent) : rainflow contrôlé sur l'exemple de la norme, puis sur la batterie synthétique.
    verifier(sorted(scan_flex.rainflow([-2, 1, -3, 5, -1, 3, -4, 4, -2])) == [(3, 0.5), (4, 0.5), (4, 1.0), (6, 0.5), (8, 0.5), (8, 0.5), (9, 0.5)],
             "rainflow : exemple de l'ASTM E1049-85 retrouvé (3 : 0,5 ; 4 : 1,5 ; 6 : 0,5 ; 8 : 1 ; 9 : 0,5)")
    u = o["batterie"]["usure"]
    verifier(u["classes"][-1]["cycles"] == 10.0 and abs(u["cycles_pleins"]["valeur"] - 9.0) < 0.05 and abs(u["profondeur_max"]["valeur"] - 0.9) < 1e-3
             and u["duree_vie_ans"]["nature"] == "a_completer",
             "usure : 10 décharges de 90 % de la capacité nominale, 9 cycles pleins ; durée de vie à compléter sans garantie")
    g = {"cycles": 6000, "profondeur": 0.9, "annees": 15, "etat_fin": 0.7, "source": "essai"}
    # Revue de 04 h 12 : garanties mal formées refusées avec un message, jamais de capacité négative ni de TypeError.
    mal_formees = [{**g, "cycles": 10 ** 400}, {**g, "cycles": -6000}, {**g, "profondeur": 0}, {**g, "profondeur": 1.2}, {**g, "etat_fin": -0.7},
                   {**g, "etat_fin": 0}, {**g, "cycles": "6000"}, {**g, "annees": float("nan")}, {**g, "annees": float("inf")},
                   {**g, "etat_fin": True}, "6000 cycles"]
    refusees = 0
    for garantie in mal_formees:
        try:
            scan_flex.scanner(kw, fins, {**fiche, "batterie_garantie": garantie, "tirages_confiance": 0})
        except ValueError as erreur:
            refusees += "batterie_garantie" in str(erreur)
    # Nombres de la fiche : refusés avec le nom du champ, au lieu d'une erreur de type plus loin.
    fiches_fausses = [{"gtv_kw": "600"}, {"gtv_kw": -600}, {"plafond_cible_kw": float("nan")}, {"capacite_aansluiting_kva": 0},
                      {"tirages_confiance": "100"}, {"tirages_confiance": -1}, {"tirages_confiance": 10 ** 6},
                      {"croissance_prevue": {"kw": "150", "debut": "22:00", "fin": "06:00", "jours": "tous"}},
                      {"hypotheses": {"heures_ecretees": "8"}}, {"hypotheses": {"profondeur_decharge": 1.5}},
                      {"hypotheses": {"prix_batterie_eur_kwh": [700, 400]}}, {"heures_activite_an": 9000},
                      {"hypotheses": {"heures_ecretees": {"source": "sans valeur"}}},
                      {"croissance_prevue": {"kw": 150, "debut": "25:00", "fin": "06:00", "jours": "tous"}},
                      {"croissance_prevue": {"kw": 150, "debut": "22:00", "fin": "6h", "jours": "tous"}},
                      {"gtv_kw": 10 ** 400},  # entier JSON géant : refus clair, pas OverflowError (audit de Codex)
                      {"horaires_semaine": ["lundi 8-17"]}, {"horaires_semaine": [{"jour": "lundi", "debut": "08:00", "fin": "17:00"}]}]
    noms = 0
    for extra in fiches_fausses:
        try:
            scan_flex.scanner(kw, fins, {**fiche, **extra, "tirages_confiance": extra.get("tirages_confiance", 0)})
        except ValueError as erreur:
            noms += str(erreur).startswith("Fiche :")
    verifier(noms == len(fiches_fausses), f"fiche : {noms} nombres mal formés sur {len(fiches_fausses)} refusés avec le nom du champ")
    partielle = scan_flex.scanner(kw, fins, {**fiche, "batterie_garantie": {"cycles": 6000, "source": "essai"},
                                             "tirages_confiance": 0})["options"]["batterie"]["usure"]
    verifier(refusees == len(mal_formees) and partielle["duree_vie_ans"]["nature"] == "a_completer",
             f"garantie : {refusees} saisies mal formées sur {len(mal_formees)} refusées avec message ; garantie partielle à compléter")
    courte = scan_flex.scanner(kw, fins, {**fiche, "batterie_garantie": g})["options"]["batterie"]["usure"]
    verifier(courte["duree_vie_ans"]["nature"] == "a_chiffrer" and courte["nominale_fin_vie_kwh"]["valeur"] == round(117.1 / 0.7, 1),
             "usure sur deux semaines : durée de vie non calculée, capacité de fin de garantie 117,1 / 0,7")

    csv = EXEMPLE / "vea-2708-2016.csv"
    if csv.exists():
        kw, fins = scan_flex.lire_csv(csv)
        fiche = json.loads((EXEMPLE / "fiche.json").read_text(encoding="utf-8"))
        r = scan_flex.scanner(kw, fins, fiche)
        st, bat = r["statistiques"], r["options"]["batterie"]
        verifier(st["quarts"] == 35136 and st["pointe_kw"]["valeur"] == 595, "VEA 2708 : 35 136 quarts d'heure, pointe 595 kW")
        verifier(r["plafond_kw"]["valeur"] == 523 and bat["flex_kw"]["valeur"] == 72.0,
                 "VEA 2708 : plafond des 8 heures 523 kW, 72 kW à écrêter (chiffres de docs/preuves)")
        verifier(bat["dimensionnement"] == "puissance" and bat["capacite_nominale_kwh"]["valeur"] == 72.0,
                 "VEA 2708 : pointe courte, la puissance dimensionne la batterie (72 kWh à 1C)")
        r_fr = rapport_flex.rendre(r, "fr")
        verifier("Tranche ETVT" in r_fr and "plus de 15 ans" in r_fr and bat["retour_ans"]["nature"] == "simule",
                 "VEA 2708 (année entière) : retour calculé, tranche ETVT de la toelichting 2026 affichée")
        verifier(bat["controle_moteur"]["methode"] == "analytique_avec_temoin" and max(bat["profil_apres"]) <= 523 + 1e-6,
                 "VEA 2708 : moteur cyclique vérifié et simulation sous le plafond toute l'année")
        # Relecture de 05 h, défaut 2 : avec un projet, la pointe étudiée (profil + projet) est simulée, pas mesurée.
        jour = json.loads((EXEMPLE / "croissance-jour" / "fiche.json").read_text(encoding="utf-8"))
        rj = " ".join(texte_visible(rapport_flex.rendre(scan_flex.scanner(kw, fins, {**jour, "tirages_confiance": 5}), "fr")).split())
        verifier("Avec le projet, la pointe serait de 695 kW" in rj and "Avec le projet, la pointe serait de 695 kW, le 05/01/2016 à 08:15, "
                 "atteinte un seul quart d'heure dans l'année. Simulé" in rj and "Année du profil avec le projet" in rj,
                 "scénario de croissance : pointe de 695 kW et confiance présentées « avec le projet », étiquetées « Simulé »")
        g = {"cycles": 6000, "profondeur": 0.9, "annees": 15, "etat_fin": 0.7, "source": "essai"}
        vie = scan_flex.scanner(kw, fins, {**fiche, "batterie_garantie": g})["options"]["batterie"]["usure"]
        usee = scan_flex.scanner(kw, fins, {**fiche, "batterie_garantie": {**g, "cycles": 20}})["options"]["batterie"]["usure"]
        pleins = vie["cycles_pleins"]["valeur"]
        verifier(vie["duree_vie_ans"]["valeur"] == 15 and vie["duree_vie_ans"]["source"] == "src_duree_garantie_calendrier"
                 and vie["nominale_fin_vie_kwh"]["valeur"] == round(72 / 0.7, 1)
                 and usee["duree_vie_ans"]["source"] == "src_duree_garantie_cycles"
                 and abs(usee["duree_vie_ans"]["valeur"] - 20 * 0.9 / pleins) < 0.2,
                 f"VEA 2708, usure : {pleins} cycles pleins par an, la garantie de 15 ans limite ; avec 20 cycles garantis, ce sont les cycles")
        with tempfile.TemporaryDirectory() as tmp:
            code = scan_flex.main(["scan_flex.py", str(csv), str(EXEMPLE / "fiche.json"), tmp])
            fichiers = sorted(p.name for p in Path(tmp).iterdir())
        verifier(code == 0 and fichiers == ["rapport-flex-nl.html", "rapport-flex.html", "scan.json"],
                 "ligne de commande : scan.json et les deux rapports écrits")
        # Export PDF (dépôt Flex-e) : ignoré seulement sans navigateur ; sinon toute erreur est un échec.
        verifier_export_pdf(rapport_flex.rendre(r, "fr"))
    else:
        print("ignoré : docs/exemples/scan-flex/vea-2708-2016.csv absent")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])
        # Sans navigateur, l'export PDF est compté comme ignoré dans le bilan de unittest, pas comme réussi.
        for raison in PDF_IGNORE:
            with self.subTest("export PDF A4 du rapport"):
                self.skipTest(f"aucun navigateur disponible ici : {raison}")


class ExportPdf(unittest.TestCase):
    """Constat n°23 : l'export PDF n'est ignoré que sans navigateur ; toute autre erreur est un échec."""

    def setUp(self):
        echecs.clear()
        PDF_IGNORE.clear()
        self.addCleanup(echecs.clear)
        self.addCleanup(PDF_IGNORE.clear)

    def test_erreur_de_l_export_avec_un_navigateur_est_un_echec(self):
        import rapport_pdf
        ici = sys.modules[__name__]
        with mock.patch.object(ici, "navigateur_indisponible", return_value=None), \
                mock.patch.object(rapport_pdf, "html_vers_pdf", side_effect=TypeError("régression simulée")):
            verifier_export_pdf("<p>essai</p>")
        self.assertEqual(echecs, ["export PDF A4 du rapport : TypeError : régression simulée"])
        self.assertEqual(PDF_IGNORE, [])

    def test_sans_navigateur_l_export_est_ignore_et_dit(self):
        import rapport_pdf
        ici = sys.modules[__name__]
        with mock.patch.object(ici, "navigateur_indisponible", return_value="aucun navigateur (essai)"), \
                mock.patch.object(rapport_pdf, "html_vers_pdf", side_effect=AssertionError("appel inattendu")):
            verifier_export_pdf("<p>essai</p>")
        self.assertEqual(echecs, [])
        self.assertEqual(PDF_IGNORE, ["aucun navigateur (essai)"])

    def test_seul_l_echec_du_lancement_vaut_indisponible(self):
        import rapport_pdf
        with mock.patch.object(rapport_pdf, "navigateur", return_value="/chemin/absent/navigateur"):
            raison = navigateur_indisponible()
        self.assertIsInstance(raison, str)
        self.assertTrue("/chemin/absent/navigateur" in raison or "Playwright" in raison, raison)
        # Une erreur du code de l'export (ici le choix du navigateur) n'est pas une absence de navigateur.
        with mock.patch.object(rapport_pdf, "navigateur", side_effect=TypeError("régression simulée")):
            with self.assertRaises(TypeError):
                navigateur_indisponible()


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
