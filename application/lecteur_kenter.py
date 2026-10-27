"""Lecture de la réponse « meetdata » de l'API Kenter (format officiel, sans deviner).

Source : Kenter, « Handleiding Meetdata API » NL v1.5 (mars 2025), publique :
https://kenter.nu/wp-content/uploads/2025/03/Handleiding-Meetdata-API-NL-v1-5-27-2.pdf
- réponse : liste de canaux {channelId, Measurements: [{origin, status, timestamp, value}]} (p. 16) ;
- timestamp : Unix en UTC, FIN de la période, sans heure d'été (p. 32) ;
- 16180 : levering tbv allocatie, kWh par quart d'heure, avec trafocorrectiefactor. C'est le canal
  sur lequel le netbeheerder contrôle le GTV, « kwartierlevering x 4 = belasting » (p. 25) ;
- 18160 : piekvermogen levering tbv facturatie, kW, une valeur par mois, posée sur le dernier
  jour du mois (p. 16 et 20) : le kWmax de la facture ;
- origin/status : Measured/Valid, Invalid, ManualAccepted, Estimated, Calculated, Unknown (p. 17).

Le canal 10180 (compteur brut, parfois au pas de 5 minutes) n'est pas celui du netbeheerder :
il n'est pas accepté ici, pour ne jamais comparer au contrat une pointe qui n'est pas la sienne.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CANAL_KWARTIER = "16180"
CANAL_PIEK_FACTUUR = "18160"
PAS_SECONDES = 900
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
SOURCE = "Kenter Handleiding Meetdata API v1.5 (mars 2025)"


def _canaux(reponse) -> dict[str, list[dict]]:
    try:
        donnees = json.loads(reponse) if isinstance(reponse, (str, bytes)) else reponse
    except (ValueError, UnicodeError) as erreur:
        raise ValueError("Réponse Kenter JSON illisible.") from erreur
    if not isinstance(donnees, list):
        raise ValueError("Réponse Kenter attendue : une liste de canaux (channelId, Measurements).")
    canaux = {}
    for canal in donnees:
        if not isinstance(canal, dict):
            raise ValueError("Chaque canal Kenter doit être un objet.")
        identifiant = canal.get("channelId")
        if isinstance(identifiant, bool) or not isinstance(identifiant, (str, int)):
            raise ValueError("Identifiant de canal Kenter invalide.")
        ident = str(identifiant).strip()
        mesures = canal.get("Measurements")
        if not ident or not isinstance(mesures, list):
            raise ValueError("Canal Kenter sans channelId ni Measurements.")
        canaux.setdefault(ident, []).extend(mesures)
    return canaux


def _mesure(mesure, canal):
    """Valide les types publiés, sans tronquer un timestamp ni inventer un statut."""
    if not isinstance(mesure, dict):
        raise ValueError(f"Mesure Kenter {canal} attendue sous forme d'objet.")
    horodatage = mesure.get("timestamp")
    if isinstance(horodatage, bool) or not isinstance(horodatage, int):
        raise ValueError("Horodatage Kenter attendu en secondes Unix entières, sans fraction.")
    try:
        fin = datetime.fromtimestamp(horodatage, timezone.utc).astimezone(AMSTERDAM)
    except (ValueError, OverflowError, OSError) as erreur:
        raise ValueError("Horodatage Kenter hors de la plage de dates prise en charge.") from erreur
    if canal == CANAL_KWARTIER and horodatage % PAS_SECONDES:
        raise ValueError("Horodatage Kenter hors d'un quart d'heure exact.")
    valeur = mesure.get("value")
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        raise ValueError("Valeur Kenter attendue sous forme de nombre JSON.")
    try:
        valeur = float(valeur)
    except (ValueError, OverflowError) as erreur:
        raise ValueError("Valeur Kenter hors limites.") from erreur
    limite = 1e7 / 4 if canal == CANAL_KWARTIER else 1e7
    if not math.isfinite(valeur) or not 0 <= valeur <= limite:
        raise ValueError("Valeur Kenter non finie, négative ou hors limites du diagnostic (10 millions de kW).")
    origine = mesure.get("origin")
    if origine is None:
        origine = "Unknown"
    statut = mesure.get("status")
    if statut == "Invalid":
        raise ValueError("Mesure Kenter au statut Invalid (rejetée par la meetcode) : attendre la "
                         "valeur définitive avant tout diagnostic.")
    if origine == "Measured" and statut in ("Valid", "ManualAccepted"):
        qualite = "mesure"
    elif origine in ("Estimated", "Calculated", "Unknown") and statut is None:
        qualite = {"Estimated": "estime", "Calculated": "calcule", "Unknown": "inconnue"}[origine]
    else:
        raise ValueError("Combinaison origin/status Kenter inconnue ou non publiée dans le manuel.")
    return horodatage, valeur, fin, {"origin": origine, "status": statut, "qualite": qualite}


def lire_kenter(reponses) -> dict:
    """Assemble les réponses d'un seul point de mesure, à garantir par l'appelant.

    16180 : kWh par quart vers kW, fins datées en heure d'Amsterdam. 18160 :
    pointes mensuelles de facturation. Qualité conservée pour les deux canaux.
    Les réponses peuvent se recouvrir : seuls les doublons strictement identiques
    (valeur et qualité) sont réunis et comptés. Toute contradiction est refusée.
    Le tri UTC est signalé ; aucun trou n'est rempli et aucun nombre n'est arrondi.
    """
    if not isinstance(reponses, list) or reponses and isinstance(reponses[0], dict):
        reponses = [reponses]
    quarts = {}
    pics = {}
    qualites_pics = {}
    doublons = {CANAL_KWARTIER: 0, CANAL_PIEK_FACTUUR: 0}
    ordre_recu = []
    for reponse in reponses:
        canaux = _canaux(reponse)
        if CANAL_KWARTIER not in canaux:
            present = ", ".join(sorted(canaux)) or "aucun"
            raise ValueError(f"Canal {CANAL_KWARTIER} (kwartierlevering du netbeheerder) absent ; canaux reçus : "
                             f"{present}. Le canal 10180 ne le remplace pas.")
        for mesure in canaux[CANAL_KWARTIER]:
            horodatage, valeur, fin, qualite = _mesure(mesure, CANAL_KWARTIER)
            nouvelle = (valeur, qualite)
            if horodatage in quarts:
                if quarts[horodatage] != nouvelle:
                    raise ValueError("Valeurs ou qualités contradictoires pour le même quart Kenter.")
                doublons[CANAL_KWARTIER] += 1
                continue
            quarts[horodatage] = nouvelle
            ordre_recu.append(horodatage)
        for mesure in canaux.get(CANAL_PIEK_FACTUUR, []):
            horodatage, valeur, fin, qualite = _mesure(mesure, CANAL_PIEK_FACTUUR)
            mois = fin.strftime("%Y-%m")
            qualite = qualite | {"fin_source": fin.isoformat()}
            if mois in pics:
                if pics[mois] != valeur or qualites_pics[mois] != qualite:
                    raise ValueError("Plusieurs pointes ou qualités contradictoires pour un mois Kenter.")
                doublons[CANAL_PIEK_FACTUUR] += 1
                continue
            pics[mois] = valeur
            qualites_pics[mois] = qualite
    if not quarts:
        raise ValueError(f"Aucune mesure sur le canal {CANAL_KWARTIER}.")
    instants = sorted(quarts)
    if any(b - a != PAS_SECONDES for a, b in zip(instants, instants[1:])):
        raise ValueError("Mesures Kenter non consécutives au pas de 15 minutes : trou ou doublon.")
    lignes = ["fin_intervalle,puissance_kw"]
    qualites = []
    statuts = {}
    for instant in instants:
        fin = datetime.fromtimestamp(instant, timezone.utc).astimezone(AMSTERDAM)
        valeur, qualite = quarts[instant]
        puissance = valeur * 4
        # repr conserve le float lors d'une relecture, contrairement à .6g.
        nombre = str(int(puissance)) if puissance.is_integer() else repr(puissance)
        lignes.append(f"{fin.isoformat()},{nombre}")
        qualites.append(qualite | {"fin_intervalle": fin.isoformat()})
        cle = f"{qualite['origin']}/{qualite['status'] or '-'}"
        statuts[cle] = statuts.get(cle, 0) + 1
    avertissements = []
    for nature, message in (("estime", "Des valeurs sont estimées, pas mesurées."),
                            ("calcule", "Des valeurs ont été recalculées par Kenter, pas mesurées directement."),
                            ("inconnue", "L'origine ou la validation de certaines valeurs n'est pas connue.")):
        if any(q['qualite'] == nature for q in [*qualites, *qualites_pics.values()]):
            avertissements.append(message)
    if ordre_recu != instants:
        avertissements.append("Les mesures ont été remises dans l'ordre chronologique UTC.")
    if any(doublons.values()):
        avertissements.append("Des réponses se recouvrent : les doublons identiques sont réunis et comptés dans la provenance.")
    return {"csv": "\n".join(lignes) + "\n", "unite": "kw", "kwmax_facture_par_mois": pics,
            "statuts": statuts, "qualites": qualites, "kwmax_qualites_par_mois": qualites_pics,
            "avertissements": avertissements,
            "provenance": {"format": "kenter_meetdata", "manuel": "1.5", "facteur_vers_kw": 4,
                           "doublons_identiques": doublons, "tri_utc_effectue": ordre_recu != instants,
                           "nombre_quarts": len(instants), "nombre_reponses": len(reponses),
                           "point_de_mesure": "à garantir par l'appelant : la réponse ne porte pas son identifiant"},
            "source": f"{SOURCE}, canal {CANAL_KWARTIER} (kWh par quart x 4)"}
