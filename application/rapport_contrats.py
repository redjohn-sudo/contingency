"""Rapport autonome FR/NL. Textes du client conservés et échappés."""
from html import escape
from messages_contrats_nl import traduire_message


def verifier_langue(langue):
    if langue not in ('fr', 'nl'):
        raise ValueError('Langue du rapport attendue : fr ou nl.')
    return langue


def montant(valeur, unite='€', langue='fr'):
    if valeur is None:
        return 'À renseigner' if langue == 'fr' else 'Nog in te vullen'
    texte = f'{valeur:,.2f}'.replace(',', ' ').replace('.', ',')
    if langue == 'nl':
        texte = texte.replace(' ', '.')
    return texte + ' ' + unite


def liste(lignes):
    return '<ul>' + ''.join('<li>' + escape(str(ligne)) + '</li>' for ligne in lignes) + '</ul>' if lignes else ''


def rendre_comparaison(resultat, langue='fr'):
    verifier_langue(langue)
    def t(fr, nl):
        return fr if langue == 'fr' else nl
    def m(valeur, unite='€'):
        return montant(valeur, unite, langue)
    def message(texte):
        return traduire_message(texte, langue)
    def raisons(textes):
        return liste([message(texte) for texte in textes])
    def p(texte):
        return '<p>' + escape(texte) + '</p>'
    def libelle(option):
        return t('Contrat actuel', 'Huidig contract') if option['id'] == 'actuel' else str(option['libelle'])

    profil, options = resultat['profil'], resultat['options']
    dominante = next((o for o in options if o['id'] == resultat['dominante']), None)
    titre = (t('Coût de référence le plus faible : ', 'Laagste referentiekosten: ') + libelle(dominante)) if dominante else t('Aucun gagnant financier établi', 'Geen financieel beste optie vastgesteld')
    statuts = {
        'comparable': t('Pièces déclarées vérifiées', 'Documenten volgens opgave gecontroleerd'),
        'incomplet': t('Dossier incomplet', 'Onvolledig dossier'),
        'reference_depassee': t('Référence actuelle dépassée, à régulariser', 'Huidige referentie overschreden, afstemming vereist'),
        'incompatible': t('Incompatible avec ce profil ou cette offre', 'Niet verenigbaar met dit profiel of aanbod'),
    }
    lignes, details = [], []
    for numero, option in enumerate(options, 1):
        statut = statuts[option['statut']]
        cout = m(option['cout_annuel_reference_eur'])
        if option['statut'] != 'comparable' and option['cout_annuel_reference_eur'] is not None:
            cout += t(' (conditionnel)', ' (voorwaardelijk)')
        date_effet = option['date_effet_confirmee'] or (t('Contrat en place', 'Bestaand contract') if option['id'] == 'actuel' else t('À confirmer', 'Te bevestigen'))
        lignes.append(f'<tr><th scope="row"><a href="#option-{numero}">{escape(libelle(option))}</a></th>' + ''.join('<td>' + escape(valeur) + '</td>' for valeur in (cout, m(option['ecart_reference_eur']), date_effet, statut)) + '</tr>')
        corps = p(statut + '.')
        corps += p(t('GTV fixe : {fixe}. Capacité variable : {variable}. Catégorie : {categorie}.', 'Vast GTV: {fixe}. Variabel vermogen: {variable}. Categorie: {categorie}.').format(fixe=m(option['gtv_fixe_kw'], 'kW'), variable=m(option['gtv_variable_kw'], 'kW'), categorie=option['categorie'] or t('À confirmer', 'Te bevestigen')))
        transport = option['cout_transport']
        if transport:
            pointes = option.get('pointes_ponderees')
            termes = [('capacite_eur', t('Capacité contractuelle', 'Gecontracteerd vermogen')),
                      ('pointes_eur', t('Pointes mensuelles pondérées', 'Gewogen maandmaxima') if pointes else t('Pointes mensuelles', 'Maandmaxima')),
                      ('energie_eur', t('Énergie transportée', 'Getransporteerde energie')),
                      ('fixe_transport_eur', t('Fixe transport', 'Vastrecht transport')),
                      ('autres_reseau_eur', t('Autres coûts réseau', 'Overige netkosten'))]
            corps += '<dl>' + ''.join('<div><dt>' + escape(nom) + '</dt><dd>' + escape(m(transport[cle])) + '</dd></div>' for cle, nom in termes) + '</dl>'
            corps += p(t('Coûts complémentaires annuels : ', 'Aanvullende jaarlijkse kosten: ') + m(option['couts_complementaires_eur_an']) + '.')
            if pointes:
                corps += '<details><summary>' + t('Quarts qui déterminent les maxima pondérés', 'Kwartieren die de gewogen maxima bepalen') + '</summary>'
                corps += p(t('Chaque quart est multiplié par son facteur avant de chercher le maximum mensuel. Cette pondération tarifaire ne réduit pas la puissance réelle ni le GTV nécessaire.', 'Elk kwartier wordt met zijn factor vermenigvuldigd voordat het maandmaximum wordt bepaald. Deze tariefweging verlaagt het werkelijke vermogen of het benodigde GTV niet.'))
                corps += p(t('Calendrier de l’année mesurée : ', 'Kalender van het meetjaar: ') + str(pointes['annee_calendrier']) + '. ' + t('Grille : Tarievencode 2026, annexe 5.', 'Tabel: Tarievencode 2026, bijlage 5.'))
                entetes_pointes = [t('Mois', 'Maand'), t('Début du quart local', 'Lokaal begin kwartier'), t('Puissance brute', 'Ongewogen vermogen'), t('Facteur', 'Factor'), t('Maximum pondéré', 'Gewogen maximum')]
                corps += '<div class="tableau" tabindex="0" aria-label="' + t('Détail des maxima pondérés, défilement horizontal', 'Details van gewogen maxima, horizontaal scrollbaar') + '"><table><thead><tr>' + ''.join('<th>' + e + '</th>' for e in entetes_pointes) + '</tr></thead><tbody>'
                for mois, maximum in sorted(pointes['mensuel'].items(), key=lambda paire: int(paire[0])):
                    cellules = [mois, maximum['debut_local'], m(maximum['puissance_brute_kw'], 'kW'), m(maximum['facteur'], '').strip(), m(maximum['pointe_ponderee_kw'], 'kW')]
                    corps += '<tr>' + ''.join('<td>' + escape(cellule) + '</td>' for cellule in cellules) + '</tr>'
                corps += '</tbody></table></div></details>'
        defauts = option['depassements']
        if defauts:
            corps += p(t('{quarts} quarts au-dessus des limites, {jours} jours concernés. Écart maximal : {ecart}.', '{quarts} kwartieren boven de grenzen, op {jours} dagen. Grootste overschrijding: {ecart}.').format(quarts=defauts['quarts'], jours=len(defauts['jours']), ecart=m(defauts['pointe_ecart_kw'], 'kW')))
            corps += liste([d['debut_local'] + ' : ' + m(d['puissance_kw'], 'kW') + t(', limite ', ', grens ') + m(d['plafond_kw'], 'kW') for d in defauts['premiers']])
        if option.get('reference_depassee'):
            corps += p(t('Le contrat actuel sert de référence. Son dépassement n’est pas une autorisation de consommer davantage. Coût de dépassement ou correction de facture : ', 'Het huidige contract dient als referentie. Een overschrijding geeft geen toestemming om meer af te nemen. Kosten van overschrijding of factuurcorrectie: ') + m(option['cout_depassement_eur_an']) + '.')
            corps += p(t('Conserver ce contrat dépassé n’est pas une option recommandée. Un coût inconnu empêche de calculer l’écart financier.', 'Voortzetting van het overschreden contract wordt niet aanbevolen. Bij onbekende kosten kan het financiële verschil niet worden berekend.'))
        if option.get('classement_tarifaire'):
            corps += p(t('Puissance totale prise en compte pour la catégorie : {capacite}, avant toute réduction du terme facturé.', 'Totaal vermogen voor de categorie-indeling: {capacite}, vóór toepassing van korting op de gefactureerde component.').format(capacite=m(option['classement_tarifaire']['puissance_totale_kw'], 'kW')))
        if option['remuneration_cbc']:
            cbc = option['remuneration_cbc']
            corps += p(t('Rémunération CBC brute : {brut}. Perdue sur les jours en défaut : {perdu}. Résiduelle dans ce calcul : {residuel}.', 'Bruto CBC-vergoeding: {brut}. Vervallen op dagen met niet-nakoming: {perdu}. Resterend in deze berekening: {residuel}.').format(brut=m(cbc['brute_eur']), perdu=m(cbc['perdue_eur']), residuel=m(cbc['residuelle_eur'])))
            corps += p(message(cbc['limite']))
            if option['depassements']['quarts']:
                corps += p(t('La perte de rémunération chiffrée ne rend pas les dépassements conformes. Cette version exclut le CBC tant que le profil inchangé viole ses limites.', 'Berekening van de vervallen vergoeding maakt overschrijdingen niet contractueel toegestaan. Deze versie sluit het CBC uit zolang het ongewijzigde profiel de grenzen overschrijdt.'))
        borne = option.get('borne_date_gtv')
        if borne:
            corps += p(t('Borne réglementaire calculée : {borne}. Ce n’est pas une date d’acceptation.', 'Berekende wettelijke datumgrens: {borne}. Dit is geen bevestigde ingangsdatum.').format(borne=borne['borne_reglementaire'] or t('Non déterminée', 'Niet vastgesteld')))
            corps += raisons(borne['manquants'] + borne['conditions']) + p(message(borne['limite_source']))
        for cle, fr, nl in [('refus', 'Ce qui empêche cette option', 'Wat deze optie uitsluit'), ('manquants', 'Pièces et paramètres à compléter', 'Aan te vullen documenten en gegevens')]:
            if option[cle]:
                corps += '<h3>' + t(fr, nl) + '</h3>' + raisons(option[cle])
        corps += '<details><summary>' + t('Offre publique et sources déclarées', 'Gepubliceerd aanbod en opgegeven bronnen') + '</summary>'
        corps += raisons(option['filtre_public']['remarques'])
        validations = {'verifie': t('Vérification déclarée', 'Controle volgens opgave'), 'hypothese': t('Hypothèse', 'Aanname'), 'a_verifier': t('À vérifier', 'Te controleren')}
        preuves = []
        for cle, trace in option['traces'].items():
            etat = validations.get(trace.get('statut'), t('Non vérifié', 'Niet gecontroleerd'))
            preuves.append(cle + ' : ' + str(trace.get('source') or t('Source absente', 'Bron ontbreekt')) + ' ; ' + etat + ' ; ' + str(trace.get('verifie_par') or t('Lecteur non renseigné', 'Controleur niet vermeld')) + ' ; ' + str(trace.get('date_verification') or t('Date non renseignée', 'Datum niet vermeld')))
        corps += liste(preuves) + '</details>'
        details.append(f'<section id="option-{numero}"><h2>{escape(libelle(option))}</h2>{corps}</section>')
    entetes = [t('Option', 'Optie'), t('Coût annuel de référence HT', 'Jaarlijkse referentiekosten excl. btw'), t('Écart au contrat actuel', 'Verschil met huidig contract'), t('Date', 'Datum'), t('État', 'Status')]
    tableau = ('<div class="tableau" tabindex="0" aria-label="' + t('Comparaison des options, défilement horizontal', 'Vergelijking van opties, horizontaal scrollbaar') + '"><table><thead><tr>' + ''.join('<th>' + e + '</th>' for e in entetes) + '</tr></thead><tbody>' + ''.join(lignes) + '</tbody></table></div>') if lignes else ''
    sources = ''.join('<li><a href="' + escape(url, quote=True) + '">' + escape(nom) + '</a></li>' for nom, url in resultat['sources'].items())
    provenance = resultat.get('traces', {}).get('provenance', {})
    description_source = str(provenance.get('source') or t('Source de mesure non renseignée', 'Meetbron niet opgegeven'))
    corps = '<header>contingency. / ' + t('Comparaison contractuelle', 'Contractvergelijking') + '</header><h1>' + escape(titre) + '</h1>'
    corps += p(message(resultat['portee']) if resultat.get('portee') else t('Compléter les pièces du raccordement pour comparer les contrats.', 'Vul de documenten van de aansluiting aan om contracten te vergelijken.'))
    corps += p(t('Année mesurée : {annee}. {quarts} quarts continus, Europe/Amsterdam. Pointe : {pointe}. Énergie : {energie}.', 'Meetjaar: {annee}. {quarts} aaneengesloten kwartieren, Europe/Amsterdam. Piek: {pointe}. Energie: {energie}.').format(annee=profil['annee_mesuree'], quarts=profil['quarts'], pointe=m(profil['pointe_kw'], 'kW'), energie=m(profil['energie_kwh'], 'kWh')))
    corps += p(t('Source déclarée du profil : ', 'Opgegeven bron van het profiel: ') + description_source + '.')
    corps += p(t('Année tarifaire : {annee}. Date de comparaison : {date}.', 'Tariefjaar: {annee}. Vergelijkingsdatum: {date}.').format(annee=resultat.get('annee_tarifaire', t('À renseigner', 'Nog in te vullen')), date=resultat.get('date_comparaison', t('À renseigner', 'Nog in te vullen'))))
    corps += p(t('Une courbe passée ne garantit pas les besoins futurs. Aucun quart n’est effacé ou diminué pour rendre une option réalisable.', 'Een historisch profiel garandeert de toekomstige behoefte niet. Er wordt geen kwartier verwijderd of verlaagd om een optie haalbaar te maken.'))
    corps += raisons(resultat['manquants']) + tableau + p(t('Un écart positif correspond à un coût inférieur au contrat actuel, dans ce calcul de référence.', 'Een positief verschil betekent lagere kosten dan het huidige contract in deze referentieberekening.'))
    corps += '<p class="risque">' + escape(message(resultat['risque_northc'])) + '</p>' + ''.join(details)
    corps += '<section><h2>' + t('Traçabilité', 'Herleidbaarheid') + '</h2>'
    corps += p(message(resultat['validation']) if resultat.get('validation') else t('Validations humaines déclarées, pièces non authentifiées par le logiciel.', 'Menselijke controles volgens opgave. De software verifieert de echtheid van documenten niet.'))
    corps += p(t('Empreinte du profil : ', 'Hash van het profiel: ') + profil['sha256']) + '<ul>' + sources + '</ul></section>'
    return '<!doctype html><html lang="' + langue + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + t('Comparaison des contrats', 'Contractvergelijking') + ' | Contingency</title><style>' + STYLE + '</style></head><body><main>' + corps + '</main></body></html>'


STYLE = '''
*{box-sizing:border-box}body{margin:0;background:white;color:#18232b;font-family:Arial,sans-serif;line-height:1.55}main{max-width:76rem;margin:auto;padding:clamp(1rem,4vw,3rem)}
h1{font-size:clamp(1.8rem,4vw,3rem);line-height:1.15;letter-spacing:-.035em}h2{font-size:clamp(1.25rem,2.5vw,1.7rem)}h3{font-size:1rem}a{color:#164cb0;text-underline-offset:3px}p,li,dd,dt{overflow-wrap:anywhere}section{border-top:1px solid #b9c4cd;margin-top:2rem;padding-top:1rem}li{margin:.4rem 0}ul{padding-left:1.3rem}small,.limite{color:#50606d}.tableau{max-width:100%;overflow:auto}table{border-collapse:collapse;width:100%;text-align:left}th,td{padding:.8rem;vertical-align:top;border-bottom:1px solid #cdd5dc;min-width:9rem}th:first-child{min-width:11rem}dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,12rem),1fr));gap:1rem}dl div{border-left:2px solid #d5dee5;padding-left:.8rem}dd{margin:0;font-weight:bold}summary{cursor:pointer}details{margin:1rem 0}.risque{border-left:3px solid #916522;padding:.5rem 1rem;background:#fffaf1}@media print{main{padding:0}details{display:block}.tableau{overflow:visible}th,td{min-width:0;padding:.3rem}section{break-inside:avoid}}
'''
