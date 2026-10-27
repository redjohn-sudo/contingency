"""Textes FR/NL de fiabilité, contrat partagé avec jeu_donnees.

L'appelant décide du code, de la gravité et du blocage. Ce catalogue ne valide
pas les mesures et ne calcule aucun seuil. Les paramètres source restent des
valeurs littérales ; les dates identifiées et la pointe numérique sont mises en
forme pour l'affichage, sans arrondi de la pointe ni réécriture du texte source.
Aucune conversion de fuseau ni inférence de chronologie n'est effectuée.

Retour en texte brut, sans HTML : le moteur du rapport doit l'échapper au
moment de l'insérer dans le document. Ne pas appliquer aux pièces du client.
Un code, une langue ou des paramètres inconnus sont une erreur de contrat.
"""
from datetime import date, datetime
import math
import re
from string import Formatter

MESSAGES_FR = {'UNITE_ABSENTE': "L'unité de la colonne « {colonne} » n'est pas documentée. Indiquez s'il s'agit de "
                  "puissance en kW, d'énergie par intervalle en kWh ou d'un index cumulé, avec la convention "
                  'source.',
 'UNITE_CONTRADICTOIRE': 'Ligne {ligne}, colonne « {colonne} » : la valeur brute « {valeur_brute} » est '
                         'interprétée comme {interpretation}, en contradiction avec {preuve}. Corrigez la '
                         'sélection ou la convention à partir de cette pièce.',
 'GRANDEUR_INDEX_DOCUMENTE': 'La colonne « {colonne} » est documentée comme un index cumulé. Elle ne peut '
                             'pas être lue comme une puissance ou une énergie par intervalle. Sélectionnez '
                             'une série compatible ou fournissez un export par intervalle.',
 'VALEUR_ATYPIQUE': 'Ligne {ligne} : « {valeur_brute} », interprétée comme {interpretation}, est à vérifier '
                    "au regard de {reference}. Une valeur inhabituelle ne prouve pas une erreur d'unité. "
                    "Vérifiez la source avant de confirmer ; aucune correction automatique n'est appliquée.",
 'HEURE_AMBIGUE': "Ligne {ligne} : l'heure locale « {valeur_brute} » correspond à plusieurs instants dans "
                  "{fuseau}. Fournissez le décalage UTC ou une convention d'ordre documentée. Les mesures "
                  'restent conservées.',
 'HEURE_INEXISTANTE': "Ligne {ligne} : l'heure locale « {valeur_brute} » n'existe pas dans {fuseau} à cette "
                      'date. Vérifiez le fuseau et la convention du fichier source.',
 'FUSEAU_CONTRADICTOIRE': 'Ligne {ligne} : le marqueur de « {valeur_brute} » contredit la convention '
                          "documentée {convention}. L'interprétation doit être justifiée et confirmée avant "
                          "le calcul ; aucun fuseau n'est remplacé en silence.",
 'HEURE_REPETEE_ORDRE_AMBIGU': "Le {jour}, l'ordre des occurrences de l'heure répétée "
                               "n'est pas établi. Les lignes restent conservées ; les calculs dépendant de "
                               'cet ordre attendent une désambiguïsation justifiée.',
 'ANOMALIE_TROU': "Entre {apres} et {avant}, {quarts} quarts d'heure attendus sont absents. Vérifiez les "
                  'lignes indiquées dans le fichier source. Les valeurs manquantes ne sont remplacées ni par '
                  'zéro ni par une interpolation.',
 'ANOMALIE_DOUBLON': "Plusieurs valeurs correspondent à l'instant {instant}. Vérifiez les lignes indiquées, "
                     "le compteur, le canal et la convention de temps ; aucune ligne n'est supprimée "
                     'automatiquement.',
 'VALEUR_INVALIDE': 'Ligne {ligne}, colonne « {colonne} » : « {valeur_brute} » ne correspond pas au format '
                    'déclaré {format_attendu}. Corrigez le fichier ou sa convention sans remplacer la valeur '
                    'par zéro.',
 'POINTS_MULTIPLES': 'La sélection contient plusieurs points de mesure : {compteurs}. Choisissez '
                     'explicitement le point à analyser ; leurs séries ne sont pas assemblées '
                     'automatiquement.',
 'CANAL_ABSENT': "Le canal demandé « {canal} » n'est pas identifié dans la sélection. Choisissez un canal "
                 "documenté, avec son sens de circulation de l'énergie.",
 'QUALITE_INCONNUE': "La qualité des mesures n'est pas documentée : {raison}. Les valeurs ne sont pas présentées "
                     "comme des mesures validées. Demandez les informations d'origine, de validation et de "
                     'réparation au fournisseur de données.',
 'QUALITE_VALEURS_NON_MESUREES': 'Intervalles : {quarts}. Valeurs estimées : {estime} ; calculées : {calcule} ; '
                               'de qualité inconnue : {inconnue}. Leur effet sur les résultats est à examiner. '
                               'Ces catégories ne prouvent ni une mesure directe ni une validation.',
 'QUALITE_POINTE_NON_MESUREE': "La valeur de pointe de {pointe_kw} kW, pour le quart d'heure se terminant le {instant}, "
                             'a pour qualité : {qualite}. '
                             'La pointe et le dimensionnement qui en dépend restent à confirmer.',
 'QUALITE_POINTE_INTERVALLE_NON_MESUREE': 'La valeur de pointe de {pointe_kw} kW, pour l’intervalle de {pas_minutes} minutes '
                                        'se terminant le {instant}, a pour qualité : {qualite}. '
                                        'La pointe et le dimensionnement qui en dépend restent à confirmer.',
 'QUALITE_ESTIMEE': 'Valeur estimée ou reconstruite, méthode déclarée : {methode}, origine déclarée : '
                    '{origine}. Son effet sur les résultats est à examiner. Un statut définitif ne prouve '
                    'pas une mesure directe.',
 'QUALITE_INVALIDE': 'Ligne {ligne} : le statut source « {statut} » signale une valeur invalide. Demandez '
                     'une donnée corrigée ou la justification du statut avant les calculs qui en dépendent.',
 'POINTE_A_CONFIRMER': "La pointe à {instant} dépend d'une valeur dont la qualité est {qualite}. Cette "
                       'pointe et le dimensionnement qui en dépend restent à confirmer, même si les autres '
                       'intervalles sont validés.',
 'PERIODE_ANNEE_INCOMPLETE': "La période {debut} à {fin} ne couvre pas toute l'année civile {annee}. Les "
                             'résultats portent sur la période disponible ; la rubrique annuelle ne peut pas '
                             'être validée à partir de cette seule couverture.',
 'PERIODE_ANNEE_FUTURE': "L'année {annee} est future par rapport à l'année de référence {annee_scan}. Elle "
                         'peut décrire un scénario, mais ne peut pas être qualifiée de mesure historique '
                         'récente.',
 'PERIODE_ANCIENNE': "L'année {annee} est en dehors de la période de référence retenue pour l'étude : "
                     '{periode_reference}. Fournissez une année admissible et justifiez sa représentativité '
                     "pour l'activité.",
 'CONFIRMATION_PERIMEE': 'Le fichier ou ses conventions ont changé depuis la confirmation. La version '
                         '{version_actuelle} doit être examinée et confirmée à nouveau avant de réutiliser '
                         'les résultats.',
 'BILAN_LIGNES': 'Lignes de données lues : {lues}. Conservées : {conservees}. Écartées par les filtres '
                 'déclarés : {filtrees}. Rejetées : {rejetees}. Les motifs et numéros de ligne sont '
                 "conservés dans le bilan d'import.",
 'INTERPRETATION_A_CONFIRMER': 'Lignes {lignes} : interprétation proposée {interpretation}, fondée sur '
                               '{preuve}. Vérifiez les instants et décalages affichés, puis confirmez cette '
                               'interprétation pour la version {version}. Le calcul attend cette '
                               'confirmation.',
 'PERIODE_ANNEE_EN_COURS': "L'année {annee} est encore en cours pour l'étude de référence {annee_scan}. "
                           'Distinguez les mesures déjà disponibles des prévisions ; elles ne constituent '
                           'pas une année civile achevée.',
 'PERIODE_NON_CIVILE': 'La période du {debut} au {fin} couvre {jours} jours mais ne correspond pas à une '
                       'année civile complète. Les résultats concernent cette période ; choisissez une année '
                       'civile complète pour la rubrique annuelle.',
 'PERIODE_PARTIELLE': 'La période du {debut} au {fin} couvre {jours} jours. Elle est partielle : un maximum '
                      'observé sur cette période ne constitue pas une pointe annuelle établie.',
 'ANOMALIE_PAS': "Ligne {ligne} : l'écart entre deux instants successifs est de {ecart_minutes} minutes. "
                 "Vérifiez le pas déclaré, l'ordre des lignes et le fuseau dans le fichier source ; aucun "
                 "intervalle n'est ajouté ni supprimé automatiquement.",
 'HEURE_REPETEE_A_CONFIRMER': "Le {jour}, les lignes {lignes_ete} proposées en heure d'été et les lignes "
                              "{lignes_hiver} proposées en heure d'hiver ont pour décalages respectifs {decalages}. "
                              "Vérifiez la convention source et l'ordre des occurrences, puis confirmez "
                              "l'interprétation {identite} du fichier {empreinte} avant le calcul. "
                              'Cette confirmation porte sur ce fichier, ses conventions et la version du lecteur. '
                              'Toute modification des conventions nécessite une nouvelle confirmation. '
                              'Le nombre de lignes ne suffit pas à établir cet ordre.',
 'HEURE_REPETEE_INTERPRETEE': "Le {jour}, l'interprétation {identite} de l'heure répétée a été confirmée pour le fichier "
                            "{empreinte}, ses conventions et la version du lecteur. Les lignes {lignes_ete} sont lues en heure d'été et les lignes "
                            "{lignes_hiver} en heure d'hiver, avec les décalages respectifs {decalages}. "
                            'Chaque ligne conserve sa mesure.',
 'GRANDEUR_INDEX_POSSIBLE': 'La série de {quarts} intervalles croît de {premier} à {dernier}. Vérifiez si elle '
                            'correspond à un index cumulé ou à une puissance moyenne par intervalle. Sa '
                            'croissance ne prouve pas une erreur. Consultez la convention source avant de '
                            "confirmer l'interprétation {identite}. Confirmation déclarée : {confirmation}. "
                            'Une autre série demande une nouvelle confirmation. Les valeurs restent inchangées.',
 'UNITE_RECOUPEE': "Recoupement de l'unité {unite} déclaré à partir de : {source}. Conservez cette pièce "
                   'et le résultat de la comparaison pour la période concernée.',
 'UNITE_NON_RECOUPEE': "L'unité {unite}, indiquée par {source}, n'a pas été recoupée avec une référence "
                       'indépendante. Vérifiez la convention et une pièce compatible avant de considérer '
                       "l'unité comme contrôlée.",
 'ANOMALIE_ORDRE': "L'ordre des lignes revient de {de} à {vers}. Vérifiez la chronologie du fichier source ; "
                   'les lignes ne sont ni réordonnées ni supprimées automatiquement.'}

MESSAGES_NL = {'UNITE_ABSENTE': 'De eenheid van kolom ‘{colonne}’ is niet gedocumenteerd. Geef aan of het gaat om vermogen '
                  'in kW, energie per interval in kWh of een cumulatieve meterstand, met de bronconventie.',
 'UNITE_CONTRADICTOIRE': 'Regel {ligne}, kolom ‘{colonne}’: de ruwe waarde ‘{valeur_brute}’ wordt '
                         'geïnterpreteerd als {interpretation}, in strijd met {preuve}. Corrigeer de '
                         'selectie of conventie op basis van dit bewijsstuk.',
 'GRANDEUR_INDEX_DOCUMENTE': 'Kolom ‘{colonne}’ is gedocumenteerd als een cumulatieve meterstand. Deze kan '
                             'niet als vermogen of energie per interval worden gelezen. Selecteer een '
                             'geschikte reeks of lever een export met intervalwaarden aan.',
 'VALEUR_ATYPIQUE': 'Regel {ligne}: ‘{valeur_brute}’, geïnterpreteerd als {interpretation}, moet worden '
                    'gecontroleerd aan de hand van {reference}. Een ongebruikelijke waarde bewijst geen fout '
                    'in de eenheid. Controleer de bron voordat u bevestigt; er wordt geen automatische '
                    'correctie toegepast.',
 'HEURE_AMBIGUE': 'Regel {ligne}: de lokale tijd ‘{valeur_brute}’ komt overeen met meerdere tijdstippen in '
                  '{fuseau}. Geef de UTC-offset op of een gedocumenteerde conventie voor de volgorde. De '
                  'meetwaarden blijven behouden.',
 'HEURE_INEXISTANTE': 'Regel {ligne}: de lokale tijd ‘{valeur_brute}’ bestaat op deze datum niet in '
                      '{fuseau}. Controleer de tijdzone en de conventie van het bronbestand.',
 'FUSEAU_CONTRADICTOIRE': 'Regel {ligne}: de tijdzonemarkering van ‘{valeur_brute}’ is in strijd met de '
                          'gedocumenteerde conventie {convention}. De interpretatie moet vóór de berekening '
                          'worden onderbouwd en bevestigd; er wordt niet stilzwijgend een andere tijdzone '
                          'toegepast.',
 'HEURE_REPETEE_ORDRE_AMBIGU': 'Op {jour} is de volgorde van de tijdstippen in het herhaalde '
                               'uur niet vastgesteld. De regels blijven behouden; berekeningen die van '
                               'deze volgorde afhangen, wachten op een onderbouwde opheldering.',
 'ANOMALIE_TROU': 'Tussen {apres} en {avant} ontbreken {quarts} verwachte kwartierwaarden. Controleer de '
                  'aangegeven regels in het bronbestand. Ontbrekende waarden worden niet vervangen door nul '
                  'of interpolatie.',
 'ANOMALIE_DOUBLON': 'Meerdere waarden komen overeen met tijdstip {instant}. Controleer de aangegeven '
                     'regels, de meter, het kanaal en de tijdconventie; er wordt geen regel automatisch '
                     'verwijderd.',
 'VALEUR_INVALIDE': 'Regel {ligne}, kolom ‘{colonne}’: ‘{valeur_brute}’ voldoet niet aan het opgegeven '
                    'formaat {format_attendu}. Corrigeer het bestand of de conventie zonder de waarde door '
                    'nul te vervangen.',
 'POINTS_MULTIPLES': 'De selectie bevat meerdere meetpunten: {compteurs}. Kies expliciet het te analyseren '
                     'meetpunt; de reeksen worden niet automatisch samengevoegd.',
 'CANAL_ABSENT': 'Het gevraagde kanaal ‘{canal}’ is niet geïdentificeerd in de selectie. Kies een '
                 'gedocumenteerd kanaal met de bijbehorende energierichting.',
 'QUALITE_INCONNUE': 'De meetkwaliteit is niet gedocumenteerd: {raison}. De waarden worden niet als '
                     'gevalideerde meetwaarden gepresenteerd. Vraag de gegevensleverancier om informatie '
                     'over herkomst, validatie en reparatie.',
 'QUALITE_VALEURS_NON_MESUREES': 'Aantal intervallen: {quarts}. Geschatte waarden: {estime}; berekende waarden: {calcule}; '
                               'waarden met onbekende kwaliteit: {inconnue}. Het effect op de resultaten '
                               'moet worden onderzocht. Deze categorieën bewijzen geen rechtstreekse meting of validatie.',
 'QUALITE_POINTE_NON_MESUREE': 'De piekwaarde van {pointe_kw} kW, voor het kwartier dat eindigt op {instant}, '
                             'heeft als kwaliteit: {qualite}. '
                             'De piek en de dimensionering die ervan afhangt, moeten nog worden bevestigd.',
 'QUALITE_POINTE_INTERVALLE_NON_MESUREE': 'De piekwaarde van {pointe_kw} kW, voor het interval van {pas_minutes} minuten '
                                        'dat eindigt op {instant}, heeft als kwaliteit: {qualite}. '
                                        'De piek en de dimensionering die ervan afhangt, moeten nog worden bevestigd.',
 'QUALITE_ESTIMEE': 'Geschatte of gereconstrueerde waarde, opgegeven methode: {methode}, opgegeven herkomst: '
                    '{origine}. Het effect op de resultaten moet worden onderzocht. Een definitieve status '
                    'bewijst niet dat de waarde rechtstreeks is gemeten.',
 'QUALITE_INVALIDE': 'Regel {ligne}: bronstatus ‘{statut}’ duidt op een ongeldige waarde. Vraag om '
                     'gecorrigeerde gegevens of een onderbouwing van de status vóór berekeningen die ervan '
                     'afhangen.',
 'POINTE_A_CONFIRMER': 'De piek op {instant} hangt af van een waarde met kwaliteit {qualite}. Deze piek en '
                       'de dimensionering die ervan afhangt, moeten nog worden bevestigd, ook als de overige '
                       'intervallen gevalideerd zijn.',
 'PERIODE_ANNEE_INCOMPLETE': 'De periode van {debut} tot {fin} dekt niet het volledige kalenderjaar {annee}. '
                             'De resultaten betreffen de beschikbare periode; de jaarrubriek kan niet op '
                             'basis van alleen deze dekking worden gevalideerd.',
 'PERIODE_ANNEE_FUTURE': 'Het jaar {annee} ligt in de toekomst ten opzichte van referentiejaar {annee_scan}. '
                         'Het kan een scenario beschrijven, maar kan niet als recente historische meting '
                         'worden aangemerkt.',
 'PERIODE_ANCIENNE': 'Het jaar {annee} valt buiten de gekozen referentieperiode voor het onderzoek: '
                     '{periode_reference}. Lever een jaar binnen deze periode aan en onderbouw de '
                     'representativiteit voor de bedrijfsactiviteiten.',
 'CONFIRMATION_PERIMEE': 'Het bestand of de conventies zijn sinds de bevestiging gewijzigd. Versie '
                         '{version_actuelle} moet opnieuw worden beoordeeld en bevestigd voordat de '
                         'resultaten worden hergebruikt.',
 'BILAN_LIGNES': 'Gelezen gegevensregels: {lues}. Behouden: {conservees}. Uitgesloten door de opgegeven '
                 'filters: {filtrees}. Afgewezen: {rejetees}. De redenen en regelnummers blijven in het '
                 'importverslag bewaard.',
 'INTERPRETATION_A_CONFIRMER': 'Regels {lignes}: voorgestelde interpretatie {interpretation}, gebaseerd op '
                               '{preuve}. Controleer de weergegeven tijdstippen en UTC-offsets en bevestig '
                               'deze interpretatie voor versie {version}. De berekening wacht op deze '
                               'bevestiging.',
 'PERIODE_ANNEE_EN_COURS': 'Het jaar {annee} loopt nog voor het onderzoek met referentiejaar {annee_scan}. '
                           'Maak onderscheid tussen de al beschikbare metingen en prognoses; ze vormen geen '
                           'afgesloten kalenderjaar.',
 'PERIODE_NON_CIVILE': 'De periode van {debut} tot {fin} beslaat {jours} dagen, maar komt niet overeen met '
                       'een volledig kalenderjaar. De resultaten betreffen deze periode; kies een volledig '
                       'kalenderjaar voor de jaarrubriek.',
 'PERIODE_PARTIELLE': 'De periode van {debut} tot {fin} beslaat {jours} dagen. De periode is onvolledig: een '
                      'waargenomen maximum in deze periode is geen vastgestelde jaarpiek.',
 'ANOMALIE_PAS': 'Regel {ligne}: het verschil tussen twee opeenvolgende tijdstippen is {ecart_minutes} '
                 'minuten. Controleer de opgegeven intervalduur, regelvolgorde en tijdzone in het '
                 'bronbestand; er wordt geen interval automatisch toegevoegd of verwijderd.',
 'HEURE_REPETEE_A_CONFIRMER': 'Op {jour} worden regels {lignes_ete} als zomertijd en regels {lignes_hiver} als '
                              'wintertijd voorgesteld, met respectievelijk de UTC-offsets {decalages}. '
                              'Controleer de bronconventie en de volgorde van de tijdstippen en bevestig '
                              'interpretatie {identite} van bestand {empreinte} vóór de berekening. '
                              'Deze bevestiging geldt voor dit bestand, de conventies en de versie van de importsoftware. '
                              'Bij gewijzigde conventies is een nieuwe bevestiging nodig. Het aantal regels alleen '
                              'volstaat niet om deze volgorde vast te stellen.',
 'HEURE_REPETEE_INTERPRETEE': 'Op {jour} is de interpretatie {identite} van het herhaalde uur bevestigd voor bestand '
                            '{empreinte}, de conventies en de versie van de importsoftware. Regels {lignes_ete} worden als zomertijd en regels {lignes_hiver} als '
                            'wintertijd gelezen, met respectievelijk de UTC-offsets {decalages}. '
                            'Elke regel behoudt zijn meetwaarde.',
 'GRANDEUR_INDEX_POSSIBLE': 'De reeks van {quarts} intervallen stijgt van {premier} naar {dernier}. Controleer '
                            'of deze cumulatieve meterstanden of gemiddeld vermogen per interval bevat. Een '
                            'stijgende reeks bewijst geen fout. Raadpleeg de bronconventie voordat u interpretatie '
                            '{identite} bevestigt. Opgegeven bevestiging: {confirmation}. '
                            'Een andere reeks vereist een nieuwe bevestiging. De waarden blijven ongewijzigd.',
 'UNITE_RECOUPEE': 'De eenheid {unite} is volgens de opgave getoetst aan: {source}. Bewaar dit bewijsstuk '
                   'en het resultaat van de vergelijking voor de betreffende periode.',
 'UNITE_NON_RECOUPEE': 'De eenheid {unite}, opgegeven door {source}, is niet getoetst aan een onafhankelijke '
                       'referentie. Controleer de conventie en een passend bewijsstuk voordat u de eenheid '
                       'als gecontroleerd beschouwt.',
 'ANOMALIE_ORDRE': 'De regelvolgorde loopt terug van {de} naar {vers}. Controleer de chronologie van het '
                   'bronbestand; de regels worden niet automatisch gesorteerd of verwijderd.'}

CODES = tuple(MESSAGES_FR)
PARAMETRES = {
    code: tuple(sorted({champ for _, champ, _, _ in Formatter().parse(texte)
                        if champ is not None}))
    for code, texte in MESSAGES_FR.items()
}
# Le producteur 2c6a7d9 n'émet que les catégories présentes : une clé omise vaut zéro.
PARAMETRES_OPTIONNELS = {
    'QUALITE_VALEURS_NON_MESUREES': frozenset({'estime', 'calcule', 'inconnue'}),
}
CHAMPS_DATES = frozenset({'debut', 'fin', 'instant', 'jour', 'apres', 'avant', 'de', 'vers'})
CHAMPS_LISTES = frozenset({'lignes', 'lignes_ete', 'lignes_hiver', 'decalages', 'compteurs'})
CODES_POINTE = frozenset({'QUALITE_POINTE_NON_MESUREE', 'QUALITE_POINTE_INTERVALLE_NON_MESUREE'})


def _date_affichee(valeur: str, langue: str) -> str:
    """Date ISO en FR/NL, avec son décalage conservé et sans conversion de zone."""
    if not isinstance(valeur, str):
        raise ValueError('Date ISO attendue dans un paramètre de message.')
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', valeur):
            moment = date.fromisoformat(valeur)
            return moment.strftime('%d/%m/%Y' if langue == 'fr' else '%d-%m-%Y')
        if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', valeur):
            raise ValueError('Horodatage ISO attendu.')
        moment = datetime.fromisoformat(valeur.replace('Z', '+00:00'))
    except ValueError as erreur:
        raise ValueError('Date ISO invalide dans un paramètre de message.') from erreur
    jour = moment.strftime('%d/%m/%Y' if langue == 'fr' else '%d-%m-%Y')
    # L'affichage conserve les fractions source, même au-delà des microsecondes.
    # datetime sert à vérifier la forme, pas à réécrire la précision du relevé.
    heure = valeur[11:].replace('Z', '+00:00')
    if moment.utcoffset() is None:
        suffixe = ' (fuseau non indiqué)' if langue == 'fr' else ' (tijdzone niet opgegeven)'
    else:
        # Garder le décalage source, y compris ses secondes éventuelles.
        position = max(heure.find('+'), heure.find('-'))
        suffixe = ' UTC' + heure[position:]
        heure = heure[:position]
    return jour + (' à ' if langue == 'fr' else ' om ') + heure + suffixe


def message_fiabilite(code: str, langue: str = 'fr', **parametres) -> str:
    """Rend un constat sans changer sa gravité, les données ou leur version.

    Paramètres : texte, entier ou nombre fini. Les champs CHAMPS_LISTES acceptent
    aussi des listes/tuples non vides de textes ou d'entiers, sans tri ni filtre.
    Les dates des champs CHAMPS_DATES
    sont des chaînes ISO (date ou horodatage avec T). Une date sans décalage
    conserve cette absence, visible à l'écran. Les autres chaînes ne sont ni
    traduites, ni réinterprétées, ni échappées pour HTML. Exceptions ciblées : None
    signifie absence de confirmation pour GRANDEUR_INDEX_POSSIBLE ; les classes
    des CODES_POINTE ont des libellés traduits et leurs pointes numériques utilisent
    la virgule décimale. Leur instant désigne la fin de l'intervalle : un quart
    d'heure pour QUALITE_POINTE_NON_MESUREE, le pas déclaré dans pas_minutes pour
    QUALITE_POINTE_INTERVALLE_NON_MESUREE. Aucun pas n'est déduit par le catalogue.
    Les comptes optionnels
    de QUALITE_VALEURS_NON_MESUREES valent zéro s'ils sont omis par le producteur,
    mais celui-ci doit fournir au moins une catégorie et le nombre de quarts.
    """
    if not isinstance(code, str) or code not in MESSAGES_FR:
        raise ValueError('Code de fiabilité inconnu.')
    if langue not in ('fr', 'nl'):
        raise ValueError('Langue de fiabilité non prise en charge : fr ou nl attendue.')
    autorises = set(PARAMETRES[code])
    optionnels = PARAMETRES_OPTIONNELS.get(code, frozenset())
    requis = autorises - optionnels
    manquants, inattendus = requis - parametres.keys(), parametres.keys() - autorises
    if manquants or inattendus:
        raise ValueError('Paramètres de message incorrects : manquants = '
                         + ', '.join(sorted(manquants)) + ' ; inattendus = '
                         + ', '.join(sorted(inattendus)) + '.')
    if optionnels:
        if not optionnels.intersection(parametres):
            raise ValueError('Au moins un compte de qualité doit être fourni.')
        parametres = {nom: 0 for nom in optionnels} | parametres
    affiches = {}
    for nom, valeur in parametres.items():
        if code == 'GRANDEUR_INDEX_POSSIBLE' and nom == 'confirmation':
            if valeur is None:
                valeur = 'non fournie' if langue == 'fr' else 'niet verstrekt'
        if code in CODES_POINTE and nom == 'qualite' and isinstance(valeur, str):
            libelles = {'estime': ('estimée', 'geschat'), 'calcule': ('calculée', 'berekend'),
                        'inconnue': ('inconnue', 'onbekend'), 'mesure': ('mesurée', 'gemeten')}
            if valeur in libelles:
                valeur = libelles[valeur][0 if langue == 'fr' else 1]
        if nom in CHAMPS_LISTES and isinstance(valeur, (list, tuple)):
            if not valeur or any(type(element) not in (str, int) for element in valeur):
                raise ValueError('Liste de message non affichable : ' + nom + '.')
            valeur = ', '.join(str(element) for element in valeur)
        if type(valeur) not in (str, int, float) or isinstance(valeur, float) and not math.isfinite(valeur):
            raise ValueError('Paramètre de message non affichable : ' + nom + '.')
        if code in CODES_POINTE and nom == 'pointe_kw' and type(valeur) is float:
            valeur = str(int(valeur)) if valeur.is_integer() else str(valeur).replace('.', ',')
        affiches[nom] = _date_affichee(valeur, langue) if nom in CHAMPS_DATES else valeur
    catalogue = MESSAGES_FR if langue == 'fr' else MESSAGES_NL
    return catalogue[code].format(**affiches)
