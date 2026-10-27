function limitedStudyReason(a) {
  const limits={capacite_incoherente:'The battery quotation conflict remains unresolved; this simulation does not validate either quoted capacity.',donnees_preliminaires:'The preliminary specification has not been confirmed for this factory; any machine load remains an assumption.',reserve_prioritaire:'Backup reserve is excluded from this calculation; the result does not validate total battery sizing.',rendement_cycle:'Per-direction efficiency is not established by round-trip efficiency; an explicit input assumption is still required.',sources_contradictoires:'Conflicting sources remain unresolved; any selected input must be reviewed as an explicit assumption.'};
  return 'Run a limited simulation. '+(limits[a.code]||'This document issue remains unresolved; the simulation does not establish site applicability.');
}
/* Findings are existing audit results, never fabricated model claims. */
function findingStory(a,d){
  const names={sources_contradictoires:'Two sources. Two different limits.',capacite_incoherente:'The battery numbers do not add up.',donnees_preliminaires:'This specification is not site-approved.',reserve_prioritaire:'The backup reserve is missing from the model.',rendement_cycle:'One efficiency number hides two steps.'};
  const meanings={sources_contradictoires:'Neither value can be used until the conflicting sources are resolved.',capacite_incoherente:'The quoted usable energy disagrees with the battery’s own operating limit.',donnees_preliminaires:'A preliminary manufacturer sheet is being used for a specific factory. Its applicability still needs confirmation.',reserve_prioritaire:'The documents require energy to be kept for backup. Peak smoothing alone cannot validate the battery size.',rendement_cycle:'Round-trip efficiency covers charging and discharging together. The model needs an assumption for each direction.'};
  const quantity=(proof,unit)=>{const match=(proof?.citation||'').match(new RegExp('(\\d+(?:[.,]\\d+)?)\\s*'+unit,'i'));return match?Number(match[1].replace(',','.')):null};
  let visual='';
  if(a.code==='capacite_incoherente'){
    const nominal=quantity(a.preuves[0],'kWh'),usable=quantity(a.preuves[1],'kWh'),dod=quantity(a.preuves[2],'%');
    if([nominal,usable,dod].every(n=>n!==null))visual=`<div class="finding-equation"><div><strong>${nominal} kWh</strong><small>Nominal capacity</small></div><em>×</em><div><strong>${dod}%</strong><small>Usable share</small></div><em>=</em><div><strong>${Number((nominal*dod/100).toFixed(2))} kWh</strong><small>Calculated usable energy</small></div><div class="quoted"><strong>${usable} kWh</strong><small>But the quotation says</small></div></div>`;
  }else if(a.code==='reserve_prioritaire'||a.code==='rendement_cycle'){
    const amount=quantity(a.preuves[0],'%');
    if(amount!==null)visual=`<div class="finding-equation"><div><strong>${amount}%</strong><small>${a.code==='reserve_prioritaire'?'Required backup reserve':'Round-trip efficiency in the document'}</small></div><em>→</em><div><strong>${a.code==='reserve_prioritaire'?'Not modelled':'Each way?'}</strong><small>${a.code==='reserve_prioritaire'?'Separate sizing still needed':'An explicit assumption is required'}</small></div></div>`;
  }
  const mapped=a.champs?.length?a.champs:a.code==='donnees_preliminaires'?['puissance_kw']:[];
  const held=(a.code==='capacite_incoherente'?[]:mapped).filter(key=>d.extraction_ia?.propositions?.[key]?.valeur_modele===null);
  const fieldNames={plafond_kw:'grid power',puissance_kw:'machine power',puissance_max_kw:'battery power',rendement:'battery efficiency'};
  const action=held.length?`AI left ${held.map(key=>fieldNames[key]||key).join(' and ')} unset.`:'Resolve this before approving the study.';
  const englishFact=(proof)=>{
    const value=quantity(proof,'kWh'),percent=quantity(proof,'%');
    if(a.code==='capacite_incoherente')return proof===a.preuves[0]?`Nominal capacity: ${value} kWh`:proof===a.preuves[1]?`Quoted usable energy: ${value} kWh`:`Maximum depth of discharge: ${percent}%`;
    if(a.code==='reserve_prioritaire')return percent===null?'Battery energy must remain available for backup.':`Keep ${percent}% of usable energy for backup.`;
    if(a.code==='rendement_cycle')return percent===null?'Only round-trip efficiency is specified.':`Round-trip efficiency: ${percent}%.`;
    if(a.code==='donnees_preliminaires')return 'Preliminary specification — factory applicability is not confirmed.';
    const power=quantity(proof,'kW(?!h)');
    return power===null?'Conflicting specification — inspect the original source.':`Stated power limit: ${power} kW`;
  };
  const groups=a.code==='capacite_incoherente'?[[a.preuves[0],a.preuves[2]],[a.preuves[1]]]:a.preuves.length>1?[[a.preuves[0]],[a.preuves[1]]]:[a.preuves];
  const evidence=`<div class="evidence-comparison">${groups.map((proofs,i)=>`<div class="evidence-card"><span class="evidence-caption">${a.code==='capacite_incoherente'?(i?'Quoted usable energy':'Capacity and operating limit'):`Source ${i+1}`}</span>${proofs.filter(Boolean).map(proof=>`<blockquote>${echappe(englishFact(proof))}</blockquote><small>${echappe(d.documents[proof.document]?.nom||proof.nom||'Document')} · line ${proof.ligne}</small>`).join('')}</div>`).join('<span class="evidence-vs" aria-hidden="true">≠</span>')}</div>`;
  return `<div class="finding-head"><h3>${echappe(names[a.code]||uiText(a.message))}</h3></div>${evidence}${visual}<div class="finding-decision"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 3 7v6c0 4 9 8 9 8s9-4 9-8V7zM8 12l3 3 5-6"/></svg><div><strong>${echappe(action)}</strong><p>${echappe(meanings[a.code]||uiText(a.message))}</p></div></div>`;
}
/* Les alertes restent visibles même après une dérogation pour simulation. */
function afficherAudit(d) {
  let zone = document.getElementById('audit-documentaire');
  if (!zone) {
    zone = document.createElement('div');
    zone.id = 'audit-documentaire';
    document.getElementById('faits').before(zone);
  }
  const alertes = [...(d.audit_documentaire?.anomalies || [])].sort((a,b)=>
    Number(b.code==='capacite_incoherente')-Number(a.code==='capacite_incoherente'));
  zone.innerHTML = alertes.length ? `<h3>${alertes.length} decisions needed</h3>` + alertes.map((a,index) => {
      const revue = d.revue_documentaire?.[a.id];
      const reason = limitedStudyReason(a);

      return `<div class="fait alerte-documentaire" data-alerte="${echappe(a.id)}">
      ${findingStory(a,d)}
      <details class="finding-evidence"><summary>Original source</summary>${a.preuves.map(p => `<p class="evidence-ref">${echappe(d.documents[p.document]?.nom||`Document ${p.document+1}`)} · line ${p.ligne}</p><blockquote>${echappe(p.citation)}</blockquote>${boutonPreuve(p.document,p.ligne,p.citation)}`).join('')}</details>
      <details class="detail-alerte"><summary>Choose how to proceed</summary>
      <label for="decision-${echappe(a.id)}">How to proceed</label>
      <select id="decision-${echappe(a.id)}" class="decision-alerte">
      <option value="simulation_limitee">Run a limited simulation</option>
      <option value="non_applicable" ${revue?.decision === 'non_applicable' ? 'selected' : ''}>Not applicable — explain why</option></select>
      <label for="revue-${echappe(a.id)}">Reason and limits</label>
      <textarea id="revue-${echappe(a.id)}" class="motif-alerte" minlength="30" maxlength="2000" placeholder="Explain your decision and its limits (at least 30 characters)." rows="3">${echappe(revue?.motif || reason)}</textarea></details>
      <label><input type="checkbox" class="accord-alerte" ${revue ? 'checked' : ''}><span class="decision-label">${revue?.decision==='non_applicable'?'I confirm this does not apply.':'Continue with a limited simulation; this issue stays unresolved.'}</span></label></div>`;
    }).join('') : '<p><small>No document issues detected. Review the values and sources.</small></p>';
  zone.querySelectorAll('.decision-alerte').forEach(select=>select.addEventListener('change',()=>{
    const row=select.closest('.alerte-documentaire'), area=row.querySelector('.motif-alerte');
    const anomaly=alertes.find(a=>a.id===row.dataset.alerte);
    area.value=select.value==='simulation_limitee'?limitedStudyReason(anomaly):'';
    row.querySelector('.decision-label').textContent=select.value==='simulation_limitee'?'Continue with a limited simulation; this issue stays unresolved.':'I confirm this does not apply.';
    row.querySelector('.detail-alerte').open=true;
    row.querySelector('.accord-alerte').checked=false;
    invalider();window.parcours?.sync();
  }));
  zone.querySelectorAll('input,textarea,select').forEach(e => e.addEventListener('input', () => { if (!e.classList.contains('accord-alerte')) e.closest('.alerte-documentaire').querySelector('.accord-alerte').checked=false; invalider();window.parcours?.sync(); }));
}

function recueillirRevue() {
  const revue = {};
  document.querySelectorAll('.alerte-documentaire').forEach(e => {
    const motif = e.querySelector('.motif-alerte').value.trim();
    if (!e.querySelector('.accord-alerte').checked || motif.length < 30) {
      throw Error('Confirm each decision and provide a reason of at least 30 characters.');
    }
    revue[e.dataset.alerte] = {decision: e.querySelector('.decision-alerte').value, motif};
  });
  return revue;
}
