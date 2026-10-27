"""Masquage des données personnelles et des secrets avant tout envoi au fournisseur de modèle (issue n° 12).

Masqués : IBAN, e-mails, téléphones (NL, FR, international), BSN (nommés, ou neuf chiffres passant la preuve de 11,
qui ne prouve pas qu'un numéro a été attribué), EAN et KvK quand ils sont nommés,
secrets (clés d'API, jetons Bearer, identifiants dans une URL). Ni les noms ni les adresses : limite assumée.
Aucune promesse de couverture complète : un identifiant découpé autrement (hors IBAN coupé en fin de ligne) peut passer.
Le masquage ne change jamais le nombre de lignes, et les valeurs techniques (kW, heures, montants, dates) restent intactes.
"""
import copy
import re

VERSION = "masquage-1"

_SEP = r"[ \-]"


_UNITE_APRES = re.compile(r"[ \t]*(?:EUR|€|kWh|kW|MWh|MW|kVA|MVA|VA|W|V|A|%|uur|h|min|m3|m³)(?![A-Za-z])")
_DEVISE_AVANT = re.compile(r"(?:€|EUR)[ \t]*$")


def _bsn(m):
    chiffres = m.group(0)
    # Un montant ou une valeur technique avec son unité reste intact, même s'il passe la preuve de 11.
    if set(chiffres) == {"0"} or _UNITE_APRES.match(m.string, m.end()) or _DEVISE_AVANT.search(m.string, 0, m.start()):
        return chiffres
    total = sum(int(c) * poids for c, poids in zip(chiffres[:8], range(9, 1, -1))) - int(chiffres[8])
    return "[BSN]" if total % 11 == 0 else chiffres


# Ordre voulu : secrets, e-mails et IBAN avant les règles purement numériques.
REGLES = [
    ("SECRET", re.compile(r"(?<=://)[^\s/@:]+:[^\s/@]+(?=@)"), "[SECRET]"),
    ("SECRET", re.compile(r"(?<=Bearer )[A-Za-z0-9\-._~+/]+=*"), "[SECRET]"),
    ("SECRET", re.compile(r"\b(?:sk[-_][A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9\-]{10,})"),
     "[SECRET]"),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    # Un IBAN coupé par un retour à la ligne (PDF) est masqué en gardant ce retour, pour ne pas décaler les lignes.
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ \n]?[A-Z0-9]{4}){2,7}(?:[ \n]?[A-Z0-9]{1,3})?\b"),
     lambda m: "[IBAN]" + "\n" * m.group(0).count("\n")),
    ("EAN", re.compile(r"(?i)\b(EAN(?:[- ]?code)?[ \t]*[:\-]?[ \t]*)\d{18}\b"), r"\1[EAN]"),
    ("KVK", re.compile(r"(?i)\b(KvK(?:[- ]?nummer)?[ \t]*[:\-]?[ \t]*)\d{8}\b"), r"\1[KVK]"),
    ("BSN", re.compile(r"(?i)\b((?:BSN|burgerservicenummer|sofinummer)[ \t]*[:\-]?[ \t]*)\d{8,9}\b"), r"\1[BSN]"),
    ("BSN", re.compile(r"(?<![\d.,])\b\d{9}\b(?![.,]\d)"), _bsn),
    ("TEL", re.compile(r"(?<![\w+])(?:\+|00)(?:31|32|33|44|49|1)" + _SEP + r"?\(?\d{1,4}\)?(?:" + _SEP + r"?\d{2,4}){2,4}\b"),
     "[TEL]"),
    ("TEL", re.compile(r"(?<![\w])\(0[1-9]\d{0,2}\)[ \-]?\d{6,8}\b"), "[TEL]"),
    ("TEL", re.compile(r"(?<![\w])0[1-9](?:([ .])\d{2})(?:\1\d{2}){3}\b"), "[TEL]"),
    ("TEL", re.compile(r"(?<![\w])0[1-9]\d{0,2}" + _SEP + r"?\d{6,8}\b"), "[TEL]"),
]


ETIQUETTES = ("SECRET", "EMAIL", "IBAN", "EAN", "KVK", "BSN", "TEL")


def masquer_compter(texte):
    """Texte masqué et nombre d'éléments masqués par catégorie (jamais les valeurs). Aucun état partagé."""
    compte = {}
    for categorie, motif, remplacement in REGLES:
        def remplacer(m):
            nouveau = remplacement(m) if callable(remplacement) else m.expand(remplacement)
            if nouveau != m.group(0):
                compte[categorie] = compte.get(categorie, 0) + 1
            return nouveau
        texte = motif.sub(remplacer, texte)
    return texte, compte


def masquer(texte):
    return masquer_compter(texte)[0]


def masquer_corps(corps):
    """Copie du corps d'une requête au fournisseur, messages et entrées masqués ; le reste (schéma, paramètres) intact.

    Les comptes rendus sont ceux des étiquettes réellement présentes dans ce qui part, y compris celles déjà posées en
    amont (documents masqués en entier) ou présentes dans le texte d'origine : ce ne sont pas les seules substitutions faites ici."""
    copie, total = copy.deepcopy(corps), {}

    def ajouter(texte):
        # On compte les étiquettes présentes dans ce qui part, que le masquage ait eu lieu ici ou plus tôt
        # (documents masqués en entier avant la mise en JSON).
        masque = masquer(texte)
        for categorie in ETIQUETTES:
            n = masque.count("[" + categorie + "]")
            if n:
                total[categorie] = total.get(categorie, 0) + n
        return masque

    for message in copie.get("messages") or []:
        contenu = message.get("content")
        if isinstance(contenu, str):
            message["content"] = ajouter(contenu)
        elif isinstance(contenu, list):
            for partie in contenu:
                if isinstance(partie, dict) and isinstance(partie.get("text"), str):
                    partie["text"] = ajouter(partie["text"])
    if isinstance(copie.get("input"), str):
        copie["input"] = ajouter(copie["input"])
    elif isinstance(copie.get("input"), list):
        copie["input"] = [ajouter(t) if isinstance(t, str) else t for t in copie["input"]]
    return copie, total


def citation_trouvee(citation, ligne):
    """Citation littérale non vide de la ligne d'origine ou de sa version masquée ; la citation n'est jamais masquée."""
    return bool(citation) and (citation in ligne or citation in masquer(ligne))


def document_masque(document):
    """Vue masquée d'un document pour les contrôles numériques : un identifiant ne fournit jamais de valeur technique."""
    return {**document, "texte": masquer(document["texte"])}


def documents_masques(documents):
    """Vue masquée du document COMPLET, à construire avant toute mise en JSON ou découpage en repères : un identifiant
    coupé entre deux lignes y est vu en entier. Mêmes lignes, mêmes numéros ; les originaux restent locaux."""
    return [document_masque(document) for document in documents]
