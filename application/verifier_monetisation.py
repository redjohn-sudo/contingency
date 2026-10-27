"""Monétisation (monetisation.py) et seuils GOTORK : chiffres connus d'avance, brief du 27/09/2026.

Aides Flex-e (50 % du scan au plus 10 000 € ; étude de faisabilité aidée de 10 000 à 125 000 €), EIA (40 % au taux
d'impôt de 19 ou 25,8 %), revenus de flexibilité ramenés aux deux points du brief, contrat au tarif déclaré ou de
référence (Enexis MS-D 28,91 €/kW/an), aucun total, les deux réponses à la question de la batterie, et GOTORK
seulement au-delà de 50 % inutilisés ou de 1 MW (art. 7.13 de la Netcode).
"""
import json
from datetime import datetime, timedelta
import sys
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import monetisation as m  # noqa: E402
import rapport_flex  # noqa: E402
import scan_flex  # noqa: E402
from verifier_scan_flex import texte_visible  # noqa: E402

EXEMPLE = ICI.parent / "docs" / "exemples" / "scan-flex"
echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def cles(objet):
    """Toutes les clés d'un résultat imbriqué, pour vérifier qu'aucun total n'est calculé."""
    if isinstance(objet, dict):
        return set(objet) | set().union(*(cles(v) for v in objet.values()))
    if isinstance(objet, list):
        return set().union(*(cles(v) for v in objet)) if objet else set()
    return set()


def avec_remise(remise):
    return {"options": {"contrat": {"remise_eur_an": remise}}}


def main():
    echecs.clear()
    # Flex-e : scan et étude de faisabilité
    verifier(m.aide_scan(None)["nature"] == "a_completer", "aide au scan : prix non fourni, à compléter")
    verifier(m.aide_scan(8000)["valeur"] == 4000 and m.aide_scan(30000)["valeur"] == 10000,
             "aide au scan : 50 % de 8 000 € = 4 000 € ; 30 000 € plafonné à 10 000 €")
    verifier(m.aide_etude(None)["nature"] == "a_completer", "étude de faisabilité : coût non fourni, aucune aide supposée")
    sous = m.aide_etude(15000)
    verifier(sous["valeur"] == 0 and sous["source"] == "src_mon_etude_sous_minimum",
             "étude de 15 000 € : 7 500 € sous l'aide minimale de 10 000 €, donc 0 €")
    verifier(m.aide_etude(20000)["valeur"] == 10000 and m.aide_etude(40000)["valeur"] == 20000
             and m.aide_etude(400000)["valeur"] == 125000,
             "étude : 20 000 € donne 10 000 €, 40 000 € donne 20 000 €, 400 000 € plafonné à 125 000 €")
    # EIA : 40 % x 19 % = 7,6 % et 40 % x 25,8 % = 10,32 %
    g = m.eia([10000.0, 20000.0], 50, 50)
    verifier(g["valeur"] == [800.0, 2100.0] and g.get("conditionnel"),
             "EIA : 7,6 % de 10 000 € (760, arrondi 800) à 10,32 % de 20 000 € (2 064, arrondi 2 100), 0 € possible")
    verifier(m.eia([10000.0, 20000.0], 10, 50)["valeur"] == 0 and m.eia([10000.0, 20000.0], 50, 4)["valeur"] == 0,
             "EIA : sous 15 kWh ou sous 5 kW, pas d'EIA (Energielijst 2026)")
    verifier(m.eia(None, 50, 50)["nature"] == "a_chiffrer", "EIA : prix de batterie inconnu, à chiffrer")
    # Audit A10 : même seuil de 2 500 € que le dossier d'aides
    sous = m.eia([2000.0, 2000.0], 15, 5, aide_eur=0)
    verifier(sous["valeur"] == 0 and sous["source"] == "src_mon_eia_sous_seuil", "EIA : assiette de 2 000 €, sous le seuil de 2 500 €, 0 €")
    fr, nl = (rapport_flex.SOURCES[langue]["src_mon_eia_sous_seuil"] for langue in ("fr", "nl"))
    verifier("par déclaration" in fr and "RVO" in fr and "non relu" not in fr and "par bien" not in fr
             and "per melding" in nl and "RVO" in nl and "niet gecontroleerd" not in nl and "bedrijfsmiddel" not in nl,
             "EIA : seuil de 2 500 € cité par déclaration avec sa source RVO, en FR et en NL")
    verifier(m.eia([2000.0, 3000.0], 50, 50)["valeur"] == [0.0, 300.0],
             "EIA : assiette de 2 000 à 3 000 €, borne basse sous le seuil (0 €), borne haute 309,6 € arrondis à 300 €")
    # Assiette de l'EIA : l'aide reçue se retranche (FAQ EIA de RVO ; relecture de Codex, bus n°484)
    sans = m.eia([10000.0, 20000.0], 50, 50)
    verifier(sans["source"] == "src_mon_eia" and "aucune n'étant déclarée" in rapport_flex.source(sans["source"], {}, "fr"),
             "EIA sans aide déclarée : calcul sans aide, et la ligne le dit")
    avec = m.eia([10000.0, 20000.0], 50, 50, 5000.0)
    verifier(avec["valeur"] == [400.0, 1500.0] and avec["source"] == "src_mon_eia_aide",
             "EIA avec 5 000 € d'aide : assiette 5 000 à 15 000 €, soit 380 à 1 548 € arrondis à 400 à 1 500 €")
    verifier(m.eia([10000.0, 20000.0], 50, 50, 0.0)["valeur"] == [800.0, 2100.0],
             "EIA avec une aide déclarée nulle : même montant que sans aide, source qui cite l'aide")
    totale = m.eia([10000.0, 20000.0], 50, 50, 25000.0)
    verifier(totale["valeur"] == 0 and totale["source"] == "src_mon_eia_aide_totale",
             "EIA : aide de 25 000 € au-dessus de l'investissement, assiette nulle, 0 €")
    # Revenus de flexibilité : les deux points du brief, et la ressource la plus rare
    verifier(m.revenus_flex(100, 50)["valeur"] == [5300.0, 8600.0] and m.revenus_flex(100, 50)["source"] == "src_mon_revenus_flex",
             "revenus flex : 100 kWh et 50 kW, 5 300 à 8 600 €/an")
    verifier(m.revenus_flex(500, 250)["valeur"] == [26000.0, 43000.0], "revenus flex : 500 kWh et 250 kW, 26 000 à 43 000 €/an")
    verifier(m.revenus_flex(200, 50)["valeur"] == [5300.0, 8600.0],
             "revenus flex : 200 kWh mais 50 kW, compté comme 100 kWh équivalents (puissance limitante)")
    petite = m.revenus_flex(72, 72)
    verifier(petite["valeur"] == [3800.0, 6200.0] and petite["source"] == "src_mon_revenus_flex_extrapole",
             "revenus flex : 72 kWh, 3 816 à 6 192 € arrondis à 3 800 à 6 200 €/an, dit extrapolé")
    # Contrat (constat n°10) : la remise de l'option 5.4, en fourchette, jamais un autre tarif
    nfa = scan_flex.remise_volledig_variabel(1200, 150, 27.48)
    c = m.optimisation_contrat(avec_remise(nfa))
    verifier(c["valeur"] == [0, 28854] and c["source"] == "src_mon_contrat" and c["parametres"]["kw"] == 1050,
             "contrat : 0 à la remise de l'option 5.4 (1 050 kW x 27,48 €/kW/an = 28 854 €/an)")
    ls = m.optimisation_contrat(avec_remise(scan_flex.remise_volledig_variabel(1200, 150, None)))
    verifier(ls["valeur"] is None and ls["source"] == "src_pas_kw_contrat",
             "contrat, catégorie sans terme kW (LS) : pas de montant, même statut que l'option 5.4")
    verifier(m.optimisation_contrat(avec_remise(scan_flex.remise_volledig_variabel(None, 150, 27.48)))["nature"] == "a_completer"
             and m.optimisation_contrat(avec_remise(scan_flex.remise_volledig_variabel(150, 150, 27.48)))["valeur"] == 0,
             "contrat : GTV inconnu à compléter ; GTV au niveau de la limite, 0 €")
    # GOTORK, art. 7.13 : au plus 50 % utilisé, ou 1 MW ou plus inutilisé, sur 12 mois
    regle = lambda gtv, pointe: scan_flex.marge_sous_gtv(gtv, pointe)["regle"]  # noqa: E731
    verifier(regle(1000, 600) == "marge" and regle(2000, 1001) == "marge",
             "GOTORK : 60 % utilisé et 400 kW libres, ou 50,05 % et 999 kW, sous les seuils : pas exposé")
    verifier(regle(1000, 500) == "gotork" and regle(3000, 1900) == "gotork",
             "GOTORK : exactement 50 % utilisé, ou 1 100 kW inutilisés : exposé, alerte de risque")
    verifier(regle(600, 600) == "limite" and regle(500, 600) == "depassement", "GTV atteint ou dépassé : règles inchangées")
    # Constat n°12 : une économie négative ne donne jamais de retour ni de tranche « moins de 3 ans »
    neg = scan_flex.retour(scan_flex.grandeur([10000.0, 20000.0], "€", "hypothese", "src_invest_prix"),
                           {"eur_an": scan_flex.grandeur(-150, "€/an", "simule", "src_kwmax")})
    verifier(neg["valeur"] is None and neg["source"] == "src_retour_negatif", "retour : économie de -150 €/an, pas de retour")
    # Constat n°11 : un projet de croissance garde la cible de plafond de la fiche quand elle est plus basse
    kw11, fins11 = [100.0] * 96 * 7, [datetime(2021, 1, 4) + timedelta(minutes=15 * (q + 1)) for q in range(96 * 7)]
    kw11[40] = 103.0
    r11 = scan_flex.scanner(kw11, fins11, {"plafond_cible_kw": 80, "tirages_confiance": 0,
                                           "croissance_prevue": {"kw": 10, "debut": "08:00", "fin": "12:00"}})
    verifier(r11["plafond_kw"]["valeur"] == 80 and r11["scenario_croissance"]["limite_kw"]["source"] == "src_plafond_fiche",
             "croissance : cible de 80 kW gardée (pointe 103 kW, projet +10 kW), plus remplacée par la pointe")
    # Constat n°13 : export glissant de 367 jours, sans année civile complète : les 365 derniers jours
    import tempfile
    from zoneinfo import ZoneInfo
    ams = ZoneInfo("Europe/Amsterdam")
    debut13 = datetime(2025, 9, 25, tzinfo=ams)
    with tempfile.TemporaryDirectory() as tmp:
        csv = Path(tmp) / "glissant.csv"
        lignes = ["fin_intervalle,puissance_kw"]
        t = debut13.astimezone(ZoneInfo("UTC"))
        for q in range(367 * 96 + 8):  # heure d'hiver : 4 quarts de plus le jour du changement, marge
            t += timedelta(minutes=15)
            if t.astimezone(ams) > datetime(2026, 9, 27, tzinfo=ams):
                break
            lignes.append(f"{t.astimezone(ams).isoformat()},100")
        csv.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        kw13, fins13, sel13 = scan_flex.lire_profil_annee(csv)
    verifier(sel13["regle"] == "glissante" and fins13[-1] == datetime(2026, 9, 27, tzinfo=ams) and fins13[0] == datetime(2025, 9, 27, 0, 15, tzinfo=ams),
             f"export glissant de 367 jours : les 365 derniers gardés ({fins13[0]} à {fins13[-1]}), dit dans le rapport")
    # Scan complet de l'exemple 2708 : les deux réponses, le bureau d'études, aucun total
    kw, fins, _ = scan_flex.lire_profil_annee(EXEMPLE / "vea-2708-2016.csv", None)
    fiche = json.loads((EXEMPLE / "fiche.json").read_text(encoding="utf-8"))
    fiche.update(tirages_confiance=0, gtv_kw=700, prix_scan_eur=6000, cout_etude_eur=30000)
    r = scan_flex.scanner(kw, fins, fiche)
    mo = r["monetisation"]
    bat = r["options"]["batterie"]
    verifier(set(mo) == {"sans_batterie", "avec_batterie", "bureau_etudes"} and mo["sans_batterie"]["mesure"] == "decalage",
             "2708 : réponses « pas de batterie » (limite tenue par le décalage) et « batterie », et bureau d'études")
    verifier(mo["sans_batterie"]["investissement_evite"]["valeur"] == bat["investissement_eur"]["valeur"],
             "investissement évité : la batterie de l'option 5.1, même fourchette")
    plafond = r["plafond_kw"]["valeur"]
    remise = r["options"]["contrat"]["remise_eur_an"]["valeur"]
    verifier(mo["sans_batterie"]["optimisation_contrat"]["valeur"] == [0, remise],
             f"contrat : GTV 700 kW, limite {plafond} kW, même remise que l'option 5.4 ({remise} €/an)")
    verifier(mo["sans_batterie"]["aide_scan"]["valeur"] == 3000 and mo["sans_batterie"]["aide_etude"]["valeur"] == 15000,
             "aides : scan de 6 000 € aidé à 3 000 € ; étude de 30 000 € aidée à 15 000 €")
    verifier(all(mo["avec_batterie"][c].get("conditionnel") for c in ("bon_dimensionnement", "eia", "revenus_flex")),
             "réponse « batterie » : dimensionnement, EIA et revenus flex peuvent valoir 0 €, le rapport le dit")
    verifier(mo["bureau_etudes"]["valeur"]["valeur"] == [720, 1440], "bureau d'études : 8 à 16 h x 90 €/h = 720 à 1 440 € par scan")
    verifier(not any("total" in c or "somme" in c for c in cles(mo)), "aucun total ni somme dans le résultat")
    verifier(r["marge_gtv"]["regle"] == "marge", "GTV 700 kW pour une pointe de 595 kW : 105 kW sous les seuils GOTORK")
    # Rapport : la section dans les deux langues, sans français dans le néerlandais
    fr, nl = rapport_flex.rendre(r, "fr"), rapport_flex.rendre(r, "nl")
    verifier("Économies par type de client" in fr and "Besparingen per type klant" in nl
             and "0 € ou 2" in texte_visible(fr) and "€ 0 of 2" in texte_visible(nl),
             "rapport : section dans les deux langues, « 0 € ou » devant l'EIA")
    # Audit O14 : aide Flex-e aux mesures, minimum de 25 000 € (RVO, flexibiliteitsmaatregelen)
    inv = r["options"]["batterie"]["investissement_eur"]["valeur"]
    verifier(0.4 * inv[1] < 25000 and "sous le minimum de 25 000 €" in texte_visible(fr)
             and "onder het minimum van € 25.000" in texte_visible(nl) and "62 500 €" in texte_visible(fr),
             f"Flex-e mesures : batterie {inv[0]:.0f} à {inv[1]:.0f} €, 40 % sous le minimum de 25 000 €, dit en FR et NL")
    mots = ("Mesuré", "Simulé", "Hypothèse", "À chiffrer", "puissance", "période", "énergie", "plafond", "l'année",
            "Économies", "Bureau d'études", "Investissement", "une fois", "par an")
    verifier(not [x for x in mots if x in texte_visible(nl)], "rapport NL : aucun mot français de la liste")
    # Fiche : prix et coût contrôlés à l'entrée
    for champ, valeur in (("prix_scan_eur", "6000"), ("cout_etude_eur", -5), ("aide_batterie_eur", -1),
                          ("aide_batterie_eur", "abc"), ("aide_batterie_eur", float("nan"))):
        try:
            scan_flex.fiche_controlee({champ: valeur})
            refus = False
        except ValueError as erreur:
            refus = champ in str(erreur)
        verifier(refus, f"fiche : {champ} = {valeur!r} refusé avec le nom du champ")
    try:
        scan_flex.fiche_controlee({"aide_batterie_eur": 0})
        zero_accepte = True
    except ValueError:
        zero_accepte = False
    verifier(zero_accepte, "fiche : aide_batterie_eur = 0 accepté (aucune aide, réponse valable)")
    fiche_aide = dict(fiche, aide_batterie_eur=10000)
    r_aide = scan_flex.scanner(kw, fins, fiche_aide)
    inv = r_aide["options"]["batterie"]["investissement_eur"]["valeur"]
    attendu = [round((inv[0] - 10000) * 0.4 * 0.19, -2), round((inv[1] - 10000) * 0.4 * 0.258, -2)]
    verifier(r_aide["monetisation"]["avec_batterie"]["eia"]["valeur"] == attendu,
             f"scan 2708 avec 10 000 € d'aide : EIA sur l'assiette {inv[0] - 10000:.0f} à {inv[1] - 10000:.0f} €, soit {attendu}")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
