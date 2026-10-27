"""Rapport des contrôles, le document que l'ingénieur montre à son client.

Structure arrêtée le 24/09/2026 après débat sur le bus inter-agents.

Le plan suit l'ordre des vrais dossiers néerlandais, relevé par hermes dans des
zienswijzennota, raadsvoorstel et ruimtelijke onderbouwing réels. Raison : le
rapport de l'ingénieur devient une pièce du dossier de permis sans réécriture,
parce que le gestionnaire, la commune et la veiligheidsregio le liront ensuite
dans cet ordre.

1. Synthèse : ce qui est établi, ce qui alerte, ce qui n'est pas évaluable.
2. Wat is aangevraagd : ce qui est demandé, en une phrase chiffrée, puis les
   données du dossier avec leur origine.
3. Toetsingskader : à quelles règles on a testé, chacune avec sa date.
4. Beoordeling, par aspect : raccordement, sécurité externe, bruit, insertion.
   Chaque aspect porte ses contrôles.
5. Aan te leveren stukken : les pièces à fournir, classées par ce qu'elles
   débloquent. Le vocabulaire est celui qu'un ingénieur néerlandais emploie déjà
   vis-à-vis de son client ; une liste de pièces à fournir ne fait pas passer le
   produit pour incapable, elle dit au client ce qui manque à SON dossier.

Deux exigences ajoutées au débat :

- Le rapport porte l'empreinte du catalogue et sa date de génération. Sans cela
  un rapport n'est pas reproductible six mois plus tard, quand la règle aura
  changé. C'est aussi ce qui rend la revalidation possible.
- Un blocage nomme non seulement la donnée manquante mais OÙ aller la chercher.
  « dernier vermogen déclaré, à lire sur une facture de transport du
  gestionnaire » vaut mieux que « dernier vermogen déclaré ».

Le rapport ne dit jamais « je ne sais pas ». Il dit ce qui manque pour savoir.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

import catalogue
import controles
import couverture

RACINE = Path(__file__).resolve().parent.parent
CATALOGUE_JSON = RACINE / "docs" / "contraintes" / "catalogue.json"

LIBELLES = {
    "constat": "Établi",
    "a_confirmer": "À confirmer",
    "alerte": "Point d'attention",
    "bloque": "Non évaluable",
}

# Les quatre aspects que la commune, le gestionnaire et la veiligheidsregio
# instruisent séparément. Un contrôle non classé tombe dans « overig ».
ASPECTS = [
    # En premier : si les mesures ne sont pas fiables, rien de ce qui suit ne l'est.
    ("meetgegevens", "Fiabilité des mesures",
     ("COH-PERIODE", "COH-UNITE", "COH-ENERGIE", "COH-PERTES")),
    ("netaansluiting", "Raccordement et capacité",
     ("CTRL-MARGE", "CTRL-GTV-MAX", "CTRL-GTV-DECLARE", "CTRL-DEPASSEMENT",
      "CTRL-CAPACITE-DORMANTE", "CTRL-DELAI-OFFRE", "CTRL-REGIME-DEPOT")),
    ("externe veiligheid", "Sécurité externe et permis",
     ("CTRL-SEUIL-PERMIS", "CTRL-USAGE-COMMUNE")),
    ("geluid", "Bruit",
     ("CTRL-BRUIT-COMMUNE",)),
    ("ruimtelijke inpassing", "Insertion spatiale",
     ("CTRL-HAUTEUR-COMMUNE", "CTRL-PLAFOND-PARC-PV")),
    ("batterij", "Cohérence des caractéristiques batterie",
     ("CTRL-BAT-SOC", "CTRL-BAT-PUISSANCE", "CTRL-BAT-ENGAGEMENTS")),
]


def _par_aspect(controles_detail: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Range les contrôles dans l'ordre d'instruction néerlandais."""
    restants = {c["id"]: c for c in controles_detail}
    groupes = []
    for code, titre, identifiants in ASPECTS:
        contenu = [restants.pop(i) for i in identifiants if i in restants]
        if contenu:
            groupes.append({"code": code, "titre": titre, "controles": contenu})
    if restants:
        groupes.append({"code": "overig", "titre": "Autres",
                        "controles": list(restants.values())})
    return groupes


def _version_catalogue() -> dict[str, str]:
    """Version exacte du catalogue, pour qu'un rapport soit reproductible."""
    empreinte = catalogue.empreinte()
    version = {"empreinte": empreinte, "genere_le": "inconnu",
               "nombre_entrees": str(len(catalogue.charger()))}
    if CATALOGUE_JSON.exists():
        donnees = json.loads(CATALOGUE_JSON.read_text(encoding="utf-8"))
        if donnees.get("empreinte_source") == empreinte:
            version["genere_le"] = donnees.get("genere_le", "inconnu")
    return version


def _sources(identifiants: list[str], entrees: dict[str, Any]) -> list[dict[str, str]]:
    sources = []
    for identifiant in identifiants:
        entree = entrees.get(identifiant)
        if not entree:
            continue
        sources.append({
            "id": identifiant,
            "nom": entree.get("nom", ""),
            "juridiction": entree.get("juridiction", "?"),
            "confiance": entree.get("confiance", "?"),
            "source": entree.get("source", "source non renseignée dans le catalogue"),
        })
    return sources


def _resume_profil(dossier: dict[str, Any], resultats: list[dict[str, Any]]) -> dict[str, Any]:
    """Pointe comparable et pointe brute, avec le facteur retenu contre la facture."""
    import coherence_mesures
    # Le profil que lisent les contrôles de puissance : tout l'export s'il est fourni (audit Opus n°4).
    brut = (dossier["profil_export"][0] if "profil_export" in dossier
            else dossier.get("profil_brut") if "profil_brut" in dossier else dossier.get("profil_kw"))
    facteur = 1.
    pointe_brute = None
    try:
        kw = coherence_mesures.en_kw(brut, dossier.get("unite_profil") if "profil_brut" in dossier else "kw")
        pointe_brute = round(max(kw), 1) if kw else None
        unite = next((r for r in resultats if r["id"] == "COH-UNITE" and r["statut"] == "constat"), None)
        if unite is not None and "profil_brut" in dossier:
            kw = coherence_mesures.profil_comparable(brut, dossier.get("unite_profil"), unite)
            facteur = unite["valeurs"]["facteur_correction_pertes"]
    except (ValueError, OverflowError):
        kw = None
    return {"mesures": len(brut) if isinstance(brut, (list, tuple)) else 0, "pas": "15 minutes",
            "pointe_kw": round(max(kw), 1) if kw else None,
            "pointe_brute_kw": pointe_brute, "facteur_correction_pertes": facteur,
            "unite_declaree": dossier.get("unite_profil")}


def _precision_pertes(profil: dict[str, Any]) -> str:
    facteur = profil.get("facteur_correction_pertes", 1.)
    if facteur == 1.:
        return ""
    return (f"Pointe brute {profil['pointe_brute_kw']:.1f} kW ; correction de pertes "
            f"retenue contre la facture : +{(facteur - 1) * 100:.1f} %. "
            "Cette correction est appliquée aux contrôles de puissance et d'énergie. "
            "Le défaut de 1,4 % concerne les raccordements MS avec mesure BT ; "
            "le taux convenu reste à vérifier.")


def _precision_gtv(reference: dict[str, Any] | None) -> str:
    if not reference:
        return ""
    if reference['statut'] == 'bloque':
        return "La puissance actuelle reste à confirmer : la dernière déclaration est invalide ou diffère de l'ATO sans confirmation documentée. Aucune marge ni économie n'est calculée contre l'ancien ATO."
    preuve = reference['confirmation']
    return (f"Référence des contrôles : dernière déclaration {reference['reference_kw']:.1f} kW ; "
            f"valeur figurant dans l'ATO fourni {reference['gtv_ato_kw']:.1f} kW. "
            f"Source : {preuve['source_document']}, document du {preuve['date_document']}. "
            f"Confirmation renseignée par {preuve['verifie_par']} le {preuve['date_verification']}. "
            "L'application n'authentifie ni la pièce ni son lecteur. Une hausse ultérieure "
            "demande un nouvel accord, soumis à la capacité disponible.")


def _donnee_serialisable(valeur: Any) -> Any:
    """Conserve une entrée non finie comme texte brut, jamais comme nombre JSON."""
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return str(valeur)
    if isinstance(valeur, dict):
        return {cle: _donnee_serialisable(v) for cle, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_donnee_serialisable(v) for v in valeur]
    return valeur


def composer(dossier: dict[str, Any], resultats: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Assemble le rapport en données, avant toute mise en forme."""
    import reference_gtv
    resultats = resultats if resultats is not None else controles.executer_tous(dossier)
    entrees = catalogue.charger()
    compte = controles.compter(resultats)
    # Revue d'Astra de 69800f2 (P1-V) : un constat qui repose sur des valeurs non mesurées est « à confirmer », dans son
    # titre comme dans le décompte ; une alerte reste une alerte, un contrôle non évaluable le reste.
    compte["a_confirmer"] = sum(1 for r in resultats if r["statut"] == "constat" and r.get("reserves_qualite"))
    compte["constat"] -= compte["a_confirmer"]
    deblocage = controles.plan_de_deblocage(resultats)

    detail = []
    for resultat in resultats:
        affiche = "a_confirmer" if resultat["statut"] == "constat" and resultat.get("reserves_qualite") else resultat["statut"]
        detail.append({
            **resultat,
            "statut_affiche": affiche,
            "libelle_statut": LIBELLES.get(affiche, affiche),
            "sources": _sources(resultat.get("contraintes", []), entrees),
        })

    demande = []
    from controles_contrat import nombre_non_negatif
    for champ, unite, libelle in (("puissance_kw", "kW", "puissance"),
                                  ("capacite_kwh", "kWh", "capacité")):
        valeur = dossier.get(champ)
        if valeur in (None, "", [], ()):
            continue
        demande.append(f"{float(valeur):.0f} {unite}" if nombre_non_negatif(valeur)
                       else f"{libelle} invalide, à vérifier")
    if dossier.get("commune"):
        demande.append(f"à {dossier['commune']}")
    if dossier.get("qualification_usage"):
        demande.append(f"usage déclaré « {dossier['qualification_usage']} »")

    regles_testees = sorted({identifiant
                             for resultat in resultats
                             for identifiant in resultat.get("contraintes", [])})

    return {
        "version_catalogue": _version_catalogue(),
        "aangevraagd": ", ".join(demande) if demande
                       else ("aucun projet : diagnostic du contrat et des mesures existants"
                             if dossier.get("profil_brut") or dossier.get("profil_kw")
                             else "non précisé dans le dossier fourni"),
        "toetsingskader": _sources(regles_testees, entrees),
        "aspects": _par_aspect(detail),
        "compte": compte,
        "evaluables": compte["constat"] + compte["a_confirmer"] + compte["alerte"],
        "total": len(resultats),
        "donnees_fournies": {
            cle: (f"{valeur}  (source : {dossier['provenance'][cle]})"
                  if isinstance(dossier.get("provenance"), dict) and dossier["provenance"].get(cle)
                  else _donnee_serialisable(valeur))
            for cle, valeur in sorted(dossier.items())
            if cle not in ("profil_kw", "profil_brut", "profil_export", "provenance", "profil_horodatages",
                           "confirmation_gtv_declare")
            and valeur not in (None, "", [])
        },
        "profil": _resume_profil(dossier, resultats),
        "reference_gtv": reference_gtv.etablir(dossier),
        "controles": detail,
        "a_fournir": deblocage,
        "couverture": couverture.etablir(),
    }


def _ligne_source(source: dict[str, str]) -> str:
    return (f"{source['id']} ({source['juridiction']}, confiance {source['confiance']}) "
            f"{source['nom']}. Source : {source['source']}")


def en_texte(rapport: dict[str, Any], qualite: dict[str, Any] | None = None) -> str:
    """Rendu texte, lisible en terminal et collable dans un courriel. ``qualite`` : page qualité en tête."""
    import rapport_flex
    version = rapport["version_catalogue"]
    lignes = [
        "RAPPORT DE CONTRÔLES CONTINGENCY",
        "=" * 64,
        *([rapport_flex.section_qualite_texte(qualite, "fr"), "", "=" * 64] if qualite else []),
        "",
        "1. SYNTHÈSE",
        f"   {rapport['evaluables']} contrôle(s) évalués sur {rapport['total']}.",
        f"   Établis : {rapport['compte']['constat']}. "
        + (f"À confirmer : {rapport['compte']['a_confirmer']}. " if rapport["compte"].get("a_confirmer") else "")
        + f"Points d'attention : {rapport['compte']['alerte']}. "
        f"Non évaluables : {rapport['compte']['bloque']}.",
        "",
        "   PORTÉE : " + couverture.phrase(rapport["couverture"]),
    ]
    unite = next((c for c in rapport["controles"] if c["id"] == "COH-UNITE"), None)
    reserves = sum(1 for c in rapport["controles"] if c.get("reserves_qualite"))
    if reserves:
        lignes += ["", f"   ⚠ À CONFIRMER : {reserves} contrôle(s) lisent des valeurs dont la qualité n'est pas "
                   "documentée comme une mesure ; leurs résultats restent indicatifs (voir chaque contrôle)."]
    if precision := _precision_gtv(rapport.get("reference_gtv")):
        lignes += ["", "   " + precision]
    if unite is not None and unite["statut"] != "constat":
        lignes += ["", "   ⚠ MESURES NON VÉRIFIÉES : " + unite["constat"],
                   "     Aucune conclusion de puissance n'est donnée tant que ce point n'est pas réglé."]
    attention = [c for groupe in rapport["aspects"] for c in groupe["controles"]
                 if c["statut"] == "alerte"]
    if attention:
        lignes.append("")
        lignes.append("   Points d'attention :")
        for controle in attention:
            lignes.append(f"     - {controle['titre']} : {controle['constat']}")
    if rapport["a_fournir"]:
        premier = rapport["a_fournir"][0]
        lignes.append("")
        lignes.append(f"   Pièce la plus utile à fournir : {premier['champ']}, "
                      f"elle ouvre {len(premier['debloque'])} contrôle(s).")

    lignes += ["", "2. WAT IS AANGEVRAAGD — ce qui est demandé", "",
               f"   {rapport['aangevraagd']}", ""]
    if rapport["profil"]["mesures"]:
        lignes.append(f"   profil : {rapport['profil']['mesures']} mesures au pas de "
                      f"{rapport['profil']['pas']}, pointe {rapport['profil']['pointe_kw'] if rapport['profil']['pointe_kw'] is not None else 'non calculable'} kW")
        if precision := _precision_pertes(rapport["profil"]):
            lignes.append("   " + precision)
    for cle, valeur in rapport["donnees_fournies"].items():
        lignes.append(f"   {cle} : {valeur}")

    lignes += ["", "3. TOETSINGSKADER — les règles auxquelles le dossier a été testé", ""]
    for source in rapport["toetsingskader"]:
        lignes.append(f"   {_ligne_source(source)}")

    lignes += ["", "4. BEOORDELING — évaluation par aspect", ""]
    for groupe in rapport["aspects"]:
        lignes.append(f"   {groupe['titre'].upper()} ({groupe['code']})")
        for controle in groupe["controles"]:
            lignes.append(f"      [{controle['libelle_statut']}] {controle['id']} — {controle['titre']}")
            lignes.append(f"         {controle['constat']}")
            champ = controle.get("champ_d_application")
            if champ:
                lignes.append(f"         Champ d'application : {champ['statut']}. {champ['raison']}")
                if champ.get("reference"):
                    lignes.append(f"         Source datée : {champ['reference']}, en vigueur depuis "
                                  f"{champ.get('en_vigueur_le', 'date inconnue')}.")
                citation_champ = champ.get("citation_variante") or champ.get("citation")
                if citation_champ and citation_champ != controle.get("citation_communale"):
                    lignes.append(f"         Citation de champ : {citation_champ}")
            if controle.get("consequence_contractuelle"):
                lignes.append(f"         Conséquence : {controle['consequence_contractuelle']}")
            if controle.get("citation_communale"):
                lignes.append(f"         Texte : {controle['citation_communale']}")
            if controle.get("derogation"):
                lignes.append(f"         Dérogation : {controle['derogation']}")
            if controle.get("portee"):
                lignes.append(f"         Portée : {controle['portee']}")
            if controle.get("tension_juridique"):
                lignes.append(f"         Point de droit à trancher : {controle['tension_juridique']}")
            if controle.get("source_communale"):
                lignes.append(f"         Texte communal : {controle['source_communale']}")
            for cle, etiquette in (("source_methode", "Méthode"), ("source_donnees", "Référence déclarée")):
                if controle.get(cle):
                    lignes.append(f"         {etiquette} : {controle[cle]}")
            for manque in controle.get("manque", []):
                lignes.append(f"         À fournir : {manque['champ']} — {manque['ou_le_trouver']}")
            for texte in rapport_flex.reserves_controle(controle, "fr"):
                lignes.append(f"         À confirmer : {texte}")
        lignes.append("")

    lignes += ["5. AAN TE LEVEREN STUKKEN — pièces à fournir", ""]
    if not rapport["a_fournir"]:
        lignes.append("   Aucune : tous les contrôles disponibles ont pu être évalués.")
    for fiche in rapport["a_fournir"]:
        lignes.append(f"   {fiche['champ']} — ouvre {len(fiche['debloque'])} contrôle(s) : "
                      f"{', '.join(fiche['debloque'])}")
        lignes.append(f"      Où le trouver : {fiche['ou_le_trouver']}")

    lignes += [
        "",
        "-" * 64,
        f"Catalogue des contraintes : {version['nombre_entrees']} entrées, "
        f"empreinte {version['empreinte'][:16]}, généré le {version['genere_le']}.",
        "Ce rapport est reproductible sur cette version du catalogue. Une règle "
        "modifiée depuis change le résultat : relancer la revalidation.",
        "Aucune conclusion n'est produite sur une donnée absente.",
    ]
    return "\n".join(lignes)


def en_html(rapport: dict[str, Any], qualite: dict[str, Any] | None = None) -> str:
    """Rendu HTML sobre, sans dépendance externe, même plan que le texte. ``qualite`` : page « Qualité des données »
    en tête (FB1), avec la réserve sur la pointe reportée sur les contrôles qui en dépendent."""
    import rapport_flex

    def e(valeur: Any) -> str:
        return html.escape(str(valeur))
    reserves = sum(1 for c in rapport["controles"] if c.get("reserves_qualite"))

    version = rapport["version_catalogue"]
    couleurs = {"constat": "#1a7f37", "a_confirmer": "#9a6700", "alerte": "#9a6700", "bloque": "#57606a"}
    m = [
        "<!doctype html><html lang='fr'><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Rapport de contrôles Contingency</title>",
        "<style>body{font-family:Figtree,system-ui,sans-serif;max-width:52rem;margin:2rem auto;overflow-wrap:anywhere;"
        "padding:0 1rem;line-height:1.55;color:#1f2328}h1{font-size:clamp(1.25rem,4vw,1.5rem)}h2{font-size:1.1rem;"
        "margin-top:2.2rem;border-bottom:1px solid #d0d7de;padding-bottom:.3rem}"
        "h3{font-size:.95rem;margin-top:1.4rem;color:#57606a;text-transform:uppercase;"
        "letter-spacing:.04em}.c{border-left:3px solid #d0d7de;padding:.5rem 0 .5rem .8rem;"
        "margin:.8rem 0}.s{font-weight:600}.src{color:#57606a;font-size:.85rem}"
        "footer{margin-top:2.5rem;color:#57606a;font-size:.85rem;border-top:1px solid #d0d7de;"
        f"padding-top:1rem}}{rapport_flex.STYLE_QUALITE if qualite else ''}</style>",
        "<h1>Rapport de contrôles</h1>",
        rapport_flex._section_qualite(qualite, "fr") if qualite else "",
        "<h2>1. Synthèse</h2>",
        f"<p>{rapport['evaluables']} contrôle(s) évalués sur {rapport['total']}. "
        f"Établis {rapport['compte']['constat']}, "
        + (f"à confirmer {rapport['compte']['a_confirmer']}, " if rapport["compte"].get("a_confirmer") else "")
        + f"points d'attention {rapport['compte']['alerte']}, non évaluables {rapport['compte']['bloque']}.</p>",
        f"<p><strong>Portée.</strong> {e(couverture.phrase(rapport['couverture']))}</p>",
    ]
    if reserves:
        m.append(f"<p style='color:#9a6700'><strong>À confirmer.</strong> {reserves} contrôle(s) lisent des valeurs dont "
                 "la qualité n'est pas documentée comme une mesure : leurs résultats restent indicatifs (voir chaque "
                 "contrôle et la page qualité).</p>")
    unite = next((c for c in rapport["controles"] if c["id"] == "COH-UNITE"), None)
    if unite is not None and unite["statut"] != "constat":
        m.append(f"<p style='color:#9a6700'><strong>Mesures non vérifiées.</strong> "
                 f"{e(unite['constat'])} Aucune conclusion de puissance n'est donnée "
                 f"tant que ce point n'est pas réglé.</p>")
    attention = [c for groupe in rapport["aspects"] for c in groupe["controles"]
                 if c["statut"] == "alerte"]
    if attention:
        m.append("<ul>" + "".join(
            f"<li><strong>{e(c['titre'])}</strong> : {e(c['constat'])}</li>" for c in attention
        ) + "</ul>")

    m.append("<h2>2. Wat is aangevraagd</h2>")
    if precision := _precision_gtv(rapport.get("reference_gtv")):
        m.append(f"<p>{e(precision)}</p>")
    m.append(f"<p>{e(rapport['aangevraagd'])}</p><ul>")
    if rapport["profil"]["mesures"]:
        m.append(f"<li>profil : {rapport['profil']['mesures']} mesures au pas de "
                 f"{e(rapport['profil']['pas'])}, pointe {e(rapport['profil']['pointe_kw'] if rapport['profil']['pointe_kw'] is not None else 'non calculable')} kW</li>")
        if precision := _precision_pertes(rapport["profil"]):
            m.append(f"<li>{e(precision)}</li>")
    for cle, valeur in rapport["donnees_fournies"].items():
        m.append(f"<li>{e(cle)} : {e(valeur)}</li>")
    m.append("</ul>")

    m.append("<h2>3. Toetsingskader</h2><ul>")
    for source in rapport["toetsingskader"]:
        m.append(f"<li class='src'>{e(_ligne_source(source))}</li>")
    m.append("</ul>")

    m.append("<h2>4. Beoordeling</h2>")
    for groupe in rapport["aspects"]:
        m.append(f"<h3>{e(groupe['titre'])} ({e(groupe['code'])})</h3>")
        for controle in groupe["controles"]:
            couleur = couleurs.get(controle["statut_affiche"], "#57606a")
            m.append(f"<div class='c' style='border-left-color:{couleur}'>")
            m.append(f"<p class='s' style='color:{couleur}'>{e(controle['libelle_statut'])} "
                     f"— {e(controle['id'])} {e(controle['titre'])}</p>")
            m.append(f"<p>{e(controle['constat'])}</p>")
            champ = controle.get("champ_d_application")
            if champ:
                m.append(f"<p>Champ d'application : {e(champ['statut'])}. {e(champ['raison'])}</p>")
                if champ.get("reference"):
                    m.append(f"<p class='src'>Source datée : {e(champ['reference'])}, en vigueur depuis "
                             f"{e(champ.get('en_vigueur_le', 'date inconnue'))}.</p>")
                citation_champ = champ.get("citation_variante") or champ.get("citation")
                if citation_champ and citation_champ != controle.get("citation_communale"):
                    m.append(f"<p>Citation de champ : {e(citation_champ)}</p>")
            for cle, etiquette in (("consequence_contractuelle", "Conséquence"),
                                   ("citation_communale", "Texte"),
                                   ("derogation", "Dérogation"),
                                   ("portee", "Portée"),
                                   ("tension_juridique", "Point de droit à trancher")):
                if controle.get(cle):
                    m.append(f"<p>{etiquette} : {e(controle[cle])}</p>")
            if controle.get("source_communale"):
                m.append(f"<p class='src'>Texte communal : {e(controle['source_communale'])}</p>")
            for cle, etiquette in (("source_methode", "Méthode"), ("source_donnees", "Référence déclarée")):
                if controle.get(cle):
                    m.append(f"<p class='src'>{etiquette} : {e(controle[cle])}</p>")
            for manque in controle.get("manque", []):
                m.append(f"<p>À fournir : <strong>{e(manque['champ'])}</strong> — "
                         f"{e(manque['ou_le_trouver'])}</p>")
            for texte in rapport_flex.reserves_controle(controle, "fr"):
                m.append(f"<p style='color:#9a6700'>À confirmer : {e(texte)}</p>")
            m.append("</div>")

    m.append("<h2>5. Aan te leveren stukken</h2>")
    if not rapport["a_fournir"]:
        m.append("<p>Aucune : tous les contrôles disponibles ont pu être évalués.</p>")
    else:
        m.append("<ol>")
        for fiche in rapport["a_fournir"]:
            m.append(f"<li><strong>{e(fiche['champ'])}</strong> ouvre "
                     f"{len(fiche['debloque'])} contrôle(s) ({e(', '.join(fiche['debloque']))})<br>"
                     f"<span class='src'>Où le trouver : {e(fiche['ou_le_trouver'])}</span></li>")
        m.append("</ol>")

    m.append(
        f"<footer><p>Catalogue des contraintes : {e(version['nombre_entrees'])} entrées, "
        f"empreinte {e(version['empreinte'][:16])}, généré le {e(version['genere_le'])}.</p>"
        "<p>Ce rapport est reproductible sur cette version du catalogue. Une règle modifiée "
        "depuis change le résultat : relancer la revalidation.</p>"
        "<p>Aucune conclusion n'est produite sur une donnée absente.</p></footer>")
    return "\n".join(m)
