"""Diagnostic gratuit : trois pièces du client, un rapport HTML à lui renvoyer.

Usage :
    python3 diagnostic.py modele [liander|stedin|enexis] > fiche.json
                                                   fiche vierge aux libellés du gestionnaire
    python3 diagnostic.py rapport fiche.json sortie/  produit sortie/rapport.html

La fiche contient ce que l'on relève à la main sur le contrat (ATO) et sur la
facture. Chaque valeur porte le document dont elle vient : une valeur sans
origine est refusée, parce qu'un chiffre tapé de mémoire est exactement la
source des fausses conclusions (DeepSeek, soirée du 24/09).

Le profil est lu par le lecteur d'export de l'application. L'unité n'est jamais
devinée : elle est déclarée dans la fiche, puis vérifiée contre le kWmax de la
facture par coherence_mesures avant toute conclusion de puissance.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import controles
import rapport_controles

# Champ -> (document attendu, obligatoire pour la promesse faite au client)
# Champ -> (où le relever, obligatoire). Libellés de facture relevés par hermes
# sur le modèle officiel Liander « Maandfactuur Netbeheer Elektra », voir
# docs/contraintes/terrain/FORMATS-EXPORT-ET-FACTURE.md. Stedin : modèle trouvé et lu
# par DeepSeek (6/6, 25/09). Enexis : modèle non trouvé, les libellés peuvent différer. Les montants néerlandais s'écrivent
# « 1.010,00 » : point des milliers, virgule décimale, à retaper en 1010.00.
CHAMPS_FICHE = {
    "gtv_kw": ("ATO, page des puissances (gecontracteerd transportvermogen)", True),
    "capacite_aansluiting_kva": ("ATO, première page (aansluitcapaciteit)", False),
    "gtv_declare_kw": ("facture, en-tête « Gecontracteerd transportvermogen: » ou ligne "
                       "« Gecontracteerd transportverm. »", True),
    "confirmation_gtv_declare": ("relecture humaine de la dernière facture ou de l'accord applicable : valeur_kw, confirme_actuel, source_document, date_document, verifie_par, date_verification ; nécessaire si l'ATO et la déclaration divergent", False),
    "kwmax_facture": ("facture, section TRANSPORTDIENST, ligne « Maximale belasting »", True),
    "kwh_facture": ("facture, somme des lignes « Transportdiensten afn. laag » et « afn. hoog »", True),
    "periode_facture_debut": ("facture, « Verbruiksperiode », premier jour (AAAA-MM-JJ)", True),
    "periode_facture_fin": ("facture, « Verbruiksperiode », dernier jour inclus (AAAA-MM-JJ)", True),
    "mesure_au_point_de_livraison": ("ATO ou schéma unifilaire : mesure côté MS ou côté BT", False),
    "gestionnaire": ("en-tête de l'ATO ou de la facture", False),
    "commune": ("adresse du site", False),
    "unite_profil": ("en-tête de l'export : kw ou kwh_par_quart, jamais deviné", True),
    "meetbedrijf": ("ATO ou portail de mesure : meetverantwoordelijke de cet export", True),
    # Carte publique des gestionnaires (capaciteitskaart.netbeheernederland.nl), relevée par
    # l'ingénieur avec sa date : pas de données ouvertes téléchargeables au 25/09/2026.
    "statut_zone_afname": ("capaciteitskaart, couche Afname, à l'adresse du site : beschikbaar, beperkt, "
                           "onderzoek, tekort ou a_evaluer (couleur pas encore attribuée)", False),
    "statut_zone_teruglevering": ("capaciteitskaart, couche Teruglevering, à l'adresse du site : beschikbaar, "
                                  "beperkt, onderzoek, tekort ou a_evaluer (couleur pas encore attribuée)", False),
    "date_carte": ("date de consultation de la capaciteitskaart (AAAA-MM-JJ)", False),
    "annee_liberation_annoncee": ("capaciteitskaart ou page du gestionnaire : année annoncée de fin de "
                                  "congestion de la zone", False),
    "type_transportrecht": ("ATO, nature du droit de transport : vast, tijdsduurgebonden, tijdsblok ou "
                            "non_firm", False),
    "blocs_transport": ("ATO, blocs horaires du droit de transport en Europe/Amsterdam, ex. « 22:00-06:00 », bornes au quart d'heure", False),
    "gtv_hors_bloc_kw": ("ATO, transport autorisé hors des blocs horaires, en kW (0 si rien n'est prévu)", False),
}

# Ces champs restent facultatifs pour le diagnostic de réseau. Leur absence ne
# bloque que les contrôles batterie, jamais la mesure de la marge contractuelle.
from controles_batterie import BESOINS_SOC, BESOINS_PUISSANCE, BESOINS_ENGAGEMENTS
CHAMPS_FICHE.update({champ: (source, False)
                    for champ, source in (BESOINS_SOC | BESOINS_PUISSANCE | BESOINS_ENGAGEMENTS).items()})


# Libellés de facture par gestionnaire, sources primaires relevées par hermes :
# modèle officiel Liander, voorbeeldnota Stedin, glossaire officiel Enexis 2023.
# Voir docs/contraintes/terrain/FORMATS-EXPORT-ET-FACTURE.md, section 6.
LIBELLES_FACTURE = {
    "liander": {
        "kwmax_facture": "facture Liander, ligne « Maximale belasting ... KW »",
        "gtv_declare_kw": "facture Liander, ligne « Gecontracteerd transportverm. »",
        "kwh_facture": "facture Liander, somme « afn. laag » + « afn. hoog »",
    },
    "stedin": {
        "kwmax_facture": "facture Stedin, ligne « Afgenomen belasting ... kW » "
                         "(répété « Max ... kW » dans la SPECIFICATIE VERBRUIKEN)",
        "gtv_declare_kw": "facture Stedin, ligne « Gecontracteerd transportvermogen » ; "
                          "attention au prorata « 15/31 » écrit à côté",
        "kwh_facture": "facture Stedin, somme « Verbruik laag » + « Verbruik normaal »",
    },
    "enexis": {
        "kwmax_facture": "facture Enexis, ligne « Maximaal vermogen maand », "
                         "JAMAIS « Maximaal vermogen week »",
        "gtv_declare_kw": "facture Enexis, ligne « Gecontracteerd vermogen (kW) »",
        "kwh_facture": "facture Enexis, ligne « Getransporteerde kWh's »",
    },
}

AVERTISSEMENTS = {
    "enexis": "Enexis facture aussi un maximum HEBDOMADAIRE pour certaines catégories : "
              "relever le maximum du MOIS, sinon faux écart garanti avec le profil. "
              "Mise en page Enexis vue seulement dans le glossaire officiel : à vérifier "
              "sur la première vraie facture.",
    "stedin": "Stedin peut facturer une partie du mois (« 15/31 ») : la Verbruiksperiode "
              "saisie doit être celle réellement facturée. Les nombres s'écrivent « 50.137 » "
              "ou « 50137 » sur la même page : c'est le même nombre.",
}


def modele(gestionnaire: str | None = None) -> dict[str, Any]:
    cle = (gestionnaire or "").strip().lower()
    fiche = _modele_base()
    for champ, libelle in LIBELLES_FACTURE.get(cle, {}).items():
        fiche["valeurs"][champ]["source_document"] = libelle
    fiche["valeurs"]["gestionnaire"]["valeur"] = cle or None
    fiche["valeurs"]["meetbedrijf"] = {
        "valeur": None,
        "source_document": "facture, poste « Meetverantwoordelijke » : l'unité de l'export "
                           "dépend de ce meetbedrijf"}
    if cle in AVERTISSEMENTS:
        fiche["avertissement"] = AVERTISSEMENTS[cle]
    return fiche


def _modele_base() -> dict[str, Any]:
    return {
        "client": "nom anonymisé du site",
        "export_profil": "chemin du fichier CSV exporté",
        # À remplir après lecture de l'aperçu, aucune convention de portail
        # n'étant publiée de façon exploitable.
        "import_profil": {
            "colonne_temps": "",
            "colonne_valeur": "",
            "format_temps": "",
            "separateur": "",
            "decimal": "",
            "milliers": "",
            "fuseau": "",
            "horodatage_marque": "",
            "kanaal": "",
        },
        "valeurs": {champ: {"valeur": None, "source_document": doc}
                    for champ, (doc, _obligatoire) in CHAMPS_FICHE.items()},
    }


def valider(fiche: dict[str, Any]) -> list[str]:
    """Liste des problèmes. Vide seulement si la fiche tient la promesse faite."""
    problemes = []
    valeurs = fiche.get("valeurs", {})
    for champ, (doc, obligatoire) in CHAMPS_FICHE.items():
        entree = valeurs.get(champ) or {}
        present = entree.get("valeur") not in (None, "")
        if obligatoire and not present:
            problemes.append(f"{champ} manquant, à relever sur : {doc}")
        if present and not str(entree.get("source_document", "")).strip():
            problemes.append(f"{champ} n'indique pas de quel document il vient")
    if not Path(str(fiche.get("export_profil", ""))).is_file():
        problemes.append("export_profil introuvable")
    return problemes


def lire_profil(chemin: Path, configuration: dict[str, Any] | None = None) -> tuple[list[float], list[Any]]:
    """Délègue au lecteur de l'application ; garde valeurs ET horodatages.

    Les horodatages servent à vérifier que l'export couvre le mois facturé
    (COH-PERIODE). Les jeter, comme la première version le faisait, empêchait
    ce contrôle : relevé par codex le 24/09.
    """
    import serveur
    texte = chemin.read_text(encoding="utf-8-sig")
    # Une configuration de fiche vierge (toutes les cases vides) n'en est pas une :
    # la passer ferait refuser même le format interne explicite.
    if configuration and not any(str(v).strip() for v in configuration.values()):
        configuration = None
    try:
        if configuration:
            lu = serveur.lire_export(texte, configuration)
        else:
            lu = serveur._lire_profil_detaille(texte.lstrip("\ufeff"), jours_civils=True)
    except ValueError as erreur:
        raise SystemExit(f"Export illisible, rapport NON produit : {erreur}") from erreur
    if not isinstance(lu, tuple) or len(lu) < 2:
        raise SystemExit("Le lecteur d'export ne renvoie pas les horodatages : rapport NON produit.")
    return list(lu[0]), list(lu[1])


def configuration_import(fiche: dict[str, Any]) -> dict[str, Any] | None:
    """Configuration d'import de la fiche, meetbedrijf compris ; None pour le CSV interne."""
    configuration = dict(fiche.get("import_profil") or {})
    if not any(str(v).strip() for v in configuration.values()):
        return None
    configuration["meetbedrijf"] = (fiche.get("valeurs", {}).get("meetbedrijf") or {}).get("valeur") or ""
    return configuration


def controler(fiche: dict[str, Any], profil: tuple[list[float], list[Any]] | None = None,
              export: tuple[list[float], list[Any]] | None = None
              ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Dossier aplati et résultats des contrôles. ``profil`` (valeurs brutes, horodatages)
    évite une deuxième lecture quand l'appelant a déjà lu l'export (dossier_client).

    ``export`` : tout l'export quand ``profil`` n'en garde que la période facturée. La cohérence
    (période, unité, énergie) se vérifie sur la période ; marge et dépassements se lisent sur
    tout l'export, comme le scan du même dossier (audit Opus n°4)."""
    problemes = valider(fiche)
    if problemes:
        raise SystemExit("Fiche incomplète, rapport NON produit :\n- " + "\n- ".join(problemes))
    dossier = {champ: entree["valeur"] for champ, entree in fiche["valeurs"].items()
               if entree.get("valeur") not in (None, "")}
    if profil is None:
        profil = lire_profil(Path(fiche["export_profil"]), configuration_import(fiche))
    dossier["profil_brut"], dossier["profil_horodatages"] = list(profil[0]), list(profil[1])
    if export is not None:
        dossier["profil_export"] = (list(export[0]), list(export[1]))
    dossier["provenance"] = {c: e.get("source_document") for c, e in fiche["valeurs"].items()}
    return dossier, controles.executer_tous(dossier)


def qualite_import(export: Path, lignes: int) -> tuple[list[str] | None, dict[str, Any]]:
    """Provenance du profil, et qualités de l'audit import.json du convertisseur strict (AF06, constat d'Astra du
    30/09) : reprises seulement si l'audit décrit exactement ce profil (empreinte des octets, nombre de lignes)."""
    donnees = export.read_bytes()
    provenance: dict[str, Any] = {"fichier": export.name, "sha256": hashlib.sha256(donnees).hexdigest(), "octets": len(donnees),
                                  # Lecteur strict : chaque ligne de données devient un quart, sinon la lecture s'arrête.
                                  "bilan_lignes": {"recues": lignes, "nature": "lignes", "ecartees": {}, "doublons_identiques": 0}}
    audit = export.with_name("import.json")
    if not audit.exists():
        return None, provenance
    try:
        lu = json.loads(audit.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lu = None
    # Revue d'Astra de d5ec7f4 (P2-I) : structure et types vérifiés avant toute lecture ; un audit invérifiable est
    # écarté avec son motif, jamais repris ni cause d'un plantage.
    if not (isinstance(lu, dict) and isinstance(lu.get("provenance"), dict) and isinstance(lu.get("qualites"), list)
            and all(isinstance(q, dict) and isinstance(q.get("qualite"), str) for q in lu["qualites"])
            and isinstance(lu.get("journal", []), list) and isinstance(lu.get("avertissements", []), list)):
        provenance["import_ignore"] = "import.json illisible ou mal formé : qualités non reprises"
        return None, provenance
    source = lu["provenance"]
    if source.get("empreinte_profil_csv") != provenance["sha256"] or len(lu["qualites"]) != lignes:
        provenance["import_ignore"] = ("import.json présent mais il ne décrit pas ce profil (empreinte des octets ou nombre "
                                       "de lignes différents) : qualités non reprises")
        return None, provenance
    provenance["import"] = source
    provenance["journal_import"] = lu.get("journal") or []
    provenance["avertissements_import"] = lu.get("avertissements") or []
    provenance["details_import"] = lu["qualites"]
    # Bilan du fichier d'origine, repris seulement si ses trois comptes sont présents, entiers et décrivent exactement ce
    # profil ; sinon le bilan du fichier lu reste, et la raison est tracée (FB1, section 4 ; P2-U d'Astra de 26ba18b).
    # Un ancien audit sans l'un de ces comptes tombe dans le même cas.
    recues, ecartees, importees = (source.get(c) for c in ("lignes_source", "lignes_ecartees", "lignes_importees"))
    if all(type(n) is int for n in (recues, ecartees, importees)) and ecartees >= 0 and recues - ecartees == importees == lignes:
        provenance["bilan_lignes"] = {"recues": recues, "nature": "lignes_source", "doublons_identiques": 0,
                                      "ecartees": {"filtre_compteur_canal": ecartees} if ecartees else {}}
    else:
        provenance["bilan_source_ignore"] = ("comptes lignes_source, lignes_ecartees, lignes_importees de import.json absents, "
                                             "non entiers ou contradictoires avec le profil : bilan du fichier lu conservé")
    # P1-H : seule une origine mesurée documentée donne « mesure » ; « valide » seul reste d'origine inconnue.
    return [{"mesure": "mesure", "estime": "estime"}.get(q["qualite"], "inconnue") for q in lu["qualites"]], provenance


# Réserves de qualité par contrôle (revue d'Astra de 69800f2, P1-W) : chaque contrôle qui lit le profil porte la qualité
# des valeurs qu'il utilise ; une pointe mesurée ne valide pas les autres quarts. Constats de scan_flex.qualite_jeu.
RESERVES_CONTROLES = {
    "CTRL-MARGE": ("QUALITE_POINTE_NON_MESUREE", "QUALITE_VALEURS_NON_MESUREES"),  # la pointe, et les quarts > GTV
    "CTRL-CAPACITE-DORMANTE": ("QUALITE_POINTE_NON_MESUREE",),
    "CTRL-DEPASSEMENT": ("QUALITE_VALEURS_NON_MESUREES",),
    "CTRL-TRANSPORTRECHT": ("QUALITE_VALEURS_NON_MESUREES",),  # quand il évalue les quarts hors plage
}


def fiche_qualite(fiche: dict[str, Any]) -> dict[str, Any]:
    """Champs de la fiche imbriquée que lit la page qualité, à plat, contrôlés comme par le scan (EAN en texte)."""
    import scan_flex
    plate = {c: e["valeur"] for c in ("ean", "confirmation_grandeur", "unite_recoupee")
             if (e := fiche.get("valeurs", {}).get(c) or {}).get("valeur") not in (None, "")}
    scan_flex.fiche_controlee(plate)
    return plate


def preparer_qualite(fiche: dict[str, Any], dossier: dict[str, Any], resultats: list[dict[str, Any]], export: Path,
                     brut: list[float], horodatages: list[str], periode: list[int]) -> dict[str, Any]:
    """Page qualité et réserves des contrôles, même source pour la commande du diagnostic et le dossier client (revue
    d'Astra de 69800f2, P1-X). ``periode`` : indices des quarts comparés à la facture. Annote les résultats qui lisent
    le profil (reserves_qualite) d'après les valeurs qu'ils utilisent (P1-W)."""
    import scan_flex
    import coherence_mesures
    unite = next(r for r in resultats if r["id"] == "COH-UNITE")
    fiable = coherence_mesures.puissance_fiable(resultats)
    qualites, provenance = qualite_import(export, len(brut))
    # Recoupements avec la facture (FB1, section Q6) : chiffres du diagnostic, sur sa période, en heure d'Amsterdam.
    provenance["recoupements"] = [{"id": r["id"], "statut": r["statut"], "valeurs": r.get("valeurs") or {}}
                                  for r in resultats if r["id"] in ("COH-UNITE", "COH-ENERGIE")]
    if periode:
        zone = ZoneInfo("Europe/Amsterdam")
        provenance["periode_comparee"] = [
            (datetime.fromisoformat(horodatages[periode[0]]) - timedelta(minutes=15)).astimezone(zone).isoformat(),
            datetime.fromisoformat(horodatages[periode[-1]]).astimezone(zone).isoformat()]
    provenance["meetbedrijf"] = (fiche.get("valeurs", {}).get("meetbedrijf") or {}).get("valeur")
    # Conventions de lecture de l'export (critère 1 de Fable : quel fuseau, quel marqueur).
    if "import" not in provenance:
        configuration = configuration_import(fiche)
        provenance["format"] = "csv_declare" if configuration else "csv_canonique"
        if configuration:
            provenance["conventions"] = {c: configuration.get(c) for c in ("fuseau", "horodatage_marque")}
    # En kW selon l'unité recoupée avec la facture, sinon selon l'unité déclarée (la page le dit) ; sans unité
    # exploitable, pas de page plutôt qu'une page fausse.
    kw = (coherence_mesures.profil_comparable(brut, dossier["unite_profil"], unite) if fiable
          else coherence_mesures.en_kw(brut, dossier.get("unite_profil")))
    fins = [datetime.fromisoformat(h) for h in horodatages]
    plate = {**fiche_qualite(fiche), **({"unite_recoupee_controle": "coh_unite"} if fiable else {})}
    jeu = None if kw is None else scan_flex.qualite_jeu(
        kw, fins, plate, qualites, {k: v for k, v in provenance.items() if k not in ("details_import", "avertissements_import")},
        provenance.get("details_import"), provenance.get("avertissements_import"))
    from messages_fiabilite import CODES_POINTE
    # Les deux codes de pointe (quart d'heure ou intervalle natif) valent la même réserve.
    constats = {("QUALITE_POINTE_NON_MESUREE" if c["code"] in CODES_POINTE else c["code"]): c
                for c in jeu["qualite_donnees"]["constats"]} if jeu else {}
    for r in resultats:
        r.pop("reserves_qualite", None)
        evalue = r["statut"] != "bloque" and (r["id"] != "CTRL-TRANSPORTRECHT" or "quarts_evalues" in (r.get("valeurs") or {}))
        reserves = [constats[c] for c in RESERVES_CONTROLES.get(r["id"], ()) if evalue and c in constats]
        if reserves:
            r["reserves_qualite"] = reserves
    return {"jeu": jeu, "qualites": qualites, "provenance": provenance, "kw": kw, "fins": fins, "fiche": plate}


def ecrire(fiche: dict[str, Any], dossier: dict[str, Any], resultats: list[dict[str, Any]],
           dossier_sortie: Path, qualite: dict[str, Any] | None = None) -> Path:
    """``qualite`` : jeu de la page « Qualité des données » (preparer_qualite), qui ouvre alors les rapports HTML et
    texte ; les résultats portent déjà leurs réserves (reserves_qualite)."""
    rapport = rapport_controles.composer(dossier, resultats)
    dossier_sortie.mkdir(parents=True, exist_ok=True)
    cible = dossier_sortie / "rapport.html"
    cible.write_text(rapport_controles.en_html(rapport, qualite), encoding="utf-8")
    (dossier_sortie / "rapport.txt").write_text(rapport_controles.en_texte(rapport, qualite), encoding="utf-8")
    # Version néerlandaise, celle qu'on remet au client ou à l'adviseur.
    import rapport_nl
    (dossier_sortie / "rapport-nl.html").write_text(
        rapport_nl.en_html(rapport, fiche.get("client"), qualite), encoding="utf-8")
    return cible


def produire(fiche: dict[str, Any], dossier_sortie: Path) -> Path:
    """Commande du diagnostic seul : même page qualité et mêmes réserves que le dossier client (P1-X d'Astra), le
    profil entier servant aussi de période comparée, comme dans ses contrôles."""
    dossier, resultats = controler(fiche)
    brut, horodatages = dossier["profil_brut"], dossier["profil_horodatages"]
    prepare = preparer_qualite(fiche, dossier, resultats, Path(fiche["export_profil"]), brut, horodatages,
                               list(range(len(brut))))
    return ecrire(fiche, dossier, resultats, dossier_sortie, qualite=prepare["jeu"])


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "modele":
        print(json.dumps(modele(sys.argv[2] if len(sys.argv) > 2 else None),
                         ensure_ascii=False, indent=2))
    elif len(sys.argv) == 4 and sys.argv[1] == "rapport":
        fiche = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        print(produire(fiche, Path(sys.argv[3])))
    elif len(sys.argv) == 3 and sys.argv[1] == "apercu":
        import serveur
        texte = Path(sys.argv[2]).read_text(encoding="utf-8-sig")
        import csv
        import io
        try:
            dialecte = csv.Sniffer().sniff(texte[:8192], delimiters=",;\t")
            lignes = list(csv.reader(io.StringIO(texte), dialecte))[:4]
        except csv.Error:
            lignes = [ligne.splitlines() for ligne in [texte[:2000]]]
        print(json.dumps(lignes, ensure_ascii=False, indent=2))
    else:
        print(__doc__)
        sys.exit(2)
