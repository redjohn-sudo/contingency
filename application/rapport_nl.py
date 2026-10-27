"""Rapport des contrôles en néerlandais, celui qu'on remet à un client ou un adviseur NL.

Même données que rapport_controles.composer, même plan (Samenvatting, Wat is
aangevraagd, Toetsingskader, Beoordeling, Aan te leveren stukken). Les phrases
ne sont PAS traduites depuis le français : elles sont recalculées ici à partir
des valeurs chiffrées de chaque contrôle, pour qu'aucune phrase française ne
fuie dans le rapport et qu'un chiffre ne soit jamais recopié à la main.

Limite assumée : les contrôles communaux évalués (hauteur, bruit, usage, parc PV)
n'ont pas encore de phrase néerlandaise dédiée. Ils s'affichent avec leur titre,
leur statut, la citation communale (déjà en néerlandais) et leurs valeurs brutes.
Les contrôles du diagnostic (mesures et contrat) ont chacun leur phrase.
"""
from __future__ import annotations

import html
import math
from typing import Any

STATUT = {"constat": "Vastgesteld", "a_confirmer": "Te bevestigen", "alerte": "Aandachtspunt", "bloque": "Niet beoordeeld"}

ASPECTEN = {
    "meetgegevens": "Betrouwbaarheid van de meetgegevens",
    "netaansluiting": "Aansluiting en capaciteit",
    "externe veiligheid": "Externe veiligheid en vergunningen",
    "geluid": "Geluid",
    "ruimtelijke inpassing": "Ruimtelijke inpassing",
    "overig": "Overig",
    "batterij": "Consistentie van de batterijkenmerken",
}

CONTROLES = {
    "CTRL-BAT-SOC": "Bruikbare capaciteit binnen het laadvenster",
    "CTRL-BAT-PUISSANCE": "Gevraagd vermogen en ontlaadsnelheid",
    "CTRL-BAT-ENGAGEMENTS": "Gelijktijdige batterijverplichtingen",
    "COH-PERIODE": "Periode van de export tegen de factuur",
    "COH-UNITE": "Eenheid van het profiel tegen de factuur",
    "COH-ENERGIE": "Energie van het profiel tegen de factuur",
    "COH-PERTES": "Correctie voor meetverliezen",
    "CTRL-MARGE": "Ruimte binnen het huidige contract",
    "CTRL-GTV-MAX": "Maximaal contracteerbaar transportvermogen",
    "CTRL-GTV-DECLARE": "Capaciteit verloren tussen contract en laatste opgave",
    "CTRL-CM-1MW": "Mogelijke deelname aan congestiemanagement vanaf 1 MW",
    "CTRL-ZONE": "Status van het gebied op de openbare kaart, per richting",
    "CTRL-TRANSPORTRECHT": "Soort transportrecht",
    "CTRL-DEPASSEMENT": "Overschrijdingen van het gecontracteerd vermogen",
    "CTRL-CAPACITE-DORMANTE": "Kosten van gecontracteerde maar ongebruikte capaciteit",
    "CTRL-DELAI-OFFRE": "Twee termijnen, niet één",
    "CTRL-REGIME-DEPOT": "Toepasselijk regime volgens de indieningsdatum",
    "CTRL-HAUTEUR-COMMUNE": "Toegestane hoogte volgens de gemeente",
    "CTRL-BRUIT-COMMUNE": "Geluid op de gevel van gevoelige gebouwen",
    "CTRL-USAGE-COMMUNE": "Kwalificatie van het gebruik door de gemeente",
    "CTRL-SEUIL-PERMIS": "Drempels die een verplichting activeren",
    "CTRL-PLAFOND-PARC-PV": "Batterij begrensd door de piek van het zonnepark",
}

# Pièce manquante -> (libellé, où la trouver), dans les mots d'un adviseur néerlandais.
VELDEN = {
    "batterie_soc_instant_pct": ("Laadtoestand op het onderzochte moment (%)", "meting of expliciete aanname, ten opzichte van de resterende capaciteit"),
    "batterie_instant_engagements": ("Onderzocht moment", "datum en tijd met expliciete UTC-offset waarop de verplichtingen tegelijk gelden"),
    "batterie_nature_etat": ("Herkomst van de laadtoestand", "meting of aanname, expliciet onderscheiden"),
    "batterie_source_etat": ("Bron van de laadtoestand", "gedateerde meting of onderbouwing van het scenario"),
    "batterie_charge_max_dc_kw": ("Beschikbaar laadvermogen (DC kW)", "continue limiet aan de batterijzijde op het onderzochte moment"),
    "batterie_decharge_max_dc_kw": ("Beschikbaar ontlaadvermogen (DC kW)", "continue limiet aan de batterijzijde op het onderzochte moment"),
    "batterie_engagements_simultanes": ("Gelijktijdige batterijverplichtingen", "volledige lijst met bron, laad- en ontlaadvermogen, en gereserveerde energie per dienst"),
    "batterie_nominale_dc_kwh": ("Nominale batterijcapaciteit (DC kWh)", "technisch blad, vóór veroudering en laadgrenzen"),
    "batterie_source": ("Opgegeven batterijbron", "gedateerd technisch blad en de gebruikte bedrijfsvoorwaarden"),
    "batterie_soc_min_pct": ("Minimale laadtoestand (%)", "instelling ten opzichte van de resterende capaciteit"),
    "batterie_soc_max_pct": ("Maximale laadtoestand (%)", "instelling ten opzichte van de resterende capaciteit"),
    "batterie_soh_pct": ("Resterende capaciteit (%)", "meting of garantie op de onderzochte datum, ten opzichte van de nominale capaciteit"),
    "batterie_utile_dc_annoncee_kwh": ("Opgegeven bruikbare energie (DC kWh)", "offerte of berekening, dezelfde laadgrenzen en datum"),
    "batterie_c_rate_decharge_max": ("Maximale continue ontlaadsnelheid (h^-1)", "technisch blad, verhouding DC kW tot nominale DC kWh"),
    "batterie_puissance_dc_demandee_kw": ("Gevraagd ontlaadvermogen (DC kW)", "berekening aan de batterijzijde, vóór omzetting naar wisselstroom"),
    "gtv_kw": ("Gecontracteerd transportvermogen (kW)", "aansluit- en transportovereenkomst, pagina met de vermogens"),
    "capacite_aansluiting_kva": ("Aansluitcapaciteit (kVA)", "eerste pagina van de aansluitovereenkomst"),
    "gtv_declare_kw": ("Laatst opgegeven transportvermogen (kW)", "factuur van de netbeheerder, regel gecontracteerd transportvermogen"),
    "confirmation_gtv_declare": ("Bevestiging van het actuele transportvermogen", "laatste factuur of geldende overeenkomst: vermogen, documentbron en documentdatum, naam en datum van de menselijke controle, bevestiging dat de waarde nu geldt"),
    "periodes_gtv_facturees": ("Gefactureerde GTV-perioden", "opeenvolgende facturen: GTV, tarief en geldigheidsdata per periode; handmatige reconstructie nodig"),
    "direction": ("Transportrichting", "aansluit- en transportovereenkomst: afname of invoeding"),
    "kwmax_facture": ("Maximale belasting van de maand (kW)", "factuur van de netbeheerder, regel maximale belasting"),
    "kwh_facture": ("Afgenomen energie (kWh)", "factuur, regels afname laag en hoog opgeteld"),
    "periode_facture": ("Verbruiksperiode van de factuur", "factuur, regel verbruiksperiode"),
    "periode_facture_debut": ("Begin van de verbruiksperiode", "factuur, regel verbruiksperiode"),
    "periode_facture_fin": ("Einde van de verbruiksperiode", "factuur, regel verbruiksperiode"),
    "profil_kw": ("Kwartierwaarden (kW)", "export van de netbeheerder of het meetbedrijf"),
    "profil_horodatages": ("Tijdstempels van de kwartierwaarden", "kolom datum en tijd in de export"),
    "export_profil": ("Export van de kwartierwaarden", "opnieuw exporteren voor precies de factuurperiode"),
    "unite_profil": ("Eenheid van de export (kW of kWh per kwartier)", "kop van de export, nooit geraden"),
    "mesure_au_point_de_livraison": ("Meetpunt op het overdrachtspunt?", "aansluitovereenkomst of éénlijnschema, meting aan MS- of LS-zijde"),
    "correction_pertes_export": ("Verliescorrectie in de export", "meetbedrijf: bevestig of verliezen al zijn verwerkt en welk percentage geldt; bij onbeslisbare afronding is handmatige vergelijking nodig"),
    "meetbedrijf": ("Meetverantwoordelijke", "factuur, post meetverantwoordelijke"),
    "statut_zone_afname": ("Status van het gebied voor afname", "capaciteitskaart.netbeheernederland.nl, laag Afname, op het adres van de locatie"),
    "statut_zone_teruglevering": ("Status van het gebied voor teruglevering", "capaciteitskaart.netbeheernederland.nl, laag Teruglevering"),
    "date_carte": ("Datum van raadpleging van de capaciteitskaart", "datum waarop de capaciteitskaart is bekeken"),
    "annee_liberation_annoncee": ("Aangekondigd jaar van einde congestie", "capaciteitskaart of pagina van de netbeheerder"),
    "type_transportrecht": ("Soort transportrecht", "aansluit- en transportovereenkomst, clausule over het transportrecht"),
    "blocs_transport": ("Tijdsblokken van het transportrecht", "aansluit- en transportovereenkomst, tijdsblokken"),
    "gtv_hors_bloc_kw": ("Transportvermogen buiten de tijdsblokken (kW)", "aansluit- en transportovereenkomst"),
    "profil_horodatages": ("Tijdstempels van de kwartierwaarden", "export van de kwartierwaarden"),
    "gestionnaire": ("Netbeheerder", "kop van de overeenkomst of de factuur"),
    "commune": ("Gemeente", "adres van de locatie"),
    "puissance_kw": ("Vermogen van de installatie (kW)", "technisch blad van de installatie"),
    "capacite_kwh": ("Bruikbare capaciteit (kWh)", "technisch blad van de installatie"),
    "tarif_kw_mois_eur": ("Tarief per gecontracteerde kW per maand (euro)", "tarievenregeling van de netbeheerder, lopend jaar"),
    "mois_factures": ("Aantal gefactureerde maanden op dit contract", "facturen van de netbeheerder"),
    "date_demande": ("Datum van de aanvraag", "bevestiging van de aanvraag door de netbeheerder"),
    "date_offre": ("Datum van de offerte", "offerte van de netbeheerder"),
    "date_signature": ("Datum van ondertekening", "getekende offerte"),
    "date_depot": ("Indieningsdatum van het dossier", "bevestiging van de netbeheerder"),
    "regime_depot_gestionnaire": ("Regime van de aanvraag bij deze netbeheerder", "geldende regeling van de betrokken netbeheerder en categorie van de aansluiting"),
    "donnees_du_controle": ("Ongeldige controlegegevens", "brondocument: corrigeer de invoer van deze controle"),
    "date_mise_en_service": ("Datum van ingebruikname", "geldige datum in formaat JJJJ-MM-DD; leeg indien nog niet in gebruik"),
    "chimie_batterie": ("Batterijchemie", "technisch blad van de fabrikant, met vermelding van lithium"),
    "conforme_plan_temporaire": ("Conform het tijdelijke omgevingsplan", "toetsing van de bestaande activiteit aan het tijdelijke omgevingsplan"),
    "zone_nommee": ("Naam van het gebied", "omgevingsplan en kadastrale kaart, of bevestiging dat de locatie buiten de genoemde gebieden ligt"),
    "zone": ("Gebied van de locatie", "omgevingsplan: buitengebied, bedrijventerrein of stedelijk gebied"),
    "couplee_parc_pv": ("Gekoppeld aan een zonnepark", "situatietekening van batterij en zonnepark"),
    "grootschalig": ("Grootschalige installatie", "kwalificatie volgens de gemeentelijke regeling"),
    "regime_lieu": ("Gebiedsregime", "gemeentelijke aanwijzing van de locatie"),
    "soumis_a_permis": ("Vergunningplicht", "omgevingsplan en bevestiging van het bevoegd gezag"),
    "regle_communale": ("Gemeentelijke regel", "omgevingsplan of beleidsregel van de gemeente, lokaleregelgeving.overheid.nl"),
    "hauteur_installation_m": ("Hoogte van de installatie (m)", "tekening, inclusief fundering"),
    "adjacent_poste_380kv": ("Grenst de installatie aan het 380 kV-station?", "kadastrale kaart: bevestiging met ja of nee"),
    "bruit_facade_db": ("Geluid op de gevel dag, avond en nacht (dB(A))", "akoestisch rapport"),
    "qualification_usage": ("Gebruik van de batterij", "eigen gebruik, lokale dienst of handel"),
    "sur_site_de_l_entreprise": ("Staat de installatie op het terrein van het bedrijf?", "kadastrale kaart of huurcontract"),
    "terrain_industriel_zone": ("Gezoneerd industrieterrein?", "omgevingsplan of gemeente"),
    "puissance_pointe_parc_pv_kw": ("Piekvermogen van het zonnepark (kW)", "technisch blad van het park"),
}

# Titres néerlandais des règles citées par les contrôles. Les sources restent celles du catalogue.
REGELS = {
    "ECO-010": "Samenloop van batterijverplichtingen, interne ontwerpregel",
    "BAT-004": "Laadvenster en bruikbare batterijcapaciteit",
    "BAT-008": "De C-rate koppelt vermogen aan nominale capaciteit",
    "DAT-001": "Het kwartier is de eenheid van waarheid",
    "DAT-005": "Meting buiten het overdrachtspunt: verliescorrectie verplicht, 1,4 procent bij MS met LS-meting",
    "DAT-006": "Boven 3 x 80 A moet de meter kWmax en blindvermogen registreren",
    "ECO-005": "De gecontracteerde kW wordt betaald vanaf ondertekening, ook ongebruikt",
    "ECO-006": "De aansluitvergoeding loopt zodra de aansluiting gereed is, gebruikt of niet",
    "OPE-004": "De termijn loopt vanaf ondertekening van de offerte, niet vanaf de aanvraag",
    "OPE-007": "Eerste uitkomst: de resterende ruimte in het bestaande contract",
    "PER-004": "Reikwijdte van PGS 37-1: lithium, meer dan 20 kWh en standaardmaatregelen tot en met 400 MWh",
    "PER-010": "Meldplicht pas vanaf 800 kW: de blinde vlek van de netbeheerder",
    "PER-012": "De vergunningsdrempel verschilt per gemeente",
    "REG-007": "Energiewet artikel 6.12: wat provincie en gemeente niet mogen regelen",
    "REG-009": "Deelname aan congestiemanagement kan verplicht zijn vanaf 1 MW",
    "REG-014": "Overschrijding van het GTV kan onder dwangsom worden verboden",
    "REG-018": "Kwalificatie van het gebruik van de batterij: eigen, lokaal of handel",
    "RES-001": "Gecontracteerd transportvermogen (GTV)",
    "RES-002": "Fysieke aansluitcapaciteit is iets anders dan het transportrecht",
    "RES-011": "Plaats in de wachtrij: datum van het complete dossier en tijdige ondertekening",
    "REG-003": "Non-firm ATO: niet-vast transportrecht tegen een lager tarief",
    "REG-004": "Tijdsduurgebonden transportrecht: minstens 85% van de uren per jaar",
    "REG-005": "Transportrecht gebonden aan tijdsblokken",
    "RES-005": "Congestie van het gebied volgens de capaciteitskaart, op de datum van het onderzoek",
    "RES-006": "Afname en teruglevering kunnen een verschillende status hebben",
    "RES-021": "De aangekondigde datum van vrijgave schuift op in blokken van jaren",
    "RES-012": "Het GTV is het laatst opgegeven vermogen, niet dat van het oude contract",
    "RES-022": "Extra capaciteit hoger in het net maakt de lagere netdelen niet vrij",
    "RES-023": "De formule tussen aansluitcapaciteit en GTV: cos phi 0,85",
    "RES-024": "Opgave van het GTV voor volgend jaar uiterlijk 30 november",
    "RES-026": "Herhaalde overschrijding: de aansluiting kan worden opgeschort",
    "SIT-002": "Hoogte van het systeem: de grenzen van 5 m en 20 m uit het Bbl",
    "SIT-004": "Aanvaardbaar geluidsniveau volgens het omgevingsplan",
    "SIT-011": "Co-locatie: batterijvermogen begrensd door de opwek",
    "SIT-015": "Toegestane hoogte: de gemeente kan strenger zijn dan het Bbl",
    "SIT-016": "Geluid in cijfers: 45, 40 en 35 dB(A) dag, avond en nacht op gevoelige gevel",
    "SIT-017": "Voorwaardelijke vestigingsregels per gemeente",
    "TRA-008": "De indieningsdatum bepaalt het toepasselijke regime",
    "ECO-001": "Tariefcomponenten per categorie: gecontracteerd vermogen, vermogensmaxima en energie",
}

# Bronnen van de geciteerde regels, zonder Franse toelichting uit de catalogus.
BRONNEN = {
    "ECO-010": "Interne ontwerpregel van Contingency op basis van ECO-001, ECO-008, REG-011 tot REG-013 en BAT-004. Geen zelfstandige juridische bron.",
    "BAT-004": "SAM, Battery Dispatch BTM, Charge Limits and Priority, https://samrepo.nlr.gov/help/battery_dispatch_btm.html, geraadpleegd op 27/09/2026",
    "BAT-008": "SAM, Battery Storage BTM, https://samrepo.nlr.gov/help/battery_storage_btm.html, geraadpleegd op 27/09/2026",
    "DAT-001": "Stedin, Tarieven- en vergoedingsregeling (Grootverbruik) 2026, art. 7 lid 6, https://www.stedin.net/-/media/project/online/files/tarieven/tarieven-2026/tarieven-en-vergoedingsregeling-2026_-elektriciteit_grootverbruik.pdf, geraadpleegd op 24/09/2026 · ACM, codebesluit tijdsafhankelijke tarieven grootverbruik, 2026",
    "DAT-005": "Stedin, Tarieven- en vergoedingsregeling (Grootverbruik) 2026, artikel 5 leden 9 tot en met 11, https://www.stedin.net/-/media/project/online/files/tarieven/tarieven-2026/tarieven-en-vergoedingsregeling-2026_-elektriciteit_grootverbruik.pdf",
    "DAT-006": "Stedin, Tarieven- en vergoedingsregeling (Grootverbruik) 2026, art. 7 lid 6, https://www.stedin.net/-/media/project/online/files/tarieven/tarieven-2026/tarieven-en-vergoedingsregeling-2026_-elektriciteit_grootverbruik.pdf, geraadpleegd op 24/09/2026",
    "ECO-005": "College van Beroep voor het bedrijfsleven, ECLI:NL:CBB:2026:47",
    "ECO-006": "Stedin, Tarieven- en vergoedingsregeling (Grootverbruik) 2026, art. 4 lid 17, https://www.stedin.net/-/media/project/online/files/tarieven/tarieven-2026/tarieven-en-vergoedingsregeling-2026_-elektriciteit_grootverbruik.pdf, geraadpleegd op 24/09/2026",
    "OPE-004": "trip.nl, De redelijke aansluittermijn bij een grootverbruikaansluiting, 15/06/2023",
    "OPE-007": "nuna.energy, casus De Zwaaikom (praktijkervaring van een leverancier, cijfers met voorzichtigheid)",
    "PER-004": "PGS 37-1:2023 versie 1.1, april 2026, paragraaf 1.2, geraadpleegd op 27/09/2026: https://publicatiereeksgevaarlijkestoffen.nl/publicaties/online/pgs-37-1/2023/1-1-april-2026",
    "PER-010": "energyshift.nl, 25/04/2025",
    "PER-012": "lokaleregelgeving.overheid.nl",
    "REG-007": "wetten.overheid.nl, Energiewet BWBR0050714, art. 6.12, versie 01/01/2026 · Provincie Noord-Holland, Beleidskader grootschalige batterijen · Solar Magazine 17/04/2026, Flevoland",
    "REG-009": "Stedin, deelnameverplichting congestiemanagement",
    "REG-003": "acm.nl, codewijzigingsvoorstel non-firm ATO",
    "REG-004": "dirkzwager.nl en akd.eu, alternatieve transportrechten",
    "REG-005": "dirkzwager.nl en akd.eu, alternatieve transportrechten en tijdgebonden transporttarieven, 24/09/2026",
    "RES-005": "Capaciteitskaart Netbeheer Nederland, legenda geraadpleegd op 25/09/2026",
    "RES-006": "Stedin, netcongestie voor grootverbruikers, 24/09/2026",
    "RES-021": "RTV Utrecht, 12/06/2025 ; Enexis, update netcapaciteit, september 2026",
    "REG-014": "nieuweoogst.nl, 23/04/2025",
    "REG-018": "lokaleregelgeving.overheid.nl, regelingen van Oosterhout, Dordrecht en Tiel",
    "RES-001": "ACM, codebesluit tijdsafhankelijke tarieven grootverbruik, 2026, acm.nl",
    "RES-002": "Stedin, Tarieven- en vergoedingsregeling (Grootverbruik) 2026, art. 5, https://www.stedin.net/-/media/project/online/files/tarieven/tarieven-2026/tarieven-en-vergoedingsregeling-2026_-elektriciteit_grootverbruik.pdf, geraadpleegd op 24/09/2026",
    "RES-011": "Stedin, wachtlijst, stand september 2026",
    "RES-012": "ACM, samenvatting definitieve uitspraak CBb 23/06/2026, ECLI:NL:CBB:2026:282, https://www.acm.nl/nl/publicaties/uitspraak-cbb-northc-heeft-geen-recht-op-verhoging-van-transportvermogen-elektriciteit, geraadpleegd op 27/09/2026. Volledige uitspraak niet geraadpleegd.",
    "RES-022": "netcapaciteitcheck.nl, 27/07/2026 · NU.nl",
    "RES-023": "Stedin, Tarieven- en vergoedingsregeling (Grootverbruik) 2026, art. 5 lid 7, https://www.stedin.net/-/media/project/online/files/tarieven/tarieven-2026/tarieven-en-vergoedingsregeling-2026_-elektriciteit_grootverbruik.pdf, geraadpleegd op 24/09/2026",
    "RES-024": "Stedin, Tarieven- en vergoedingsregeling (Grootverbruik) 2026",
    "RES-026": "Stedin, Tarieven- en vergoedingsregeling (Grootverbruik) 2026",
    "SIT-002": "RVO, Handreiking, hoofdstuk 4.1.3",
    "SIT-004": "RVO, Handreiking, hoofdstukken 4 en 5",
    "SIT-011": "Provincie Noord-Holland, Beleidskader",
    "SIT-015": "lokaleregelgeving.overheid.nl, Hollands Kroon 14/07/2026 en regelingen Drechtsteden",
    "SIT-016": "lokaleregelgeving.overheid.nl, regelingen Drechtsteden",
    "SIT-017": "lokaleregelgeving.overheid.nl",
    "TRA-008": "netcapaciteitcheck.nl, 27/07/2026, op basis van berichten van Enexis en Liander. Te bevestigen op de pagina van de betrokken netbeheerder",
    "ECO-001": "Tarievencode elektriciteit 2026, artikelen 3.9 tot en met 3.11 en bijlage 5, Staatscourant 2026 nr. 4090, https://zoek.officielebekendmakingen.nl/stcrt-2026-4090.html"
}


def _getal(x: Any, decimalen: int = 1) -> str:
    """Nederlandse notatie: punt voor duizendtallen, komma als decimaalteken."""
    if x is None:
        return "onbekend"
    if not math.isfinite(float(x)):
        return "ongeldige numerieke waarde"
    tekst = f"{float(x):,.{decimalen}f}"
    return tekst.replace(",", " ").replace(".", ",").replace(" ", ".")


def _zin(controle: dict[str, Any]) -> tuple[str, str | None]:
    """(bevinding, gevolg) in het Nederlands, berekend uit de waarden van de controle."""
    ident, statut, v = controle["id"], controle["statut"], controle.get("valeurs") or {}
    if v.get("raison") == "gtv_reference_non_confirmee":
        return ("Het actuele transportvermogen is niet bevestigd. De opgegeven laatste waarde is ongeldig "
                "of verschilt van de ATO zonder gedocumenteerde bevestiging. Er wordt geen ruimte, "
                "overschrijding of besparing berekend tegen de oude ATO-waarde.", None)
    if v.get("raison") == "gtv_cout_periode_non_confirmee":
        return ("ATO en laatste opgave verschillen. Bevestiging van het huidige GTV bewijst niet dat "
                "dit voor alle gefactureerde maanden gold. Kosten van ongebruikt vermogen worden "
                "niet berekend zonder reconstructie van de geldende perioden.", None)
    if v.get("raison") == "entree_contrat_invalide":
        return (f"Ongeldige invoer voor {_veld(v['champ'])[0]}: geef eindige, niet-negatieve getallen op, "
                "geen ja/nee-waarde.", None)
    if v.get("raison") == "calcul_contrat_non_fini":
        return (f"De berekening met {_veld(v['champ'])[0]} valt buiten het numerieke bereik. "
                "Controleer de opgegeven waarde.", None)
    if v.get("raison") == "direction_invalide":
        return "Ongeldige transportrichting: geef afname of invoeding op.", None
    if v.get("raison") == "terrain_bruit_invalide":
        return "Bevestig met ja of nee of de locatie op een gezoneerd industrieterrein ligt, op basis van het omgevingsplan of de gemeente.", None
    if v.get("raison") == "mesures_bruit_incompletes":
        return "Onvolledige geluidgegevens: geef de niveaus voor dag, avond en nacht op. Er is geen conclusie voor alle drie perioden mogelijk.", None
    if v.get("raison") == "mesures_bruit_invalides":
        return "Ongeldige geluidgegevens: elke periode vereist een eindig getal, geen ja/nee-waarde of tekst.", None
    if v.get("raison") == "annee_liberation_invalide":
        return "Ongeldig jaar voor het einde van de congestie: geef een geheel jaar van 1 tot en met 9995 op, zonder ja/nee-waarde of fractie. Ook vier jaar later moet kunnen worden onderzocht.", None
    if v.get("raison") == "adjacence_380kv_invalide":
        return "Bevestig met ja of nee of de installatie aan het 380 kV-station grenst; tekst en numerieke waarden zijn niet geldig.", None
    if ident.startswith("COH-"):
        raisons = {
            "profil_invalide": "Ongeldig profiel: geef eindige, niet-negatieve meetwaarden op die naar kW kunnen worden omgerekend.",
            "kwmax_invalide": "Ongeldige maximale belasting op de factuur: geef een eindig, niet-negatief getal op.",
            "kwh_invalide": "Ongeldige gefactureerde energie: geef een eindig, niet-negatief getal op.",
            "point_livraison_invalide": "Geef aan of de meter op het overdrachtspunt staat: ja, nee of onbekend.",
            "pointes_nulles": "Profiel en gefactureerde maximale belasting zijn nul. Daarmee is kW niet van kWh per kwartier te onderscheiden; de eenheid is niet bevestigd.",
            "pointe_nulle": "Het volledige profiel is nul, maar de gefactureerde maximale belasting is positief. De eenheid kan niet worden bevestigd, ook niet binnen de afrondingstolerantie.",
            "kwmax_nul": "Het profiel bevat positief vermogen, maar de gefactureerde maximale belasting is nul. Controleer de factuur en de periode.",
            "kwh_nul": "De gefactureerde energie is nul, maar het profiel bevat positieve energie. Het relatieve verschil is niet gedefinieerd. Controleer de metingen en de factuur.",
            "calcul_non_fini": "Deze waarden leveren geen eindig berekeningsresultaat op. Controleer de meetwaarden en de factuur.",
            "unite_non_confirmee": "Energie niet vergeleken: de eenheid van het profiel is niet bevestigd.",
            "correction_pertes_ambigue": "Verliescorrectie niet vast te stellen: zowel de ongecorrigeerde als de gecorrigeerde piek past binnen de factuurtolerantie. Er wordt geen factor gekozen. Ruimte en energie worden niet berekend totdat het meetbedrijf de correctiestatus en het geldende percentage heeft bevestigd.",
        }
        if v.get("raison") in raisons:
            return raisons[v["raison"]], None
    if statut == "bloque" and ident not in ("COH-PERIODE", "COH-UNITE", "COH-ENERGIE", "CTRL-TRANSPORTRECHT"):
        return "Niet beoordeeld: er ontbreekt een stuk, zie hieronder wat nodig is.", None
    if ident == "CTRL-BAT-SOC":
        return (f"{_getal(v['exploitable_dc_kwh'])} kWh DC bruikbaar volgens de opgegeven nominale capaciteit, "
                f"laadgrenzen en resterende capaciteit; {_getal(v['annoncee_dc_kwh'])} kWh DC opgegeven.",
                "Alleen een rekenkundige controle bij nominale spanning. Temperatuur, conversieverliezen, "
                "hulpverbruik en initiële lading zijn niet gesimuleerd. Dit is geen garantie voor energie op het net.")
    if ident == "CTRL-BAT-ENGAGEMENTS":
        engage, beschikbaar = v['engage'], v['disponible']
        aard = 'meting' if v['nature_etat'] == 'mesure' else 'aanname'
        return (f"Op {v['instant']}: {v['nombre_services']} gelijktijdig opgegeven diensten ({aard}). "
                f"Ontladen: {_getal(engage['puissance_decharge_dc_kw'])}/{_getal(beschikbaar['puissance_decharge_dc_kw'])} kW DC "
                f"en {_getal(engage['energie_decharge_dc_kwh'])}/{_getal(beschikbaar['energie_decharge_dc_kwh'])} kWh DC gereserveerd/beschikbaar. "
                f"Opladen: {_getal(engage['puissance_charge_dc_kw'])}/{_getal(beschikbaar['puissance_charge_dc_kw'])} kW DC "
                f"en {_getal(engage['energie_charge_dc_kwh'])}/{_getal(beschikbaar['energie_charge_dc_kwh'])} kWh DC gereserveerd/beschikbaar.",
                "Interne consistentiecontrole, zonder juridische werking. Verplichtingen per richting worden opgeteld; "
                "laden en ontladen worden niet tegen elkaar weggestreept. Moment, reserves en gelijktijdigheid zijn opgegeven. "
                "Laadverloop, herladen, werkelijke activering, AC-omzetting en jaarlijkse inkomsten zijn niet getoetst. "
                "Herhaal dit voor elk kritisch moment; een onvolledige lijst kan een conflict verbergen.")
    if ident == "CTRL-BAT-PUISSANCE":
        return (f"{_getal(v['demande_dc_kw'])} kW DC gevraagd tegenover maximaal "
                f"{_getal(v['puissance_max_dc_kw'])} kW DC volgens de opgegeven continue C-rate "
                f"({_getal(v['nominale_dc_kwh'])} kWh nominaal × {_getal(v['c_rate_max'], 3)} h^-1).",
                "De grenzen van omvormer, temperatuur en spanning blijven te controleren. "
                "Dit is geen garantie voor beschikbaar vermogen op het net.")
    if ident == "COH-PERIODE":
        if v.get("raison") == "periode_invalide":
            return "Ongeldige factuurdatums of tijdzone. Controleer de twee volledige datums en de tijdzone van de factuur.", None
        if v.get("raison") == "horodatages_invalides":
            return ("De tijdstempels zijn ongeldig: geef het einde van elk kwartier met UTC-offset op. "
                    "Ontbrekende, dubbele, verschoven of omgekeerde kwartieren worden niet geaccepteerd.", None)
        if statut == "constat":
            return (f"De export dekt de gefactureerde periode: {v['mesures']} kwartieren tegen "
                    f"{v['attendues']} verwacht in {v.get('fuseau_facture', 'Europe/Amsterdam')}; grenzen en opeenvolging gecontroleerd. Het meetbedrijf kan waarden hebben gereconstrueerd "
                    "(Meetcode 5.4.3); zonder kwaliteitskolom in het bestand blijft hun status onbekend.", None)
        if "mesures" in v:
            return (f"De export dekt de gefactureerde periode niet precies: {v['mesures']} metingen, "
                    f"{v.get('horodatages', v['mesures'])} tijdstempels tegen {v['attendues']} kwartieren verwacht "
                    f"in {v.get('fuseau_facture', 'Europe/Amsterdam')}, waarvan {v.get('hors_periode', 0)} buiten de periode. "
                    "De piek kan ontbreken, dus geen enkele vergelijking met de kWmax is betrouwbaar.", None)
        return "De periode van de export is niet te controleren tegen de factuur.", None
    if ident == "COH-UNITE":
        if v.get("raison") == "periode_non_confirmee":
            return "Eenheid niet gecontroleerd: de periode van de export is niet bevestigd tegen de factuur.", None
        if statut == "constat":
            soort = "bruto" if v.get("correspondance") == "brute" else "na verliescorrectie"
            return (f"Piek van het profiel {_getal(v['pointe_comparee'])} kW ({soort}), maximale belasting "
                    f"op de factuur {_getal(v['kwmax_facture'])} kW: gelijk binnen de afronding van de factuur. "
                    "Eenheid bevestigd.", None)
        if "rapport" in v:
            return (f"Tegenstrijdig: piek van het profiel {_getal(v['pointe_kw'])} kW tegen "
                    f"{_getal(v['kwmax_facture'])} kW op de factuur, verhouding {_getal(v['rapport'], 3)}. "
                    "Geen enkele vermogensconclusie is betrouwbaar zolang dit niet is opgelost.", None)
        return "Eenheid niet te controleren: de maximale belasting van dezelfde periode ontbreekt.", None
    if ident == "COH-ENERGIE":
        if "ecart" not in v:
            return "Gefactureerde energie ontbreekt: de dekking van het profiel is niet te controleren.", None
        basis = (f"Energie van het profiel {_getal(v['energie_profil_kwh'], 0)} kWh, gefactureerd "
                 f"{_getal(v['kwh_facture'], 0)} kWh, verschil {_getal(v['ecart'] * 100)} %")
        if statut == "constat":
            return basis + ", binnen de meetnauwkeurigheid.", None
        if statut == "alerte":
            return basis + ", boven de meetnauwkeurigheid maar binnen de grens van 5 %.", None
        return basis + ", boven 5 %. Andere periode, onvolledige export of verkeerde eenheid.", None
    if ident == "COH-PERTES":
        if statut == "constat":
            return "Meting op het overdrachtspunt: geen verliescorrectie nodig.", None
        return (f"Meting buiten het overdrachtspunt: gefactureerde waarden zijn gecorrigeerd voor verliezen, "
                f"standaard {_getal(v.get('correction_defaut', 0.014) * 100)} % bij MS-aansluitingen met LS-meting, "
                "tenzij een ander percentage is overeengekomen. Vergelijk met het GTV op de "
                "gecorrigeerde waarden.", None)
    if ident == "CTRL-MARGE":
        zin = (f"Hoogste kwartierwaarde {_getal(v['pointe_kw'])} kW bij een gecontracteerd transportvermogen "
               f"van {_getal(v['gtv_kw'])} kW. Ruimte binnen het contract: {_getal(v['marge_kw'])} kW. ")
        if v['taux_utilisation'] is None:
            zin += "Bij nul gecontracteerd vermogen is geen gebruikspercentage gedefinieerd."
        else:
            zin += f"Het contract wordt voor {_getal(v['taux_utilisation'] * 100, 0)} % gebruikt."
        if v.get("nombre_quarts_en_depassement"):
            zin += (f" {v['nombre_quarts_en_depassement']} van de {v['nombre_quarts_mesures']} kwartieren "
                    "liggen boven het contract.")
        return zin, ("De facturatie hangt af van de tariefcategorie: maand- of weekmaxima, eventueel "
                     "gewogen, en andere tariefcomponenten. De fysieke ruimte bepaalt niet op zichzelf het factuurbedrag.")
    if ident == "CTRL-GTV-MAX":
        return (f"Met een aansluitcapaciteit van {_getal(v['capacite_kva'])} kVA is maximaal "
                f"{_getal(v['gtv_max_kw'])} kW transport te contracteren (gebruikelijke factor "
                f"{_getal(v['facteur_cos_phi'], 2)}).",
                "Een hoger contract vraagt een aanvraag bij de netbeheerder en kan in een congestiegebied "
                "worden geweigerd. Een andere factor geldt alleen als die in het contract staat.")
    if ident == "CTRL-GTV-DECLARE":
        return (f"Contract {_getal(v['gtv_contrat_kw'])} kW, laatst opgegeven vermogen "
                f"{_getal(v['gtv_declare_kw'])} kW, verschil {_getal(v['ecart_kw'])} kW.",
                "Het afdwingbare recht is het laatst opgegeven vermogen. Terug naar het contractcijfer is "
                "een verzwaringsaanvraag, die in congestie kan worden geweigerd.")
    if ident == "CTRL-TRANSPORTRECHT":
        if statut == 'bloque':
            if v.get('raison') == 'blocs_invalides':
                return ("Ongeldige of dubbelzinnige tijdsblokken. Geef verschillende kwartiergrenzen in Europe/Amsterdam op, "
                        "bijvoorbeeld 22:00-06:00. 24:00 is alleen toegestaan als eindtijd.", None)
            if v.get('raison') == 'profil_ou_limite_invalide':
                return ("Profiel of vermogen buiten de tijdsblokken ongeldig. Elk kwartier vereist één eindtijd met UTC-offset "
                        "en één eindige, niet-negatieve afnamewaarde. Controleer ook het toegestane vermogen buiten de blokken.", None)
            return "Niet beoordeeld: controleer het transportrecht en lever de ontbrekende gegevens aan.", None
        soort = v.get("nature")
        if soort == "vast":
            return "Vast transportrecht: het hele jaar beschikbaar binnen het gecontracteerd vermogen.", None
        if soort == "non_firm":
            return ("Non-firm transportrecht: het contract moet de omstandigheden van beschikbaarheid, de methode "
                    "van vaststelling en de aankondiging van vrijgave beschrijven.",
                    "Geen enkele studie mag uitgaan van continue beschikbaarheid.")
        if soort == "tijdsduurgebonden":
            return (f"Tijdsduurgebonden transportrecht: {_getal(v['heures_garanties'], 0)} van de 8.760 uur "
                    f"gegarandeerd, tot {_getal(v['heures_coupables'], 0)} uur kan worden onderbroken.",
                    "Elke ruimte, opwek of peak shaving wordt herberekend op 85% van de uren, niet op het hele jaar.")
        if soort == "tijdsblok":
            zin = (f"Transportrecht in tijdsblokken ({v['blocs']}): {v['quarts_hors_bloc_au_dessus']} kwartier(en) "
                   f"buiten de blokken boven {_getal(v['transport_hors_bloc_kw'], 0)} kW, beoordeeld in Europe/Amsterdam")
            if v["quarts_hors_bloc_au_dessus"]:
                return (zin + f", piek buiten de blokken {_getal(v['pointe_hors_bloc_kw'])} kW.",
                        "Buiten de blokken is de locatie niet conform: dit verbruik moet binnen de blokken vallen "
                        "of onder een ander recht.")
            return zin + ".", None
        return "Soort transportrecht niet herkend of niet te beoordelen.", None
    if ident == "CTRL-ZONE":
        kaart = {"beschikbaar": "transportcapaciteit beschikbaar zonder wachtrij",
                 "beperkt": "transportcapaciteit beperkt beschikbaar zonder wachtrij",
                 "onderzoek": "gebied is in onderzoek met wachtrij",
                 "tekort": "tekort aan transportcapaciteit met wachtrij",
                 "a_evaluer": "kleur wordt later toegevoegd"}
        if "statut_afname" not in v:
            return "Status van het gebied niet herkend: gebruik de legenda van de capaciteitskaart.", None
        zin = (f"Capaciteitskaart van {_waarde('date_carte', v['date_carte'])}: afname « {kaart[v['statut_afname']]} », "
               f"teruglevering « {kaart[v['statut_teruglevering']]} ».")
        if v["asymetrique"]:
            zin += " De twee richtingen verschillen: elk wordt apart behandeld."
        if v.get("non_evaluee"):
            zin += (" Kleur nog niet toegekend: het gebied is niet beoordeeld, niets wijst op beschikbare capaciteit; "
                    "de status wordt bij de netbeheerder opgevraagd.")
        if "annee_annoncee" in v:
            zin += (f" Einde congestie aangekondigd in {v['annee_annoncee']}: elk plan dat daarvan afhangt, "
                    f"moet ook in {v['annee_a_tester']} worden getoetst.")
        gevolg = ("Elk extra vermogen voor afname gaat via de wachtrij: de ruimte binnen het huidige contract "
                  "is de enige capaciteit die zonder wachten beschikbaar is.") if v["file_afname"] else None
        return zin, gevolg
    if ident == "CTRL-CM-1MW":
        if v["concerne"]:
            return (f"Gecontracteerd transportvermogen {_getal(v['gtv_kw'], 0)} kW, boven de drempel van 1 MW: "
                    "een deelnameverplichting aan congestiemanagement is mogelijk en moet bij de netbeheerder "
                    "worden nagevraagd.",
                    "Afhankelijk van de richting van de congestie kan de netbeheerder minder of meer afname vragen. "
                    "Zonder contract of toepasselijke instructie wordt niets beperkt.")
        return (f"Gecontracteerd transportvermogen {_getal(v['gtv_kw'], 0)} kW, onder de drempel van 1 MW: "
                "geen deelnameverplichting op deze grond.", None)
    if ident == "CTRL-DEPASSEMENT":
        aantal = len(v.get("blocs_en_depassement", []))
        return (f"{aantal} van de {v['nombre_blocs']} blokken van 24 uur hebben minstens één kwartier "
                f"boven het gecontracteerd vermogen; langste reeks {v['plus_longue_serie_blocs']} blok(ken).",
                "Overschrijding wordt gefactureerd, kan onder dwangsom worden verboden en na twee "
                "opeenvolgende maanden tot opschorting van de aansluiting leiden.")
    if ident == "CTRL-CAPACITE-DORMANTE":
        return (f"{_getal(v['kw_dormants'])} kW gecontracteerd maar niet bereikt in de gemeten periode, "
                f"gewaardeerd op {_getal(v['cout_eur'], 0)} euro bij ongewijzigd GTV en tarief "
                f"gedurende {_getal(v.get('mois_factures'), 2)} opgegeven maanden. "
                "Indicatief bedrag voor alleen deze component, geen gegarandeerde besparing.",
                "Gecontracteerd vermogen wordt vanaf ondertekening betaald, gebruikt of niet. Een verlaging kan "
                "deze component verkleinen, afhankelijk van contractvoorwaarden en ingangsdata, en verlaagt ook het vaste transportrecht. "
                "Een latere verhoging vereist een nieuwe overeenkomst en hangt af van beschikbare transportcapaciteit.")
    if ident == "CTRL-BRUIT-COMMUNE" and "exception" in v:
        return ("De cijfermatige gemeentelijke geluidgrenzen gelden hier niet wegens het gezoneerde industrieterrein. Het aanvaardbare niveau moet uit het omgevingsplan volgen.",
                "Dit is geen vrijstelling van alle geluidvoorwaarden.")
    if ident == "CTRL-BRUIT-COMMUNE" and "mesures_db" in v and "seuils_db" in v:
        perioden = {"jour": "dag", "soir": "avond", "nuit": "nacht"}
        cijfers = "; ".join(f"{naam}: {_getal(v['mesures_db'][sleutel])} dB(A), grens {_getal(v['seuils_db'][sleutel])} dB(A)"
                            for sleutel, naam in perioden.items())
        return (("Gemeentelijke grens overschreden. " if statut == "alerte" else "Opgegeven niveaus binnen de gemeentelijke grenzen. ") + cijfers,
                "De vergelijking geldt voor de drie opgegeven perioden binnen het vooraf getoetste toepassingsgebied.")
    if ident == "CTRL-SEUIL-PERMIS":
        pgs = {
            'sous_seuil': 'De capaciteit overschrijdt de drempel van 20 kWh niet.',
            'hors_champ_chimie': 'De opgegeven chemie valt buiten het lithiumbereik van PGS 37-1.',
            'dans_plage': 'Lithiumopslag van meer dan 20 kWh tot en met 400 MWh: gebruiksuitzonderingen en toepasselijke voorschriften van PGS 37-1 moeten worden bevestigd.',
            'sur_mesure': 'Meer dan 400 MWh: een risicoanalyse op maat en afstemming met de veiligheidsregio zijn nodig, in lijn met PGS 37-1.',
        }.get(v.get('pgs37_1'), 'De toepasselijkheid van PGS 37-1 is niet vastgesteld.')
        permis = v.get('permis_communal_requis')
        communal = ('Volgens het opgegeven toepassingsgebied is een gemeentelijke vergunning vereist.' if permis is True
                    else 'Deze gemeentelijke vergunningsdrempel geldt hier niet of is niet bereikt.' if permis is False
                    else 'De gemeentelijke vergunningplicht is niet vastgesteld.')
        declaration = ('Vanaf 800 kW wordt een meldplicht genoemd; de sectorbron moet in de code worden bevestigd.'
                       if v.get('declaration_800_kw') else 'De meldingsdrempel van 800 kW is niet bereikt.')
        return f"{pgs} {communal} {declaration}", None
    if ident == "CTRL-DELAI-OFFRE":
        return (f"{v['jours_demande_offre']} dagen tussen aanvraag en offerte, daarna "
                f"{v['jours_offre_signature']} dagen tot ondertekening. "
                "De termijn vóór ondertekening blijft afzonderlijk zichtbaar.", None)
    if ident == "CTRL-REGIME-DEPOT":
        periode = 'vóór' if v['regime_anterieur'] else 'op of na'
        contexte = ('Enexis noemt een overgang van 01-07-2026 tot 01-01-2027.'
                    if v.get('gestionnaire') == 'enexis' else
                    'Liander maakt onderscheid voor nieuwe aanvragen in congestiegebieden.')
        return (f"Aanvraag van {_waarde('date_depot', v['date_depot'])}, {periode} 01-07-2026. "
                f"{contexte} De individuele behandeling hangt af van aanvraag en aansluiting en is nog niet bevestigd.", None)
    return "Voor deze controle is nog geen Nederlandse toelichting beschikbaar. Raadpleeg de Franse versie; hieruit volgt geen bevestiging van conformiteit.", None


def _dekking(bilan: dict[str, Any]) -> str:
    niet = bilan["juridiques"] - bilan["testees"]
    return (f"Dit rapport past {bilan['controles']} controles toe, die {bilan['testees']} van de "
            f"{bilan['juridiques']} juridische of technische regels uit de catalogus toetsen. De {niet} "
            f"andere zijn NIET automatisch gecontroleerd: {len(bilan['par_categorie']['codable'])} zijn "
            f"programmeerbaar en in behandeling, {len(bilan['par_categorie']['procedure'])} zijn procedureel "
            f"en blijven voor de adviseur, {len(bilan['par_categorie']['a_verifier'])} hebben nog een te "
            f"bevestigen bron. {len(bilan.get('conception_testees', []))} interne ontwerpregel(s) zijn "
            "afzonderlijk getoetst, zonder juridische werking. Het ontbreken van een waarschuwing op een niet getoetste regel betekent geen "
            "conformiteit.")


def _bron(tekst: str) -> str:
    """Bron uit de catalogus zonder Franse toelichting: naam, vindplaats en datum van raadpleging."""
    import re
    tekst = re.sub(r"\s*\([^)]*\)", "", str(tekst))
    tekst = re.sub(r"\blu le (\d{2}/\d{2}/\d{4})", r"geraadpleegd op \1", tekst)
    delen = [d.strip() for d in re.split(r"\s*;\s*", tekst) if d.strip()]
    return " · ".join(delen)


def _waarde(sleutel: str, waarde: Any) -> str:
    """Waarde zoals een Nederlandse lezer die verwacht: 63.135, 01-08-2026, Liander, kW."""
    import re
    tekst = str(waarde).split("  (source")[0].strip()
    if isinstance(waarde, bool):
        return 'ja' if waarde else 'nee'
    if sleutel == "gestionnaire":
        return tekst[:1].upper() + tekst[1:]
    if sleutel == "unite_profil":
        return {"kw": "kW", "kwh_par_quart": "kWh per kwartier"}.get(tekst.lower(), tekst)
    if sleutel == "direction":
        return {"soutirage": "afname", "injection": "invoeding"}.get(tekst.lower(), tekst)
    if sleutel == "batterie_nature_etat":
        return {'mesure': 'meting', 'hypothese': 'aanname'}.get(tekst, tekst)
    if sleutel == "batterie_engagements_simultanes" and isinstance(waarde, list):
        beschrijvingen = []
        for dienst in waarde:
            if not isinstance(dienst, dict):
                beschrijvingen.append('Onvolledige dienst')
                continue
            cijfers = ', '.join(f"{label}: {dienst.get(veld, 'ontbreekt')} {eenheid}"
                               for veld, label, eenheid in (
                                   ('puissance_decharge_dc_kw', 'ontladen', 'kW DC'),
                                   ('puissance_charge_dc_kw', 'laden', 'kW DC'),
                                   ('energie_decharge_dc_kwh', 'ontlaadreserve', 'kWh DC'),
                                   ('energie_charge_dc_kwh', 'laadreserve', 'kWh DC')))
            beschrijvingen.append(f"{dienst.get('nom', 'Naam ontbreekt')}: {cijfers}. Bron: {dienst.get('source', 'ontbreekt')}")
        return ' ; '.join(beschrijvingen)
    datum = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", tekst)
    if datum:
        return f"{datum[3]}-{datum[2]}-{datum[1]}"
    try:
        getal = float(tekst)
    except ValueError:
        return tekst
    if not math.isfinite(getal):
        return "ongeldige numerieke waarde"
    if sleutel == 'annee_liberation_annoncee':
        return str(int(getal)) if getal == int(getal) else tekst
    return _getal(getal, 0 if getal == int(getal) else 1)


def _veld(champ: str) -> tuple[str, str]:
    return VELDEN.get(champ, (champ, "zie de toelichting van de controle"))


def en_html(rapport: dict[str, Any], klant: str | None = None, qualite: dict[str, Any] | None = None) -> str:
    """HTML-weergave in het Nederlands, zelfde plan als het Franse rapport. ``qualite`` : pagina « Kwaliteit van de
    gegevens » vooraan (FB1), met het voorbehoud op de piek bij de controles die ervan afhangen."""
    import rapport_flex
    e = lambda x: html.escape(str(x))
    voorbehoud = sum(1 for c in rapport["controles"] if c.get("reserves_qualite"))
    kleuren = {"constat": "#1a7f37", "a_confirmer": "#9a6700", "alerte": "#9a6700", "bloque": "#57606a"}
    versie = rapport["version_catalogue"]
    tel = rapport["compte"]
    m = ["<!doctype html><html lang='nl'><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width, initial-scale=1'>",
         "<title>Contingency, controlerapport</title>",
         "<style>body{font-family:Inter,system-ui,sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem;overflow-wrap:anywhere;"
         "line-height:1.55;color:#1f2328}h1{font-size:clamp(1.25rem,4vw,1.6rem);margin-bottom:.2rem}h2{font-size:1.1rem;"
         "margin-top:2.2rem;border-bottom:1px solid #d0d7de;padding-bottom:.3rem}h3{font-size:.95rem;"
         "margin-top:1.4rem;color:#57606a}.c{border-left:3px solid #d0d7de;padding:.5rem 0 .5rem .8rem;"
         "margin:.8rem 0}.s{font-weight:600}.bron{color:#57606a;font-size:.85rem}table{border-collapse:"
         "collapse;width:100%;font-size:.92rem}td{border-top:1px solid #eaeef2;padding:.4rem .5rem;"
         "vertical-align:top}td:first-child{width:38%;color:#57606a}footer{margin-top:2.5rem;color:#57606a;"
         f"font-size:.85rem;border-top:1px solid #d0d7de;padding-top:1rem}}{rapport_flex.STYLE_QUALITE if qualite else ''}</style>",
         "<h1>Controlerapport</h1>"]
    if klant:
        m.append(f"<p class='bron'>{e(klant)}</p>")
    if qualite:
        m.append(rapport_flex._section_qualite(qualite, "nl"))
    m += ["<h2>1. Samenvatting</h2>",
          f"<p>{rapport['evaluables']} van de {rapport['total']} controles beoordeeld. Vastgesteld {tel['constat']}, "
          + (f"te bevestigen {tel['a_confirmer']}, " if tel.get("a_confirmer") else "")
          + f"aandachtspunten {tel['alerte']}, niet beoordeeld {tel['bloque']}.</p>"]
    marge = next((c for c in rapport["controles"] if c["id"] == "CTRL-MARGE" and c["statut"] != "bloque"), None)
    if marge:
        v = marge["valeurs"]
        # De ruimte zelf draagt haar voorbehoud (besluit van Astra van 30/09, revue van 69800f2, P1-V).
        m.append(f"<p><strong>Ruimte binnen het huidige contract: {e(_getal(v['marge_kw']))} kW"
                 + (", te bevestigen" if marge.get("reserves_qualite") else "") + "</strong> "
                 f"(hoogste kwartier {e(_getal(v['pointe_kw']))} kW, contract {e(_getal(v['gtv_kw']))} kW).</p>")
    if voorbehoud:
        m.append(f"<p style='color:#9a6700'><strong>Te bevestigen.</strong> {voorbehoud} controle(s) gebruiken waarden "
                 "waarvan de kwaliteit niet als meting is gedocumenteerd: hun resultaten blijven indicatief (zie elke "
                 "controle en de kwaliteitspagina).</p>")
    eenheid = next((c for c in rapport["controles"] if c["id"] == "COH-UNITE"), None)
    if eenheid is not None and eenheid["statut"] != "constat":
        m.append(f"<p style='color:#9a6700'><strong>Metingen niet bevestigd.</strong> {e(_zin(eenheid)[0])} "
                 "Er wordt geen vermogensconclusie gegeven zolang dit niet is opgelost.</p>")
    aandacht = [c for groep in rapport["aspects"] for c in groep["controles"] if c["statut"] == "alerte"]
    if aandacht:
        m.append("<ul>" + "".join(f"<li><strong>{e(CONTROLES.get(c['id'], c['id']))}</strong>. "
                                  f"{e(_zin(c)[0])}</li>" for c in aandacht) + "</ul>")
    m.append(f"<p><strong>Reikwijdte.</strong> {e(_dekking(rapport['couverture']))}</p>")

    m.append("<h2>2. Wat is aangevraagd</h2>")
    referentie = rapport.get('reference_gtv')
    if referentie:
        if referentie['statut'] == 'bloque':
            m.append("<p>Actueel transportvermogen nog te bevestigen: de laatste waarde is ongeldig "
                     "of wijkt zonder gedocumenteerde bevestiging af van de ATO. Geen ruimte of "
                     "besparing berekend tegen de oude ATO.</p>")
        else:
            bewijs = referentie['confirmation']
            m.append(f"<p>Referentie voor de controles: laatst opgegeven vermogen {e(_getal(referentie['reference_kw']))} kW; "
                     f"waarde in de aangeleverde ATO {e(_getal(referentie['gtv_ato_kw']))} kW. "
                     f"Bron: {e(bewijs['source_document'])}, document van {e(_waarde('date_document', bewijs['date_document']))}. "
                     f"Bevestiging ingevuld door {e(bewijs['verifie_par'])} op {e(_waarde('date_verification', bewijs['date_verification']))}. "
                     "De toepassing controleert niet de authenticiteit van het document of de identiteit van de lezer. "
                     "Een latere verhoging vraagt een nieuwe overeenkomst en hangt af van beschikbare transportcapaciteit.</p>")
    profiel = rapport["profil"]
    if profiel["mesures"]:
        m.append("<p>Geen nieuw project: diagnose van het bestaande contract en de metingen. "
                 f"Profiel van {profiel['mesures']} kwartierwaarden, hoogste waarde "
                 f"{e(_getal(profiel['pointe_kw']) if isinstance(profiel['pointe_kw'], (int, float)) else 'niet berekenbaar')} kW.</p>")
        if profiel.get("facteur_correction_pertes", 1.) != 1.:
            m.append(f"<p>Piek vóór correctie: {e(_getal(profiel['pointe_brute_kw']))} kW; "
                     "verliescorrectie gebruikt bij de vergelijking met de factuur: "
                     f"+{e(_getal((profiel['facteur_correction_pertes'] - 1) * 100))} %. "
                     "Deze correctie geldt voor de vermogens- en energiecontroles. "
                     "De standaard van 1,4 % betreft MS-aansluitingen met LS-meting; "
                     "het overeengekomen percentage moet nog worden gecontroleerd.</p>")
    m.append("<table>")
    for sleutel, waarde in rapport["donnees_fournies"].items():
        schoon = _waarde(sleutel, waarde)
        label, bron = _veld(sleutel)
        m.append(f"<tr><td>{e(label)}</td><td>{e(schoon)}<br><span class='bron'>Bron: {e(bron)}</span></td></tr>")
    m.append("</table>")

    m.append("<h2>3. Toetsingskader</h2><ul>")
    for bron in rapport["toetsingskader"]:
        titel = REGELS.get(bron["id"])
        tekst = f"{bron['id']}. {titel}. " if titel else f"{bron['id']}. "
        m.append(f"<li class='bron'>{e(tekst)}Bron: {e(BRONNEN.get(bron['id']) or _bron(bron['source']))}</li>")
    m.append("</ul>")

    m.append("<h2>4. Beoordeling</h2>")
    for groep in rapport["aspects"]:
        m.append(f"<h3>{e(ASPECTEN.get(groep['code'], groep['code']))}</h3>")
        for c in groep["controles"]:
            kleur = kleuren.get(c["statut_affiche"], "#57606a")
            bevinding, gevolg = _zin(c)
            m.append(f"<div class='c' style='border-left-color:{kleur}'>")
            m.append(f"<p class='s' style='color:{kleur}'>{e(STATUT.get(c['statut_affiche'], c['statut_affiche']))}. "
                     f"{e(CONTROLES.get(c['id'], c['id']))} <span class='bron'>({e(c['id'])})</span></p>")
            m.append(f"<p>{e(bevinding)}</p>")
            if gevolg:
                m.append(f"<p>Gevolg: {e(gevolg)}</p>")
            if c.get("citation_communale"):
                m.append(f"<p>Tekst: {e(c['citation_communale'])}</p>")
            if c.get("source_communale"):
                m.append(f"<p class='bron'>Gemeentelijke bron: {e(c['source_communale'])}</p>")
            for sleutel, label in (("source_methode", "Methode"), ("source_donnees", "Opgegeven bron")):
                if c.get(sleutel):
                    m.append(f"<p class='bron'>{label}: {e(c[sleutel])}</p>")
            for manque in c.get("manque", []):
                label, waar = _veld(manque["champ"])
                m.append(f"<p>Aan te leveren: <strong>{e(label)}</strong>. Te vinden in: {e(waar)}.</p>")
            for tekst in rapport_flex.reserves_controle(c, "nl"):
                m.append(f"<p style='color:#9a6700'>Te bevestigen: {e(tekst)}</p>")
            m.append("</div>")

    m.append("<h2>5. Aan te leveren stukken</h2>")
    if not rapport["a_fournir"]:
        m.append("<p>Geen: alle beschikbare controles konden worden beoordeeld.</p>")
    else:
        m.append("<ol>")
        for fiche in rapport["a_fournir"]:
            label, waar = _veld(fiche["champ"])
            n = len(fiche["debloque"])
            m.append(f"<li><strong>{e(label)}</strong> opent {n} controle{'s' if n > 1 else ''}"
                     f"<br><span class='bron'>Te vinden in: {e(waar)}</span></li>")
        m.append("</ol>")

    m.append(f"<footer><p>Catalogus van regels: {e(versie['nombre_entrees'])} regels, vingerafdruk "
             f"{e(versie['empreinte'][:16])}, gegenereerd op {e(versie['genere_le'])}.</p>"
             "<p>Dit rapport is reproduceerbaar op deze versie van de catalogus. Een sindsdien gewijzigde "
             "regel verandert de uitkomst: voer dan de hervalidatie opnieuw uit.</p>"
             "<p>Er wordt geen conclusie getrokken op een ontbrekend gegeven.</p></footer></html>")
    return "\n".join(m)
