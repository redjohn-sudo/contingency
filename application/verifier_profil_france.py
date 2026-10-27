"""Lecteur de profil France (profil_france.py) : pas détecté, fuseau, signe, changement d'heure, rééchantillonnage."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import profil_france as pf  # noqa: E402

echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def csv_regulier(debut: datetime, pas_min: int, n: int, valeur=lambda i: 100.0, suffixe: str = "") -> str:
    lignes = ["fin_intervalle,puissance_kw"]
    for i in range(n):
        fin = debut + timedelta(minutes=pas_min * (i + 1))
        lignes.append(f"{fin.isoformat()}{suffixe},{valeur(i)}")
    return "\n".join(lignes) + "\n"


def main():
    """Toutes les vérifications ; renvoie la liste des échecs."""
    echecs.clear()
    for pas in (5, 10, 15, 30, 60):
        p = pf.lire(csv_regulier(datetime(2025, 3, 3), pas, 48))
        verifier(p["pas_minutes"] == pas and abs(p["pas_h"] - pas / 60) < 1e-12 and len(p["valeurs"]) == 48,
                 f"pas de {pas} min détecté sur des horodatages sans décalage (lus en heure de Paris)")
    p = pf.lire(csv_regulier(datetime(2025, 3, 3), 10, 6, suffixe="+01:00"))
    verifier(p["fuseau_lu"] == "offset" and p["fins"][0] == datetime(2025, 3, 3, 0, 10) and p["fins_utc"][0] == datetime(2025, 3, 2, 23, 10),
             "décalage +01:00 lu : heure légale 00:10 à Paris, 23:10 la veille en UTC")
    p = pf.lire(csv_regulier(datetime(2025, 7, 3), 10, 6, suffixe="Z"))
    verifier(p["fins"][0] == datetime(2025, 7, 3, 2, 10), "« Z » (UTC) en été : 00:10 UTC devient 02:10 heure de Paris")
    # Passage à l'heure d'été du 30/03/2025 : 2 h à 3 h n'existe pas en heure légale, le pas reste régulier en UTC.
    debut = datetime(2025, 3, 30, 0, 0, tzinfo=pf.ZoneInfo("UTC"))
    texte = "fin_intervalle,puissance_kw\n" + "".join(f"{(debut + timedelta(minutes=10 * (i + 1))).isoformat()},100\n" for i in range(24))
    p = pf.lire(texte)
    heures = sorted({f.hour for f in p["fins"]})
    verifier(2 not in heures and 3 in heures and p["pas_minutes"] == 10, "changement d'heure de mars : l'heure 2 h n'apparaît pas, le pas de 10 min est gardé")
    # Passage à l'heure d'hiver du 26/10/2025 : 2 h à 3 h existe deux fois ; en UTC tout reste régulier.
    debut = datetime(2025, 10, 25, 23, 0, tzinfo=pf.ZoneInfo("UTC"))
    texte = "fin_intervalle,puissance_kw\n" + "".join(f"{(debut + timedelta(minutes=15 * (i + 1))).isoformat()},100\n" for i in range(24))
    p = pf.lire(texte)
    verifier(sum(1 for f in p["fins"] if f.hour == 2) == 8 and len(set(p["fins_utc"])) == 24,
             "changement d'heure d'octobre : huit quarts d'heure entre 2 h et 3 h en heure légale, tous distincts en UTC")
    # Signe : injection conservée, séparée.
    p = pf.lire(csv_regulier(datetime(2025, 6, 2), 15, 8, valeur=lambda i: [120, 80, -30, -50, 0, 60, -10, 90][i]))
    soutirage, injection = pf.separer(p["valeurs"])
    verifier(p["injection"] and soutirage == [120, 80, 0, 0, 0, 60, 0, 90] and injection == [0, 0, 30, 50, 0, 0, 10, 0],
             "valeurs négatives lues comme injection et séparées du soutirage, jamais refusées")
    verifier(pf.lire(csv_regulier(datetime(2025, 6, 2), 15, 4, valeur=lambda i: "12.5"))["valeurs"] == [12.5] * 4,
             "point décimal lu (la virgule décimale est le séparateur de colonnes de ce CSV : elle passe par l'import configuré)")
    # Garde-fous.
    cas = [("fin,puissance_kw\n2025-01-01T00:15:00,1\n2025-01-01T00:30:00,1\n", "CSV attendu"),
           (csv_regulier(datetime(2025, 1, 1), 15, 1), "au moins deux"),
           ("fin_intervalle,puissance_kw\n2025-01-01T00:15:00,1\n2025-01-01T00:30:00,1\n2025-01-01T01:00:00,1\n", "pas régulier"),
           (csv_regulier(datetime(2025, 1, 1), 7, 5), "non pris en charge"),
           ("fin_intervalle,puissance_kw\n2025-01-01T00:15:00,1\n2025-01-01T00:30:00+01:00,1\n", "tantôt"),
           ("fin_intervalle,puissance_kw\n2025-01-01T00:15:00,1\n2025-01-01T00:30:00,nan\n", "invalide"),
           ("fin_intervalle,puissance_kw\n2025-01-01T00:15:00,1\n2025-01-01T00:30:00,abc\n", "illisible"),
           ("fin_intervalle,puissance_kw\n2025-01-01T00:15:00,1\n2025-13-01T00:30:00,1\n", "illisible")]
    for texte, attendu in cas:
        try:
            pf.lire(texte)
            verifier(False, f"garde-fou « {attendu} »")
        except ValueError as erreur:
            verifier(attendu in str(erreur), f"garde-fou « {attendu} » : refusé avec un message clair")
    # Couverture et rééchantillonnage.
    p = pf.lire(csv_regulier(datetime(2024, 1, 1, 0, 0), 10, 6 * 24 * 366, suffixe="+01:00"))
    c = pf.couverture(p["fins"], p["pas_h"])
    verifier(c["annee_complete"] and c["intervalles_par_an"] == 52560 and c["jours"] == 366, "année bissextile 2024 au pas de 10 min : 52 560 intervalles par an, 366 jours")
    dix = lambda i: datetime(2025, 1, 1) + timedelta(minutes=10 * i)  # noqa: E731
    v, f = pf.reechantillonner([10, 20, 30, 40, 50, 60], [dix(i + 1) for i in range(6)], 10 / 60, 0.5)
    verifier(v == [20.0, 50.0] and f == [datetime(2025, 1, 1, 0, 30), datetime(2025, 1, 1, 1, 0)], "10 vers 30 min : moyennes par blocs de trois, fins alignées")
    v, f = pf.reechantillonner([1, 10, 20, 30, 40, 50, 60], [dix(i) for i in range(7)], 10 / 60, 0.5)
    verifier(v == [20.0, 50.0], "10 vers 30 min avec un intervalle de tête non aligné : il est ignoré, pas moyenné avec le bloc suivant")
    try:
        pf.reechantillonner([1, 2, 3], [datetime(2025, 1, 1, 0, 15 * (i + 1)) for i in range(3)], 0.25, 10 / 60)
        verifier(False, "15 vers 10 min refusé")
    except ValueError as erreur:
        verifier("multiple" in str(erreur), "15 vers 10 min refusé : pas cible non multiple du pas source")
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return list(echecs)


class Verification(unittest.TestCase):
    """Pour `python -m unittest discover` (README) : même contenu que le script."""

    def test_colonne_repetee_refusee(self):
        # A6 : DictReader garde la dernière colonne du même nom, 900 kW deviendraient 9 kW sans avertissement.
        with self.assertRaises(ValueError) as cm:
            pf.lire("fin_intervalle,puissance_kw,puissance_kw\n2026-01-01T00:15Z,900,9\n2026-01-01T00:30Z,900,9\n")
        self.assertIn("répétée", str(cm.exception))

    def test_message_heure_locale_sans_decalage(self):
        # OF8 : un export en heure locale sans décalage, autour du retour à l'heure d'hiver, était refusé avec
        # « écarts vus : [-2700, 900, 4500] s ». Le message doit nommer la ligne, l'heure et la marche à suivre.
        debut = datetime(2026, 10, 24, 22, 0, tzinfo=pf.ZoneInfo("UTC"))
        lignes = ["fin_intervalle,puissance_kw"] + [
            f"{(debut + timedelta(minutes=15 * (i + 1))).astimezone(pf.PARIS).replace(tzinfo=None).isoformat()},100" for i in range(40)]
        with self.assertRaises(ValueError) as cm:
            pf.lire("\n".join(lignes) + "\n")
        message = str(cm.exception)
        self.assertIn("Ligne 9", message)           # fin 00:00 UTC = 02:00 CEST, première heure locale ambiguë (02:00 existe deux fois le 25/10/2026)
        self.assertIn("02:00", message)
        self.assertIn("changement d'heure", message)
        self.assertIn("décalage UTC", message)
        self.assertNotIn("écarts vus", message)
        # Trou ordinaire : la ligne et les deux horodatages sont nommés.
        with self.assertRaises(ValueError) as cm:
            pf.lire("fin_intervalle,puissance_kw\n2026-01-01T00:15:00+01:00,1\n2026-01-01T00:30:00+01:00,1\n2026-01-01T01:15:00+01:00,1\n2026-01-01T01:30:00+01:00,1\n")
        message = str(cm.exception)
        self.assertIn("Ligne 4", message)
        self.assertIn("45 min", message)
        self.assertIn("00:30", message)
        self.assertIn("01:15", message)

    def test_provenance_du_profil(self):
        # FB1 : le lecteur dit ce qu'il a lu (empreinte, lignes, format ou conventions) pour la page qualité.
        import hashlib
        texte = csv_regulier(datetime(2025, 3, 3), 15, 8, suffixe="+01:00")
        p = pf.lire(texte)
        prov = p["provenance"]
        # P2-AC : l'empreinte du lecteur porte sur le texte fourni, avant retrait du BOM, et se nomme ainsi ; les octets
        # reçus (sha256, octets) ne sont connus que de l'appelant qui a lu le fichier.
        self.assertEqual(prov["sha256_texte"], hashlib.sha256(texte.encode("utf-8")).hexdigest())
        self.assertEqual(prov["octets_texte"], len(texte.encode("utf-8")))
        self.assertNotIn("sha256", prov)
        self.assertEqual(pf.lire("\ufeff" + texte)["provenance"]["sha256_texte"], hashlib.sha256(("\ufeff" + texte).encode("utf-8")).hexdigest())
        self.assertEqual(prov["bilan_lignes"], {"recues": 8, "nature": "lignes", "ecartees": {}, "doublons_identiques": 0})
        self.assertEqual(prov["format"], "csv_canonique")
        self.assertEqual(prov["pas_minutes"], 15)
        self.assertNotIn("conventions", prov)
        naif = pf.lire(csv_regulier(datetime(2025, 3, 3), 10, 8))["provenance"]
        self.assertEqual(naif["format"], "csv_france_heure_locale")
        self.assertEqual(naif["conventions"], {"fuseau": "Europe/Paris", "horodatage_marque": "fin"})
        self.assertEqual(naif["pas_minutes"], 10)

    def test_tout(self):
        self.assertEqual(main(), [])


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
