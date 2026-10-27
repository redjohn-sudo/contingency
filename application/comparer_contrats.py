"""CLI locale : CSV canonique, fiche sourcée, résultats JSON et rapport HTML."""
import argparse
import json
from pathlib import Path

from fiche_contrats import modele_contrats


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--modele', type=Path, help='Écrire une fiche vide, aucune hypothèse de prix.')
    arguments.add_argument('--profil', type=Path)
    arguments.add_argument('--fiche', type=Path)
    arguments.add_argument('--sortie', type=Path)
    arguments.add_argument('--langue', choices=('fr', 'nl'), default='fr', help='Langue du rapport HTML, calculs inchangés.')
    options = arguments.parse_args()
    if options.modele:
        options.modele.write_text(json.dumps(modele_contrats(), ensure_ascii=False, indent=2) + '\n')
        print(options.modele)
        return
    if not all((options.profil, options.fiche, options.sortie)):
        arguments.error('--profil, --fiche et --sortie requis pour comparer.')
    from serveur import _lire_profil_detaille
    from optimisation_contrat import comparer_contrats
    from rapport_contrats import rendre_comparaison
    if options.profil.stat().st_size > 20 * 1024 * 1024 or options.fiche.stat().st_size > 20 * 1024 * 1024:
        arguments.error('Un fichier ne doit pas dépasser 20 Mio.')
    try:
        valeurs, dates = _lire_profil_detaille(options.profil.read_text(encoding='utf-8-sig'), jours_civils=True)
        configuration = json.loads(options.fiche.read_text(encoding='utf-8-sig'))
        resultat = comparer_contrats(valeurs, dates, configuration)
    except (ValueError, UnicodeError) as erreur:
        arguments.error(str(erreur))
    options.sortie.mkdir(parents=True, exist_ok=True)
    (options.sortie / 'comparaison.json').write_text(json.dumps(resultat, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    (options.sortie / 'comparaison.html').write_text(rendre_comparaison(resultat, options.langue), encoding='utf-8')
    print(json.dumps({'rapport': str(options.sortie / 'comparaison.html'),
                      'dominante': resultat['dominante'], 'options': len(resultat['options'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
