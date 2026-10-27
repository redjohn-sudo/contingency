"""Préparer un dossier Flex-e/EIA en JSON et Markdown, sans dépôt externe."""
import argparse
import json
from pathlib import Path

from dossier_subventions import modele, preparer, rapport
from fiches_dossiers import lire_fiche


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--modele', type=Path)
    arguments.add_argument('--fiche', type=Path)
    arguments.add_argument('--sortie', type=Path)
    options = arguments.parse_args()
    if options.modele and any((options.fiche, options.sortie)):
        arguments.error('--modele s’utilise seul, sans fiche ni sortie.')
    try:
        if options.modele:
            with options.modele.open('x', encoding='utf-8') as fichier:
                json.dump(modele(), fichier, indent=2, ensure_ascii=False, allow_nan=False)
            print(options.modele)
            return
        if not options.fiche or not options.sortie:
            arguments.error('--fiche et --sortie sont requis.')
        fiche = lire_fiche(options.fiche)
        resultat = preparer(fiche)
        serialise = json.dumps(resultat, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
        rendu = rapport(resultat)
        options.sortie.mkdir(parents=True, exist_ok=False)
        (options.sortie / 'subventions.json').write_text(serialise, encoding='utf-8')
        (options.sortie / 'dossier-subventions.md').write_text(rendu, encoding='utf-8')
        print(json.dumps({'dossier': str(options.sortie), 'flex_e': resultat['flex_e']['statut'],
                          'eia': resultat['eia']['statut']}, ensure_ascii=False))
    except (OSError, ValueError, TypeError) as erreur:
        arguments.error(str(erreur))


if __name__ == '__main__':
    main()
