# Corrections appuyées sur des outils existants

15 septembre 2026. Changements intégrés à la démo locale, sans accès Nebius ni appel payant. Travail préparatoire antérieur au hackathon.

## Planning : limite corrigée sur les petits horizons

[OR-Tools](https://developers.google.com/optimization/scheduling/job_shop) fournit des solveurs d'ordonnancement. Le modèle de ce projet a été écrit spécifiquement avec OR-Tools/SCIP : choix d'un départ par bloc, cycle machine consécutif, puissance réseau limitée, stockage cyclique, rendement constant par sens, interdiction de charger et décharger simultanément. Il minimise la capacité utile de stockage, pas le makespan de l'exemple Google.

| Cas synthétique de régression | Capacité utile |
| :--- | ---: |
| Meilleure des deux anciennes stratégies | 22,22 kWh |
| Meilleur des horaires testés exhaustivement | 12,22 kWh |
| Solution OR-Tools, optimum déclaré par SCIP | 12,22 kWh |

Aucun gain client ni économie financière n'est déduit de ce cas construit. Le fichier `optimisation/contre-exemple-planning.json` conserve toutes ses entrées. Le résultat du solveur est contrôlé par le moteur analytique indépendant. Un second cas sur deux jours concorde avec l'énumération exhaustive des départs. Un cas infaisable et le garde-fou d'horizon sont vérifiés.

L'interface appelle désormais ce solveur pour les profils de sept blocs maximum, avec quatre secondes de recherche et un seul thread. Elle garde les stratégies de référence si la recherche est indisponible, échoue ou ne propose pas mieux. Le rapport expose le statut et n'annonce un optimum que si le solveur le rapporte. L'optimalité porte sur ce modèle discret, aux tolérances numériques du solveur, pas sur tous les aspects d'un site réel. L'optimisation annuelle reste ouverte.

## Documents : lecture structurée ajoutée, erreurs encore signalées

[Docling](https://github.com/docling-project/docling), version 2.127.0, a traité les deux PDF fabricants localement, sur CPU avec deux threads. Les données structurées conservent coordonnées de cellules, lignes/colonnes fusionnées et pages. La [documentation de sérialisation](https://docling-project.github.io/docling/concepts/serialization/) conseille de conserver la structure plutôt que de compter uniquement sur le Markdown pour les tableaux complexes.

Les discussions et [problèmes remontés sur GitHub](https://github.com/docling-project/docling/issues/2073) ont motivé une vérification ciblée, pas une confiance automatique dans l'outil. Une recherche Reddit a servi à repérer les difficultés récurrentes, pas à établir la précision de l'extraction.

| Vérification sur nos fichiers | Lecture texte précédente | Docling |
| :--- | :--- | :--- |
| Puissance du groupe et son libellé sur une même ligne | Non | Oui |
| Puissance nominale moteur et unité sur une même ligne | Oui | Oui |
| Nombre 181 sans espace interne | Oui | Non |
| Libellé de puissance à débit nul conservé | Oui | Non |
| Phrase du service factor sans entrelacement de colonnes | Non | Oui |

Ces cinq vérifications choisies pendant le développement ne constituent pas un score général de précision. Le gain est complémentaire : Docling améliore certains rapports entre valeurs et libellés, mais perd d'autres informations. Deux blocs de tableaux détectés sur Atlas, trois sur Kaeser, dont un petit bloc non exploitable comme fiche complète. Aucun taux de compréhension correcte par LLM n'est mesuré.

La démo conserve donc le texte brut comme source numérotée et affiche les tableaux reconstruits en complément. Un contrôle signale les nombres non retrouvés tels quels dans la lecture structurée. Il ne corrige pas « 1 81 » en « 181 » sans preuve et ne certifie pas l'association d'une valeur à sa condition. Le JSON téléchargeable inclut les cellules et ce contrôle. Les chiffres des tableaux ne sont pas injectés automatiquement dans les paramètres de calcul.

Les conversions ont pris environ 60 secondes pour Atlas, téléchargement initial des modèles inclus, puis 14 secondes pour Kaeser. Ce ne sont pas des latences comparables à chaud. Un cache local évite de refaire une conversion identique. Les imports suivants n'autorisent aucun téléchargement de modèle : si les modèles locaux manquent, la lecture brute reste disponible et l'échec structuré est affiché. OCR désactivé dans cette passe.

## Import : correction supplémentaire

Les dates ISO UTC terminées par Z étaient refusées par Python 3.9. L'import les prend désormais en charge sans changer les instants représentés. La cadence, les trous et les doublons restent contrôlés.

## Vérifications

- Trois tests du solveur, avec comparaison exhaustive et contrôle physique indépendant.
- Six tests du parcours serveur renforcés : ils contrôlent aussi l'extraction structurée réelle, le signalement du nombre 181 et l'import UTC.
- Parcours Brave : import du PDF réel, affichage des deux tableaux, simulation, validation, export disponible et invalidation des révisions. Contrôles de largeur à 600 et 2000 pixels, mobile dans une iframe de 390 pixels.

Reproduction : `python3 application/verifier.py`, `.venv-documents/bin/python optimisation/verifier_planning_solveur.py`, puis `node application/verifier-interface.cjs` avec le serveur actif. Les dépendances installées sont consignées dans `evaluation-rag/dependances-documents.txt`.

## Ce qui reste ouvert

Lecture et réponses par LLM, embeddings, évaluation sémantique des conditions, OCR, documents contradictoires, optimisation sur une année, validation physique par un professionnel, preuve de valeur client et autorisations du hackathon. L'intégration d'une bibliothèque ne résout pas ces points à elle seule.
