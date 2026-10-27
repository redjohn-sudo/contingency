"""Rapport HTML du scan de flexibilité, en français et en néerlandais.

Chaque grandeur affiche sa nature (mesuré, simulé, publié, hypothèse, à chiffrer) et sa source. Sources,
unités et textes arrivent de scan_flex.py sous forme de clés : ils sont rendus ici dans la langue
demandée, et une clé sans traduction fait échouer le rendu plutôt que d'afficher du français dans le
rapport néerlandais. Les graphiques sont des SVG écrits ici : le rapport s'ouvre hors ligne.
"""
from __future__ import annotations

import html
import math
import re
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

# « tarif » couvre les tarifs publiés et les règles publiées (ACM, RVO) : l'étiquette dit « Publié », pas « Tarif »,
# qui était posée sur des règles (troisième relecture, point 11).
NATURES = {
    "fr": {"mesure": "Mesuré", "lu": "Lu", "simule": "Simulé", "tarif": "Publié", "hypothese": "Hypothèse", "a_chiffrer": "À chiffrer",
           "a_confirmer": "À confirmer"},
    "nl": {"mesure": "Gemeten", "lu": "Gelezen", "simule": "Gesimuleerd", "tarif": "Gepubliceerd", "hypothese": "Aanname", "a_chiffrer": "Nog te bepalen",
           "a_confirmer": "Te bevestigen"},
}

UNITES = {
    "fr": {"€/jour": "€/jour","MWh/an": "MWh/an", "MWh/periode": "MWh sur la période", "h/an": "h/an", "h/periode": "h sur la période",
           "episodes/an": "épisodes/an", "episodes/periode": "épisodes sur la période", "cycles/an": "cycles/an",
           "cycles/periode": "cycles sur la période", "€/an": "€/an", "€/periode": "€ sur la période", "ans": "ans",
           "kW/kWh": "kW par kWh", "€/kWh": "€/kWh installé", "h": "h", "kW": "kW", "kWh": "kWh", "€": "€", "%": "%", "": ""},
    "nl": {"€/jour": "€/dag", "MWh/an": "MWh/jaar", "MWh/periode": "MWh in de periode", "h/an": "uur/jaar", "h/periode": "uur in de periode",
           "episodes/an": "episodes/jaar", "episodes/periode": "episodes in de periode", "cycles/an": "cycli/jaar",
           "cycles/periode": "cycli in de periode", "€/an": "€/jaar", "€/periode": "€ in de periode", "ans": "jaar",
           "kW/kWh": "kW per kWh", "€/kWh": "€/kWh geïnstalleerd", "h": "uur", "kW": "kW", "kWh": "kWh", "€": "€", "%": "%", "": ""},
}

SOURCES = {
    "fr": {
        "": "",
        "src_tarifs": "{gestionnaire}, tarievenblad elektriciteit 2026 publié par l'ACM, feuilles 2a et 2b",
        "src_tarif_groupe": ("contrat de transport de groupe : aucune grille publiée, ses conditions (partage des coûts, limites) "
                             "restent à fixer avec le gestionnaire (communiqué ACM du 19/12/2025) ; les tarifs d'un raccordement "
                             "unique ne s'appliquent pas"),
        "src_centile5": "5e centile des quarts d'heure",
        # Revue d'Astra de 8569b5d : vrai aussi quand Q5 documente des valeurs estimées ou calculées.
        "src_lu": "valeur lue dans le profil ; une mesure directe n'est pas établie pour toutes les valeurs nécessaires, "
                  "voir « Qualité des données »",
        "src_utilisation": "énergie divisée par la pointe",
        "src_pas_kwmax": "pas de terme kWmax dans cette catégorie",
        "src_kwmax": "{kw_mois} kW-mois évités x {tarif} €/kW/mois, tarievenblad {gestionnaire} 2026",
        "src_puissance_decharge": "puissance de décharge nécessaire",
        "src_energie_dechargee": "énergie déchargée",
        "src_duree_batterie": "capacité utile divisée par la puissance",
        "src_prevision_parfaite": "le calcul suppose une prévision parfaite des pointes : borne optimiste",
        "src_moteur": "moteur cyclique vérifié (optimisation/moteur.py), puis simulation du profil",
        "src_nominale_puissance": "dimensionnée par la puissance : puissance / {crate} C, plus grand que utile / {dod}",
        "src_nominale_energie": "dimensionnée par l'énergie : utile / {dod}, plus grand que puissance / {crate} C",
        "src_invest_prix": "{bas} à {haut} €/kWh installé (voir hypothèses) x {nominale} kWh nominaux",
        "src_invest_prix_palier": ("{bas} €/kWh jusqu'à 100 kWh puis 350 €/kWh au-delà, à {haut} €/kWh, installé (voir hypothèses), "
                                   "x {nominale} kWh nominaux"),
        "src_invest_a_demander": "prix installé à demander à deux fournisseurs",
        "src_baisse_pic": "baisse de charge à obtenir au pic",
        "src_energie_deplacee": "énergie déplacée, non perdue",
        "src_plus_long_episode": "plus long épisode au-dessus du plafond",
        "src_confirmer_process": "à confirmer process par process avec l'exploitant",
        "src_invest_organisation": "organisation et éventuel pilotage automatique, sans matériel lourd",
        "src_puissance_couper": "puissance à couper au pic",
        "src_energie_non_consommee": "énergie non consommée",
        "src_invest_delestage": "commande de délestage, selon les usages",
        "src_cout_perte": "valeur de la production ou du confort perdus, à fournir par le site",
        "src_part_tdtr": "part de la charge utilisée moins de 15 % du temps",
        "src_energie_expo": "au plus, énergie à reporter si toutes les coupures tombent sur ces heures",
        "src_tdtr_85": "droit lié à la durée : 85 % des heures garanties (REG-004, ACM)",
        "src_niveau_15": "niveau dépassé pendant 15 % du temps au plus",
        "src_reg003_004": "REG-003, REG-004 (ACM)",
        "src_changement_contrat": "changement contractuel, sans matériel",
        "src_remise": "remise sur le tarif de transport à relever auprès du gestionnaire",
        "src_offre_puissance": "puissance que la batterie ou le décalage peuvent libérer à la demande",
        "src_appels": "dépend des appels du gestionnaire",
        "src_autonomie": "autonomie de la batterie à pleine puissance",
        "src_reg009": ("participation au congestiemanagement à partir de 1 MW (REG-009), et prévisions de transport à envoyer "
                       "chaque jour pour le lendemain (ACM, Overzicht congestiemaatregelen du 30/04/2025)"),
        "src_aucun_invest": "aucun en plus de la batterie ou du décalage",
        "src_remuneration": ("pas de tarif public : le site fixe lui-même le prix demandé dans son offre (ACM, Overzicht "
                             "congestiemaatregelen du 30/04/2025, §5.4). Le montant convenu dépend du client et reste "
                             "confidentiel (toelichting capaciteitsbeperkingscontract v3, art. 8). Formes prévues : forfait "
                             "mensuel, forfait par jour d'appel ou prix par MWh indexé sur le day-ahead, avec plancher et "
                             "plafond (contrat type Enexis, annexe 1) ; contrats types sur partnersinenergie.nl"),
        "src_retour_non_chiffre": "investissement ou économie non chiffrés",
        "src_retour_negatif": "la mesure n'abaisse pas le kWmax facturé sur l'année (économie négative) : pas de retour",
        "src_retour_simple": "retour simple, sans actualisation, sur la seule baisse du kWmax",
        "src_plafond_heures": "pointe sans ses {heures} heures les plus hautes",
        "src_plafond_heures_periode": ("pointe sans ses {heures} heures les plus hautes par an, ramenées à la durée du profil : "
                                       "{h_periode} h sur la période"),
        "src_retour_periode": "profil de moins d'un an : l'économie ne couvre pas une année, retour non calculé",
        "src_plafond_fiche": "plafond fixé dans la fiche",
        "dispo_batterie": "toute l'année, si l'état de charge est piloté",
        "dispo_decalage": "si les process concernés glissent de ± {fenetre} h",
        "dispo_ecretage": "seulement si la perte de production est acceptable",
        "dispo_contrat": "85 % des heures pour la part liée à la durée ; aucune garantie en non ferme",
        "dispo_offre": "selon le contrat signé avec le gestionnaire",
        "hyp_heures_ecretees": "plafond visé : la pointe, moins ses heures les plus hautes de l'année (nombre ci-contre)",
        "hyp_rendement_aller_retour": "batterie lithium-ion, ordre de grandeur courant, à remplacer par la fiche du fabricant",
        "hyp_profondeur_decharge": "part utilisable de la capacité nominale, à remplacer par la fiche du fabricant",
        "hyp_puissance_sur_capacite_max": "C-rate de décharge rapporté à la capacité nominale (1C : décharge en une heure), à remplacer par la fiche du fabricant",
        "hyp_prix_batterie_eur_kwh": ("prix indicatif installé publié par un installateur néerlandais (charge24.nl, 10/08/2026 : 400 à 700 €/kWh, "
                                      "vers 350 €/kWh au-delà de 100 kWh) ; repère public : marché Aquafin, TED 863953-2025, environ 385 €/kWh "
                                      "pour environ 2 MWh ; à remplacer par deux devis"),
        "hyp_fenetre_decalage_h": "écart maximal entre l'heure prévue et l'heure réelle d'un process décalé, à confirmer avec l'exploitant",
    },
    "nl": {
        "": "",
        "src_tarifs": "{gestionnaire}, tarievenblad elektriciteit 2026 gepubliceerd door de ACM, bladen 2a en 2b",
        "src_tarif_groupe": ("groepstransportovereenkomst: geen gepubliceerd tarief, de voorwaarden (kostenverdeling, grenzen) "
                             "moeten nog met de netbeheerder worden vastgelegd (persbericht ACM van 19-12-2025); de tarieven van "
                             "een enkele aansluiting gelden niet"),
        "src_centile5": "5e percentiel van de kwartierwaarden",
        "src_lu": "waarde uit het gelezen profiel; niet voor alle benodigde waarden is rechtstreekse meting vastgesteld, "
                  "zie ‘Kwaliteit van de gegevens’",
        "src_utilisation": "energie gedeeld door de piek",
        "src_pas_kwmax": "geen kWmax-tarief in deze categorie",
        "src_kwmax": "{kw_mois} vermeden kW-maanden x {tarif} €/kW/maand, tarievenblad {gestionnaire} 2026",
        "src_puissance_decharge": "benodigd ontlaadvermogen",
        "src_energie_dechargee": "ontladen energie",
        "src_duree_batterie": "bruikbare capaciteit gedeeld door het vermogen",
        "src_prevision_parfaite": "de berekening veronderstelt een perfecte piekvoorspelling: optimistische grens",
        "src_moteur": "gecontroleerd cyclisch optimalisatiemodel, daarna simulatie van het profiel",
        "src_nominale_puissance": "gedimensioneerd op vermogen: vermogen / {crate} C, groter dan bruikbaar / {dod}",
        "src_nominale_energie": "gedimensioneerd op energie: bruikbaar / {dod}, groter dan vermogen / {crate} C",
        "src_invest_prix": "{bas} tot {haut} €/kWh geïnstalleerd (zie aannames) x {nominale} kWh nominaal",
        "src_invest_prix_palier": ("{bas} €/kWh tot 100 kWh en daarboven 350 €/kWh, tot {haut} €/kWh, geïnstalleerd (zie aannames), "
                                   "x {nominale} kWh nominaal"),
        "src_invest_a_demander": "geïnstalleerde prijs opvragen bij twee leveranciers",
        "src_baisse_pic": "benodigde verlaging op het piekmoment",
        "src_energie_deplacee": "verschoven energie, niet verloren",
        "src_plus_long_episode": "langste episode boven de grens",
        "src_confirmer_process": "per proces te bevestigen met de exploitant",
        "src_invest_organisation": "organisatie en eventueel automatische sturing, geen zware hardware",
        "src_puissance_couper": "af te schakelen vermogen op het piekmoment",
        "src_energie_non_consommee": "niet verbruikte energie",
        "src_invest_delestage": "afschakelsturing, afhankelijk van de verbruikers",
        "src_cout_perte": "waarde van gemiste productie of comfort, aan te leveren door de locatie",
        "src_part_tdtr": "deel van de belasting dat minder dan 15 % van de tijd wordt gebruikt",
        "src_energie_expo": "hoogstens, te verschuiven energie als alle beperkingen op die uren vallen",
        "src_tdtr_85": "tijdsduurgebonden recht: 85 % van de uren gegarandeerd (REG-004, ACM)",
        "src_niveau_15": "niveau dat hoogstens 15 % van de tijd wordt overschreden",
        "src_reg003_004": "REG-003, REG-004 (ACM)",
        "src_changement_contrat": "contractwijziging, zonder hardware",
        "src_remise": "korting op het transporttarief op te vragen bij de netbeheerder",
        "src_offre_puissance": "vermogen dat de batterij of het verschuiven op verzoek kunnen vrijmaken",
        "src_appels": "afhankelijk van de afroepen van de netbeheerder",
        "src_autonomie": "autonomie van de batterij op vol vermogen",
        "src_reg009": ("deelname aan congestiemanagement vanaf 1 MW (REG-009), en dagelijks prognosegegevens voor de volgende dag "
                       "delen (ACM, Overzicht congestiemaatregelen van 30/04/2025)"),
        "src_aucun_invest": "geen, bovenop de batterij of het verschuiven",
        "src_remuneration": ("geen openbaar tarief: de locatie bepaalt zelf de gevraagde vergoeding in haar bieding (ACM, Overzicht "
                             "congestiemaatregelen van 30/04/2025, §5.4). De overeengekomen vergoeding verschilt per klant en is "
                             "vertrouwelijk (toelichting capaciteitsbeperkingscontract v3, art. 8). Mogelijke vormen: vaste "
                             "vergoeding per maand, afroepvergoeding per dag of vergoeding per MWh op basis van de day-aheadprijs, "
                             "met minimum en maximum (modelcontract Enexis, bijlage 1); standaardcontracten op partnersinenergie.nl"),
        "src_retour_non_chiffre": "investering of besparing niet bepaald",
        "src_retour_negatif": "de maatregel verlaagt de gefactureerde kWmax over het jaar niet (negatieve besparing): geen terugverdientijd",
        "src_retour_simple": "eenvoudige terugverdientijd, zonder discontering, alleen op de kWmax-besparing",
        "src_plafond_heures": "piek zonder de {heures} hoogste uren",
        "src_plafond_heures_periode": ("piek zonder de {heures} hoogste uren per jaar, omgerekend naar de duur van het profiel: "
                                       "{h_periode} uur in de periode"),
        "src_retour_periode": "profiel korter dan een jaar: de besparing dekt geen jaar, terugverdientijd niet berekend",
        "src_plafond_fiche": "grens vastgelegd in de fiche",
        "dispo_batterie": "het hele jaar, als de laadtoestand wordt gestuurd",
        "dispo_decalage": "als de betrokken processen ± {fenetre} uur kunnen schuiven",
        "dispo_ecretage": "alleen als het productieverlies aanvaardbaar is",
        "dispo_contrat": "85 % van de uren voor het tijdsduurgebonden deel; geen garantie bij niet-vast",
        "dispo_offre": "volgens het contract met de netbeheerder",
        "hyp_heures_ecretees": "beoogde grens: de piek zonder de hoogste uren van het jaar (aantal hiernaast)",
        "hyp_rendement_aller_retour": "lithium-ionbatterij, gangbare orde van grootte, te vervangen door de fabrieksgegevens",
        "hyp_profondeur_decharge": "bruikbaar deel van de nominale capaciteit, te vervangen door de fabrieksgegevens",
        "hyp_puissance_sur_capacite_max": "ontlaad-C-rate ten opzichte van de nominale capaciteit (1C: ontladen in een uur), te vervangen door de fabrieksgegevens",
        "hyp_prix_batterie_eur_kwh": ("indicatieve geïnstalleerde prijs van een Nederlandse installateur (charge24.nl, 10/08/2026: € 400 tot € 700 per kWh, "
                                      "richting € 350 per kWh boven 100 kWh); openbaar referentiepunt: aanbesteding Aquafin, TED 863953-2025, circa "
                                      "€ 385 per kWh voor circa 2 MWh; te vervangen door twee offertes"),
        "hyp_fenetre_decalage_h": "maximaal verschil tussen gepland en werkelijk tijdstip van een verschoven proces, te bevestigen met de exploitant",
    },
}

T = {
    "fr": {
        "titre": "Scan de flexibilité",
        "exemple": "Exemple sur données publiques réelles, pas un dossier client.",
        "nom": "Site", "secteur": "Secteur", "gestionnaire": "Gestionnaire de réseau", "source_profil": "Source du profil",
        "periode": "Période", "quarts": "Quarts d'heure", "energie": "Consommation", "pointe": "Pointe",
        "moyenne": "Puissance moyenne", "utilisation": "Heures d'utilisation",
        "facteur": "Facteur de charge", "capacite": "Capacité de raccordement",
        "categorie": "Catégorie tarifaire", "tarif_kw": "Tarif kW contracté", "tarif_kwmax": "Tarif kWmax",
        "non_fourni": "non fourni", "estimee": "estimée d'après la puissance", "par_an": "€/kW/an", "par_mois": "€/kW/mois", "eco_par_an": "par an", "eco_periode": "sur la période",
        "cat_LS": "LS", "cat_TRAFO_MS_LS": "Trafo MS/LS", "cat_MS": "MS (1-20 kV)", "cat_TRAFO_HS_TS_MS": "Trafo HS+TS/MS",
        "cat_GROUPE": "Contrat de transport de groupe (grille à fixer avec le gestionnaire)",
        "cat_MS_TRANSPORT": "MS (1-20 kV) transport",
        "afname": "Zone, sens prélèvement (afname)", "invoeding": "Zone, sens injection (teruglevering)",
        "date_carte": "Date de lecture de la carte", "liberation": "Levée de congestion annoncée",
        "congestion_vide": "Statut de zone à relever sur capaciteitskaart.netbeheernederland.nl, à l'adresse du site, dans les deux sens.",
        "p_annuel": "Profil annuel : maximum et moyenne de chaque jour", "p_mensuel": "Profil mensuel",
        "p_hebdo": "Semaine type (moyenne de chaque quart d'heure) et semaine de la pointe",
        "p_jour": "Journée type : jours ouvrés, week-ends, jour de la pointe",
        "p_monotone": "Courbe monotone : puissance atteinte ou dépassée pendant x heures",
        "mois": "Mois", "max": "Maximum", "moy": "Moyenne", "mwh": "MWh",
        "semaine_type": "semaine type", "semaine_pointe": "semaine de la pointe", "ouvre": "jours ouvrés",
        "repos": "week-ends", "jour_pointe": "jour de la pointe", "max_jour": "maximum du jour", "moy_jour": "moyenne du jour",
        "plafond": "plafond visé", "avant": "avant", "apres": "après", "courbe": "puissance",
        "plafond_txt": ("Plafond visé : {plafond} kW, soit {liberes} kW sous la pointe de {pointe} kW. La charge le dépasse "
                        "pendant {heures} h, en {episodes} épisodes, le plus long de {duree} h, pour {energie} kWh au total."),
        "grandeur": "Grandeur", "valeur": "Valeur", "nature": "Nature", "source": "Source ou hypothèse",
        "flex_kw": "Puissance flexible", "energie_mwh_an": "Énergie concernée", "duree_h": "Durée",
        "disponibilite": "Disponibilité", "investissement_eur": "Investissement", "economie": "Économie de transport (kWmax)",
        "retour_ans": "Retour sur investissement", "capacite_utile_kwh": "Capacité utile nécessaire", "capacite_nominale_kwh": "Capacité nominale",
        "cycles_equivalents_an": "Cycles équivalents (capacité utile nécessaire)", "episodes": "Épisodes", "heures_an": "Heures concernées",
        "part_energie": "Part de la consommation", "cout_perte": "Coût de la production perdue", "remise": "Remise tarifaire",
        "remise_eur_an": "Remise si la part au-dessus du plafond passe en volledig variabel",
        "niveau_ferme_kw": "Niveau dépassé 15 % du temps au plus", "obligation_1mw": "Participation obligatoire (1 MW)",
        "remuneration": "Rémunération",
        "o_batterie": "Batterie", "o_decalage": "Décalage d'horaires", "o_ecretage": "Écrêtage (délestage)",
        "o_contrat": "Contrat flexible : non ferme ou lié à la durée", "o_offre_gestionnaire": "Flexibilité offerte au gestionnaire",
        "principe_batterie": ("La batterie se charge sous le plafond et se décharge au-dessus. Dimensionnement cyclique vérifié "
                              "par le moteur d'optimisation, puis simulation quart d'heure par quart d'heure."),
        "principe_decalage": ("La part au-dessus du plafond est déplacée vers les quarts d'heure les plus proches restés sous le "
                              "plafond, dans une fenêtre de ± {fenetre} h. L'énergie consommée ne change pas."),
        "principe_ecretage": "Les usages au-dessus du plafond sont réduits ou arrêtés. L'énergie coupée n'est pas rattrapée.",
        "principe_contrat": ("Trois droits de transport alternatifs existent (ACM). Non ferme (volledig variabel), sur tous les réseaux : "
                             "transport seulement quand la capacité suffit, annoncé la veille. Par blocs horaires (tijdsblokgebonden), "
                             "sur les réseaux régionaux : transport dans des créneaux convenus. Lié à la durée (tijdsduurgebonden), "
                             "sur le réseau haute tension de TenneT : au moins 85 % des heures de l'année. On lit ici quelle part "
                             "de la charge pourrait vivre avec ces droits."),
        "principe_offre_gestionnaire": ("Le site met à disposition du gestionnaire une baisse de charge à la demande "
                                        "(congestiemanagement, contrat de limitation de capacité, plateforme GOPACS)."),
        "semaine_avant_apres": "Semaine de la pointe, avant et après",
        "niveaux": "Durée au-dessus de chaque niveau", "niveau": "Niveau", "part_pointe": "Part de la pointe",
        "heures_dessus": "Heures au-dessus", "energie_dessus": "Énergie au-dessus",
        "option": "Option", "faisable": "Faisable sur la période", "oui": "oui", "non": "non", "a_voir": "à voir",
        "reco_intro": "Ordre d'examen conseillé, tiré des chiffres ci-dessus. Chaque ligne dit sa condition.",
        "reco_decalage": ("{flex} kW à déplacer lors de {episodes} épisodes, le plus long de {duree} h, sans énergie "
                          "perdue. Condition : l'exploitant confirme que les process concernés peuvent glisser de ± {fenetre} h."),
        "reco_decalage_partiel": ("Dans une fenêtre de ± {fenetre} h, seule une part de {part} de l'énergie au-dessus du plafond "
                                  "trouve de la place : le décalage seul ne suffit pas."),
        "reco_ecretage": ("{mwh} MWh ({pct} de la consommation), sur {heures} h. Condition : cette perte de production est "
                          "acceptable pour le site."),
        "reco_ecretage_couteux": ("{mwh} MWh ({pct} de la consommation) seraient perdus : à ne retenir que si cette production "
                                  "n'a pas de valeur."),
        "reco_batterie_chiffree": "Retour estimé entre {ans_bas} et {ans_haut} ans sur la seule baisse du kWmax.",
        "reco_batterie_longue": ("La baisse du kWmax rapporte {eco} € {par_an}, le retour dépasse {ans_bas} ans. Son intérêt ici serait la "
                                 "marge de {flex} kW libérée pour croître sans attendre le réseau, pas l'économie tarifaire."),
        "reco_batterie_a_chiffrer": ("{nominale} kWh nominaux pour {flex} kW, dimensionnée par {dim}. Prix installé à demander à deux "
                                     "fournisseurs ; la baisse du kWmax rapporterait {eco} € {par_an}."),
        "reco_batterie_impossible": "Aucune batterie du modèle ne tient ce plafond sur la période : voir la raison donnée en 5.1.",
        "reco_contrat": ("La charge ne dépasse {niveau} kW que 15 % du temps. Au-dessus de ce niveau, {flex} kW pourraient relever "
                         "d'un droit alternatif : non ferme ou par blocs horaires sur un réseau régional, lié à la durée sur le "
                         "réseau TenneT, si le gestionnaire le propose ; la remise est à demander."),
        "reco_offre_obligatoire": ("Transport contracté d'au moins 1 MW : le site doit pouvoir participer au congestiemanagement "
                                   "(REG-009). Préparer une offre de {flex} kW."),
        "reco_offre_si_annoncee": ("Transport contracté d'au moins 1 MW : la participation au congestiemanagement devient obligatoire "
                                   "si le gestionnaire l'annonce dans une zone de congestion, à vérifier auprès de lui. {flex} kW "
                                   "pourraient être offerts ; la rémunération se négocie."),
        "reco_offre_groupe": ("Participation au congestiemanagement : à évaluer raccordement par raccordement (1 MW ou plus). "
                              "{flex} kW pourraient être offerts ; la rémunération se négocie."),
        "reco_offre_a_verifier": ("Participation obligatoire au-delà de 1 MW à vérifier : le GTV n'est pas fourni. {flex} kW pourraient "
                                  "être offerts au gestionnaire ; la rémunération se négocie."),
        "reco_batterie_sans_retour": ("{nominale} kWh nominaux pour {flex} kW, dimensionnée par {dim}. Aucun retour calculable ici "
                                      "(pas d'économie de transport à compter, ou profil de moins d'un an) : son intérêt serait la capacité."),
        "reco_offre_volontaire": ("Offrir {flex} kW au gestionnaire reste volontaire ici. La rémunération n'est pas publiée d'avance, elle "
                                  "se négocie."),
        "dim_puissance": "la puissance", "dim_energie": "l'énergie", "dimtab_puissance": "puissance", "dimtab_energie": "énergie",
        "hyp": "Hypothèse", "pourquoi": "Pourquoi cette valeur",
        "genere": "Produit le {jour} par Contingency, {version}.",
    },
    "nl": {
        "titre": "Flexibiliteitsscan",
        "exemple": "Voorbeeld op echte openbare data, geen klantdossier.",
        "nom": "Locatie", "secteur": "Sector", "gestionnaire": "Netbeheerder", "source_profil": "Bron van het profiel",
        "periode": "Periode", "quarts": "Kwartierwaarden", "energie": "Verbruik", "pointe": "Piek",
        "moyenne": "Gemiddeld vermogen", "utilisation": "Benuttingsduur",
        "facteur": "Belastingsgraad", "capacite": "Aansluitcapaciteit",
        "categorie": "Tariefcategorie", "tarif_kw": "Tarief kW gecontracteerd", "tarif_kwmax": "Tarief kWmax",
        "non_fourni": "niet aangeleverd", "estimee": "geschat op basis van het vermogen", "par_an": "€/kW/jaar", "par_mois": "€/kW/maand", "eco_par_an": "per jaar", "eco_periode": "in de periode",
        "cat_LS": "LS", "cat_TRAFO_MS_LS": "Trafo MS/LS", "cat_MS": "MS (1-20 kV)", "cat_TRAFO_HS_TS_MS": "Trafo HS+TS/MS",
        "cat_GROUPE": "Groepstransportovereenkomst (tarief af te spreken met de netbeheerder)",
        "cat_MS_TRANSPORT": "MS (1-20 kV) transport",
        "afname": "Gebied, afname", "invoeding": "Gebied, teruglevering",
        "date_carte": "Datum kaart geraadpleegd", "liberation": "Aangekondigde opheffing congestie",
        "congestion_vide": "Status op te zoeken op capaciteitskaart.netbeheernederland.nl, op het adres van de locatie, in beide richtingen.",
        "p_annuel": "Jaarprofiel: maximum en gemiddelde per dag", "p_mensuel": "Maandprofiel",
        "p_hebdo": "Gemiddelde week (per kwartier) en de week van de piek",
        "p_jour": "Dagprofiel: werkdagen, weekend, dag van de piek",
        "p_monotone": "Belastingduurkromme: vermogen dat x uur wordt bereikt of overschreden",
        "mois": "Maand", "max": "Maximum", "moy": "Gemiddeld", "mwh": "MWh",
        "semaine_type": "gemiddelde week", "semaine_pointe": "week van de piek", "ouvre": "werkdagen",
        "repos": "weekend", "jour_pointe": "dag van de piek", "max_jour": "dagmaximum", "moy_jour": "daggemiddelde",
        "plafond": "beoogde grens", "avant": "voor", "apres": "na", "courbe": "vermogen",
        "plafond_txt": ("Beoogde grens: {plafond} kW, dus {liberes} kW onder de piek van {pointe} kW. De belasting ligt erboven "
                        "gedurende {heures} uur, in {episodes} episodes, de langste {duree} uur, samen {energie} kWh."),
        "grandeur": "Grootheid", "valeur": "Waarde", "nature": "Aard", "source": "Bron of aanname",
        "flex_kw": "Flexibel vermogen", "energie_mwh_an": "Betrokken energie", "duree_h": "Duur",
        "disponibilite": "Beschikbaarheid", "investissement_eur": "Investering", "economie": "Besparing transport (kWmax)",
        "retour_ans": "Terugverdientijd", "capacite_utile_kwh": "Benodigde bruikbare capaciteit", "capacite_nominale_kwh": "Nominale capaciteit",
        "cycles_equivalents_an": "Equivalente cycli (benodigde bruikbare capaciteit)", "episodes": "Episodes", "heures_an": "Betrokken uren",
        "part_energie": "Aandeel van het verbruik", "cout_perte": "Kosten van gemiste productie", "remise": "Tariefkorting",
        "remise_eur_an": "Korting als het deel boven de beoogde grens volledig variabel wordt",
        "niveau_ferme_kw": "Niveau hoogstens 15 % van de tijd overschreden", "obligation_1mw": "Verplichte deelname (1 MW)",
        "remuneration": "Vergoeding",
        "o_batterie": "Batterij", "o_decalage": "Verschuiven van processen", "o_ecretage": "Afschakelen van verbruik",
        "o_contrat": "Flexibel contract: niet-vast of tijdsduurgebonden", "o_offre_gestionnaire": "Flexibiliteit aanbieden aan de netbeheerder",
        "principe_batterie": ("De batterij laadt onder de grens en ontlaadt erboven. Cyclische dimensionering gecontroleerd door de "
                              "optimalisatiemotor, daarna kwartier voor kwartier gesimuleerd."),
        "principe_decalage": ("Het deel boven de grens wordt verschoven naar de dichtstbijzijnde kwartieren onder de grens, binnen "
                              "± {fenetre} uur. Het verbruik zelf verandert niet."),
        "principe_ecretage": "Verbruik boven de grens wordt verminderd of gestopt. Die energie wordt niet ingehaald.",
        "principe_contrat": ("Er bestaan drie alternatieve transportrechten (ACM). Volledig variabel, op alle netten: transport alleen "
                             "als er capaciteit is, een dag van tevoren aangekondigd. Tijdsblokgebonden, op regionale netten: transport "
                             "binnen afgesproken tijdsblokken. Tijdsduurgebonden, op het hoogspanningsnet van TenneT: minstens 85 % "
                             "van de uren per jaar. Hier staat welk deel van de belasting onder deze rechten zou kunnen vallen."),
        "principe_offre_gestionnaire": ("De locatie stelt op verzoek een verlaging van de belasting beschikbaar aan de netbeheerder "
                                        "(congestiemanagement, capaciteitsbeperkingscontract, GOPACS)."),
        "semaine_avant_apres": "Week van de piek, voor en na",
        "niveaux": "Duur boven elk niveau", "niveau": "Niveau", "part_pointe": "Deel van de piek",
        "heures_dessus": "Uren erboven", "energie_dessus": "Energie erboven",
        "option": "Optie", "faisable": "Haalbaar over de periode", "oui": "ja", "non": "nee", "a_voir": "te bekijken",
        "reco_intro": "Aanbevolen volgorde, afgeleid uit de cijfers hierboven. Elke regel noemt zijn voorwaarde.",
        "reco_decalage": ("{flex} kW verplaatsen tijdens {episodes} episodes, de langste {duree} uur, zonder energieverlies. "
                          "Voorwaarde: de exploitant bevestigt dat de betrokken processen ± {fenetre} uur kunnen schuiven."),
        "reco_decalage_partiel": ("Binnen ± {fenetre} uur vindt maar {part} van de energie boven de grens een plek: verschuiven alleen "
                                  "is niet genoeg."),
        "reco_ecretage": ("{mwh} MWh ({pct} van het verbruik), gedurende {heures} uur. Voorwaarde: dit productieverlies is aanvaardbaar."),
        "reco_ecretage_couteux": ("{mwh} MWh ({pct} van het verbruik) zou verloren gaan: alleen als die productie geen waarde heeft."),
        "reco_batterie_chiffree": "Geschatte terugverdientijd tussen {ans_bas} en {ans_haut} jaar op basis van alleen de kWmax-besparing.",
        "reco_batterie_longue": ("De kWmax-besparing levert {eco} € {par_an} op, de terugverdientijd is meer dan {ans_bas} jaar. De waarde "
                                 "zit hier in de {flex} kW ruimte om te groeien zonder op het net te wachten, niet in de tariefbesparing."),
        "reco_batterie_a_chiffrer": ("{nominale} kWh nominaal voor {flex} kW, gedimensioneerd op {dim}. Prijs bij twee leveranciers "
                                     "opvragen; de kWmax-besparing zou {eco} € {par_an} opleveren."),
        "reco_batterie_impossible": "Geen batterij in dit model houdt deze grens over de periode: zie de reden in 5.1.",
        "reco_contrat": ("De belasting ligt maar 15 % van de tijd boven {niveau} kW. Boven dat niveau kan {flex} kW onder een "
                         "alternatief recht vallen: volledig variabel of tijdsblokgebonden op een regionaal net, tijdsduurgebonden op "
                         "het TenneT-net, als de netbeheerder dat aanbiedt; de korting moet worden opgevraagd."),
        "reco_offre_obligatoire": ("Gecontracteerd transport van minstens 1 MW: de locatie moet kunnen deelnemen aan congestiemanagement "
                                   "(REG-009). Een aanbod van {flex} kW voorbereiden."),
        "reco_offre_si_annoncee": ("Gecontracteerd transport van minstens 1 MW: deelname aan congestiemanagement wordt verplicht "
                                   "als de netbeheerder die in een congestiegebied aankondigt; na te vragen bij de netbeheerder. "
                                   "{flex} kW zou kunnen worden aangeboden; de vergoeding is onderhandelbaar."),
        "reco_offre_groupe": ("Deelname aan congestiemanagement: per aansluiting te beoordelen (1 MW of meer). {flex} kW zou "
                              "kunnen worden aangeboden; de vergoeding is onderhandelbaar."),
        "reco_offre_a_verifier": ("Verplichte deelname boven 1 MW te controleren: het GTV is niet aangeleverd. {flex} kW zou aan de "
                                  "netbeheerder kunnen worden aangeboden; over de vergoeding wordt onderhandeld."),
        "reco_batterie_sans_retour": ("{nominale} kWh nominaal voor {flex} kW, gedimensioneerd op {dim}. Hier is geen terugverdientijd te "
                                      "berekenen (geen transportbesparing, of een profiel korter dan een jaar): de waarde zit in de capaciteit."),
        "reco_offre_volontaire": ("{flex} kW aanbieden aan de netbeheerder is hier vrijwillig. De vergoeding wordt niet vooraf gepubliceerd, "
                                  "daarover wordt onderhandeld."),
        "dim_puissance": "vermogen", "dim_energie": "energie", "dimtab_puissance": "vermogen", "dimtab_energie": "energie",
        "hyp": "Aanname", "pourquoi": "Waarom deze waarde",
        "genere": "Gemaakt op {jour} door Contingency, {version}.",
    },
}

# Structure Flex-e (bijlage 4.12.1) : textes des articles 1 à 7, vérifiés le 27/09/2026 (docs/recherche/FLEXSCAN-FORMAT.md).
SOURCES["fr"].update({
    "src_acm_overzicht": "ACM, Overzicht en inzicht congestiemaatregelen, mise à jour du 30/04/2025, §2.1 à 2.3",
    "src_rainflow": "comptage rainflow (ASTM E1049-85) de l'énergie stockée simulée, en part de la capacité nominale",
    "src_cycles_arbitrage": "un cycle par jour de la capacité utilisable installée, capacité nominale x profondeur de décharge (borne haute de l'arbitrage)",
    "src_garantie_fabricant": ("garantie du fabricant à fournir (cycles, profondeur, années, capacité restante en fin de garantie) : "
                               "aucun taux de vieillissement n'est supposé"),
    "src_duree_garantie_calendrier": ("garantie {garantie} : {annees} ans, ou {cycles} cycles à {profondeur} % ; au rythme simulé, "
                                      "c'est la durée en années qui limite"),
    "src_duree_garantie_cycles": ("garantie {garantie} : {cycles} cycles à {profondeur} %, ou {annees} ans ; au rythme simulé, ce sont "
                                  "les cycles qui limitent (usure comptée en énergie cumulée)"),
    "src_fin_vie": "capacité nominale divisée par la capacité restante garantie en fin de garantie ({etat} %)",
    "src_duree_courte": "profil de moins d'un an : les cycles ne sont pas ramenés à l'année, la durée de vie n'est pas calculée",
    "src_acm_faq_atr": ("ACM, Overzicht en inzicht congestiemaatregelen, mise à jour du 30/04/2025, §2.1 à 2.3 ; Netbeheer "
                        "Nederland, FAQ alternatieve transportrechten, exemples au tarif Liander 2024"),
    "src_remise_nfa": ("{kw} kW entre le plafond visé ({plafond} kW), que la batterie ou le décalage tiennent, et le GTV ({gtv} kW), "
                       "passés en volledig variabel : pas de terme kW contracté sur cette part, kWmax et kWh restent dus "
                       "(Tarievencode 2026, art. 3.14, Stcrt 2026, 4090 ; FAQ alternatieve transportrechten de Netbeheer Nederland) "
                       "x {tarif} €/kW/an, tarievenblad {gestionnaire} 2026. Possible seulement en zone avec "
                       "vooraankondiging congestie. Le droit ferme cédé ne revient que par une nouvelle demande, placée dans la file "
                       "d'attente en zone saturée : un GTV déclaré plus bas réduit le droit ferme lui-même, pas seulement le tarif "
                       "(CBb, NorthC contre ACM, 23/06/2026). Ce montant reste donc à part de l'économie. Le Reststroom est encore "
                       "en développement chez Liander et ses conditions à l'étude chez Enexis (pages du 27/09/2026) : une possibilité "
                       "de droit, pas encore une offre disponible."),
    "src_remise_sans_gtv": "GTV non fourni : la remise porte sur la part du GTV au-dessus du plafond visé",
    "src_remise_sans_mesure": ("aucune mesure simulée (batterie, décalage) ne tient le plafond visé de {plafond} kW : passer la part "
                               "au-dessus en volledig variabel exposerait le site à des coupures ; remise non chiffrée"),
    "src_pas_kw_contrat": "pas de terme kW contracté dans cette catégorie tarifaire",
    "src_remise_gtv_sous_plafond": "GTV ({gtv} kW) au niveau du plafond visé ({plafond} kW) ou dessous : aucune part à passer en variable",
    "preavis_contrat": "limitations annoncées au plus tard la veille",
    "src_arbitrage": ("borne haute : un cycle par jour sur {jours} jours de prix day-ahead NL 2025 (Energy-Charts, CC BY 4.0, "
                      "Bundesnetzagentur | SMARD.de), prévision parfaite, contrat de fourniture indexé sur le day-ahead, "
                      "hors taxes et sans conflit avec l'écrêtage"),
    "src_part_charge_pic": "puissance à déplacer divisée par la pointe : à comparer à ce que les process peuvent décaler",
    "src_arbitrage_absent": "prix day-ahead non disponibles (docs/donnees/prix-day-ahead-nl-2025.csv absent)",
    "src_retour_arbitrage": "retour simple sur la baisse du kWmax plus l'arbitrage théorique : délai le plus court possible",
    "src_autonomie_dimensionnee": "capacité nominale x {dod} de profondeur de décharge, divisée par la puissance",
    "part_alternative": "part de la charge qui pourrait passer sous un droit alternatif, pas une flexibilité technique",
    "src_plafond_palier": "pointe plate, atteinte plus de {heures} heures : premier palier sous la pointe",
    "src_limite_gtv": "transport contracté (GTV) déclaré : la limite à ne pas dépasser sans nouvelle demande",
    "src_limite_pointe": "GTV non fourni : la pointe actuelle sert de limite, ne pas la dépasser évite toute nouvelle demande",
    "src_croissance": "pointe actuelle moins plafond tenu, plus la marge libre sous le GTV si elle est connue",
    "src_flex_e": "RVO, pages Flex-e flexibiliteitsscan et flexibiliteitsmaatregelen, état au 20/09/2026",
    "src_acm_sanction": "ACM, Overzicht congestiemaatregelen (30/04/2025), p. 15 : 120 € par MW de GTV ({mw} MW) et par jour sans offre de contrat de limitation",
    "src_acm_sanction_sans_objet": "transport contracté sous 1 MW : pas d'obligation, donc pas de montant dû",
    "src_acm_sanction_si_annoncee": ("dû seulement si l'obligation est annoncée puis non respectée : 120 € par MW de GTV et par jour, "
                                     "soit {montant} € par jour pour {mw} MW (ACM, Overzicht congestiemaatregelen, p. 15)"),
    "src_acm_sanction_non_annoncee": "obligation non annoncée : pas de montant dû",
    "src_acm_sanction_groupe": "montant dû éventuel par raccordement, pas pour le groupe : à évaluer site par site",
    "src_reg009_a_verifier": ("au-delà de 1 MW, l'obligation ne naît que si le gestionnaire la déclenche dans une zone de congestion "
                              "(« Netbeheerders kunnen de deelnameplicht inzetten in een congestiegebied », ACM, Overzicht "
                              "congestiemaatregelen, p. 10) : à vérifier auprès du gestionnaire"),
    "src_reg009_non_annoncee": ("le gestionnaire n'a pas annoncé l'obligation de participer (fiche) : pas d'obligation aujourd'hui, "
                                "elle peut l'être en zone de congestion"),
    "src_reg009_groupe": ("l'obligation de participer vise un raccordement de 1 MW ou plus (ACM, Overzicht congestiemaatregelen, "
                          "p. 10), pas la somme d'un groupe : à évaluer site par site"),
    "src_gotork_groupe": ("GOTORK (Netcode elektriciteit, art. 7.13) vaut par raccordement : ses seuils (50 % du GTV ou 1 MW "
                          "inutilisés sur 12 mois) s'évaluent site par site, avec le GTV et la pointe de chacun, jamais sur la "
                          "somme d'un groupe."),
    "hyp_fiche_sans_source": "valeur fixée dans la fiche, sans source donnée",
    "src_marge_gtv": "GTV {gtv} kW moins pointe mesurée {pointe} kW",
    "src_acm_gotork": ("GOTORK (Netcode elektriciteit, art. 7.13, décision ACM du 16/04/2024, en vigueur le 26/04/2024) : en zone "
                       "de congestion, en moyenne tension ou plus, le gestionnaire peut baisser le GTV ferme si, sur les 12 derniers "
                       "mois, au plus 50 % en a servi ou si 1 MW ou plus est resté inutilisé (10 MW à partir de 110 kV). Ce n'est "
                       "pas automatique : il le notifie par écrit, se concerte avec le client et ne reprend que la part qui ne "
                       "servira pas dans un délai d'au moins 12 mois. D'après la pointe mesurée, ce site atteint l'un de ces seuils : "
                       "c'est un risque à préparer, pas une perte certaine. Un projet de croissance documenté, comme le scénario "
                       "de ce scan, sert à le défendre."),
    "src_acm_gotork_sous_seuil": ("GOTORK (Netcode elektriciteit, art. 7.13, en vigueur le 26/04/2024) vise un GTV dont au plus 50 % a "
                                  "servi sur 12 mois, ou dont 1 MW ou plus reste inutilisé (10 MW à partir de 110 kV). D'après la "
                                  "pointe mesurée, ce site n'atteint aucun de ces seuils : selon ces règles, sa marge n'est pas "
                                  "exposée à une reprise."),
    "src_acm_depassement": ("ACM (en vigueur le 26/04/2025) : en zone de congestion, un dépassement du GTV n'augmente plus le "
                            "contrat automatiquement ; il faut une nouvelle demande. Le site dépasse déjà son contrat."),
    "src_acm_limite": ("ACM (en vigueur le 26/04/2025) : en zone de congestion, un dépassement du GTV n'augmente plus le contrat "
                       "automatiquement. La pointe du site atteint exactement son GTV : aucune marge."),
    "remise_contrat": ("tarif de réseau environ 50 % plus bas en non ferme (tous réseaux) et en lié à la durée (TenneT) ; "
                       "en blocs horaires (réseaux régionaux), le terme kW contracté baisse au prorata des heures hors "
                       "créneau, les autres termes restent dus : -33 % sur la facture mensuelle de transport dans l'exemple "
                       "officiel à 10 MW (créneau 22 h à 6 h), -17 % à 2 MW ; droit ferme et droit alternatif se combinent "
                       "sur un même raccordement"),
    "gestionnaire_defaut": "gestionnaire non fourni : grille Liander par défaut",
    "gestionnaire_inconnu": "gestionnaire sans grille connue ici : grille Liander par défaut, à remplacer par la sienne",
    "src_a_completer": "à compléter par l'entreprise ou l'energieadviseur",
    "src_fiche": "déclaré par l'entreprise",
    "src_ato": "à lire dans l'ATO (aansluit- en transportovereenkomst)",
    "src_activite_estimee": "estimé d'après le profil : quarts d'heure au-dessus de {seuil} kW, soit la charge de base plus {part} de l'écart jusqu'à la pointe",
    "src_horaires_estimes": "estimés d'après la semaine type : moyenne au-dessus de {seuil} kW",
    "src_visite": "à décrire lors de la visite du site, exigée par Flex-e",
    "src_preference": "à recueillir auprès de l'entreprise",
    "activation_batterie": "moins d'une minute, pilotage automatique",
    "src_activation_batterie": "ordre de grandeur des onduleurs de batterie, à confirmer par le fabricant",
    "src_activation_process": "selon le process (démarrage, arrêt, sécurité), à décrire avec l'exploitant",
    "src_activation_usages": "selon les usages coupés, à décrire avec l'exploitant",
    "src_activation_contrat": "délai d'annonce des limitations, fixé par le contrat",
    "src_activation_offre": "délai d'activation demandé par le gestionnaire, fixé par l'offre ou le contrat",
})
SOURCES["nl"].update({
    "src_acm_overzicht": "ACM, Overzicht en inzicht congestiemaatregelen, update van 30/04/2025, §2.1 tot 2.3",
    "src_rainflow": "rainflow-telling (ASTM E1049-85) van de gesimuleerde opgeslagen energie, als deel van de nominale capaciteit",
    "src_cycles_arbitrage": "één cyclus per dag van de geïnstalleerde bruikbare capaciteit, nominale capaciteit x ontlaaddiepte (bovengrens van arbitrage)",
    "src_garantie_fabricant": ("fabrieksgarantie aan te leveren (cycli, diepte, jaren, resterende capaciteit aan het einde van de "
                               "garantie): er wordt geen verouderingssnelheid aangenomen"),
    "src_duree_garantie_calendrier": ("garantie {garantie}: {annees} jaar, of {cycles} cycli bij {profondeur} %; bij het gesimuleerde "
                                      "gebruik is de looptijd in jaren de beperkende factor"),
    "src_duree_garantie_cycles": ("garantie {garantie}: {cycles} cycli bij {profondeur} %, of {annees} jaar; bij het gesimuleerde gebruik "
                                  "zijn de cycli de beperkende factor (slijtage geteld als cumulatieve energie)"),
    "src_fin_vie": "nominale capaciteit gedeeld door de gegarandeerde resterende capaciteit aan het einde van de garantie ({etat} %)",
    "src_duree_courte": "profiel korter dan een jaar: de cycli worden niet naar een jaar omgerekend, de levensduur wordt niet berekend",
    "src_acm_faq_atr": ("ACM, Overzicht en inzicht congestiemaatregelen, update van 30/04/2025, §2.1 tot 2.3; Netbeheer "
                        "Nederland, FAQ alternatieve transportrechten, rekenvoorbeelden met tarieven van Liander 2024"),
    "src_remise_nfa": ("{kw} kW tussen de beoogde grens ({plafond} kW), die de batterij of het verschuiven vasthouden, en het "
                       "GTV ({gtv} kW), als volledig variabel transportrecht: geen tariefdrager kWgecontracteerd voor dat deel, kW max "
                       "en kWh blijven gelden (Tarievencode 2026, art. 3.14, Stcrt. 2026, 4090; FAQ alternatieve transportrechten van "
                       "Netbeheer Nederland) x {tarif} €/kW/jaar, tarievenblad {gestionnaire} 2026. "
                       "Alleen mogelijk in gebieden met een vooraankondiging congestie. Afgestaan vast transportrecht komt alleen "
                       "terug via een nieuwe aanvraag, die in een congestiegebied in de wachtrij komt: een lager opgegeven GTV verkleint "
                       "ook het vaste transportrecht zelf, niet alleen het tarief (CBb, NorthC tegen ACM, 23-06-2026). Dit bedrag staat "
                       "daarom los van de besparing. Reststroom is bij Liander nog in ontwikkeling en bij Enexis worden de voorwaarden "
                       "nog onderzocht (pagina's van 27-09-2026): een wettelijke mogelijkheid, nog geen beschikbaar aanbod."),
    "src_remise_sans_gtv": "GTV niet aangeleverd: de korting geldt voor het deel van het GTV boven de beoogde grens",
    "src_remise_sans_mesure": ("geen gesimuleerde maatregel (batterij, verschuiven) houdt de beoogde grens van {plafond} kW vast: het "
                               "deel erboven volledig variabel maken zou de locatie aan afschakelingen blootstellen; korting niet berekend"),
    "src_pas_kw_contrat": "geen tariefdrager kWgecontracteerd in deze tariefcategorie",
    "src_remise_gtv_sous_plafond": ("GTV ({gtv} kW) op of onder de beoogde grens ({plafond} kW): geen deel om "
                                    "variabel te maken"),
    "preavis_contrat": "beperkingen uiterlijk een dag van tevoren aangekondigd",
    "src_arbitrage": ("bovengrens: één cyclus per dag over {jours} dagen day-aheadprijzen NL 2025 (Energy-Charts, CC BY 4.0, "
                      "Bundesnetzagentur | SMARD.de), perfecte voorspelling, dynamisch leveringscontract, "
                      "zonder belastingen en zonder conflict met peak shaving"),
    "src_part_charge_pic": "te verschuiven vermogen gedeeld door de piek: te vergelijken met wat de processen kunnen verschuiven",
    "src_arbitrage_absent": "day-aheadprijzen niet beschikbaar (docs/donnees/prix-day-ahead-nl-2025.csv ontbreekt)",
    "src_retour_arbitrage": "eenvoudige terugverdientijd op kWmax-besparing plus theoretische arbitrage: kortst mogelijke termijn",
    "src_autonomie_dimensionnee": "nominale capaciteit x {dod} ontladingsdiepte, gedeeld door het vermogen",
    "part_alternative": "deel van de belasting dat onder een alternatief transportrecht zou kunnen vallen, geen technische flexibiliteit",
    "src_plafond_palier": "vlakke piek, langer dan {heures} uur bereikt: eerste niveau onder de piek",
    "src_limite_gtv": "opgegeven gecontracteerd transportvermogen (GTV): de grens die zonder nieuwe aanvraag niet mag worden overschreden",
    "src_limite_pointe": "GTV niet aangeleverd: de huidige piek dient als grens; die niet overschrijden voorkomt een nieuwe aanvraag",
    "src_croissance": "huidige piek min de aangehouden grens, plus de vrije ruimte onder het GTV als die bekend is",
    "src_flex_e": "RVO, pagina's Flex-e flexibiliteitsscan en flexibiliteitsmaatregelen, stand op 20/09/2026",
    "src_acm_sanction": "ACM, Overzicht congestiemaatregelen (30/04/2025), p. 15: € 120 per MW GTV ({mw} MW) per dag zonder aanbod voor een capaciteitsbeperkingscontract",
    "src_acm_sanction_sans_objet": "gecontracteerd transport onder 1 MW: geen verplichting, dus geen bedrag verschuldigd",
    "src_acm_sanction_si_annoncee": ("alleen verschuldigd als de deelnameplicht is aangekondigd en niet wordt nagekomen: € 120 per MW "
                                     "GTV per dag, dus € {montant} per dag voor {mw} MW (ACM, Overzicht congestiemaatregelen, p. 15)"),
    "src_acm_sanction_non_annoncee": "deelnameplicht niet aangekondigd: geen bedrag verschuldigd",
    "src_acm_sanction_groupe": "eventueel verschuldigd bedrag per aansluiting, niet voor de groep: per locatie te beoordelen",
    "src_reg009_a_verifier": ("boven 1 MW ontstaat de plicht alleen als de netbeheerder die in een congestiegebied inzet "
                              "(« Netbeheerders kunnen de deelnameplicht inzetten in een congestiegebied », ACM, Overzicht "
                              "congestiemaatregelen, p. 10): na te vragen bij de netbeheerder"),
    "src_reg009_non_annoncee": ("de netbeheerder heeft de deelnameplicht niet aangekondigd (fiche): nu geen plicht, in een "
                                "congestiegebied kan die nog komen"),
    "src_reg009_groupe": ("de deelnameplicht geldt voor een aansluiting van 1 MW of meer (ACM, Overzicht congestiemaatregelen, "
                          "p. 10), niet voor de som van een groep: per locatie te beoordelen"),
    "src_gotork_groupe": ("GOTORK (Netcode elektriciteit, art. 7.13) geldt per aansluiting: de drempels (50 % van het GTV of 1 MW "
                          "onbenut in twaalf maanden) worden per locatie beoordeeld, met het GTV en de piek van elke locatie, "
                          "nooit op de som van een groep."),
    "hyp_fiche_sans_source": "waarde vastgelegd in de opgegeven gegevens, zonder bron",
    "src_marge_gtv": "GTV {gtv} kW min gemeten piek {pointe} kW",
    "src_acm_gotork": ("GOTORK (Netcode elektriciteit, art. 7.13, ACM-besluit van 16-04-2024, in werking per 26-04-2024): in een "
                       "congestiegebied en vanaf middenspanning kan de netbeheerder het vaste GTV verlagen als in de afgelopen "
                       "twaalf maanden ten hoogste 50 % ervan is benut of 1 MW of meer onbenut is gebleven (10 MW vanaf 110 kV). "
                       "Dat gaat niet automatisch: de netbeheerder meldt het schriftelijk, overlegt met de aangeslotene en neemt "
                       "alleen het deel terug dat niet binnen ten minste twaalf maanden wordt gebruikt. Op basis van de gemeten "
                       "piek haalt deze locatie een van die drempels: een risico om voor te bereiden, geen zeker verlies. Een "
                       "gedocumenteerd groeiplan, zoals het scenario in deze scan, dient om het te verdedigen."),
    "src_acm_gotork_sous_seuil": ("GOTORK (Netcode elektriciteit, art. 7.13, in werking per 26-04-2024) geldt voor een GTV waarvan in "
                                  "twaalf maanden ten hoogste 50 % is benut of waarvan 1 MW of meer onbenut blijft (10 MW vanaf "
                                  "110 kV). Op basis van de gemeten piek haalt deze locatie geen van die drempels: volgens deze "
                                  "regels loopt de ruimte geen risico op terugname."),
    "src_acm_depassement": ("ACM (in werking per 26/04/2025): in een congestiegebied wordt het GTV bij overschrijding niet meer "
                            "automatisch verhoogd; daarvoor is een nieuwe aanvraag nodig. De locatie overschrijdt haar contract al."),
    "src_acm_limite": ("ACM (in werking per 26/04/2025): in een congestiegebied wordt het GTV bij overschrijding niet meer automatisch "
                       "verhoogd. De piek van de locatie is precies gelijk aan haar GTV: er is geen ruimte."),
    "remise_contrat": ("nettarief ongeveer 50 % lager bij volledig variabel (alle netten) en tijdsduurgebonden (TenneT); "
                       "bij tijdsblokgebonden (regionale netten) daalt kWgecontracteerd naar rato van de uren buiten het "
                       "tijdsvenster, de overige tarieven blijven gelden: -33 % op de maandfactuur transport in het officiële "
                       "rekenvoorbeeld van 10 MW (venster 22.00 tot 6.00 uur), -17 % bij 2 MW; vast en alternatief transportrecht "
                       "zijn op één aansluiting te combineren"),
    "gestionnaire_defaut": "netbeheerder niet aangeleverd: standaard tarieven van Liander",
    "gestionnaire_inconnu": "netbeheerder zonder bekende tarieftabel hier: standaard tarieven van Liander, te vervangen door de eigen tabel",
    "src_a_completer": "aan te vullen door het bedrijf of de energieadviseur",
    "src_fiche": "opgegeven door het bedrijf",
    "src_ato": "af te lezen in de ATO (aansluit- en transportovereenkomst)",
    "src_activite_estimee": "geschat uit het profiel: kwartieren boven {seuil} kW, dus basislast plus {part} van het verschil tot de piek",
    "src_horaires_estimes": "geschat uit de gemiddelde week: gemiddelde boven {seuil} kW",
    "src_visite": "te beschrijven tijdens het locatiebezoek dat Flex-e vereist",
    "src_preference": "op te vragen bij het bedrijf",
    "activation_batterie": "minder dan een minuut, automatisch gestuurd",
    "src_activation_batterie": "orde van grootte van batterijomvormers, te bevestigen door de fabrikant",
    "src_activation_process": "afhankelijk van het proces (opstart, stop, veiligheid), te beschrijven met de exploitant",
    "src_activation_usages": "afhankelijk van de afgeschakelde verbruikers, te beschrijven met de exploitant",
    "src_activation_contrat": "aankondigingstermijn van beperkingen, vastgelegd in het contract",
    "src_activation_offre": "activeringstijd gevraagd door de netbeheerder, vastgelegd in bieding of contract",
})

MOIS_LONG = {"fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
             "nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"]}
NATURES["fr"]["declare"] = "Déclaré"
NATURES["nl"]["declare"] = "Opgegeven"
NATURES["fr"]["a_completer"] = "À compléter"
NATURES["nl"]["a_completer"] = "Aan te vullen"

T["fr"].update({
    "sous_titre": "Plan d'un flexibiliteitsscan Flex-e (RVO), bijlage 4.12.1 de la Regeling nationale EZ-, LVVN- en KGG-subsidies",
    "s1": "1. Entreprise et raccordement", "s2": "2. Congestion et besoin de flexibilité dans la zone",
    "s3": "3. Processus principaux et production propre", "s4": "4. Profil de consommation d'électricité",
    "s5": "5. Mesures de flexibilité réalistes", "s6": "6. Analyse financière",
    "s7": "7. Avantages, inconvénients et conclusion", "s8": "8. Hypothèses du scan", "s9": "9. Sources et limites",
    "ean": "Code EAN du raccordement", "sbi": "Code SBI", "gtv": "Transport contracté (GTV)",
    "transport_autres": "Transport contracté, gaz et autres énergies", "changements_prevus": "Changements de contrat prévus",
    "autres_energies": "Gaz, chaleur et autres énergies", "heures_activite": "Heures d'activité",
    "horaires": "Horaires habituels sur la semaine", "instant": "Moment",
    "congestierapport": "Dernier congestierapport de la zone",
    "congestierapport_vide": "à consulter sur le site du gestionnaire s'il existe (exigé par Flex-e).",
    "besoin_zone": "Besoin de flexibilité dans la zone", "besoin_zone_vide": "à décrire à partir de la carte et du congestierapport.",
    "processus": "Processus principaux", "production_propre": "Production ou conversion propre",
    "analyse_titre": "Analyse des pics et des creux",
    "analyse_txt": ("Sur les {n} quarts d'heure les plus hauts (1 % du temps), {part} tombent en semaine et {part_fenetre} entre {h1} et {h2}. "
                    "La pointe mensuelle est la plus haute en {mois_max} ({kw_max} kW) et la plus basse en {mois_min} ({kw_min} kW). "
                    "Niveaux moyens : {ouvre} kW les jours ouvrés, {repos} kW le week-end, {nuit} kW la nuit (0 h à 6 h), "
                    "charge de base {base} kW."),
    "pics_titre": "Les dix jours de plus forte pointe", "plafond_titre": "Plafond visé par les mesures",
    "mesures_intro": ("Pour chaque mesure : a. puissance flexible en MW ; b. énergie flexible en MWh par an ; c. durée continue ; "
                      "d. moments d'utilisation sur la semaine et la journée ; e. mise en route et arrêt ; f. profils après la mesure."),
    "mise_en_route": "Mise en route et arrêt", "baisse": "baisse de charge (maximum par quart d'heure)",
    "hausse": "hausse de charge", "hausse_batterie": "recharge de la batterie", "hausse_decalage": "charge reportée",
    "moments_semaine": "d. Moments d'utilisation sur la semaine", "moments_jour": "d. Moments d'utilisation sur la journée",
    "moments_offre": "d. Moments fixés à la demande du gestionnaire : à définir dans l'offre ou le contrat.",
    "apres_annuel": "f. Profil annuel après la mesure (maximum de chaque jour)", "apres_mensuel": "f. Profil mensuel après la mesure (maximum de chaque mois)",
    "apres_hebdo": "f. Profil hebdomadaire après la mesure, semaine de la pointe", "apres_jour": "f. Profil journalier après la mesure, jour de la pointe",
    "financiere_intro_groupe": ("Investissement et eenvoudige terugverdientijd (ETVT) par mesure. Contrat de transport de groupe : "
                                "sans grille publiée, les économies de transport et les retours qui en dépendent restent à chiffrer ; "
                                "le transport contracté n'est pas baissé."),
    "financiere_intro": ("Investissement et eenvoudige terugverdientijd (ETVT) par mesure. L'économie comptée est la seule baisse du kWmax "
                         "aux tarifs {gestionnaire} 2026 ; le transport contracté n'est pas baissé."),
    "financiere_projet": (" Avec le projet, cette économie est comptée par rapport au projet sans mesure : la part kWmax de la "
                          "facture peut quand même monter par rapport à aujourd'hui."),
    "tranche_etvt": "Tranche ETVT", "autres_montants": "Autres montants",
    "marge_gtv": "Marge sous le transport contracté",
    "arbitrage_eur_an": "Arbitrage day-ahead (borne haute)", "retour_arbitrage_ans": "Retour avec arbitrage",
    "reco_arbitrage": (" Avec un arbitrage day-ahead théorique de {arb} € par an (borne haute), le retour descendrait à {a1} à {a2} ans, "
                       "à condition d'un contrat de fourniture indexé sur le day-ahead."),
    "annee_rep": "Année du profil", "annee_rep_src": "Flex-e demande une année représentative des trois dernières (bijlage 4.12.1, art. 1 et 4)",
    "annee_ok": "{annee}, dans les trois dernières années",
    "annee_future": "{annee} : postérieure à {annee_scan}, un scénario et non une mesure récente",
    "annee_en_cours": "{annee} : année en cours, pas encore l'une des trois dernières années complètes",
    "annee_periode_annuelle": " ; {jours} jours lus, pas une année civile complète",
    "annee_partielle": " ; {jours} jours lus seulement, moins d'un an",
    "annee_choisie_plus_recente": " ; choisie parmi {annees} : la plus récente année civile complète, à confirmer comme représentative",
    "annee_choisie_fiche": " ; choisie dans la fiche parmi {annees}",
    "annee_choisie_glissante": " ; aucune année civile complète dans {annees} : les 365 derniers jours du fichier", "annee_ancienne": "{annee} : plus de trois ans avant {annee_scan}, à remplacer par une année récente pour un scan Flex-e", "sanction_sans_offre": "Montant dû sans offre (au-delà de 1 MW)",
    "etvt_moins_3": "moins de 3 ans", "etvt_3_5": "3 à 5 ans", "etvt_5_7": "5 à 7 ans", "etvt_7_15": "7 à 15 ans", "etvt_plus_15": "plus de 15 ans",
    "voordelen": "Avantages", "nadelen": "Inconvénients",
    "voor_batterie": "Tient le plafond sans toucher aux process ; peut aussi servir au gestionnaire.",
    "nadeel_batterie": "Investissement et usure ; place et sécurité incendie à étudier ; dimensionnée ici par {dim}.",
    "nadeel_batterie_impossible": "Aucune batterie du modèle ne tient le plafond sur la période (raison en 5.1).",
    "voor_decalage": "Aucune énergie perdue ; pas de matériel lourd.",
    "nadeel_decalage": "Exige que des process glissent de ± {fenetre} h ; une organisation à tenir dans la durée.",
    "voor_ecretage": "Simple et immédiat.", "nadeel_ecretage": "Production ou confort perdus : {mwh} MWh ({pct} de la consommation).",
    "voor_contrat": "Aucun investissement ; peut ouvrir de la capacité en zone saturée.",
    "nadeel_contrat": "Pas de garantie en non ferme ; jusqu'à 15 % des heures pouvant être coupées en lié à la durée ; dépend de l'offre du gestionnaire.",
    "voor_offre_gestionnaire": "Rémunération possible ; au-delà de 1 MW, la participation est attendue (REG-009).",
    "nadeel_offre_gestionnaire": "Rémunération non publiée d'avance ; exige une flexibilité disponible à la demande.",
    "comparaison_titre": "Comparaison des mesures", "conclusion_titre": "Conclusion",
    "conclusion_txt": ("Mesure la plus prometteuse à ce stade : {option}, avec les réserves indiquées ci-dessous. La conclusion définitive "
                       "revient à l'energieadviseur après la visite du site."),
    "preference": "Préférence de l'entreprise",
    "conformite_titre": "Où en est ce scan par rapport au format Flex-e",
    "etapes_titre": "Prochaines étapes",
    "etape_visite": "Visiter le site avec l'energieadviseur : processus, équipements, contraintes d'exploitation (exigé par Flex-e).",
    "etape_pieces": "Réunir les pièces manquantes : codes EAN et SBI, ATO avec le GTV et les changements prévus, gaz et chaleur.",
    "etape_annee": "Remplacer le profil par une année récente (2023, 2024 ou 2025), téléchargeable chez le gestionnaire.",
    "etape_carte": "Relever le statut de la zone sur la capaciteitskaart, dans les deux sens, et le dernier congestierapport.",
    "etape_process": "Vérifier avec l'exploitant quels process peuvent glisser, de combien d'heures, et à quel coût.",
    "etape_devis": "Demander deux devis de batterie, avec C-rate, rendement et profondeur de décharge garantis.",
    "etape_gestionnaire": "Demander au gestionnaire ses offres de droit alternatif (non ferme, par blocs) et leur remise.",
    "etape_1mw": "Au-delà de 1 MW : préparer l'offre de flexibilité et les prévisions quotidiennes exigées.",
    "etape_flexe": "Déposer la demande Flex-e avant le 15/10/2026 à 17 h si le scan doit être subventionné.",
    "syn_titre": "L'essentiel",
    "syn_profil": "Pointe de {pointe} kW pour {energie}. La charge ne dépasse {plafond} kW que {heures} h sur la période.",
    "syn_profil_simple": "Pointe actuelle de {pointe} kW pour {energie}.",
    "syn_capacite": "Tenir ce plafond libère {liberes} kW pour de nouveaux usages, sans nouvelle demande au réseau.",
    "groupe_condition": ("Ce profil additionne plusieurs raccordements : cela suppose un contrat de transport de groupe, à demander "
                         "au gestionnaire, qui devra le proposer à partir du 01/01/2027, à des conditions encore à fixer (communiqué ACM du 19/12/2025)."),
    "syn_capacite_depasse": ("Le site dépasse déjà son GTV de {dep} kW ; tenir ce plafond le ramène sous son contrat et laisse "
                             "{total} kW pour de nouveaux usages."),
    "syn_capacite_depasse_reste": ("Le site dépasse déjà son GTV de {dep} kW, et même ce plafond reste au-dessus : aucune capacité "
                                   "sans nouvelle demande au réseau."),
    "croissance_depasse": ("Le site dépasse déjà son GTV ({gtv} kW) de {dep} kW. En tenant le plafond de {plafond} kW, il revient sous "
                           "son contrat et garde {total} kW pour de nouveaux usages, sans nouvelle demande de transport."),
    "croissance_depasse_reste": ("Le site dépasse déjà son GTV ({gtv} kW) de {dep} kW, et le plafond visé de {plafond} kW reste "
                                 "au-dessus : aucune capacité n'est libérée sans nouvelle demande de transport."),
    "syn_projet": "Le projet ajoute {kw} kW : la pointe passerait à {pointe} kW pour une limite de {limite} kW. Les mesures visent à l'accueillir sous cette limite.",
    "syn_projet_tient": "Le projet ajoute {kw} kW et tient sous la limite de {limite} kW sans mesure.",
    "syn_mesure": "Mesure à examiner en premier : {option}. {condition}",
    "syn_facture": "Sur la facture de transport, l'effet reste faible ({eco} € {par_an} sur le kWmax) : l'enjeu est la capacité.",
    "syn_facture_neutre": "Économie de transport sur le kWmax : {eco} € {par_an} ; le retour de chaque mesure est en partie 6.",
    "syn_facture_sans_kwmax": "Pas de terme kWmax dans cette catégorie tarifaire : aucune économie de transport à compter ; l'enjeu est la capacité.",
    "duree_besoin_h": "Durée équivalente à pleine puissance (capacité utile nécessaire)", "flex_kw_contrat": "Part sous droit alternatif",
    "duree_contrat": "Heures limitables (droit lié à la durée, réseau TenneT)",
    "part_charge_pic": "Part de la charge à déplacer au moment de la pointe",
    "sens_titre": "Sensibilité des conclusions",
    "sens_txt": ("Deux hypothèses pèsent le plus : la fenêtre que les process supportent pour glisser, et le C-rate de la batterie. "
                 "Les tableaux montrent ce qui change quand elles bougent."),
    "sens_fenetre": "Décalage : part de l'énergie qui trouve place selon la fenêtre", "fenetre": "Fenêtre",
    "part_placee": "Part placée", "suffit": "Suffit toute la période",
    "sens_crate": "Batterie : capacité et investissement selon le C-rate", "dimension_par": "Dimensionnée par",
    "blocs_titre": "Droit par blocs horaires : où se trouve la charge", "bloc": "Bloc indicatif",
    "blocs_txt": ("Sur les réseaux régionaux, le droit par blocs horaires s'appelle Blokstroom. Le seul créneau proposé "
                  "aujourd'hui est la nuit, de 0 h à 6 h, payé 25 % du terme kW contracté. Chez Enexis, seulement si le poste a de la "
                  "capacité à ces heures, et le GTV ferme peut y être échangé en tout ou partie ; chez Stedin, d'abord en Zeeland "
                  "seulement ; chez Liander, d'abord en Friesland et dans le Noordoostpolder, toujours en plus du GTV ferme, jamais en "
                  "échange (pages des trois gestionnaires lues le 27/09/2026). Ce tableau montre la pointe et l'énergie de chaque période."),
    "bloc_nuit": "nuit, 0 h à 6 h", "bloc_jour_ouvre": "jours ouvrés, 6 h à minuit", "bloc_week_end_jour": "week-end, 6 h à minuit",
    "complement": "Combinaison : batterie pour le reste", "complement_txt": "{kw} kW, {kwh} kWh nominaux",
    "complement_impossible": "aucune batterie du modèle ne suffit",
    "scenario_titre": "Scénario de croissance étudié",
    "scenario_txt": ("Projet : {desc}. {kw} kW de plus, de {debut} à {fin}, {jours}, soit {mwh} MWh {periode}. Avec ce projet, la pointe "
                     "passerait à {pointe} kW pour une limite de {limite} kW."),
    "scenario_depasse": (" Elle dépasserait la limite pendant {heures} h {periode}, pour {energie} kWh au total. Les mesures de la partie 5 "
                         "portent sur ce profil augmenté : elles cherchent à accueillir le projet sous la limite."),
    "scenario_tient": " Le projet tient déjà sous la limite : aucune mesure n'est nécessaire pour lui. Les mesures ci-dessous portent sur le profil actuel.",
    "jours_ouvres": "les jours ouvrés", "jours_tous": "tous les jours", "projet_sans_nom": "charge supplémentaire",
    "avant_croissance": "avec le projet, avant mesure",
    "croissance_scenario": ("Pour accueillir le projet ({kw} kW) sous la limite de {limite} kW, la mesure la plus prometteuse est : {option}. "
                            "Sans aucune mesure, il faudrait une nouvelle demande de transport ; en zone saturée, l'attente peut durer des années."),
    "croissance_scenario_tient": "Le projet ({kw} kW) tient sous la limite de {limite} kW sans aucune mesure : aucune nouvelle demande n'est nécessaire.",
    "conformite_txt": ("Éléments exigés par la bijlage 4.12.1 et par la page RVO : {n} sur {total} restent à compléter ou à faire sur "
                       "place avant de déposer un scan. Le reste est fourni par l'entreprise ou calculé ici."),
    "element": "Élément", "etat": "État",
    "croissance_titre": "Capacité de croissance sans nouvelle demande au réseau",
    "croissance_txt": ("En tenant le plafond de {plafond} kW, le site peut ajouter jusqu'à {liberes} kW de nouveaux usages sans dépasser "
                       "sa pointe actuelle, donc sans nouvelle demande de transport."),
    "croissance_gtv": " Avec la marge de {marge} kW encore libre sous le GTV, cela fait {total} kW.",
    "croissance_valeur": ("En zone saturée, où une nouvelle demande peut attendre des années, cette capacité peut peser bien plus que "
                          "l'économie sur la facture ({eco} € {par_an} ici)."),
    "financement_titre": "Financement Flex-e (RVO)",
    "financement_batterie_sous_minimum": (" Pour la batterie de ce scan ({bas} à {haut} €), 40 % donneraient {a1} à {a2} €, sous le "
                                          "minimum de 25 000 € : pas d'aide aux mesures pour elle seule."),
    "financement_batterie_partiel": (" Pour la batterie de ce scan ({bas} à {haut} €), 40 % donneraient {a1} à {a2} € : l'aide n'est "
                                     "possible que si le coût réel atteint 62 500 €."),
    "financement_batterie_eligible": " Pour la batterie de ce scan ({bas} à {haut} €), 40 % donneraient {a1} à {a2} €.",
    "financement_txt": ("Flex-e rembourse 50 % d'un flexibiliteitsscan, jusqu'à 10 000 €, et 40 % des mesures, avec une aide de "
                        "25 000 € au moins (donc des mesures d'au moins 62 500 €) et de 300 000 € au plus (50 000 € pour une "
                        "exploitation agricole), "
                        "pour les demandes déposées entre le 06/05/2026 et le 15/10/2026 à 17 h. Au 20/09/2026, le budget des scans "
                        "était disponible à 62 %, celui des mesures était sursouscrit."),
    "limites": ("Ce rapport prépare un flexibiliteitsscan, il ne le remplace pas : Flex-e exige qu'un energieadviseur visite le site au "
                "moins une fois et décrive les processus. La batterie suppose une prévision parfaite des pointes : c'est une borne "
                "optimiste. Le décalage suppose que des process peuvent glisser : à confirmer sur place. L'économie de transport ne compte "
                "que la baisse du kWmax, et l'arbitrage day-ahead est une borne haute donnée à part ; baisser le transport contracté "
                "n'est pas compté, car en zone saturée une capacité rendue ne revient que par une nouvelle demande, soumise à la capacité disponible (affaire NorthC : décision ACM du 19/07/2024, confirmée par le CBb le 23/06/2026). "
                "Remises et rémunérations restent à demander."),
})
T["nl"].update({
    "sous_titre": "Opbouw van een Flex-e-flexibiliteitsscan (RVO), bijlage 4.12.1 van de Regeling nationale EZ-, LVVN- en KGG-subsidies",
    "s1": "1. Gegevens over de onderneming", "s2": "2. Congestieproblematiek en flexibiliteitsbehoefte in het gebied",
    "s3": "3. Hoofdprocessen en eigen opwek", "s4": "4. Energievraagprofiel elektriciteit",
    "s5": "5. Realistische flexibiliteitsmaatregelen", "s6": "6. Financiële analyse",
    "s7": "7. Voor- en nadelen en conclusie", "s8": "8. Aannames van de scan", "s9": "9. Bronnen en beperkingen",
    "ean": "EAN-code van de aansluiting", "sbi": "SBI-code", "gtv": "Gecontracteerd transportvermogen (GTV)",
    "transport_autres": "Gecontracteerd transport, gas en andere energiedragers", "changements_prevus": "Geplande contractwijzigingen",
    "autres_energies": "Aardgas, warmte en andere energiedragers", "heures_activite": "Bedrijfsuren per jaar",
    "horaires": "Standaard bedrijfstijden per week", "instant": "Moment",
    "congestierapport": "Meest recente congestierapport van het gebied",
    "congestierapport_vide": "te raadplegen op de website van de netbeheerder, indien beschikbaar (vereist door Flex-e).",
    "besoin_zone": "Flexibiliteitsbehoefte in het gebied", "besoin_zone_vide": "te beschrijven op basis van de kaart en het congestierapport.",
    "processus": "Hoofdprocessen", "production_propre": "Eigen opwek of conversie",
    "analyse_titre": "Analyse van pieken en dalen",
    "analyse_txt": ("Van de {n} hoogste kwartieren (1 % van de tijd) valt {part} op werkdagen en {part_fenetre} tussen {h1} en {h2}. "
                    "De maandpiek is het hoogst in {mois_max} ({kw_max} kW) en het laagst in {mois_min} ({kw_min} kW). "
                    "Gemiddelde niveaus: {ouvre} kW op werkdagen, {repos} kW in het weekend, {nuit} kW 's nachts (0 tot 6 uur), "
                    "basislast {base} kW."),
    "pics_titre": "De tien dagen met de hoogste piek", "plafond_titre": "Beoogde grens van de maatregelen",
    "mesures_intro": ("Per maatregel: a. flexibel vermogen in MW; b. flexibele energie in MWh per jaar; c. aaneengesloten duur; "
                      "d. inzetmomenten over de week en de dag; e. op- en afregelprocedure; f. profielen na de maatregel."),
    "mise_en_route": "Op- en afregelprocedure", "baisse": "verlaging (maximum per kwartier)",
    "hausse": "verhoging", "hausse_batterie": "laden van de batterij", "hausse_decalage": "verschoven verbruik",
    "moments_semaine": "d. Inzetmomenten over de week", "moments_jour": "d. Inzetmomenten over de dag",
    "moments_offre": "d. Momenten op verzoek van de netbeheerder: vast te leggen in bieding of contract.",
    "apres_annuel": "f. Jaarprofiel na de maatregel (dagmaximum)", "apres_mensuel": "f. Maandprofiel na de maatregel (maandmaximum)",
    "apres_hebdo": "f. Weekprofiel na de maatregel, week van de piek", "apres_jour": "f. Dagprofiel na de maatregel, dag van de piek",
    "financiere_intro_groupe": ("Investering en eenvoudige terugverdientijd (ETVT) per maatregel. Groepstransportovereenkomst: zonder "
                                "gepubliceerd tarief moeten de transportbesparingen en de terugverdientijden die daarvan afhangen nog "
                                "worden bepaald; het gecontracteerde transportvermogen wordt niet verlaagd."),
    "financiere_intro": ("Investering en eenvoudige terugverdientijd (ETVT) per maatregel. De getelde besparing is alleen de verlaging van "
                         "kWmax tegen de tarieven van {gestionnaire} 2026; het gecontracteerde transportvermogen wordt niet verlaagd."),
    "financiere_projet": (" Met het project wordt deze besparing berekend ten opzichte van het project zonder maatregel: het "
                          "kWmax-deel van de factuur kan ten opzichte van nu toch stijgen."),
    "tranche_etvt": "ETVT-klasse", "autres_montants": "Overige bedragen",
    "marge_gtv": "Ruimte onder het gecontracteerde transportvermogen",
    "arbitrage_eur_an": "Arbitrage op de day-aheadmarkt (bovengrens)", "retour_arbitrage_ans": "Terugverdientijd met arbitrage",
    "reco_arbitrage": (" Met theoretische arbitrage op de day-aheadmarkt van {arb} € per jaar (bovengrens) zou de terugverdientijd dalen naar {a1} "
                       "à {a2} jaar, op voorwaarde van een dynamisch leveringscontract."),
    "annee_rep": "Jaar van het profiel", "annee_rep_src": "Flex-e vraagt een representatief jaar van de afgelopen drie jaren (bijlage 4.12.1, art. 1 en 4)",
    "annee_ok": "{annee}, binnen de afgelopen drie jaren",
    "annee_future": "{annee}: later dan {annee_scan}, een scenario en geen recente meting",
    "annee_en_cours": "{annee}: lopend jaar, nog geen van de afgelopen drie volledige jaren",
    "annee_periode_annuelle": "; {jours} dagen gelezen, geen volledig kalenderjaar",
    "annee_partielle": "; slechts {jours} dagen gelezen, minder dan een jaar",
    "annee_choisie_plus_recente": "; gekozen uit {annees}: het meest recente volledige kalenderjaar, als representatief te bevestigen",
    "annee_choisie_fiche": "; in de fiche gekozen uit {annees}",
    "annee_choisie_glissante": "; geen volledig kalenderjaar in {annees}: de laatste 365 dagen van het bestand", "annee_ancienne": "{annee}: meer dan drie jaar vóór {annee_scan}, voor een Flex-e-scan te vervangen door een recent jaar", "sanction_sans_offre": "Verschuldigd bedrag zonder aanbod (boven 1 MW)",
    "etvt_moins_3": "minder dan 3 jaar", "etvt_3_5": "3 tot 5 jaar", "etvt_5_7": "5 tot 7 jaar", "etvt_7_15": "7 tot 15 jaar",
    "etvt_plus_15": "meer dan 15 jaar",
    "voordelen": "Voordelen", "nadelen": "Nadelen",
    "voor_batterie": "Houdt de belasting onder de grens zonder in te grijpen in processen; ook inzetbaar voor de netbeheerder.",
    "nadeel_batterie": "Investering en slijtage; ruimte en brandveiligheid te onderzoeken; hier gedimensioneerd op {dim}.",
    "nadeel_batterie_impossible": "Geen batterij uit het model houdt de grens vast over de periode (reden in 5.1).",
    "voor_decalage": "Geen energieverlies; geen zware hardware.",
    "nadeel_decalage": "Processen moeten ± {fenetre} uur kunnen schuiven; een organisatie die blijvend moet werken.",
    "voor_ecretage": "Eenvoudig en direct.", "nadeel_ecretage": "Gemiste productie of comfort: {mwh} MWh ({pct} van het verbruik).",
    "voor_contrat": "Geen investering; kan extra capaciteit opleveren in een congestiegebied.",
    "nadeel_contrat": "Geen garantie bij niet-vast; tot 15 % van de uren beperkbaar bij tijdsduurgebonden; afhankelijk van het aanbod van de netbeheerder.",
    "voor_offre_gestionnaire": "Mogelijke vergoeding; boven 1 MW wordt deelname verwacht (REG-009).",
    "nadeel_offre_gestionnaire": "Vergoeding niet vooraf gepubliceerd; vraagt flexibiliteit die op verzoek beschikbaar is.",
    "comparaison_titre": "Vergelijking van de maatregelen", "conclusion_titre": "Conclusie",
    "conclusion_txt": ("Meest kansrijke maatregel in dit stadium: {option}, met de kanttekeningen hieronder. De definitieve conclusie ligt bij "
                       "de energieadviseur na het locatiebezoek."),
    "preference": "Voorkeur van het bedrijf",
    "conformite_titre": "Stand van deze scan ten opzichte van het Flex-e-format",
    "etapes_titre": "Volgende stappen",
    "etape_visite": "De locatie bezoeken met de energieadviseur: processen, installaties, bedrijfsbeperkingen (vereist door Flex-e).",
    "etape_pieces": "Ontbrekende stukken verzamelen: EAN- en SBI-codes, ATO met GTV en geplande wijzigingen, gas en warmte.",
    "etape_annee": "Het profiel vervangen door een recent jaar (2023, 2024 of 2025), te downloaden bij de netbeheerder.",
    "etape_carte": "De status van het gebied op de capaciteitskaart opzoeken, in beide richtingen, en het meest recente congestierapport.",
    "etape_process": "Met de exploitant nagaan welke processen kunnen schuiven, hoeveel uur, en tegen welke kosten.",
    "etape_devis": "Twee offertes voor een batterij opvragen, met gegarandeerde C-rate, rendement en ontladingsdiepte.",
    "etape_gestionnaire": "De netbeheerder vragen naar zijn aanbod van alternatieve transportrechten (volledig variabel, tijdsblokken) en de korting.",
    "etape_1mw": "Boven 1 MW: het flexibiliteitsaanbod en de verplichte dagelijkse prognoses voorbereiden.",
    "etape_flexe": "De Flex-e-aanvraag indienen vóór 15/10/2026 17:00 als de scan gesubsidieerd moet worden.",
    "syn_titre": "In het kort",
    "syn_profil": "Piek van {pointe} kW bij {energie}. De belasting ligt maar {heures} uur in de periode boven {plafond} kW.",
    "syn_profil_simple": "Huidige piek van {pointe} kW bij {energie}.",
    "syn_capacite": "Door deze grens aan te houden komt {liberes} kW vrij voor nieuw verbruik, zonder nieuwe aanvraag bij de netbeheerder.",
    "groupe_condition": ("Dit profiel telt meerdere aansluitingen op: dat veronderstelt een groepstransportovereenkomst, aan te vragen "
                         "bij de netbeheerder, die deze vanaf 1 januari 2027 moet aanbieden, onder voorwaarden die nog moeten worden vastgelegd "
                         "(persbericht ACM van 19-12-2025)."),
    "syn_capacite_depasse": ("De locatie overschrijdt haar GTV al met {dep} kW; door deze grens aan te houden blijft ze weer binnen "
                             "haar contract en blijft er {total} kW over voor nieuw verbruik."),
    "syn_capacite_depasse_reste": ("De locatie overschrijdt haar GTV al met {dep} kW, en ook deze grens ligt erboven: zonder nieuwe "
                                   "aanvraag bij de netbeheerder komt er geen ruimte vrij."),
    "croissance_depasse": ("De locatie overschrijdt haar GTV ({gtv} kW) al met {dep} kW. Door de grens van {plafond} kW aan te houden, "
                           "blijft ze weer binnen haar contract en houdt ze {total} kW over voor nieuw verbruik, zonder nieuwe "
                           "transportaanvraag."),
    "croissance_depasse_reste": ("De locatie overschrijdt haar GTV ({gtv} kW) al met {dep} kW, en de beoogde grens van {plafond} kW "
                                 "ligt erboven: zonder nieuwe transportaanvraag komt er geen ruimte vrij."),
    "syn_projet": "Het project voegt {kw} kW toe: de piek zou stijgen naar {pointe} kW bij een grens van {limite} kW. De maatregelen zoeken ruimte om het daaronder te laten passen.",
    "syn_projet_tient": "Het project voegt {kw} kW toe en past zonder maatregel onder de grens van {limite} kW.",
    "syn_mesure": "Eerst te bekijken maatregel: {option}. {condition}",
    "syn_facture": "Op de transportrekening blijft het effect klein ({eco} € {par_an} op kWmax): het gaat om capaciteit.",
    "syn_facture_neutre": "Besparing op het kWmax-tarief: {eco} € {par_an}; de terugverdientijd per maatregel staat in deel 6.",
    "syn_facture_sans_kwmax": "Geen kWmax-component in deze tariefcategorie: geen transportbesparing te tellen; het gaat om capaciteit.",
    "duree_besoin_h": "Equivalente duur op vol vermogen (benodigde bruikbare capaciteit)", "flex_kw_contrat": "Deel onder alternatief recht",
    "duree_contrat": "Beperkbare uren (tijdsduurgebonden recht, TenneT-net)",
    "part_charge_pic": "Deel van de belasting dat op het piekmoment moet schuiven",
    "sens_titre": "Gevoeligheid van de conclusies",
    "sens_txt": ("Twee aannames wegen het zwaarst: het tijdvenster waarbinnen processen kunnen schuiven, en de C-rate van de batterij. "
                 "De tabellen tonen wat er verandert als ze anders zijn."),
    "sens_fenetre": "Verschuiven: deel van de energie dat een plek vindt, per tijdvenster", "fenetre": "Tijdvenster",
    "part_placee": "Geplaatst deel", "suffit": "Voldoende over de hele periode",
    "sens_crate": "Batterij: capaciteit en investering per C-rate", "dimension_par": "Gedimensioneerd op",
    "blocs_titre": "Tijdsblokgebonden recht: waar de belasting zit", "bloc": "Indicatief tijdsblok",
    "blocs_txt": ("Op regionale netten heet het tijdsblokgebonden recht Blokstroom. Het enige aangeboden tijdsblok "
                  "is nu de nacht, van 0 tot 6 uur, tegen 25 % van het tarief voor gecontracteerd transportvermogen. Bij Enexis alleen "
                  "als het station op die uren capaciteit heeft, en het vaste GTV kan geheel of gedeeltelijk worden ingewisseld; bij "
                  "Stedin eerst alleen in Zeeland; bij Liander eerst in Friesland en de Noordoostpolder, altijd bovenop het vaste GTV, "
                  "nooit ter vervanging ervan (pagina's van de drie netbeheerders gelezen op 27-09-2026). Deze tabel toont de piek en de energie per periode."),
    "bloc_nuit": "nacht, 0 tot 6 uur", "bloc_jour_ouvre": "werkdagen, 6 tot 24 uur", "bloc_week_end_jour": "weekend, 6 tot 24 uur",
    "complement": "Combinatie: batterij voor de rest", "complement_txt": "{kw} kW, {kwh} kWh nominaal",
    "complement_impossible": "geen batterij in dit model volstaat",
    "scenario_titre": "Onderzocht groeiscenario",
    "scenario_txt": ("Project: {desc}. {kw} kW extra, van {debut} tot {fin}, {jours}, dus {mwh} MWh {periode}. Met dit project zou de piek "
                     "stijgen naar {pointe} kW, bij een grens van {limite} kW."),
    "scenario_depasse": (" De grens zou {heures} uur {periode} worden overschreden, samen {energie} kWh. De maatregelen in deel 5 gaan uit van "
                         "dit verhoogde profiel: ze zoeken ruimte voor het project onder de grens."),
    "scenario_tient": " Het project past al onder de grens: daarvoor is geen maatregel nodig. De maatregelen hieronder gaan uit van het huidige profiel.",
    "jours_ouvres": "op werkdagen", "jours_tous": "elke dag", "projet_sans_nom": "extra verbruik",
    "avant_croissance": "met het project, voor de maatregel",
    "croissance_scenario": ("Om het project ({kw} kW) onder de grens van {limite} kW te laten passen, is de meest kansrijke maatregel: {option}. "
                            "Zonder enige maatregel is een nieuwe transportaanvraag nodig; in een congestiegebied kan de wachttijd jaren duren."),
    "croissance_scenario_tient": "Het project ({kw} kW) past zonder maatregel onder de grens van {limite} kW: een nieuwe aanvraag is niet nodig.",
    "conformite_txt": ("Onderdelen die bijlage 4.12.1 en de RVO-pagina vragen: {n} van de {total} moeten nog worden aangevuld of ter "
                       "plaatse worden gedaan voordat een scan wordt ingediend. De rest is aangeleverd door het bedrijf of hier berekend."),
    "element": "Onderdeel", "etat": "Stand",
    "croissance_titre": "Groeiruimte zonder nieuwe aanvraag bij de netbeheerder",
    "croissance_txt": ("Door de grens van {plafond} kW aan te houden, kan de locatie tot {liberes} kW nieuw verbruik toevoegen zonder "
                       "haar huidige piek te overschrijden, dus zonder nieuwe transportaanvraag."),
    "croissance_gtv": " Met de {marge} kW die nog vrij is onder het GTV, is dat {total} kW.",
    "croissance_valeur": ("In een congestiegebied, waar een nieuwe aanvraag jaren kan duren, kan deze ruimte veel zwaarder wegen dan "
                          "de besparing op de rekening ({eco} € {par_an} hier)."),
    "financement_titre": "Financiering via Flex-e (RVO)",
    "financement_batterie_sous_minimum": (" Voor de batterij uit deze scan (€ {bas} tot € {haut}) zou 40 % € {a1} tot € {a2} "
                                          "opleveren, onder het minimum van € 25.000: geen subsidie voor maatregelen voor die batterij "
                                          "alleen."),
    "financement_batterie_partiel": (" Voor de batterij uit deze scan (€ {bas} tot € {haut}) zou 40 % € {a1} tot € {a2} opleveren: "
                                     "subsidie is alleen mogelijk als de werkelijke kosten € 62.500 bereiken."),
    "financement_batterie_eligible": " Voor de batterij uit deze scan (€ {bas} tot € {haut}) zou 40 % € {a1} tot € {a2} opleveren.",
    "financement_txt": ("Flex-e vergoedt 50 % van een flexibiliteitsscan, tot € 10.000, en 40 % van maatregelen, met een subsidie van "
                        "minimaal € 25.000 (dus maatregelen van minstens € 62.500) en maximaal € 300.000 (€ 50.000 voor een "
                        "landbouwbedrijf), voor "
                        "aanvragen tussen 06/05/2026 en 15/10/2026 17:00. Op 20/09/2026 was 62 % van het scanbudget beschikbaar; "
                        "het budget voor maatregelen was overtekend."),
    "limites": ("Dit rapport bereidt een flexibiliteitsscan voor, het vervangt hem niet: Flex-e vereist dat een energieadviseur de locatie "
                "minstens één keer bezoekt en de processen beschrijft. De batterij veronderstelt een perfecte voorspelling van de pieken: "
                "een optimistische grens. Verschuiven veronderstelt dat processen kunnen schuiven: ter plaatse te bevestigen. De "
                "transportbesparing telt alleen de kWmax-verlaging, en arbitrage op de day-aheadmarkt is een apart vermelde bovengrens; "
                "een lager GTV wordt niet meegeteld, want in een congestiegebied komt teruggegeven capaciteit alleen terug via een nieuwe aanvraag, "
                "afhankelijk van de beschikbare capaciteit (zaak NorthC, "
                "ACM-besluit van 19-07-2024, bevestigd door het CBb op 23-06-2026). Kortingen en vergoedingen moeten worden opgevraagd."),
})

MOIS = {"fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
        "nl": ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]}
JOURS = {"fr": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"], "nl": ["ma", "di", "wo", "do", "vr", "za", "zo"]}
COULEURS = {"avant": "#8a8f98", "apres": "#c2410c", "moyenne": "#2563eb", "plafond": "#b91c1c", "repos": "#16a34a"}


def e(x: Any) -> str:
    return html.escape(str(x))


def nombre(x: Any, langue: str, dec: int = 0) -> str:
    if x is None:
        return "–"
    if isinstance(x, bool):
        return T[langue]["oui"] if x else T[langue]["non"]
    if isinstance(x, (list, tuple)):
        lien = " à " if langue == "fr" else " tot "
        return lien.join(nombre(v, langue, dec) for v in x)
    if not isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, int) or (x.is_integer() and abs(x) >= 100):
        dec = 0
    texte = f"{x:,.{dec}f}"
    return texte.replace(",", "§").replace(".", ",").replace("§", " " if langue == "fr" else ".")


def pourcent(x: float, langue: str) -> str:
    if x == 0:
        return "0 %"
    if 0 < x < 0.0001:  # « 0,00 % » pour une part non nulle : dire « moins de 0,01 % »
        return "< " + nombre(0.01, langue, 2) + " %"
    return nombre(x * 100, langue, 2 if x < 0.01 else 1) + " %"


def badge(nature: str, langue: str) -> str:
    return f"<span class='n n-{nature}'>{e(NATURES[langue][nature])}</span>"


def unite(cle: str, langue: str) -> str:
    return UNITES[langue][cle]


def _nombre_source(x: float, langue: str) -> str:
    """Nombre cité dans une source : jusqu'à 4 décimales, sans zéros inutiles. Le tarif Stedin de 3,0966 €/kW/mois
    s'affichait « 3,10 », et 15 ans « 15,00 » (relecture de 05 h)."""
    texte = nombre(x, langue, 4)
    return texte.rstrip("0").rstrip(",") if "," in texte else texte


def source(cle: str, parametres: dict[str, Any], langue: str) -> str:
    """Texte d'une source dans la langue voulue. Une clé absente lève KeyError : jamais de repli silencieux."""
    valeurs = {k: (_nombre_source(v, langue) if isinstance(v, float) else nombre(v, langue) if type(v) is int else v)
               for k, v in (parametres or {}).items()}
    return SOURCES[langue][cle].format(**valeurs)


def champ_site(site: dict[str, Any], champ: str, langue: str) -> Any:
    traduit = ((site.get("traductions") or {}).get(langue) or {}).get(champ)
    return traduit if traduit is not None else site.get(champ)


# ---------------------------------------------------------------- graphiques SVG

def _reduire(valeurs: list[float], cible: int) -> list[float]:
    """Réduit une série en gardant le maximum de chaque paquet : les pointes restent visibles."""
    if len(valeurs) <= cible:
        return valeurs
    taille = len(valeurs) / cible
    return [max(valeurs[int(i * taille):max(int((i + 1) * taille), int(i * taille) + 1)]) for i in range(cible)]


def _haut_rond(valeur: float) -> float:
    """Borne haute de l'axe : quatre graduations d'un pas rond (1, 1,5, 2, 2,5 ou 5 fois une puissance de dix)."""
    if valeur <= 0:
        return 1.0
    pas_brut = valeur / 4
    puissance = 10 ** math.floor(math.log10(pas_brut))
    pas = next(f * puissance for f in (1, 1.5, 2, 2.5, 5, 10) if pas_brut <= f * puissance + 1e-12)
    return 4 * pas


def _axes(parts: list[str], haut: float, g: int, h: int, L: float, H: float) -> None:
    for k in range(5):
        y = h + H - H * k / 4
        parts.append(f"<line x1='{g}' x2='{g + L}' y1='{y:.1f}' y2='{y:.1f}' stroke='#e5e7eb'/>"
                     f"<text x='{g - 6}' y='{y + 4:.1f}' text-anchor='end' class='ax'>{f'{haut * k / 4:g}'.replace('.', ',')}</text>")


def courbe(series: list[tuple[list[float | None], str, str]], *, lignes: list[tuple[float, str, str]] = (),
           largeur: int = 760, hauteur: int = 230, graduations_x: list[tuple[float, str]] = (), titre: str = "",
           max_points: int = 900) -> str:
    """Courbes superposées ; `graduations_x` en fraction de la largeur (0 à 1)."""
    g, d, h, b = 46, 10, 12, 26
    tous = [v for s, _, _ in series for v in s if v is not None] + [v for v, _, _ in lignes]
    haut = _haut_rond(max(tous) * 1.04 if tous else 1)
    L, H = largeur - g - d, hauteur - h - b
    parts = [f"<svg viewBox='0 0 {largeur} {hauteur}' role='img' aria-label='{e(titre)}' class='graph'>"]
    _axes(parts, haut, g, h, L, H)
    for fx, etiquette in graduations_x:
        parts.append(f"<text x='{g + L * fx:.1f}' y='{hauteur - 8}' text-anchor='middle' class='ax'>{e(etiquette)}</text>")
    for valeurs, couleur, _ in series:
        v = _reduire([x if x is not None else 0 for x in valeurs], max_points)
        if len(v) < 2:
            continue
        pts = " ".join(f"{g + L * i / (len(v) - 1):.1f},{h + H - H * x / haut:.1f}" for i, x in enumerate(v))
        parts.append(f"<polyline fill='none' stroke='{couleur}' stroke-width='1.3' points='{pts}'/>")
    for valeur, etiquette, couleur in lignes:
        y = h + H - H * valeur / haut
        parts.append(f"<line x1='{g}' x2='{g + L}' y1='{y:.1f}' y2='{y:.1f}' stroke='{couleur}' stroke-dasharray='5 4'/>"
                     f"<text x='{g + L - 4}' y='{y - 5:.1f}' text-anchor='end' class='ax' fill='{couleur}'>{e(etiquette)}</text>")
    parts.append("</svg>")
    legende = "".join(f"<span><i style='background:{c}'></i>{e(nom)}</span>" for _, c, nom in series)
    return f"<figure>{''.join(parts)}<figcaption>{legende}</figcaption></figure>"


def barres(etiquettes: list[str], hautes: list[float], basses: list[float], noms: tuple[str, str],
           largeur: int = 760, hauteur: int = 210, couleurs: tuple[str, str] = (COULEURS["avant"], COULEURS["moyenne"])) -> str:
    g, d, h, b = 46, 10, 12, 26
    haut = _haut_rond(max(hautes) * 1.04)
    L, H = largeur - g - d, hauteur - h - b
    pas = L / len(etiquettes)
    parts = [f"<svg viewBox='0 0 {largeur} {hauteur}' class='graph' role='img'>"]
    _axes(parts, haut, g, h, L, H)
    for i, (et, a, m) in enumerate(zip(etiquettes, hautes, basses)):
        x, w = g + pas * i + pas * 0.15, pas * 0.34
        for j, (v, c) in enumerate(((a, couleurs[0]), (m, couleurs[1]))):
            parts.append(f"<rect x='{x + j * w:.1f}' y='{h + H - H * v / haut:.1f}' width='{w:.1f}' "
                         f"height='{H * v / haut:.1f}' fill='{c}'/>")
        parts.append(f"<text x='{g + pas * i + pas / 2:.1f}' y='{hauteur - 8}' text-anchor='middle' class='ax'>{e(et)}</text>")
    parts.append("</svg>")
    legende = (f"<span><i style='background:{couleurs[0]}'></i>{e(noms[0])}</span>"
               f"<span><i style='background:{couleurs[1]}'></i>{e(noms[1])}</span>")
    return f"<figure>{''.join(parts)}<figcaption>{legende}</figcaption></figure>"


def _graduations_mois(annuel: list[dict[str, Any]], langue: str) -> list[tuple[float, str]]:
    """Une étiquette au milieu de chaque mois présent, à sa vraie place dans la série des jours."""
    positions: dict[str, list[int]] = {}
    for i, jour in enumerate(annuel):
        positions.setdefault(jour["jour"][:7], []).append(i)
    n = max(len(annuel) - 1, 1)
    return [((sum(p) / len(p)) / n, MOIS[langue][int(m[5:]) - 1]) for m, p in positions.items()]


def _graduations_semaine(langue: str) -> list[tuple[float, str]]:
    return [((i + 0.5) / 7, j) for i, j in enumerate(JOURS[langue])]


def _graduations_jour() -> list[tuple[float, str]]:
    return [(h / 24, f"{h:02d}:00") for h in range(0, 25, 3)]


def _graduations_monotone(n_quarts: int, langue: str) -> list[tuple[float, str]]:
    heures = n_quarts / 4
    pas = 1000 if heures > 3000 else 100 if heures > 300 else 10
    return [(x / heures, f"{nombre(x, langue)} h") for x in range(0, int(heures) + 1, pas * 2)]


# ---------------------------------------------------------------- sections

def _ligne(libelle: str, valeur: str, nature: str | None, texte_source: str, langue: str) -> str:
    return (f"<tr><th>{e(libelle)}</th><td>{valeur}</td><td>{badge(nature, langue) if nature else ''}</td>"
            f"<td class='src'>{e(texte_source)}</td></tr>")


def _valeur(cle: str, g: dict[str, Any], langue: str, dec: int = 0) -> str:
    v = g.get("valeur")
    # Saisie de l'entreprise : rendue telle quelle, jamais lue comme une clé de texte (un EAN en texte faisait
    # planter le rapport, relecture de 05 h). EAN et SBI sont des identifiants, pas des nombres à formater.
    if g.get("nature") == "declare" and (isinstance(v, str) or cle in ("ean", "sbi")):
        return e(str(v))
    if g.get("nature") == "declare" and isinstance(v, list):  # plusieurs processus : une énumération, pas une fourchette
        return e(", ".join(str(x) for x in v))
    if isinstance(v, str):
        return e(source(v, g.get("parametres"), langue))
    if v is None:
        return "–"
    if cle in ("part_energie", "part_charge_pic"):
        return pourcent(v, langue)
    if isinstance(v, bool):
        return nombre(v, langue)
    return f"{nombre(v, langue, dec)} {e(unite(g.get('unite', ''), langue))}".strip()


def _grandeur(cle: str, g: dict[str, Any], langue: str, dec: int = 0) -> str:
    texte_source = source(g.get("source", ""), g.get("parametres"), langue) or (SOURCES[langue]["src_lu"] if g.get("nature") == "lu" else "")
    return _ligne(T[langue].get(cle, cle), _valeur(cle, g, langue, dec), g.get("nature"), texte_source, langue)


def _section_entreprise(r: dict[str, Any], langue: str) -> str:
    """Bijlage 4.12.1, article 1."""
    t, s, rac, site, ent = T[langue], r["statistiques"], r["raccordement"], r["site"], r["entreprise"]
    marge, reserve = r["marge_gtv"]["kw"], _reserve_pointe(r, langue)
    groupe = rac["categorie"] == "GROUPE"
    src_tarifs = source("src_tarif_groupe" if groupe else "src_tarifs", {"gestionnaire": rac["gestionnaire_tarifs"].capitalize()}, langue)
    categorie = t["cat_GROUPE"] if groupe else f"{t['cat_' + rac['categorie']]}, {rac['categorie_plage']}"
    if rac["categorie_nature"] != "tarif" and not groupe:
        categorie += f" ({t['estimee']})"
    if isinstance(ent["horaires_semaine"], str):
        horaires = e(ent["horaires_semaine"])
    else:
        horaires = "<br>".join(f"{JOURS[langue][h['jour']]} {h['debut']}–{h.get('fin') or ''}" if h.get("debut") else
                               f"{JOURS[langue][h['jour']]} –" for h in ent["horaires_semaine"])
    lignes = [
        _ligne(t["nom"], e(champ_site(site, "nom", langue) or "–"), None, "", langue),
        _ligne(t["secteur"], e(champ_site(site, "secteur", langue) or "–"), None, "", langue),
        _grandeur("ean", ent["ean"], langue), _grandeur("sbi", ent["sbi"], langue),
        _ligne(t["gestionnaire"], e(_majuscule(site.get("gestionnaire")) or t["non_fourni"]), "declare" if site.get("gestionnaire") else "hypothese",
               "" if rac["gestionnaire_nature"] == "declare" else
               source("gestionnaire_inconnu" if site.get("gestionnaire") else "gestionnaire_defaut", {}, langue), langue),
        _grandeur("gtv", ent["gtv_kw"], langue),
        _ligne(t["marge_gtv"], f"{nombre(marge['valeur'], langue, 1)} kW", "a_confirmer",
               t["reserve_marge"].format(gtv=nombre(ent["gtv_kw"]["valeur"], langue), pointe=nombre(s["pointe_kw"]["valeur"], langue),
                                         raison=reserve), langue) if reserve and marge["valeur"] is not None
        else _grandeur("marge_gtv", marge, langue),
        _grandeur("transport_autres", ent["transport_autres"], langue),
        _grandeur("changements_prevus", ent["changements_prevus"], langue),
        _ligne(t["capacite"], f"{nombre(rac['capacite_aansluiting_kva'], langue)} kVA" if rac["capacite_aansluiting_kva"]
               else t["non_fourni"], "declare" if rac["capacite_aansluiting_kva"] else None, "", langue),
        _ligne(t["source_profil"], e(champ_site(site, "source_profil", langue) or "–"), None,
               champ_site(site, "licence_profil", langue) or "", langue),
        _ligne(t["periode"], f"{e(s['debut'][:16].replace('T', ' '))} → {e(s['fin'][:16].replace('T', ' '))}", None, "", langue),
        _ligne(t["quarts"], nombre(s["quarts"], langue), s["energie_mwh"]["nature"], "", langue),
        _ligne(t["annee_rep"], e(t[{"recente": "annee_ok"}.get(s["representativite"]["statut"], "annee_" + s["representativite"]["statut"])].format(
            **s["representativite"]) + (t["annee_choisie_" + s["selection_annee"]["regle"]].format(
                annees=", ".join(map(str, s["selection_annee"]["annees"]))) if s.get("selection_annee")
                else t["annee_" + s["couverture"]["type"]].format(jours=nombre(s["couverture"]["jours"], langue))
                if s["couverture"]["type"] != "annee_civile" else "")),
               s["energie_mwh"]["nature"], t["annee_rep_src"], langue),
        _ligne(t["energie"], _valeur("energie", s["energie_mwh"], langue, 1), s["energie_mwh"]["nature"],
               SOURCES[langue]["src_lu"] if s["energie_mwh"]["nature"] == "lu" else "", langue),
        _grandeur("autres_energies", ent["autres_energies"], langue),
        _grandeur("heures_activite", ent["heures_activite"], langue),
        _ligne(t["horaires"], horaires, ent["horaires_nature"],
               "" if ent["horaires_nature"] == "declare" else source("src_horaires_estimes", {"seuil": ent["seuil_activite_kw"]}, langue),
               langue),
        _ligne(t["pointe"], f"{nombre(s['pointe_kw']['valeur'], langue)} kW, {e(s['instant_pointe'][:16].replace('T', ' '))}",
               "a_confirmer" if reserve else s["pointe_kw"]["nature"], reserve, langue),
        _grandeur("moyenne", s["moyenne_kw"], langue, 1),
        _grandeur("utilisation", s["heures_utilisation"], langue),
        _ligne(t["facteur"], nombre(s["facteur_charge"]["valeur"], langue, 3), s["facteur_charge"]["nature"], "", langue),
        _ligne(t["categorie"], e(categorie), rac["categorie_nature"], src_tarifs, langue),
        # La grille publiée est un tarif ; appliquée à un site dont le gestionnaire n'est pas connu, c'est une hypothèse.
        _ligne(t["tarif_kw"], f"{_nombre_source(rac['tarif_kw_contrat_an'], langue)} {t['par_an']}" if rac["tarif_kw_contrat_an"] else "–",
               "tarif" if rac["gestionnaire_nature"] == "declare" else "hypothese", src_tarifs, langue),
        _ligne(t["tarif_kwmax"], f"{_nombre_source(rac['tarif_kwmax_mois'], langue)} {t['par_mois']}" if rac["tarif_kwmax_mois"] else "–",
               "tarif" if rac["gestionnaire_nature"] == "declare" else "hypothese", src_tarifs, langue),
    ]
    alerte = ""
    if r["marge_gtv"].get("regle"):
        alerte = f"<p class='afaire'>{e(source(r['marge_gtv']['source'], {}, langue))} {badge('tarif', langue)}</p>"
    return f"<h2>{t['s1']}</h2>{_ref(1)}<table class='g'>{''.join(lignes)}</table>{alerte}"


def _ref(article: int) -> str:
    return f"<p class='ref'>Flex-e, bijlage 4.12.1, art. {article}</p>"


def _section_congestion(r: dict[str, Any], langue: str) -> str:
    """Bijlage 4.12.1, article 2 : capaciteitskaart et, s'il existe, le dernier congestierapport."""
    t, c = T[langue], r["congestion"]
    blocs = [f"<h2>{t['s2']}</h2>{_ref(2)}"]
    note = champ_site({**r["site"], "note_congestion": c.get("note_congestion")}, "note_congestion", langue)
    if note:
        blocs.append(f"<p>{e(note)}</p>")
    if any(c.get(k) for k in ("statut_zone_afname", "statut_zone_teruglevering")):
        blocs.append("<table class='g'>" + "".join(
            _ligne(t[k], e(c.get(champ) or "–"), "declare" if c.get(champ) else None, "capaciteitskaart.netbeheernederland.nl", langue)
            for k, champ in (("afname", "statut_zone_afname"), ("invoeding", "statut_zone_teruglevering"),
                             ("date_carte", "date_carte"), ("liberation", "annee_liberation_annoncee"))) + "</table>")
    else:
        blocs.append(f"<p class='afaire'>{e(t['congestion_vide'])}</p>")
    for champ, cle in (("congestierapport", "congestierapport"), ("besoin_flexibilite_zone", "besoin_zone")):
        if c.get(champ):
            blocs.append(f"<p><strong>{e(t[cle])}</strong>{' :' if langue == 'fr' else ':'} {e(c[champ])} {badge('declare', langue)}</p>")
        else:
            blocs.append(f"<p class='afaire'><strong>{e(t[cle])}</strong>{' :' if langue == 'fr' else ':'} {e(t[cle + '_vide'])}</p>")
    return "".join(blocs)


def _section_processus(r: dict[str, Any], langue: str) -> str:
    """Bijlage 4.12.1, article 3 : processus principaux, production ou conversion propre."""
    t, p = T[langue], r["processus"]
    lignes = [_grandeur("processus", p["description"], langue), _grandeur("production_propre", p["production_propre"], langue)]
    return f"<h2>{t['s3']}</h2>{_ref(3)}<table class='g'>{''.join(lignes)}</table>"


def _lignes_reference(r: dict[str, Any], langue: str) -> list[tuple[float, str, str]]:
    t = T[langue]
    plafond = r["plafond_kw"]["valeur"]
    lignes = [(plafond, f"{t['plafond']} {nombre(plafond, langue)} kW", COULEURS["plafond"])]
    gtv = r["raccordement"]["gtv_kw"]
    if gtv:
        lignes.append((gtv, f"GTV {nombre(gtv, langue)} kW", "#111827"))
    return lignes


def _section_pics_creux(r: dict[str, Any], langue: str) -> str:
    """Bijlage 4.12.1, article 4, a, 2° : analyse des pics et des creux, tirée du profil."""
    t, a = T[langue], r["pics_creux"]
    texte = t["analyse_txt"].format(
        n=nombre(a["quarts_top_1pct"], langue), part=pourcent(a["part_top_jours_ouvres"], langue),
        part_fenetre=pourcent(a.get("part_top_fenetre", 1.0), langue),
        h1=f"{a['heures_top_min']:02d}:00", h2=f"{a['heures_top_max']:02d}:00",
        mois_max=MOIS_LONG[langue][int(a["mois_pointe_max"]["mois"][5:]) - 1], kw_max=nombre(a["mois_pointe_max"]["max_kw"], langue),
        mois_min=MOIS_LONG[langue][int(a["mois_pointe_min"]["mois"][5:]) - 1], kw_min=nombre(a["mois_pointe_min"]["max_kw"], langue),
        ouvre=nombre(a["moyenne_jours_ouvres_kw"], langue), repos=nombre(a["moyenne_week_end_kw"], langue),
        nuit=nombre(a["moyenne_nuit_kw"], langue), base=nombre(a["charge_de_base_kw"], langue))
    pics = "".join(f"<tr><td>{e(p['instant'].replace('T', ' '))}</td><td>{nombre(p['kw'], langue)} kW</td></tr>" for p in a["pics"])
    return (f"<h3>{t['analyse_titre']}</h3><p>{e(texte)} {badge(r['statistiques']['energie_mwh']['nature'], langue)}</p>"
            f"<h4>{t['pics_titre']}</h4><table class='num'><tr><th>{t['instant']}</th><th>{t['pointe']}</th></tr>{pics}</table>")


def _section_profils(r: dict[str, Any], langue: str) -> str:
    """Bijlage 4.12.1, article 4 : profils annuel, mensuel, hebdomadaire, journalier au quart d'heure."""
    t, p, kw = T[langue], r["profils"], r["profil_kw"]
    ref = _lignes_reference(r, langue)
    annuel = courbe([([j["max_kw"] for j in p["annuel"]], COULEURS["avant"], t["max_jour"]),
                     ([j["moyenne_kw"] for j in p["annuel"]], COULEURS["moyenne"], t["moy_jour"])],
                    lignes=ref, graduations_x=_graduations_mois(p["annuel"], langue), titre=t["p_annuel"])
    mensuel_graph = barres([MOIS[langue][int(m["mois"][5:]) - 1] for m in p["mensuel"]],
                           [m["max_kw"] for m in p["mensuel"]], [m["moyenne_kw"] for m in p["mensuel"]], (t["max"], t["moy"]))
    mensuel_table = "".join(f"<tr><th>{e(m['mois'])}</th><td>{nombre(m['max_kw'], langue)} kW</td>"
                            f"<td>{nombre(m['moyenne_kw'], langue, 1)} kW</td><td>{nombre(m['energie_mwh'], langue, 1)} MWh</td></tr>"
                            for m in p["mensuel"])
    sp = p["semaine_pointe"]
    hebdo = courbe([([v for jour in p["semaine_type"] for v in jour], COULEURS["moyenne"], t["semaine_type"]),
                    (kw[sp["debut"]:sp["fin"]], COULEURS["avant"], f"{t['semaine_pointe']} ({sp['lundi']})")],
                   lignes=ref[:1], graduations_x=_graduations_semaine(langue), titre=t["p_hebdo"])
    jour = courbe([(p["jour_ouvre_moyen"], COULEURS["moyenne"], t["ouvre"]), (p["jour_repos_moyen"], COULEURS["repos"], t["repos"]),
                   (p["jour_pointe"]["kw"], COULEURS["avant"], f"{t['jour_pointe']} ({p['jour_pointe']['jour']})")],
                  lignes=ref[:1], graduations_x=_graduations_jour(), titre=t["p_jour"])
    monotone = courbe([(p["monotone"], COULEURS["avant"], t["courbe"])], lignes=ref,
                      graduations_x=_graduations_monotone(len(p["monotone"]), langue), titre=t["p_monotone"])
    return (f"<h2>{t['s4']}</h2>{_ref(4)}<h3>{t['p_annuel']}</h3>{annuel}<h3>{t['p_mensuel']}</h3>{mensuel_graph}"
            f"<table class='num'><tr><th>{t['mois']}</th><th>{t['max']}</th><th>{t['moy']}</th><th>{t['mwh']}</th></tr>"
            f"{mensuel_table}</table><h3>{t['p_hebdo']}</h3>{hebdo}<h3>{t['p_jour']}</h3>{jour}"
            f"<h3>{t['p_monotone']}</h3>{monotone}{_section_pics_creux(r, langue)}{_section_plafond(r, langue)}")


def _section_plafond(r: dict[str, Any], langue: str) -> str:
    t, ep = T[langue], r["episodes"]
    pointe = max(r.get("profil_mesures_kw") or r["profil_kw"])
    plafond = r["plafond_kw"]["valeur"]
    texte = t["plafond_txt"].format(plafond=nombre(plafond, langue), liberes=nombre(pointe - plafond, langue),
                                    pointe=nombre(pointe, langue), heures=nombre(ep["quarts"] / 4, langue, 2),
                                    episodes=nombre(ep["nombre"], langue), duree=nombre(ep["duree_max_h"], langue, 2),
                                    energie=nombre(ep["energie_kwh"], langue))
    src = source(r["plafond_kw"]["source"], r["plafond_kw"]["parametres"], langue)
    scen = r.get("scenario_croissance")
    bloc_scenario = ""
    if scen:
        desc = (((r["site"].get("traductions") or {}).get(langue) or {}).get("croissance_description")
                or scen.get("description") or t["projet_sans_nom"])
        texte_s = t["scenario_txt"].format(desc=desc, kw=nombre(scen["kw"], langue),
                                           debut=scen["debut"], fin=scen["fin"], jours=t["jours_" + scen["jours"]],
                                           mwh=nombre(scen["energie_ajoutee_mwh"], langue, 1), pointe=nombre(scen["pointe_scenario_kw"], langue),
                                           periode=t["eco_par_an" if r["statistiques"].get("duree_annuelle") else "eco_periode"],
                                           limite=nombre(scen["limite_kw"]["valeur"], langue))
        texte_s += (t["scenario_tient"] if scen["tient_sans_mesure"] else
                    t["scenario_depasse"].format(heures=nombre(scen["heures_au_dessus"], langue, 2), energie=nombre(scen["energie_au_dessus_kwh"], langue),
                                                periode=t["eco_par_an" if r["statistiques"].get("duree_annuelle") else "eco_periode"]))
        bloc_scenario = f"<h3>{t['scenario_titre']}</h3><p class='cle'>{e(texte_s)} {badge('simule', langue)}</p>"
    return (f"{bloc_scenario}<h3>{t['plafond_titre']}</h3><p>{e(texte)} {badge(r['plafond_kw']['nature'], langue)} "
            f"<span class='src'>{e(src)}</span></p>")


ORDRE_GRANDEURS = ["flex_kw", "part_charge_pic", "energie_mwh_an", "duree_h", "duree_besoin_h", "mise_en_route", "episodes", "heures_an", "part_energie",
                   "capacite_utile_kwh", "capacite_nominale_kwh", "cycles_equivalents_an", "niveau_ferme_kw", "remise_eur_an", "disponibilite",
                   "obligation_1mw", "sanction_sans_offre"]
DECIMALES = {"energie_mwh_an": 2, "duree_h": 2, "duree_besoin_h": 2, "retour_arbitrage_ans": 1, "heures_an": 2, "capacite_utile_kwh": 1, "capacite_nominale_kwh": 1,
             "cycles_equivalents_an": 1, "retour_ans": 1, "flex_kw": 1}


def _moments(o: dict[str, Any], langue: str) -> str:
    """Article 5, d : moments d'utilisation en semaine et en journée, au quart d'heure."""
    t, m = T[langue], o["moments"]
    series_semaine = [([v for jour in m["semaine_baisse"] for v in jour], COULEURS["apres"], t["baisse"])]
    series_jour = [(m["jour_baisse"], COULEURS["apres"], t["baisse"])]
    if any(v for v in m["jour_hausse"]):
        series_semaine.append(([v for jour in m["semaine_hausse"] for v in jour], COULEURS["moyenne"], t["hausse_" + o["id"]]
                               if "hausse_" + o["id"] in t else t["hausse"]))
        series_jour.append((m["jour_hausse"], COULEURS["moyenne"], t["hausse_" + o["id"]] if "hausse_" + o["id"] in t else t["hausse"]))
    return (f"<h4>{t['moments_semaine']}</h4>{courbe(series_semaine, graduations_x=_graduations_semaine(langue), max_points=672)}"
            f"<h4>{t['moments_jour']}</h4>{courbe(series_jour, graduations_x=_graduations_jour(), max_points=96)}")


def _profil_apres(r: dict[str, Any], apres: list[float], langue: str) -> str:
    """Article 5, f : profils annuel, mensuel, hebdomadaire et journalier après la mesure."""
    t, kw, p = T[langue], r.get("profil_mesures_kw") or r["profil_kw"], r["profils"]
    sp = p["semaine_pointe"]
    ligne = _lignes_reference(r, langue)[:1]
    scen = r.get("scenario_croissance")
    if scen and not scen["tient_sans_mesure"]:
        t = {**t, "avant": t["avant_croissance"]}
    jours_avant: dict[str, float] = {}
    jours_apres: dict[str, float] = {}
    mois_avant: dict[str, float] = {}
    mois_apres: dict[str, float] = {}
    jour_pointe = p["jour_pointe"]["jour"]
    avant_jour, apres_jour = [], []
    for x, y, fin in zip(kw, apres, r["horodatages"]):
        # Le quart qui finit à minuit appartient à la veille : on classe par début d'intervalle.
        cle = fin[:10] if fin[11:16] != "00:00" else _veille(fin[:10])
        jours_avant[cle] = max(jours_avant.get(cle, 0.0), x)
        jours_apres[cle] = max(jours_apres.get(cle, 0.0), y)
        mois_avant[cle[:7]] = max(mois_avant.get(cle[:7], 0.0), x)
        mois_apres[cle[:7]] = max(mois_apres.get(cle[:7], 0.0), y)
        if cle == jour_pointe:
            avant_jour.append(x)
            apres_jour.append(y)
    annee = courbe([(list(jours_avant.values()), COULEURS["avant"], t["avant"]),
                    (list(jours_apres.values()), COULEURS["apres"], t["apres"])],
                   lignes=ligne, graduations_x=_graduations_mois(p["annuel"], langue), titre=t["apres_annuel"])
    mois = barres([MOIS[langue][int(m[5:]) - 1] for m in mois_avant], list(mois_avant.values()), list(mois_apres.values()),
                  (t["avant"], t["apres"]), couleurs=(COULEURS["avant"], COULEURS["apres"]))
    semaine = courbe([(kw[sp["debut"]:sp["fin"]], COULEURS["avant"], t["avant"]),
                      (apres[sp["debut"]:sp["fin"]], COULEURS["apres"], t["apres"])],
                     lignes=ligne, graduations_x=_graduations_semaine(langue), titre=t["apres_hebdo"])
    jour = courbe([(avant_jour, COULEURS["avant"], t["avant"]), (apres_jour, COULEURS["apres"], t["apres"])],
                  lignes=ligne, graduations_x=_graduations_jour(), titre=t["apres_jour"], max_points=96)
    return (f"<h4>{t['apres_annuel']}</h4>{annee}<h4>{t['apres_mensuel']}</h4>{mois}"
            f"<h4>{t['apres_hebdo']} ({sp['lundi']})</h4>{semaine}<h4>{t['apres_jour']} ({jour_pointe})</h4>{jour}")


def _usure(u: dict[str, Any], langue: str) -> str:
    """Priorité 4 de Vincent (27/09) : cycles comptés par rainflow, sans taux de vieillissement inventé."""
    t = T[langue]
    classes = "".join(f"<tr><td>{pourcent(c['de'], langue)}{t['conf_a']}{pourcent(c['a'], langue)}</td><td>{nombre(c['cycles'], langue, 1)}</td></tr>"
                      for c in u["classes"])
    lignes = [_grandeur("usure_pleins", u["cycles_pleins"], langue, 1),
              _ligne(t["usure_max"], pourcent(u["profondeur_max"]["valeur"], langue), "simule",
                     source(u["profondeur_max"]["source"], {}, langue), langue)]
    if u.get("cycles_arbitrage_an"):
        lignes.append(_grandeur("usure_arbitrage", u["cycles_arbitrage_an"], langue))
    lignes += [_grandeur("usure_vie", u["duree_vie_ans"], langue, 1), _grandeur("usure_fin", u["nominale_fin_vie_kwh"], langue, 1)]
    return (f"<h4>{e(t['usure_titre'])}</h4><p class='src'>{e(t['usure_txt'])}</p><table class='num'><tr><th>{t['usure_classe']}</th>"
            f"<th>{t['usure_cycles']}</th></tr>{classes}</table><table class='g'>{''.join(lignes)}</table>")


def _veille(jour: str) -> str:
    return (date.fromisoformat(jour) - timedelta(days=1)).isoformat()


def _section_mesures(r: dict[str, Any], langue: str) -> str:
    """Bijlage 4.12.1, article 5 : pour chaque mesure, les grandeurs a à f."""
    t = T[langue]
    fenetre_h = r["hypotheses"]["fenetre_decalage_h"]["valeur"]
    fenetre = nombre(fenetre_h, langue, 1 if fenetre_h % 1 else 0)
    blocs = [f"<h2>{t['s5']}</h2>{_ref(5)}<p>{e(t['mesures_intro'])}</p>"]
    if _reserve_pointe(r, langue):
        blocs.append(f"<p class='afaire'>{e(t['reserve_suite'].format(raison=_reserve_pointe(r, langue)))}</p>")
    for i, (cle, o) in enumerate(r["options"].items(), 1):
        blocs.append(f"<h3>5.{i} {e(t['o_' + cle])}</h3><p>{e(t['principe_' + cle].format(fenetre=fenetre))}</p>")
        if o.get("faisable") is False and "raison" in o:
            # La raison du moteur est rédigée en français : le rapport NL donne sa propre phrase (relecture de 05 h).
            raison = o["raison"] if langue == "fr" else t["raison_infaisable"]
            blocs.append(f"<p class='afaire'>{e(raison)}</p>")
            continue
        lignes = [f"<tr class='entete'><th>{t['grandeur']}</th><th>{t['valeur']}</th><th>{t['nature']}</th><th>{t['source']}</th></tr>"]
        for g in ORDRE_GRANDEURS:
            if isinstance(o.get(g), dict) and "nature" in o[g]:
                ligne = _grandeur(g, o[g], langue, DECIMALES.get(g, 0))
                if cle == "contrat" and g == "flex_kw":
                    ligne = ligne.replace(f"<th>{e(t['flex_kw'])}</th>", f"<th>{e(t['flex_kw_contrat'])}</th>", 1)
                if cle == "contrat" and g == "duree_h":
                    ligne = ligne.replace(f"<th>{e(t['duree_h'])}</th>", f"<th>{e(t['duree_contrat'])}</th>", 1)
                lignes.append(ligne)
        blocs.append(f"<table class='g'>{''.join(lignes)}</table>")
        if cle == "batterie" and o.get("usure"):
            blocs.append(_usure(o["usure"], langue))
        if cle == "contrat":
            entete = (f"<tr><th>{t['part_pointe']}</th><th>{t['niveau']}</th><th>{t['heures_dessus']}</th>"
                      f"<th>{t['energie_dessus']}</th></tr>")
            corps = "".join(f"<tr><td>{pourcent(n['part_pointe'], langue)}</td><td>{nombre(n['niveau_kw'], langue)} kW</td>"
                            f"<td>{nombre(n['heures_au_dessus'], langue, 2)} h</td>"
                            f"<td>{nombre(n['energie_au_dessus_mwh'], langue, 2)} MWh</td></tr>" for n in o["niveaux"])
            blocs.append(f"<h4>{t['niveaux']}</h4><table class='num'>{entete}{corps}</table>")
            if o.get("blocs"):
                corps_b = "".join(f"<tr><td>{e(t['bloc_' + b['bloc']])}</td><td>{nombre(b['pointe_kw'], langue)} kW</td>"
                                  f"<td>{nombre(b['energie_mwh'], langue, 1)} MWh</td><td>{pourcent(b['part_energie'], langue)}</td></tr>"
                                  for b in o["blocs"])
                blocs.append(f"<h4>{t['blocs_titre']}</h4><p class='src'>{e(t['blocs_txt'])}</p><table class='num'>"
                             f"<tr><th>{t['bloc']}</th><th>{t['pointe']}</th><th>{t['energie']}</th><th>{t['part_energie']}</th></tr>"
                             f"{corps_b}</table>")
        if "moments" in o:
            blocs.append(_moments(o, langue))
        else:
            blocs.append(f"<p class='afaire'>{e(t['moments_offre'])}</p>")
        if "profil_apres" in o:
            blocs.append(_profil_apres(r, o["profil_apres"], langue))
    return "".join(blocs)


def _section_financiere(r: dict[str, Any], langue: str) -> str:
    """Bijlage 4.12.1, article 6 (version 2026) : investissement et eenvoudige terugverdientijd (ETVT)."""
    t = T[langue]
    entete = (f"<tr><th>{t['option']}</th><th>{t['investissement_eur']}</th><th>{t['economie']}</th>"
              f"<th>{t['retour_ans']}</th><th>{t['tranche_etvt']}</th><th>{t['autres_montants']}</th></tr>")
    lignes = []
    for cle, o in r["options"].items():
        inv = o.get("investissement_eur")
        eco = (o.get("economie") or {}).get("eur_an")
        ret = o.get("retour_ans")
        cellule = lambda g, c: (f"{_valeur(c, g, langue, DECIMALES.get(c, 0))}<br>{badge(g['nature'], langue)}"
                                f"<br><span class='src'>{e(source(g.get('source', ''), g.get('parametres'), langue))}</span>"
                                if isinstance(g, dict) else "–")
        tranches = " / ".join(t["etvt_" + x] for x in (ret or {}).get("parametres", {}).get("tranches", [])) or "–"
        deux_points = " : " if langue == "fr" else ": "
        autres = [f"{t[c]}{deux_points}{_valeur(c, o[c], langue, DECIMALES.get(c, 0))} {badge(o[c]['nature'], langue)}" for c in ("arbitrage_eur_an", "retour_arbitrage_ans", "cout_perte", "remise", "remise_eur_an", "remuneration")
                  if isinstance(o.get(c), dict)]
        lignes.append(f"<tr><th>{e(t['o_' + cle])}</th><td>{cellule(inv, 'investissement_eur')}</td>"
                      f"<td>{cellule(eco, 'economie')}</td><td>{cellule(ret, 'retour_ans')}</td><td>{e(tranches)}</td>"
                      f"<td>{'<br>'.join(autres) or '–'}</td></tr>")
    # Audit O14 : l'aide aux mesures a un minimum de 25 000 € (RVO) ; on situe la batterie du scan par rapport à lui.
    inv = (r["options"]["batterie"].get("investissement_eur") or {}).get("valeur")
    phrase = ""
    if isinstance(inv, list) and inv[1]:
        a1, a2 = min(0.4 * inv[0], 300_000), min(0.4 * inv[1], 300_000)
        cle = ("financement_batterie_sous_minimum" if a2 < 25_000 else "financement_batterie_partiel" if a1 < 25_000
               else "financement_batterie_eligible")
        phrase = t[cle].format(bas=nombre(inv[0], langue), haut=nombre(inv[1], langue), a1=nombre(round(a1), langue),
                               a2=nombre(round(a2), langue))
    financement = (f"<h3>{t['financement_titre']}</h3><p>{e(t['financement_txt'] + phrase)} {badge('tarif', langue)} "
                   f"<span class='src'>{e(source('src_flex_e', {}, langue))}</span></p>")
    intro = (t["financiere_intro_groupe"] if r["raccordement"]["categorie"] == "GROUPE" else
             t["financiere_intro"].format(gestionnaire=r["raccordement"]["gestionnaire_tarifs"].capitalize()))
    if r.get("scenario_croissance"):
        intro += t["financiere_projet"]
    return (f"<h2>{t['s6']}</h2>{_ref(6)}<p>{e(intro)}</p>"
            f"<div class='defile'><table class='comp'>{entete}{''.join(lignes)}</table></div>{financement}")


def _valeurs_texte(r: dict[str, Any], langue: str) -> dict[str, str]:
    t, o = T[langue], r["options"]
    bat, dec, ecr, con = (o[k] for k in ("batterie", "decalage", "ecretage", "contrat"))
    retour_bat = (bat.get("retour_ans") or {}).get("valeur") or [None, None]
    annuel = ((bat.get("economie") or {}).get("eur_an") or {}).get("unite", "€/an") == "€/an"
    return {
        "par_an": t["eco_par_an"] if annuel else t["eco_periode"],
        "episodes": nombre(dec["episodes"]["valeur"], langue), "duree": nombre(dec["duree_h"]["valeur"], langue, 2),
        "fenetre": nombre(r["hypotheses"]["fenetre_decalage_h"]["valeur"], langue, 1 if r["hypotheses"]["fenetre_decalage_h"]["valeur"] % 1 else 0),
        "part": pourcent(dec.get("part_reportee", 0), langue),
        "mwh": nombre(ecr["energie_mwh_an"]["valeur"], langue, 2), "pct": pourcent(ecr["part_energie"]["valeur"], langue),
        "heures": nombre(ecr["heures_an"]["valeur"], langue, 2),
        "eco": nombre((bat.get("economie") or {}).get("eur_an", {}).get("valeur"), langue),
        "nominale": nombre((bat.get("capacite_nominale_kwh") or {}).get("valeur"), langue),
        "dim": t["dim_" + bat.get("dimensionnement", "energie")],
        "ans_bas": nombre(retour_bat[0], langue, 1), "ans_haut": nombre(retour_bat[-1], langue, 1),
        "niveau": nombre(con["niveau_ferme_kw"]["valeur"], langue),
    }


def _section_conclusion(r: dict[str, Any], langue: str) -> str:
    """Bijlage 4.12.1, article 7 : avantages, inconvénients, conclusion ; et la préférence de l'entreprise (RVO)."""
    t, o = T[langue], r["options"]
    commun = _valeurs_texte(r, langue)
    flex = lambda cle: nombre((o[cle].get("flex_kw") or {}).get("valeur"), langue, 1)
    voor_nadelen = "".join(
        f"<tr><th>{e(t['o_' + cle])}</th><td>{e(t['voor_' + cle].format(**commun, flex=flex(cle)))}</td>"
        f"<td>{e(t['nadeel_' + cle + ('_impossible' if cle == 'batterie' and o[cle].get('faisable') is False else '')].format(**commun, flex=flex(cle)))}</td></tr>"
        for cle in o)
    ra = (o["batterie"].get("retour_arbitrage_ans") or {}).get("valeur")
    phrase_arbitrage = (t["reco_arbitrage"].format(arb=nombre(o["batterie"]["arbitrage_eur_an"]["valeur"], langue),
                                                   a1=nombre(ra[0], langue, 1), a2=nombre(ra[1], langue, 1)) if ra else "")
    items = "".join(f"<li><strong>{e(t['o_' + l['option']])}.</strong> {e(t[l['cle']].format(**commun, flex=flex(l['option'])))}"
                    f"{e(phrase_arbitrage) if l['option'] == 'batterie' else ''}</li>" for l in r["recommandation"])
    premiere = r["recommandation"][0]["option"]
    c, scen = r["croissance"], r.get("scenario_croissance")
    if scen:
        cle_s = "croissance_scenario_tient" if scen["tient_sans_mesure"] else "croissance_scenario"
        texte_croissance = t[cle_s].format(kw=nombre(scen["kw"], langue), limite=nombre(scen["limite_kw"]["valeur"], langue),
                                           option=t["o_" + premiere].lower())
    elif c.get("depassement_kw"):
        cle_d = "croissance_depasse" if c["total_kw"]["valeur"] > 0 else "croissance_depasse_reste"
        texte_croissance = t[cle_d].format(gtv=nombre(c["gtv_kw"], langue), dep=nombre(c["depassement_kw"], langue, 1),
                                           plafond=nombre(r["plafond_kw"]["valeur"], langue), total=nombre(c["total_kw"]["valeur"], langue, 1))
        texte_croissance += " " + t["croissance_valeur"].format(eco=commun["eco"], par_an=commun["par_an"])
    else:
        texte_croissance = t["croissance_txt"].format(plafond=nombre(r["plafond_kw"]["valeur"], langue), liberes=nombre(c["liberes_kw"], langue, 1))
        if c["marge_gtv_kw"] is not None:
            texte_croissance += t["croissance_gtv"].format(marge=nombre(c["marge_gtv_kw"], langue, 1), total=nombre(c["total_kw"]["valeur"], langue, 1))
        texte_croissance += " " + t["croissance_valeur"].format(eco=commun["eco"], par_an=commun["par_an"])
    if r.get("contrat_groupe"):
        texte_croissance += " " + t["groupe_condition"]
    reserve = _reserve_pointe(r, langue)
    if reserve:
        texte_croissance += " " + t["croissance_reserve"].format(raison=reserve)
    bloc_croissance = (f"<h3>{t['croissance_titre']}</h3><p class='cle'>{e(texte_croissance)} {badge('simule', langue)}</p>")
    preference = _grandeur("preference", r["preference"], langue)
    return (f"<h2>{t['s7']}</h2>{_ref(7)}<div class='defile'><table class='vn'><tr><th>{t['option']}</th><th>{t['voordelen']}</th><th>{t['nadelen']}</th></tr>"
            f"{voor_nadelen}</table></div>{_section_comparaison(r, langue)}{bloc_croissance}<h3>{t['conclusion_titre']}</h3>"
            f"<p>{e(t['conclusion_txt'].format(option=t['o_' + premiere].lower()))}</p>"
            + (f"<p class='afaire'>{e(t['reserve_suite'].format(raison=reserve))}</p>" if reserve else "")
            + f"<p>{e(t['reco_intro'])}</p><ol>{items}</ol>"
            f"<table class='g'>{preference}</table>")


def _section_comparaison(r: dict[str, Any], langue: str) -> str:
    t = T[langue]
    colonnes = ["flex_kw", "energie_mwh_an", "duree_h", "investissement_eur", "economie", "retour_ans"]
    entete = f"<tr><th>{t['option']}</th>" + "".join(f"<th>{t[c]}</th>" for c in colonnes) + f"<th>{t['faisable']}</th></tr>"
    lignes = []
    for cle, o in r["options"].items():
        cellules = []
        for c in colonnes:
            g = o["economie"]["eur_an"] if c == "economie" and "economie" in o else o.get(c)
            if not isinstance(g, dict):
                cellules.append("<td>–</td>")
                continue
            texte = _valeur(c, g, langue, DECIMALES.get(c, 0))
            if c == "flex_kw" and isinstance(g.get("valeur"), (int, float)):
                texte += f"<br><span class='src'>{nombre(g['valeur'] / 1000, langue, 3)} MW</span>"
                if cle == "contrat":
                    texte += f"<br><span class='src'>{e(source('part_alternative', {}, langue))}</span>"
            cellules.append(f"<td>{texte}<br>{badge(g['nature'], langue)}</td>")
        faisable = {True: t["oui"], False: t["non"], None: t["a_voir"]}[o.get("faisable")]
        lignes.append(f"<tr><th>{e(t['o_' + cle])}</th>{''.join(cellules)}<td>{faisable}</td></tr>")
    return f"<h3>{t['comparaison_titre']}</h3><div class='defile'><table class='comp'>{entete}{''.join(lignes)}</table></div>"


# Noms lisibles des hypothèses : le rapport NL affichait les clés françaises du code (troisième relecture, point 12).
NOMS_HYPOTHESES = {
    "fr": {"heures_ecretees": "Heures écrêtées pour fixer le plafond", "rendement_aller_retour": "Rendement aller-retour de la batterie",
           "profondeur_decharge": "Profondeur de décharge", "puissance_sur_capacite_max": "Puissance maximale par kWh de capacité",
           "prix_batterie_eur_kwh": "Prix de la batterie installée", "fenetre_decalage_h": "Fenêtre de décalage des charges"},
    "nl": {"heures_ecretees": "Afgetopte uren voor het bepalen van de grens", "rendement_aller_retour": "Rendement heen en terug van de batterij",
           "profondeur_decharge": "Ontladingsdiepte", "puissance_sur_capacite_max": "Maximaal vermogen per kWh capaciteit",
           "prix_batterie_eur_kwh": "Prijs van de geïnstalleerde batterij", "fenetre_decalage_h": "Venster voor het verschuiven van lasten"},
}


def _majuscule(texte: str | None) -> str | None:
    """« liander » devient « Liander » sans toucher au reste (« TenneT » reste « TenneT »)."""
    return texte[:1].upper() + texte[1:] if texte else texte


def _section_hypotheses(r: dict[str, Any], langue: str) -> str:
    t = T[langue]
    lignes = [f"<tr class='entete'><th>{t['hyp']}</th><th>{t['valeur']}</th><th>{t['pourquoi']}</th></tr>"]
    for cle, h in r["hypotheses"].items():
        v = h["valeur"]
        texte = "–" if v is None else nombre(v, langue, 2)
        pourquoi = h.get("source") or source(h.get("source_cle") or "hyp_" + cle, {}, langue)
        nom = NOMS_HYPOTHESES[langue].get(cle)
        lignes.append(f"<tr><td>{e(nom) if nom else f'<code>{e(cle)}</code>'}</td><td>{texte} {e(unite(h.get('unite', ''), langue))}</td>"
                      f"<td class='src'>{e(pourquoi)}</td></tr>")
    sens = r.get("sensibilite") or {}
    blocs = [f"<h2>{t['s8']}</h2><table class='g'>{''.join(lignes)}</table>", f"<h3>{t['sens_titre']}</h3><p>{e(t['sens_txt'])}</p>"]
    if sens.get("fenetres"):
        def complement(f: dict[str, Any]) -> str:
            c = f.get("batterie_complement")
            if f["faisable"] or not c:
                return "–"
            if not c.get("faisable"):
                return t["complement_impossible"]
            return t["complement_txt"].format(kw=nombre(c["puissance_kw"], langue, 1), kwh=nombre(c["nominale_kwh"], langue, 1))
        corps = "".join(f"<tr><td>± {nombre(f['heures'], langue)} h</td><td>{pourcent(f['part_reportee'], langue)}</td>"
                        f"<td>{t['oui'] if f['faisable'] else t['non']}</td><td>{e(complement(f))}</td></tr>" for f in sens["fenetres"])
        blocs.append(f"<h4>{t['sens_fenetre']}</h4><table class='num'><tr><th>{t['fenetre']}</th><th>{t['part_placee']}</th>"
                     f"<th>{t['suffit']}</th><th>{t['complement']}</th></tr>{corps}</table>")
    if sens.get("c_rates"):
        corps = "".join(f"<tr><td>{nombre(c['c_rate'], langue, 1)} C</td><td>{nombre(c['nominale_kwh'], langue, 1)} kWh</td>"
                        f"<td>{t['dimtab_' + c['dimension']]}</td><td>{nombre(c.get('investissement_eur'), langue)} €</td></tr>"
                        for c in sens["c_rates"])
        blocs.append(f"<h4>{t['sens_crate']}</h4><table class='num'><tr><th>C-rate</th><th>{t['capacite_nominale_kwh']}</th>"
                     f"<th>{t['dimension_par']}</th><th>{t['investissement_eur']}</th></tr>{corps}</table>")
    blocs.append(_confiance(r, langue))
    return "".join(blocs)


def _confiance(r: dict[str, Any], langue: str) -> str:
    """Priorité 3 de Vincent (27/09) : niveau de confiance par rééchantillonnage des jours, avec ses limites."""
    c = r.get("confiance")
    if not c:
        return ""
    t = T[langue]
    plafond = nombre(r["plafond_kw"]["valeur"], langue)
    texte = t["conf_txt"].format(tirages=nombre(c["tirages"], langue))
    if c["jours_gardes"]:
        texte += t["conf_gardes"].format(n=nombre(c["jours_gardes"], langue))
    def ligne(libelle: str, g: dict[str, Any], unite_txt: str, dec: int) -> str:
        mesure = t["conf_impossible"] if g["mesure"] is None else f"{nombre(g['mesure'], langue, dec)} {unite_txt}"
        if "p5" not in g:
            return f"<tr><td>{e(libelle)}</td><td>{mesure}</td><td>–</td><td>–</td></tr>"
        return (f"<tr><td>{e(libelle)}</td><td>{mesure}</td><td>{nombre(g['mediane'], langue, dec)} {unite_txt}</td>"
                f"<td>{nombre(g['p5'], langue, dec)}{t['conf_a']}{nombre(g['p95'], langue, dec)} {unite_txt}</td></tr>")
    h = r["hypotheses"]
    corps = (ligne(t["conf_niveau"].format(heures=nombre(h["heures_ecretees"]["valeur"], langue)), c["niveau_heures_kw"], "kW", 0)
             + ligne(t["conf_heures"].format(plafond=plafond), c["heures_au_dessus"], e(unite("h", langue)), 2)
             + ligne(t["conf_batterie"].format(plafond=plafond), c["batterie_kwh"], "kWh", 1)
             + (f"<tr><td>{e(t['conf_batterie_impossible'].format(plafond=plafond))}</td>"
                f"<td>{nombre(c['batterie_kwh']['mesure'] is None, langue)}</td><td>–</td>"
                f"<td>{e(t['conf_part'].format(pct=pourcent(c['batterie_impossible_part'], langue)))}</td></tr>"
                if c.get("batterie_impossible_part") or c["batterie_kwh"]["mesure"] is None else "")
             + f"<tr><td>{e(t['conf_decalage'].format(fenetre=nombre(h['fenetre_decalage_h']['valeur'], langue, 1 if h['fenetre_decalage_h']['valeur'] % 1 else 0)))}</td>"
               f"<td>{nombre(bool(r['options']['decalage']['faisable']), langue)}</td><td>–</td>"
               f"<td>{e(t['conf_part'].format(pct=pourcent(c['decalage_suffisant_part'], langue)))}</td></tr>")
    return (f"<h3>{t['conf_titre']}</h3><p>{e(texte)} {badge('simule', langue)}</p><div class='defile'><table class='num'>"
            f"<tr><th>{t['conf_grandeur']}</th><th>{t['conf_mesure_projet' if r.get('scenario_croissance') else 'conf_mesure']}</th>"
            f"<th>{t['conf_mediane']}</th><th>{t['conf_intervalle']}</th></tr>"
            f"{corps}</table></div><p class='src'>{e(t['conf_limites'])}</p>")


# ---------------------------------------------------------------- conformité au format Flex-e

ETATS = {"fr": {"fourni": "Fourni", "calcule": "Calculé", "a_completer": "À compléter", "a_faire": "À faire sur place"},
         "nl": {"fourni": "Aangeleverd", "calcule": "Berekend", "a_completer": "Aan te vullen", "a_faire": "Ter plaatse te doen"}}
ELEMENTS_FLEXE = {
    "fr": {"0": "Visite du site par l'energieadviseur", "1a": "Codes EAN", "1b": "Codes SBI",
           "1c": "Transport contracté (électricité, gaz, autres) et changements prévus",
           "1d": "Consommation d'une année représentative des trois dernières", "1e": "Heures d'activité et horaires de la semaine",
           "2": "Congestion : capaciteitskaart et dernier congestierapport", "3": "Processus principaux et production propre",
           "4a": "Profils annuel, mensuel, hebdomadaire et journalier au quart d'heure", "4b": "Analyse des pics et des creux",
           "4c": "Gaz, chaleur et autres énergies", "5abc": "Par mesure : MW, MWh par an, durée continue",
           "5d": "Par mesure : moments d'utilisation (semaine et journée)", "5e": "Par mesure : mise en route et arrêt",
           "5f": "Par mesure : profils après la mesure", "6": "Investissement et ETVT par mesure",
           "7": "Avantages, inconvénients et conclusion", "7p": "Préférence de l'entreprise (page RVO)"},
    "nl": {"0": "Locatiebezoek door de energieadviseur", "1a": "EAN-codes", "1b": "SBI-codes",
           "1c": "Gecontracteerd transport (elektriciteit, gas, overig) en geplande wijzigingen",
           "1d": "Verbruik van een representatief jaar van de afgelopen drie jaren", "1e": "Bedrijfsuren en bedrijfstijden per week",
           "2": "Congestie: capaciteitskaart en meest recente congestierapport", "3": "Hoofdprocessen en eigen opwek",
           "4a": "Jaar-, maand-, week- en dagprofiel op kwartierbasis", "4b": "Analyse van pieken en dalen",
           "4c": "Aardgas, warmte en andere energiedragers", "5abc": "Per maatregel: MW, MWh per jaar, aaneengesloten duur",
           "5d": "Per maatregel: inzetmomenten (week en dag)", "5e": "Per maatregel: op- en afregelprocedure",
           "5f": "Per maatregel: profielen na de maatregel", "6": "Investering en ETVT per maatregel",
           "7": "Voor- en nadelen en conclusie", "7p": "Voorkeur van het bedrijf (RVO-pagina)"},
}


def conformite(r: dict[str, Any]) -> list[tuple[str, str]]:
    """État de chaque élément de la bijlage 4.12.1 : fourni, calculé, à compléter, ou à faire sur place."""
    ent, proc, s, c, o = r["entreprise"], r["processus"], r["statistiques"], r["congestion"], r["options"]
    fourni = lambda g: "fourni" if g.get("nature") == "declare" else "a_completer"
    mesures = [o[k] for k in ("batterie", "decalage", "ecretage")]
    chiffre = all(m.get("investissement_eur", {}).get("nature") != "a_chiffrer" for m in mesures)
    # Rubriques annuelles 1d et 4a : « een representatief jaar van de afgelopen drie jaren » (RVO), donc une année civile
    # complète ET récente ; une année future, en cours ou ancienne reste à compléter (revue d'Astra de f0eb305).
    annuelle = "calcule" if s["annee_complete"] and s["representativite"]["dans_les_3_ans"] else "a_completer"
    return [
        ("0", "a_faire"),
        ("1a", fourni(ent["ean"])), ("1b", fourni(ent["sbi"])),
        ("1c", "fourni" if ent["gtv_kw"].get("nature") == "declare" and ent["changements_prevus"].get("nature") == "declare"
         else "a_completer"),
        ("1d", annuelle),
        ("1e", "fourni" if ent["heures_activite"].get("nature") == "declare" else "calcule"),
        ("2", "fourni" if c.get("statut_zone_afname") and c.get("congestierapport") else "a_completer"),
        ("3", "fourni" if proc["description"].get("nature") == "declare" and proc["production_propre"].get("nature") == "declare"
         else "a_completer"),
        ("4a", annuelle), ("4b", "calcule"),
        ("4c", fourni(ent["autres_energies"])),
        ("5abc", "calcule"), ("5d", "calcule"),
        ("5e", "a_completer" if any(m.get("mise_en_route", {}).get("nature") == "a_chiffrer" for m in mesures) else "calcule"),
        ("5f", "calcule"), ("6", "calcule" if chiffre else "a_completer"),
        ("7", "calcule"), ("7p", fourni(r["preference"])),
    ]


def etapes(r: dict[str, Any]) -> list[str]:
    """Prochaines étapes concrètes, tirées de ce qui reste à compléter et des mesures : des clés de texte."""
    etats = dict(conformite(r))
    o = r["options"]
    cles = ["etape_visite"]
    if any(etats[k] == "a_completer" for k in ("1a", "1b", "1c", "3", "4c")):
        cles.append("etape_pieces")
    if etats["1d"] == "a_completer":
        cles.append("etape_annee")
    if etats["2"] == "a_completer":
        cles.append("etape_carte")
    if o["decalage"].get("faisable") or o["decalage"].get("part_reportee", 0) >= 0.5:  # décalage seul ou en combinaison
        cles.append("etape_process")
    if o["batterie"].get("faisable"):
        cles.append("etape_devis")
    cles.append("etape_gestionnaire")
    obligation, raison = o["offre_gestionnaire"]["obligation_1mw"].get("valeur"), o["offre_gestionnaire"]["obligation_1mw"].get("source")
    if obligation or (obligation is None and raison != "src_reg009_groupe"
                      and (raison == "src_reg009_a_verifier" or r["statistiques"]["pointe_kw"]["valeur"] >= 1000)):
        cles.append("etape_1mw")
    cles.append("etape_flexe")
    return cles


def _section_etapes(r: dict[str, Any], langue: str) -> str:
    t = T[langue]
    items = "".join(f"<li>{e(t[c])}</li>" for c in etapes(r))
    return f"<h2>{t['etapes_titre']}</h2><ol>{items}</ol>"


T["fr"].update({
    "qd_titre": "Les quarts d'heure qui décident",
    "qd_intro": ("Quelques quarts d'heure de l'année fixent la capacité demandée au réseau et la taille de la batterie. "
                 "Les chiffres ci-dessous disent ce que deviendraient ces grandeurs si ces quarts d'heure-là avaient été plus "
                 "bas. C'est un calcul sur le profil, pas une recommandation."),
    "qd_pointe": "La pointe de {kw} kW, le {jour} à {heure}, est atteinte {n} quarts d'heure {periode}.",
    "qd_pointe_une": "La pointe de {kw} kW, le {jour} à {heure}, n'est atteinte qu'un quart d'heure {periode}.",
    "qd_pointe_projet": "Avec le projet, la pointe serait de {kw} kW, le {jour} à {heure}, atteinte {n} quarts d'heure {periode}.",
    "qd_pointe_une_projet": "Avec le projet, la pointe serait de {kw} kW, le {jour} à {heure}, atteinte un seul quart d'heure {periode}.",
    "qd_annee": "dans l'année", "qd_periode": "sur la période",
    "qd_cap_quarts": "Quarts d'heure les plus hauts", "qd_cap_duree": "Durée", "qd_cap_jours": "Jours concernés",
    "qd_cap_pointe": "Pointe s'ils étaient au niveau suivant", "qd_cap_baisse": "Baisse de la pointe",
    "qd_bat_txt": ("{jours} jours dépassent le plafond visé de {plafond} kW, et la batterie de {nominale} kWh (option 5.1) "
                   "est dimensionnée sur eux. Les jours sont classés selon la batterie que chacun demanderait seul (énergie "
                   "au-dessus du plafond ou puissance, la plus exigeante des deux) ; ramener un jour au plafond ne réduit la "
                   "batterie que si c'est lui qui la dimensionne, une ligne peut donc ne rien changer. Si les jours les plus "
                   "lourds avaient été ramenés au plafond :"),
    "qd_bat_retires": "Jours ramenés au plafond", "qd_bat_puissance": "Puissance", "qd_bat_nominale": "Capacité nominale",
    "qd_bat_baisse": "Baisse de la batterie", "qd_bat_invest": "Investissement indicatif", "qd_aucun": "aucun jour (référence)",
    "qd_zero": "Aucune batterie ne serait nécessaire pour tenir {plafond} kW si {conditions}.",
    "qd_condition": "la pointe du {jour} était {pct} plus basse",
    "qd_zero_beaucoup": "Pour se passer de batterie, ces {jours} jours devraient tous rester sous {plafond} kW. Les plus lourds :",
    "qd_j_jour": "Jour", "qd_j_pointe": "Pointe du jour", "qd_j_quarts": "Quarts d'heure au-dessus",
    "qd_j_energie": "Énergie au-dessus", "qd_j_baisse": "Baisse de pointe nécessaire ce jour-là",
    "qd_prudence": ("Ces calculs ne disent pas que ces pointes peuvent baisser. Décaler une charge ou réduire une production "
                    "ces jours-là n'est réalisable qu'après examen des process et validation de l'ingénieur du site."),
    "qd_et": " et ", "qd_le": "le ",
    "syn_decisifs": ("Ce qui décide la batterie : {n} jours au-dessus du plafond. Si les {k} plus lourds étaient restés sous "
                     "{plafond} kW, {b} kWh suffiraient au lieu de {a} kWh ({pct} de moins) ; un calcul sur des jours classés un à un, pas "
                     "une recommandation."),
    "syn_decisifs_un": ("Ce qui décide la batterie : {n} jours au-dessus du plafond. Si le plus lourd était resté sous {plafond} kW, "
                        "{b} kWh suffiraient au lieu de {a} kWh ({pct} de moins) ; un calcul, pas une recommandation."),
    "syn_decisifs_zero": ("Ce qui décide la batterie : {jours}. S'ils étaient restés sous {plafond} kW, aucune batterie ne serait "
                          "nécessaire ; un calcul, pas une recommandation."),
    "syn_jours": "{n} jours au-dessus du plafond, {liste}", "syn_un_jour": "un seul jour au-dessus du plafond, {liste}",
    "conf_titre": "Niveau de confiance",
    "conf_txt": ("Pour savoir si ces chiffres tiennent à l'année mesurée, chaque jour a été remplacé {tirages} fois par un jour "
                 "mesuré du même mois et du même type (ouvré, samedi, dimanche), tiré au hasard avec une graine fixe : le calcul "
                 "se refait à l'identique."),
    "conf_gardes": " {n} jours incomplets ou de changement d'heure sont restés tels quels.",
    "conf_limites": ("Limites : aucune journée plus haute que la plus haute mesurée ne peut apparaître ; l'intervalle ne dit donc "
                     "rien d'une pointe plus haute que celle de l'année mesurée. Les jours fériés comptent comme des jours ouvrés. "
                     "Une année de croissance ou de météo plus rude n'est pas couverte."),
    "conf_impossible": "impossible", "conf_batterie_impossible": "Aucune batterie ne tient {plafond} kW",
    "conf_grandeur": "Grandeur", "conf_mesure": "Année du profil", "conf_mesure_projet": "Année du profil avec le projet", "conf_mediane": "Médiane", "conf_intervalle": "5 % à 95 %",
    "conf_niveau": "Niveau dépassé {heures} h par an", "conf_heures": "Heures au-dessus du plafond visé ({plafond} kW)",
    "conf_batterie": "Batterie pour tenir {plafond} kW (capacité nominale)", "conf_decalage": "Décalage de ± {fenetre} h suffisant",
    "conf_part": "dans {pct} des années rééchantillonnées", "conf_a": " à ",
    "usure_titre": "Usure (comptage rainflow)",
    "usure_txt": ("Cycles de charge et de décharge comptés sur la période simulée, en part de la capacité nominale. Aucun taux "
                  "de vieillissement n'est supposé : la durée de vie se lit dans la garantie du fabricant."),
    "usure_classe": "Profondeur de cycle", "usure_cycles": "Cycles", "usure_pleins": "Cycles pleins équivalents (capacité nominale)",
    "usure_max": "Profondeur maximale", "usure_arbitrage": "Avec l'arbitrage (borne haute)", "usure_vie": "Durée de vie",
    "usure_fin": "Capacité à installer pour tenir le plafond en fin de garantie",
})
T["nl"].update({
    "qd_titre": "De kwartieren die beslissen",
    "qd_intro": ("Een paar kwartieren per jaar bepalen de gevraagde netcapaciteit en de omvang van de batterij. De cijfers "
                 "hieronder laten zien wat die grootheden zouden worden als juist die kwartieren lager waren geweest. Dit is "
                 "een berekening op het profiel, geen aanbeveling."),
    "qd_pointe": "De piek van {kw} kW, op {jour} om {heure}, wordt {n} kwartieren {periode} bereikt.",
    "qd_pointe_une": "De piek van {kw} kW, op {jour} om {heure}, wordt maar één kwartier {periode} bereikt.",
    "qd_pointe_projet": "Met het project zou de piek {kw} kW zijn, op {jour} om {heure}, {n} kwartieren {periode} bereikt.",
    "qd_pointe_une_projet": "Met het project zou de piek {kw} kW zijn, op {jour} om {heure}, maar één kwartier {periode} bereikt.",
    "qd_annee": "per jaar", "qd_periode": "in de periode",
    "qd_cap_quarts": "Hoogste kwartieren", "qd_cap_duree": "Duur", "qd_cap_jours": "Betrokken dagen",
    "qd_cap_pointe": "Piek als ze op het volgende niveau lagen", "qd_cap_baisse": "Daling van de piek",
    "qd_bat_txt": ("{jours} dagen gaan boven de beoogde grens van {plafond} kW, en de batterij van {nominale} kWh (optie 5.1) "
                   "is op die dagen gedimensioneerd. De dagen zijn gerangschikt naar de batterij die elke dag afzonderlijk "
                   "zou vragen (energie boven de grens of vermogen, wat het zwaarst weegt); een dag terugbrengen tot de grens "
                   "maakt de batterij alleen kleiner als die dag haar bepaalt, dus een regel kan niets veranderen. Als de "
                   "zwaarste dagen tot de grens waren teruggebracht:"),
    "qd_bat_retires": "Dagen teruggebracht tot de grens", "qd_bat_puissance": "Vermogen", "qd_bat_nominale": "Nominale capaciteit",
    "qd_bat_baisse": "Kleinere batterij", "qd_bat_invest": "Indicatieve investering", "qd_aucun": "geen dag (referentie)",
    "qd_zero": "Er zou geen batterij nodig zijn om onder {plafond} kW te blijven als {conditions}.",
    "qd_condition": "de piek van {jour} {pct} lager was",
    "qd_zero_beaucoup": "Zonder batterij zouden deze {jours} dagen allemaal onder {plafond} kW moeten blijven. De zwaarste:",
    "qd_j_jour": "Dag", "qd_j_pointe": "Piek van de dag", "qd_j_quarts": "Kwartieren erboven",
    "qd_j_energie": "Energie erboven", "qd_j_baisse": "Benodigde daling van de piek op die dag",
    "qd_prudence": ("Deze wat-als-berekeningen zeggen niet dat deze pieken omlaag kunnen. Een last verschuiven of productie "
                    "verminderen op die dagen kan pas na onderzoek van de processen en goedkeuring door de ingenieur van de locatie."),
    "qd_et": " en ", "qd_le": "",
    "syn_decisifs": ("Wat de batterij bepaalt: {n} dagen boven de grens. Als de {k} zwaarste onder {plafond} kW waren gebleven, "
                     "zou {b} kWh volstaan in plaats van {a} kWh ({pct} minder); een berekening op één voor één gerangschikte "
                     "dagen, geen aanbeveling."),
    "syn_decisifs_un": ("Wat de batterij bepaalt: {n} dagen boven de grens. Als de zwaarste onder {plafond} kW was gebleven, "
                        "zou {b} kWh volstaan in plaats van {a} kWh ({pct} minder); een berekening, geen aanbeveling."),
    "syn_decisifs_zero": ("Wat de batterij bepaalt: {jours}. Als die onder {plafond} kW waren gebleven, zou er geen batterij "
                          "nodig zijn; een berekening, geen aanbeveling."),
    "syn_jours": "{n} dagen boven de grens, {liste}", "syn_un_jour": "één dag boven de grens, {liste}",
    "conf_titre": "Betrouwbaarheid",
    "conf_txt": ("Om te zien of deze cijfers afhangen van het gemeten jaar, is elke dag {tirages} keer vervangen door een "
                 "willekeurig gekozen gemeten dag uit dezelfde maand en van hetzelfde type (werkdag, zaterdag, zondag), met een "
                 "vaste startwaarde: de berekening is exact te herhalen."),
    "conf_gardes": " {n} onvolledige dagen of dagen waarop de klok werd verzet, zijn ongewijzigd gebleven.",
    "conf_limites": ("Beperkingen: een dag hoger dan de hoogste gemeten dag kan niet voorkomen; het interval zegt dus niets over een "
                     "hogere piek dan in het gemeten jaar. Feestdagen tellen als werkdagen. Een jaar met groei of strenger weer valt "
                     "erbuiten."),
    "conf_impossible": "onmogelijk", "conf_batterie_impossible": "Geen batterij houdt {plafond} kW vast",
    "raison_infaisable": ("Geen batterij kan de beoogde grens het hele jaar vasthouden: tussen de pieken is er niet genoeg "
                          "laadenergie onder de grens."),
    "conf_grandeur": "Grootheid", "conf_mesure": "Jaar van het profiel", "conf_mesure_projet": "Jaar van het profiel met het project", "conf_mediane": "Mediaan", "conf_intervalle": "5 % tot 95 %",
    "conf_niveau": "Niveau dat {heures} uur per jaar wordt overschreden", "conf_heures": "Uren boven de beoogde grens ({plafond} kW)",
    "conf_batterie": "Batterij om onder {plafond} kW te blijven (nominale capaciteit)", "conf_decalage": "Verschuiven met ± {fenetre} uur volstaat",
    "conf_part": "in {pct} van de nagebootste jaren", "conf_a": " tot ",
    "usure_titre": "Slijtage (rainflow-telling)",
    "usure_txt": ("Laad- en ontlaadcycli worden geteld over de gesimuleerde periode, als deel van de nominale capaciteit. Er wordt geen "
                  "verouderingssnelheid aangenomen: de levensduur volgt uit de fabrieksgarantie."),
    "usure_classe": "Cyclusdiepte", "usure_cycles": "Cycli", "usure_pleins": "Equivalente volle cycli (nominale capaciteit)",
    "usure_max": "Grootste diepte", "usure_arbitrage": "Met arbitrage (bovengrens)", "usure_vie": "Levensduur",
    "usure_fin": "Te installeren capaciteit om aan het einde van de garantie nog onder de grens te blijven",
})


def _date_locale(instant: str, langue: str) -> str:
    return date.fromisoformat(instant[:10]).strftime("%d/%m/%Y" if langue == "fr" else "%d-%m-%Y")


def _liste_jours(jours: list[str], langue: str) -> str:
    t = T[langue]
    noms = [t["qd_le"] + _date_locale(j, langue) for j in jours]
    return noms[0] if len(noms) == 1 else ", ".join(noms[:-1]) + t["qd_et"] + noms[-1]


def _section_quarts_decisifs(r: dict[str, Any], langue: str) -> str:
    """Demande de Vincent (27/09, 3 h 27) : les quelques quarts d'heure qui décident de la capacité et de la batterie,
    avec leur contrefactuel chiffré, sans présenter une baisse comme réalisable."""
    q = r.get("quarts_decisifs")
    if not q:
        return ""
    t = T[langue]
    pic = q["pointe"]
    # Avec un scénario de croissance, le profil étudié est la mesure plus le projet : un chiffre simulé, pas mesuré.
    projet = bool(r.get("scenario_croissance"))
    cle = ("qd_pointe_une" if pic["quarts"] == 1 else "qd_pointe") + ("_projet" if projet else "")
    periode = t["qd_annee"] if r["statistiques"].get("duree_annuelle") else t["qd_periode"]
    pointe = t[cle].format(kw=nombre(pic["kw"], langue), jour=_date_locale(pic["debut"], langue), heure=pic["debut"][11:16],
                           n=nombre(pic["quarts"], langue), periode=periode)
    lignes_cap = "".join(f"<tr><td>{nombre(c['quarts'], langue)}</td><td>{nombre(c['heures'], langue, 2)} h</td>"
                         f"<td>{nombre(c['jours'], langue)}</td><td>{nombre(c['pointe_kw'], langue)} kW</td>"
                         f"<td>{nombre(c['baisse_kw'], langue)} kW ({pourcent(c['baisse_part'], langue)})</td></tr>" for c in q["capacite"])
    cap = (f"<p>{e(pointe)} {badge('simule' if projet else 'mesure', langue)}</p><div class='defile'><table class='num'><tr><th>{t['qd_cap_quarts']}</th>"
           f"<th>{t['qd_cap_duree']}</th><th>{t['qd_cap_jours']}</th><th>{t['qd_cap_pointe']} {badge('simule', langue)}</th>"
           f"<th>{t['qd_cap_baisse']}</th></tr>"
           f"{lignes_cap}</table></div>")
    plafond = nombre(r["plafond_kw"]["valeur"], langue)
    bat = ""
    if q["jours"] and q["batterie_nominale_kwh"]:
        texte = t["qd_bat_txt"].format(jours=nombre(q["jours_au_dessus"], langue), plafond=plafond,
                                       nominale=nombre(q["batterie_nominale_kwh"], langue, 1))
        invest = lambda x: f"{nombre(x, langue)} €" if x else "–"  # noqa: E731
        reference = (f"<tr><td>{e(t['qd_aucun'])}</td><td>{nombre(r['options']['batterie']['flex_kw']['valeur'], langue, 1)} kW</td>"
                     f"<td>{nombre(q['batterie_nominale_kwh'], langue, 1)} kWh</td><td>–</td>"
                     f"<td>{invest(q.get('batterie_investissement_eur'))}</td></tr>")
        lignes_bat = reference + "".join(
            f"<tr><td>{e(_liste_jours([j['jour'] for j in q['jours'][:s['jours_retires']]], langue))}</td>"
            f"<td>{nombre(s['puissance_kw'], langue, 1)} kW</td><td>{nombre(s['nominale_kwh'], langue, 1)} kWh</td>"
            f"<td>{pourcent(s['baisse_part'], langue) if s['baisse_part'] is not None else '–'}</td>"
            f"<td>{invest(s.get('investissement_eur'))}</td></tr>" for s in q["sans_jours"])
        bat = (f"<p>{e(texte)} {badge('simule', langue)}</p><div class='defile'><table class='num'><tr><th>{t['qd_bat_retires']}</th>"
               f"<th>{t['qd_bat_puissance']}</th><th>{t['qd_bat_nominale']}</th><th>{t['qd_bat_baisse']}</th>"
               f"<th>{t['qd_bat_invest']} {badge('hypothese', langue)}</th></tr>{lignes_bat}</table></div>")
        if q["jours_au_dessus"] <= 3:
            conditions = t["qd_et"].join(t["qd_condition"].format(jour=_date_locale(j["jour"], langue), pct=pourcent(j["baisse_necessaire"], langue))
                                         for j in q["jours"])
            zero = f"<p class='cle'>{e(t['qd_zero'].format(plafond=plafond, conditions=conditions))} {badge('simule', langue)}</p>"
        else:
            zero = f"<p>{e(t['qd_zero_beaucoup'].format(jours=nombre(q['jours_au_dessus'], langue), plafond=plafond))}</p>"
        lignes_j = "".join(f"<tr><td>{_date_locale(j['jour'], langue)}</td><td>{nombre(j['max_kw'], langue)} kW</td>"
                           f"<td>{nombre(j['quarts'], langue)}</td><td>{nombre(j['energie_kwh'], langue, 1)} kWh</td>"
                           f"<td>{pourcent(j['baisse_necessaire'], langue)}</td></tr>" for j in q["jours"])
        bat += (f"{zero}<div class='defile'><table class='num'><tr><th>{t['qd_j_jour']}</th><th>{t['qd_j_pointe']}</th>"
                f"<th>{t['qd_j_quarts']}</th><th>{t['qd_j_energie']}</th><th>{t['qd_j_baisse']} {badge('simule', langue)}</th></tr>{lignes_j}</table></div>")
    return (f"<h2>{e(t['qd_titre'])}</h2><p>{e(t['qd_intro'])}</p>{cap}{bat}"
            f"<p class='afaire'>{e(t['qd_prudence'])}</p>")


# Vocabulaire affiché de la page qualité (Fable, docs/maquettes/README.md, 30/09), repris tel quel en FR et en NL.
VOCABULAIRE = {
    "mesure": ("mesuré", "gemeten"), "estime": ("estimé", "geschat"), "calcule": ("calculé", "berekend"),
    "accepte_manuellement": ("accepté manuellement", "handmatig aanvaard"), "inconnue": ("inconnu", "onbekend"),
    "valide": ("validé, origine non documentée", "gevalideerd, herkomst niet gedocumenteerd"),
    "a_confirmer": ("à confirmer", "te bevestigen"), "declare": ("déclaré", "opgegeven"), "verifie": ("vérifié", "gecontroleerd"),
    "bloquant": ("bloquant", "blokkerend"), "alerte": ("alerte", "waarschuwing"), "info": ("information", "informatie"),
    "concordant": ("concordant", "overeenstemmend"), "non_fait": ("non fait", "niet uitgevoerd"),
}
# Valeurs de paramètres produites par Contingency (pas des pièces du client), traduites au rendu (revue d'Astra).
GENERIQUES = {
    "declaration_source": ("déclaration du fichier ou de sa configuration", "opgave in het bestand of de importconfiguratie"),
    "coh_unite": ("facture du même intervalle (contrôle COH-UNITE du diagnostic)",
                  "factuur over hetzelfde interval (controle COH-UNITE van de diagnose)"),
    "aucun_statut_source": ("la source ne fournit aucun statut de qualité", "de bron levert geen kwaliteitsstatus"),
}
# Raisons d'un contrôle COH bloqué sans chiffres comparables (coherence_mesures._invalide), revue d'Astra de 26ba18b (P1-Q).
RAISONS_BLOCAGE = {
    "kwh_invalide": ("énergie facturée invalide sur la facture", "ongeldig energieverbruik op de factuur"),
    "kwmax_invalide": ("kWmax facturé invalide", "ongeldige gefactureerde kWmax"),
    "profil_invalide": ("profil invalide : valeurs non finies ou négatives", "ongeldig profiel: niet-eindige of negatieve waarden"),
    "calcul_non_fini": ("calcul hors des nombres représentables", "berekening buiten de representeerbare getallen"),
    "point_livraison_invalide": ("position de mesure invalide", "ongeldige meetpositie"),
    "pointe_nulle": ("profil nul mais kWmax facturé positif", "profiel nul maar gefactureerde kWmax positief"),
    "pointes_nulles": ("profil et kWmax facturé nuls : unité indiscernable",
                       "profiel en gefactureerde kWmax nul: eenheid niet te onderscheiden"),
    "kwmax_nul": ("kWmax facturé nul alors que le profil a une puissance positive",
                  "gefactureerde kWmax nul terwijl het profiel een positief vermogen heeft"),
}


T["fr"].update({
    "q_titre": "Qualité des données",
    "q_intro": "Ce que le rapport sait des données lues : fichier, conventions, période, statut des mesures, alertes et "
               "confirmations. Aucun score global : chaque réserve vaut pour les résultats qui en dépendent.",
    "q_h_fichier": "Q1. Fichier et provenance", "q_fichier": "Fichier reçu", "q_octets": "octets",
    "q_non_transmis": "non transmis au scan (appel direct, sans fichier)",
    "q_sha": "Empreinte SHA-256", "q_sha_src": "identifie les octets reçus, pas leur exactitude physique",
    "q_format": "Format lu",
    "q_ean": "EAN du raccordement", "q_ean_src": "conservé en texte, jamais en nombre",
    "q_non_renseigne": "non renseigné", "q_a_demander": "à demander avant tout rapport client",
    "q_meetbedrijf": "Meetbedrijf", "q_mb_kenter": "déduit du format lu : réponse de l'API Meetdata de Kenter",
    "q_mb_declare": "déclaré dans le dossier", "q_canal": "Canal et point de mesure",
    "q_canal_kenter_val": "canal 16180 (kwartierlevering)",
    "q_canal_kenter": "la réponse ne porte pas l'identifiant du point de mesure : à garantir par l'appelant",
    "q_canal_import": "déclarés à l'import (configuration et colonne compteur)",
    "q_h_conventions": "Q2. Conventions : déclarées, puis vérifiées", "q_unite": "Unité",
    "q_unite_val": "puissance moyenne par {intervalle}, en kW",
    "q_quart": "quart d'heure", "q_intervalle": "intervalle de {pas} minutes",
    "q_non_recoupee": "non recoupée avec une facture du même intervalle",
    "q_marque": "Marqueur d'horodatage", "q_marque_val": "fin de chaque {intervalle}", "q_debut": "début", "q_fin": "fin",
    "q_marque_kenter": "documenté par le manuel de l'API Meetdata de Kenter : horodatage de fin de période",
    "q_marque_import": "déclaré à l'import : {marque} de chaque {intervalle}, converti en fin",
    "q_marque_canonique": "format canonique : colonne fin_intervalle",
    "q_fuseau": "Fuseau", "q_fuseau_kenter_val": "UTC (horodatage Unix)",
    "q_fuseau_kenter": "documenté par le manuel de l'API Meetdata de Kenter", "q_fuseau_import": "déclaré à l'import",
    "q_fuseau_canonique_val": "décalage UTC écrit sur chaque ligne", "q_fuseau_canonique": "lu dans le fichier, jamais supposé",
    "q_jours_amsterdam": "jours civils comptés en heure {ville}",
    "q_ville": {"Europe/Amsterdam": "d'Amsterdam", "Europe/Paris": "de Paris"}, "q_ville_autre": "du fuseau {zone}",
    "q_pas": "Pas de temps", "q_pas_val": "{pas} minutes",
    "q_horodatage_src": "vérifié à la lecture : trous, doublons et retours en arrière refusés",
    "q_versions": "Versions", "q_versions_val": "{scan} ; règles de vraisemblance du {vraisemblance}",
    "q_versions_src": "une confirmation de grandeur est liée à cette version des règles",
    "q_h_periode": "Q3. Période et calendrier", "q_periode": "Période lue", "q_jours": "jours",
    "q_annee_civile": "Année civile complète", "q_oui": "oui", "q_non": "non",
    "q_jours_particuliers": "Jours particuliers (heure {ville})",
    "q_jour_ete": "journée de 23 heures : passage à l'heure d'été",
    "q_jour_hiver": "journée de 25 heures : passage à l'heure d'hiver",
    "q_jour_partiel": "jour partiel : début ou fin de la période lue",
    "q_h_bilan": "Q4. Bilan des lignes", "q_recues": "Reçues", "q_n_lignes": "enregistrements CSV du fichier lu",
    "q_n_lignes_source": "enregistrements CSV du fichier d'origine, selon son audit import.json",
    "q_bilan_source_ignore": "Bilan du fichier d'origine non repris : comptes de l'audit import.json absents ou contradictoires.",
    "q_n_mesures_kenter": "mesures reçues sur le canal 16180",
    "q_conservees": "Conservées", "q_conservees_src": "un {intervalle} chacune, avec un horodatage exploitable et une valeur finie",
    "q_ecartees": "Écartées", "q_aucune": "aucune",
    "q_motif_filtre_compteur_canal": "autre compteur ou canal, filtre déclaré à l'import",
    "q_motif_hors_periode_retenue": "hors de la période retenue (Q3)",
    "q_doublons": "Doublons identiques", "q_doublons_src": "même instant et même valeur : gardés une fois, comptés",
    "q_refus": "Trous, conflits, retours en arrière",
    "q_refus_src": "refusés à la lecture : jamais remplis, triés ni départagés en silence",
    "q_h_statuts": "Q5. Statut des mesures",
    "q_pointe_mesuree": "La pointe de la période est atteinte par au moins une valeur mesurée.",
    "reserve_inconnue": "La qualité des valeurs qui déterminent la pointe n'est pas documentée.",
    "reserve_estime": "La pointe est fixée par une valeur estimée, pas mesurée.",
    "reserve_calcule": "La pointe est fixée par une valeur calculée, pas mesurée.",
    "reserve_marge": "GTV {gtv} kW moins pointe {pointe} kW. {raison}",
    "reserve_suite": "À confirmer : ce qui suit dépend de la pointe. {raison}",
    "syn_reserve": "À confirmer : {raison} La pointe, la marge sous le GTV et le dimensionnement qui en dépendent restent "
                   "indicatifs.",
    "croissance_reserve": "Ces chiffres dépendent de la pointe, à confirmer : {raison}",
    "q_h_recoupements": "Q6. Recoupements indépendants", "q_attendu": "facture", "q_observe": "profil", "q_ecart": "écart",
    "q_rc_kwmax": "kWmax facturé contre pointe du profil", "q_rc_pertes": "corrigée des pertes",
    "q_rc_kwmax_src": "facture, ligne « Maximale belasting ». Seuil interne de Contingency : écart d'arrondi de {kw} kW ou "
                      "{rel} % ; son adéquation à cette comparaison reste à justifier.",
    "q_rc_18160": "kWmax facturé par Kenter (canal 18160) contre pointe du profil (canal 16180)",
    "q_rc_18160_mois": "{mois} : facture {facture} kW, profil {profil} kW, écart {ecart} kW",
    "q_rc_18160_incomplet": "{mois} : mois incomplet dans le profil, non comparé",
    "q_rc_18160_qualite": " (kWmax facturé : {qualite})",
    "q_rc_18160_src": "manuel de l'API Meetdata de Kenter, v1.5 (canaux 16180 et 18160). Seuil interne de Contingency : "
                      "écart d'arrondi de {kw} kW ou {rel} % ; son adéquation à cette comparaison reste à justifier.",
    "q_rc_energie": "Énergie facturée contre énergie du profil",
    "q_rc_energie_src": "facture, lignes « afn. laag » et « afn. hoog ». Seuils internes de Contingency : alerte au-delà de "
                        "{alerte} %, blocage au-delà de {bloc} % ; leur adéquation à cette comparaison reste à justifier. Les "
                        "textes qui ont servi à les choisir portent sur autre chose : l'écart maximal admis d'une installation "
                        "de mesure neuve (Meetcode, bijlage B1.1, raccordement « hoogspanning ») et l'écart journalier entre "
                        "mesure principale et mesure de contrôle (art. 5.3.9 a).",
    "q_rc_periode": "période comparée",
    "q_rc_non_fait": "pièce absente : aucune conclusion tirée de ce contrôle",
    "q_rc_bloque": "Bloqué : {raison}. Corriger la donnée avant de conclure ce contrôle.",
    "q_rc_index": "Série strictement croissante (index cumulé ?)",
    "q_rc_index_oui": "oui, confirmée comme puissance moyenne (confirmation liée à cette série)",
    "q_rc_index_src": "une série qui ne fait que croître ressemble à un index cumulé ; elle n'est jamais rééchelonnée",
    "q_h_alertes": "Q7. Alertes et confirmations", "q_confirmations": "Confirmations enregistrées à l'import",
    "q_avertissements": "Avertissements du lecteur",
    "q_h_limites": "Q8. Ce que cette page ne prouve pas",
    "q_limites": ["Une empreinte identifie les octets reçus ; elle ne prouve ni leur authenticité ni leur exactitude.",
                  "Un recoupement avec la facture ne vaut que pour la période comparée, pas pour toute la période lue.",
                  "Un statut validé ou définitif ne prouve pas une mesure directe : une valeur peut avoir été reconstituée.",
                  "Les conventions déclarées le sont par la source ou l'utilisateur ; seules celles marquées vérifiées ont "
                  "été recoupées par un contrôle nommé."],
})
T["nl"].update({
    "q_titre": "Kwaliteit van de gegevens",
    "q_intro": "Wat het rapport weet over de gelezen gegevens: bestand, conventies, periode, status van de metingen, "
               "waarschuwingen en bevestigingen. Geen totaalscore: elk voorbehoud geldt voor de resultaten die ervan afhangen.",
    "q_h_fichier": "Q1. Bestand en herkomst", "q_fichier": "Ontvangen bestand", "q_octets": "bytes",
    "q_non_transmis": "niet aan de scan doorgegeven (directe aanroep, zonder bestand)",
    "q_sha": "SHA-256-vingerafdruk", "q_sha_src": "identificeert de ontvangen bytes, niet hun fysieke juistheid",
    "q_format": "Gelezen formaat",
    "q_ean": "EAN van de aansluiting", "q_ean_src": "als tekst bewaard, nooit als getal",
    "q_non_renseigne": "niet ingevuld", "q_a_demander": "opvragen vóór elk klantrapport",
    "q_meetbedrijf": "Meetbedrijf", "q_mb_kenter": "afgeleid uit het gelezen formaat: antwoord van de Meetdata-API van Kenter",
    "q_mb_declare": "opgegeven in het dossier", "q_canal": "Kanaal en meetpunt",
    "q_canal_kenter_val": "kanaal 16180 (kwartierlevering)",
    "q_canal_kenter": "het antwoord bevat de identificatie van het meetpunt niet: door de aanroeper te waarborgen",
    "q_canal_import": "opgegeven bij het importeren (configuratie en meterkolom)",
    "q_h_conventions": "Q2. Conventies: opgegeven, daarna gecontroleerd", "q_unite": "Eenheid",
    "q_unite_val": "gemiddeld vermogen per {intervalle}, in kW",
    "q_quart": "kwartier", "q_intervalle": "interval van {pas} minuten",
    "q_non_recoupee": "niet vergeleken met een factuur over hetzelfde interval",
    "q_marque": "Tijdstempel", "q_marque_val": "einde van elk {intervalle}", "q_debut": "begin", "q_fin": "einde",
    "q_marque_kenter": "gedocumenteerd in de handleiding van de Meetdata-API van Kenter: tijdstempel aan het einde van de periode",
    "q_marque_import": "opgegeven bij het importeren: {marque} van elk {intervalle}, omgezet naar het einde",
    "q_marque_canonique": "canoniek formaat: kolom fin_intervalle",
    "q_fuseau": "Tijdzone", "q_fuseau_kenter_val": "UTC (Unix-tijdstempel)",
    "q_fuseau_kenter": "gedocumenteerd in de handleiding van de Meetdata-API van Kenter",
    "q_fuseau_import": "opgegeven bij het importeren",
    "q_fuseau_canonique_val": "UTC-offset op elke regel geschreven", "q_fuseau_canonique": "gelezen in het bestand, nooit verondersteld",
    "q_jours_amsterdam": "kalenderdagen geteld in {ville}",
    "q_ville": {"Europe/Amsterdam": "Amsterdamse tijd", "Europe/Paris": "Parijse tijd"}, "q_ville_autre": "tijdzone {zone}",
    "q_pas": "Tijdstap", "q_pas_val": "{pas} minuten",
    "q_horodatage_src": "gecontroleerd bij het lezen: gaten, dubbele en teruglopende tijden geweigerd",
    "q_versions": "Versies", "q_versions_val": "{scan}; plausibiliteitsregels van {vraisemblance}",
    "q_versions_src": "een bevestiging van de grootheid is aan deze versie van de regels gekoppeld",
    "q_h_periode": "Q3. Tijdvak en kalender", "q_periode": "Gelezen tijdvak", "q_jours": "dagen",
    "q_annee_civile": "Volledig kalenderjaar", "q_oui": "ja", "q_non": "nee",
    "q_jours_particuliers": "Bijzondere dagen ({ville})",
    "q_jour_ete": "dag van 23 uur: overgang naar zomertijd", "q_jour_hiver": "dag van 25 uur: overgang naar wintertijd",
    "q_jour_partiel": "onvolledige dag: begin of einde van het gelezen tijdvak",
    "q_h_bilan": "Q4. Balans van de regels", "q_recues": "Ontvangen", "q_n_lignes": "CSV-records van het gelezen bestand",
    "q_n_lignes_source": "CSV-records van het oorspronkelijke bestand, volgens de audit import.json",
    "q_bilan_source_ignore": "Balans van het oorspronkelijke bestand niet overgenomen: tellingen in de audit import.json "
                             "ontbreken of spreken elkaar tegen.",
    "q_n_mesures_kenter": "ontvangen metingen op kanaal 16180",
    "q_conservees": "Behouden", "q_conservees_src": "elk één {intervalle}, met een bruikbare tijdstempel en een eindige waarde",
    "q_ecartees": "Weggelaten", "q_aucune": "geen",
    "q_motif_filtre_compteur_canal": "andere meter of ander kanaal, filter opgegeven bij het importeren",
    "q_motif_hors_periode_retenue": "buiten het gekozen tijdvak (Q3)",
    "q_doublons": "Identieke dubbele waarden", "q_doublons_src": "zelfde tijdstip en zelfde waarde: één keer bewaard, geteld",
    "q_refus": "Gaten, conflicten, teruglopende tijden",
    "q_refus_src": "bij het lezen geweigerd: nooit stilzwijgend aangevuld, gesorteerd of beslecht",
    "q_h_statuts": "Q5. Status van de metingen",
    "q_pointe_mesuree": "De piek van het tijdvak wordt bereikt door ten minste één gemeten waarde.",
    "reserve_inconnue": "De kwaliteit van de waarden die de piek bepalen is niet gedocumenteerd.",
    "reserve_estime": "De piek wordt bepaald door een geschatte waarde, niet door een gemeten waarde.",
    "reserve_calcule": "De piek wordt bepaald door een berekende waarde, niet door een gemeten waarde.",
    "reserve_marge": "GTV {gtv} kW min piek {pointe} kW. {raison}",
    "reserve_suite": "Te bevestigen: wat volgt hangt af van de piek. {raison}",
    "syn_reserve": "Te bevestigen: {raison} De piek, de ruimte onder het GTV en de dimensionering die ervan afhangen, "
                   "blijven indicatief.",
    "croissance_reserve": "Deze cijfers hangen af van de piek, die nog moet worden bevestigd: {raison}",
    "q_h_recoupements": "Q6. Vergelijkingen met onafhankelijke bronnen", "q_attendu": "factuur", "q_observe": "profiel",
    "q_ecart": "verschil",
    "q_rc_kwmax": "Gefactureerde kWmax tegenover piek van het profiel", "q_rc_pertes": "gecorrigeerd voor verliezen",
    "q_rc_kwmax_src": "factuur, regel ‘Maximale belasting’. Interne drempel van Contingency: afrondingsverschil van {kw} kW "
                      "of {rel} %. De geschiktheid ervan moet nog worden onderbouwd voor deze vergelijking.",
    "q_rc_18160": "Door Kenter gefactureerde kWmax (kanaal 18160) tegenover piek van het profiel (kanaal 16180)",
    "q_rc_18160_mois": "{mois}: factuur {facture} kW, profiel {profil} kW, verschil {ecart} kW",
    "q_rc_18160_incomplet": "{mois}: onvolledige maand in het profiel, niet vergeleken",
    "q_rc_18160_qualite": " (gefactureerde kWmax: {qualite})",
    "q_rc_18160_src": "handleiding van de Meetdata-API van Kenter, v1.5 (kanalen 16180 en 18160). Interne drempel van "
                      "Contingency: afrondingsverschil van {kw} kW of {rel} %. De geschiktheid ervan moet nog worden "
                      "onderbouwd voor deze vergelijking.",
    "q_rc_energie": "Gefactureerde energie tegenover energie van het profiel",
    "q_rc_energie_src": "factuur, regels ‘afn. laag’ en ‘afn. hoog’. Interne controledrempels van Contingency: waarschuwing "
                        "boven {alerte} %, blokkering boven {bloc} %. De geschiktheid van deze drempels moet nog worden "
                        "onderbouwd voor deze vergelijking. De bronnen die bij de keuze zijn gebruikt, gaan over iets anders: "
                        "de maximaal toelaatbare afwijking van een nieuwe meetinrichting (Meetcode, bijlage B1.1, aansluiting "
                        "op hoogspanning) en het verschil per dag tussen hoofd- en controlemeting (art. 5.3.9 a).",
    "q_rc_periode": "vergeleken tijdvak",
    "q_rc_non_fait": "stuk ontbreekt: uit deze controle wordt geen conclusie getrokken",
    "q_rc_bloque": "Geblokkeerd: {raison}. Corrigeer de gegevens voordat deze controle kan worden afgerond.",
    "q_rc_index": "Strikt stijgende reeks (cumulatieve meterstand?)",
    "q_rc_index_oui": "ja, bevestigd als gemiddeld vermogen (bevestiging gekoppeld aan deze reeks)",
    "q_rc_index_src": "een reeks die alleen stijgt lijkt op een cumulatieve meterstand; ze wordt nooit herschaald",
    "q_h_alertes": "Q7. Waarschuwingen en bevestigingen", "q_confirmations": "Bij het importeren vastgelegde bevestigingen",
    "q_avertissements": "Waarschuwingen bij het inlezen",
    "q_h_limites": "Q8. Wat deze pagina niet bewijst",
    "q_limites": ["Een vingerafdruk identificeert de ontvangen bytes; hij bewijst hun echtheid of juistheid niet.",
                  "Een vergelijking met de factuur geldt alleen voor het vergeleken tijdvak, niet voor het hele gelezen tijdvak.",
                  "Een gevalideerde of definitieve status bewijst geen directe meting: een waarde kan gereconstrueerd zijn.",
                  "Opgegeven conventies komen van de bron of de gebruiker; alleen de als gecontroleerd gemarkeerde zijn met "
                  "een benoemde controle vergeleken."],
})


# Avertissements produits par lecteur_kenter et lecteur_csv_compteur (textes de Contingency, pas des pièces du
# client), localisés au rendu (revue d'Astra de fb1b673, P2-K).
AVERTISSEMENTS_NL = {
    "Des valeurs sont estimées, pas mesurées.": "Sommige waarden zijn geschat, niet gemeten.",
    "Des valeurs ont été recalculées par Kenter, pas mesurées directement.":
        "Sommige waarden zijn door Kenter berekend, niet rechtstreeks gemeten.",
    "L'origine ou la validation de certaines valeurs n'est pas connue.":
        "De herkomst of validatie van sommige waarden is niet bekend.",
    "Les mesures ont été remises dans l'ordre chronologique UTC.": "De metingen zijn in chronologische UTC-volgorde gezet.",
    "Des réponses se recouvrent : les doublons identiques sont réunis et comptés dans la provenance.":
        "Antwoorden overlappen: identieke dubbele waarden zijn samengevoegd en in de herkomst geteld.",
    "Qualité des mesures inconnue : aucune colonne de statut déclarée.":
        "Kwaliteit van de metingen onbekend: geen statuskolom opgegeven.",
    "Statut « valide » sans origine documentée : la mesure directe n’est pas établie.":
        "Status ‘geldig’ zonder gedocumenteerde herkomst: een directe meting is niet vastgesteld.",
    "Des mesures estimées sont présentes ; elles ne constituent pas toutes des mesures observées.":
        "Er zijn geschatte waarden; niet alle waarden zijn waargenomen metingen.",
    "Unité déclarée : à recouper avec la facture du même intervalle avant conclusion de puissance.":
        "Opgegeven eenheid: vergelijken met de factuur over hetzelfde interval vóór een conclusie over het vermogen.",
}


def _avertissement(texte: str, langue: str) -> str:
    if langue != "nl":
        return texte
    return AVERTISSEMENTS_NL.get(texte) or f"{texte} (brontekst, niet vertaald)"


def _mot(cle: str, langue: str) -> str:
    return VOCABULAIRE[cle][langue == "nl"]


def _constat_texte(c: dict[str, Any], langue: str) -> str:
    """Texte du constat par le catalogue d'Astra. Seuls les paramètres marqués codes_internes par le producteur sont
    traduits ; une référence du client reste telle quelle, même égale à un code (revue d'Astra de fb1b673, P2-M)."""
    from messages_fiabilite import message_fiabilite
    internes = set(c.get("codes_internes") or [])
    p = {k: (GENERIQUES[v][langue == "nl"] if k in internes and v in GENERIQUES else v) for k, v in c["parametres"].items()}
    return message_fiabilite(c["code"], langue, **p)


# Règles de la page qualité pour une feuille qui ne les a pas (rapport du diagnostic) : tableaux g, badges, encadrés.
STYLE_QUALITE = (
    "table.g{border-collapse:collapse;width:100%;margin:.6rem 0;font-size:.9rem}table.g th,table.g td{text-align:left;"
    "padding:.35rem .5rem;border-bottom:1px solid #eaeef2;vertical-align:top;overflow-wrap:anywhere;width:auto;color:inherit}"
    "table.g th{font-weight:600}table.g th,table.g td:not(.src){overflow-wrap:normal}table.g code{overflow-wrap:anywhere}"
    "table.g td.src,.src{color:#57606a;font-size:.8rem}h4{font-size:.85rem;color:#57606a;"
    "text-transform:uppercase;letter-spacing:.04em;margin:1.2rem 0 .3rem}.n{display:inline-block;font-size:.72rem;"
    "padding:.05rem .4rem;border-radius:3px;border:1px solid;white-space:nowrap}.n-declare{color:#0e7490;border-color:#0e7490}"
    ".n-a_completer,.n-a_confirmer{color:#b91c1c;border-color:#b91c1c}.afaire{border-left:3px solid #b91c1c;padding:.4rem .8rem;"
    "background:#fff5f5}@media (max-width:40rem){table.g,table.g tbody{display:block}table.g tr{display:grid;"
    "grid-template-columns:1fr auto;gap:.15rem .6rem;padding:.45rem 0;border-bottom:1px solid #eaeef2}table.g th,table.g td"
    "{border:0;padding:0}table.g th,table.g td.src{grid-column:1/-1}table.g td:empty{display:none}}"
)


def reserves_controle(controle: dict[str, Any], langue: str) -> list[str]:
    """Textes des réserves de qualité d'un contrôle du diagnostic (diagnostic.preparer_qualite), par le catalogue."""
    return [_constat_texte(c, langue) for c in controle.get("reserves_qualite") or []]


def section_qualite_texte(r: dict[str, Any], langue: str) -> str:
    """Page qualité en texte brut, tirée du même HTML (revue d'Astra de 69800f2, P2-Y) : mêmes preuves, mêmes réserves.
    Une rangée de tableau devient une ligne de cellules non vides séparées par « | »."""
    texte = re.sub(r"<tr>(.*?)</tr>", lambda m: "\n   " + " | ".join(
        x for x in (re.sub(r"<[^>]+>", "", c.replace("<br>", " / ")).strip()
                    for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", m.group(1))) if x),
        _section_qualite(r, langue))
    texte = re.sub(r"<h2>(.*?)</h2>", lambda m: "\n" + m.group(1).upper() + "\n", texte)
    texte = re.sub(r"<h[34]>(.*?)</h[34]>", r"\n\1", texte)
    texte = re.sub(r"<li>", "\n   - ", texte)
    texte = re.sub(r"<p[^>]*>", "\n", texte)
    texte = html.unescape(re.sub(r"<[^>]+>", "", texte))
    return "\n".join(ligne.rstrip() for ligne in texte.splitlines() if ligne.strip())


def _reserve_pointe(r: dict[str, Any], langue: str) -> str:
    """Raison de la réserve sur la pointe (statut du quart qui la fixe), ou chaîne vide si la pointe est mesurée."""
    reserve = r.get("reserve_pointe")
    if not reserve:
        return ""
    return T[langue]["reserve_" + (reserve["qualite"] if reserve["qualite"] in ("estime", "calcule") else "inconnue")]


def _raison_blocage(raison: str, langue: str) -> str:
    return T[langue]["q_rc_bloque"].format(raison=RAISONS_BLOCAGE[raison][langue == "nl"] if raison in RAISONS_BLOCAGE
                                           else raison)


def _classe_detail(combinaison: dict[str, Any]) -> str:
    if combinaison.get("status") == "ManualAccepted":
        return "accepte_manuellement"
    return combinaison.get("qualite") if combinaison.get("qualite") in VOCABULAIRE else "inconnue"


def _section_qualite(r: dict[str, Any], langue: str) -> str:
    """FB1 : page « Qualité des données » en tête du rapport (maquette de Fable, docs/maquettes/qualite-donnees.html).
    Ce que le lecteur du bureau d'études doit savoir sans ouvrir le code : quel fichier, quelle unité, quelle période,
    quels jours particuliers, quelles valeurs non mesurées, quelles confirmations. Aucun score global."""
    t, q, st = T[langue], r.get("qualite_donnees") or {"constats": []}, r["statistiques"]
    prov, detail, constats = q.get("provenance") or {}, q.get("detail"), q["constats"]
    par_code = {c["code"]: c for c in constats}
    # 1. Fichier et provenance
    fichier = [_ligne(t["q_fichier"], e(f"{prov['fichier']} ({nombre(prov['octets'], langue)} {t['q_octets']})") if prov.get("fichier")
                      else e(t["q_non_transmis"]), None, "", langue),
               _ligne(t["q_sha"], f"<code>{e(prov['sha256'])}</code>" if prov.get("sha256") else "–", None, t["q_sha_src"], langue)]
    # Identité du point de mesure (AF02) : ce qui n'est pas fourni est dit « non renseigné », jamais supposé.
    ean, kenter = r["entreprise"]["ean"], prov.get("format") == "kenter_meetdata"
    meetbedrijf = "Kenter" if kenter else prov.get("meetbedrijf")
    imp = prov.get("import") if isinstance(prov.get("import"), dict) else {}  # audit import.json : types non garantis
    fichier.append(_ligne(t["q_format"], e(str(prov.get("format") or imp.get("format") or "–")), None, "", langue))
    fichier.append(_ligne(t["q_versions"], e(t["q_versions_val"].format(scan=r["version"],
                                                                      vraisemblance=q.get("regles_vraisemblance", "–"))),
                          None, t["q_versions_src"], langue))
    conf, compteurs = imp.get("configuration"), imp.get("compteurs")
    canal = ", ".join(str(x) for x in [conf.get("kanaal") if isinstance(conf, dict) else None,
                                       *(compteurs if isinstance(compteurs, list) else [])] if x)
    fichier += [_ligne(t["q_ean"], e(str(ean["valeur"]) if ean["valeur"] is not None else t["q_non_renseigne"]), ean["nature"],
                       t["q_ean_src"] if ean["valeur"] is not None else t["q_a_demander"], langue),
                _ligne(t["q_meetbedrijf"], e(str(meetbedrijf or t["q_non_renseigne"])),
                       None if kenter else "declare" if meetbedrijf else "a_completer",
                       t["q_mb_kenter"] if kenter else t["q_mb_declare"] if meetbedrijf else t["q_a_demander"], langue),
                _ligne(t["q_canal"], e(t["q_canal_kenter_val"] if kenter else canal or t["q_non_renseigne"]),
                       None if kenter else "declare" if canal else "a_completer",
                       t["q_canal_kenter"] if kenter else t["q_canal_import"] if canal else t["q_a_demander"], langue)]
    # 2. Conventions : déclarées, puis vérifiées. Marqueur et fuseau selon la source (relecture de Fable, critères 1 et 2).
    dp, pv = (" : ", " ; ") if langue == "fr" else (": ", "; ")  # espace avant la ponctuation double en français seulement
    # Pas natif et fuseau du profil (France : 5 à 60 minutes, Europe/Paris), jamais recadrés pour la page.
    pas, zone = q.get("pas_minutes", 15), q.get("zone", "Europe/Amsterdam")
    intervalle = t["q_quart"] if pas == 15 else t["q_intervalle"].format(pas=pas)
    ville = t["q_ville"].get(zone) or t["q_ville_autre"].format(zone=zone)
    recoupe = par_code.get("UNITE_RECOUPEE")
    conf = imp.get("configuration") if isinstance(imp.get("configuration"), dict) else prov.get("conventions")
    conf = conf if isinstance(conf, dict) else {}
    if kenter:
        marque, fuseau, fuseau_src = t["q_marque_kenter"], t["q_fuseau_kenter_val"], t["q_fuseau_kenter"]
    elif conf:
        marque = t["q_marque_import"].format(marque={"debut": t["q_debut"], "fin": t["q_fin"]}.get(conf.get("horodatage_marque"), "–"),
                                             intervalle=intervalle)
        fuseau, fuseau_src = str(conf.get("fuseau") or "–"), t["q_fuseau_import"]
    elif prov.get("format") == "csv_canonique":
        marque, fuseau, fuseau_src = t["q_marque_canonique"], t["q_fuseau_canonique_val"], t["q_fuseau_canonique"]
    else:
        marque, fuseau, fuseau_src = t["q_non_transmis"], "–", t["q_non_transmis"]
    conventions = [_ligne(t["q_unite"], e(t["q_unite_val"].format(intervalle=intervalle)), None,
                          f"{_mot('verifie', langue)}{dp}{_constat_texte(recoupe, langue)}"
                          if recoupe else f"{_mot('declare', langue)}, {t['q_non_recoupee']}", langue),
                   _ligne(t["q_marque"], e(t["q_marque_val"].format(intervalle=intervalle)), None, marque, langue),
                   _ligne(t["q_fuseau"], e(fuseau), None, f"{fuseau_src}{pv}{t['q_jours_amsterdam'].format(ville=ville)}", langue),
                   _ligne(t["q_pas"], e(t["q_pas_val"].format(pas=pas)), None, t["q_horodatage_src"], langue)]
    # 3. Période et calendrier ; jours particuliers comptés en heure d'Amsterdam
    couv, rep = st["couverture"], st["representativite"]
    periode = [_ligne(t["q_periode"], e(f"{st['debut'][:16].replace('T', ' ')} → {st['fin'][:16].replace('T', ' ')} "
                                        f"({nombre(couv['jours'], langue, 1)} {t['q_jours']})"), None, "", langue),
               _ligne(t["q_annee_civile"], e(t["q_oui" if couv["type"] == "annee_civile" else "q_non"]
                                             + f"{pv}{t['annee_' + rep['statut'] if rep['statut'] != 'recente' else 'annee_ok'].format(**rep)}"),
                      None, "", langue)]
    # Jours particuliers comptés par qualite_jeu en intervalles natifs, sur les débuts physiques (revue d'Astra).
    particuliers = "".join(f"<tr><td>{e(_date_locale(j['jour'], langue))}</td><td>{j['intervalles']}</td>"
                           f"<td>{e(t['q_jour_' + j['motif']])}</td></tr>" for j in q.get("jours_particuliers") or [])
    # 4. Bilan des lignes : reçues, conservées, écartées avec leur motif ; trous et conflits sont refusés à la lecture.
    total, b = st["quarts"], prov.get("bilan_lignes")
    bilan = [_ligne(t["q_recues"], nombre(b["recues"], langue), None, t["q_n_" + b["nature"]]
                    + (". " + t["q_bilan_source_ignore"] if prov.get("bilan_source_ignore") else ""), langue) if b
             else _ligne(t["q_recues"], "–", None, t["q_non_transmis"], langue),
             _ligne(t["q_conservees"], nombre(total, langue), None, t["q_conservees_src"].format(intervalle=intervalle), langue)]
    if b:
        motifs = ", ".join(f"{t['q_motif_' + m]} ({nombre(n, langue)})" for m, n in b["ecartees"].items())
        bilan += [_ligne(t["q_ecartees"], nombre(sum(b["ecartees"].values()), langue), None, motifs or t["q_aucune"], langue),
                  _ligne(t["q_doublons"], nombre(b["doublons_identiques"], langue), None, t["q_doublons_src"], langue)]
    bilan.append(_ligne(t["q_refus"], "0", None, t["q_refus_src"], langue))
    # 5. Statut des mesures, et statut du quart qui fixe la pointe (critère 3 de Fable)
    if detail:
        lignes_statut = defaultdict(int)
        for cle, n in detail["combinaisons"].items():
            lignes_statut[_classe_detail(json.loads(cle))] += n
    else:
        lignes_statut = {"inconnue": total}
    statuts = "".join(f"<tr><td>{e(_mot(k, langue))}</td><td>{nombre(n, langue)}</td><td>{e(pourcent(n / total, langue))}</td></tr>"
                      for k, n in sorted(lignes_statut.items(), key=lambda x: -x[1]))
    from messages_fiabilite import CODES_POINTE
    pointe = next((c for c in constats if c["code"] in CODES_POINTE), None)
    ligne_pointe = (f"<p class='afaire'>{e(_mot('a_confirmer', langue))}{dp}{e(_constat_texte(pointe, langue))}</p>" if pointe
                    else f"<p>{e(t['q_pointe_mesuree'])}</p>")
    # 6. Recoupements indépendants : chiffres du diagnostic contre la facture, sur sa période ; « non fait » sans pièce.
    import coherence_mesures as cm

    def rangee(controle: str, parties: list[str], verdict: str, texte_source: str) -> str:
        return (f"<tr><th>{e(controle)}</th><td>{'<br>'.join(e(x) for x in parties if x)}</td>"
                f"<td><strong>{e(_mot(verdict, langue))}</strong></td><td class='src'>{e(texte_source)}</td></tr>")
    rc = {x["id"]: x for x in prov.get("recoupements") or []}
    verdicts = {"constat": "concordant", "alerte": "alerte"}  # tout autre statut du diagnostic bloque
    comparee = prov.get("periode_comparee")
    periode_rc = (f"{t['q_rc_periode']} {comparee[0][:16].replace('T', ' ')} → {comparee[1][:16].replace('T', ' ')}"
                  if comparee else "")
    u = (rc.get("COH-UNITE") or {}).get("valeurs") or {}
    if "kwmax_facture" in u and "pointe_kw" in u:
        observe = u.get("pointe_comparee", u["pointe_kw"])
        ecart = observe - u["kwmax_facture"]
        kwmax = rangee(t["q_rc_kwmax"], [f"{t['q_attendu']} {nombre(u['kwmax_facture'], langue, 1)} kW",
                                        f"{t['q_observe']} {nombre(observe, langue, 1)} kW"
                                        + (f" ({t['q_rc_pertes']})" if u.get("facteur_correction_pertes", 1) != 1 else ""),
                                        f"{t['q_ecart']} {'+' if ecart > 0 else ''}{nombre(ecart, langue, 1)} kW", periode_rc],
                       verdicts.get(rc["COH-UNITE"]["statut"], "bloquant"),
                       t["q_rc_kwmax_src"].format(kw=nombre(cm.TOLERANCE_KWMAX_KW, langue),
                                                  rel=nombre(cm.TOLERANCE_KWMAX_RELATIVE * 100, langue)))
    elif u.get("raison"):  # contrôle mené, bloqué sans chiffres comparables : jamais « non fait » (P1-Q d'Astra)
        kwmax = rangee(t["q_rc_kwmax"], [_raison_blocage(u["raison"], langue)], "bloquant", "")
    elif recoupe:  # recoupement affirmé par la fiche, sans les chiffres
        kwmax = rangee(t["q_rc_kwmax"], [_constat_texte(recoupe, langue)], "declare", "")
    else:
        kwmax = rangee(t["q_rc_kwmax"], [t["q_rc_non_fait"]], "non_fait", "")
    # Kenter publie aussi le kWmax de facturation (canal 18160) : recoupé mois par mois avec le profil (canal 16180).
    kenter_18160 = ""
    if q.get("recoupement_18160"):
        parties = []
        for m in q["recoupement_18160"]:
            qualite = (t["q_rc_18160_qualite"].format(qualite=_mot(m["qualite_facture"], langue))
                       if m.get("qualite_facture") not in (None, "mesure") else "")
            parties.append(t["q_rc_18160_incomplet"].format(mois=m["mois"]) + qualite if m["verdict"] == "mois_incomplet"
                           else t["q_rc_18160_mois"].format(mois=m["mois"], facture=nombre(m["facture_kw"], langue, 1),
                                                            profil=nombre(m["profil_kw"], langue, 1),
                                                            ecart=("+" if m["ecart_kw"] > 0 else "") + nombre(m["ecart_kw"], langue, 1))
                           + qualite)
        verdicts_18160 = {m["verdict"] for m in q["recoupement_18160"]}
        kenter_18160 = rangee(t["q_rc_18160"], parties, "alerte" if "alerte" in verdicts_18160 else
                              "concordant" if "concordant" in verdicts_18160 else "non_fait",
                              t["q_rc_18160_src"].format(kw=nombre(cm.TOLERANCE_KWMAX_KW, langue),
                                                         rel=nombre(cm.TOLERANCE_KWMAX_RELATIVE * 100, langue)))
    en = rc.get("COH-ENERGIE") or {}
    v = en.get("valeurs") or {}
    if "kwh_facture" in v and "energie_profil_kwh" in v:
        energie = rangee(t["q_rc_energie"], [f"{t['q_attendu']} {nombre(v['kwh_facture'], langue)} kWh",
                                            f"{t['q_observe']} {nombre(v['energie_profil_kwh'], langue)} kWh",
                                            f"{t['q_ecart']} {pourcent(v['ecart'], langue)}" if v.get("ecart") is not None else "",
                                            periode_rc],
                         verdicts.get(en["statut"], "bloquant"),
                         t["q_rc_energie_src"].format(alerte=nombre(cm.SEUIL_ALERTE_ENERGIE * 100, langue),
                                                      bloc=nombre(cm.TOLERANCE_ENERGIE * 100, langue)))
    elif v.get("raison"):
        energie = rangee(t["q_rc_energie"], [_raison_blocage(v["raison"], langue)], "bloquant", "")
    else:
        energie = rangee(t["q_rc_energie"], [t["q_rc_non_fait"]], "non_fait", "")
    indice = par_code.get("GRANDEUR_INDEX_POSSIBLE")
    index = rangee(t["q_rc_index"], [t["q_rc_index_oui"] if indice else t["q_non"]], "alerte" if indice else "concordant",
                   t["q_rc_index_src"])
    # 7. Alertes et confirmations
    alertes = "".join(f"<li><strong>{e(_mot(c['gravite'], langue))}</strong>{dp}{e(_constat_texte(c, langue))}</li>" for c in constats)
    journal = prov.get("journal_import") or []
    confirmations = "".join(f"<li>{e(_constat_texte(c, langue))}</li>" for c in journal)
    avertis = "".join(f"<li>{e(_avertissement(a, langue))}</li>" for a in q.get("avertissements_lecteur") or [])
    return (f"<h2>{t['q_titre']}</h2><p class='src'>{e(t['q_intro'])}</p>"
            f"<h3>{t['q_h_fichier']}</h3><table class='g'>{''.join(fichier)}</table>"
            f"<h3>{t['q_h_conventions']}</h3><table class='g'>{''.join(conventions)}</table>"
            f"<h3>{t['q_h_periode']}</h3><table class='g'>{''.join(periode)}</table>"
            + (f"<h4>{t['q_jours_particuliers'].format(ville=ville)}</h4><table class='g'>{particuliers}</table>"
               if particuliers else "")
            + f"<h3>{t['q_h_bilan']}</h3><table class='g'>{''.join(bilan)}</table>"
            f"<h3>{t['q_h_statuts']}</h3><table class='g'>{statuts}</table>{ligne_pointe}"
            f"<h3>{t['q_h_recoupements']}</h3><table class='g'>{kwmax}{kenter_18160}{energie}{index}</table>"
            f"<h3>{t['q_h_alertes']}</h3><ul>{alertes}</ul>"
            + (f"<h4>{t['q_confirmations']}</h4><ul>{confirmations}</ul>" if confirmations else "")
            + (f"<h4>{t['q_avertissements']}</h4><ul>{avertis}</ul>" if avertis else "")
            + f"<h3>{t['q_h_limites']}</h3><ul>{''.join(f'<li>{e(x)}</li>' for x in t['q_limites'])}</ul>")


def _section_synthese(r: dict[str, Any], langue: str) -> str:
    """L'essentiel en cinq lignes au plus, tiré des sections détaillées, sans chiffre nouveau."""
    t, o, st = T[langue], r["options"], r["statistiques"]
    commun = _valeurs_texte(r, langue)
    premiere = r["recommandation"][0]
    scen = r.get("scenario_croissance")
    # Avec un projet qui dépasse la limite, épisodes et plafond portent sur le profil augmenté : la première ligne
    # ne décrit alors que le profil mesuré, pour ne pas mêler les deux.
    avec_projet = bool(scen) and not scen["tient_sans_mesure"]
    points = [t["syn_profil_simple" if avec_projet else "syn_profil"].format(
        pointe=nombre(st["pointe_kw"]["valeur"], langue), energie=_valeur("energie", st["energie_mwh"], langue, 1),
        heures=nombre(r["episodes"]["quarts"] / 4, langue, 2), plafond=nombre(r["plafond_kw"]["valeur"], langue))]
    if _reserve_pointe(r, langue):
        points.append(t["syn_reserve"].format(raison=_reserve_pointe(r, langue)))
    if scen:
        points.append(t["syn_projet_tient" if scen["tient_sans_mesure"] else "syn_projet"].format(
            kw=nombre(scen["kw"], langue), limite=nombre(scen["limite_kw"]["valeur"], langue),
            pointe=nombre(scen["pointe_scenario_kw"], langue)))
    else:
        c = r["croissance"]
        if c.get("depassement_kw"):
            points.append(t["syn_capacite_depasse" if c["total_kw"]["valeur"] > 0 else "syn_capacite_depasse_reste"].format(
                dep=nombre(c["depassement_kw"], langue, 1), total=nombre(c["total_kw"]["valeur"], langue, 1)))
        else:
            points.append(t["syn_capacite"].format(liberes=nombre(c["liberes_kw"], langue, 1))
                          + (" " + t["groupe_condition"] if r.get("contrat_groupe") else ""))
    condition = t[premiere["cle"]].format(**commun, flex=nombre((o[premiere["option"]].get("flex_kw") or {}).get("valeur"), langue, 1))
    points.append(t["syn_mesure"].format(option=t["o_" + premiere["option"]].lower(), condition=condition))
    q = r.get("quarts_decisifs") or {}
    sans = [x for x in q.get("sans_jours") or [] if x.get("baisse_part")]
    if sans:
        # Le plus petit nombre de jours qui donne la plus forte baisse : ne pas dire « les 3 » si 2 suffisent.
        dernier = next(x for x in sans if x["baisse_part"] == max(y["baisse_part"] for y in sans))
        plafond = nombre(r["plafond_kw"]["valeur"], langue)
        if dernier.get("aucune", dernier["nominale_kwh"] == 0):
            liste = _liste_jours([j["jour"] for j in q["jours"][:dernier["jours_retires"]]], langue)
            jours = t["syn_un_jour" if q["jours_au_dessus"] == 1 else "syn_jours"].format(n=nombre(q["jours_au_dessus"], langue), liste=liste)
            points.append(t["syn_decisifs_zero"].format(jours=jours, plafond=plafond))
        else:
            points.append(t["syn_decisifs_un" if dernier["jours_retires"] == 1 else "syn_decisifs"].format(
                                                   n=nombre(q["jours_au_dessus"], langue), k=nombre(dernier["jours_retires"], langue),
                                                   plafond=plafond, a=nombre(q["batterie_nominale_kwh"], langue, 1),
                                                   b=nombre(dernier["nominale_kwh"], langue, 1), pct=pourcent(dernier["baisse_part"], langue)))
    tranches = ((o["batterie"].get("retour_ans") or {}).get("parametres") or {}).get("tranches") or []
    if r["raccordement"].get("tarif_kwmax_mois") is None:
        points.append(t["syn_facture_sans_kwmax"])
    else:
        points.append(t["syn_facture" if tranches == ["plus_15"] else "syn_facture_neutre"].format(eco=commun["eco"], par_an=commun["par_an"]))
    return f"<h2>{t['syn_titre']}</h2><ul class='syn'>{''.join(f'<li>{e(p)}</li>' for p in points)}</ul>"


def _section_conformite(r: dict[str, Any], langue: str) -> str:
    t, etats, noms = T[langue], ETATS[langue], ELEMENTS_FLEXE[langue]
    lignes = conformite(r)
    restant = sum(1 for _, etat in lignes if etat in ("a_completer", "a_faire"))
    corps = "".join(f"<tr><td>{e(cle)}</td><td>{e(noms[cle])}</td><td class='etat-{etat}'>{e(etats[etat])}</td></tr>"
                    for cle, etat in lignes)
    return (f"<h2>{t['conformite_titre']}</h2><p>{e(t['conformite_txt'].format(n=restant, total=len(lignes)))}</p>"
            f"<div class='defile'><table class='num'><tr><th>Art.</th><th>{t['element']}</th><th>{t['etat']}</th></tr>"
            f"{corps}</table></div>")


STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:58rem;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#1f2328;background:#fff}"
    "h1{font-size:1.6rem;margin-bottom:.2rem}h2{font-size:1.15rem;margin-top:2.4rem;border-bottom:1px solid #d0d7de;padding-bottom:.3rem}"
    "h3{font-size:1rem;margin-top:1.6rem}h4{font-size:.85rem;color:#57606a;text-transform:uppercase;letter-spacing:.04em;margin:1.2rem 0 .3rem}"
    "table{border-collapse:collapse;width:100%;margin:.6rem 0;font-size:.9rem}th,td{text-align:left;padding:.35rem .5rem;"
    "border-bottom:1px solid #eaeef2;vertical-align:top}th{font-weight:600}table.num td{font-variant-numeric:tabular-nums}"
    ".src{color:#57606a;font-size:.8rem}.n{display:inline-block;font-size:.72rem;padding:.05rem .4rem;border-radius:3px;"
    "border:1px solid;white-space:nowrap}.n-mesure{color:#1f2328;border-color:#1f2328}.n-simule{color:#b45309;border-color:#b45309}"
    ".n-tarif,.n-lu{color:#57606a;border-color:#8c959f}.n-hypothese{color:#6d28d9;border-color:#6d28d9}"
    ".n-a_chiffrer,.n-a_completer,.n-a_confirmer{color:#b91c1c;border-color:#b91c1c}.n-declare{color:#0e7490;border-color:#0e7490}.ref{color:#57606a;font-size:.78rem;margin-top:-.4rem}.afaire{border-left:3px solid #b91c1c;padding:.4rem .8rem;background:#fff5f5}"
    ".exemple{border:1px solid #d0d7de;background:#f6f8fa;padding:.6rem .9rem}.cle{border-left:3px solid #1f2328;padding:.4rem .8rem;background:#f6f8fa}.syn{background:#f6f8fa;border:1px solid #d0d7de;padding:.8rem 1rem .8rem 2rem}.syn li{margin:.3rem 0}.etat-a_completer,.etat-a_faire{color:#b91c1c;font-weight:600}.etat-calcule{color:#b45309}.etat-fourni{color:#0e7490}figure{margin:.4rem 0 1rem}"
    ".graph{width:100%;height:auto}.ax{font-size:10px;fill:#57606a}figcaption{font-size:.8rem;color:#57606a;display:flex;"
    "gap:1rem;flex-wrap:wrap}figcaption i{display:inline-block;width:14px;height:3px;margin-right:.35rem;vertical-align:middle}"
    ".defile{overflow-x:auto}table.comp{min-width:52rem}table.comp th,table.comp td{overflow-wrap:normal;word-break:normal;hyphens:auto}"
    "table.comp th:first-child{min-width:8rem}table.comp td{min-width:6.5rem}ol li{margin:.5rem 0}"
    "footer{margin-top:2.5rem;color:#57606a;font-size:.85rem;border-top:1px solid #d0d7de;padding-top:1rem}"
    "td,th{overflow-wrap:anywhere}"
    # Chiffres et valeurs : coupure aux espaces seulement, sinon le tableau se tasse (« Média ne », « cycles /an »).
    "table.num td,table.num th,table.g th,table.g td:not(.src){overflow-wrap:normal}"
    # Empreinte SHA-256 de la page qualité : 64 caractères sans espace, sécable (revue d'Astra de 716cf27, P2-Z).
    "table.g code{overflow-wrap:anywhere}"
    "@media (max-width:40rem){body{margin:1rem auto}table{font-size:.84rem}th,td{padding:.3rem}"
    "table.g,table.g tbody{display:block}table.g tr{display:grid;grid-template-columns:1fr auto;gap:.15rem .6rem;"
    "padding:.45rem 0;border-bottom:1px solid #eaeef2}table.g th,table.g td{border:0;padding:0}table.g th{grid-column:1/-1}"
    "table.g td.src{grid-column:1/-1}table.g tr.entete{display:none}table.g td:empty{display:none}"
    "table.vn{min-width:36rem}}"
    "@media print{body{max-width:none;margin:0;font-size:10.5pt}h2{break-after:avoid}figure,tr{break-inside:avoid}"
    ".defile{overflow:visible}table.comp,table.vn{min-width:0;font-size:8pt}table.comp td,table.comp th:first-child{min-width:0}"
    ".syn,.cle,.afaire,.exemple{break-inside:avoid}}"
)

# ---------------------------------------------------------------- économies par type de client (brief du 27/09/2026)

T["fr"].update({
    "mon_titre": "Économies par type de client", "mon_zero_ou": "0 € ou",
    "mon_intro": ("Fourchettes calculées sur les hypothèses citées à chaque ligne : ce ne sont pas des promesses. Un "
                  "investissement évité ou une aide (une fois) et une économie ou un revenu (par an) ne s'additionnent pas : "
                  "chaque ligne se lit seule. Les deux réponses possibles à la question de la batterie sont chiffrées."),
    "mon_patron_non": "Patron de site, réponse « pas de batterie » : la limite est tenue par {mesure}",
    "mon_patron_oui": "Patron de site, réponse « batterie »",
    "mon_bureau": "Bureau d'études",
    "mon_invest_evite": "Investissement évité (une fois)", "mon_contrat": "Optimisation du contrat (par an)",
    "mon_aide_scan": "Aide Flex-e au scan (une fois)", "mon_aide_etude": "Aide Flex-e à l'étude de faisabilité (une fois)",
    "mon_dimensionnement": "Bon dimensionnement : investissement en moins (une fois)", "mon_eia": "EIA : impôt en moins (une fois)",
    "mon_revenus_flex": "Revenus de flexibilité (par an)",
    "mon_bureau_heures": "Temps gagné par scan", "mon_bureau_valeur": "Valeur du temps gagné, par scan, hors TVA",
    "mon_regles": ("Règles de lecture : les mêmes quarts d'heure ne sont jamais vendus à la fois en déséquilibre (onbalans) et "
                   "en redispatch ; les revenus de flexibilité ne s'ajoutent pas à l'arbitrage day-ahead de la section 6, qui "
                   "utilise la même capacité ; la baisse du kWmax (section 6) est la même quelle que soit la mesure qui tient "
                   "la limite."),
})
T["nl"].update({
    "mon_titre": "Besparingen per type klant", "mon_zero_ou": "€ 0 of",
    "mon_intro": ("Bandbreedtes op basis van de aannames die bij elke regel staan: het zijn geen beloftes. Een vermeden "
                  "investering of een subsidie (eenmalig) en een besparing of opbrengst (per jaar) worden nooit opgeteld: elke "
                  "regel staat op zichzelf. Beide antwoorden op de batterijvraag worden doorgerekend."),
    "mon_patron_non": "Eigenaar van de locatie, antwoord ‘geen batterij’: de grens wordt gehouden door {mesure}",
    "mon_patron_oui": "Eigenaar van de locatie, antwoord ‘batterij’",
    "mon_bureau": "Ingenieursbureau",
    "mon_invest_evite": "Vermeden investering (eenmalig)", "mon_contrat": "Contractoptimalisatie (per jaar)",
    "mon_aide_scan": "Flex-e-subsidie voor de scan (eenmalig)", "mon_aide_etude": "Flex-e-subsidie voor de haalbaarheidsstudie (eenmalig)",
    "mon_dimensionnement": "Juiste dimensionering: lagere investering (eenmalig)", "mon_eia": "EIA: minder belasting (eenmalig)",
    "mon_revenus_flex": "Opbrengsten uit flexibiliteit (per jaar)",
    "mon_bureau_heures": "Tijdwinst per scan", "mon_bureau_valeur": "Waarde van de tijdwinst per scan, exclusief btw",
    "mon_regles": ("Leeswijzer: dezelfde kwartieren worden nooit tegelijk op de onbalansmarkt en voor redispatch aangeboden; de "
                   "opbrengsten uit flexibiliteit komen niet bovenop de day-aheadarbitrage uit sectie 6, die dezelfde capaciteit "
                   "gebruikt; de verlaging van kWmax (sectie 6) is dezelfde, welke maatregel de grens ook houdt."),
})
SOURCES["fr"].update({
    "src_mon_scan_prix": "Flex-e (RVO) : 50 % du coût du scan hors TVA, au plus 10 000 € ; prix du scan non fourni",
    "src_mon_flex_e_scan": "Flex-e (RVO) : 50 % de {prix} € hors TVA, au plus 10 000 € ; demandes du 06/05/2026 au 15/10/2026",
    "src_mon_etude_cout": ("Flex-e (RVO) : 50 % du coût d'une étude de faisabilité, aide de 10 000 € au moins et de 125 000 € au "
                           "plus ; coût non fourni, aucune étude supposée"),
    "src_mon_etude_sous_minimum": ("Flex-e (RVO) : 50 % de {cout} € reste sous l'aide minimale de 10 000 € ; une étude de moins de "
                                   "20 000 € n'est pas aidée"),
    "src_mon_etude": "Flex-e (RVO) : 50 % de {cout} € hors TVA, aide comprise entre 10 000 et 125 000 € ; demandes jusqu'au 15/10/2026",
    "src_mon_invest_evite_decalage": ("batterie de l'option 5.1 ({nominale} kWh), inutile si le décalage d'horaires tient la limite ; "
                                      "prix indicatif des hypothèses, pas un devis"),
    "src_mon_invest_evite_ecretage": ("batterie de l'option 5.1 ({nominale} kWh), inutile si l'écrêtage est accepté, au prix de la "
                                      "production coupée ; prix indicatif des hypothèses, pas un devis"),
    "src_mon_batterie_impossible": "aucune batterie ne tient la limite toute l'année (option 5.1)",
    "src_mon_batterie_inutile": "aucune batterie n'est nécessaire pour tenir la limite : sans objet",
    "src_mon_batterie_sans_prix": "prix de la batterie non fourni : à chiffrer sur devis",
    "src_mon_contrat": ("0 € si {gestionnaire} ne propose pas le droit non ferme (volledig variabel) dans la zone ; au plus "
                        "{kw} kW au-dessus de la limite x {tarif} €/kW/an : la remise de l'option 5.4, terme kW contracté que "
                        "ce droit supprime (Tarievencode 2026, art. 3.14)"),
    "src_mon_dimensionnement": ("0 € si aucun jour ne peut être évité ; cette baisse si les {jours} jours classés les plus lourds "
                                "sont traités autrement : la batterie passerait de {reference} à {nominale} kWh (section « Les quarts "
                                "d'heure qui décident », jours classés un à un, pas la meilleure combinaison possible ; à valider par l'ingénieur du site)"),
    "src_mon_dimensionnement_un": ("0 € si ce jour ne peut pas être évité ; cette baisse si le jour classé le plus lourd est traité "
                                   "autrement : la batterie passerait de {reference} à {nominale} kWh (section « Les quarts d'heure "
                                   "qui décident », jours classés un à un, pas la meilleure combinaison possible ; à valider par l'ingénieur du site)"),
    "src_mon_dimensionnement_absent": "pas de batterie chiffrée à comparer",
    "src_mon_eia": ("0 € si la batterie n'est pas éligible ; sinon 40 % de l'assiette déduits du bénéfice imposable (EIA, RVO), "
                    "soit 7,6 % au taux d'impôt de 19 % et 10,32 % au taux de 25,8 % (impôt sur les sociétés 2026). Calculé "
                    "sans aide à l'investissement, aucune n'étant déclarée : une aide reçue, Flex-e comprise, se retranche "
                    "de l'assiette (RVO). "
                    "Éligible, ce que le scan ne vérifie pas : code 260101 (batterie pilotée par logiciel sur un "
                    "marché de l'électricité) ou 251118 (production renouvelable de plus de 15 kW sur le même "
                    "raccordement), 5 kW et 15 kWh au moins ; sans bénéfice, la déduction se reporte sur les années "
                    "antérieures ou suivantes"),
    "src_mon_eia_aide": ("0 € si la batterie n'est pas éligible ; sinon 40 % de l'assiette déduits du bénéfice imposable (EIA, "
                         "RVO), soit 7,6 % au taux d'impôt de 19 % et 10,32 % au taux de 25,8 % (impôt sur les sociétés 2026). "
                         "Assiette : investissement moins l'aide déclarée de {aide} € (RVO). "
                         "Éligible, ce que le scan ne vérifie pas : code 260101 (batterie pilotée par logiciel sur "
                         "un marché de l'électricité) ou 251118 (production renouvelable de plus de 15 kW sur le "
                         "même raccordement), 5 kW et 15 kWh au moins ; sans bénéfice, la déduction se reporte sur "
                         "les années antérieures ou suivantes"),
    "src_mon_eia_aide_totale": "l'aide déclarée de {aide} € couvre tout l'investissement : l'assiette de l'EIA est nulle (RVO)",
    "src_mon_eia_trop_petite": "sous le minimum de l'Energielijst 2026 (5 kW et 15 kWh) : pas d'EIA",
    "src_mon_eia_sous_seuil": ("assiette sous 2 500 € : pas d'EIA si la batterie est déclarée seule, le minimum étant de "
                               "2 500 € par déclaration (RVO, page Voorwaarden Energie-investeringsaftrek, état au 29/09/2026). "
                               "Déclarée avec d'autres investissements, le seuil porte sur le total de la déclaration : à confirmer"),
    "src_mon_eia_sans_prix": "prix de la batterie non fourni : EIA à chiffrer sur devis",
    "src_mon_revenus_flex": ("0 € sans agrégateur ou sans activation rentable ; sinon hypothèse interne de Contingency du 27/09/2026, "
                             "non vérifiée par une source publique (5 300 à 8 600 €/an pour 100 kWh et 50 kW, 26 000 à 43 000 €/an "
                             "pour 500 kWh et 250 kW), ramenée à {kwh} kWh équivalents ; à confirmer par un agrégateur, et la "
                             "batterie reste réservée les jours où elle tient la limite"),
    "src_mon_revenus_flex_extrapole": ("0 € sans agrégateur ou sans activation rentable ; sinon hypothèse interne de Contingency du "
                                       "27/09/2026, non vérifiée par une source publique (5 300 à 8 600 €/an pour 100 kWh et 50 kW, "
                                       "26 000 à 43 000 €/an pour 500 kWh et 250 kW), extrapolée à {kwh} kWh équivalents, hors de "
                                       "ces deux points ; à confirmer par un agrégateur, et la batterie reste réservée les jours où "
                                       "elle tient la limite"),
    "src_mon_bureau_heures": "estimation interne de Contingency du 27/09/2026, à valider sur un vrai dossier : ce n'est pas une mesure",
    "src_mon_bureau_valeur": ("8 à 16 h x {tarif} €/h hors TVA, tarif moyen supposé d'un bureau d'études néerlandais (estimation "
                              "interne, à valider)"),
})
SOURCES["nl"].update({
    "src_mon_scan_prix": "Flex-e (RVO): 50 % van de kosten van de scan exclusief btw, maximaal € 10.000; prijs van de scan niet opgegeven",
    "src_mon_flex_e_scan": ("Flex-e (RVO): 50 % van € {prix} exclusief btw, maximaal € 10.000; aanvragen van 06-05-2026 tot en met "
                            "15-10-2026"),
    "src_mon_etude_cout": ("Flex-e (RVO): 50 % van de kosten van een haalbaarheidsstudie, subsidie van minimaal € 10.000 en maximaal "
                           "€ 125.000; kosten niet opgegeven, er wordt geen studie verondersteld"),
    "src_mon_etude_sous_minimum": ("Flex-e (RVO): 50 % van € {cout} blijft onder het minimale subsidiebedrag van € 10.000; een studie "
                                   "onder € 20.000 krijgt geen subsidie"),
    "src_mon_etude": ("Flex-e (RVO): 50 % van € {cout} exclusief btw, subsidie tussen € 10.000 en € 125.000; aanvragen tot en met "
                      "15-10-2026"),
    "src_mon_invest_evite_decalage": ("batterij uit optie 5.1 ({nominale} kWh), overbodig als het verschuiven van processen de grens "
                                      "houdt; indicatieve prijs uit de aannames, geen offerte"),
    "src_mon_invest_evite_ecretage": ("batterij uit optie 5.1 ({nominale} kWh), overbodig als afschakelen van verbruik aanvaardbaar is, "
                                      "ten koste van de gemiste productie; indicatieve prijs uit de aannames, geen offerte"),
    "src_mon_batterie_impossible": "geen enkele batterij houdt de grens het hele jaar (optie 5.1)",
    "src_mon_batterie_inutile": "er is geen batterij nodig om de grens te houden: niet van toepassing",
    "src_mon_batterie_sans_prix": "prijs van de batterij niet opgegeven: te bepalen op basis van een offerte",
    "src_mon_contrat": ("€ 0 als {gestionnaire} in het gebied geen volledig variabel recht aanbiedt; hoogstens {kw} kW boven de "
                        "grens x {tarif} €/kW/jaar: de korting uit optie 5.4, de term gecontracteerd transportvermogen die dit "
                        "recht laat vervallen (Tarievencode 2026, art. 3.14)"),
    "src_mon_dimensionnement": ("€ 0 als geen enkele dag te vermijden is; deze daling als de {jours} als zwaarste gerangschikte dagen anders worden "
                                "opgevangen: de batterij zou van {reference} naar {nominale} kWh gaan (sectie ‘De kwartieren die "
                                "beslissen’, dagen één voor één gerangschikt, niet de best mogelijke combinatie; te bevestigen door de ingenieur van de locatie)"),
    "src_mon_dimensionnement_un": ("€ 0 als die dag niet te vermijden is; deze daling als de als zwaarste gerangschikte dag anders wordt "
                                   "opgevangen: de batterij zou van {reference} naar {nominale} kWh gaan (sectie ‘De kwartieren die "
                                   "beslissen’, dagen één voor één gerangschikt, niet de best mogelijke combinatie; te bevestigen door de ingenieur van de locatie)"),
    "src_mon_dimensionnement_absent": "geen doorgerekende batterij om mee te vergelijken",
    "src_mon_eia": ("€ 0 als de batterij niet in aanmerking komt; anders 40 % van de grondslag afgetrokken van de fiscale winst "
                    "(EIA, RVO), dus 7,6 % bij 19 % vennootschapsbelasting en 10,32 % bij 25,8 % (tarieven 2026). Berekend "
                    "zonder investeringssubsidie, omdat er geen is opgegeven: ontvangen subsidie, ook Flex-e, gaat af van de "
                    "grondslag (RVO). "
                    "In aanmerking, wat de scan niet controleert: code 260101 (batterij met software gekoppeld aan "
                    "een elektrische deelmarkt) of 251118 (duurzame opwek van meer dan 15 kW op dezelfde "
                    "aansluiting), minimaal 5 kW en 15 kWh; zonder winst wordt de aftrek verrekend met eerdere of "
                    "latere jaren"),
    "src_mon_eia_aide": ("€ 0 als de batterij niet in aanmerking komt; anders 40 % van de grondslag afgetrokken van de fiscale "
                         "winst (EIA, RVO), dus 7,6 % bij 19 % vennootschapsbelasting en 10,32 % bij 25,8 % (tarieven 2026). "
                         "Grondslag: investering min de opgegeven subsidie van € {aide} (RVO). "
                         "In aanmerking, wat de scan niet controleert: code 260101 (batterij met software gekoppeld "
                         "aan een elektrische deelmarkt) of 251118 (duurzame opwek van meer dan 15 kW op dezelfde "
                         "aansluiting), minimaal 5 kW en 15 kWh; zonder winst wordt de aftrek verrekend met eerdere "
                         "of latere jaren"),
    "src_mon_eia_aide_totale": "de opgegeven subsidie van € {aide} dekt de hele investering: de EIA-grondslag is nul (RVO)",
    "src_mon_eia_trop_petite": "onder het minimum van de Energielijst 2026 (5 kW en 15 kWh): geen EIA",
    "src_mon_eia_sous_seuil": ("grondslag onder € 2.500: geen EIA als de batterij apart wordt gemeld, want het minimum is "
                               "€ 2.500 per melding (RVO, pagina Voorwaarden Energie-investeringsaftrek, stand op 29/09/2026). "
                               "Samen met andere investeringen gemeld geldt de drempel voor het totaal van de melding: te bevestigen"),
    "src_mon_eia_sans_prix": "prijs van de batterij niet opgegeven: EIA te bepalen op basis van een offerte",
    "src_mon_revenus_flex": ("€ 0 zonder aggregator of zonder rendabele activeringen; anders interne aanname van Contingency van "
                             "27-09-2026, niet gecontroleerd aan een openbare bron (€ 5.300 tot € 8.600 per jaar voor 100 kWh en 50 kW, "
                             "€ 26.000 tot € 43.000 per jaar voor 500 kWh en 250 kW), omgerekend naar {kwh} kWh equivalent; te "
                             "bevestigen door een aggregator, en de batterij blijft gereserveerd op de dagen dat zij de grens houdt"),
    "src_mon_revenus_flex_extrapole": ("€ 0 zonder aggregator of zonder rendabele activeringen; anders interne aanname van Contingency "
                                       "van 27-09-2026, niet gecontroleerd aan een openbare bron (€ 5.300 tot € 8.600 per jaar voor "
                                       "100 kWh en 50 kW, € 26.000 tot € 43.000 per jaar voor 500 kWh en 250 kW), geëxtrapoleerd naar "
                                       "{kwh} kWh equivalent, buiten die twee punten; te bevestigen door een aggregator, en de batterij "
                                       "blijft gereserveerd op de dagen dat zij de grens houdt"),
    "src_mon_bureau_heures": "interne schatting van Contingency van 27-09-2026, te toetsen aan een echt dossier: geen meting",
    "src_mon_bureau_valeur": ("8 tot 16 uur x € {tarif} per uur exclusief btw, verondersteld gemiddeld tarief van een Nederlands "
                              "ingenieursbureau (interne schatting, te toetsen)"),
})


def _section_monetisation(r: dict[str, Any], langue: str) -> str:
    """Économies par type de client : chaque ligne seule, jamais de total (brief du 27/09/2026)."""
    m = r.get("monetisation")
    if not m:
        return ""
    t = T[langue]
    entete = f"<tr class='entete'><th>{t['grandeur']}</th><th>{t['valeur']}</th><th>{t['nature']}</th><th>{t['source']}</th></tr>"

    def ligne(cle: str, g: dict[str, Any]) -> str:
        valeur = _valeur(cle, g, langue)
        if g.get("conditionnel"):
            valeur = f"{e(t['mon_zero_ou'])} {valeur}"
        return _ligne(t[cle], valeur, g.get("nature"), source(g.get("source", ""), g.get("parametres"), langue), langue)

    def tableau(bloc: dict[str, Any], cles: tuple[str, ...]) -> str:
        return f"<table class='g'>{entete}{''.join(ligne('mon_' + c, bloc[k]) for c, k in cles)}</table>"

    non, oui, bureau = m["sans_batterie"], m["avec_batterie"], m["bureau_etudes"]
    return (f"<h3>{t['mon_titre']}</h3><p>{e(t['mon_intro'])}</p>"
            f"<h4>{e(t['mon_patron_non'].format(mesure=t['o_' + non['mesure']].lower()))}</h4>"
            + tableau(non, (("invest_evite", "investissement_evite"), ("contrat", "optimisation_contrat"),
                            ("aide_scan", "aide_scan"), ("aide_etude", "aide_etude")))
            + f"<h4>{e(t['mon_patron_oui'])}</h4>"
            + tableau(oui, (("dimensionnement", "bon_dimensionnement"), ("eia", "eia"), ("revenus_flex", "revenus_flex")))
            + f"<h4>{e(t['mon_bureau'])}</h4>"
            + tableau(bureau, (("bureau_heures", "heures"), ("bureau_valeur", "valeur")))
            + f"<p class='src'>{e(t['mon_regles'])}</p>")



def rendre(r: dict[str, Any], langue: str = "fr") -> str:
    if langue not in T:
        raise ValueError(f"langue non prise en charge : {langue}")
    t, site = T[langue], r["site"]
    deux_points = " : " if langue == "fr" else ": "  # espace avant les deux-points en français seulement
    entete = (f"<h1>{e(t['titre'])}{deux_points}{e(champ_site(site, 'nom', langue) or '')}</h1><p class='src'>{e(t['sous_titre'])}</p>")
    if site.get("exemple"):
        entete += f"<p class='exemple'>{e(t['exemple'])}</p>"
    corps = [entete, _section_qualite(r, langue), _section_synthese(r, langue), _section_conformite(r, langue), _section_entreprise(r, langue), _section_congestion(r, langue), _section_processus(r, langue),
             _section_profils(r, langue), _section_mesures(r, langue), _section_quarts_decisifs(r, langue), _section_financiere(r, langue),
             _section_monetisation(r, langue),
             _section_conclusion(r, langue), _section_etapes(r, langue), _section_hypotheses(r, langue),
             f"<h2>{t['s9']}</h2><p>{e(t['limites'])}</p><p class='src'>"
             f"{e(source('src_tarif_groupe' if r['raccordement']['categorie'] == 'GROUPE' else 'src_tarifs', {'gestionnaire': r['raccordement']['gestionnaire_tarifs'].capitalize()}, langue))}. "
             f"{e(source('src_acm_overzicht', {}, langue))}. "
             f"{e(champ_site(site, 'source_profil', langue) or '')}. {e(champ_site(site, 'licence_profil', langue) or '')}</p>",
             f"<footer>{e(t['genere'].format(jour=date.today().strftime('%d/%m/%Y'), version=r['version']))}</footer>"]
    return (f"<!doctype html><html lang='{langue}'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(t['titre'])}</title>"
            f"<style>{STYLE}</style></head><body>{''.join(corps)}</body></html>")
