"""Scan de groupe (scan_groupe.py) : foisonnement de sites voisins, chiffres connus d'avance.

Deux sites d'une semaine : le premier monte à 200 kW le matin (8 h-10 h), le second à 150 kW l'après-midi
(14 h-16 h), 100 kW sinon. Pointes cumulées 350 kW ; pointe commune 300 kW (200 + 100 le matin) : 50 kW
libérés, 14,3 %. Avec des GTV de 250 et 200 kW, un contrat de groupe laisse 150 kW au-dessus de 300 kW.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ICI = Path(__file__).resolve().parent
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
sys.path.insert(0, str(ICI))
import scan_groupe  # noqa: E402

echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def profils():
    debut = datetime(2021, 1, 4)
    fins = [debut + timedelta(minutes=15 * (q + 1)) for q in range(7 * 96)]
    matin = [200.0 if 8 <= (f - timedelta(minutes=15)).hour < 10 else 100.0 for f in fins]
    apres_midi = [150.0 if 14 <= (f - timedelta(minutes=15)).hour < 16 else 100.0 for f in fins]
    return fins, matin, apres_midi


def main():
    echecs.clear()
    fins, a, b = profils()
    g = scan_groupe.grouper([("matin", a, fins), ("après-midi", b, fins)], [250, 200])
    verifier(g["somme_pointes_kw"] == 350 and g["pointe_commune_kw"] == 300 and g["capacite_liberee_kw"] == 50,
             "pointes cumulées 350 kW, pointe commune 300 kW, 50 kW libérés par le partage")
    verifier(abs(g["foisonnement"] - 50 / 350) < 1e-4, "foisonnement 14,3 %")
    verifier(g["marge_gtv_groupe_kw"] == 150 and g["somme_gtv_kw"] == 450, "GTV cumulés 450 kW : 150 kW de marge sur la pointe commune")
    apm = next(s for s in g["sites"] if s["nom"] == "après-midi")
    verifier(apm["a_la_pointe_commune_kw"] == 100.0 and abs(apm["part_de_sa_pointe"] - 100 / 150) < 1e-3,
             "à la pointe commune (matin), le site de l'après-midi n'est qu'aux deux tiers de sa pointe")
    try:
        scan_groupe.grouper([("matin", a, fins), ("décalé", b[1:], fins[1:])], [None, None])
        verifier(False, "profils sur des quarts d'heure différents refusés")
    except ValueError:
        verifier(True, "profils sur des quarts d'heure différents refusés")
    fr, nl = scan_groupe.rendre(g, {"nom": "essai"}, "fr"), scan_groupe.rendre(g, {"nom": "essai"}, "nl")
    verifier("50 kW de moins" in fr and "150 kW de marge" in fr and "groepstransportovereenkomst" in fr,
             "rapport FR : capacité libérée, marge de groupe et nature du contrat")
    verifier("50 kW minder" in nl and "150 kW ruimte" in nl and "Los van elkaar" in nl, "rapport NL rendu en néerlandais")
    # Audit O1 : quatre raccordements de 400 kW ne font pas un raccordement de 1,6 MW. GOTORK et l'obligation de
    # participer valent site par site ; sur le groupe, le scan ne les tranche pas et ne chiffre aucune pénalité.
    import scan_flex
    r_g = scan_flex.scanner(g["profil_commun_kw"], fins, {"gtv_kw": 1600, "contrat_groupe": True, "tirages_confiance": 0})
    off = r_g["options"]["offre_gestionnaire"]
    verifier(r_g["marge_gtv"]["regle"] == "groupe" and off["obligation_1mw"]["valeur"] is None
             and off["obligation_1mw"]["source"] == "src_reg009_groupe" and off["sanction_sans_offre"]["valeur"] is None
             and any(l["cle"] == "reco_offre_groupe" for l in r_g["recommandation"]),
             "groupe de GTV cumulés 1,6 MW : ni GOTORK ni obligation de 1 MW appliqués à la somme, aucune pénalité")
    # Audits O6 et O13 : ni catégorie tirée de la somme des GTV, ni tarif d'un raccordement unique.
    verifier(r_g["raccordement"]["categorie"] == "GROUPE" and r_g["raccordement"]["tarif_kwmax_mois"] is None
             and r_g["options"]["batterie"]["economie"]["eur_an"]["source"] == "src_tarif_groupe"
             and r_g["options"]["contrat"]["remise_eur_an"]["source"] == "src_tarif_groupe"
             and r_g["monetisation"]["sans_batterie"]["optimisation_contrat"]["source"] == "src_tarif_groupe",
             "groupe : catégorie « contrat de groupe », économie kWmax et remise à chiffrer, aucune grille d'un raccordement unique")
    page_g = __import__("rapport_flex").rendre(r_g, "fr")
    page_g_nl = __import__("rapport_flex").rendre(r_g, "nl")
    verifier("site par site" in page_g and "Participation obligatoire (1 MW)</th><td>oui" not in page_g
             and "Contrat de transport de groupe" in page_g and "Groepstransportovereenkomst (tarief" in page_g_nl
             and "None" not in page_g and "None" not in page_g_nl and "aux tarifs Liander" not in page_g
             and "tarievenblad elektriciteit" not in page_g,
             "rapport du groupe : règles par raccordement dites site par site, aucune obligation affichée « oui »")
    with tempfile.TemporaryDirectory() as tmp:
        chemins = []
        for nom, valeurs in (("matin", a), ("apres-midi", b)):
            chemin = Path(tmp) / f"{nom}.csv"
            # Décalage explicite : le lecteur canonique refuse les dates sans fuseau (janvier, donc +01:00).
            chemin.write_text("fin_intervalle,puissance_kw\n" + "".join(f"{f.replace(tzinfo=AMSTERDAM).isoformat()},{v}\n"
                                                                         for f, v in zip(fins, valeurs)),
                              encoding="utf-8")
            chemins.append(str(chemin))
        fiche = Path(tmp) / "groupe.json"
        fiche.write_text(json.dumps({"nom": "essai", "plafond_cible_kw": 250,
                                     "sites": [{"nom": "matin", "gtv_kw": 250}, {"nom": "après-midi", "gtv_kw": 200}]}), encoding="utf-8")
        code = scan_groupe.main(["scan_groupe.py", str(fiche), str(Path(tmp) / "sortie"), *chemins])
        ecrits = sorted(p.name for p in (Path(tmp) / "sortie").iterdir())
        # Relecture de 05 h, défaut 8 : le même profil écrit en UTC (« Z ») pour le second site est accepté.
        utc_chemin = Path(tmp) / "apres-midi-utc.csv"
        utc_chemin.write_text("fin_intervalle,puissance_kw\n" + "".join(
            f"{f.replace(tzinfo=AMSTERDAM).astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%SZ')},{v}\n" for f, v in zip(fins, b)),
            encoding="utf-8")
        code_utc = scan_groupe.main(["scan_groupe.py", str(fiche), str(Path(tmp) / "sortie-utc"), chemins[0], str(utc_chemin)])
        meme = json.loads((Path(tmp) / "sortie-utc" / "scan_groupe.json").read_text(encoding="utf-8"))
        fausse = Path(tmp) / "groupe-faux.json"
        fausse.write_text(json.dumps({"nom": "essai", "sites": [{"nom": "matin", "gtv_kw": "250"}, {"nom": "après-midi", "gtv_kw": 200}]}),
                          encoding="utf-8")
        try:
            scan_groupe.main(["scan_groupe.py", str(fausse), str(Path(tmp) / "sortie2"), *chemins])
            refus_gtv = False
        except ValueError as erreur:
            refus_gtv = "gtv_kw de « matin »" in str(erreur)
    verifier(refus_gtv, "fiche de groupe : GTV saisi en texte refusé avec le nom du site")
    verifier(code_utc == 0 and meme["pointe_commune_kw"] == 300 and meme["capacite_liberee_kw"] == 50,
             "second site écrit en UTC : même groupe, pointe commune 300 kW, 50 kW libérés")
    verifier(code == 0 and ecrits == ["rapport-flex-nl.html", "rapport-flex.html", "rapport-groupe-nl.html", "rapport-groupe.html",
                                      "scan_groupe.json"], "ligne de commande : rapports de groupe et scan de flexibilité du profil commun")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
