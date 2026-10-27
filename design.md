# Direction visuelle de Contingency

## Décision de Kusaila, 22 septembre 2026

Refonte complète pour rendre la démonstration compréhensible, avec de grandes étapes. Référence choisie : capture fournie par Kusaila, conservée localement dans `.local/design-reference/reference-ui.png`. Blanc froid, accent bleu électrique, fines bordures et relief discret. Cette référence claire remplace le sombre par défaut pour ce projet.

## Parcours

Quatre étapes numérotées, une seule visible à la fois : dossier, données, simulation, résultat. Les étapes futures sont désactivées tant que leurs conditions ne sont pas réunies. La revue affiche une seule décision à la fois : une valeur avec source, confirmation et édition, puis chaque point à clarifier. Continuer avance, Retour permet de corriger. Aucun récapitulatif dense au niveau principal. Un bandeau de progression conserve l’action principale au même emplacement et indique les entrées ou décisions manquantes. Détails techniques repliés ; résultat raconté avec horaires et énergie avant/après issus des calculs réels. Aucune valeur ni alerte acceptée automatiquement. Les sources et documents restent consultables. Toute modification invalide validation et résultat. Comparaison uniquement entre calculs réels du même dossier.

## Référence et transposition

Reprendre de la capture les surfaces blanches, l’accent bleu lumineux, la précision des séparations et les ombres douces. Les logos de sociétés et les affirmations commerciales de la référence ne font pas partie du produit. Pleine largeur sur desktop, mise en page adaptée au mobile.

## Tokens

- Fond : `--paper: #f8fafc` ; surface `--surface: #ffffff`.
- Texte : `--ink: #1c243b` ; secondaire `--muted: #647087`.
- Accent : `--blue: #3859f5` ; survol `--blue-dark: #2645d5` ; surface `--blue-wash: #edf2ff`.
- Bordures : `--line: #e4e9f2`.
- Alertes : `--red: #a93c48` ; fond `--red-wash: #fff5f5`.
- Rayon principal : `--radius: 18px` ; contrôles 8–10 px.
- Police Figtree variable, hébergée localement avec licence OFL. Corps 16 px, titres 28–66 px, détails 14 px.
- Espacements : 8, 12, 16, 20, 24, 32, 44 px.
- Mouvement : entrée 350 ms, survol 160 ms. Schéma réseau animé, explicitement illustratif sans données inventées. Respect de prefers-reduced-motion.

## Langue et lisibilité

Anglais intégral par défaut, demandé par Kusaila après le premier aperçu. Les faits visibles sont formulés en anglais ; les citations fidèles restent dans leur langue originale uniquement sous « Original source ». Vérifier aussi erreurs, résultats, détails et formats numériques. Légendes des schémas séparées des lignes de connexion.

## Contraintes conservées

Réponse IA archivée annoncée ; données publiques et fictives distinguées ; contrôle humain obligatoire ; réserve de secours hors modèle affichée près des résultats. Pas de nouvelle promesse client ni de gain inventé. Fonctions et API métier conservées.

## Simplification, 23 septembre 2026

Retour Kusaila : supprimer les éléments superflus de la revue. Un seul titre par étape ; aucune sidebar secondaire ni répétition du chiffre dans plusieurs vues. Valeur, Source et Edit suffisent au niveau principal ; la confirmation appartient au bouton principal du parcours. Source ouvre les citations au clic. Réduire aussi les textes, pas seulement le nombre de panneaux : aucune introduction répétée, états inutiles ou sous-titres de navigation. Les décisions gardent un intitulé court ; preuves et explications sont dépliables. Détails techniques à la demande, avec les limites qui affectent la décision toujours visibles.

Retour prioritaire : réduire les informations simultanées, pas seulement les mots. Une décision visible à la fois dans Review, avec progression et retour. Les détails ne se déplient jamais automatiquement. Supprimer entièrement les slogans et pieds de page (« From evidence to options », « Human approval required ») : chaque texte visible doit aider une action ou une décision actuelle.

Les animations et le schéma réseau/usine/batterie sont expressément approuvés par Kusaila. Les conserver pendant la simplification ; alléger les textes et la densité, sans retirer les mouvements appréciés. Respecter prefers-reduced-motion.

Retour prioritaire : ne pas isoler une case Confirm entre les actions secondaires. Le chiffre est suivi de Source et Edit ; le bouton principal « Confirm & continue » accepte explicitement la proposition et avance. Les hypothèses manuelles passent par Continue, puis l’accord global. Vérifier ce regroupement sur desktop et mobile. Nommer explicitement ce que décrit chaque donnée : « New machine runtime per day » pour la durée de la nouvelle machine. Source et Edit restent dans une barre fixe même ouverts ; seul le contenu se déplie dessous. Une hypothèse affiche directement sa justification, sans texte générique répété ni renvoi à Edit.

## Parcours produit et démo, 23 septembre 2026

Retour Kusaila : la valeur à montrer est l’analyse documentaire et le résultat expliqué, pas une succession de chiffres sans contexte. Accueil usine avec profil existant, schéma animé et Add a machine. Référence expressément approuvée par Kusaila après visualisation : les grands chiffres, la courbe, le schéma animé et la table Machines avec puissance, énergie quotidienne et planning sont « excellents, très visuels ». Préserver ce rendu et appliquer sa hiérarchie au reste. Chaque ajout est une étude indépendante ; ne pas présenter les machines simulées comme installées ou les additionner silencieusement au profil. Le préchargement du dossier d’exemple ne doit jamais déverrouiller Review : il faut une machine ajoutée ou sélectionnée, puis une analyse explicitement lancée (ou une revue manuelle choisie). Changer les documents reverrouille la revue. Les quatre problèmes documentaires passent avant les sept entrées. Une contradiction montre le calcul et la citation, avec les décisions détaillées à la demande. Le bouton d’hypothèses de démo reste secondaire, après le problème.

La simulation conserve une présentation animée de 10 secondes minimum, y compris en production, à la demande explicite de Kusaila. Cette durée est une présentation cadencée, pas une mesure du temps de calcul. Montrer le vrai profil de consommation et le schéma de flux approuvé ; ne pas prétendre que Nebius travaille pendant le calcul du solveur. Les échecs sont affichés immédiatement et un calcul plus long reste en attente réelle, sans résultat inventé. Le calcul reste réel. L’extraction de démo est une réponse Kimi archivée via Nebius Token Factory, identifiée dans les détails IA et le rapport ; le timing animé ne mesure jamais une performance IA. Conserver les confirmations et les erreurs réelles. Les résultats expliquent les horaires par la demande existante et la durée de dépassement avant batterie, avec un graphique visible. Interface et exports lisibles en anglais ; aucune action d’export « French ». Les citations originales restent fidèles.

Retour prioritaire, même session : supprimer les microtextes de fabrication et de contexte qui encombrent le produit (« Local calculation · paced demo playback », « Amsterdam · Demo factory », « Document analysis · model proposals + source checks »). Aucun nouveau texte de ce genre. Retirer aussi le bandeau « Demo · Recorded AI / Details ». Le statut réel du modèle et les informations de démo restent dans les détails IA de la revue et le rapport, sans qualifier le rejeu d’appel en direct. Pour une analyse indisponible, retirer le paragraphe rouge explicatif : état accessible discret, bouton « Retry analysis » et accès à la revue manuelle. Ne jamais transformer un échec en succès apparent. Un nombre de documents sans rôle ni accès n’explique rien : montrer contrat réseau, spécifications et consommation dans une étape documents identifiable. L’accueil doit présenter les machines saisies, puissance, énergie quotidienne et horaires, avec ajout + ; préserver la distinction entre données existantes agrégées et nouvelles machines simulées.

## Findings for judges, 23 September 2026

Make the model contribution inspectable: opposing source excerpts side by side, the exact conflict, and which proposed value the model withheld. Keep this visual and compact. Distinguish model-detected issues from deterministic checks; never describe a local arithmetic rule as a fine-tuned model capability. Put model identity and training status in details, not decorative banners.

Retour sur les contrôles : permettre la saisie directement dans la carte de valeur ; une valeur saisie devient une hypothèse, jamais une fausse citation. Les valeurs d’exemple remplissent seulement les champs manquants, y compris la puissance de la machine déjà créée, et produisent un retour visible. Une confirmation ne doit pas rester bloquée par une justification cachée : proposer une portée de simulation explicite, laisser les autres décisions demander leur raison. Pendant l’analyse réelle, montrer la liste effective des documents et les phases reçues du serveur ; ne pas inventer de progression document par document pour un appel qui traite tout ensemble.

Première visite des juges : une seule carte d’accueil, courte, avec une usine fictive, une machine et des documents proposés. Le bouton ouvre directement le dossier d’une nouvelle étude, sans appel IA automatique ni approbation implicite. L’utilisateur choisit ensuite de lancer l’analyse ou de remplacer les documents. Un petit dialogue doit s’ouvrir automatiquement à la première visite, y compris sur /demo en navigation privée : un simple encart dans le dashboard ne constitue pas un onboarding assez visible (retour Kusaila du 23/09). Deux choix seulement : Explore sample et View factory ; Échap ferme aussi le dialogue. Le choix est mémorisé localement. Vérifier le rendu public dans une vraie fenêtre privée, pas uniquement le DOM simulé.

Soumission jury : description produit courte et sécurité rassurante en deux phrases, fondée sur les protections réelles. Détailler les étapes dans le champ modèles et comparer explicitement qualité, latence, contrôle et adaptation dans le champ avantage mesurable ; ne pas inventer un coût non vérifié. Éviter préambules et accumulation de réserves. Kusaila interdit les tirets cadratins dans les textes rédigés pour lui.

## Fiabilité de l’analyse, 23 septembre 2026

Retour Kusaila après le jury : une attente de 74 secondes suivie d’un échec apparent est inacceptable. Mesurer le vrai dossier complet, pas seulement les petits cas. Le réglage de raisonnement du modèle fait partie de la configuration évaluée et de la clé de cache. Les coupures de suivi ne doivent pas perdre un résultat encore calculé côté serveur : reprise du même travail, POST idempotent et nouvelles tentatives limitées sur erreurs réseau temporaires. Aucun résultat archivé ne remplace silencieusement une analyse réelle en échec. Vérifier le passage effectif Documents vers Review sur le lien public.
