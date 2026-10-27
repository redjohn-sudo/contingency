"""Contrôles bornés FR/EN/NL : quantités, contexte et désaccords, sans arbitrage LLM.

Ces règles ne constituent pas une compréhension générale des contrats. Une absence
d'alerte signifie seulement qu'aucune des règles couvertes n'a détecté de problème.
"""
import hashlib
import json
import math
import re
import unicodedata

VERSION = 'controle-documents-4-battery-labels'
NOMBRE = r'(?<![\w.,+\-])\d+(?:[.,]\d+)?(?![\d.,])'
QUANTITE = re.compile(r'(' + NOMBRE + r')\s*(MW|kW|W|kVA|MVA|kWh|MWh|minutes?|minuten|mins?|heures?|hours?|uur|h)\b', re.I)
# Le pourcentage n'a pas de frontière de mot après le signe.
POURCENT = re.compile(r'(' + NOMBRE + r')\s*%')
HEURE = re.compile(r'(?<!\d)(\d{1,2}):([0-5]\d)(?!\d)')
HORAIRE_FRAGMENTE = re.compile(r'\d[^\S\r\n]+\d{1,2}\s*:\s*\d{2}\b|\b\d{1,2}\s*:\s*\d[^\S\r\n]+\d\b')
NOTATION_AMBIGUE = re.compile(r"\d[.,]\d{3}(?!\d)|\d\s+\d{3}(?!\d)|\d['’ʼ]\d")
ROUND_TRIP = r'round[ -]?trip|aller[ -]?retour|heen en terug'
NEGATION = r'\b(?:no|not|geen|niet|sans|aucun|aucune|pas de)\b'
INSTRUCTION = r'(?:ignore|negeer|oublie).*?(?:instruct|consign|previous)|system prompt'
# Gabarit de document : des dates laissées en format à remplir trahissent un modèle, pas la
# pièce d'un site (facture modèle Liander, 25/09 : DeepSeek ne l'avait pas signalé).
GABARIT_DATE = re.compile(r'\b(?:DD[/-]MM[/-](?:JJJJ|YYYY)|MM[/-](?:JJJJ|YYYY)|(?:JJJJ|YYYY)-MM-DD)\b')
# Valeur masquée (xxxxx) : modèle ou pièce anonymisée par le client. Signalée, jamais bloquante
# seule, et jamais remplacée par une déduction.
# Données fictives nommées comme telles (modèle Stedin « VOORBEELDKLANT BV, Voorbeeldstraat 1 »).
# Mot composé seulement : « bijvoorbeeld » et « voorbeeld » seul n'en font pas un modèle.
MODELE_NOMME = re.compile(r'\bvoorbeeld(?:klant|straat|plaats|bedrijf|nota|factuur)\b')
VALEUR_MASQUEE = re.compile(r'(?<![A-Za-z])[xX]{4,}(?![A-Za-z])')
LIBELLES = {
    'plafond_kw': r'plafond|puissance de raccordement contractuelle|limite (?:reseau|contractuelle)|grid (?:limit|cap)|import limit|contract(?:ed|ual).*?(?:power|limit)|gecontracteerd transportvermogen afname|\bgtv\b',
    'puissance_max_kw': r'omvormervermogen|inverter|(?:battery|batterie|stockage|converter|convertisseur).*?(?:power|puissance)|(?:puissance|power).*?(?:batterie|battery|convertisseur)|charge.?discharge',
    'puissance_kw': r'(?:machine|equipment).*?(?:power|puissance)|package input power|puissance.*?(?:machine|absorbee)|opgenomen vermogen|puissance electrique',
    'rendement': r'rendement|efficiency|efficientie|laadrendement|ontlaadrendement',
    'duree_heures': r'duree|duration|duurt|aaneengesloten|consecutive|consecuti',
    'ouverture_heure': r'fenetre|window|tussen|debut|start|vanaf|opening|autorisee de',
    'echeance_heure': r'fenetre|window|tussen|fin obligatoire|deadline|uiterlijk|eind|autorisee de|atelier ferme|workshop closes',
}


def normaliser(texte):
    propre = ''.join(c for c in unicodedata.normalize('NFKD', texte.lower())
                     if not unicodedata.combining(c))
    propre = propre.translate(str.maketrans({s: '-' for s in '−–—‐‑‒﹣－'}))
    propre = propre.translate(str.maketrans({'’': "'", 'ʼ': "'"}))
    # Le lecteur numérique doit voir le signe même si le PDF l'espace du nombre.
    return re.sub(r'([+-])[^\S\r\n]+(?=\d)', r'\1', propre)


def nombre(texte):
    return float(texte.replace(',', '.'))


def egal(a, b):
    return math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-9)


def quantites(texte, grandeur):
    """Pas de conversion kVA/kW ni kWh/kW. Notation des milliers ambiguë refusée."""
    texte = normaliser(texte)
    if NOTATION_AMBIGUE.search(texte):
        return []
    unites = {'puissance': {'w': .001, 'kw': 1, 'mw': 1000},
              'energie': {'kwh': 1, 'mwh': 1000},
              'apparente': {'kva': 1, 'mva': 1000},
              'duree': {'h': 1, 'hour': 1, 'hours': 1, 'heure': 1, 'heures': 1,
                        'uur': 1, 'minute': 1/60, 'minutes': 1/60, 'minuten': 1/60, 'min': 1/60, 'mins': 1/60}}[grandeur]
    return [nombre(m[1]) * unites[m[2].lower()] for m in QUANTITE.finditer(texte)
            if m[2].lower() in unites]


def contexte_ligne(document, ligne):
    lignes = document['texte'].splitlines()
    debut, fin = max(0, ligne - 3), min(len(lignes), ligne + 2)
    return '\n'.join(lignes[debut:fin])


def valeurs_ligne(champ, texte):
    propre = normaliser(texte)
    if re.search(INSTRUCTION, propre):
        return []
    structure = re.fullmatch(r'\s*' + re.escape(champ) + r'\s*=\s*(\d+(?:[.,]\d+)?)\s*', propre)
    if structure:
        return [nombre(structure[1])]
    if not re.search(LIBELLES[champ], propre):
        return []
    if re.search(r'(?:not specified|non (?:specifie|fourni)|niet (?:opgegeven|bekend))', propre):
        return []
    assertion = re.sub(r'mag niet worden onderbroken|not interruptible|non interruptible|sans interruption|aucun equipement ne tourne apres la fermeture', '', propre)
    if re.search(NEGATION + r"|n[' ]est pas", assertion):
        return []
    if champ == 'plafond_kw' and re.search(r'invoeding|export|injection', propre) and not re.search(r'afname|import|soutirage', propre):
        return []
    if champ.endswith('_kw'):
        return quantites(texte, 'puissance')
    if champ == 'rendement':
        if re.search(ROUND_TRIP, propre):
            return []
        pourcents = [nombre(m[1])/100 for m in POURCENT.finditer(propre)]
        if pourcents:
            return pourcents
        ratio = re.search(r'(?:ratio|rendement|efficiency)\s*(?:par sens)?\s*[:=]?\s*(0[.,]\d+|1(?:[.,]0+)?)\b', propre)
        return [nombre(ratio[1])] if ratio else []
    if champ == 'duree_heures':
        return quantites(texte, 'duree')
    if HORAIRE_FRAGMENTE.search(texte):
        return []
    horaires = list(HEURE.finditer(texte))
    if any(int(m[1]) > 24 or (int(m[1]) == 24 and int(m[2]) != 0) for m in horaires):
        return []
    heures = [int(m[1]) + int(m[2])/60 for m in horaires]
    if not heures:
        heures = quantites(texte, 'duree')
    if len(heures) == 2:
        return [heures[0 if champ == 'ouverture_heure' else 1]]
    return heures if len(heures) == 1 else []


def preuve(document, numero, ligne, lignes=None, sha=None):
    return {'document': numero, 'ligne': ligne, 'nom': document.get('nom', f'D{numero+1}'),
            'citation': (lignes if lignes is not None else document['texte'].splitlines())[ligne - 1],
            'sha256': sha or hashlib.sha256(document['texte'].encode()).hexdigest()}


def qualificatifs(document):
    if document.get('type_document') == 'hypothese_simulation':
        return {'generique': False, 'preliminaire': False}
    titre = normaliser(document.get('nom', '') + '\n' + document['texte'][:1600])
    lignes = [t.strip() for t in document['texte'].splitlines() if t.strip()]
    entete = normaliser(document.get('nom', '') + '\n' + (lignes[0] if lignes else ''))
    entete = re.sub(r'\b(?:par exemple|for example|bijvoorbeeld)\b', '', entete)
    return {'generique': bool(re.search(r'\b(?:guide|tutorial|exemple|example|voorbeeld)\b', entete)
                              or GABARIT_DATE.search(document['texte'])
                              or MODELE_NOMME.search(titre)),
            'preliminaire': bool(re.search(r'preliminary data|donnees preliminaires|voorlopige gegevens', titre))}


def par_sens_explicite(texte):
    propre = normaliser(texte)
    if re.search(r'par sens|per direction|each direction', propre):
        return True
    deux_sens = re.search(r'\b(?:charge|charging|laadrendement)\b', propre) and re.search(
        r'\b(?:decharge|discharge|discharging|ontlaadrendement)\b', propre)
    valeurs = [nombre(m[1])/100 for m in POURCENT.finditer(propre)]
    return bool(deux_sens and len(valeurs) == 2 and egal(*valeurs))


def controler_valeur(champ, valeur, document, ligne):
    """Contrôle la ligne entière et son voisinage, pas le seul extrait choisi par le LLM."""
    texte = document['texte'].splitlines()[ligne - 1]
    contexte = normaliser(contexte_ligne(document, ligne))
    if champ == 'rendement' and re.search(ROUND_TRIP, contexte):
        # Une valeur explicitement par sens reste distincte d'un rendement de cycle voisin.
        if not par_sens_explicite(texte):
            return False, 'rendement aller-retour bloqué'
    q = qualificatifs(document)
    if q['generique'] or q['preliminaire']:
        return False, 'source générique ou préliminaire, application au site à confirmer'
    if champ in ('ouverture_heure', 'echeance_heure') and HORAIRE_FRAGMENTE.search(texte):
        return False, 'horaire fragmenté : vérifier les chiffres sur le document original'
    if NOTATION_AMBIGUE.search(texte) and QUANTITE.search(normaliser(texte)):
        return False, 'notation numérique ambiguë : confirmer séparateur décimal ou de milliers'
    valeurs = list(dict.fromkeys(valeurs_ligne(champ, texte)))
    if len(valeurs) != 1 or not egal(valeurs[0], valeur):
        return False, 'valeur, unité ou sens non établis par la ligne complète'
    return True, 'valeur et unité contrôlées sur la ligne complète, portée à vérifier'


def auditer_documents(documents):
    anomalies, candidats = [], {champ: [] for champ in LIBELLES}

    def ajouter(code, message, champs, preuves):
        donnees = {'code': code, 'message': message, 'champs': sorted(champs), 'preuves': preuves}
        donnees['id'] = hashlib.sha256(json.dumps(donnees, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        if not any(a['id'] == donnees['id'] for a in anomalies):
            anomalies.append(donnees)

    for numero, doc in enumerate(documents):
        lignes = doc['texte'].splitlines()
        sha = hashlib.sha256(doc['texte'].encode()).hexdigest()
        q = qualificatifs(doc)
        portees = re.findall(r'^\s*(?:site|klant|customer)\s*:\s*(.+)', normaliser(doc['texte']), re.M)
        portee = portees[0].strip(' .') if len(set(portees)) == 1 else ''
        if q['generique'] or q['preliminaire']:
            code = 'donnees_preliminaires' if q['preliminaire'] else 'document_generique'
            ligne = next((i for i, t in enumerate(lignes, 1) if re.search(
                r'guide|tutorial|example|exemple|voorbeeld|preliminary|preliminaire|voorlopige', normaliser(t))
                or GABARIT_DATE.search(t)), 1)
            if lignes:
                ajouter(code, 'Document générique ou préliminaire : confirmer son application au site.', [], [preuve(doc, numero, ligne)])
        energie_nominale, energie_utile, dod, apparente = [], [], [], []
        for ligne, texte in enumerate(lignes, 1):
            propre = normaliser(texte)
            if not texte.strip():
                continue
            p = preuve(doc, numero, ligne, lignes, sha)
            if VALEUR_MASQUEE.search(texte):
                champs = [champ for champ, libelle in LIBELLES.items() if re.search(libelle, propre)]
                ajouter('valeur_masquee', 'Valeur masquée dans le document : la demander, ne jamais la déduire.', champs, [p])
            if re.search(INSTRUCTION, propre):
                ajouter('instruction_parasite', 'Une instruction adressée au modèle est ignorée comme preuve numérique.', [], [p])
                continue
            if HORAIRE_FRAGMENTE.search(texte):
                champs = [c for c in ('ouverture_heure', 'echeance_heure') if re.search(LIBELLES[c], propre)]
                if champs:
                    ajouter('horaire_fragmente', 'Un horaire contient des chiffres séparés : vérifier le document original avant simulation.', champs, [p])
            if NOTATION_AMBIGUE.search(texte) and QUANTITE.search(propre):
                champs = [champ for champ, libelle in LIBELLES.items() if re.search(libelle, propre)]
                if champs:
                    ajouter('notation_ambigue', 'Notation numérique à confirmer : séparateur décimal ou de milliers. Aucune conversion automatique.', champs, [p])
            if re.search(r'(?:site operating pressure|pression du site|bedrijfsdruk).*?(?:not specified|non specifie|onbekend)', propre):
                ajouter('condition_site_absente', 'La pression de fonctionnement du site manque pour choisir une puissance parmi les conditions fabricant.', ['puissance_kw'], [p])
            for champ in LIBELLES:
                valeurs = valeurs_ligne(champ, texte)
                if valeurs and not (q['generique'] or q['preliminaire']):
                    candidats[champ].append({'valeurs': valeurs, 'portee': portee, 'preuve': p})
            if re.search(r'noodstroomreserve|(?:reserve|backup).*?(?:priorit|must|toujours|always)|reserve gaat|reserve.*?voorrang', propre):
                if not re.search(NEGATION, propre) and any(nombre(m[1]) > 0 for m in POURCENT.finditer(propre)):
                    ajouter('reserve_prioritaire', 'Une réserve obligatoire est déclarée. Le modèle actuel ne représente pas cette obligation.',
                            ['puissance_max_kw', 'rendement'], [p])
            if re.match(r'\s*(?:(?:battery|batterie|accu)\s+)?(?:nominale? (?:capaciteit|capacity)|capacite nominale|nominal capacity)\s*:', propre):
                energie_nominale.extend((v, p) for v in quantites(texte, 'energie'))
            if re.match(r'\s*(?:(?:battery|batterie|accu)\s+)?(?:bruikbare capaciteit|usable capacity|capacite (?:utile|utilisable))\s*:', propre):
                energie_utile.extend((v, p) for v in quantites(texte, 'energie'))
            if re.search(r'\bdod\b|depth of discharge|ontlaaddiepte|profondeur de decharge', propre):
                dod.extend((nombre(m[1])/100, p) for m in POURCENT.finditer(propre))
            if re.search(r'aansluitcapaciteit|puissance apparente|apparent power', propre):
                apparente.extend((v, p) for v in quantites(texte, 'apparente'))
            if re.search(ROUND_TRIP, propre) and POURCENT.search(propre):
                # Signaler la sémantique de cycle même si le modèle choisit une citation réduite.
                par_sens = any(par_sens_explicite(t) and valeurs_ligne('rendement', t) for t in lignes)
                if not par_sens:
                    ajouter('rendement_cycle', 'Un rendement aller-retour ne définit pas le rendement par sens utilisé par le modèle.', ['rendement'], [p])
        if len(energie_nominale) == len(energie_utile) == len(dod) == 1:
            nominale, utile, profondeur = energie_nominale[0][0], energie_utile[0][0], dod[0][0]
            if not egal(nominale * profondeur, utile):
                ajouter('capacite_incoherente', 'Capacité utile incompatible avec capacité nominale × profondeur de décharge. Périmètre et fournisseur à confirmer.',
                        ['puissance_max_kw', 'rendement'], [energie_nominale[0][1], energie_utile[0][1], dod[0][1]])
        plafonds = [c for c in candidats['plafond_kw'] if c['preuve']['document'] == numero]
        if len(apparente) == 1:
            for c in plafonds:
                if len(c['valeurs']) == 1 and c['valeurs'][0] > apparente[0][0] + 1e-6:
                    ajouter('capacites_a_confirmer', 'Le plafond actif déclaré dépasse la capacité apparente citée : vérifier le périmètre et les limites physiques.',
                            ['plafond_kw'], [c['preuve'], apparente[0][1]])

    for champ, valeurs in candidats.items():
        # Regrouper par site explicitement nommé. Une date plus récente ne vaut pas autorité contractuelle.
        groupes = {}
        for c in valeurs:
            groupes.setdefault(c['portee'], []).append(c)
        for groupe in groupes.values():
            distincts = []
            for c in groupe:
                for v in c['valeurs']:
                    if not any(egal(v, precedent) for precedent in distincts):
                        distincts.append(v)
            if len(distincts) > 1:
                ajouter('valeurs_a_concilier', champ + ' : plusieurs valeurs ou conditions dans le dossier ; aucune priorité automatique.',
                        [champ], [c['preuve'] for c in groupe])
        if len(groupes) > 1:
            ajouter('portee_a_confirmer', champ + ' : les pièces ne désignent pas toutes le même site ou leur portée est inconnue.',
                    [champ], [c['preuve'] for c in valeurs])
    return {'version': VERSION, 'anomalies': anomalies,
            'limite': 'Règles locales FR/EN/NL, non exhaustives. Absence d’alerte ne vaut pas validation métier.'}


def verifier_revue(audit, revue):
    """Conserve les alertes : une dérogation n'autorise qu'une simulation explicitement limitée."""
    attendus = {a['id'] for a in audit['anomalies']}
    if not isinstance(revue, dict) or set(revue) != attendus:
        raise ValueError('Chaque alerte documentaire nécessite une revue explicite avant simulation.')
    propres = {}
    for identifiant in sorted(attendus):
        entree = revue[identifiant]
        if not isinstance(entree, dict) or entree.get('decision') not in {'simulation_limitee', 'non_applicable'}:
            raise ValueError('Expliquez une hypothèse de simulation ou pourquoi chaque alerte ne s’applique pas.')
        motif = entree.get('motif', '')
        if not isinstance(motif, str) or not 30 <= len(motif.strip()) <= 2000:
            raise ValueError('Expliquez pour chaque alerte l’hypothèse et la limite retenues (30 caractères minimum).')
        propres[identifiant] = {'decision': entree['decision'], 'motif': motif.strip()}
    return propres
