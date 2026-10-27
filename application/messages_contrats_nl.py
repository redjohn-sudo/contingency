"""Messages du moteur destinés au rapport NL, relus après brouillon local.

Ne jamais appliquer ce catalogue aux libellés, sources ou pièces du client.
Les codes du fichier JSON restent stables et sont affichés à côté du message.
"""
import re

MESSAGES = {
    'Contrat actuel : confirmer un droit entièrement fixe sans CBC actif ; aucune référence financière calculée sans cette nature.': 'Huidig contract: bevestig een volledig vast transportrecht zonder actieve CBC. Zonder dit gegeven worden geen financiële referentiekosten berekend.',
    'Contrat actuel non fixe ou avec CBC : référence non prise en charge ; ses limites et sa rémunération ne peuvent pas être ignorées.': 'Een bestaand niet-vast contract of contract met CBC wordt niet als referentie ondersteund. De bijbehorende grenzen en vergoeding mogen niet worden genegeerd.',
    'Les responsabilités, pénalités supplémentaires et le risque de déconnexion ne sont pas valorisés.': 'Aansprakelijkheid, aanvullende boetes en het risico op afsluiting zijn niet in geld uitgedrukt.',
    'Moindre coût annuel de référence HT sur le profil inchangé, aux tarifs fournis. Aucun prorata de première année, aucune prévision de revenu ou de besoins futurs.': 'Vergelijking van jaarlijkse referentiekosten exclusief btw, op basis van het ongewijzigde profiel en de opgegeven tarieven. Geen berekening naar rato voor het eerste jaar en geen voorspelling van inkomsten of toekomstige behoeften.',
    'Sources et validations humaines déclarées ; le logiciel n’authentifie pas les pièces ni l’accord du gestionnaire.': 'Bronnen en menselijke controles zijn door de gebruiker opgegeven. De software verifieert de echtheid van documenten of de instemming van de netbeheerder niet.',
    'Un profil individuel mesuré est requis pour désigner un gagnant.': 'Een gemeten profiel van één aansluiting is vereist om de financieel beste optie vast te stellen.',
    'Relier la preuve de provenance à l’empreinte du profil analysé.': 'Koppel het bewijs van herkomst aan de hash van het geanalyseerde profiel.',
    'Gestionnaire non couvert : aucune conclusion dominante.': 'Deze netbeheerder valt buiten deze vergelijking. Er wordt geen financieel beste optie vastgesteld.',
    'La capacité demandée dépasse la puissance physique du raccordement.': 'Het aangevraagde vermogen overschrijdt de fysieke capaciteit van de aansluiting.',
    'Baisse du droit ferme et date acceptées par le gestionnaire à confirmer.': 'Bevestig dat de netbeheerder de verlaging van het vaste transportrecht en de ingangsdatum heeft aanvaard.',
    'Date d’effet confirmée manquante.': 'Een bevestigde ingangsdatum ontbreekt.',
    'Cette offre ne prend pas effet à la date de comparaison.': 'Dit aanbod is op de vergelijkingsdatum nog niet ingegaan.',
    'Date d’offre antérieure à la borne réglementaire calculée : vérifier l’exception et les pièces.': 'De ingangsdatum ligt vóór de berekende wettelijke ondergrens. Controleer de uitzondering en de bewijsstukken.',
    'L’offre n’est plus valable à la date de comparaison.': 'Het aanbod is op de vergelijkingsdatum niet meer geldig.',
    'Le bloc public quotidien 00:00 à 06:00 facture 25 % du terme de capacité ; vérifier le coefficient fourni.': 'Voor het gepubliceerde dagelijkse blok van 00:00 tot 06:00 wordt 25 % van het kW-contracttarief in rekening gebracht. Controleer de opgegeven factor.',
    'Horaire distinct de la phase publique 00:00 à 06:00 : offre particulière et barème à confirmer.': 'De tijden wijken af van het gepubliceerde blok van 00:00 tot 06:00. Bevestig het afzonderlijke aanbod en het tarief.',
    'Allocations futures et continuité du transport non garanties par la relecture historique.': 'De historische berekening garandeert geen toekomstige toewijzingen en geen continuïteit van het transport.',
    'Le profil inchangé dépasse les limites : adaptation de process et coûts non démontrés.': 'Het ongewijzigde profiel overschrijdt de grenzen. De vereiste procesaanpassing en de kosten daarvan zijn niet aangetoond.',
    'Catégorie Blokstroom : justifier le classement sur GTV fixe plus totalité du GTV variable, sans coefficient de 25 %.': 'Blokstroomcategorie: onderbouw de indeling op basis van het vaste GTV plus het volledige variabele GTV, zonder de factor van 25 %.',
    'Catégorie Blokstroom : le classement individuel doit correspondre au barème utilisé.': 'Blokstroomcategorie: de indeling van deze aansluiting moet overeenkomen met de gebruikte tarieftabel.',
    'Annexe 1 CBC : formule, périodes et règle de défaut à confirmer ; rémunération conditionnelle seulement.': 'CBC-bijlage 1: bevestig de formule, de perioden en de gevolgen van niet-nakoming. De berekende vergoeding is voorwaardelijk.',
    'Exhaustivité des coûts réseau, process, installation, financement, maintenance et CSP à confirmer.': 'Bevestig dat alle kosten voor het net, bedrijfsprocessen, installatie, financiering, onderhoud en CSP zijn opgenomen.',
    'Tarif : lettre de catégorie nationale a à h à confirmer, indépendamment du nom commercial.': 'Tarief: bevestig de landelijke categorieletter a tot en met h, los van de commerciële naam.',
    'Tarif : assiette des pointes absente ou non prise en charge ; maxima hebdomadaires non calculés.': 'Tarief: de grondslag voor pieken ontbreekt of wordt niet ondersteund. Weekmaxima worden niet berekend.',
    'Catégorie EHS/HS : le maximum mensuel pondéré est requis, une pointe brute ne suffit pas.': 'Categorie EHS/HS: het gewogen maandmaximum is vereist. Een ongewogen piek volstaat niet.',
    'Pondération mensuelle : réservée aux catégories EHS/HS a et b dans ce module.': 'Gewogen maandmaxima worden in deze module uitsluitend voor de categorieën EHS/HS a en b berekend.',
    'Catégorie EHS/HS, TS ou HS+TS/MS à courte utilisation : régime hebdomadaire à vérifier et non calculé ici.': 'Categorie EHS/HS, TS of HS+TS/MS met korte benuttingsduur: controleer de regeling met weekmaxima. Deze wordt hier niet berekend.',
    'Pondération : confirmer que la grille de l’annexe 5 publiée en février 2026 s’applique au dossier.': 'Weging: bevestig dat de tabel uit bijlage 5, gepubliceerd in februari 2026, op dit dossier van toepassing is.',
    'Pondération : grille publiée pour 2026 seulement ; vérifier la version applicable aux autres années tarifaires.': 'Weging: de tabel is uitsluitend voor 2026 gepubliceerd. Controleer de toepasselijke versie voor andere tariefjaren.',
    'Pondération : cette grille est prise en charge pour le réseau de transmission TenneT seulement ; justifier le régime des autres raccordements.': 'Weging: deze tabel wordt uitsluitend voor het transmissienet van TenneT ondersteund. Onderbouw de regeling voor andere aansluitingen.',
    'Pondération : confirmer le régime terrestre ou le régime en mer de l’article 3.8(2)f.': 'Weging: bevestig de regeling voor het landnet of de regeling op zee volgens artikel 3.8(2)f.',
    'Pondération en mer : le régime de l’article 3.8(2)f exige la catégorie a.': 'Weging op zee: de regeling van artikel 3.8(2)f vereist categorie a.',
    'Pondération : confirmer que chaque heure tarifaire correspond au début local du quart en Europe/Amsterdam.': 'Weging: bevestig dat het tariefuur wordt bepaald door het lokale begin van het kwartier in Europe/Amsterdam.',
    'Pondération : confirmer la liste exhaustive des jours fériés tarifaires de l’année mesurée.': 'Weging: bevestig de volledige lijst van feestdagen voor de tarieven in het meetjaar.',
    'Cette catégorie comporte une pointe tarifaire ; elle ne peut pas être omise.': 'Deze categorie bevat een tarief voor piekvermogen. Dit mag niet worden weggelaten.',
    'Catégorie LS : vérifier l’absence de terme de pointe dans le barème applicable.': 'Categorie LS: controleer dat de toepasselijke tarieftabel geen tarief voor piekvermogen bevat.',
    'Absence de terme de pointe : le tarif de pointe doit être explicitement nul.': 'Zonder piekcomponent moet het piektarief expliciet nul zijn.',
    'Tarievencode 3.14 : pas de terme kW contract sur la partie variable ; coefficient nul à confirmer.': 'Tarievencode 3.14: geen kW-contractcomponent voor het variabele deel. Bevestig een factor nul.',
    'Baisser le GTV peut réduire le droit ferme disponible. Le rétablissement ultérieur peut être refusé en congestion. NorthC, CBb du 23 juin 2026 : la dernière valeur déclarée compte. Une économie de tarif ne conserve pas à elle seule la capacité abandonnée.': 'Verlaging van het GTV kan het beschikbare vaste transportrecht verkleinen. Herstel kan later wegens netcongestie worden geweigerd. NorthC, CBb 23 juni 2026: de laatst opgegeven waarde is bepalend. Een lager tarief geeft geen recht op herstel van de prijsgegeven transportcapaciteit.',
    'Date effective à confirmer par le gestionnaire.': 'De netbeheerder moet de daadwerkelijke ingangsdatum bevestigen.',
    'Cette publication entre en vigueur le 21 février 2026 ; rechercher les règles applicables à la date antérieure.': 'Deze publicatie treedt op 21 februari 2026 in werking. Controleer welke regels op een eerdere datum golden.',
    'Motifs raisonnables de changement acceptés par le gestionnaire.': 'Bevestig dat de netbeheerder de redelijke gronden voor de wijziging heeft aanvaard.',
    'Confirmer qu’aucun changement sur demande n’a déjà été effectué cette année.': 'Bevestig dat dit jaar nog geen wijziging op verzoek heeft plaatsgevonden.',
    'Article 7.25 : au maximum une modification sur demande par an, sur motifs raisonnables.': 'Artikel 7.25: maximaal één wijziging op verzoek per jaar, op redelijke gronden.',
    'Date de dernière hausse ou absence de hausse depuis douze mois confirmée.': 'Bevestig de datum van de laatste verhoging of dat er gedurende twaalf maanden geen verhoging is geweest.',
    'Article 7.26 : une nouvelle pointe dans les douze mois suivant la baisse peut entraîner une correction rétroactive.': 'Artikel 7.26: een nieuwe piek binnen twaalf maanden na de verlaging kan tot een correctie met terugwerkende kracht leiden.',
    'Borne nationale non établie pour cette catégorie : a à d = EHS, HS, TS, HS+TS/MS ; e/f = MS et MS/LS. Pour LS (g/h), vérifier les conditions du gestionnaire.': 'Voor deze categorie is geen landelijke datumgrens vastgesteld: a tot en met d = EHS, HS, TS, HS+TS/MS; e/f = MS en MS/LS. Controleer voor LS (g/h) de voorwaarden van de netbeheerder.',
    'Capacité réseau disponible et accord du gestionnaire requis, aucune hausse automatique en congestion.': 'Beschikbare netcapaciteit en instemming van de netbeheerder zijn vereist. Bij netcongestie volgt geen automatische verhoging.',
    'La consolidation au 27 septembre n’a pas été accessible ; vérifier les modifications applicables au dossier.': 'De geconsolideerde tekst op 27 september was niet toegankelijk. Controleer welke wijzigingen voor dit dossier gelden.',
    'Offre et règles du gestionnaire non couvert par cette veille.': 'Het aanbod en de regels van deze netbeheerder vallen buiten het bronnenonderzoek.',
    'Tension de raccordement en kV, relevée sur l’ATO.': 'Vermeld de aansluitspanning in kV uit de ATO.',
    'Nature du réseau de raccordement : distribution ou transmission.': 'Vermeld het type aangesloten net: distributie of transmissie.',
    'Statut de grande connexion à confirmer.': 'Bevestig dat dit een grootverbruikaansluiting is.',
    'Ce comparateur traite les grandes connexions seulement.': 'Deze vergelijking behandelt uitsluitend grootverbruikaansluitingen.',
    'Gestionnaire TenneT incompatible avec un réseau déclaré de distribution.': 'TenneT als netbeheerder is niet verenigbaar met een opgegeven distributienet.',
    'Gestionnaire régional incompatible avec un réseau déclaré de transmission.': 'Een regionale netbeheerder is niet verenigbaar met een opgegeven transmissienet.',
    'Tijdsduur : réservé au réseau de transmission, article 7.6.': 'Tijdsduurgebonden transportrecht: uitsluitend voor het transmissienet, artikel 7.6.',
    'Tijdsblok : grandes connexions de distribution, article 7.7.': 'Tijdsblokgebonden transportrecht: grootverbruikaansluitingen op het distributienet, artikel 7.7.',
    'Offre publique actuelle : consommation entre 00:00 et 06:00, capacité locale et amont à confirmer.': 'Huidig gepubliceerd aanbod: afname tussen 00:00 en 06:00. Bevestig de capaciteit op het lokale en bovenliggende net.',
    'Liander n’autorise pas l’échange du GTV fixe contre Blokstroom sur la page actuelle.': 'Volgens de huidige pagina staat Liander geen omruiling van vast GTV voor Blokstroom toe.',
    'Phase Liander publiée : Friesland et Noordoostpolder ; disponibilité ailleurs non établie.': 'De gepubliceerde fase van Liander omvat Friesland en Noordoostpolder. Beschikbaarheid elders is niet vastgesteld.',
    'Phase Stedin publiée : Zeeland ; disponibilité ailleurs non établie.': 'De gepubliceerde fase van Stedin omvat Zeeland. Beschikbaarheid elders is niet vastgesteld.',
    'Possibilité de remplacer le GTV fixe chez Stedin à vérifier dans l’offre.': 'Controleer in het aanbod of vast GTV bij Stedin kan worden vervangen.',
    'Enexis permet l’échange total ou partiel du GTV fixe, sur demande acceptée.': 'Enexis staat gehele of gedeeltelijke omruiling van vast GTV toe na aanvaarding van het verzoek.',
    'Le prix de 25 % porte sur le terme kW contract du bloc de six heures, pas sur toute la facture.': 'Het tarief van 25 % geldt voor de kW-contractcomponent van het blok van zes uur. De overige factuuronderdelen vallen niet onder deze korting.',
    'Volledig variabel : grande connexion en zone de congestion, article 7.5.': 'Volledig variabel transportrecht: een grootverbruikaansluiting in een congestiegebied, artikel 7.5.',
    'Zone de congestion pour le sens concerné à confirmer.': 'Bevestig de congestiestatus voor de betreffende transportrichting.',
    'Reststroom non disponible comme offre générale sur la page actuelle : offre individuelle indispensable.': 'Reststroom is op de huidige pagina niet beschikbaar als algemeen aanbod. Een individueel aanbod is noodzakelijk.',
    'Aucune capacité garantie ; un historique des allocations ne garantit pas celles de demain.': 'Er is geen gegarandeerde capaciteit. Historische toewijzingen garanderen toekomstige toewijzingen niet.',
    '85 % des heures de l’année selon le contrat et les restrictions du gestionnaire ; le client ne choisit pas ses meilleurs quarts.': '85 % van de uren van het jaar, volgens het contract en de beperkingen van de netbeheerder. De klant kiest niet zelf de gunstigste kwartieren.',
    'CBC V3 : montant, périodes et date figurent dans l’annexe 1, qui prime. Un défaut peut annuler la rémunération du jour entier.': 'CBC V3: bedrag, perioden en datum staan in bijlage 1, die voorrang heeft. Niet-nakoming kan de vergoeding voor de hele dag doen vervallen.',
    'Admissibilité individuelle, tension, catégorie et date à confirmer dans l’offre du gestionnaire.': 'Bevestig geschiktheid van de aansluiting, spanning, categorie en ingangsdatum in het aanbod van de netbeheerder.',
}

# Seuls ces gabarits émis par le moteur contiennent un champ variable.
GABARITS = (
    (r'(.+) : valeur et pièce manquantes\.', '{}: waarde en bewijsstuk ontbreken.'),
    (r'(.+) : valeur, source et validation humaine à confirmer\.', '{}: bevestig de waarde, de bron en de menselijke controle.'),
    (r'Provenance : (.+) à confirmer\.', 'Herkomst: bevestig {}.'),
    (r'Offre : concordance de (.+) à vérifier\.', 'Aanbod: controleer of {} overeenkomt.'),
    (r'Offre : (.+) à confirmer\.', 'Aanbod: bevestig {}.'),
)


def traduire_message(message, langue):
    if langue == 'fr':
        return message
    if message in MESSAGES:
        return MESSAGES[message]
    for motif, gabarit in GABARITS:
        correspondance = re.fullmatch(motif, message)
        if correspondance:
            return gabarit.format(*correspondance.groups())
    raise ValueError('Traduction néerlandaise absente pour un message du comparateur : ' + message)
