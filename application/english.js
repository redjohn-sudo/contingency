/* English presentation only: never rewrite source documents, citations or user inputs. */
(() => {
const translations = {
  "Contingency : vérifier les contraintes avant de calculer.": "Contingency: check the inputs before calculating.",
  "Contingency · Étude de capacité réseau": "Contingency | Grid capacity study",
  "Contingency, démonstration hors ligne.": "Contingency, offline demonstration.",
  "Réponse Kimi réelle enregistrée le 22 septembre. Aucun appel IA en direct. Dossier construit et profil fictif. Validation et calcul exécutés localement.": "Recorded walkthrough (Kimi K3, September 22). Live analysis on this site uses DeepSeek V4.1 Flash via Nebius. Constructed dossier and simulated profile; review and calculation run locally.",
  "Vos documents deviennent des propositions sourcées. Vérifiez les points à clarifier, puis comparez les simulations.": "Your documents become proposed inputs with sources. Review the open questions, then compare simulations.",
  "Préparation d’étude : les propositions restent à vérifier avant calcul.": "Study preparation: proposed inputs require review before calculation.",
  "1. Ouvrir le dossier de démonstration": "1. Open the demonstration dossier",
  "Neuf pièces : textes archivés de quatre PDF publics et cinq pièces de site fictives. Le profil de consommation est simulé.": "Nine documents: archived text from four public PDFs and five constructed site documents. Simulated load profile.",
  "Ouvrir le dossier de démonstration": "Open the demonstration dossier",
  "La réponse Kimi est enregistrée. Les calculs seront exécutés sur cette machine.": "Recorded Kimi response. Calculations run on this machine.",
  "2. Relire les propositions, décider des hypothèses": "2. Review the proposed inputs and assumptions",
  "Documents et contexte du dossier": "Documents and dossier context",
  "Le modèle propose les valeurs avec leurs sources. Retenez celles que vous avez vérifiées ; les valeurs bloquées demandent une clarification ou une hypothèse explicite.": "The model proposes values with their sources. Keep the ones you have checked; blocked values need clarification or an explicit assumption.",
  "Revoir la réponse Kimi enregistrée": "Review the recorded Kimi response",
  "Réponse déjà enregistrée. Aucun envoi externe dans ce mode.": "Previously recorded response. No external requests in this mode.",
  "Ce que les documents permettent de proposer": "Inputs proposed from your documents",
  "Lecture du modèle et contrôles": "Model response and checks",
  "Plafond réseau": "Grid cap",
  "Puissance maximale batterie": "Maximum battery power",
  "Rendement par sens": "Per-direction efficiency",
  "Puissance de la machine ajoutée": "Added machine power",
  "Durée consécutive par bloc de 24 h": "Consecutive runtime per 24-hour block",
  "Début autorisé dans le bloc": "Earliest start within the block",
  "Fin obligatoire dans le bloc": "Required end within the block",
  "À clarifier": "Needs review",
  "Preuve insuffisante ou valeur bloquée": "Insufficient evidence or blocked value",
  "Voir les preuves et le contrôle": "See the evidence and the check",
  "Retenir cette valeur après lecture de sa source": "Keep this value after reading its source",
  "Proposition bloquée : clarification nécessaire": "Blocked proposal: clarification required",
  "Valeurs retenues pour cette simulation": "Selected inputs for this simulation",
  "Préremplir les hypothèses de démonstration": "Prepare the demonstration assumptions",
  "Trois valeurs de simulation et les motifs de revue sont préparés. Aucune proposition ni alerte n’est validée par ce bouton.": "Prepares three simulation assumptions and review reasons. This button does not approve any proposal or alert.",
  "Ouvrez chaque point pour lire ses preuves et motiver votre décision. Les alertes restent dans le rapport.": "Open each issue to read its evidence and explain your decision. Alerts remain in the report.",
  "Capacité utile incompatible avec capacité nominale × profondeur de décharge. Périmètre et fournisseur à confirmer.": "Usable capacity conflicts with nominal capacity × depth of discharge. Confirm the scope with the supplier.",
  "Document générique ou préliminaire : confirmer son application au site.": "Generic or preliminary document: confirm that it applies to this site.",
  "Une réserve obligatoire est déclarée. Le modèle actuel ne représente pas cette obligation.": "A mandatory backup reserve is stated. The current model does not include it.",
  "Un rendement aller-retour ne définit pas le rendement par sens utilisé par le modèle.": "Round-trip efficiency does not establish the per-direction efficiency used by this model.",
  "Décision après lecture des sources": "Decision after reviewing the sources",
  "Simuler sous une hypothèse explicite": "Simulate under an explicit assumption",
  "Déclarer cette alerte non applicable, avec justification": "Declare this alert not applicable, with justification",
  "Justification, sources vérifiées et limites": "Reason, reviewed sources and limits",
  "J’ai vérifié les sources et motivé cette décision. L’alerte reste au rapport.": "I have reviewed the sources and explained this decision. The alert stays in the report.",
  "À renseigner": "Not selected",
  "Aucune valeur retenue.": "No value selected.",
  "Hypothèse explicite, à valider.": "Explicit assumption, still to approve.",
  "Corriger la valeur, la source ou l’hypothèse": "Edit the value, source or assumption",
  "Hypothèse à justifier": "Assumption requiring a reason",
  "Ligne source": "Source line",
  "Justification / correction": "Reason / correction",
  "Hypothèse explicitement déclarée.": "Explicitly declared assumption.",
  "Préparer la validation": "Prepare for approval",
  "3. Valider cette simulation": "3. Approve this simulation",
  "Un cycle machine par bloc de 24 heures. Les horaires désignent des positions dans ce bloc, pas un calendrier de travail vérifié. Batterie à rendement constant, état initial libre et cyclique. Une recherche conjointe est tentée sur les dossiers de sept blocs maximum. Le rapport indique si l’optimalité est prouvée dans ce modèle.": "One machine cycle per 24-hour block. Times are positions within that block, not a verified work calendar. Constant battery efficiency and a free, cyclic initial state. Joint optimisation is attempted for up to seven blocks. The report states whether optimality was proved within this model.",
  "J’ai vérifié les valeurs, leurs sources et les hypothèses pour cette simulation.": "I have reviewed the values, sources and assumptions for this simulation.",
  "Calculer les scénarios": "Calculate the scenarios",
  "4. Résultat de simulation": "4. Simulation result",
  "Capacité utile pour le lissage des pointes dans le modèle déclaré.": "Usable capacity for peak smoothing within the stated model.",
  "Comparer les simulations": "Compare the simulations",
  "Simulation précédente": "Previous simulation",
  "Simulation actuelle": "Current simulation",
  "kWh de lissage": "kWh for peak smoothing",
  "Deux calculs exécutés après validation explicite. Réserve de secours non modélisée : zéro lissage ne signifie pas zéro batterie.": "Two calculations after explicit approval. Backup reserve excluded: zero peak smoothing does not mean no battery.",
  "Planning, courbes et portée du calcul": "Schedule, curves and calculation scope",
  "Départ au début de la fenêtre": "Start at the earliest allowed time",
  "Planning retenu": "Selected schedule",
  "Ouvrir le rapport": "Open the report",
  "Version Markdown": "Markdown version",
  "Télécharger les données": "Download the data",
  "Calcul de stockage cyclique avec contrôle physique. Préparation préexistante à déclarer au hackathon.": "Cyclic storage calculation with a physical consistency check. Pre-existing preparation to declare at the hackathon.",
  "Traitement en cours…": "Processing…",
  "Source": "Source",
  "Constituer le dossier": "Build your study dossier",
  "Rassemblez le contrat du site, les fiches techniques et les mesures de consommation.": "Bring together the site contract, equipment specifications and measured power demand.",
  "Documents PDF ou TXT": "PDF or TXT documents",
  "Consommation au fil du temps (CSV)": "Power demand over time (CSV)",
  "Ouvrir le dossier": "Open the dossier",
  "Essayer le cas fictif": "Try the sample study",
  "L’exemple décrit une journée fictive. Aucun fichier n’est envoyé à un service externe.": "The sample describes a fictional day. No files are sent to an external service.",
  "20 documents maximum, 5 Mio chacun. CSV : fin_intervalle,puissance_kw, une mesure toutes les 15 minutes, journées complètes de 96 mesures.": "Up to 20 documents, 5 MiB each. CSV columns: fin_intervalle,puissance_kw. One reading every 15 minutes, in complete days of 96 readings.",
  "Lire les documents avec Nebius": "Read documents with Nebius",
  "Le texte complet des documents est envoyé à Nebius pour comparer les sources. Aucune proposition n’est appliquée sans votre acceptation.": "Document text is sent to Nebius to compare the sources. No proposed value is applied without your approval.",
  "Ouvrir le PDF original": "Open the original PDF",
  "Lecture OCR à vérifier sur le PDF original. Des lignes entières peuvent manquer, même avec de bons scores de lecture.": "Compare the recognised text with the original PDF. Entire lines may be missing, even when reading confidence is high.",
  "Valeur issue d’un scan : comparer les chiffres au PDF original avant de la retenir.": "Read from a scan: compare the numbers with the original PDF before accepting this value.",
  "Un horaire contient des chiffres séparés : vérifier le document original avant simulation.": "A time contains separated digits. Check the original document before simulating.",
  "Aucune alerte détectée par les règles locales. Les valeurs, les conditions et les sources restent à vérifier.": "No issue detected by the local checks. Values, conditions and sources still require review.",
  "Non réalisable": "Not feasible",
  "Valeurs identiques ; sources ou hypothèses de revue modifiées.": "Same values; the sources or review assumptions have changed.",
  "Pourquoi le planning change le besoin de stockage": "How the schedule changes the battery requirement",
  "Demande électrique avant stockage, premier bloc de 24 heures. Les dépassements du plafond doivent être couverts par le stockage dans ce scénario.": "Power demand before battery action, first 24-hour block. Demand above the grid limit must be covered by storage in this scenario.",
  "Demande électrique selon le planning": "Power demand by schedule",
  "Capacité utile théorique, pas capacité commerciale. Aucune économie financière ou de temps humain mesurée. Une éventuelle preuve d’optimalité reste limitée au modèle déclaré.": "Theoretical usable capacity, not a commercial battery size. No financial or human time savings have been measured. Any optimality proof applies only to the stated model.",
  "valeur et unité contrôlées sur la ligne complète, portée à vérifier": "Value and unit checked against the complete source line; applicability still needs review",
  "revue documentaire requise, proposition bloquée": "Document review required; this proposal is blocked",
  "aucune valeur proposée": "No value proposed",
  "Information absente ou non arbitrée.": "Information missing or unresolved.",
  "source générique ou préliminaire, application au site à confirmer": "Generic or preliminary source; applicability to the site must be confirmed",
  "proposition bloquée": "proposal blocked",
  "Justifier l’hypothèse": "Explain the assumption",
  "Justifier la correction de la valeur source": "Explain the correction to the source value",
  "Valeur non établie par sa source": "The source does not establish this value",
  "Justifiez précisément une hypothèse de simulation (30 caractères minimum).": "Explain the simulation assumption precisely (at least 30 characters).",
  "Renseignez toutes les valeurs.": "Enter all values before continuing.",
  "Chaque alerte nécessite une décision expliquée et une acceptation explicite pour cette simulation.": "Review every open question, explain your decision and tick its approval box before continuing.",
  "Choisissez les documents et le profil CSV.": "Choose the documents and the demand CSV file.",
  "Limite de 5 Mio par fichier.": "Each file must be no larger than 5 MiB.",
  "Traitement impossible": "Unable to process this request",
  "Failed to fetch": "Connection lost. Check that the local server is running and try again.",
  "Tous les paramètres doivent être renseignés.": "All inputs must be filled in.",
  "Le rendement par sens doit être compris entre 0 exclu et 1 inclus.": "Per-direction efficiency must be greater than 0 and no greater than 1.",
  "Horaires attendus par multiples de 15 minutes.": "Times must use 15-minute intervals.",
  "La durée ne tient pas dans la fenêtre autorisée.": "The required runtime does not fit within the allowed time window.",
  "CSV attendu : fin_intervalle,puissance_kw (puissance moyenne en kW).": "Expected CSV columns: fin_intervalle,puissance_kw (average power in kW).",
  "CSV attendu : fin_intervalle,puissance_kw, deux colonnes uniques (puissance moyenne en kW).": "Expected CSV columns: fin_intervalle,puissance_kw, two unique columns (average power in kW).",
  "CSV attendu sous forme de texte.": "The CSV must be provided as text.",
  "Horodatage sans fuseau : préciser le décalage UTC ou utiliser l’import configuré.": "Timestamp has no time zone: provide a UTC offset or use the configured import.",
  "Horodatage hors d’un quart d’heure exact.": "The timestamp is not on an exact quarter-hour boundary.",
  "Horodatage hors de la plage de dates prise en charge.": "Timestamp is outside the supported date range.",
  "Horodatage attendu sous forme de date et heure ISO.": "Timestamp must be an ISO date and time.",
  "Le profil doit avoir un pas régulier de 15 minutes, sans trou ni doublon, dans l’ordre UTC.": "The profile must have regular 15-minute intervals in UTC order, with no gaps or duplicates.",
  "Rien n'a été comblé ni supprimé : corriger l'export ou fournir la période manquante.": "Nothing was filled in or removed: correct the export or provide the missing period.",
  "Rien n'a été comblé ni supprimé : corriger l'ordre ou les doublons de l'export.": "Nothing was filled in or removed: correct the order or the duplicates in the export.",
  "Export irrégulier : trou, doublon ou pas différent de 15 minutes. Les changements d’heure doivent inclure le fuseau ou un décalage UTC.": "Irregular export: gap, duplicate or step other than 15 minutes. Clock changes must include the time zone or a UTC offset.",
  "Puissance illisible : le CSV canonique attend un nombre avec point décimal, en kW.": "Invalid power: the prepared CSV requires a number with a decimal point, in kW.",
  "Profil trop long : au maximum 366 jours de quarts d’heure.": "Profile is too long: at most 366 days of quarter-hour readings.",
  "Profil attendu : blocs complets de 96 mesures, au maximum 366 blocs.": "The demand profile must contain complete blocks of 96 readings, up to 366 blocks.",
  "Profil attendu : au moins un jour et au plus 366 jours de quarts d’heure.": "The demand profile must cover at least one day and at most 366 days of quarter-hours.",
  "Le profil doit avoir un pas régulier de 15 minutes, sans trou ni doublon.": "The demand profile must use regular 15-minute intervals, with no gaps or duplicates.",
  "Puissance du profil invalide (0 à 10 millions de kW).": "Invalid demand value: expected 0 to 10 million kW.",
  "Valeurs négatives dans le profil : import refusé. Elles peuvent venir d'un export qui mêle consommation (afname) et injection (teruglevering), d'une convention de signe inversée ou d'une anomalie de mesure. Vérifier le canal exporté et sa convention de signe avant de réimporter.": "Negative values in the profile: import refused. They may come from an export that mixes consumption (afname) and feed-in (teruglevering), from an inverted sign convention or from a measurement anomaly. Check the exported channel and its sign convention before importing again.",
  "Document source inconnu": "Unknown source document",
  "Ligne source absente ou vide": "Missing or empty source line",
  "Valeur numérique manquante": "Missing numeric value",
  "Valeur invalide": "Invalid value",
  "Choisissez une ligne source non vide.": "Choose a non-empty source line.",
  "Proposition Nebius acceptée après vérification humaine.": "Nebius proposal accepted after human review.",
  "Planning optimal dans le modèle déclaré (OR-Tools/SCIP)": "Optimal schedule within the stated model (OR-Tools/SCIP)",
  "Planning réalisable OR-Tools/SCIP, optimalité non prouvée": "Feasible OR-Tools/SCIP schedule; optimality not proven",
  "Stratégie de référence": "Baseline strategy",
  "non testé": "not tested",
  "non testée": "not tested",
  " Étude de capacité réseau": " Grid capacity study",
  "Imprimer ou enregistrer en PDF": "Print or save as PDF",
  "Télécharger la version Markdown": "Download Markdown version",
  "Étude de capacité réseau": "Grid capacity study",
  "Résultat de simulation": "Simulation result",
  "Alertes documentaires maintenues": "Unresolved document issues",
  "Paramètres vérifiés par l’utilisateur": "User-reviewed inputs",
  "Paramètre": "Input",
  "Valeur": "Value",
  "Portée": "Scope",
  "Recherche du planning": "Schedule search",
  "Traçabilité": "Traceability",
  "Conclusion issue du contrôle déterministe du planning.": "Conclusion from the deterministic schedule check.",
  "Simulation exploratoire. Les alertes et les décisions déclarées par l’utilisateur sont conservées ci-dessous. Les motifs ne constituent pas une vérification indépendante. Ce résultat ne valide pas la faisabilité du site.": "Exploratory simulation. The issues and declared user decisions are retained below. These reasons are not an independent verification. This result does not establish site feasibility.",
  "La capacité calculée concerne le lissage dans le modèle déclaré. La réserve de secours obligatoire n’est pas modélisée : un besoin de lissage nul ne signifie pas qu’aucune batterie ne serait nécessaire sur le site.": "The calculated capacity covers peak smoothing in the stated model. Mandatory backup reserve is not modelled: zero peak smoothing does not mean the site needs no battery.",
  "Hypothèse déclarée": "Declared assumption",
  "Demande connue à l’avance. Pas de 15 minutes, puissance moyenne. Un cycle machine par bloc de 24 heures, sans jours exclus. Rendement constant par sens. État initial du stockage libre et cyclique. Pas de vieillissement, de démarrages, de tarifs ni de contraintes de personnel. Les stratégies de référence sont heuristiques. Une preuve d’optimalité OR-Tools ne vaut que dans ce modèle discret et aux tolérances du solveur. Un échec des heuristiques ne prouve pas que tout planning est impossible.": "Demand is known in advance. Average power at 15-minute intervals. One machine cycle per 24-hour block, with no excluded days. Constant efficiency in each direction, free and cyclic initial battery state. Ageing, startup transients, tariffs and staffing constraints are excluded. Baselines use heuristic methods. Any OR-Tools optimality proof applies only within this discrete model and solver tolerances. Failure of a heuristic does not prove all schedules are infeasible.",
  "Optimalité uniquement si le solveur la certifie dans le modèle déclaré. Recherche conjointe limitée à sept blocs et quatre secondes ; au-delà, les stratégies de référence sont utilisées.": "Optimality is claimed only when certified by the solver within the stated model. Joint search is limited to seven blocks and four seconds; beyond these limits, baseline strategies are used.",
  "Cette décision documentaire ne valide ni la faisabilité ni les pièces.": "This document-level decision validates neither site feasibility nor the source documents.",
  "REJEU DE RÉPONSE ENREGISTRÉE, PAS UN APPEL EN DIRECT.": "RECORDED RESPONSE REPLAY, NOT A LIVE CALL.",
  "reserve_prioritaire": "backup_reserve",
  "sources_contradictoires": "conflicting_sources",
  "unites_ambigues": "ambiguous_units",
  "donnees_preliminaires": "preliminary_data",
  "document_generique": "generic_document",
  "rendement_cycle": "round_trip_efficiency",
  "capacite_incoherente": "inconsistent_capacity",
  "Notation numérique à confirmer : séparateur décimal ou de milliers. Aucune conversion automatique.": "Confirm whether the separator is decimal or thousands. No automatic conversion is applied.",
  "La pression de fonctionnement du site manque pour choisir une puissance parmi les conditions fabricant.": "The site operating pressure is missing. It is needed to select power for the appropriate manufacturer conditions.",
  "Le plafond actif déclaré dépasse la capacité apparente citée : vérifier le périmètre et les limites physiques.": "The declared active-power limit exceeds the quoted apparent-power capacity. Check scope and physical limits.",
  " : plusieurs valeurs ou conditions dans le dossier ; aucune priorité automatique.": ": multiple values or conditions occur in the dossier; no priority is selected automatically.",
  " : les pièces ne désignent pas toutes le même site ou leur portée est inconnue.": ": the documents do not all refer to the same site, or their scope is unknown.",
  "Une instruction adressée au modèle est ignorée comme preuve numérique.": "Instructions addressed to the model are ignored as numeric evidence."
};
const pieces = Object.entries(translations).sort((a,b)=>b[0].length-a[0].length);
function text(value) {
 let output=String(value);
 if(translations[output])return translations[output];
 for(const [fr,en] of pieces)if(fr.length>16&&output.includes(fr))output=output.split(fr).join(en);
 return output.replace(/^(\d+) valeurs proposées$/, '$1 proposed values')
 .replace(/^Horodatage (\d+) invalide : /, 'Invalid timestamp $1: ')
 .replace(/^Colonne vide, absente ou en trop dans le CSV, ligne (\d+)\.$/, 'Empty, missing or extra CSV column at row $1.')
 .replace(/^CSV mal formé : /, 'Malformed CSV: ')
 .replace(/^(\d+) valeurs à clarifier$/, '$1 values requiring review')
 .replace(/^(\d+) points à clarifier avant simulation$/, '$1 issues to review before simulation')
 .replace(/^(\d+) \/ (\d+) paramètres renseignés\. La validation reste à faire\.$/, '$1 / $2 inputs entered. Approval still required.')
 .replace(/, ligne (\d+)/g, ', line $1').replace(/^Valeur \(/, 'Value (')
 .replace(/citation retrouvée/g,'citation found').replace(/preuve refusée/g,'evidence rejected')
 .replace(/Cycle machine retenu : (.*?) à (.*?) h\. Courbes de demande, pas de flux réseau après action de la batterie\./,'Selected machine cycle: $1 to $2 h. Demand curves, not grid flow after battery action.')
 .replace(/Tableau reconstruit, page (\d+)/g,'Reconstructed table, page $1')
 .replace(/Trouvé : /,'Found: ').replace(/(\d+) trous? \((\d+) quarts manquants au total\)/,'$1 gap(s) ($2 missing quarter-hours in total)')
 .replace(/(\d+) doublons?(?=[,.])/,'$1 duplicate(s)').replace(/(\d+) retours? en arrière(?=[,.])/,'$1 step(s) back in time')
 .replace(/Premiers cas : /,'First cases: ').replace(/(^|\. )Cas : /,'$1Case: ')
 .replace(/trou de (\d+) quarts entre les lignes (\d+) et (\d+), après (\S+)/g,'gap of $1 quarter-hours between lines $2 and $3, after $4')
 .replace(/doublon aux lignes (\d+) et (\d+) \(([^)]+)\)/g,'duplicate at lines $1 and $2 ($3)')
 .replace(/retour en arrière entre les lignes (\d+) et (\d+) \((\S+) puis (\S+)\)/g,'step back between lines $1 and $2 ($3 then $4)')
 .replace(/ ; (\d+) autres? cas/,'; $1 more case(s)');
}
window.uiText=text;
function translate(){
 document.documentElement.lang='en';
 const walker=document.createTreeWalker(document.querySelector('main')||document.body,NodeFilter.SHOW_TEXT);let node;
 while(node=walker.nextNode()){
  if(node.parentElement.closest('script,style,pre,blockquote,textarea,input,.original-content,#nature'))continue;
  const original=node.nodeValue,clean=original.trim();if(!clean)continue;
  let translated=text(clean);
  if(node.parentElement.closest('.valeur,.comparaison-chiffres,.valeur-proposee,.fait-retenu'))translated=translated.replace(/(\d),(\d)/g,'$1.$2');
  if(translated!==clean)node.nodeValue=original.replace(clean,translated);
 }
 document.querySelectorAll('[data-en]').forEach(el=>{if(el.textContent!==el.dataset.en)el.textContent=el.dataset.en});
}
translate();new MutationObserver(translate).observe(document.querySelector('main')||document.body,{subtree:true,childList:true,characterData:true});
})();
