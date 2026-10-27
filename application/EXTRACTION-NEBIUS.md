# Extraction Nebius intégrée, mesures du 15 septembre 2026

## Chaîne exécutée

1. Découpage local des documents en passages repérés par document et ligne.
2. Présélection lexicale par champ.
3. Classement sémantique avec `Qwen/Qwen3-Embedding-8B` et fusion des classements.
4. Extraction par `Qwen/Qwen3-235B-A22B-Instruct-2507` avec schéma JSON strict.
5. Contrôle local de chaque repère et citation littérale.
6. Proposition séparée du formulaire. L'utilisateur accepte chaque valeur avant la validation globale et le solveur.

Une citation absente, une réponse tronquée, une valeur non finie ou un rendement hors domaine bloque la
proposition concernée. Les documents restent des données et les instructions qu'ils contiennent sont ignorées.

## Test court réel

| Mesure | Résultat |
| :--- | ---: |
| Champs exacts | 7 / 7 |
| Embeddings | 6,31 s, 339 tokens d'entrée |
| Extraction | 5,85 s, 565 tokens d'entrée, 783 tokens de sortie |
| Total API | 12,16 s |

Le dossier était construit avec trois textes en langage naturel. Le premier appel avec une limite de 2 200
tokens a été interrompu et rejeté. La limite a été portée à 6 000, puis l'appel a terminé normalement.

## Test long construit

Le dossier contient 44 pages de publications techniques publiques, dont un rapport NREL sur les modèles de
batterie et une publication Kaeser avec tableaux, plus trois documents fictifs explicites portant les sept
contraintes attendues. Il ne s'agit pas d'un dossier client.

| Mesure | Résultat |
| :--- | ---: |
| PDF | 44 pages, 4 398 581 octets |
| Import | 3,75 s |
| Lecture structurée | 1 PDF réussi, 1 en échec avec repli sur texte brut |
| Tableaux reconstruits | 3 |
| Extraction Nebius | 13,02 s |
| Champs exacts | 7 / 7 |
| Calcul | réalisable |
| Preuve solveur | optimale dans le modèle déclaré |
| Rapport | généré, traçabilité IA présente |

Une première version du classement sémantique a émis des avertissements numériques sur ce dossier. La
normalisation a été remplacée par une norme mise à l'échelle et le produit matriciel par des produits scalaires
contrôlés. Le second test n'a émis aucun avertissement.

## Test des neuf pièces existantes

Les quatre PDF publics et les cinq pièces construites du dossier long ont ensuite été importés ensemble. Le
premier passage a révélé que la recherche française perdait la fenêtre de production écrite en néerlandais et
que 88 % aller-retour pouvait être confondu avec un rendement par sens. Les requêtes ont été rendues
multilingues et un contrôle local bloque désormais cette confusion d'unité.

Au passage corrigé, cinq contraintes directes sur sept sont retrouvées et contrôlées : 650 kW, 100 kW, 4 h,
08:00 et 16:00. Le rendement reste vide car seule une valeur aller-retour est disponible. La puissance totale
reste vide car elle demande de relier deux pièces et de calculer `10 × 7,3 kW`. Ces absences sont le comportement
sûr attendu. Après une revue humaine qui déclare les deux hypothèses, le calcul est réalisable, le solveur
renvoie `optimal` dans le modèle déclaré et le rapport est généré avec sa trace IA.

L'extraction a varié de 22,73 s à 101,89 s sur trois passages. Le dernier appel a consommé 13 870 tokens
d'embedding, puis 8 302 tokens d'entrée et 937 tokens de sortie pour l'extraction. Les faits du dossier sont
restés inchangés avant la revue humaine.

Sources publiques utilisées :

- NREL, *Technoeconomic Modeling of Battery Energy Storage in SAM*, 36 pages : https://www.nlr.gov/docs/fy15osti/64641.pdf
- Kaeser, *CAGI Data Sheets: Blower Performance Comparison*, 8 pages : https://us.kaeser.com/download.ashx?id=tcm%3A46-37895

## Ce que cela ne prouve pas

Ce test prouve que la chaîne fonctionne sur un volume documentaire supérieur à quarante pages avec du bruit
technique. Il ne prouve ni la justesse sur un dossier industriel réel, ni un gain de temps, ni une validation
métier. Ces trois preuves nécessitent encore un dossier autorisé et un ingénieur chronométré.
