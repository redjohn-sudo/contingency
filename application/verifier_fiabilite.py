"""Fiabilité des données, lot 1 de la mission du 30/09/2026 (issue n°7) : chaque test part d'un défaut reproduit
sur 1216155 et doit échouer avant sa correction."""
import sys
import unittest
from typing import Any
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rapport_flex  # noqa: E402
import scan_flex  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")
QUART = timedelta(minutes=15)
SCAN_LE = datetime(2026, 9, 30)


def profil(debut: datetime, fin: datetime) -> tuple[list[float], list[datetime]]:
    """Quarts réguliers entre deux instants d'Amsterdam, fins en UTC, pointe les matins de semaine."""
    t, borne, kw, fins = debut.astimezone(timezone.utc), fin.astimezone(timezone.utc), [], []
    while t < borne:
        local = t.astimezone(AMS)
        t += QUART
        fins.append(t)
        kw.append(200.0 if local.weekday() < 5 and 8 <= local.hour < 10 else 100.0)
    return kw, fins


def ams(*date: int) -> datetime:
    return datetime(*date, tzinfo=AMS)


class Periode(unittest.TestCase):
    """AF10 (Astra, commentaire 5900457980) : une année civile complète l'est jour par jour, une année future est un
    scénario, et seule une année civile récente remplit les rubriques annuelles 1d et 4a du scan Flex-e."""

    def test_annee_future_est_un_scenario(self):
        _, fins = profil(ams(2027, 1, 1), ams(2028, 1, 1))
        r = scan_flex.annee_representative(fins, SCAN_LE)
        self.assertEqual((r["statut"], r["dans_les_3_ans"]), ("future", False))

    def test_2024_sans_31_decembre_nest_pas_une_annee_civile(self):
        kw, fins = profil(ams(2024, 1, 1), ams(2024, 12, 31))
        s = scan_flex.statistiques(kw, fins)
        self.assertEqual(len(kw), 35040)
        self.assertEqual(s["couverture"]["type"], "periode_annuelle")
        self.assertFalse(s["annee_complete"])
        self.assertTrue(s["duree_annuelle"])

    def test_temoins_annee_bissextile_et_ordinaire(self):
        for an, quarts in ((2024, 35136), (2025, 35040)):
            kw, fins = profil(ams(an, 1, 1), ams(an + 1, 1, 1))
            s = scan_flex.statistiques(kw, fins)
            self.assertEqual((len(kw), s["couverture"]["type"], s["couverture"]["annee"]), (quarts, "annee_civile", an))
            self.assertTrue(s["annee_complete"])
            self.assertEqual(scan_flex.annee_representative(fins, SCAN_LE)["statut"], "recente")

    def test_annee_en_cours_nest_pas_une_des_trois_dernieres(self):
        _, fins = profil(ams(2025, 12, 1), ams(2026, 9, 1))
        r = scan_flex.annee_representative(fins, SCAN_LE)
        self.assertEqual((r["annee"], r["statut"], r["dans_les_3_ans"]), (2026, "en_cours", False))

    def test_rapport_rubriques_annuelles_et_textes(self):
        kw, fins = profil(ams(2024, 1, 1), ams(2024, 12, 31))
        r = scan_flex.scanner(kw, fins, {})
        rubriques = dict(rapport_flex.conformite(r))
        self.assertEqual((rubriques["1d"], rubriques["4a"]), ("a_completer", "a_completer"))
        self.assertIn("pas une année civile complète", rapport_flex.rendre(r, "fr"))
        self.assertIn("geen volledig kalenderjaar", rapport_flex.rendre(r, "nl"))
        kw, fins = profil(ams(2027, 1, 1), ams(2028, 1, 1))
        r = scan_flex.scanner(kw, fins, {})
        self.assertEqual(dict(rapport_flex.conformite(r))["1d"], "a_completer")
        self.assertIn("un scénario et non une mesure récente", rapport_flex.rendre(r, "fr"))
        self.assertIn("een scenario en geen recente meting", rapport_flex.rendre(r, "nl"))

    def test_rubriques_annuelles_seulement_pour_une_annee_civile_recente(self):
        """Revue d'Astra de f0eb305 (P1) : 4a restait « calculé » pour une année complète future ou trop ancienne."""
        attendu = {2022: ("ancienne", "a_completer"), 2024: ("recente", "calcule"), 2027: ("future", "a_completer")}
        for an, (statut, rubrique) in attendu.items():
            kw, fins = profil(ams(an, 1, 1), ams(an + 1, 1, 1))
            r = scan_flex.scanner(kw, fins, {"tirages_confiance": 0})
            rubriques = dict(rapport_flex.conformite(r))
            self.assertEqual((r["statistiques"]["representativite"]["statut"], rubriques["1d"], rubriques["4a"]),
                             (statut, rubrique, rubrique), an)


def canonique(fins: list[datetime], kw: list[float]) -> str:
    return "fin_intervalle,puissance_kw\n" + "".join(f"{f.isoformat()},{v:g}\n" for f, v in zip(fins, kw))


class Anomalies(unittest.TestCase):
    """OF3 et AF04 : trous, doublons et retours en arrière sont refusés en disant combien, où et de quelle durée,
    sans rien combler ni supprimer. Avant, le refus s'arrêtait au premier cas, sans ligne ni durée."""

    def setUp(self):
        self.kw, self.fins = profil(ams(2025, 1, 1), ams(2025, 2, 1))

    def refus(self, texte: str) -> ValueError:
        import serveur
        with self.assertRaises(ValueError) as refus:
            serveur._lire_profil_detaille(texte, jours_civils=True)
        return refus.exception

    def test_trou_localise_avec_sa_duree(self):
        e = self.refus(canonique(self.fins[:1000] + self.fins[1096:], self.kw[:1000] + self.kw[1096:]))
        self.assertIn("1 trou", str(e))
        self.assertIn("96 quarts manquants", str(e))
        self.assertIn("lignes 1001 et 1002", str(e))
        self.assertEqual([c["code"] for c in e.constats], ["ANOMALIE_TROU"])

    def test_doublon_localise(self):
        e = self.refus(canonique(self.fins[:500] + [self.fins[499]] + self.fins[500:],
                                 self.kw[:500] + [self.kw[499]] + self.kw[500:]))
        self.assertIn("1 doublon", str(e))
        self.assertIn("lignes 501 et 502", str(e))

    def test_toutes_les_anomalies_comptees_rien_comble(self):
        fins = self.fins[:100] + self.fins[104:600] + [self.fins[599]] + self.fins[600:2000] + self.fins[2010:]
        kw = self.kw[:len(fins)]
        e = self.refus(canonique(fins, kw))
        self.assertEqual(sorted(c["code"] for c in e.constats), ["ANOMALIE_DOUBLON", "ANOMALIE_TROU", "ANOMALIE_TROU"])
        self.assertIn("2 trous (14 quarts manquants au total)", str(e))
        self.assertIn("Rien n'a été comblé ni supprimé", str(e))

    def test_export_configure_localise(self):
        import serveur
        lignes = ["tijdstip;afname"] + [f"{(f - QUART).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')};{v / 4:g}"
                                          for f, v in zip(self.fins[:300] + self.fins[304:], self.kw[:300] + self.kw[304:])]
        conf = {"colonne_temps": "tijdstip", "colonne_valeur": "afname", "format_temps": "ISO8601", "separateur": ";",
                "decimal": ".", "milliers": "aucun", "fuseau": "UTC", "horodatage_marque": "debut",
                "meetbedrijf": "test", "kanaal": "afname"}
        with self.assertRaises(ValueError) as refus:
            serveur.lire_export("\n".join(lignes) + "\n", conf)
        self.assertIn("lignes 301 et 302", str(refus.exception))
        self.assertIn("4 quarts manquants", str(refus.exception))

    def test_lignes_interverties_sans_faux_trou(self):
        """Revue d'Astra de 393def5 (P2-A) : deux lignes interverties donnaient « 2 trous », tous les quarts présents."""
        fins = list(self.fins)
        fins[1], fins[2] = fins[2], fins[1]
        e = self.refus(canonique(fins, self.kw))
        self.assertEqual([c["code"] for c in e.constats], ["ANOMALIE_ORDRE"])
        self.assertIn("1 retour en arrière", str(e))
        self.assertNotIn("trou", str(e).split("Trouvé")[1])
        self.assertNotIn("période manquante", str(e))

    def test_numeros_de_ligne_physiques_malgre_une_ligne_vide(self):
        """Revue d'Astra de 393def5 (P2-B) : une ligne vide décalait les numéros annoncés d'une unité."""
        import serveur
        conf = {"colonne_temps": "temps", "colonne_valeur": "valeur", "format_temps": "ISO8601", "separateur": ";",
                "decimal": ".", "milliers": "aucun", "fuseau": "UTC", "horodatage_marque": "fin", "meetbedrijf": "test",
                "kanaal": "afname"}
        with self.assertRaises(ValueError) as refus:
            serveur.lire_export("temps;valeur\n\n2025-01-01T00:15:00+00:00;25\n2025-01-01T00:45:00+00:00;25\n", conf)
        self.assertEqual(refus.exception.constats[0]["lignes"], [3, 4])
        texte = canonique(self.fins[:200] + self.fins[201:], self.kw[:199] + self.kw[200:])
        e = self.refus(texte.replace("\n", "\n\n", 1))
        self.assertEqual(e.constats[0]["lignes"], [202, 203])



CONF_LOCALE = {"colonne_temps": "tijdstip", "colonne_valeur": "afname", "format_temps": "%Y-%m-%d %H:%M", "separateur": ";",
               "decimal": ".", "milliers": "aucun", "fuseau": "Europe/Amsterdam", "horodatage_marque": "debut",
               "meetbedrijf": "test", "kanaal": "afname"}


def export_local(marque: str = "debut", melange: bool = False, retirer: int | None = None, utc: bool = False) -> str:
    """Export néerlandais typique autour du passage à l'heure d'hiver du 26/10/2025 : heure locale sans décalage."""
    t, borne, lignes = ams(2025, 10, 20).astimezone(timezone.utc), ams(2025, 11, 3).astimezone(timezone.utc), []
    while t < borne:
        repere = t if marque == "debut" else t + QUART
        texte = repere.strftime("%Y-%m-%dT%H:%M:%SZ") if utc else repere.astimezone(AMS).strftime("%Y-%m-%d %H:%M")
        lignes.append((texte, f"{0.5 + (t.hour % 5) / 10:g}"))
        t += QUART
    doubles = [i for i, (h, _) in enumerate(lignes) if h.startswith("2025-10-26 02:")]
    if melange:  # comme Fluvius : les deux heures classées par heure affichée, pas par ordre physique
        lignes[doubles[0]:doubles[-1] + 1] = sorted(lignes[doubles[0]:doubles[-1] + 1], key=lambda x: x[0])
    if retirer is not None:
        del lignes[doubles[retirer]]
    return "tijdstip;afname\n" + "".join(f"{h};{v}\n" for h, v in lignes)


class HeureRepetee(unittest.TestCase):
    """AF03, OF2 et les cinq conditions d'Astra (commentaire 5900270133) : l'heure répétée d'octobre en heure locale
    sans décalage est proposée par l'ordre des lignes, montrée avec ses lignes et ses deux décalages, et acceptée
    seulement sur confirmation liée à l'empreinte du fichier. Avant, tout le fichier était refusé sans alternative."""

    def lire(self, texte: str, **conf):
        import serveur
        journal = []
        return serveur.lire_export(texte, {**CONF_LOCALE, **conf}, journal=journal), journal

    def identite(self, texte: str, **conf) -> str:
        """Ce que l'interface fait confirmer : l'identité lue dans le refus (fichier, conventions, version du lecteur)."""
        with self.assertRaises(ValueError) as refus:
            self.lire(texte, **conf)
        return refus.exception.constats[0]["parametres"]["identite"]

    def test_proposee_avec_lignes_et_decalages(self):
        import hashlib
        texte = export_local()
        with self.assertRaises(ValueError) as refus:
            self.lire(texte)
        e = refus.exception
        self.assertEqual([c["code"] for c in e.constats], ["HEURE_REPETEE_A_CONFIRMER"])
        self.assertEqual(len(e.constats[0]["lignes"]), 8)
        for attendu in ("+02:00", "+01:00", hashlib.sha256(texte.encode("utf-8")).hexdigest(), e.constats[0]["parametres"]["identite"]):
            self.assertIn(attendu, str(e))
        # Relecture de Fable (FB5) : chaque heure répétée avec ses deux mesures, valeurs telles qu'écrites et instants
        # proposés, pour voir avant de confirmer que ce sont deux mesures et non un doublon.
        paires = e.constats[0]["paires"]
        self.assertEqual([p["heure"] for p in paires], ["02:00", "02:15", "02:30", "02:45"])
        self.assertEqual({(p["ete"]["valeur"], p["hiver"]["valeur"]) for p in paires}, {("0.5", "0.6")})
        self.assertTrue(all(p["ete"]["instant"].endswith("+02:00") and p["hiver"]["instant"].endswith("+01:00") for p in paires))
        self.assertEqual([p["ete"]["ligne"] for p in paires] + [p["hiver"]["ligne"] for p in paires], e.constats[0]["lignes"])

    def test_acceptee_sur_confirmation_liee_au_fichier(self):
        for marque in ("debut", "fin"):
            texte = export_local(marque)
            (valeurs, horodatages), journal = self.lire(texte, horodatage_marque=marque,
                                                        heure_repetee_confirmee=self.identite(texte, horodatage_marque=marque))
            self.assertEqual(len(valeurs), 14 * 96 + 4)
            self.assertEqual(len(set(horodatages)), len(horodatages))
            self.assertEqual([c["code"] for c in journal], ["HEURE_REPETEE_INTERPRETEE"])
        with self.assertRaises(ValueError):
            self.lire(export_local(), heure_repetee_confirmee="0" * 64)

    def test_confirmation_perimee_si_une_convention_change(self):
        """Revue d'Astra de 1842576 (P1-C) : la même confirmation, début d'intervalle devenu fin, décalait toute la série
        de 15 minutes sans nouvelle confirmation. La confirmation vaut pour ce fichier ET ces conventions."""
        texte = export_local()
        confirmee = self.identite(texte)
        self.lire(texte, heure_repetee_confirmee=confirmee)
        with self.assertRaises(ValueError) as refus:
            self.lire(texte, horodatage_marque="fin", heure_repetee_confirmee=confirmee)
        self.assertEqual([c["code"] for c in refus.exception.constats], ["HEURE_REPETEE_A_CONFIRMER"])

    def test_ordre_melange_ou_ligne_manquante_refuses_meme_confirmes(self):
        import hashlib
        for texte in (export_local(melange=True), export_local(retirer=5)):
            with self.assertRaises(ValueError) as refus:
                self.lire(texte, heure_repetee_confirmee=hashlib.sha256(texte.encode("utf-8")).hexdigest())
            self.assertIn("HEURE_REPETEE_ORDRE_AMBIGU", [c["code"] for c in getattr(refus.exception, "constats", [])])
            # Ordre mêlé : aucune paire proposée, rien à confirmer (cas intercalés jamais acceptés).
            self.assertFalse([c for c in getattr(refus.exception, "constats", []) if c.get("paires")])

    def test_export_utc_correct_accepte_sans_confirmation(self):
        (valeurs, _), journal = self.lire(export_local(utc=True), format_temps="ISO8601", fuseau="UTC")
        self.assertEqual((len(valeurs), journal), (14 * 96 + 4, []))

    def test_convertisseur_strict_empreinte_et_lignes_du_fichier_source(self):
        import hashlib
        import lecteur_csv_compteur as lcc
        texte = "# export test\n" + export_local()
        conf = dict(lcc.modele(), meetbedrijf="test", format_temps="%Y-%m-%d %H:%M", decimal=".", milliers="aucun",
                    fuseau="Europe/Amsterdam", horodatage_marque="debut", kanaal="afname", separateur=";",
                    colonne_temps="tijdstip", colonne_valeur="afname", compteur_unique=True, unite="kwh_par_quart",
                    lignes_avant_entete=1)
        with self.assertRaises(ValueError) as refus:
            lcc.convertir_csv(texte, conf)
        source = hashlib.sha256(texte.encode("utf-8")).hexdigest()
        self.assertIn(source, str(refus.exception))
        premiere = next(n for n, l in enumerate(texte.splitlines(), 1) if l.startswith("2025-10-26 02:00"))
        self.assertEqual(refus.exception.constats[0]["lignes"][0], premiere)
        confirmee = refus.exception.constats[0]["parametres"]["identite"]
        lu = lcc.convertir_csv(texte, {**conf, "heure_repetee_confirmee": confirmee})
        self.assertEqual(len(lu["valeurs_kw"]), 14 * 96 + 4)
        # Revue d'Astra de 1842576 (P2-D) : le journal de l'interprétation reste dans le résultat, donc dans import.json.
        (trace,) = lu["journal"]
        self.assertEqual((trace["code"], trace["lignes"][0], trace["parametres"]["decalages"]),
                         ("HEURE_REPETEE_INTERPRETEE", premiere, ["+02:00", "+01:00"]))
        # P1-C : changer l'unité change l'interprétation ; l'ancienne confirmation ne vaut plus.
        with self.assertRaises(ValueError):
            lcc.convertir_csv(texte, {**conf, "unite": "kw", "heure_repetee_confirmee": confirmee})



class Vraisemblance(unittest.TestCase):
    """OF1, AF01 et FB4, critères de phase 2 : jamais de rééchelonnement automatique. Une série qui ne fait que croître
    ressemble à un index cumulé et bloque sans confirmation explicite ; l'unité non recoupée avec une facture est dite.
    Avant, un index cumulé sous l'en-tête puissance_kw passait avec une pointe de 1,65 million de kW (audit T09)."""

    def setUp(self):
        self.kw, self.fins = profil(ams(2025, 1, 1), ams(2025, 2, 1))
        self.index = [sum(self.kw[:i + 1]) / 4 for i in range(len(self.kw))]

    def identite(self, kw: list[float]) -> str:
        with self.assertRaises(ValueError) as refus:
            scan_flex.scanner(kw, self.fins, {"tirages_confiance": 0})
        (alerte,) = [c for c in refus.exception.constats if c["code"] == "GRANDEUR_INDEX_POSSIBLE"]
        self.assertIsNone(alerte["parametres"]["confirmation"])
        self.assertIn("index cumulé", str(refus.exception))
        return alerte["parametres"]["identite"]

    def test_index_cumule_possible_bloque_sans_confirmation(self):
        confirmee = self.identite(self.index)
        r = scan_flex.scanner(self.index, self.fins, {"tirages_confiance": 0, "confirmation_grandeur": confirmee})
        (alerte,) = [c for c in r["qualite_donnees"]["constats"] if c["code"] == "GRANDEUR_INDEX_POSSIBLE"]
        self.assertEqual(alerte["parametres"]["confirmation"], confirmee)

    def test_confirmation_liee_a_la_serie(self):
        """Revue d'Astra de 143a896 (P1-E) : une confirmation en chaîne fixe valait pour n'importe quelle série."""
        autre = [10000 + 5 * i for i in range(len(self.fins))]
        with self.assertRaises(ValueError):
            scan_flex.scanner(autre, self.fins, {"tirages_confiance": 0, "confirmation_grandeur": self.identite(self.index)})

    def test_profil_ordinaire_sans_alerte_et_unite_non_recoupee_dite(self):
        r = scan_flex.scanner(self.kw, self.fins, {"tirages_confiance": 0})
        # Aucune alerte de vraisemblance. Sans statut, les valeurs sont d'origine inconnue (décision d'Astra du 30/09) :
        # raison tracée, puis les mêmes constats qu'une liste « inconnue ».
        qualite = ["QUALITE_INCONNUE", "QUALITE_VALEURS_NON_MESUREES", "QUALITE_POINTE_NON_MESUREE"]
        codes = [c["code"] for c in r["qualite_donnees"]["constats"]]
        self.assertEqual(codes, ["UNITE_NON_RECOUPEE", *qualite])
        r = scan_flex.scanner(self.kw, self.fins, {"tirages_confiance": 0, "unite_recoupee": "facture de janvier 2025"})
        self.assertEqual([c["code"] for c in r["qualite_donnees"]["constats"]], ["UNITE_RECOUPEE", *qualite])

    def test_confirmation_ou_recoupement_mal_formes_refuses(self):
        for fiche in ({"confirmation_grandeur": "oui"}, {"confirmation_grandeur": "puissance_moyenne_kw"},
                      {"unite_recoupee": ""}, {"unite_recoupee": 3}):
            with self.assertRaises(ValueError):
                scan_flex.scanner(self.kw, self.fins, {"tirages_confiance": 0, **fiche})



def reponse_kenter(kw: list[float], fins: list[datetime], estimes: tuple[int, ...] = (),
                   manuels: tuple[int, ...] = (), pics: dict[datetime, float] | None = None) -> list[dict]:
    """Réponse de l'API Kenter (canal 16180, kWh par quart, fin de période en Unix UTC), manuel v1.5 : une valeur
    estimée n'a pas de statut de validation (combinaison admise par lecteur_kenter). ``pics`` : kWmax de facturation
    du canal 18160, un par mois, à l'instant donné."""
    reponse = [{"channelId": "16180", "Measurements": [
        {"origin": "Estimated", "status": None, "timestamp": int(f.timestamp()), "value": v / 4} if i in estimes else
        {"origin": "Measured", "status": "ManualAccepted" if i in manuels else "Valid", "timestamp": int(f.timestamp()),
         "value": v / 4}
        for i, (v, f) in enumerate(zip(kw, fins))]}]
    if pics:
        reponse.append({"channelId": "18160", "Measurements": [
            {"origin": "Measured", "status": "Valid", "timestamp": int(instant.timestamp()), "value": valeur}
            for instant, valeur in pics.items()]})
    return reponse


class QualiteDeBoutEnBout(unittest.TestCase):
    """AF06, ON1 et ON3 (lot 1) : la qualité connue du lecteur arrive jusqu'au scan. Avant, scan_flex.lire_profil
    convertissait la réponse Kenter en CSV et ne gardait que valeurs et dates (constat d'Astra du 30/09)."""

    def setUp(self):
        import json
        import tempfile
        self.kw, self.fins = profil(ams(2025, 1, 6), ams(2025, 1, 20))
        self.pic = 500
        self.kw[self.pic] = 300.0
        self.dossier = tempfile.TemporaryDirectory()
        self.json = Path(self.dossier.name) / "kenter.json"
        self.json.write_text(json.dumps(reponse_kenter(self.kw, self.fins, estimes=(self.pic, 800))), encoding="utf-8")
        self.csv = Path(self.dossier.name) / "profil.csv"
        self.csv.write_text(canonique(self.fins, self.kw), encoding="utf-8")

    def tearDown(self):
        self.dossier.cleanup()

    def test_pointe_estimee_signalee_et_provenance_gardee(self):
        import hashlib
        lu = scan_flex.lire_profil_qualifie(self.json)
        self.assertEqual((lu["qualites"][self.pic], lu["qualites"][0]), ("estime", "mesure"))
        r = scan_flex.scanner(lu["kw"], lu["fins"], {"tirages_confiance": 0}, qualites=lu["qualites"], provenance=lu["provenance"])
        constats = {c["code"]: c for c in r["qualite_donnees"]["constats"]}
        self.assertEqual(constats["QUALITE_POINTE_NON_MESUREE"]["parametres"]["qualite"], "estime")
        self.assertEqual(constats["QUALITE_VALEURS_NON_MESUREES"]["parametres"]["estime"], 2)
        self.assertEqual(r["qualite_donnees"]["provenance"]["sha256"], hashlib.sha256(self.json.read_bytes()).hexdigest())

    def test_pointe_mesuree_non_signalee_et_csv_sans_statut_dit_inconnu(self):
        import json
        self.json.write_text(json.dumps(reponse_kenter(self.kw, self.fins, estimes=(800,))), encoding="utf-8")
        lu = scan_flex.lire_profil_qualifie(self.json)
        r = scan_flex.scanner(lu["kw"], lu["fins"], {"tirages_confiance": 0}, qualites=lu["qualites"], provenance=lu["provenance"])
        self.assertNotIn("QUALITE_POINTE_NON_MESUREE", [c["code"] for c in r["qualite_donnees"]["constats"]])
        lu = scan_flex.lire_profil_qualifie(self.csv)
        self.assertIsNone(lu["qualites"])
        r = scan_flex.scanner(lu["kw"], lu["fins"], {"tirages_confiance": 0}, qualites=lu["qualites"], provenance=lu["provenance"])
        self.assertIn("QUALITE_INCONNUE", [c["code"] for c in r["qualite_donnees"]["constats"]])
        self.assertEqual(r["qualite_donnees"]["provenance"]["format"], "csv_canonique")

    def test_detail_par_quart_conserve_et_avertissements_du_lecteur(self):
        """Revue d'Astra de 2c6a7d9 (P2-G) : origine et statut de chaque quart se réduisaient à « mesure » ou « estime »
        (ManualAccepted perdu) et la ligne de commande laissait tomber les avertissements du lecteur."""
        import json
        import tempfile
        self.json.write_text(json.dumps(reponse_kenter(self.kw, self.fins, estimes=(self.pic,), manuels=(4,))), encoding="utf-8")
        with tempfile.TemporaryDirectory() as sortie:
            fiche = Path(sortie) / "fiche.json"
            fiche.write_text(json.dumps({"tirages_confiance": 0}), encoding="utf-8")
            self.assertEqual(scan_flex.main(["scan_flex.py", str(self.json), str(fiche), sortie]), 0)
            qualite = json.loads((Path(sortie) / "scan.json").read_text(encoding="utf-8"))["qualite_donnees"]
        detail = qualite["detail"]
        self.assertEqual(detail["combinaison_courante"], {"origin": "Measured", "status": "Valid", "qualite": "mesure"})
        particuliers = {q["status"] or q["origin"]: q for q in detail["quarts_particuliers"]}
        self.assertEqual(set(particuliers), {"ManualAccepted", "Estimated"})
        self.assertEqual(particuliers["Estimated"]["fin"], self.fins[self.pic].astimezone(AMS).isoformat())
        self.assertIn("Des valeurs sont estimées, pas mesurées.", qualite["avertissements_lecteur"])

    def test_qualites_de_longueur_differente_refusees(self):
        with self.assertRaises(ValueError):
            scan_flex.scanner(self.kw, self.fins, {"tirages_confiance": 0}, qualites=["mesure"] * 10)



class ConfirmationParLeDossier(unittest.TestCase):
    """Revue d'Astra de 143a896 (P2-F) : le dossier client refusait confirmation_grandeur comme champ inconnu ; une
    vraie puissance croissante, recoupée par COH-UNITE, ne pouvait donc jamais être scannée par ce parcours."""

    def test_attente_puis_confirmation_valable(self):
        import tempfile
        import dossier_client
        from verifier_dossier_client import fiche_remplie
        _, fins = profil(ams(2025, 1, 1), ams(2025, 1, 8))
        serie = [100 + i / 10 for i in range(len(fins))]
        fiche = fiche_remplie()
        for champ, valeur in (("kwmax_facture", max(serie)), ("kwh_facture", sum(serie) / 4), ("tirages_confiance", 0),
                              ("periode_facture_debut", "2025-01-01"), ("periode_facture_fin", "2025-01-07")):
            fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "pièce synthétique de test, 1er au 7 janvier 2025"}
        with tempfile.TemporaryDirectory() as dossier:
            export = Path(dossier) / "profil.csv"
            export.write_text(canonique(fins, serie), encoding="utf-8")
            index = dossier_client.produire(fiche, export, Path(dossier) / "attente")
            self.assertEqual((index["diagnostic"]["puissance_fiable"], index["scan"]["produit"]), (True, False))
            (alerte,) = [c for c in index["scan"]["constats"] if c["code"] == "GRANDEUR_INDEX_POSSIBLE"]
            fiche["valeurs"]["confirmation_grandeur"] = {"valeur": alerte["parametres"]["identite"],
                                                         "source_document": "convention de la colonne relue avec le client"}
            index = dossier_client.produire(fiche, export, Path(dossier) / "confirme")
            self.assertTrue(index["scan"]["produit"])



class ImportAuditeParLeDossier(unittest.TestCase):
    """AF06, second volet (constat d'Astra du 30/09) : dossier_client ne chargeait pas l'audit import.json du
    convertisseur strict. Il le reprend désormais, seulement s'il décrit exactement le profil reçu (empreinte)."""

    def test_statuts_de_l_import_arrivent_au_scan_du_dossier(self):
        import json
        import subprocess
        import tempfile
        import dossier_client
        from verifier_dossier_client import fiche_remplie
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 8))
        estimes = {10, 11}
        source = "tijdstip;afname;status\n" + "".join(
            f"{f.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')};{v / 4:g};{'E' if i in estimes else 'V'}\n"
            for i, (v, f) in enumerate(zip(kw, fins)))
        import lecteur_csv_compteur
        conf = dict(lecteur_csv_compteur.modele(), meetbedrijf="test", format_temps="ISO8601", decimal=".", milliers="aucun",
                    fuseau="UTC", horodatage_marque="fin", kanaal="afname", separateur=";", colonne_temps="tijdstip",
                    colonne_valeur="afname", colonne_statut="status", statuts={"V": "valide", "E": "estime"},
                    compteur_unique=True, unite="kwh_par_quart")
        fiche = fiche_remplie()
        for champ, valeur in (("kwmax_facture", max(kw)), ("kwh_facture", sum(kw) / 4), ("tirages_confiance", 0),
                              ("periode_facture_debut", "2025-01-01"), ("periode_facture_fin", "2025-01-07")):
            fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "pièce synthétique de test, 1er au 7 janvier 2025"}
        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier)
            (racine / "export.csv").write_text(source, encoding="utf-8")
            (racine / "conf.json").write_text(json.dumps(conf), encoding="utf-8")
            subprocess.run([sys.executable, str(Path(__file__).with_name("lecteur_csv_compteur.py")), "convertir",
                            str(racine / "export.csv"), "--configuration", str(racine / "conf.json"), "--sortie",
                            str(racine / "import")], check=True, capture_output=True)
            export = racine / "import" / "profil.csv"
            index = dossier_client.produire(fiche, export, racine / "dossier")
            self.assertTrue(index["scan"]["produit"])
            scan = json.loads((racine / "dossier" / "scan.json").read_text(encoding="utf-8"))
            constats = {c["code"]: c for c in scan["qualite_donnees"]["constats"]}
            self.assertEqual(constats["QUALITE_VALEURS_NON_MESUREES"]["parametres"]["estime"], 2)
            # Revue d'Astra de d5ec7f4 (P1-H) : « valide » dit une validation, pas une origine mesurée.
            self.assertEqual(constats["QUALITE_VALEURS_NON_MESUREES"]["parametres"]["inconnue"], len(kw) - 2)
            self.assertEqual(scan["qualite_donnees"]["provenance"]["import"]["format"], "csv_declare")
            # Page qualité (FB1, sections 1, 4 et 6) : meetbedrijf du dossier, bilan du fichier d'origine, recoupements chiffrés.
            import html
            page = html.unescape((racine / "dossier" / "rapport-flex.html").read_text(encoding="utf-8"))
            debut = page.index("Recoupements indépendants")
            recoupements = page[debut:page.index("Alertes et confirmations", debut)]
            for attendu in ("kWmax facturé contre pointe du profil", "Énergie facturée contre énergie du profil",
                            "période comparée 2025-01-01 00:00 → 2025-01-08 00:00", "concordant",
                            "Seuil interne de Contingency", "Seuils internes de Contingency"):
                self.assertIn(attendu, recoupements)
            self.assertNotIn("non fait", recoupements)
            self.assertIn("enregistrements CSV du fichier d'origine", page)
            self.assertIn("déclaré dans le dossier", page)
            # Conventions de l'import (fuseau déclaré UTC, marqueur de fin), dites déclarées (critère 1 de Fable).
            self.assertIn("déclaré à l'import : fin de chaque quart d'heure, converti en fin", page)
            self.assertRegex(page, r"Fuseau</th><td>UTC</td>")
            # Un profil modifié après l'import ne reprend pas un audit qui ne le décrit plus.
            lignes = export.read_text(encoding="utf-8").splitlines()
            lignes[1] += "0" if "." in lignes[1] else ".0"  # même nombre, autres octets
            export.write_text("\n".join(lignes) + "\n", encoding="utf-8")
            dossier_client.produire(fiche, export, racine / "dossier-2")
            scan = json.loads((racine / "dossier-2" / "scan.json").read_text(encoding="utf-8"))
            self.assertIn("QUALITE_INCONNUE", [c["code"] for c in scan["qualite_donnees"]["constats"]])
            self.assertIn("import_ignore", scan["qualite_donnees"]["provenance"])
            # Audit devenu inutilisable : la conclusion n'en devient pas plus affirmative (décision d'Astra du 30/09).
            premier = json.loads((racine / "dossier" / "scan.json").read_text(encoding="utf-8"))
            self.assertEqual(scan["reserve_pointe"]["qualite"], premier["reserve_pointe"]["qualite"])



class AuditImportRobuste(unittest.TestCase):
    """Revue d'Astra de d5ec7f4 : origine documentée (P1-H), lignes source gardées (P2-G), audit mal formé (P2-I)."""

    def test_origine_mesuree_documentee(self):
        import lecteur_csv_compteur as lcc
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 2))
        texte = "tijdstip;afname;status\n" + "".join(f"{f.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')};{v / 4:g};M\n"
                                                     for f, v in zip(fins, kw))
        conf = dict(lcc.modele(), meetbedrijf="test", format_temps="ISO8601", decimal=".", milliers="aucun", fuseau="UTC",
                    horodatage_marque="fin", kanaal="afname", separateur=";", colonne_temps="tijdstip", colonne_valeur="afname",
                    colonne_statut="status", compteur_unique=True, unite="kwh_par_quart")
        self.assertEqual({q["qualite"] for q in lcc.convertir_csv(texte, {**conf, "statuts": {"M": "mesure"}})["qualites"]}, {"mesure"})
        lu = lcc.convertir_csv(texte, {**conf, "statuts": {"M": "valide"}})
        self.assertTrue(any("origine" in a for a in lu["avertissements"]))

    def test_lignes_source_discontinues_gardees(self):
        details = [{"ligne_source": 2 + 2 * i, "statut_source": "V", "qualite": "valide"} for i in range(672)]
        _, fins = profil(ams(2025, 1, 1), ams(2025, 1, 8))
        detail = scan_flex.detail_qualite(fins, details)
        self.assertEqual((detail["quarts_particuliers"], detail["lignes_source"]), ([], [[2, 672, 2]]))

    def test_audit_mal_forme_ecarte_sans_plantage(self):
        import json
        import tempfile
        import diagnostic
        with tempfile.TemporaryDirectory() as dossier:
            export = Path(dossier) / "profil.csv"
            export.write_text("fin_intervalle,puissance_kw\n", encoding="utf-8")
            for audit in ([], {"provenance": []}, {"provenance": {}, "qualites": ["x"]}, {"provenance": {}, "qualites": [{}]}):
                (Path(dossier) / "import.json").write_text(json.dumps(audit), encoding="utf-8")
                qualites, provenance = diagnostic.qualite_import(export, 1)
                self.assertIsNone(qualites)
                self.assertIn("import_ignore", provenance)



class PageQualite(unittest.TestCase):
    """FB1 (Fable, docs/maquettes) : page « Qualité des données » en tête du rapport Flex-e, FR et NL, remplie par les
    constats, la provenance et le détail de qualité du scan ; textes du catalogue d'Astra (messages_fiabilite)."""

    @classmethod
    def setUpClass(cls):
        import json
        import tempfile
        kw, fins = profil(ams(2025, 1, 6), ams(2025, 1, 20))
        kw[500] = 300.0
        cls.dossier = tempfile.TemporaryDirectory()
        chemin = Path(cls.dossier.name) / "kenter.json"
        chemin.write_text(json.dumps(reponse_kenter(kw, fins, estimes=(500,), manuels=(4,))), encoding="utf-8")
        lu = scan_flex.lire_profil_qualifie(chemin)
        cls.r = scan_flex.scanner(lu["kw"], lu["fins"], {"tirages_confiance": 0}, qualites=lu["qualites"],
                                  provenance=lu["provenance"], details_qualite=lu["details_qualite"],
                                  avertissements=lu["avertissements"])
        cls.fr, cls.nl = rapport_flex.rendre(cls.r, "fr"), rapport_flex.rendre(cls.r, "nl")

    @classmethod
    def tearDownClass(cls):
        cls.dossier.cleanup()

    def test_page_en_tete_avec_fichier_empreinte_et_statuts(self):
        sha = self.r["qualite_donnees"]["provenance"]["sha256"]
        for html, titre, statut in ((self.fr, "Qualité des données", "estimé"), (self.nl, "Kwaliteit van de gegevens", "geschat")):
            self.assertLess(html.index(titre), html.index("<h2", html.index(titre) + 1))
            self.assertIn(sha, html)
            self.assertIn(statut, html)
            self.assertIn("kenter.json", html)

    def test_pointe_estimee_a_confirmer_et_textes_du_catalogue(self):
        import messages_fiabilite
        attendu = messages_fiabilite.message_fiabilite("QUALITE_POINTE_NON_MESUREE", "nl",
                                                       **next(c for c in self.r["qualite_donnees"]["constats"]
                                                              if c["code"] == "QUALITE_POINTE_NON_MESUREE")["parametres"])
        self.assertIn(rapport_flex.e(attendu), self.nl)
        self.assertIn("à confirmer", self.fr)
        self.assertIn("handmatig aanvaard", self.nl)

    def test_rapport_nl_sans_texte_generique_francais(self):
        for mot in ("déclaration du fichier", "la source ne fournit", "Qualité des données", "à confirmer"):
            self.assertNotIn(mot, self.nl)



class PageQualiteRendu(unittest.TestCase):
    """Revue d'Astra de fb1b673 : jours particuliers qualifiés par le calendrier (P2-J), avertissements localisés (P2-K),
    échappement simple (P2-L), références client jamais confondues avec un code interne (P2-M)."""

    def scan(self, debut: datetime, fin: datetime, **fiche):
        import json
        import tempfile
        kw, fins = profil(debut, fin)
        kw[500] = 300.0
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "kenter.json"
            chemin.write_text(json.dumps(reponse_kenter(kw, fins, estimes=(500,), manuels=(4,))), encoding="utf-8")
            lu = scan_flex.lire_profil_qualifie(chemin)
        return scan_flex.scanner(lu["kw"], lu["fins"], {"tirages_confiance": 0, **fiche}, qualites=lu["qualites"],
                                 provenance=lu["provenance"], details_qualite=lu["details_qualite"],
                                 avertissements=lu["avertissements"])

    def test_jour_tronque_n_est_pas_un_changement_d_heure(self):
        r = self.scan(datetime(2025, 1, 1, 1, tzinfo=AMS), ams(2025, 1, 15))
        fr = rapport_flex._section_qualite(r, "fr")
        self.assertNotIn("heure d&#x27;été", fr)
        self.assertIn("jour partiel", fr)
        r = self.scan(ams(2025, 3, 24), ams(2025, 4, 7))
        self.assertIn("passage à l&#x27;heure d&#x27;été", rapport_flex._section_qualite(r, "fr"))

    def test_avertissements_du_lecteur_localises(self):
        nl = rapport_flex._section_qualite(self.scan(ams(2025, 1, 6), ams(2025, 1, 20)), "nl")
        self.assertNotIn("Des valeurs sont estimées", nl)
        self.assertIn("geschat", nl)

    def test_reference_client_echappee_une_fois_et_jamais_prise_pour_un_code(self):
        from html import unescape
        fr = rapport_flex._section_qualite(self.scan(ams(2025, 1, 6), ams(2025, 1, 20), unite_recoupee="facture d'essai & annexe"), "fr")
        self.assertNotIn("&amp;#x27;", fr)
        self.assertNotIn("&amp;amp;", fr)
        self.assertIn("facture d'essai & annexe", unescape(fr))
        nl = rapport_flex._section_qualite(self.scan(ams(2025, 1, 6), ams(2025, 1, 20), unite_recoupee="coh_unite"), "nl")
        self.assertIn("coh_unite", nl)
        self.assertNotIn("COH-UNITE van de diagnose", nl)



class ApercuImport(unittest.TestCase):
    """FB5 (Fable, docs/maquettes/apercu-import.html) : avant tout usage, ce qui fait voir une erreur. Jours de contrôle
    qualifiés par le calendrier, et pointe de chaque mois sous l'unité déclarée ET sous l'autre unité possible, sans
    choisir à la place de l'utilisateur ; le contrôle est écrit dans l'audit de l'import."""

    def test_pointes_mensuelles_sous_les_deux_unites_et_jours_de_controle(self):
        import horodatages
        kw, fins = profil(datetime(2025, 3, 1, 1, tzinfo=AMS), ams(2025, 4, 1))
        c = horodatages.controle_import(kw, [f.isoformat() for f in fins], "kwh_par_quart")
        (mars,) = c["pointes_mensuelles"]
        self.assertEqual((mars["mois"], mars["pointe_kw"], mars["pointe_kw_autre_unite"]), ("2025-03", 200.0, 50.0))
        self.assertEqual(c["autre_unite"], "kw")
        motifs = {j["jour"]: (j["quarts"], j["motif"]) for j in c["jours"]}
        self.assertEqual(motifs["2025-03-01"], (92, "partiel"))
        self.assertEqual(motifs["2025-03-30"], (92, "ete"))

    def test_controle_dans_le_resultat_du_convertisseur(self):
        import lecteur_csv_compteur as lcc
        kw, fins = profil(ams(2025, 10, 20), ams(2025, 11, 3))
        texte = "tijdstip;afname\n" + "".join(f"{f.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')};{v / 4:g}\n"
                                              for f, v in zip(fins, kw))
        conf = dict(lcc.modele(), meetbedrijf="test", format_temps="ISO8601", decimal=".", milliers="aucun", fuseau="UTC",
                    horodatage_marque="fin", kanaal="afname", separateur=";", colonne_temps="tijdstip",
                    colonne_valeur="afname", compteur_unique=True, unite="kwh_par_quart")
        lu = lcc.convertir_csv(texte, conf)
        self.assertEqual({j["motif"] for j in lu["controle"]["jours"] if j["jour"] == "2025-10-26"}, {"hiver"})
        self.assertEqual(lu["controle"]["pointes_mensuelles"][0]["pointe_kw"], 200.0)



class CorpusFluvius(unittest.TestCase):
    """AF24 et FB3 : l'export open data Fluvius (Belgique, attribué, docs/donnees/fluvius) écrit « Z » sur des heures
    locales. Aucune ligne n'est supprimée ni devinée : chaque doublon d'octobre est nommé avec ses deux lignes, le saut
    de mars est signalé, et rien n'est lu comme une série valide. Le concurrent, lui, supprimait 4 quarts en silence."""

    def test_doublons_d_octobre_et_saut_de_mars_nommes_sans_suppression(self):
        import serveur
        texte = (Path(__file__).resolve().parents[1] / "docs/donnees/fluvius/fluvius-2024-compteur-301-trois-jours.csv").read_text(encoding="utf-8")
        conf = {"colonne_temps": "Datum_Startuur", "colonne_valeur": "Volume_Afname_KWh", "format_temps": "ISO8601",
                "separateur": ",", "decimal": ".", "milliers": "aucun", "fuseau": "UTC", "horodatage_marque": "debut",
                "meetbedrijf": "Fluvius, open data (BE)", "kanaal": "afname"}
        with self.assertRaises(ValueError) as refus:
            serveur.lire_export(texte, conf)
        constats = refus.exception.constats
        doublons = [c["lignes"] for c in constats if c["code"] == "ANOMALIE_DOUBLON"]
        self.assertEqual(doublons, [[198, 199], [200, 201], [202, 203], [204, 205]])
        (mars,) = [c for c in constats if c["code"] == "ANOMALIE_TROU" and c["lignes"] == [9, 10]]
        self.assertEqual(mars["parametres"]["quarts"], 4)

    def test_z_contredit_le_fuseau_declare(self):
        """Second cas de Fable (relecture du 30/09) : le jour ordinaire du même fichier, déclaré en heure de Bruxelles
        alors que chaque horodatage porte « Z ». Avant, le Z l'emportait en silence : lecture décalée de deux heures."""
        import serveur
        lignes = (Path(__file__).resolve().parents[1] / "docs/donnees/fluvius/fluvius-2024-compteur-301-trois-jours.csv"
                  ).read_text(encoding="utf-8").splitlines()
        texte = "\n".join([lignes[0]] + [ligne for ligne in lignes[1:] if ",2024-06-15," in ligne]) + "\n"
        conf = {"colonne_temps": "Datum_Startuur", "colonne_valeur": "Volume_Afname_KWh", "format_temps": "ISO8601",
                "separateur": ",", "decimal": ".", "milliers": "aucun", "fuseau": "Europe/Brussels", "horodatage_marque": "debut",
                "meetbedrijf": "Fluvius, open data (BE)", "kanaal": "afname"}
        with self.assertRaises(ValueError) as refus:
            serveur.lire_export(texte, conf)
        (constat,) = refus.exception.constats
        self.assertEqual((constat["code"], constat["gravite"], constat["lignes"]), ("FUSEAU_CONTRADICTOIRE", "bloquant", [2]))
        self.assertEqual(constat["parametres"], {"ligne": 2, "valeur_brute": "2024-06-15T00:00:00.000Z",
                                                 "convention": "Europe/Brussels (UTC+02:00)"})
        from messages_fiabilite import message_fiabilite
        self.assertIn("2024-06-15T00:00:00.000Z", message_fiabilite("FUSEAU_CONTRADICTOIRE", "nl", **constat["parametres"]))
        # Déclaré UTC, le même jour est accepté : cela prouve seulement que marqueur et déclaration concordent, pas la
        # chronologie physique, que la légende du fichier contredit (remarque d'Astra sur 96c8768).
        self.assertEqual(len(serveur.lire_export(texte, conf | {"fuseau": "UTC"})[0]), 96)



class PageQualiteSections(unittest.TestCase):
    """Écarts FB1 annoncés au récap du lot 1 : bilan des lignes et recoupements en sections propres, EAN et meetbedrijf
    dans la provenance (critères 1 et 2 de Fable)."""

    def test_bilan_recoupements_ean_et_meetbedrijf(self):
        import json
        import tempfile
        kw, fins = profil(ams(2025, 1, 6), ams(2025, 1, 20))
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "kenter.json"
            chemin.write_text(json.dumps(reponse_kenter(kw, fins)), encoding="utf-8")
            lu = scan_flex.lire_profil_qualifie(chemin)
        r = scan_flex.scanner(lu["kw"], lu["fins"], {"tirages_confiance": 0, "ean": "871685900000000123"},
                              qualites=lu["qualites"], provenance=lu["provenance"], details_qualite=lu["details_qualite"])
        for langue, titres in (("fr", ("Bilan des lignes", "Recoupements", "Meetbedrijf")),
                               ("nl", ("Balans van de regels", "Vergelijkingen", "Meetbedrijf"))):
            page = rapport_flex._section_qualite(r, langue)
            for titre in titres:
                self.assertIn(titre, page)
            self.assertIn("871685900000000123", page)
            self.assertIn("Kenter", page)

    def test_fuseau_marqueur_et_versions_selon_la_source(self):
        """Relecture de Fable du 30/09, critères 1 et 2 : quel fuseau, quel marqueur, déclarés par qui ; sections Q1 à Q8 ;
        versions des règles ; ponctuation néerlandaise sans espace avant les deux-points."""
        import html
        import json
        import tempfile
        kw, fins = profil(ams(2025, 1, 6), ams(2025, 1, 20))
        with tempfile.TemporaryDirectory() as dossier:
            kenter, csv_canonique = Path(dossier) / "kenter.json", Path(dossier) / "profil.csv"
            kenter.write_text(json.dumps(reponse_kenter(kw, fins)), encoding="utf-8")
            csv_canonique.write_text(canonique(fins, kw), encoding="utf-8")
            lus = [scan_flex.lire_profil_qualifie(c) for c in (kenter, csv_canonique)]
        for lu, attendu in zip(lus, ("UTC (horodatage Unix)", "décalage UTC écrit sur chaque ligne")):
            r = scan_flex.scanner(lu["kw"], lu["fins"], {"tirages_confiance": 0}, qualites=lu["qualites"],
                                  provenance=lu["provenance"], details_qualite=lu["details_qualite"])
            page = html.unescape(rapport_flex._section_qualite(r, "fr"))
            for texte in (attendu, "jours civils comptés en heure d'Amsterdam", "Q2. Conventions", "Q8. Ce que",
                          f"règles de vraisemblance du {scan_flex.VERSION_VRAISEMBLANCE}"):
                self.assertIn(texte, page)
            nl = html.unescape(rapport_flex._section_qualite(r, "nl"))
            self.assertIn("Q4. Balans van de regels", nl)
            self.assertNotRegex(nl, r"\w : ")  # « gecontroleerd: », jamais « gecontroleerd : »



class RevueAstra26ba18b(unittest.TestCase):
    """Revue d'Astra de 26ba18b : contrôle bloqué rendu comme tel (P1-Q), enregistrements CSV comptés comme le lecteur
    (P2-R), EAN numérique refusé (P2-S), seuils nommés internes (P2-T), bilan d'import aux trois comptes (P2-U)."""

    def test_p1q_energie_invalide_reste_bloquante(self):
        import html
        import tempfile
        import dossier_client
        from verifier_dossier_client import fiche_remplie
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        fiche = fiche_remplie()
        for champ, valeur in (("kwmax_facture", max(kw)), ("kwh_facture", -1), ("tirages_confiance", 0),
                              ("periode_facture_debut", "2025-01-01"), ("periode_facture_fin", "2025-01-14")):
            fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "pièce synthétique de test, janvier 2025"}
        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier)
            (racine / "export.csv").write_text(canonique(fins, kw), encoding="utf-8")
            self.assertTrue(dossier_client.produire(fiche, racine / "export.csv", racine / "sortie")["scan"]["produit"])
            for nom, attendu, absent in (("rapport-flex.html", "Bloqué : énergie facturée invalide sur la facture", "non fait"),
                                         ("rapport-flex-nl.html", "Geblokkeerd: ongeldig energieverbruik op de factuur",
                                          "niet uitgevoerd")):
                page = html.unescape((racine / "sortie" / nom).read_text(encoding="utf-8"))
                ligne = page[page.index("<h3>Q6."):]
                ligne = ligne[:ligne.index("<h3>Q7.")].split("</tr>")[1]  # deuxième rangée : l'énergie
                self.assertIn(attendu, ligne)
                self.assertNotIn(absent, ligne)
                self.assertIn(_mot_verdict("bloquant", nom), ligne)

    def test_p2r_cellule_citee_multiligne_sans_fausse_exclusion(self):
        import tempfile
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        lignes = canonique(fins, kw).splitlines()
        lignes[1] = f'{fins[0].isoformat()},"{kw[0]:g}\n"'
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "profil.csv"
            chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
            lu = scan_flex.lire_profil_qualifie(chemin)
        self.assertEqual(len(lu["kw"]), len(kw))
        self.assertEqual(lu["provenance"]["bilan_lignes"],
                         {"recues": len(kw), "nature": "lignes", "doublons_identiques": 0, "ecartees": {}})

    def test_p2s_ean_numerique_refuse_texte_conserve(self):
        kw, fins = profil(ams(2025, 1, 6), ams(2025, 1, 20))
        for ean in (float(871685900000000123), 871685900000000123):
            with self.subTest(ean=ean), self.assertRaisesRegex(ValueError, "ean doit être écrit en texte"):
                scan_flex.scanner(kw, fins, {"tirages_confiance": 0, "ean": ean})
        r = scan_flex.scanner(kw, fins, {"tirages_confiance": 0, "ean": "001234567890123456"})
        self.assertIn("001234567890123456", rapport_flex._section_qualite(r, "nl"))
        # Même garantie par l'entrée commune de la page, qu'appellent les rapports France et solaire (P2-AB).
        with self.assertRaisesRegex(ValueError, "ean doit être écrit en texte"):
            scan_flex.qualite_jeu(kw, fins, {"ean": 871685900000000123})

    def test_p2u_bilan_repris_seulement_si_les_trois_comptes_concordent(self):
        import hashlib
        import json
        import tempfile
        import diagnostic
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        n = len(kw)
        with tempfile.TemporaryDirectory() as dossier:
            export = Path(dossier) / "profil.csv"
            export.write_text(canonique(fins, kw), encoding="utf-8")
            empreinte = hashlib.sha256(export.read_bytes()).hexdigest()
            for comptes, repris in (({"lignes_source": 2 * n, "lignes_ecartees": n, "lignes_importees": n}, True),
                                    ({"lignes_source": 2 * n, "lignes_ecartees": n, "lignes_importees": n - 1}, False),
                                    ({"lignes_source": 2 * n, "lignes_ecartees": n}, False),  # ancien audit incomplet
                                    ({"lignes_source": 2 * n, "lignes_ecartees": n, "lignes_importees": True}, False)):
                with self.subTest(comptes=comptes):
                    audit = {"provenance": {"empreinte_profil_csv": empreinte, "format": "csv_declare", **comptes},
                             "qualites": [{"qualite": "mesure"}] * n}
                    export.with_name("import.json").write_text(json.dumps(audit), encoding="utf-8")
                    qualites, provenance = diagnostic.qualite_import(export, n)
                    self.assertEqual(qualites, ["mesure"] * n)  # le lien des qualités reste vérifié par l'empreinte
                    bilan = provenance["bilan_lignes"]
                    if repris:
                        self.assertEqual((bilan["recues"], bilan["ecartees"]), (2 * n, {"filtre_compteur_canal": n}))
                        self.assertNotIn("bilan_source_ignore", provenance)
                    else:
                        self.assertEqual((bilan["recues"], bilan["nature"], bilan["ecartees"]), (n, "lignes", {}))
                        self.assertIn("lignes_importees", provenance["bilan_source_ignore"])



class QualiteInconnueEquivalente(unittest.TestCase):
    """Décision d'Astra du 30/09 (question de Fable) : qualité absente ou explicitement inconnue, même état des résultats
    qui dépendent de la pointe ; réserve visible sur la pointe, la marge, la croissance, le dimensionnement et les
    recommandations. Chiffres gardés à titre indicatif, aucun statut inventé."""

    def test_none_et_liste_inconnue_donnent_la_meme_reserve(self):
        import html
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        fiche = {"tirages_confiance": 0, "gtv_kw": 700}
        sans = scan_flex.scanner(kw, fins, fiche)
        inconnue = scan_flex.scanner(kw, fins, fiche, qualites=["inconnue"] * len(kw))
        self.assertEqual(sans["reserve_pointe"], inconnue["reserve_pointe"])
        self.assertEqual(sans["reserve_pointe"]["qualite"], "inconnue")
        self.assertEqual(sans["marge_gtv"], inconnue["marge_gtv"])  # chiffre indicatif conservé
        for langue, marge, raison in (("fr", "Marge sous le transport contracté", "n'est pas documentée"),
                                      ("nl", "Ruimte onder het gecontracteerde transportvermogen", "niet gedocumenteerd")):
            pages = [html.unescape(rapport_flex.rendre(x, langue)) for x in (sans, inconnue)]
            for page in pages:
                ligne = page[page.index(marge):]
                ligne = ligne[:ligne.index("</tr>")]
                self.assertIn(rapport_flex.NATURES[langue]["a_confirmer"], ligne)
                self.assertIn(raison, ligne)
                self.assertGreaterEqual(page.count(raison), 5)  # synthèse, pointe, marge, dimensionnement, croissance
            # Hors la page qualité, qui garde la raison « aucun statut », les deux rapports sont identiques.
            debut = [p.index("<h2>", p.index("<h2>") + 4) for p in pages]
            self.assertEqual(pages[0][debut[0]:], pages[1][debut[1]:])

    def test_pointe_mesuree_sans_reserve(self):
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        r = scan_flex.scanner(kw, fins, {"tirages_confiance": 0, "gtv_kw": 700}, qualites=["mesure"] * len(kw))
        self.assertIsNone(r["reserve_pointe"])
        self.assertNotIn(rapport_flex.NATURES["fr"]["a_confirmer"], rapport_flex.rendre(r, "fr"))
        self.assertEqual({r["statistiques"][c]["nature"] for c in ("energie_mwh", "pointe_kw", "moyenne_kw")}, {"mesure"})

    def test_valeurs_lues_jamais_dites_mesurees(self):
        """Revue d'Astra de 2adf522 (P1-AA, même règle que France et solaire) : sans qualité documentée comme mesure,
        énergie, pointe, moyenne, base, heures et facteur sont « lus », pas « mesurés » ; les chiffres ne changent pas."""
        import html
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        fiche = {"tirages_confiance": 0, "gtv_kw": 700}
        lu, mesure = scan_flex.scanner(kw, fins, fiche), scan_flex.scanner(kw, fins, fiche, qualites=["mesure"] * len(kw))
        cles = ("energie_mwh", "pointe_kw", "moyenne_kw", "charge_de_base_kw", "heures_utilisation", "facteur_charge")
        self.assertEqual({lu["statistiques"][c]["nature"] for c in cles}, {"lu"})
        self.assertEqual([lu["statistiques"][c]["valeur"] for c in cles], [mesure["statistiques"][c]["valeur"] for c in cles])
        for langue, badge, affirmation in (("fr", "Mesuré", "Pointe mesurée"), ("nl", "Gemeten", "Gemeten piek")):
            page = html.unescape(rapport_flex.rendre(lu, langue))
            section = page[page.index("<h2>", page.index("<h2>", page.index("<h2>") + 4) + 4):]  # après qualité et synthèse
            self.assertNotIn(f">{badge}<", section)
            self.assertNotIn(affirmation, page)
            self.assertIn(rapport_flex.NATURES[langue]["lu"], section)



class DiagnosticQualite(unittest.TestCase):
    """FB1 : la page qualité ouvre aussi le diagnostic, en FR, NL et texte, par les deux entrées publiques (revue d'Astra
    de 69800f2, P1-X et P2-Y). Chaque contrôle qui lit le profil porte la qualité des valeurs qu'il utilise (P1-W) ; un
    constat qui en dépend est « à confirmer » dans son titre et le décompte, une alerte reste une alerte (P1-V)."""

    def produire(self, qualites: list[str] | str | None, kw=None, fins=None, champs=(), commande=False) -> dict[str, Any]:
        import hashlib
        import json
        import tempfile
        import diagnostic
        import dossier_client
        from verifier_dossier_client import fiche_remplie
        if kw is None:
            kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        fiche = fiche_remplie()
        for champ, valeur in (("kwmax_facture", max(kw)), ("kwh_facture", sum(kw) / 4), ("tirages_confiance", 0),
                              ("periode_facture_debut", "2025-01-01"), ("periode_facture_fin", "2025-01-14"), *champs):
            fiche["valeurs"][champ] = {"valeur": valeur, "source_document": "pièce synthétique de test, janvier 2025"}
        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier)
            export = racine / "import" / "profil.csv"
            export.parent.mkdir()
            export.write_text(canonique(fins, kw), encoding="utf-8")
            if qualites:  # audit d'import qui décrit exactement ce profil
                liste = [qualites] * len(kw) if isinstance(qualites, str) else qualites
                audit = {"provenance": {"empreinte_profil_csv": hashlib.sha256(export.read_bytes()).hexdigest(),
                                        "format": "csv_declare"}, "qualites": [{"qualite": q} for q in liste]}
                export.with_name("import.json").write_text(json.dumps(audit), encoding="utf-8")
            if commande:
                diagnostic.produire({**fiche, "export_profil": str(export)}, racine / "sortie")
            else:
                dossier_client.produire(fiche, export, racine / "sortie")
            sortie = {nom: (racine / "sortie" / nom).read_text(encoding="utf-8")
                      for nom in ("rapport.html", "rapport-nl.html", "rapport.txt")}
            if not commande:
                sortie["index"] = json.loads((racine / "sortie" / "index.json").read_text(encoding="utf-8"))
            return sortie

    def bloc(self, page: str, controle: str) -> str:
        import html
        page = html.unescape(page)
        debut = page.rindex("<div", 0, page.index(f"{controle}", page.index("<h2>4.")))
        return page[debut:page.index("</div>", debut)]

    def test_qualite_absente_constats_a_confirmer_partout(self):
        import html
        for commande in (False, True):  # dossier client et commande du diagnostic : même source (P1-X)
            rapports = self.produire(None, commande=commande)
            for nom, titre, etat, synthese in (("rapport.html", "Qualité des données", "À confirmer", "à confirmer 2,"),
                                               ("rapport-nl.html", "Kwaliteit van de gegevens", "Te bevestigen",
                                                "te bevestigen 2,")):
                page = html.unescape(rapports[nom])
                self.assertLess(page.index(titre), page.index("<h2>1."))  # la page ouvre le rapport
                self.assertIn(synthese, page[page.index("<h2>1."):page.index("<h2>2.")])  # décompte à part
                for controle in ("CTRL-MARGE", "CTRL-DEPASSEMENT"):
                    bloc = self.bloc(rapports[nom], controle)
                    self.assertIn(etat, bloc.split("</p>")[0])  # le titre du contrôle, plus « Établi / Vastgesteld »
                    self.assertNotIn("#1a7f37", bloc)  # plus de vert
            texte = rapports["rapport.txt"]
            for repere in ("Q1. Fichier et provenance", "Q8. Ce que cette page ne prouve pas", "Empreinte SHA-256",
                           "[À confirmer] CTRL-MARGE", "À confirmer : Intervalles"):
                self.assertIn(repere, texte)  # page qualité en texte (P2-Y), réserves sous les contrôles
        index = {c["id"]: c for c in self.produire(None)["index"]["diagnostic"]["controles"]}
        self.assertEqual([r["code"] for r in index["CTRL-MARGE"]["reserves_qualite"]],
                         ["QUALITE_POINTE_NON_MESUREE", "QUALITE_VALEURS_NON_MESUREES"])  # export machine

    def test_pointe_mesuree_sans_reserve(self):
        import html
        rapports = self.produire("mesure")
        for nom, etat in (("rapport.html", "À confirmer"), ("rapport-nl.html", "Te bevestigen")):
            self.assertNotIn(etat, html.unescape(rapports[nom])[html.unescape(rapports[nom]).index("<h2>1."):]
                             .replace("Te bevestigen op de pagina", ""))
        self.assertTrue(all("reserves_qualite" not in c for c in rapports["index"]["diagnostic"]["controles"]))

    def test_depassement_estime_reste_une_alerte_sous_reserve(self):
        """Premier cas d'Astra : maximum mesuré à 800 kW, un autre quart estimé à 750 kW, GTV 700 kW. La pointe mesurée
        ne valide pas le second quart : dépassements et décompte de la marge sont sous réserve, et restent des alertes."""
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        kw[40], kw[40 + 96] = 800.0, 750.0
        qualites = ["mesure"] * len(kw)
        qualites[40 + 96] = "estime"
        rapports = self.produire(qualites, kw, fins)
        index = {c["id"]: c for c in rapports["index"]["diagnostic"]["controles"]}
        for controle in ("CTRL-MARGE", "CTRL-DEPASSEMENT"):
            self.assertEqual(index[controle]["statut"], "alerte")
            self.assertEqual([r["code"] for r in index[controle]["reserves_qualite"]], ["QUALITE_VALEURS_NON_MESUREES"])
            self.assertIn("Point d'attention", self.bloc(rapports["rapport.html"], controle).split("</p>")[0])
            self.assertIn("Valeurs estimées : 1", self.bloc(rapports["rapport.html"], controle))

    def test_hors_plage_de_qualite_inconnue_sous_reserve(self):
        """Second cas d'Astra : droit par plages 06:00-22:00, 100 kW hors plage ; pointe mesurée à 600 kW dans la plage,
        un quart hors plage de qualité inconnue à 150 kW. La non-conformité reste signalée, sous réserve."""
        kw, fins = profil(ams(2025, 1, 1), ams(2025, 1, 15))
        kw = [min(x, 90.0) for x in kw]
        kw[40], kw[4] = 600.0, 150.0  # 10:00-10:15 dans la plage ; 01:00-01:15 hors plage
        qualites = ["mesure"] * len(kw)
        qualites[4] = "inconnue"
        rapports = self.produire(qualites, kw, fins, champs=(("type_transportrecht", "tijdsblok"),
                                                             ("blocs_transport", "06:00-22:00"), ("gtv_hors_bloc_kw", 100)))
        droit = {c["id"]: c for c in rapports["index"]["diagnostic"]["controles"]}["CTRL-TRANSPORTRECHT"]
        self.assertEqual(droit["statut"], "alerte")
        self.assertEqual([r["code"] for r in droit["reserves_qualite"]], ["QUALITE_VALEURS_NON_MESUREES"])
        self.assertIn("de qualité inconnue : 1", self.bloc(rapports["rapport.html"], "CTRL-TRANSPORTRECHT"))



class RecoupementKenter18160(unittest.TestCase):
    """Dernier reste du lot 1 : Kenter publie aussi le kWmax de facturation (canal 18160, un par mois). La page qualité
    le recoupe avec la pointe des quarts du même mois (canal 16180 × 4), seulement pour un mois entièrement couvert,
    avec le seuil interne de rapprochement déjà nommé comme tel (revue d'Astra de 26ba18b, P2-T)."""

    def page(self, pics: dict[datetime, float], debut=None) -> str:
        import html
        import json
        import tempfile
        kw, fins = profil(debut or ams(2025, 1, 1), ams(2025, 2, 1))
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "kenter.json"
            chemin.write_text(json.dumps(reponse_kenter(kw, fins, pics={k: v(max(kw)) for k, v in pics.items()})),
                              encoding="utf-8")
            lu = scan_flex.lire_profil_qualifie(chemin)
        jeu = scan_flex.qualite_jeu(lu["kw"], lu["fins"], {}, lu["qualites"], lu["provenance"], lu["details_qualite"])
        return html.unescape(rapport_flex._section_qualite(jeu, "fr"))

    def ligne(self, page: str) -> str:
        debut = page.index("kWmax facturé par Kenter")
        return page[debut:page.index("</tr>", debut)]

    def test_mois_complet_concordant_ou_en_alerte(self):
        ligne = self.ligne(self.page({ams(2025, 1, 31): lambda pointe: pointe}))
        self.assertIn("2025-01", ligne)
        self.assertIn("concordant", ligne)
        ligne = self.ligne(self.page({ams(2025, 1, 31): lambda pointe: pointe + 10}))
        self.assertIn("alerte", ligne)
        self.assertIn("-10,0 kW", ligne)
        self.assertIn("Seuil interne de Contingency", ligne)

    def test_mois_incomplet_jamais_compare(self):
        ligne = self.ligne(self.page({ams(2025, 1, 31): lambda pointe: pointe + 10}, debut=ams(2025, 1, 10)))
        self.assertIn("mois incomplet", ligne)
        self.assertNotIn("alerte", ligne)

    def test_sans_canal_18160_pas_de_ligne(self):
        self.assertNotIn("kWmax facturé par Kenter", self.page({}))



class PasNatifEtFuseau(unittest.TestCase):
    """Relecture d'Astra pour France et solaire : la page qualité suit le pas natif et le fuseau du profil, sans rien
    recadrer. Profil de 10 minutes en heure de Paris autour du passage à l'heure d'été du 30/03/2025 (jour de 23 h)."""

    def test_page_au_pas_de_10_minutes_en_heure_de_paris(self):
        import html
        paris = ZoneInfo("Europe/Paris")
        depart, arrivee = datetime(2025, 3, 29, tzinfo=paris), datetime(2025, 4, 1, tzinfo=paris)
        n = int((arrivee.astimezone(timezone.utc) - depart.astimezone(timezone.utc)).total_seconds() // 600)
        fins = [(depart.astimezone(timezone.utc) + timedelta(minutes=10 * (i + 1))).astimezone(paris) for i in range(n)]
        kw = [40.0 + i % 7 for i in range(n)]
        jeu = scan_flex.qualite_jeu(kw, fins, {}, pas_minutes=10, zone="Europe/Paris")
        self.assertEqual(n, 426)  # 71 heures, jamais recadrées en quarts d'heure
        self.assertEqual(jeu["qualite_donnees"]["jours_particuliers"], [{"jour": "2025-03-30", "intervalles": 138, "motif": "ete"}])
        st = jeu["statistiques"]
        self.assertEqual((st["debut"], st["fin"], st["couverture"]["jours"]), ("2025-03-29T00:00:00", "2025-04-01T00:00:00", 3.0))
        for langue, attendus in (("fr", ("fin de chaque intervalle de 10 minutes", "10 minutes", "heure de Paris",
                                         "journée de 23 heures", "un intervalle de 10 minutes chacune")),
                                 ("nl", ("einde van elk interval van 10 minuten", "10 minuten", "Parijse tijd", "dag van 23 uur"))):
            page = html.unescape(rapport_flex._section_qualite(jeu, langue))
            for texte in attendus:
                self.assertIn(texte, page)
            # Plus aucun « quart d'heure » sur la page, constat de pointe compris (catalogue d'Astra, 9ac563f).
            # L'empreinte de 64 caractères reste sécable dans le rapport Flex seul (P2-Z : 542 px au lieu de 390).
            self.assertIn("table.g code{overflow-wrap:anywhere}", rapport_flex.STYLE)
            self.assertNotIn("quart" if langue == "fr" else "kwartier", page)
        self.assertEqual([c for c in jeu["qualite_donnees"]["constats"] if c["code"].startswith("QUALITE_POINTE")][0]["code"],
                         "QUALITE_POINTE_INTERVALLE_NON_MESUREE")
        self.assertEqual(jeu["reserve_pointe"]["pas_minutes"], 10)
        self.assertNotIn("horodatages", jeu)  # le JSON allégé ne recopie plus la série


def _mot_verdict(cle: str, nom: str) -> str:
    return rapport_flex.VOCABULAIRE[cle][nom.endswith("-nl.html")]


if __name__ == "__main__":
    unittest.main()
