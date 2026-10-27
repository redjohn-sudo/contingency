"""Préparer localement une alerte GOTORK et son dossier, sans envoi au gestionnaire."""
import argparse
import csv
import json
from pathlib import Path

from gotork import analyser, modele, rapport
from fiches_dossiers import lire_fiche


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--modele', type=Path)
    arguments.add_argument('--fiche', type=Path)
    arguments.add_argument('--profil', type=Path)
    arguments.add_argument('--sortie', type=Path)
    options = arguments.parse_args()
    if options.modele and any((options.fiche, options.profil, options.sortie)):
        arguments.error('--modele s’utilise seul, sans fiche, profil ni sortie.')
    try:
        if options.modele:
            with options.modele.open('x', encoding='utf-8') as fichier:
                json.dump(modele(), fichier, ensure_ascii=False, indent=2, allow_nan=False)
            print(options.modele)
            return
        if not all((options.fiche, options.sortie)):
            arguments.error('--fiche et --sortie sont requis ; --profil permet le calcul des seuils.')
        fiche = lire_fiche(options.fiche)
        if options.profil and options.profil.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Profil limité à 20 Mio.')
        lignes = []
        if options.profil:
            with options.profil.open(encoding='utf-8-sig', newline='') as fichier:
                lecteur = csv.DictReader(fichier, strict=True)
                if lecteur.fieldnames != ['fin_intervalle', 'puissance_kw']:
                    raise ValueError('CSV attendu : fin_intervalle,puissance_kw ; kW, fins de quarts avec fuseau.')
                lignes = list(lecteur)
        if any(None in l or any(v is None for v in l.values()) for l in lignes):
            raise ValueError('Ligne CSV incomplète ou colonnes supplémentaires.')
        resultat = analyser([float(l['puissance_kw']) for l in lignes],
                            [l['fin_intervalle'] for l in lignes], fiche)
        serialise = json.dumps(resultat, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        rendu = rapport(resultat)
        # Répertoire nouveau : les pièces d’un dossier existant restent intactes.
        options.sortie.mkdir(parents=True, exist_ok=False)
        (options.sortie / 'gotork.json').write_text(serialise, encoding='utf-8')
        (options.sortie / 'dossier-defense.md').write_text(rendu, encoding='utf-8')
        print(json.dumps({'statut': resultat['statut'], 'dossier': str(options.sortie)}, ensure_ascii=False))
    except (OSError, ValueError, TypeError, csv.Error) as erreur:
        arguments.error(str(erreur))


if __name__ == '__main__':
    main()
