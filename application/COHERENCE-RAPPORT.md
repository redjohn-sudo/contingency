# Contrôle de cohérence du rapport

Adaptation du principe de PIPE Zurich : la restitution doit respecter les résultats numériques, et une incohérence doit rester visible. Aucun code ni modèle acoustique de l'équipe n'a été copié. Le rapport Amsterdam est déterministe ; aucun contrôle de texte libre d'un LLM n'est revendiqué.

`coherence.py` reconstruit la charge avec les départs retenus et recalcule sa capacité par le moteur existant. Il vérifie la révision, les fenêtres, le nombre de départs, le statut, la capacité et les résidus physiques. Le rapport est suspendu si ces éléments se contredisent. Les résultats bruts sont conservés ; le JSON exporté ajoute `controle_rapport` et son recalcul.

Conclusions possibles :

- Planning réalisable, sans optimalité prouvée.
- Planning optimal dans le modèle discret, seulement si départs, capacité, objectif et borne du solveur concordent.
- Planning testé infaisable, sans conclusion sur tous les plannings.
- Infaisabilité dans le modèle lorsqu'un certificat existe : puissance de base trop élevée, énergie minimale supérieure à l'apport réseau maximal sur le cycle, ou statut infaisable du solveur.
- Calcul non résolu, distinct d'une impossibilité.
- Conclusion suspendue pour incohérence.

La faisabilité d'une heuristique recalculée reste utilisable si l'optimiseur expire. Une erreur explicite de contrôle physique du solveur suspend la conclusion. La tolérance physique est de 1e-5, cohérente avec le contrôle LP existant ; la concordance capacité/objectif/borne est vérifiée à 1e-4 kWh. La puissance et l'énergie des certificats conservateurs utilisent une marge de 1e-6 dans leurs unités respectives.

Le rapport nomme la capacité minimale du planning retenu, affiche le pic réseau recalculé et l'empreinte SHA-256 du résultat brut. Il n'utilise plus le texte libre du champ `methode` comme conclusion. La génération répétée depuis le même dossier produit le même rapport Markdown.

Validation : vingt-deux tests application réussis, comprenant treize tests de cohérence et un parcours HTTP de résultat altéré, export brut préservé et conclusion suspendue. Aucun appel API ni entraînement. La relecture du solveur par Claude du bureau est tracée dans le bus, messages 499 à 502 et suivants.

Limites : le recalcul utilise le moteur existant, pas une seconde implémentation indépendante. Le contrôle n'établit ni exactitude des documents, ni pertinence physique des hypothèses sur site, ni économies réelles. Les empreintes assurent la traçabilité, pas une signature de sécurité. Le contrôle s'applique au rapport Markdown et à son export JSON ; il ne transforme pas l'interface en système certifié.

Échanges de revue : Claude confirme les règles et les choix de tolérance (bus 503). Ses objections de mise en page, import autonome et classement des exceptions moteur ont été corrigées ; tests de rédaction et déterminisme ajoutés (bus 504).
