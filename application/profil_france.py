"""Lecture d'une courbe de charge pour le module France, à pas de temps détecté.

Le lecteur du serveur (`serveur._lire_profil_detaille`) impose un pas de 15 minutes : les courbes de charge
françaises sont au pas de 10 minutes (HTA et BT > 36 kVA, courbe de mesure Enedis) ou de 30 minutes (Linky).
Ce lecteur accepte le CSV interne `fin_intervalle,puissance_kw` à un pas régulier de 5, 10, 15, 30 ou 60 minutes,
lit les horodatages avec leur décalage, les ramène en heure légale française (Europe/Paris) et tolère les jours
de changement d'heure. Il garde le signe : une valeur négative est une injection (production propre), séparée
du soutirage au lieu d'être refusée.

Résultat de `lire` : dictionnaire
  valeurs      puissances moyennes en kW, signées (soutirage positif, injection négative)
  fins         fins d'intervalle, datetime en heure légale française sans fuseau
  fins_utc     fins d'intervalle en UTC (pour les calculs qui doivent ignorer l'heure d'été)
  debuts       débuts d'intervalle en heure légale, calculés en UTC puis convertis (justes aux changements d'heure,
               contrairement à « fin locale moins le pas » : voir debuts())
  pas_minutes  pas détecté ; pas_h en heures
  fuseau_lu    « offset » si le fichier portait un décalage, « naif » sinon (alors lu comme heure légale française)
  injection    True si au moins une valeur négative
  provenance   ce que le lecteur sait du texte lu, pour la page « Qualité des données » (FB1) : sha256_texte et
               octets_texte du texte fourni (BOM compris), bilan des lignes, format (csv_canonique avec décalages,
               csv_france_heure_locale sinon, avec les conventions déclarées), pas. Les octets reçus (fichier, octets,
               sha256) ne sont connus que de l'appelant qui a lu le fichier : sans lui, la page ne les affirme pas
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
PAS_ADMIS = (5, 10, 15, 30, 60)
COLONNES = {"fin_intervalle", "puissance_kw"}
PUISSANCE_MAX_KW = 1e7


def lire(texte: str, fuseau_naif: str = "Europe/Paris") -> dict[str, Any]:
    """CSV interne `fin_intervalle,puissance_kw`, pas régulier détecté, signe conservé."""
    octets_texte = texte.encode("utf-8")  # empreinte du texte tel que fourni, BOM compris ; les octets du fichier sont à l'appelant
    texte = texte.lstrip("﻿")
    entete = next(csv.reader(io.StringIO(texte)), [])
    if len(entete) != len(set(entete)):
        raise ValueError(f"CSV : colonne répétée ({', '.join(sorted({c for c in entete if entete.count(c) > 1}))}) ; DictReader ne garderait que la dernière.")
    lignes = list(csv.DictReader(io.StringIO(texte)))
    if not lignes or set(lignes[0]) != COLONNES:
        raise ValueError("CSV attendu : fin_intervalle,puissance_kw (puissance moyenne en kW, signée).")
    if len(lignes) < 2:
        raise ValueError("Profil : au moins deux mesures pour détecter le pas.")
    zone_naive = ZoneInfo(fuseau_naif)
    fins_utc, fuseau_lu = [], None
    for numero, ligne in enumerate(lignes, 2):
        brut = (ligne["fin_intervalle"] or "").strip().replace("Z", "+00:00")
        try:
            instant = datetime.fromisoformat(brut)
        except ValueError as erreur:
            raise ValueError(f"Ligne {numero} : horodatage illisible {brut[:40]!r} (ISO 8601 attendu).") from erreur
        lu = "offset" if instant.tzinfo is not None else "naif"
        if fuseau_lu is None:
            fuseau_lu = lu
        elif lu != fuseau_lu:
            raise ValueError(f"Ligne {numero} : horodatages tantôt avec, tantôt sans décalage.")
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=zone_naive)
            # OF8 : au changement d'heure, une heure locale sans décalage existe deux fois (octobre) ou pas du tout (mars).
            if instant.utcoffset() != instant.replace(fold=1).utcoffset() or instant.astimezone(ZoneInfo("UTC")).astimezone(zone_naive).replace(tzinfo=None) != instant.replace(tzinfo=None):
                raise ValueError(f"Ligne {numero} : heure locale {brut} ambiguë ou inexistante au changement d'heure du {instant.date().isoformat()} ({fuseau_naif}). "
                                 "Les horodatages sans décalage ne permettent pas de distinguer les deux occurrences : fournir le décalage UTC sur chaque ligne (+01:00 ou +02:00) ou un export en UTC (Z).")
        fins_utc.append(instant.astimezone(ZoneInfo("UTC")))
    ecarts = [round((b - a).total_seconds()) for a, b in zip(fins_utc, fins_utc[1:])]
    pas_s = max(set(ecarts), key=ecarts.count)
    for i, ecart in enumerate(ecarts):
        if ecart != pas_s:
            avant, apres = lignes[i]["fin_intervalle"].strip(), lignes[i + 1]["fin_intervalle"].strip()
            raise ValueError(f"Ligne {i + 3} : écart de {ecart / 60:g} min avec la ligne précédente ({avant} → {apres}) ; "
                             f"pas régulier de {pas_s / 60:g} min attendu, sans trou ni doublon.")
    if pas_s % 60 or pas_s // 60 not in PAS_ADMIS:
        raise ValueError(f"Pas de {pas_s} s non pris en charge ; pas admis : {', '.join(map(str, PAS_ADMIS))} minutes.")
    valeurs = []
    for numero, ligne in enumerate(lignes, 2):
        brut = (ligne["puissance_kw"] or "").strip().replace(",", ".")
        try:
            v = float(brut)
        except ValueError as erreur:
            raise ValueError(f"Ligne {numero} : puissance illisible {brut[:40]!r}.") from erreur
        if not math.isfinite(v) or abs(v) > PUISSANCE_MAX_KW:
            raise ValueError(f"Ligne {numero} : puissance invalide ({brut[:40]}), attendu un nombre fini de moins de 10 millions de kW.")
        valeurs.append(v)
    pas = timedelta(seconds=pas_s)
    provenance = {"sha256_texte": hashlib.sha256(octets_texte).hexdigest(), "octets_texte": len(octets_texte), "pas_minutes": pas_s // 60,
                  "bilan_lignes": {"recues": len(lignes), "nature": "lignes", "ecartees": {}, "doublons_identiques": 0},
                  "format": "csv_canonique" if fuseau_lu == "offset" else "csv_france_heure_locale"}
    if fuseau_lu == "naif":
        provenance["conventions"] = {"fuseau": fuseau_naif, "horodatage_marque": "fin"}
    return {"valeurs": valeurs, "provenance": provenance,
            "fins": [f.astimezone(PARIS).replace(tzinfo=None) for f in fins_utc],
            "debuts": [(f - pas).astimezone(PARIS).replace(tzinfo=None) for f in fins_utc],
            "fins_utc": [f.replace(tzinfo=None) for f in fins_utc],
            "pas_minutes": pas_s // 60, "pas_h": pas_s / 3600,
            "fuseau_lu": fuseau_lu, "injection": any(v < 0 for v in valeurs)}


def jeu_qualite(profil: dict[str, Any], fiche: dict[str, Any], version: str, zone: str = "Europe/Paris") -> dict[str, Any]:
    """Entrée de la page « Qualité des données » (FB1) pour les scans France et solaire : scan_flex.qualite_jeu au pas
    natif et dans la zone du profil (rien n'est recadré), sur le soutirage seul (l'injection reste distincte), qualité
    absente = inconnue. S'y ajoute la réserve sur les valeurs non mesurées, que chaque résultat reprend."""
    import scan_flex
    kw, _ = separer(profil["valeurs"])
    fins = [f.replace(tzinfo=ZoneInfo("UTC")) for f in profil["fins_utc"]]
    jeu = scan_flex.qualite_jeu(kw, fins, fiche, None, dict(profil.get("provenance") or {}), None, [],
                                pas_minutes=profil["pas_minutes"], zone=zone)
    jeu["version"] = version
    jeu["reserve_valeurs"] = next((c["parametres"] for c in jeu["qualite_donnees"]["constats"]
                                   if c["code"] == "QUALITE_VALEURS_NON_MESUREES"), None)
    return jeu


def separer(valeurs: list[float]) -> tuple[list[float], list[float]]:
    """Soutirage et injection, deux séries positives de même longueur (0 quand l'autre sens est actif)."""
    return [max(v, 0.0) for v in valeurs], [max(-v, 0.0) for v in valeurs]


def debuts(fins: list[datetime], pas_h: float) -> list[datetime]:
    """Fin locale moins le pas : faux d'une heure pour les intervalles qui chevauchent un changement d'heure (le quart
    02:45-03:00 d'été reçoit 01:45 au passage à l'heure d'hiver). Pour classer des intervalles, prendre lire()["debuts"]."""
    return [f - timedelta(hours=pas_h) for f in fins]


def couverture(fins: list[datetime], pas_h: float) -> dict[str, Any]:
    """Période couverte, nombre d'intervalles attendus pour une année pleine, jours civils présents."""
    d = debuts(fins, pas_h)
    jours = {x.date() for x in d}
    par_an = round(365 * 24 / pas_h)
    return {"debut": d[0].isoformat(), "fin": fins[-1].isoformat(), "intervalles": len(fins), "jours": len(jours),
            "annee_complete": len(fins) >= par_an, "intervalles_par_an": par_an}


def reechantillonner(valeurs: list[float], fins: list[datetime], pas_h: float, cible_h: float) -> tuple[list[float], list[datetime]]:
    """Moyenne par blocs entiers vers un pas plus grand (10 vers 30 min, 15 vers 60 min). Un pas cible qui n'est pas
    un multiple entier du pas source est refusé ; les blocs incomplets en fin de série sont ignorés."""
    rapport = cible_h / pas_h
    if abs(rapport - round(rapport)) > 1e-9 or rapport < 1:
        raise ValueError(f"Rééchantillonnage : {cible_h * 60:g} min n'est pas un multiple de {pas_h * 60:g} min.")
    n = int(round(rapport))
    if n == 1:
        return list(valeurs), list(fins)
    # Aligner sur les bornes du pas cible : on commence au premier intervalle dont la fin tombe sur un multiple.
    depart = next((i for i, f in enumerate(fins) if (f.minute * 60 + f.second) % int(cible_h * 3600) == 0), None)
    if depart is None:
        raise ValueError("Rééchantillonnage : aucune fin d'intervalle alignée sur le pas cible.")
    depart = (depart - (n - 1)) % n
    sortie_v, sortie_f = [], []
    for i in range(depart, len(valeurs) - n + 1, n):
        sortie_v.append(sum(valeurs[i:i + n]) / n)
        sortie_f.append(fins[i + n - 1])
    return sortie_v, sortie_f
