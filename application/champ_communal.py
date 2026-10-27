"""Étage 1 des contrôles communaux : le texte s'applique-t-il à ce site ?

Écrit par hermes le 24/09/2026 à la demande de claude (bus #311), après relecture
des sept textes bruts sous docs/contraintes/terrain/brut/. Ce module ne contient
QUE des faits lus dans les textes et une fonction. Il ne calcule aucun seuil
chiffré : l'étage 2 (hauteur, bruit, usage, permis, plafond PV) reste dans
controles.py et ne doit être exécuté que si ``dans_le_champ`` répond
« dans_le_champ ».

Règle de conception adoptée sur le bus : si l'étage 1 ne conclut pas, on bloque
sur les champs de l'étage 1 et on n'affiche JAMAIS le chiffre. Sinon l'ingénieur
retient « 3,5 m » pour un site où la beleidslijn ne s'applique même pas.

Constat qui fonde ce module : six communes sur six ont une clause de champ
d'application avant leur chiffre. Pour le cas type de Contingency (batterie
derrière le compteur d'une entreprise, site industriel, souvent déjà en
activité), la plupart de ces clauses disent « hors champ ».

Chaque ligne de la table porte la citation exacte, la référence CVDR et la ligne
du texte brut, pour que celui qui code ou relit ait le texte sous les yeux.

Champs du dossier lus par l'étage 1 (tous optionnels, l'absence bloque) :
- ``commune``
- ``soumis_a_permis``            bool  : l'installation est-elle vergunningplichtig ?
- ``chimie_batterie``            str   : « lithium-ion », « lfp », « sodium », « flow »...
- ``capacite_kwh``               float : capacité totale installée
- ``date_mise_en_service``       date ISO, ou None si pas encore en service
- ``conforme_plan_temporaire``   bool  : activité existante conforme au tijdelijk deel
                                         de l'omgevingsplan (Drechtsteden, art. 1.1)
- ``regime_lieu``                str   : Hollands Kroon, l'un de REGIMES_HOLLANDS_KROON
- ``energyhub_designe``          bool  : Hollands Kroon, energyhub désigné par le college
- ``lijnopstelling_windturbines`` bool : Hollands Kroon, alignement d'éoliennes
- ``perceel_attenant_380kv``     bool  : Hollands Kroon, parcelle attenante au poste
- ``zone_nommee``                str   : Oosterhout, nom de la zone ou du parc d'accueil
- ``grootschalig``               bool  : Tiel, qualification « grootschalig » (non chiffrée)
- ``zone``                       str   : Best, « buitengebied » ou autre
- ``couplee_parc_pv``            bool  : Best, batterie adossée à un zonnepark
"""
from __future__ import annotations

from datetime import date
from typing import Any
from controles_contrat import nombre_non_negatif

BRUT = "docs/contraintes/terrain/brut/https_lokaleregelgeving_overheid_nl_{ref}_{v}.txt"

REGIMES_HOLLANDS_KROON = ("bedrijfsmatig", "energyhub", "windturbines", "zonnepark", "380kv")

_DRECHTSTEDEN_COMMUN = {
    "modele": "Drechtsteden, voorbeschermingsregels energieopslagsystemen",
    "chimie_visee": "lithium",
    "citation_chimie": (
        "« energieopslagsysteem, bestaande uit lithiumhoudende oplaadbare energiedragers "
        "die (in groepen) elektrisch met elkaar zijn verbonden met een totaal opgestelde "
        "capaciteit van 1 MWh en daarboven » (art. 1.3 Toepassingsbereik)"
    ),
    "capacite_min_kwh": 1000.0,
    "citation_capacite": (
        "« Deze afdeling is van toepassing op het plaatsen van een EOS. Hierbij is een "
        "ondergrens van 1 MWh vastgelegd. » (toelichting art. 1.3) ; origine du seuil : "
        "« effectafstanden uit het scenarioboek Omgevingsveiligheid van het NIFV »"
    ),
    "citation_anteriorite": (
        "« De voorbeschermingsregels in dit hoofdstuk zijn niet van toepassing op "
        "activiteiten die al werden verricht voorafgaand aan de inwerkingtreding van dit "
        "hoofdstuk en die in overeenstemming zijn met de regels in het tijdelijke deel "
        "van dit omgevingsplan. » (art. 1.1 Overgangsrecht)"
    ),
    "porte_aussi_sur": (
        "le seuil de permis (art. 1.5), les pièces exigées (art. 1.6) ET les valeurs de "
        "bruit du tableau 1.7 : sous 1 MWh ou hors lithium, aucune de ces règles ne "
        "s'applique, le bruit est renvoyé à l'omgevingsplan"
    ),
}

CHAMPS_COMMUNAUX: dict[str, dict[str, Any]] = {
    "hollands kroon": {
        "commune": "Hollands Kroon",
        "reference": "CVDR764372",
        "titre": "Beleidslijn Batterijopslagsystemen",
        "en_vigueur_le": "2026-07-14",
        "citation_date": "« Geldend van 14-07-2026 t/m heden » (brut ligne 51)",
        "brut": BRUT.format(ref="CVDR764372", v=1),
        "clause_vergunningsvrij": True,
        "citation_vergunningsvrij": (
            "« Deze beleidslijn is nadrukkelijk niet van toepassing op vergunningsvrije "
            "batterijopslagsystemen. » (brut ligne 93)"
        ),
        "achter_de_meter_dans_le_champ": True,
        "citation_champ": (
            "« van toepassing op batterijopslagsystemen [...] die direct worden aangesloten "
            "op het elektriciteitsnet van TenneT, Liander, andere private netbeheerders of "
            "worden aangesloten op een bestaande aansluiting (\u201cachter de meter\u201d) » "
            "(brut lignes 86-90)"
        ),
        "regimes_de_lieu": {
            "citation": (
                "« Locatiekeuze : alleen op locaties waar bedrijfsmatige activiteiten zijn "
                "toegestaan, of nabij 380kV-hoogspanningsstations, of binnen energyhubs, of "
                "nabij windturbines of binnen een zonnepark » (brut ligne 96)"
            ),
            "bedrijfsmatig": {
                "citation": (
                    "« Bij bedrijfsmatige activiteiten is er één installatie per bouwvlak "
                    "toegestaan. Deze installatie moet binnen het bouwvlak worden gebouwd en "
                    "ondergeschikt zijn aan de bedrijfsvoering van het betreffende bedrijf. » "
                    "(brut lignes 99-101)"
                ),
                "condition": None,
            },
            "energyhub": {
                "citation": (
                    "« enkel toegestaan binnen de door het college van Hollands Kroon "
                    "aangewezen energyhubs » ; « Per energyhub is er één batterijopslagsysteem "
                    "toegestaan van maximaal 0,5 hectare. » (brut lignes 104-109)"
                ),
                "condition": "energyhub_designe",
                "si_condition_fausse": "hors des lieux admis : energyhub non désigné par le college",
            },
            "windturbines": {
                "citation": (
                    "« Enkel bij lijnopstellingen van windturbines zijn batterijopslagsystemen "
                    "toegestaan » ; « Per windturbine is er maximaal 300 m2 aan projectgebied "
                    "toegestaan » ; « De einddatum van de windturbine(s) is hierbij leidend. » "
                    "(brut lignes 112-124)"
                ),
                "condition": "lijnopstelling_windturbines",
                "si_condition_fausse": "hors des lieux admis : éoliennes hors alignement (lijnopstelling)",
            },
            "zonnepark": {
                "citation": (
                    "« Het batterijopslagsysteem mag maximaal 5% van het bestaande zonnepark "
                    "projectgebied innemen. » ; parc temporaire : « de vergunning voor het "
                    "batterijopslagsysteem voor dezelfde periode » (brut lignes 126-133)"
                ),
                "condition": None,
            },
            "380kv": {
                "citation": (
                    "« Het batterijopslagsysteem moet aansluitend aan het perceel van "
                    "380kV-hoogspanningsstation worden gerealiseerd. Afwijken hiervan is enkel "
                    "mogelijk op verzoek van de netbeheerder » ; « maximaal de helft van de "
                    "oppervlakte van het hoogspanningsstation [...] met een maximum van 10 "
                    "hectare (of 5 hectare, afhankelijk van de hoogte) » (brut lignes 134-140)"
                ),
                "condition": "perceel_attenant_380kv",
                "si_condition_fausse": ("hors des lieux admis : parcelle non attenante au poste 380 kV, "
                                        "dérogation seulement à la demande du gestionnaire"),
            },
        },
        "zones_exclues": (),
    },
    "dordrecht": {
        **_DRECHTSTEDEN_COMMUN,
        "commune": "Dordrecht",
        "reference": "CVDR739938",
        "en_vigueur_le": "2025-05-30",
        "citation_date": "« Geldend van 30-05-2025 t/m heden » (brut ligne 55)",
        "brut": BRUT.format(ref="CVDR739938", v=1),
        "lignes_brut": "art. 1.1 lignes 69-71, art. 1.3 lignes 92-95, toelichting lignes 206-208",
    },
    "hendrik ido ambacht": {
        **_DRECHTSTEDEN_COMMUN,
        "commune": "Hendrik-Ido-Ambacht",
        "reference": "CVDR745351",
        "en_vigueur_le": "2025-10-10",
        "citation_date": "« Geldend van 10-10-2025 t/m heden » (brut ligne 51)",
        "brut": BRUT.format(ref="CVDR745351", v=1),
        "lignes_brut": "art. 1.1 lignes 66-68",
    },
    "zwijndrecht": {
        **_DRECHTSTEDEN_COMMUN,
        "commune": "Zwijndrecht",
        "reference": "CVDR749139",
        "en_vigueur_le": "2025-12-05",
        "citation_date": "« Geldend van 05-12-2025 t/m heden » (brut ligne 59)",
        "brut": BRUT.format(ref="CVDR749139", v=1),
        "lignes_brut": "art. 1.1 lignes 74-76",
    },
    "tiel": {
        "commune": "Tiel",
        "reference": "CVDR736212",
        "titre": "Beleidskader duurzame energie, par. 5.3 et 5.4",
        "en_vigueur_le": "2025-03-05",
        "citation_date": "« Geldend van 05-03-2025 t/m heden » (brut ligne 87)",
        "brut": BRUT.format(ref="CVDR736212", v=1),
        "objet_non_chiffre": True,
        "citation_objet": (
            "« De gemeente Tiel erkent de noodzaak om grootschalige opslag van elektriciteit "
            "mogelijk te maken [...] De verschijningsvormen van grootschalige energieopslag zijn "
            "divers, hebben veelal diverse bouwvormen (containers) en betreffen een "
            "bedrijfsactiviteit. » (brut lignes 558-561). Aucun seuil chiffré de « grootschalig »."
        ),
        "zones_exclues": (),
    },
    "oosterhout": {
        "commune": "Oosterhout",
        "reference": "CVDR756415",
        "titre": "Voorbereidingsbesluit energie assets gemeente Oosterhout (2026)",
        "en_vigueur_le": "2026-06-20",
        "citation_date": ("« Geldend van 20-06-2026 t/m heden » (brut ligne 47) ; « Dit "
                          "voorbereidingsbesluit treedt daags na bekendmaking in werking. » (ligne 108)"),
        "brut": BRUT.format(ref="CVDR756415", v=2),
        "citation_anteriorite": (
            "« voor zover het daarbij gaat om activiteiten die op grond van het omgevingsplan "
            "zijn toegestaan, maar nog niet plaatsvinden op het moment van de inwerkingtreding "
            "van deze voorbeschermingsregels » (art. 1.2 lid 2, brut lignes 78-81)"
        ),
        "zones_exclues": ("everdenberg oost", "energiepark a59", "zonnepark dorst"),
        "citation_zones": (
            "« voor het gehele grondgebied van de gemeente Oosterhout, met uitzondering van het "
            "bedrijventerrein Everdenberg-Oost, het Energiepark A59 en het Zonnepark Dorst. » "
            "(art. 1.2 lid 1, brut lignes 75-76)"
        ),
    },
    "best": {
        "commune": "Best",
        "reference": "730220",
        "titre": "Afwegingskader grootschalige duurzame energie buitengebied Best 2024",
        "en_vigueur_le": "2024-12-20",
        "citation_date": "« Geldend van 20-12-2024 t/m heden » (brut ligne 70)",
        "brut": BRUT.format(ref="730220", v=1),
        "zone_visee": "buitengebied",
        "couplage_pv_exige": True,
        "citation_champ": (
            "« Als de locatie gelegen is in het buitengebied dan hanteren wij het uitgangspunt "
            "dat een batterijpakket bij een zonnepark maximaal dezelfde capaciteit mag hebben "
            "als de maximale piekcapaciteit van het zonnepark. » (brut lignes 152-154)"
        ),
        "zones_exclues": (),
    },
}


def _resultat(statut: str, commune: str, regle: dict[str, Any] | None, raison: str,
              citation: str | None = None, manque: list[dict[str, str]] | None = None,
              **extra: Any) -> dict[str, Any]:
    fiche = {
        "statut": statut,
        "commune": commune,
        "reference": regle["reference"] if regle else None,
        "en_vigueur_le": regle["en_vigueur_le"] if regle else None,
        "raison": raison,
        "citation": citation,
        "manque": manque or [],
    }
    fiche.update(extra)
    return fiche


def _date(valeur: Any) -> date:
    from controles import _jour_iso
    return _jour_iso(valeur, 'date_mise_en_service')


def _normaliser_zone(valeur: Any) -> str:
    from controles import _cle_commune
    return _cle_commune(valeur)


def dans_le_champ(dossier: dict[str, Any], commune: Any) -> dict[str, Any]:
    """Répond : le texte communal s'applique-t-il à ce site ?

    Renvoie un dictionnaire avec ``statut`` parmi ``dans_le_champ``, ``hors_champ``,
    ``indetermine``, plus ``raison``, ``citation``, et ``manque`` (liste de
    ``{champ, ou_le_trouver}``) quand c'est indéterminé. Pour Hollands Kroon,
    ``variante`` porte le régime de lieu retenu.

    Aucun chiffre de l'étage 2 n'est calculé ici.
    """
    # Import différé : controles.py importera ce module pour brancher l'étage 1,
    # un import au niveau du module créerait un cycle.
    from controles import _cle_commune

    cle = _cle_commune(commune)
    regle = CHAMPS_COMMUNAUX.get(cle)
    nom = str(commune)
    if regle is None:
        return _resultat(
            "indetermine", nom, None,
            f"Aucun texte communal lu en source primaire pour {nom}.",
            manque=[{"champ": "regle_communale",
                     "ou_le_trouver": "lokaleregelgeving.overheid.nl, beleidslijn ou "
                                      "voorbeschermingsregels batterijopslag de la commune"}])

    manque: list[dict[str, str]] = []

    # 1. Clause vergunningsvrij (Hollands Kroon).
    if regle.get("clause_vergunningsvrij"):
        soumis = dossier.get("soumis_a_permis")
        if soumis is False:
            return _resultat("hors_champ", nom, regle,
                             "L'installation est vergunningsvrij, la beleidslijn s'en exclut expressément.",
                             regle["citation_vergunningsvrij"])
        if soumis is None:
            manque.append({"champ": "soumis_a_permis",
                           "ou_le_trouver": "Bbl et omgevingsplan : l'installation est-elle "
                                            "vergunningplichtig ? à trancher avant de lire la beleidslijn"})

    # 2. Chimie visée (Drechtsteden : lithiumhoudende).
    # Corrigé par claude le 24/09 : le test « "lithium" in chimie » classait LFP,
    # Li-ion et NMC hors champ. La classification passe par controles.est_lithium.
    from controles import est_lithium as _est_lithium
    if regle.get("chimie_visee"):
        chimie = str(dossier.get("chimie_batterie") or "").strip().lower()
        if not chimie:
            manque.append({"champ": "chimie_batterie",
                           "ou_le_trouver": "fiche technique du fabricant, chimie des cellules"})
        elif _est_lithium(chimie) is None:
            manque.append({"champ": "chimie_batterie",
                           "ou_le_trouver": f"chimie « {chimie} » non reconnue : préciser la "
                                            f"chimie des cellules sur la fiche technique "
                                            f"(par exemple LFP, NMC, sodium-ion, flow)"})
        elif _est_lithium(chimie) is False:
            return _resultat("hors_champ", nom, regle,
                             f"Le texte vise les accumulateurs « lithiumhoudende » ; la chimie "
                             f"déclarée est « {chimie} ». Ni le seuil de permis ni les valeurs "
                             f"de bruit ne s'appliquent.",
                             regle["citation_chimie"], porte_aussi_sur=regle["porte_aussi_sur"])

    # 3. Capacité minimale du champ (Drechtsteden : 1 MWh dans le toepassingsbereik).
    if regle.get("capacite_min_kwh") is not None:
        capacite = dossier.get("capacite_kwh")
        if capacite is None:
            manque.append({"champ": "capacite_kwh",
                           "ou_le_trouver": "capacité totale installée, fiche technique"})
        elif not nombre_non_negatif(capacite):
            return _resultat("indetermine", nom, regle,
                             "Capacité invalide : fournir un nombre fini, non négatif, sans booléen ni texte. Le champ communal ne peut pas être déterminé avec cette valeur.",
                             manque=[{"champ": "capacite_kwh", "ou_le_trouver": "capacité totale installée en kWh, valeur numérique de la fiche technique"}])
        elif float(capacite) < regle["capacite_min_kwh"]:
            return _resultat("hors_champ", nom, regle,
                             f"Capacité {float(capacite):.0f} kWh sous la borne de "
                             f"{regle['capacite_min_kwh']:.0f} kWh du champ d'application. "
                             f"Le texte entier (permis, pièces, bruit) ne s'applique pas.",
                             regle["citation_capacite"], porte_aussi_sur=regle["porte_aussi_sur"])

    # 4. Antériorité : activité déjà en cours à la date d'effet.
    if regle.get("citation_anteriorite"):
        if "date_mise_en_service" not in dossier:
            manque.append({"champ": "date_mise_en_service",
                           "ou_le_trouver": "date de mise en service réelle, ou None si le "
                                            "projet n'est pas encore en service"})
        elif dossier["date_mise_en_service"]:
            try:
                jour = _date(dossier["date_mise_en_service"])
            except ValueError:
                return _resultat('indetermine', nom, regle, 'Date de mise en service invalide.',
                                 manque=[{'champ': 'date_mise_en_service', 'ou_le_trouver': 'Date valide au format AAAA-MM-JJ, ou null pour un projet non encore en service.'}])
            effet = date.fromisoformat(regle["en_vigueur_le"])
            if jour < effet:
                if regle.get("modele", "").startswith("Drechtsteden"):
                    # Deux conditions cumulatives dans l'art. 1.1 : antériorité ET conformité
                    # au tijdelijk deel de l'omgevingsplan.
                    conforme = dossier.get("conforme_plan_temporaire")
                    if conforme is None:
                        manque.append({"champ": "conforme_plan_temporaire",
                                       "ou_le_trouver": "omgevingsplan, tijdelijk deel : l'activité "
                                                        "existante y est-elle conforme ?"})
                    elif conforme:
                        return _resultat("hors_champ", nom, regle,
                                         f"Activité en service le {jour.isoformat()}, avant l'entrée "
                                         f"en vigueur du {effet.isoformat()}, et conforme au tijdelijk "
                                         f"deel de l'omgevingsplan.",
                                         regle["citation_anteriorite"])
                    # conforme is False : l'antériorité ne protège pas, on continue.
                else:
                    return _resultat("hors_champ", nom, regle,
                                     f"Activité en service le {jour.isoformat()}, avant l'entrée en "
                                     f"vigueur du {effet.isoformat()} : le voorbereidingsbesluit ne "
                                     f"vise que les activités « nog niet plaatsvinden ».",
                                     regle["citation_anteriorite"])

    # 5. Zones nommées hors du champ (Oosterhout).
    if regle.get("zones_exclues"):
        zone = dossier.get("zone_nommee")
        if zone is None:
            manque.append({"champ": "zone_nommee",
                           "ou_le_trouver": "nom du bedrijventerrein, energiepark ou zonnepark "
                                            "d'accueil, plan cadastral ; « aucune » si hors de ces zones"})
        elif _normaliser_zone(zone) in {*regle['zones_exclues'], 'bedrijventerrein everdenberg oost'}:
            return _resultat("hors_champ", nom, regle,
                             f"Le site est dans « {zone} », zone exclue du werkingsgebied.",
                             regle["citation_zones"])
        elif _normaliser_zone(zone) != 'aucune':
            manque.append({"champ": "zone_nommee",
                           "ou_le_trouver": "Localisation à confirmer sur le plan cadastral : fournir le nom exact de la zone, ou « aucune » si hors des zones exclues. Une proximité, une négation ou un nom voisin ne permet pas de conclure."})

    # 6. Objet non chiffré (Tiel : grootschalig).
    if regle.get("objet_non_chiffre"):
        groot = dossier.get("grootschalig")
        if groot is None:
            manque.append({"champ": "grootschalig",
                           "ou_le_trouver": "le texte de Tiel ne chiffre pas « grootschalig » : "
                                            "qualification à motiver ou à demander à la commune"})
        elif groot is False:
            return _resultat("hors_champ", nom, regle,
                             "Le beleidskader vise la « grootschalige opslag » exploitée comme "
                             "bedrijfsactiviteit ; le projet est qualifié non grootschalig. "
                             "Qualification non chiffrée par le texte, à conserver au dossier.",
                             regle["citation_objet"])

    # 7. Zone et couplage (Best : buitengebied ET batterie adossée à un zonnepark).
    if regle.get("zone_visee"):
        zone = dossier.get("zone")
        couplee = dossier.get("couplee_parc_pv")
        if zone is None:
            manque.append({"champ": "zone",
                           "ou_le_trouver": "omgevingsplan : le site est-il en buitengebied ?"})
        if couplee is None:
            manque.append({"champ": "couplee_parc_pv",
                           "ou_le_trouver": "la batterie est-elle adossée à un zonnepark ?"})
        zone_normalisee = _normaliser_zone(zone) if zone is not None else None
        zones_hors = {'bedrijventerrein', 'stedelijk gebied', 'bebouwde kom', 'hors buitengebied', 'buiten het buitengebied'}
        if zone_normalisee in zones_hors:
            return _resultat("hors_champ", nom, regle,
                             f"Le site n'est pas en buitengebied (zone déclarée « {zone} »).",
                             regle["citation_champ"])
        if zone is not None and zone_normalisee not in ('buitengebied', 'buitengebied best'):
            manque.append({'champ': 'zone', 'ou_le_trouver': 'Zone non reconnue : préciser buitengebied ou la zone du plan communal.'})
        if couplee is False:
            return _resultat("hors_champ", nom, regle,
                             "La batterie n'est pas adossée à un zonnepark ; l'uitgangspunt ne "
                             "vise que « een batterijpakket bij een zonnepark ».",
                             regle["citation_champ"])

    # 8. Régime de lieu (Hollands Kroon) : ne sort pas du champ, choisit la variante.
    variante = None
    condition_lieu_remplie = None
    if regle.get("regimes_de_lieu"):
        regimes = regle["regimes_de_lieu"]
        lieu = dossier.get("regime_lieu")
        if lieu is None:
            manque.append({"champ": "regime_lieu",
                           "ou_le_trouver": "l'un de " + ", ".join(REGIMES_HOLLANDS_KROON)
                                            + " ; omgevingsplan et situation du site"})
        else:
            lieu = str(lieu).strip().lower()
            if lieu not in REGIMES_HOLLANDS_KROON:
                variante = "hors_regimes_admis"
            else:
                fiche = regimes[lieu]
                cond = fiche.get("condition")
                if cond:
                    valeur = dossier.get(cond)
                    if valeur is None:
                        manque.append({"champ": cond, "ou_le_trouver": fiche["citation"]})
                    else:
                        condition_lieu_remplie = valeur is True
                variante = lieu

    if manque:
        return _resultat("indetermine", nom, regle,
                         "Le champ d'application n'est pas tranché : il manque des données de "
                         "l'étage 1. Ne pas afficher le seuil chiffré.",
                         regle.get("citation_champ") or regle.get("citation_chimie")
                         or regle.get("citation_anteriorite") or regle.get("citation_objet"),
                         manque=manque)

    raison = f"Le texte {regle['reference']} ({regle['en_vigueur_le']}) s'applique à ce site."
    if regle.get("achter_de_meter_dans_le_champ"):
        raison += " Une batterie derrière le compteur est expressément dans le champ."
    if variante == "hors_regimes_admis":
        raison += f" Le lieu déclaré « {dossier.get('regime_lieu')} » n'est aucun des cinq régimes admis."
    elif condition_lieu_remplie is False:
        raison += " " + regle["regimes_de_lieu"][variante]["si_condition_fausse"] + "."
    extra: dict[str, Any] = {}
    if variante:
        extra["variante"] = variante
        if variante == "hors_regimes_admis":
            extra["citation_variante"] = regle["regimes_de_lieu"]["citation"]
        else:
            extra["citation_variante"] = regle["regimes_de_lieu"][variante]["citation"]
    if condition_lieu_remplie is not None:
        extra["condition_lieu_remplie"] = condition_lieu_remplie
    return _resultat("dans_le_champ", nom, regle, raison,
                     regle.get("citation_champ") or regle.get("citation_chimie")
                     or regle.get("citation_anteriorite") or regle.get("citation_objet"),
                     **extra)
