/* Variations déclarées, exécutées localement après validation du dossier. */
function afficherSensibilite() {
  document.getElementById('sensibilite')?.remove();
  if (dossier.resultat?.retenu?.statut !== 0) return;
  const t = textePreuve;
  const zone = document.createElement('details');
  zone.id = 'sensibilite';
  zone.innerHTML = `<summary>${t('Tester la sensibilité du planning', 'Test schedule sensitivity')}</summary>
    <p>${t('Le planning machine reste identique. Chaque scénario recalcule la commande batterie et son besoin de lissage. Choisissez des variations exploratoires, pas une marge de sécurité certifiée.',
      'The machine schedule stays unchanged. Each scenario recalculates battery dispatch and peak-smoothing capacity. Choose exploratory variations, not a certified safety margin.')}</p>
    <div class="grille"><div><label for="variation-charge">${t('Variation du profil de base, ± % (0 à 50)', 'Base load variation, ± % (0 to 50)')}</label>
      <input id="variation-charge" type="number" min="0" max="50" step="any" value="10"></div>
    <div><label for="variation-plafond">${t('Variation du plafond, ± kW (0 pour conserver)', 'Grid cap variation, ± kW (0 to keep unchanged)')}</label>
      <input id="variation-plafond" type="number" min="0" step="any" value="0"></div></div>
    <small>${t('10 % est un exemple à justifier, pas une incertitude mesurée. La puissance de la machine ajoutée reste constante. Les variations ne sont pas combinées.',
      '10% is an example to justify, not measured uncertainty. Added machine power stays constant. Variations are not combined.')}</small>
    <label for="motif-sensibilite">${t('Pourquoi tester ces variations ?', 'Why test these variations?')}</label>
    <textarea id="motif-sensibilite" minlength="15" maxlength="2000" rows="2"></textarea>
    <label><input id="accord-sensibilite" type="checkbox">${t('Je confirme ces hypothèses exploratoires pour la révision validée.', 'I confirm these exploratory assumptions for the approved revision.')}</label>
    <button id="calculer-sensibilite" type="button" disabled>${t('Comparer ces scénarios', 'Compare these scenarios')}</button>
    <p class="etat-sensibilite" role="status"></p><div class="resultats-sensibilite" hidden></div>`;
  document.getElementById('rapport-lisible').before(zone);
  const accord = zone.querySelector('#accord-sensibilite'), bouton = zone.querySelector('#calculer-sensibilite');
  const etat = zone.querySelector('.etat-sensibilite'), resultats = zone.querySelector('.resultats-sensibilite');
  let generation = 0;
  zone.querySelectorAll('input,textarea').forEach(entree => entree.addEventListener('input', () => {
    generation++;
    if (entree !== accord) accord.checked = false;
    bouton.disabled = !accord.checked;
    resultats.hidden = true;
    etat.textContent = '';
  }));
  bouton.onclick = async () => {
    const id = dossier.id, revision = dossier.revision, demande = ++generation;
    bouton.disabled = true;
    etat.textContent = t('Calcul local en cours…', 'Local calculation running…');
    etat.classList.remove('erreur');
    try {
      const charge = zone.querySelector('#variation-charge').value;
      const plafond = zone.querySelector('#variation-plafond').value;
      if (!charge.trim() || !plafond.trim()) throw Error(t('Renseignez les deux variations.', 'Enter both variations.'));
      const reponse = await appel(`/api/${id}/sensibilite`, {revision, hypotheses: {
        variation_charge_pct: Number(charge), variation_plafond_kw: Number(plafond),
        motif: zone.querySelector('#motif-sensibilite').value, validation: accord.checked}});
      if (dossier.id !== id || dossier.revision !== revision || demande !== generation) return;
      dossier.sensibilite = reponse.sensibilite;
      const nombre = valeur => Number(valeur).toLocaleString(t('fr-FR', 'en-GB'), {maximumFractionDigits: 2});
      const noms = {reference: t('Référence', 'Baseline'), charge_basse: t('Charge réduite', 'Lower load'),
        charge_haute: t('Charge accrue', 'Higher load'), plafond_bas: t('Plafond réduit', 'Lower grid cap'), plafond_haut: t('Plafond accru', 'Higher grid cap')};
      const raisons = {'Puissance de décharge insuffisante': t('Puissance de décharge insuffisante', 'Insufficient discharge power'),
        'Énergie de recharge insuffisante sur le cycle': t('Énergie de recharge insuffisante sur le cycle', 'Insufficient recharge energy over the cycle')};
      const besoin = s => s.calcul.statut === 0 ? nombre(s.calcul.capacite_utile_kwh) : s.calcul.statut === 2 ?
        `${t('Irréalisable pour ce planning', 'Infeasible for this schedule')}<small>${echappe(raisons[s.calcul.message] || s.calcul.message)}</small>` : t('Non résolu', 'Unresolved');
      resultats.innerHTML = `<div class="tableau" tabindex="0" role="region" aria-label="${t('Comparaison des scénarios, défilement horizontal possible', 'Scenario comparison, scroll horizontally if needed')}"><table><thead><tr><th>${t('Scénario', 'Scenario')}</th><th>${t('Profil', 'Load')}</th><th>${t('Plafond kW', 'Grid cap kW')}</th><th>${t('Lissage kWh', 'Peak smoothing kWh')}</th><th>${t('Capacité de référence suffisante ?', 'Is baseline capacity sufficient?')}</th></tr></thead><tbody>` +
        reponse.sensibilite.scenarios.map(s => `<tr><th scope="row">${noms[s.nom]}</th><td>${s.variation_charge_pct > 0 ? '+' : ''}${nombre(s.variation_charge_pct)} %</td><td>${nombre(s.plafond_kw)}</td><td>${besoin(s)}</td><td>${s.capacite_reference_suffisante === null ? t('Non résolu', 'Unresolved') : s.capacite_reference_suffisante ? t('Oui, commande adaptée', 'Yes, adapted dispatch') : t('Non', 'No')}</td></tr>`).join('') +
        `</tbody></table></div><p>${t('Demande connue à l’avance, état initial libre et cyclique dans chaque scénario. Pas de politique commune robuste. Réserve de secours exclue. Ces résultats sont ajoutés au rapport.',
          'Perfect foresight and a free cyclic initial state in each scenario. No shared robust policy. Backup reserve excluded. These results are added to the report.')}</p>`;
      resultats.hidden = false;
      etat.textContent = t('Comparaison calculée sur la révision validée.', 'Comparison calculated for the approved revision.');
    } catch (erreur) {
      if (demande !== generation) return;
      etat.textContent = erreur.message;
      etat.classList.add('erreur');
    } finally {
      bouton.disabled = !accord.checked;
    }
  };
}
