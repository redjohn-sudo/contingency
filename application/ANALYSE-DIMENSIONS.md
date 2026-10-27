# Analyse du projet par dimensions

15 septembre 2026. Une dimension est ici un axe d'analyse, pas une dimension physique supplémentaire. Examiner les interactions permet de découvrir des erreurs que des vérifications isolées manquent.

| Axe | Question déterminante | Preuve actuelle | Limite encore ouverte |
| :--- | :--- | :--- | :--- |
| Données | Les mesures représentent-elles bien la puissance et le temps ? | Import explicite en kW, cadence de 15 minutes contrôlée, blocs complets | Exactitude du compteur et origine non certifiées ; pics intrapas invisibles |
| Documents | Chaque valeur a-t-elle une source et ses conditions ? | Texte PDF/TXT consultable avec lignes, citation vérifiée, hypothèse justifiée | OCR local et extraction Nebius intégrés ; associations cellule/unité/condition et fidélité sur scans dégradés non évaluées |
| Mathématiques | Le résultat satisfait-il le modèle annoncé ? | Moteur avec témoin physique ; cas de la nouvelle interface comparé au solveur LP | OR-Tools optimise jusqu’à sept blocs dans le modèle déclaré ; horizon annuel non résolu |
| Physique | Le modèle représente-t-il réellement le site ? | Rendement par sens, unités et durée explicités | Pas de vieillissement, démarrages, tarifs, puissance réactive, réserves ou incertitude de demande |
| Usage | Une modification peut-elle laisser croire qu'un ancien résultat est valide ? | Invalidation dans l'interface et refus des anciennes révisions côté serveur | Validation utilisateur, pas validation d'un ingénieur ; temps humain non mesuré |
| Économie | Quel bénéfice le client peut-il vérifier ? | Comparaison de capacité utile à production journalière identique | Aucun tarif, prix batterie, coût de non-production, client pilote ou gain financier mesuré |
| Hackathon | L'usage des outils et la préparation sont-ils admissibles ? | Déclaration de préparation mise à jour, dépendance Nebius identifiée | Nebius testé avant événement ; modèles et conditions du 23 à confirmer ; travail préparatoire à déclarer |

## Interactions prioritaires

1. **Document × calcul** : une valeur numérique peut être bien calculée et néanmoins mal interprétée. L'interface expose sa ligne source ; si une valeur structurée est modifiée, la correction doit être justifiée. L'interprétation des conditions reste humaine.
2. **Révision × validation** : une correction annule le résultat et sa validation. L'empreinte comprend faits, documents, profil et décisions de revue documentaire lorsqu'elles existent. Une ancienne révision est refusée au calcul.
3. **Données × planning** : une cadence correcte ne prouve pas un calendrier de travail. Le prototype parle de blocs relatifs de 24 heures et déclare un cycle dans chaque bloc, sans prétendre gérer les week-ends.
4. **Heuristique × conclusion** : un planning non réalisable ne prouve pas qu'aucun planning ne fonctionne. Le rapport limite la conclusion aux scénarios testés. Si le planning de référence est meilleur que l'heuristique, il est conservé.
5. **Stockage × achat** : une capacité utile théorique n'est pas une référence de batterie achetable. Le rapport n'annonce pas un prix ou une économie fictive.
6. **IA × hackathon** : un moteur mathématique fonctionnel ne démontre pas l'usage central de Nebius. Nebius est désormais intégré au parcours local et testé sur des dossiers construits ; cela ne remplace pas la validation métier et la démonstration du jour.

## Ce qui a été corrigé pendant cette passe

- Absence de parcours complet : import, lecture, validation, calcul et rapport reliés.
- Ancienne validation réutilisable après changement : révision et blocage explicites.
- Valeur corrigée sans explication : justification exigée quand la ligne structurée contredit la valeur.
- Heuristique potentiellement pire que le départ initial : conservation du meilleur scénario réalisable.
- Conflits de champs structurés : aucune valeur préremplie lorsqu'il existe plusieurs candidats.

## Vérifications réalisées

Six tests Python : parcours complet et comparaison LP, validation et révision, sources et hypothèses, format/cadence/horaires, import d'un PDF réel et conflit de valeurs, origine des requêtes.

Parcours Brave : exemple, préparation, case d'approbation obligatoire, calcul, résultat, invalidation après modification. Captures à 600 et 2000 pixels ; contrôle mobile dans une iframe de 390 pixels ; absence de débordement et d'erreur JavaScript observée.

Ces contrôles sont bornés. Ils ne constituent ni une certification technique ni une garantie de fiabilité absolue.

## Priorité suivante

Faire relire un dossier autorisé et mesurer les corrections humaines. Confirmer le modèle admissible le 23. Le détail des preuves manquantes est dans `../audit-contradictions/CHANTIERS-RESTANTS.md`.

## Mise à jour après intégration des outils

[Corrections vérifiées](CORRECTIONS-OUTILS.md) : OR-Tools corrige un contre-exemple de planning, Docling fournit des tableaux complémentaires sans remplacer le texte brut, et les imports de dates UTC sont corrigés. Les autres limites restent ouvertes.

## Mise à jour après l'audit contradictoire

La lecture OCR, le contrôle quantité/unité, l'audit interdocuments et la revue
motivée sont raccordés à l'application. Un appel de modèle n'est pas requis pour
ces règles locales. Les résultats actuels remplacent les anciennes descriptions
« OCR non activé » et « parcours manuel seulement » : voir
[les mesures et limites de cette passe](../audit-contradictions/RESULTATS.md).
Les réserves, dates d'effet, calendriers réels et faux négatifs non couverts
restent des limites à examiner avec un professionnel.
