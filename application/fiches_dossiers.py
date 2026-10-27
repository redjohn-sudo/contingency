"""Lecture des fiches de dossiers : objet JSON UTF-8, sans ambiguïté numérique."""
import json
import math
from pathlib import Path

TAILLE_MAX_FICHE = 1024 * 1024
PROFONDEUR_MAX_FICHE = 64


def _objet_unique(paires):
    resultat = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError(f'Champ JSON répété : {cle[:120]!r}.')
        resultat[cle] = valeur
    return resultat


def _nombre_fini(texte):
    valeur = float(texte)
    if not math.isfinite(valeur):
        raise ValueError('Nombre JSON non fini ou trop grand.')
    return valeur


def _constante_interdite(texte):
    raise ValueError(f'Constante interdite dans une fiche JSON : {texte}.')


def lire_fiche(chemin):
    """Refuse aussi les doublons imbriqués et les valeurs invalides hors calcul."""
    with Path(chemin).open('rb') as fichier:
        contenu = fichier.read(TAILLE_MAX_FICHE + 1)
    if len(contenu) > TAILLE_MAX_FICHE:
        raise ValueError('Fiche limitée à 1 Mio.')
    try:
        fiche = json.loads(contenu.decode('utf-8-sig'), object_pairs_hook=_objet_unique,
                           parse_float=_nombre_fini, parse_constant=_constante_interdite)
    except RecursionError as erreur:
        raise ValueError('Fiche JSON trop profondément imbriquée.') from erreur
    if not isinstance(fiche, dict):
        raise ValueError('La fiche doit être un objet JSON.')
    # JSON permet des échappements isolés qui ne sont pas encodables en UTF-8.
    # Les refuser ici évite un dossier partiellement écrit lors du rendu.
    a_controler = [(fiche, 0)]
    while a_controler:
        valeur, profondeur = a_controler.pop()
        if profondeur > PROFONDEUR_MAX_FICHE:
            raise ValueError('Fiche JSON trop profondément imbriquée (64 niveaux maximum).')
        if isinstance(valeur, dict):
            a_controler.extend((cle, profondeur + 1) for cle in valeur)
            a_controler.extend((enfant, profondeur + 1) for enfant in valeur.values())
        elif isinstance(valeur, list):
            a_controler.extend((enfant, profondeur + 1) for enfant in valeur)
        elif isinstance(valeur, str):
            try:
                valeur.encode('utf-8')
            except UnicodeEncodeError as erreur:
                raise ValueError('Texte JSON contenant un caractère Unicode isolé invalide.') from erreur
    return fiche
