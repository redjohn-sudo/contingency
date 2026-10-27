/* Presentation state only. Server validation and calculation remain authoritative. */
(() => {
  'use strict';
  const en = true;
  const t = (fr, english) => en ? english : fr;
  let current = 0;
  let reviewIndex = 0;

  const panels = [...document.querySelectorAll('[data-panel]')];
  const stepButtons = [...document.querySelectorAll('[data-step]')];
  const byId = id => document.getElementById(id);
  function translate(root = document) {
    root.querySelectorAll('[data-fr][data-en]').forEach(el => {
      const value = el.dataset[en ? 'en' : 'fr'];
      if (el.textContent !== value) el.textContent = value;
    });
  }
  function available(step) {
    if (step === 0) return true;
    if (step === 4) return !!dossier;
    if (!window.factory?.canReview) return false;
    if (step === 1) return !!dossier;
    if (step === 2) return !!dossier?.revision && !byId('validation').hidden;
    return !!dossier?.revision && !byId('resultat').hidden;
  }
  function open(step, scroll = true) {
    if (!available(step)) return;
    current = step;
    panels.forEach(panel => panel.classList.toggle('is-inactive', Number(panel.dataset.panel) !== step));
    stepButtons.forEach(button => {
      const n = Number(button.dataset.step);
      if (n === step) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
      button.disabled = !available(n);
    });
    if (scroll) window.scrollTo({top: 0, behavior: 'smooth'});
    sync();window.factory?.onStep(step);
  }
  const labels = {plafond_kw:'Grid power limit', puissance_kw:'New machine power', duree_heures:'New machine runtime per day', ouverture_heure:'Earliest start', echeance_heure:'Latest finish', puissance_max_kw:'Maximum battery power', rendement:'Battery efficiency (each way)'};
  const reviewRows = () => [...document.querySelectorAll('#audit-documentaire>.alerte-documentaire'),...document.querySelectorAll('#faits>.fait')];
  function chooseReview(name) {
    const rows=reviewRows();
    reviewIndex=name==='issues'?0:Math.max(0,rows.findIndex(row=>!row.classList.contains('alerte-documentaire')));
    sync();
  }
  function focusReview(index) {
    const rows=reviewRows();
    reviewIndex=Math.max(0,Math.min(index,rows.length-1));
    sync();
    window.scrollTo({top:0,behavior:'smooth'});
    const title=byId('verification').querySelector('h2');title.setAttribute('tabindex','-1');title.focus({preventScroll:true});
  }
  function remaining() {
    const fields = [...document.querySelectorAll('#faits .fait')].filter(row => {
      const value = row.querySelector('.val');
      return value.value === '' || !value.validity.valid || (row.querySelector('.doc').value === '-1' && !row.querySelector('.motif').value.trim());
    });
    const issues = [...document.querySelectorAll('.alerte-documentaire')].filter(row => !row.querySelector('.accord-alerte').checked || row.querySelector('.motif-alerte').value.trim().length < 30);
    return {fields, issues};
  }
  function sync() {
    stepButtons.forEach(button => button.disabled = !available(Number(button.dataset.step)));
    if (current !== 0 && !available(current)) { open(available(1)?1:dossier?4:0); return; }
    const {fields, issues} = remaining();
    const rows=reviewRows();
    if(reviewIndex>=rows.length)reviewIndex=0;
    const active=rows[reviewIndex];
    rows.forEach((row,index)=>row.classList.toggle('review-inactive',index!==reviewIndex));
    const issue=active?.classList.contains('alerte-documentaire');
    byId('faits').hidden=!!issue;
    byId('audit-documentaire').hidden=!issue;
    byId('demo-tools').hidden=issue?active.querySelector('.motif-alerte').value.trim().length>=30:!active?.querySelector('.accepter-ia:disabled')||active.querySelector('.val').value!=='';
    const candidate=active?.querySelector('.accepter-ia:not(:disabled)');
    const canConfirm=candidate&&!candidate.checked&&(active.querySelector('.val').value===''||active.classList.contains('matches-proposal'));
    byId('preparer').disabled = !dossier || (fields.includes(active)&&!canConfirm) || issues.includes(active);
    byId('preparer').textContent=canConfirm?'Confirm & continue →':reviewIndex===rows.length-1?'Continue to simulation →':'Continue →';
    byId('review-remaining').hidden=current!==1||reviewIndex===0;
    byId('review-remaining').textContent='← Back';
    if(active){
      const title=byId('verification').querySelector('h2');
      title.dataset.en=issue?'What the documents reveal.':labels[active.dataset.cle];
      const count=rows.filter(row=>row.classList.contains('alerte-documentaire')).length;
      byId('review-position').textContent=issue?`${reviewIndex+1} / ${count}`:`${reviewIndex-count+1} / ${rows.length-count}`;
    }
    byId('journey-step').textContent = `Step ${[0,4,1,2,3].indexOf(current)+1} of 5`;
    byId('journey-status').textContent = [dossier?'Choose a study to review':'Start with your documents', issue?(issues.includes(active)?(active.querySelector('.motif-alerte').value.trim().length<30?'Add a reason under “Choose how to proceed”':'Confirm the decision above'):''):fields.includes(active)&&!canConfirm?'Enter a value to continue':'', byId('accord').checked?'':'Approve the inputs to continue', '',''][current]||'';
    document.querySelectorAll('[data-primary-step]').forEach(el => el.hidden = Number(el.dataset.primaryStep)!==current);
    byId('session-label').textContent='';byId('session-label').closest('.session-state').hidden=true;
    translate();
  }
  function summary() {
    const labels = {
      plafond_kw: ['Limite du réseau', 'Grid power limit'],
      puissance_kw: ['Nouvelle machine', 'New machine'],
      duree_heures: ['Durée de fonctionnement', 'New machine runtime per day'],
      ouverture_heure: ['Début possible', 'Earliest start'],
      echeance_heure: ['Fin au plus tard', 'Latest finish'],
      puissance_max_kw: ['Puissance de la batterie', 'Battery power'],
      rendement: ['Rendement par sens', 'Per-direction efficiency']
    };
    byId('validation-summary').innerHTML = Object.entries(labels).map(([key, names]) => {
      const fact = dossier.faits[key];
      const value = Number(fact.valeur).toLocaleString(en ? 'en-GB' : 'fr-FR', {maximumFractionDigits: 4});
      const source = fact.document < 0 ? t('Hypothèse explicite', 'Explicit assumption') : dossier.documents[fact.document]?.nom || '';
      return `<div class="validation-row"><div><span>${echappe(names[en ? 1 : 0])}</span><small>${echappe(source)}</small></div><strong>${value} ${echappe(dossier.champs[key][1])}</strong></div>`;
    }).join('');
    byId('validation-limit').textContent = dossier.audit_documentaire?.anomalies.some(a => a.code === 'reserve_prioritaire')
      ? t('La réserve de secours est hors du calcul. Cette simulation ne valide pas à elle seule le choix d’une batterie.', 'Backup reserve excluded from this simulation.')
      : t('Les hypothèses validées définissent la portée du calcul. La faisabilité sur le site reste à confirmer.', 'Approved assumptions define the calculation scope. Site feasibility still requires confirmation.');
  }
  function outcome() {
    byId('result-limit').textContent = dossier.audit_documentaire?.anomalies.some(a => a.code === 'reserve_prioritaire')
      ? t('Réserve de secours non modélisée : un résultat de 0 kWh pour les pointes ne signifie pas que le site n’a besoin d’aucune batterie.', 'Backup reserve excluded. 0 kWh for peaks does not mean no battery is needed.')
      : t('Résultat théorique sur les hypothèses validées. Ce n’est pas une recommandation d’achat.', 'Theoretical result based on approved assumptions. This is not a purchase recommendation.');
    const r = dossier.resultat, f = dossier.faits;
    const previous = historiqueCalculs.length > 1 ? historiqueCalculs.at(-2) : null;
    const comparable = previous && previous.resultat.retenu.statut === 0 && r.retenu.statut === 0;
    const before = comparable ? previous.resultat.retenu : r.initial;
    const after = r.retenu;
    const beforeStart = comparable ? previous.resultat.debuts_heures[0] : f.ouverture_heure.valeur;
    const beforeDuration = comparable ? previous.faits.duree_heures.valeur : f.duree_heures.valeur;
    const clock = h => { const minutes = Math.round(h * 60); return `${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`; };
    const energy = result => result.statut === 0 ? `${Number(result.capacite_utile_kwh).toLocaleString('en-GB',{maximumFractionDigits:2})} kWh` : 'No feasible solution found';
    const schedule = (start,duration,result) => result.statut===0 && Number.isFinite(start) ? `${clock(start)} → ${clock(start+duration)}` : 'No validated schedule';
    const changed = comparable ? Object.keys(labels).filter(key => previous.faits[key].valeur!==f[key].valeur) : [];
    let headline = after.statut === 0 ? `Run the machine from ${clock(r.debuts_heures[0])} to ${clock(r.debuts_heures[0]+f.duree_heures.valeur)}.` : 'This schedule could not be validated.';
    let explanation = after.statut === 0 ? `Battery energy needed for power peaks: ${energy(after)}.` : 'Review the inputs or try another time window. This result does not rule out every possible schedule.';
    if (comparable && changed.length === 1 && changed[0] === 'echeance_heure') {
      headline = `Allow a ${clock(f.echeance_heure.valeur)} finish instead of ${clock(previous.faits.echeance_heure.valeur)}.`;
      explanation = `Battery energy for peaks: ${energy(before)} to ${energy(after)}. Other inputs unchanged.`;
    } else if (comparable && changed.length) {
      explanation += ` Changed inputs: ${changed.map(key=>labels[key]).join(', ')}.`;
    } else if (comparable && !changed.length) {
      explanation += ' The numerical inputs are unchanged; source or review decisions may differ.';
    }
    byId('outcome-story').innerHTML = `<div class="outcome-intro"><h3>${echappe(headline)}</h3><p>${echappe(explanation)}</p></div>
      <div class="outcome-table"><table><caption>Schedule: first day. Battery energy: full simulated period.</caption><thead><tr><th scope="col">What changes</th><th scope="col">${comparable?'Previous simulation':'Earliest allowed start'}</th><th scope="col">${comparable?'Current simulation':'Suggested schedule'}</th></tr></thead><tbody>
      <tr><th scope="row">Machine runs</th><td>${schedule(beforeStart,beforeDuration,before)}</td><td>${schedule(r.debuts_heures[0],f.duree_heures.valeur,after)}</td></tr>
      <tr><th scope="row">Battery energy for power peaks</th><td>${energy(before)}</td><td>${energy(after)}</td></tr></tbody></table></div>`;
    byId('chiffres').hidden = !byId('comparaison-variantes').hidden;
    window.factory?.explainResult(dossier);sync();
  }
  window.parcours = {open, review: chooseReview, sync, summary, outcome, label: key => labels[key]};
  function init() {
    stepButtons.forEach(button => button.addEventListener('click', () => open(Number(button.dataset.step))));
    const prepare = byId('preparer').onclick;
    byId('preparer').onclick = () => {
      const active=reviewRows()[reviewIndex];
      const candidate=active?.querySelector('.accepter-ia:not(:disabled)');
      if(candidate&&!candidate.checked&&(active.querySelector('.val').value===''||active.classList.contains('matches-proposal')))candidate.click();
      const pending=remaining();
      if(pending.fields.includes(active)||pending.issues.includes(active))return;
      if(reviewIndex<reviewRows().length-1) {focusReview(reviewIndex+1);return;}
      const {fields,issues}=remaining();
      if(fields.length||issues.length){focusReview(reviewRows().indexOf(fields[0]||issues[0]));return;}
      return prepare();
    };
    byId('review-remaining').onclick=()=>focusReview(reviewIndex-1);
    byId('back-inputs').onclick = () => { open(1); chooseReview('inputs'); };
    byId('compare-again').onclick = () => {
      open(1); focusReview(reviewRows().findIndex(row=>row.dataset.cle==='echeance_heure'));
      const editor = document.querySelector('[data-cle="echeance_heure"] .edition-fait');
      if (editor) { editor.open = true; editor.scrollIntoView({block:'center',behavior:'smooth'}); }
      byId('v-echeance_heure')?.focus({preventScroll:true});
    };
    byId('show-documents').onclick = () => {
      byId('document-drawer').open = !byId('document-drawer').open;
      if (byId('document-drawer').open) byId('document-drawer').scrollIntoView({behavior:'smooth',block:'start'});
    };
    // Demo adapter appends its script after this script; wait for DOMContentLoaded.
    const demo = byId('mode-demo');
    document.querySelector('h1').innerHTML = en ? 'A new machine.<br><span>The same grid limit.</span>' : 'Une nouvelle machine.<br><span>La même limite électrique.</span>';
    if (demo) {
      document.querySelector('.extraction-action').hidden = true;
      document.querySelector('.start-card').classList.add('demo-card');
      document.querySelector('.import-help').hidden = true;
      document.querySelector('.start-card h2').textContent = t('Explorer le dossier de démonstration', 'Explore the demonstration');
      document.querySelector('.start-card>p').textContent = t('9 documents, un site industriel et une nouvelle machine. Suivez l’étude, des sources au résultat.', 'One factory. A new machine. Nine documents.');
      document.querySelector('.start-card>small').textContent = t('Documents publics et pièces fictives. Consommation simulée.', 'Sample study · Simulated demand');
      byId('exemple').textContent = t('Ouvrir le dossier de démonstration', 'Open demo →');
      const notice = demo.textContent;
      demo.innerHTML = `<span class="demo-short">${t('Démonstration · Réponse IA enregistrée · Calculs locaux', 'Demo · Recorded AI')}</span><details class="demo-disclosure"><summary>${t('À propos des données', 'Details')}</summary><p>${echappe(en ? 'Recorded walkthrough (DeepSeek V4.1 Flash response, September 24). Live document analysis on this site uses DeepSeek V4.1 Flash via Nebius. Review and calculations run locally.' : notice)}</p></details>`;
      if(window.CONTINGENCY_LIVE_AI) demo.textContent='Document analysis uses Nebius. Sample factory documents and demand.';
      const assumptions = byId('hypotheses-demo');
      if (assumptions) {
        byId('demo-tools').append(assumptions.parentElement);
        assumptions.textContent='Use demo assumptions';
        assumptions.nextElementSibling.textContent='Fills missing inputs. Review still required.';
      }
    }
    // Auto-update counts from actual input state, never pre-approve values or warnings.
    document.addEventListener('input', () => queueMicrotask(sync));
    document.addEventListener('change', () => queueMicrotask(sync));
    byId('document-drawer').append(document.querySelector('.technical-details'));
    const primary = byId('journey-primary');
    for (const [id,step] of [[demo?'exemple':'importer',0],['analyze-documents',4],['preparer',1],['calculer',2],['rapport-lisible',3]]) {
      const button = byId(id); button.dataset.primaryStep=step; button.classList.remove('secondaire'); primary.append(button);
    }
    byId('calculer').textContent='Run simulation →';
    byId('rapport-lisible').textContent='Open report ↗';
    byId('rapport-lisible').setAttribute('aria-label','Open report in a new tab');
    translate(); open(0, false);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true}); else init();
})();
