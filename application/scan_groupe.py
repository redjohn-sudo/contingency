"""Scan de groupe : ce que plusieurs sites voisins gagnent à partager leur capacité.

Contexte : à partir du 01/01/2027, les gestionnaires néerlandais devront proposer un contrat de transport de
groupe (groepstransportovereenkomst) aux grands consommateurs qui le demandent (communiqué ACM du 19/12/2025).
Les pointes de sites voisins ne tombent pas au même quart d'heure : la pointe commune est plus basse que la
somme des pointes. L'écart est la capacité qu'un contrat de groupe peut rendre disponible sans nouveau câble.
Mesuré sur 3 890 sites réels (docs/preuves/sorties/foisonnement_vea.txt) : 13 % en médiane pour 5 sites.

Entrée : plusieurs profils (CSV interne ou réponse Kenter), sur les mêmes quarts d'heure, et une fiche de
groupe facultative (nom de chaque site, GTV de chaque site). Sortie : scan_groupe.json, rapport-groupe.html
(FR) et rapport-groupe-nl.html (NL), plus le scan de flexibilité complet du profil commun (rapport-flex*.html).

Usage : python application/scan_groupe.py fiche_groupe.json dossier_sortie/ profil1.csv profil2.csv ... [--pdf]
Fiche de groupe : {"nom": ..., "gestionnaire": ..., "sites": [{"nom": ..., "gtv_kw": ...}, ...]}, sites dans
l'ordre des profils.
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import rapport_flex  # noqa: E402
import scan_flex  # noqa: E402


def grouper(profils: list[tuple[str, list[float], list[datetime]]], gtv: list[float | None]) -> dict[str, Any]:
    """Profils sur les mêmes fins d'intervalle (vérifié), somme quart d'heure par quart d'heure."""
    if len(profils) < 2:
        raise ValueError("Scan de groupe : au moins deux sites.")
    reference = profils[0][2]
    for nom, kw, fins in profils[1:]:
        if len(fins) != len(reference) or any(a != b for a, b in zip(fins, reference)):
            raise ValueError(f"Scan de groupe : les quarts d'heure de « {nom} » ne sont pas ceux du premier site.")
    somme = [sum(valeurs) for valeurs in zip(*(kw for _, kw, _ in profils))]
    i_pointe = max(range(len(somme)), key=somme.__getitem__)
    sites = []
    for (nom, kw, _), g in zip(profils, gtv):
        pointe = max(kw)
        sites.append({"nom": nom, "pointe_kw": round(pointe, 1), "a_la_pointe_commune_kw": round(kw[i_pointe], 1),
                      "part_de_sa_pointe": round(kw[i_pointe] / pointe, 3) if pointe else 0.0, "gtv_kw": g})
    somme_pointes = sum(max(kw) for _, kw, _ in profils)  # pointes non arrondies (relecture de 05 h 50, défaut 10)
    pointe_commune = max(somme)
    gtv_connus = [g for g in gtv if g]
    return {
        "sites": sites,
        "somme_pointes_kw": round(somme_pointes, 1),
        "pointe_commune_kw": round(pointe_commune, 1),
        "instant_pointe_commune": (reference[i_pointe] - scan_flex.QUART).isoformat(timespec="minutes"),
        "foisonnement": round(1 - pointe_commune / somme_pointes, 4) if somme_pointes else 0.0,
        "capacite_liberee_kw": round(somme_pointes - pointe_commune, 1),
        "somme_gtv_kw": round(sum(gtv_connus), 1) if len(gtv_connus) == len(gtv) else None,
        "marge_gtv_groupe_kw": (round(sum(gtv_connus) - pointe_commune, 1) if len(gtv_connus) == len(gtv) else None),
        "profil_commun_kw": somme,
    }


T = {
    "fr": {"titre": "Scan de groupe", "sous_titre": "Ce que des sites voisins gagnent à partager leur capacité (groepstransportovereenkomst)",
           "site": "Site", "pointe": "Pointe du site", "a_la_pointe": "Charge au moment de la pointe commune", "part": "Part de sa pointe",
           "gtv": "GTV", "synthese": ("Pris séparément, les {n} sites ont des pointes qui totalisent {somme} kW. Ensemble, leur pointe commune "
                                      "est de {commune} kW, le {instant} : {liberes} kW de moins ({pct}), parce que les pointes ne tombent pas "
                                      "au même moment."),
           "gtv_txt": " Avec {somme_gtv} kW de GTV cumulés, un contrat de groupe laisserait {marge} kW de marge au-dessus de la pointe commune.",
           "gtv_depasse": " La pointe commune dépasse de {marge} kW les {somme_gtv} kW de GTV cumulés : un contrat de groupe ne suffirait pas.",
           "synthese_simultane": ("Pris séparément, les {n} sites ont des pointes qui totalisent {somme} kW. Leurs pointes tombent au même "
                                  "quart d'heure, le {instant} : la pointe commune est la même, le groupe ne libère rien."),
           "contexte": ("À partir du 01/01/2027, les gestionnaires devront proposer un contrat de transport de groupe aux grands consommateurs "
                        "qui le demandent (communiqué ACM du 19/12/2025). Les conditions (partage des coûts, limites, réseau commun) "
                        "restent à fixer avec le gestionnaire."),
           "flex": "Le scan de flexibilité complet du profil commun est dans rapport-flex.html.",
           "limites": ("Des sites d'une même zone ne sont pas forcément raccordés au même poste ; seul le gestionnaire peut dire si un "
                       "contrat de groupe est possible entre eux."),
           "exemple": "Exemple sur données publiques réelles, pas un dossier client."},
    "nl": {"titre": "Groepsscan", "sous_titre": "Wat naburige locaties winnen door capaciteit te delen (groepstransportovereenkomst)",
           "site": "Locatie", "pointe": "Piek van de locatie", "a_la_pointe": "Belasting op het moment van de gezamenlijke piek",
           "part": "Deel van de eigen piek", "gtv": "GTV",
           "synthese": ("Los van elkaar hebben de {n} locaties pieken die samen {somme} kW bedragen. Samen is hun gezamenlijke piek {commune} kW, "
                        "op {instant}: {liberes} kW minder ({pct}), omdat de pieken niet tegelijk vallen."),
           "gtv_txt": " Met samen {somme_gtv} kW GTV laat een groepscontract {marge} kW ruimte boven de gezamenlijke piek.",
           "gtv_depasse": " De gezamenlijke piek ligt {marge} kW boven de {somme_gtv} kW GTV samen: een groepscontract zou niet volstaan.",
           "synthese_simultane": ("Los van elkaar hebben de {n} locaties pieken die samen {somme} kW bedragen. Hun pieken vallen in hetzelfde "
                                  "kwartier, op {instant}: de gezamenlijke piek is even hoog, de groep maakt geen ruimte vrij."),
           "contexte": ("Vanaf 1 januari 2027 moeten netbeheerders grootverbruikers die erom vragen een groepstransportovereenkomst aanbieden "
                        "(ACM, 19/12/2025). De voorwaarden (kostenverdeling, grenzen, gezamenlijk net) moeten nog met de netbeheerder worden vastgelegd."),
           "flex": "De volledige flexibiliteitsscan van het gezamenlijke profiel staat in rapport-flex-nl.html.",
           "limites": ("Locaties in hetzelfde gebied zijn niet per se op hetzelfde station aangesloten; alleen de netbeheerder kan zeggen of "
                       "een groepscontract tussen hen mogelijk is."),
           "exemple": "Voorbeeld op echte openbare data, geen klantdossier."},
}


def rendre(g: dict[str, Any], fiche: dict[str, Any], langue: str) -> str:
    t, e, n = T[langue], html.escape, rapport_flex.nombre
    lignes = "".join(f"<tr><td>{e(s['nom'])}</td><td>{n(s['pointe_kw'], langue)} kW</td><td>{n(s['a_la_pointe_commune_kw'], langue)} kW</td>"
                     f"<td>{n(s['part_de_sa_pointe'] * 100, langue, 0)} %</td><td>{n(s['gtv_kw'], langue) + ' kW' if s['gtv_kw'] else '–'}</td></tr>"
                     for s in g["sites"])
    # Date au format du rapport de flexibilité : « 13/07/2016 à 06:45 » en FR, « 13-07-2016 om 06:45 » en NL.
    instant = f"{rapport_flex._date_locale(g['instant_pointe_commune'], langue)} {'à' if langue == 'fr' else 'om'} {g['instant_pointe_commune'][11:16]}"
    cle = "synthese" if g["capacite_liberee_kw"] > 0.05 else "synthese_simultane"
    texte = t[cle].format(n=len(g["sites"]), somme=n(g["somme_pointes_kw"], langue), commune=n(g["pointe_commune_kw"], langue),
                          instant=instant, liberes=n(g["capacite_liberee_kw"], langue),
                          pct=f"{n(g['foisonnement'] * 100, langue, 1)} %")
    if g["marge_gtv_groupe_kw"] is not None:
        marge = g["marge_gtv_groupe_kw"]
        texte += t["gtv_txt" if marge >= 0 else "gtv_depasse"].format(somme_gtv=n(g["somme_gtv_kw"], langue), marge=n(abs(marge), langue))
    nom = ((fiche.get("traductions") or {}).get(langue) or {}).get("nom") or fiche.get("nom") or ""
    exemple = f"<p class='exemple'>{e(t['exemple'])}</p>" if fiche.get("exemple") else ""
    return (f"<!doctype html><html lang='{langue}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(t['titre'])}</title><style>body{{font-family:system-ui,sans-serif;max-width:58rem;margin:2rem auto;padding:0 1rem;"
            f"line-height:1.5;color:#1f2328}}table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{text-align:left;padding:.35rem .5rem;"
            f"border-bottom:1px solid #eaeef2}}.cle{{border-left:3px solid #1f2328;padding:.4rem .8rem;background:#f6f8fa}}.src{{color:#57606a;font-size:.85rem}}"
            f".exemple{{border:1px solid #d0d7de;background:#f6f8fa;padding:.6rem .9rem}}.defile{{overflow-x:auto}}</style></head><body>"
            f"<h1>{e(t['titre'])}{' : ' if langue == 'fr' else ': '}{e(nom)}</h1><p class='src'>{e(t['sous_titre'])}</p>{exemple}"
            f"<p class='cle'>{e(texte)}</p>"
            f"<div class='defile'><table><tr><th>{t['site']}</th><th>{t['pointe']}</th><th>{t['a_la_pointe']}</th><th>{t['part']}</th>"
            f"<th>{t['gtv']}</th></tr>{lignes}</table></div><p>{e(t['contexte'])}</p><p>{e(t['flex'])}</p>"
            f"<p class='src'>{e(t['limites'])}</p></body></html>")


def main(argv: list[str]) -> int:
    pdf = "--pdf" in argv
    argv = [a for a in argv if a != "--pdf"]
    if len(argv) < 5:
        print(__doc__)
        return 2
    fiche = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    sortie = Path(argv[2])
    chemins = [Path(a) for a in argv[3:]]
    infos = fiche.get("sites") or [{} for _ in chemins]
    if len(infos) != len(chemins):
        raise SystemExit("La fiche de groupe doit décrire autant de sites que de profils, dans le même ordre.")
    for info in infos:
        g = info.get("gtv_kw")
        if g is not None and (not scan_flex.nombre_fini(g) or g <= 0):
            raise ValueError(f"Fiche de groupe : gtv_kw de « {info.get('nom', '?')} » doit être un nombre fini positif, reçu {str(g)[:40]!r}.")
    profils = []
    for chemin, info in zip(chemins, infos):
        # Même lecture que le scan d'un site : un export de plusieurs années donne l'année de la fiche, ou la plus récente.
        kw, fins, _ = scan_flex.lire_profil_annee(chemin, fiche.get("annee_profil"))
        # Même heure légale d'Amsterdam pour tous les sites, quel que soit le fuseau écrit dans chaque fichier.
        profils.append((info.get("nom") or chemin.stem, kw,
                        [f.astimezone(scan_flex.AMSTERDAM).replace(tzinfo=None) if f.tzinfo else f for f in fins]))
    g = grouper(profils, [info.get("gtv_kw") for info in infos])
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "scan_groupe.json").write_text(json.dumps({k: v for k, v in g.items() if k != "profil_commun_kw"},
                                                        ensure_ascii=False, indent=1), encoding="utf-8")
    (sortie / "rapport-groupe.html").write_text(rendre(g, fiche, "fr"), encoding="utf-8")
    (sortie / "rapport-groupe-nl.html").write_text(rendre(g, fiche, "nl"), encoding="utf-8")
    # Le groupe se scanne comme un seul site : GTV du groupe = somme des GTV s'ils sont tous connus.
    fiche_flex = {k: v for k, v in fiche.items() if k not in ("sites",)}
    if g["somme_gtv_kw"]:
        fiche_flex["gtv_kw"] = g["somme_gtv_kw"]
    # Audits O1, O6, O13 : le scanner sait qu'il s'agit de plusieurs raccordements, avant tout calcul par raccordement.
    fiche_flex["contrat_groupe"] = True
    resultat = scan_flex.scanner(g["profil_commun_kw"], profils[0][2], fiche_flex)
    # Plusieurs raccordements : la capacité « libérée » suppose un contrat de groupe, que le rapport doit dire.
    resultat["contrat_groupe"] = True
    (sortie / "rapport-flex.html").write_text(rapport_flex.rendre(resultat, "fr"), encoding="utf-8")
    (sortie / "rapport-flex-nl.html").write_text(rapport_flex.rendre(resultat, "nl"), encoding="utf-8")
    if pdf:
        import rapport_pdf
        for nom in ("rapport-groupe", "rapport-groupe-nl", "rapport-flex", "rapport-flex-nl"):
            rapport_pdf.html_vers_pdf(sortie / f"{nom}.html", sortie / f"{nom}.pdf")
    print(f"groupe de {len(profils)} sites : pointe commune {g['pointe_commune_kw']} kW pour {g['somme_pointes_kw']} kW "
          f"de pointes cumulées ({g['foisonnement']:.1%}) ; écrit dans {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
