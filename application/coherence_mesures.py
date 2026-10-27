"""Cohérence entre le profil importé et la facture du gestionnaire.

Chantier du 24/09/2026, avant le diagnostic gratuit proposé aux premiers
contacts néerlandais. Objectif : zéro fausse conclusion sur un vrai fichier.

La facture est la vérité de référence : c'est la seule pièce imprimée par le
gestionnaire lui-même. Le profil est une donnée exportée, qui peut être mal
lue. Donc on croise, et on BLOQUE au premier désaccord.

Faits vérifiés sur source, pas supposés :

- Le kWmax facturé est la plus haute puissance MOYENNE d'un quart d'heure dans
  le mois (Fluvius, capaciteitstarief ; loqio.nl sur le kW-max ; CE Delft,
  toelichting tijdsafhankelijke nettarieven, 2024). Le compteur enregistre des
  kWh par quart d'heure, et la puissance moyenne du quart vaut ces kWh × 4.
- Au-delà de 3 x 80 A, le compteur DOIT enregistrer le kWmax et le réactif
  (Stedin, tarieven- en vergoedingsregeling 2026, art. 7 lid 6, DAT-006). Le
  chiffre de comparaison existe donc toujours sur une facture grootverbruik.
- Une mesure qui n'est pas au point de livraison est corrigée des pertes, par
  défaut 1,4 pour cent en MS avec mesure BT (même règlement, art. 5 lid 11,
  DAT-005).

Tolérances : vérifiées par hermes sur la Meetcode elektriciteit, voir les
constantes plus bas et docs/contraintes/terrain/FORMATS-EXPORT-ET-FACTURE.md.
"""
from __future__ import annotations

from typing import Any
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from horodatages import lire_fins_quarts

FACTEUR_KWH_QUART_VERS_KW = 4.0          # 60 min / 15 min
# Tolérances vérifiées par hermes le 24/09 sur la Meetcode elektriciteit
# (BWBR0037946, version du 01/12/2025), extraits dans
# docs/contraintes/terrain/brut/meetcode_BWBR0037946_2025-12-01_extraits.txt.
#
# Pointe : le kWmax facturé est UNE valeur de quart d'heure (art. 2.4.5 et
# 4.3.4.1 b, « de kWmax binnen de gespecificeerde periode »), issue de la MÊME
# meetinrichting que le profil. Un profil complet dans la bonne unité le
# retrouve à l'arrondi de facturation près (Liander imprime des kW entiers).
# La première valeur, 5 %, n'avait pas de source et laissait passer des
# erreurs réelles.
TOLERANCE_KWMAX_KW = 1.0
TOLERANCE_KWMAX_RELATIVE = 0.01
#
# Énergie : bijlage B1.1, erreur maximale d'une meetinrichting neuve sous 2 MW
# de GTV jusqu'à 1,95 % ; art. 5.3.9 a, écart journalier admis entre mesure
# principale et de contrôle « kleiner dan tweemaal de geldende
# nauwkeurigheidsklasse » ; plus la correction de pertes de 1,4 % (DAT-005).
# Borne physique justifiable : 2 x 1,95 + 1,4 = 5,3 %. Au-delà de 5 % on bloque ;
# entre la précision de mesure (2 %) et 5 % on alerte.
TOLERANCE_ENERGIE = 0.05
SEUIL_ALERTE_ENERGIE = 0.02
CORRECTION_PERTES_DEFAUT = 0.014         # DAT-005, Stedin art. 5 lid 11


def _nombre_valide(valeur: Any) -> bool:
    try:
        return type(valeur) in (int, float) and math.isfinite(valeur) and valeur >= 0
    except OverflowError:
        return False


def _profil_valide(valeurs: Any) -> bool:
    return isinstance(valeurs, (list, tuple)) and bool(valeurs) and all(_nombre_valide(v) for v in valeurs)


def _invalide(ident: str, raison: str, constat: str, champ: str) -> dict[str, Any]:
    return {"id": ident, "statut": "bloque", "constat": constat,
            "valeurs": {"raison": raison},
            "manque": [{"champ": champ, "ou_le_trouver": "corriger la valeur dans l'export ou la facture d'origine"}]}


def en_kw(valeurs: list[float], unite: str | None) -> list[float] | None:
    """Convertit le profil en kW moyens. L'unité doit être DÉCLARÉE.

    Renvoie None si l'unité est absente ou inconnue : on ne la devine jamais.
    """
    if unite not in ("kw", "kwh_par_quart"):
        return None
    if not _profil_valide(valeurs):
        raise ValueError("Le profil doit contenir des nombres finis, non négatifs, sans booléen.")
    resultat = list(valeurs) if unite == "kw" else [v * FACTEUR_KWH_QUART_VERS_KW for v in valeurs]
    if not _profil_valide(resultat):
        raise ValueError("La conversion du profil dépasse les nombres représentables.")
    return resultat


def _dans_arrondi(valeur: float, reference: float) -> bool:
    return abs(valeur - reference) <= max(TOLERANCE_KWMAX_KW, TOLERANCE_KWMAX_RELATIVE * reference)


def profil_comparable(profil: list[float], unite: str | None,
                       controle_unite: dict[str, Any]) -> list[float]:
    """Reprend exactement la conversion retenue lors du rapprochement de facture.

    Le facteur vaut un si l'export correspond déjà à la facture. La position
    du compteur seule ne déclenche donc pas une deuxième correction. Le taux
    de 1,4 % reste le défaut MS avec mesure BT de DAT-005, pas un taux universel.
    """
    if controle_unite.get("id") != "COH-UNITE" or controle_unite.get("statut") != "constat":
        raise ValueError("Le profil comparable exige une unité confirmée contre la facture.")
    facteur = controle_unite.get("valeurs", {}).get("facteur_correction_pertes")
    if type(facteur) not in (float, int) or facteur not in (1., 1. + CORRECTION_PERTES_DEFAUT):
        raise ValueError("Le facteur de pertes retenu pour la facture est absent ou invalide.")
    kw = en_kw(profil, unite)
    if kw is None:
        raise ValueError("L'unité du profil comparable doit être déclarée.")
    resultat = [valeur * facteur for valeur in kw]
    if not _profil_valide(resultat):
        raise ValueError("La correction de pertes dépasse les nombres représentables.")
    return resultat


def controler_unite(profil: list[float], unite: str | None,
                    kwmax_facture: float | None,
                    mesure_au_point_de_livraison: bool | None = None) -> dict[str, Any]:
    """La pointe du profil doit retrouver le kWmax imprimé sur la facture.

    Si la pointe vaut environ le quart du kWmax, l'unité déclarée est fausse :
    des kWh par quart d'heure ont été lus comme des kW. C'est l'erreur qui fait
    dire à un client qu'il a de la marge alors qu'il n'en a pas.

    Si la mesure n'est pas au point de livraison, le kWmax facturé peut être
    corrigé des pertes (DAT-005) alors que l'export est brut : on accepte alors
    aussi la pointe corrigée, et on dit laquelle correspond.
    """
    ident = "COH-UNITE"
    if unite is None:
        return {"id": ident, "statut": "bloque",
                "constat": "Unité du profil non déclarée : kW moyen ou kWh par quart d'heure.",
                "manque": [{"champ": "unite_profil",
                            "ou_le_trouver": "en-tête de l'export du compteur ; si absent, "
                                             "demander au meetbedrijf"}]}
    try:
        kw = en_kw(profil, unite)
    except (ValueError, OverflowError):
        return _invalide(ident, "profil_invalide", "Profil invalide : fournir des mesures finies, non négatives et convertibles en kW.", "export_profil")
    if kw is None:
        return {"id": ident, "statut": "bloque",
                "constat": f"Unité « {unite} » non reconnue, attendu kw ou kwh_par_quart.",
                "manque": [{"champ": "unite_profil", "ou_le_trouver": "en-tête de l'export"}]}
    if kwmax_facture is None:
        return {"id": ident, "statut": "bloque",
                "constat": ("Unité déclarée, mais non vérifiable : le kWmax de la facture "
                            "de la même période manque. Sans lui, une erreur d'un facteur 4 passe."),
                "manque": [{"champ": "kwmax_facture",
                            "ou_le_trouver": "facture de transport, ligne « Maximale belasting »"}]}
    if not _nombre_valide(kwmax_facture):
        return _invalide(ident, "kwmax_invalide", "Le kWmax facturé doit être un nombre fini et non négatif, sans booléen.", "kwmax_facture")
    if mesure_au_point_de_livraison is not None and type(mesure_au_point_de_livraison) is not bool:
        return _invalide(ident, "point_livraison_invalide", "La position de mesure doit être indiquée par oui, non ou laissée inconnue.", "mesure_au_point_de_livraison")
    pointe = max(kw)
    if pointe == 0 and kwmax_facture > 0:
        return _invalide(ident, "pointe_nulle", "Profil entièrement nul mais kWmax facturé positif : l'unité ne peut pas être confirmée, même dans la tolérance d'arrondi.", "unite_profil")
    if kwmax_facture == 0:
        if pointe == 0:
            return _invalide(ident, "pointes_nulles", "Profil et kWmax facturé nuls : ces valeurs ne permettent pas de distinguer kW et kWh par quart d'heure. Unité non confirmée.", "unite_profil")
        return _invalide(ident, "kwmax_nul", "Le profil contient une puissance positive mais le kWmax facturé est nul. Vérifier la facture et la période.", "kwmax_facture")
    facteurs = {"brute": 1.}
    if mesure_au_point_de_livraison is False:
        facteurs["corrigée des pertes"] = 1. + CORRECTION_PERTES_DEFAUT
    candidats = {nom: pointe * facteur for nom, facteur in facteurs.items()}
    if not all(_nombre_valide(v) for v in candidats.values()):
        return _invalide(ident, "calcul_non_fini", "La correction de pertes dépasse les nombres représentables.", "export_profil")
    correspondances = [(nom, valeur) for nom, valeur in candidats.items() if _dans_arrondi(valeur, kwmax_facture)]
    if len(correspondances) > 1:
        return {"id": ident, "statut": "bloque",
                "constat": (f"Correction de pertes indéterminable : la pointe brute {pointe:.1f} kW "
                            f"et la pointe corrigée {candidats['corrigée des pertes']:.1f} kW "
                            f"correspondent toutes deux au kWmax facturé {kwmax_facture:.1f} kW "
                            "dans la tolérance. Aucun facteur n'est retenu ; marge et énergie "
                            "non calculées avant confirmation du statut de l'export et du taux applicable."),
                "valeurs": {"raison": "correction_pertes_ambigue", "pointe_kw": pointe,
                            "pointe_corrigee_kw": candidats['corrigée des pertes'],
                            "kwmax_facture": kwmax_facture, "facteurs_possibles": list(facteurs.values())},
                "manque": [{"champ": "correction_pertes_export",
                            "ou_le_trouver": "meetbedrijf : confirmer si l'export intègre déjà les pertes et le taux convenu ; rapprochement manuel nécessaire si l'arrondi ne permet pas de trancher"}]}
    if correspondances:
        nom, valeur = correspondances[0]
        return {"id": ident, "statut": "constat",
                "constat": (f"Pointe du profil {valeur:.1f} kW ({nom}), kWmax facturé "
                            f"{kwmax_facture:.1f} kW : identiques à l'arrondi de facturation "
                            f"près. Unité confirmée."),
                "valeurs": {"pointe_kw": pointe, "pointe_comparee": valeur,
                            "facteur_correction_pertes": facteurs[nom],
                            "kwmax_facture": kwmax_facture, "correspondance": nom}}
    rapport = pointe / kwmax_facture
    if not math.isfinite(rapport):
        return _invalide(ident, "calcul_non_fini", "Le rapport entre les pointes dépasse les nombres représentables.", "kwmax_facture")
    diagnostic = ""
    for facteur, texte in ((0.25, " La pointe vaut le quart du kWmax : le profil est en kWh par "
                                  "quart d'heure et a été déclaré en kW."),
                           (4.0, " La pointe vaut quatre fois le kWmax : le profil est en kW et "
                                 "a été déclaré en kWh par quart d'heure.")):
        for pertes in (1.0, 1 / (1 + CORRECTION_PERTES_DEFAUT)):
            # Le kWmax est imprimé en kW entiers : sur un petit site, l'arrondi seul
            # écarte le rapport de plus de 2 % (vu sur les courbes VEA, 25/09).
            if abs(pointe - facteur * pertes * kwmax_facture) <= facteur * max(
                    TOLERANCE_KWMAX_KW, 0.02 * kwmax_facture):
                diagnostic = texte
    if not diagnostic and mesure_au_point_de_livraison is None and abs(
            rapport * (1 + CORRECTION_PERTES_DEFAUT) - 1) <= TOLERANCE_KWMAX_RELATIVE:
        diagnostic = (" L'écart correspond à la correction de pertes de 1,4 % : préciser si "
                      "le compteur est au point de livraison pour conclure.")
    if not diagnostic:
        diagnostic = (" Ni l'unité ni les pertes n'expliquent l'écart : vérifier que "
                      "l'export et la facture portent sur le même compteur et la même période.")
    return {"id": ident, "statut": "bloque",
            "constat": (f"Incohérence : pointe du profil {pointe:.1f} kW contre kWmax facturé "
                        f"{kwmax_facture:.1f} kW, rapport {rapport:.3f}.{diagnostic} Aucun "
                        f"contrôle de puissance n'est fiable tant que ce point n'est pas réglé."),
            "valeurs": {"pointe_kw": pointe, "kwmax_facture": kwmax_facture, "rapport": rapport},
            "manque": [{"champ": "unite_profil",
                        "ou_le_trouver": "vérifier l'unité de l'export et la période de la facture"}]}


def controler_periode(horodatages: list[Any] | None, periode: tuple[str, str] | None,
                      nb_mesures: int, *, fuseau: str = "Europe/Amsterdam") -> dict[str, Any]:
    """L'export doit couvrir exactement la période de la facture.

    À vérifier AVANT l'unité : un export incomplet peut manquer la vraie pointe ;
    sa pointe serait inférieure au kWmax facturé et l'écart passerait pour une
    erreur d'unité (relevé par codex). La période est celle imprimée sur la
    facture, « Verbruiksperiode », qui n'est pas forcément un mois calendaire :
    un mois calendaire comparé à une facture du 15 au 15 donne un faux écart
    garanti (relevé par hermes).

    ``periode`` = (premier jour inclus, dernier jour inclus), dates ISO.
    Convention : les horodatages marquent la FIN de chaque quart d'heure.
    La facture néerlandaise est datée en Europe/Amsterdam par défaut, même
    si le fichier exprime ses instants en UTC. Les bornes civiles sont
    converties en UTC pour compter exactement les jours de 92 ou 100 quarts.
    Aucun trou, doublon, ordre inversé ou décalage des bornes n'est toléré.
    """
    ident = "COH-PERIODE"
    manque = []
    if not horodatages:
        manque.append({"champ": "profil_horodatages",
                       "ou_le_trouver": "colonne date et heure de l'export du compteur"})
    if not periode or (isinstance(periode, (tuple, list)) and not all(periode)):
        manque.append({"champ": "periode_facture",
                       "ou_le_trouver": "facture, ligne « Verbruiksperiode » (du ... au ...)"})
    if manque:
        return {"id": ident, "statut": "bloque",
                "constat": "Période de l'export non vérifiable contre la facture.",
                "manque": manque}
    try:
        if not isinstance(periode, (tuple, list)) or len(periode) != 2:
            raise ValueError('Deux dates de facture sont nécessaires.')
        debut, fin = (date.fromisoformat(str(x)) for x in periode)
        if fin < debut:
            raise ValueError('La fin de facture précède son début.')
        zone = ZoneInfo(fuseau)
        borne_debut = datetime.combine(debut, time.min, zone).astimezone(timezone.utc)
        borne_fin = datetime.combine(fin + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError) as erreur:
        return {"id": ident, "statut": "bloque",
                "constat": f"Dates ou fuseau de facturation invalides : {erreur}",
                "valeurs": {"raison": "periode_invalide"},
                "manque": [{"champ": "periode_facture", "ou_le_trouver": "facture, deux dates ISO complètes et fuseau de facturation"}]}
    attendu = int((borne_fin - borne_debut).total_seconds() / 900)
    libelle = f"du {debut.isoformat()} au {fin.isoformat()}"
    valeurs = {"mesures": nb_mesures, "attendues": attendu, "fuseau_facture": fuseau}
    try:
        dates = lire_fins_quarts(horodatages)
    except (ValueError, TypeError) as erreur:
        return {"id": ident, "statut": "bloque",
                "constat": f"Horodatages non vérifiés pour la période {libelle} : {erreur}",
                "valeurs": valeurs | {"raison": "horodatages_invalides"},
                "manque": [{"champ": "profil_horodatages", "ou_le_trouver": "export complet, fins de quarts avec décalage UTC et sans trou ni doublon"}]}
    fins = [instant.astimezone(timezone.utc) for instant in dates]
    hors = sum(1 for instant in fins if not borne_debut < instant <= borne_fin)
    valeurs.update({"horodatages": len(fins), "hors_periode": hors,
                    "premier_quart_fin": fins[0].isoformat() if fins else None,
                    "dernier_quart_fin": fins[-1].isoformat() if fins else None,
                    "premier_attendu_fin": (borne_debut + timedelta(minutes=15)).isoformat(),
                    "dernier_attendu_fin": borne_fin.isoformat()})
    if (isinstance(nb_mesures, int) and not isinstance(nb_mesures, bool)
            and nb_mesures == len(fins) == attendu and hors == 0
            and fins and fins[0] == borne_debut + timedelta(minutes=15) and fins[-1] == borne_fin):
        return {"id": ident, "statut": "constat",
                "constat": (f"L'export couvre la période facturée {libelle} : {nb_mesures} "
                            f"quarts d'heure pour {attendu} attendus en {fuseau}, bornes et continuité vérifiées. Le meetbedrijf peut avoir "
                            "reconstitué certaines valeurs selon la Meetcode 5.4.3 ; sans colonne "
                            "de qualité dans le fichier, leur statut reste inconnu."),
                "valeurs": valeurs}
    return {"id": ident, "statut": "bloque",
            "constat": (f"L'export ne couvre pas exactement la période facturée {libelle} : "
                        f"{nb_mesures} mesures, {len(fins)} horodatages pour {attendu} quarts attendus en {fuseau}, dont {hors} hors "
                        f"période. La pointe peut manquer : aucune comparaison au kWmax n'est fiable."),
            "valeurs": valeurs | {"raison": "couverture_incomplete"},
            "manque": [{"champ": "export_profil",
                        "ou_le_trouver": f"réexporter exactement la période {libelle}"}]}


def periode_du_dossier(dossier: dict[str, Any]) -> tuple[str, str] | None:
    """Bornes de la facture ; un mois calendaire AAAA-MM n'est qu'un repli."""
    from calendar import monthrange
    if dossier.get("periode_facture_debut") is not None or dossier.get("periode_facture_fin") is not None:
        return dossier.get("periode_facture_debut"), dossier.get("periode_facture_fin")
    if dossier.get("mois_facture") is not None:
        valeur = dossier["mois_facture"]
        if not isinstance(valeur, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", valeur):
            raise ValueError("Le mois facturé doit être au format AAAA-MM.")
        annee, mois = (int(x) for x in valeur.split("-"))
        date(annee, mois, 1)
        return f"{annee:04d}-{mois:02d}-01", f"{annee:04d}-{mois:02d}-{monthrange(annee, mois)[1]:02d}"
    return None


def controler_energie(profil_kw: list[float], kwh_facture: float | None) -> dict[str, Any]:
    """L'énergie du profil doit retrouver les kWh facturés sur la même période."""
    ident = "COH-ENERGIE"
    if kwh_facture is None:
        return {"id": ident, "statut": "bloque",
                "constat": "Énergie facturée absente : la couverture du profil n'est pas vérifiable.",
                "manque": [{"champ": "kwh_facture",
                            "ou_le_trouver": "facture du même mois, ligne verbruik en kWh"}]}
    if not _nombre_valide(kwh_facture):
        return _invalide(ident, "kwh_invalide", "L'énergie facturée doit être un nombre fini et non négatif, sans booléen.", "kwh_facture")
    if not _profil_valide(profil_kw):
        return _invalide(ident, "profil_invalide", "Profil invalide : fournir des puissances finies et non négatives.", "export_profil")
    try:
        energie = math.fsum(v / FACTEUR_KWH_QUART_VERS_KW for v in profil_kw)
    except OverflowError:
        return _invalide(ident, "calcul_non_fini", "L'énergie totale dépasse les nombres représentables.", "export_profil")
    if kwh_facture == 0 and energie > 0:
        return {**_invalide(ident, "kwh_nul", "Énergie facturée nulle mais énergie positive dans le profil. Écart relatif non défini : vérifier les mesures et la facture.", "kwh_facture"),
                "valeurs": {"raison": "kwh_nul", "energie_profil_kwh": energie, "kwh_facture": 0, "ecart": None}}
    ecart = abs(energie - kwh_facture) / kwh_facture if kwh_facture else 0.
    if not math.isfinite(ecart):
        return _invalide(ident, "calcul_non_fini", "L'écart relatif dépasse les nombres représentables.", "kwh_facture")
    valeurs = {"energie_profil_kwh": energie, "kwh_facture": kwh_facture, "ecart": ecart}
    causes = (" Causes légitimes possibles : énergie facturée en deux lignes « afn. laag » et "
              "« afn. hoog » à additionner ; valeurs estimées dans le profil (Meetcode 5.4.3.2, "
              "trous comblés par un jour comparable) ; correction de pertes.")
    if ecart <= SEUIL_ALERTE_ENERGIE:
        return {"id": ident, "statut": "constat",
                "constat": (f"Énergie du profil {energie:.0f} kWh, facturée {kwh_facture:.0f} kWh, "
                            f"écart {ecart * 100:.1f} %, dans la précision de mesure."),
                "valeurs": valeurs}
    if ecart <= TOLERANCE_ENERGIE:
        return {"id": ident, "statut": "alerte",
                "constat": (f"Énergie du profil {energie:.0f} kWh, facturée {kwh_facture:.0f} kWh, "
                            f"écart {ecart * 100:.1f} %, au-delà de la précision de mesure mais "
                            f"dans la borne de 5 %.{causes}"),
                "valeurs": valeurs}
    return {"id": ident, "statut": "bloque",
            "constat": (f"Énergie du profil {energie:.0f} kWh contre {kwh_facture:.0f} kWh "
                        f"facturés, écart {ecart * 100:.1f} %, au-delà de 5 %. Période différente, "
                        f"export incomplet ou mauvaise unité : à régler avant toute conclusion.{causes}"),
            "valeurs": valeurs,
            "manque": [{"champ": "kwh_facture",
                        "ou_le_trouver": "facture, lignes « afn. laag » + « afn. hoog » de la même période"}]}


def signaler_correction_pertes(mesure_au_point_de_livraison: bool | None) -> dict[str, Any]:
    """Les chiffres bruts du compteur ne sont pas les chiffres facturés (DAT-005)."""
    ident = "COH-PERTES"
    if mesure_au_point_de_livraison is not None and type(mesure_au_point_de_livraison) is not bool:
        return _invalide(ident, "point_livraison_invalide", "La position de mesure doit être indiquée par oui, non ou laissée inconnue.", "mesure_au_point_de_livraison")
    if mesure_au_point_de_livraison is None:
        return {"id": ident, "statut": "bloque",
                "constat": "On ne sait pas si le compteur est au point de livraison.",
                "manque": [{"champ": "mesure_au_point_de_livraison",
                            "ou_le_trouver": "ATO ou schéma unifilaire : mesure côté MS ou côté BT"}]}
    if mesure_au_point_de_livraison:
        return {"id": ident, "statut": "constat",
                "constat": "Mesure au point de livraison : pas de correction de pertes."}
    return {"id": ident, "statut": "alerte",
            "constat": (f"Mesure hors point de livraison : les valeurs facturées sont corrigées "
                        f"des pertes, par défaut {CORRECTION_PERTES_DEFAUT * 100:.1f} % en MS avec "
                        f"mesure BT, sauf autre pourcentage convenu. Les comparaisons au GTV "
                        f"doivent se faire sur les valeurs corrigées."),
            "valeurs": {"correction_defaut": CORRECTION_PERTES_DEFAUT}}


TITRES = {
    "COH-PERIODE": ("Période de l'export vérifiée contre la facture", ["DAT-001"]),
    "COH-UNITE": ("Unité du profil vérifiée contre la facture", ["DAT-006", "DAT-001"]),
    "COH-ENERGIE": ("Énergie du profil vérifiée contre la facture", ["DAT-001"]),
    "COH-PERTES": ("Correction de pertes de mesure", ["DAT-005"]),
}


def _habiller(resultat: dict[str, Any]) -> dict[str, Any]:
    titre, contraintes = TITRES[resultat["id"]]
    return {"titre": titre, "contraintes": contraintes, **resultat}


def executer(dossier: dict[str, Any]) -> list[dict[str, Any]]:
    """Les contrôles de cohérence, à passer AVANT les contrôles de puissance."""
    brut = dossier.get("profil_brut")
    if brut is None:
        brut = dossier.get("profil_kw")
    unite = dossier.get("unite_profil")
    try:
        periode = controler_periode(dossier.get("profil_horodatages"), periode_du_dossier(dossier),
                                    len(brut) if isinstance(brut, (list, tuple)) else 0)
    except (ValueError, TypeError, OverflowError):
        periode = _invalide("COH-PERIODE", "periode_invalide", "Dates de facturation invalides : fournir deux dates complètes ou un mois AAAA-MM valide.", "periode_facture")
    if periode["statut"] != "constat":
        return [_habiller(periode),
                _habiller({"id": "COH-UNITE", "statut": "bloque",
                           "constat": "Unité non vérifiée : la période de l'export n'est pas confirmée.",
                           "valeurs": {"raison": "periode_non_confirmee"},
                           "manque": periode.get("manque", [])}),
                _habiller(signaler_correction_pertes(dossier.get("mesure_au_point_de_livraison")))]
    resultats = [periode, controler_unite(brut, unite, dossier.get("kwmax_facture"),
                                          dossier.get("mesure_au_point_de_livraison"))]
    if resultats[1]["statut"] == "constat":
        kw = profil_comparable(brut, unite, resultats[1])
        energie = controler_energie(kw, dossier.get("kwh_facture"))
        energie.setdefault("valeurs", {})["facteur_correction_pertes"] = resultats[1]["valeurs"]["facteur_correction_pertes"]
        resultats.append(energie)
    else:
        resultats.append(_invalide("COH-ENERGIE", "unite_non_confirmee", "Énergie non comparée : l'unité du profil n'est pas confirmée.", "unite_profil"))
    resultats.append(signaler_correction_pertes(dossier.get("mesure_au_point_de_livraison")))
    return [_habiller(r) for r in resultats]


def puissance_fiable(resultats: list[dict[str, Any]]) -> bool:
    """Vrai seulement si l'unité est confirmée contre la facture."""
    return any(r["id"] == "COH-UNITE" and r["statut"] == "constat" for r in resultats)
