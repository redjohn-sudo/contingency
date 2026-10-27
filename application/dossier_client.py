"""Dossier client : une fiche, un export, le diagnostic ET le scan Flex-e dans un même dossier.

Usage : python application/dossier_client.py fiche.json export_profil dossier_sortie/ [--pdf]

La fiche unique est celle du diagnostic (diagnostic.py modele) : chaque valeur porte le document dont
elle vient, {"valeurs": {champ: {"valeur", "source_document"}}}. Les champs propres au scan (ean,
categorie_tarifaire, prix_scan_eur...) s'y ajoutent sous « valeurs », avec leur source eux aussi.

Relecture du 27/09 (module manquant n°1) : donner au scan la fiche du diagnostic faisait perdre le GTV
en silence. Ici, fiche_plate convertit la fiche pour le scan et REFUSE, en nommant le champ, toute
valeur que le scan ne saurait pas lire, au lieu de la perdre. Le GTV repris est la référence de
reference_gtv (ATO et facture égales, ou divergence confirmée), jamais l'ATO seul.

L'export est lu UNE fois. Le diagnostic vérifie période, unité et énergie sur les quarts de la période
facturée (COH-PERIODE exige la période exacte) ; sa marge, ses dépassements et le scan lisent tout
l'export, converti en kW avec le facteur que COH-UNITE a confirmé contre la facture : une seule pointe,
une seule marge sous le GTV (audit Opus n°4). Unité non confirmée : aucun scan chiffré, l'index le dit.

Sortie : rapport.html, rapport.txt, rapport-nl.html (diagnostic), scan.json, rapport-flex.html,
rapport-flex-nl.html (scan, monétisation comprise), index.json et index.md (NL puis FR) : fichiers
produits, valeurs reprises avec leur source, champs manquants. Dans un répertoire réutilisé, ces fichiers
(PDF compris) sont d'abord effacés : rien d'une production précédente ne reste à côté du nouvel index.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import coherence_mesures  # noqa: E402
import controles  # noqa: E402
import diagnostic  # noqa: E402
import reference_gtv  # noqa: E402
import scan_flex  # noqa: E402

# Champs propres au scan, à ajouter sous « valeurs » : champ -> (où le relever, signalé s'il manque).
CHAMPS_SCAN = {
    "secteur": ("entreprise ou visite : secteur d'activité", True),
    "ean": ("ATO : code EAN du raccordement (18 chiffres)", True),
    "sbi": ("extrait KvK : code SBI", True),
    "categorie_tarifaire": ("facture : catégorie tarifaire (LS, TRAFO_MS_LS, MS, MS_TRANSPORT chez Enexis, "
                            "TRAFO_HS_TS_MS) ; sinon estimée par le scan (hypothèse)", True),
    "transport_autres": ("ATO : autres droits de transport du site", False),
    "changements_prevus": ("entreprise : changements prévus (machines, bornes, panneaux)", True),
    "autres_energies": ("entreprise : autres énergies (gaz, chaleur)", False),
    "heures_activite_an": ("entreprise : heures d'activité par an", True),
    "horaires_semaine": ("entreprise : horaires de la semaine", True),
    "processus": ("visite du site : processus qui consomment", True),
    "production_propre": ("visite du site : production propre (panneaux, cogénération)", True),
    # Revue d'Astra de 143a896 (P2-F) : identité de série donnée par le refus du scan, avec sa source.
    "confirmation_grandeur": ("confirmation : la colonne est une puissance moyenne par quart (identité donnée par le scan)",
                              False),
    "congestierapport": ("gestionnaire : congestierapport de la zone", False),
    "besoin_flexibilite_zone": ("gestionnaire : besoin de flexibilité annoncé dans la zone", False),
    "note_congestion": ("note libre sur la congestion locale", False),
    "plafond_cible_kw": ("entreprise : plafond visé ; sinon choisi par le scan (hypothèse)", False),
    "preference_entreprise": ("entreprise : option de flexibilité préférée", True),
    "annee_profil": ("année à garder si l'export en couvre plusieurs", False),
    "croissance_prevue": ("entreprise : charge ajoutée prévue {kw, debut, fin, jours}", False),
    "hypotheses": ("hypothèses du scan modifiées, avec leur source", False),
    "tirages_confiance": ("nombre d'années tirées pour le niveau de confiance", False),
    "batterie_garantie": ("fiche de garantie du fabricant de la batterie", False),
    "prix_scan_eur": ("devis du scan, hors TVA (aide Flex-e)", True),
    "cout_etude_eur": ("devis de l'étude de faisabilité, hors TVA (aide Flex-e)", True),
    "aide_batterie_eur": ("entreprise : aide reçue sur la batterie, 0 si aucune (assiette de l'EIA)", True),
    "source_profil": ("origine de l'export ; sinon tirée du nom de l'export et du meetbedrijf", False),
    "licence_profil": ("conditions d'usage de l'export", False),
    "exemple": ("vrai seulement pour un site d'exemple", False),
    "traductions": ("textes néerlandais {nl: {nom, secteur, ...}}", False),
}
# Champs du diagnostic recopiés tels quels dans la fiche du scan. Le droit de transport en fait partie : le scan
# refuse un droit non ferme en le nommant au lieu de l'ignorer (audit Opus n°5).
DIRECTS = ("capacite_aansluiting_kva", "gestionnaire", "statut_zone_afname", "statut_zone_teruglevering",
           "date_carte", "annee_liberation_annoncee", "type_transportrecht", "blocs_transport", "gtv_hors_bloc_kw")
# Champs lus par les contrôles sans figurer dans CHAMPS_FICHE (dates de dépôt, bruit, parc PV...).
# Audit Astra n°7 : conditions de champ que champ_communal.py lit dans le dossier (liste de sa documentation), en plus
# des besoins statiques du registre ; le diagnostic transmet tous les champs de la fiche aux contrôles.
CHAMPS_COMMUNAUX = {"soumis_a_permis", "capacite_kwh", "conforme_plan_temporaire", "regime_lieu", "energyhub_designe",
                    "lijnopstelling_windturbines", "perceel_attenant_380kv", "zone_nommee", "grootschalig", "zone",
                    "couplee_parc_pv"}
CHAMPS_CONTROLES = {c for e in controles.REGISTRE.values() for c in e["besoins"]} | {
    "chimie_batterie", "date_mise_en_service", "direction", "mois_facture"} | CHAMPS_COMMUNAUX
CONNUS = set(diagnostic.CHAMPS_FICHE) | set(CHAMPS_SCAN) | CHAMPS_CONTROLES
CLES_FICHE = {"client", "export_profil", "import_profil", "valeurs", "avertissement"}
# Textes du gabarit : une source identique n'a pas été renseignée, seulement héritée de modele().
GABARITS = ({doc for doc, _ in diagnostic.CHAMPS_FICHE.values()} | {doc for doc, _ in CHAMPS_SCAN.values()}
            | {t for libelles in diagnostic.LIBELLES_FACTURE.values() for t in libelles.values()}
            | {diagnostic.modele()["valeurs"]["meetbedrijf"]["source_document"]})


def _positif(valeur: Any, champ: str) -> None:
    if not scan_flex.nombre_fini(valeur) or valeur <= 0:
        raise ValueError(f"Fiche : {champ} doit être un nombre fini > 0 (kW), reçu {str(valeur)[:40]!r}.")


def _reference_gtv(valeurs: dict[str, tuple[Any, str]]) -> tuple[Any, str] | str:
    """(valeur, source) du GTV à donner au scan, ou le motif pour lequel il n'y en a pas."""
    ato, declare = valeurs.get("gtv_kw"), valeurs.get("gtv_declare_kw")
    for champ, entree in (("gtv_kw", ato), ("gtv_declare_kw", declare)):
        if entree is not None:
            _positif(entree[0], champ)
    if ato is None or declare is None:
        return "ATO (gtv_kw) et facture (gtv_declare_kw) sont nécessaires pour fixer le GTV actuel"
    if ato[0] == declare[0]:
        return ato[0], f"{ato[1]} ; même valeur sur : {declare[1]}"
    confirmation = valeurs.get(reference_gtv.CHAMP_CONFIRMATION, (None,))[0]
    ref = reference_gtv.etablir({"gtv_kw": ato[0], "gtv_declare_kw": declare[0],
                                 reference_gtv.CHAMP_CONFIRMATION: confirmation})
    if ref and ref["statut"] == "confirme":
        return declare[0], f"{declare[1]} ; confirmé : {ref['confirmation']['source_document']}"
    return (f"référence GTV bloquée : ATO {ato[0]} kW, facture {declare[0]} kW, "
            "confirmation_gtv_declare absente ou invalide ; aucun GTV donné au scan")


def fiche_plate(fiche: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], list[dict[str, str]]]:
    """Fiche du diagnostic -> (fiche plate du scan, source de chaque clé, champs manquants).

    ValueError qui nomme le champ pour toute valeur que le scan ne saurait pas lire."""
    if not isinstance(fiche, dict) or not isinstance(fiche.get("valeurs"), dict):
        raise ValueError("Fiche : format du diagnostic attendu, avec une clé « valeurs ».")
    for cle in fiche:
        if cle not in CLES_FICHE:
            raise ValueError(f"Fiche : clé « {cle} » inconnue au premier niveau (attendu : {', '.join(sorted(CLES_FICHE))}).")
    valeurs: dict[str, tuple[Any, str]] = {}
    for champ, entree in fiche["valeurs"].items():
        if champ not in CONNUS:
            raise ValueError(f"Fiche : champ « {champ} » inconnu, ni le diagnostic ni le scan ne le lisent.")
        if not isinstance(entree, dict) or "valeur" not in entree:
            raise ValueError(f"Fiche : {champ} doit être un objet {{valeur, source_document}}.")
        if entree["valeur"] in (None, "", []):
            continue
        source = str(entree.get("source_document") or "").strip()
        if not source:
            raise ValueError(f"Fiche : {champ} n'indique pas de quel document il vient.")
        valeurs[champ] = (entree["valeur"], source)

    plate: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    manquants: list[dict[str, str]] = []
    if str(fiche.get("client") or "").strip():
        plate["nom"], provenance["nom"] = fiche["client"], "fiche, champ client"
    for champ in (*DIRECTS, *CHAMPS_SCAN):
        if champ in valeurs:
            plate[champ], provenance[champ] = valeurs[champ]
    if "commune" in valeurs:
        plate["adresse"], provenance["adresse"] = valeurs["commune"]
    if "gestionnaire" in plate:
        gestionnaire = str(plate["gestionnaire"]).strip().lower()
        if gestionnaire not in scan_flex.TARIFS_2026:
            raise ValueError(f"Fiche : gestionnaire « {plate['gestionnaire']} » inconnu du scan (liander, stedin, enexis) ; "
                             "le laisser vide donne la grille Liander marquée hypothèse.")
        plate["gestionnaire"] = gestionnaire
    if "categorie_tarifaire" in plate:
        grille = scan_flex.TARIFS_2026[plate.get("gestionnaire", "liander")]
        if plate["categorie_tarifaire"] not in grille or plate["categorie_tarifaire"] == "bornes":
            raise ValueError(f"Fiche : categorie_tarifaire « {plate['categorie_tarifaire']} » inconnue de la grille "
                             f"{plate.get('gestionnaire', 'liander')} ({', '.join(c for c in grille if c != 'bornes')}).")
    gtv = _reference_gtv(valeurs)
    if isinstance(gtv, tuple):
        plate["gtv_kw"], provenance["gtv_kw"] = gtv
    else:
        manquants.append({"champ": "gtv_kw", "ou_le_trouver": gtv, "pour": "scan"})
    if "source_profil" not in plate:
        meetbedrijf = valeurs.get("meetbedrijf", ("meetbedrijf non indiqué",))[0]
        plate["source_profil"] = f"export du client {Path(str(fiche.get('export_profil', ''))).name}, {meetbedrijf}"
        provenance["source_profil"] = "tiré de export_profil et meetbedrijf"
    scan_flex.fiche_controlee(plate)

    for champ, (doc, obligatoire) in diagnostic.CHAMPS_FICHE.items():
        if (champ not in valeurs and not obligatoire and not champ.startswith("batterie_")
                and champ != reference_gtv.CHAMP_CONFIRMATION):  # déjà dit par gtv_kw s'il faut la confirmer
            manquants.append({"champ": champ, "ou_le_trouver": doc, "pour": "diagnostic"})
    for champ, (doc, signaler) in CHAMPS_SCAN.items():
        if signaler and champ not in valeurs:
            manquants.append({"champ": champ, "ou_le_trouver": doc, "pour": "scan"})
    return plate, provenance, manquants


def _periode(fiche: dict[str, Any], horodatages: list[str]) -> list[int]:
    """Indices des quarts de la période facturée (fins de quart dans ]début, fin + 1 jour])."""
    v = fiche["valeurs"]
    try:
        debut, fin = (date.fromisoformat(str(v[c]["valeur"])) for c in ("periode_facture_debut", "periode_facture_fin"))
    except (KeyError, TypeError, ValueError):
        return []
    zone = ZoneInfo("Europe/Amsterdam")
    bas = datetime.combine(debut, time.min, zone).astimezone(timezone.utc)
    haut = datetime.combine(fin + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    return [i for i, h in enumerate(horodatages) if bas < datetime.fromisoformat(h).astimezone(timezone.utc) <= haut]


FICHIERS = {  # fichier -> (rôle en néerlandais, rôle en français)
    "rapport-nl.html": ("diagnose, versie voor de klant", "diagnostic, version remise au client"),
    "rapport.html": ("diagnose, Franse versie", "diagnostic en français"),
    "rapport.txt": ("diagnose, platte tekst", "diagnostic en texte brut"),
    "rapport-flex-nl.html": ("flexibiliteitsscan Flex-e, met monetisatie", "scan Flex-e en néerlandais, monétisation comprise"),
    "rapport-flex.html": ("flexibiliteitsscan, Franse versie", "scan Flex-e en français"),
    "rapport-flex-nl.pdf": ("flexibiliteitsscan, pdf", "scan Flex-e en néerlandais, PDF"),
    "rapport-flex.pdf": ("flexibiliteitsscan, Franse pdf", "scan Flex-e en français, PDF"),
    "scan.json": ("scanresultaten (machineleesbaar)", "résultats du scan (JSON)"),
    "index.json": ("deze index (machineleesbaar)", "cet index (JSON)"),
}


def produire(fiche: dict[str, Any], export: Path, sortie: Path, pdf: bool = False) -> dict[str, Any]:
    fiche = {**fiche, "export_profil": str(export.resolve())}
    plate, provenance, manquants = fiche_plate(fiche)  # refus AVANT toute écriture
    brut, horodatages = diagnostic.lire_profil(export, diagnostic.configuration_import(fiche))
    periode = _periode(fiche, horodatages)
    # Audit Opus n°23 : sans aucun quart dans la période facturée, le diagnostic reçoit tout l'export (COH-PERIODE
    # le bloque), mais l'index dit 0 quart dans la période, pas la taille de l'export.
    indices = periode or list(range(len(brut)))
    dossier, resultats = diagnostic.controler(fiche, ([brut[i] for i in indices], [horodatages[i] for i in indices]),
                                              export=(brut, horodatages))
    # Audit Astra n°1 : un répertoire réutilisé ne garde aucun fichier d'une production précédente (scan refusé
    # cette fois, PDF non redemandé) ; l'index ne peut donc annoncer que ce que cette production a écrit.
    for nom in (*FICHIERS, "index.md"):
        (sortie / nom).unlink(missing_ok=True)

    unite = next(r for r in resultats if r["id"] == "COH-UNITE")
    fiable = coherence_mesures.puissance_fiable(resultats)
    index: dict[str, Any] = {
        "client": fiche.get("client"),
        "profil": {"fichier": export.name, "quarts": len(brut), "debut_fin": [horodatages[0], horodatages[-1]],
                   "quarts_periode_facturee": len(periode), "unite_declaree": dossier.get("unite_profil")},
        "diagnostic": {"controles": [{"id": r["id"], "statut": r["statut"], "constat": r.get("constat")} for r in resultats],
                       "puissance_fiable": fiable,
                       "pointe_periode_facturee_kw": (unite.get("valeurs") or {}).get("pointe_comparee")},
        "scan": {"produit": False},
    }
    prepare = diagnostic.preparer_qualite(fiche, dossier, resultats, export, brut, horodatages, periode)
    jeu, qualites, provenance_profil = prepare["jeu"], prepare["qualites"], prepare["provenance"]
    kw, fins, fiche_qualite = prepare["kw"], prepare["fins"], {**plate, **prepare["fiche"]}
    provenance_scan = {k: v for k, v in provenance_profil.items() if k not in ("details_import", "avertissements_import")}
    index["profil"]["sha256"] = provenance_profil["sha256"]
    index["diagnostic"]["controles"] = [{"id": r["id"], "statut": r["statut"], "constat": r.get("constat"),
                                         **({"reserves_qualite": r["reserves_qualite"]} if r.get("reserves_qualite") else {})}
                                        for r in resultats]
    diagnostic.ecrire(fiche, dossier, resultats, sortie, qualite=jeu)
    if fiable:
        try:
            resultat = scan_flex.scanner(kw, fins, fiche_qualite, qualites=qualites, provenance=provenance_scan,
                                         details_qualite=provenance_profil.get("details_import"),
                                         avertissements=provenance_profil.get("avertissements_import"))
        except ValueError as erreur:
            index["scan"]["motif"] = f"scan refusé : {erreur}"
            index["scan"]["constats"] = getattr(erreur, "constats", [])
        else:
            import rapport_flex
            (sortie / "scan.json").write_text(json.dumps(scan_flex.allege(resultat), ensure_ascii=False, indent=1), encoding="utf-8")
            for nom, langue in (("rapport-flex", "fr"), ("rapport-flex-nl", "nl")):
                (sortie / f"{nom}.html").write_text(rapport_flex.rendre(resultat, langue), encoding="utf-8")
                if pdf:
                    import rapport_pdf
                    rapport_pdf.html_vers_pdf(sortie / f"{nom}.html", sortie / f"{nom}.pdf")
            index["scan"] = {"produit": True, "pointe_kw": resultat["statistiques"]["pointe_kw"]["valeur"],
                             "pointe_periode_facturee_kw": max(kw[i] for i in periode) if periode else None,
                             "gtv_kw": resultat["raccordement"]["gtv_kw"],
                             "marge_gtv": resultat["marge_gtv"]}
    else:
        index["scan"]["motif"] = ("unité du profil non confirmée contre la facture (COH-UNITE) : "
                                  "aucun scan chiffré sur une puissance peut-être fausse d'un facteur 4")

    # Valeurs reprises : tout ce que la fiche porte, avec sa source et qui la lit.
    inverse = {"adresse": "commune"}
    lu_scan = {inverse.get(c, c) for c in plate} - {"gtv_kw"}
    # Audit Opus n°12 : le GTV du scan vient de l'ATO, de la facture confirmée, ou des deux s'ils concordent ; seul le
    # champ qui porte cette valeur est marqué lu par le scan.
    lu_scan |= {c for c in ("gtv_kw", "gtv_declare_kw")
                if "gtv_kw" in plate and (fiche["valeurs"].get(c) or {}).get("valeur") == plate["gtv_kw"]}
    reprises = [{"champ": c, "valeur": e["valeur"], "source": e.get("source_document"),
                 "source_gabarit": str(e.get("source_document", "")).strip() in GABARITS,
                 "lu_par": [q for q, oui in (("diagnostic", c in diagnostic.CHAMPS_FICHE or c in CHAMPS_CONTROLES),
                                             ("scan", c in lu_scan and index["scan"]["produit"])) if oui]}
                for c, e in fiche["valeurs"].items() if e.get("valeur") not in (None, "", [])]
    reprises += [{"champ": f"scan.{c}", "valeur": plate[c], "source": provenance[c], "source_gabarit": False,
                  "lu_par": ["scan"] if index["scan"]["produit"] else []}
                 for c in ("nom", "gtv_kw", "source_profil") if c in plate]
    index["valeurs"] = reprises
    vus = {m["champ"] for m in manquants}
    for r in resultats:  # ce que les contrôles ont réclamé, sans doublon
        for m in r.get("manque") or []:
            if m.get("champ") not in vus:
                vus.add(m.get("champ"))
                manquants.append({"champ": m.get("champ"), "ou_le_trouver": m.get("ou_le_trouver"), "pour": r["id"]})
    index["manquants"] = manquants
    index["fichiers"] = [{"fichier": f, "role_nl": nl, "role_fr": fr} for f, (nl, fr) in FICHIERS.items()
                         if f == "index.json" or (sortie / f).is_file()]
    (sortie / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (sortie / "index.md").write_text(en_markdown(index), encoding="utf-8")
    return index


TEXTES = {
    "nl": {"titre": "Klantdossier", "fichiers": "Gemaakte bestanden", "valeurs": "Overgenomen waarden en hun bron",
           "manquants": "Ontbrekende gegevens", "scan_non": "Geen flexibiliteitsscan", "gabarit": "bron niet ingevuld (tekst van het sjabloon)",
           "profil": "Profiel", "quarts": "kwartieren", "facture": "in de factuurperiode", "rien": "niets",
           "entetes_v": "| Veld | Waarde | Bron | Gelezen door |", "entetes_m": "| Veld | Waar te vinden | Voor |"},
    "fr": {"titre": "Dossier client", "fichiers": "Fichiers produits", "valeurs": "Valeurs reprises et leur source",
           "manquants": "Champs manquants", "scan_non": "Pas de scan Flex-e", "gabarit": "source non renseignée (texte du gabarit)",
           "profil": "Profil", "quarts": "quarts d'heure", "facture": "dans la période facturée", "rien": "aucun",
           "entetes_v": "| Champ | Valeur | Source | Lu par |", "entetes_m": "| Champ | Où le trouver | Pour |"},
}


def _cellule(valeur: Any) -> str:
    texte = valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False)
    return texte.replace("|", "\\|").replace("\n", " ")


def en_markdown(index: dict[str, Any]) -> str:
    """Index lisible, néerlandais puis français. Les sources et le « où le trouver » restent tels que saisis."""
    lignes = []
    for langue, t in TEXTES.items():
        p = index["profil"]
        # Audit Astra n°9 : nom du client et du profil protégés comme les cellules, aucune section injectée.
        lignes += [f"# {t['titre']} : {_cellule(index.get('client') or '')}", "",
                   f"{t['profil']} : {_cellule(p['fichier'])}, {p['quarts']} {t['quarts']}, "
                   f"{p['quarts_periode_facturee']} {t['facture']}.", "", f"## {t['fichiers']}", ""]
        lignes += [f"- `{f['fichier']}` : {f['role_' + langue]}" for f in index["fichiers"]]
        if not index["scan"]["produit"]:
            lignes += ["", f"**{t['scan_non']}** : {index['scan'].get('motif')}"]
        lignes += ["", f"## {t['valeurs']}", "", t["entetes_v"], "|---|---|---|---|"]
        for v in index["valeurs"]:
            source = _cellule(v["source"]) + (f" ({t['gabarit']})" if v["source_gabarit"] else "")
            lignes.append(f"| {v['champ']} | {_cellule(v['valeur'])} | {source} | {', '.join(v['lu_par']) or t['rien']} |")
        lignes += ["", f"## {t['manquants']}", "", t["entetes_m"], "|---|---|---|"]
        lignes += [f"| {m['champ']} | {_cellule(m['ou_le_trouver'])} | {m['pour']} |" for m in index["manquants"]]
        lignes.append("")
    return "\n".join(lignes)


def main(argv: list[str]) -> int:
    pdf = "--pdf" in argv
    argv = [a for a in argv if a != "--pdf"]
    if len(argv) != 4:
        print(__doc__)
        return 2
    fiche = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    try:
        produire(fiche, Path(argv[2]), Path(argv[3]), pdf)
    except ValueError as erreur:
        raise SystemExit(f"Dossier client NON produit : {erreur}") from erreur
    print(f"dossier écrit dans {argv[3]} (index.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
