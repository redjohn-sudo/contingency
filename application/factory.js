/* Product flow over the existing sourced inputs, review gates and local solver. */
(() => {
  'use strict';
  const id = value => document.getElementById(value);
  const format = (n, digits=1) => Number(n).toLocaleString('en-GB',{maximumFractionDigits:digits});
  const hour = n => `${String(Math.floor(n)).padStart(2,'0')}:${String(Math.round((n%1)*60)).padStart(2,'0')}`;
  let machine = null;
  let ready = false;
  let factoryBase=null;
  let studies = [];
  let pendingFiles=[];
  let uploadedStudy=null;
  let reviewedStudyId=null;
  let welcomeSeen=false;
  try{welcomeSeen=localStorage.getItem('contingency-welcome-v2')==='seen'}catch{}
  function dismissWelcome(){welcomeSeen=true;id('factory-welcome').close();try{localStorage.setItem('contingency-welcome-v2','seen')}catch{}}
  let analysisProgress=null;
  async function taskRequest(url, options={}) {
    for(let attempt=0;attempt<3;attempt++){
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
      let retryable=true;
      try{
        const response=await fetch(url,{...options,signal:controller.signal});
        if(!response.ok){
          retryable=response.status>=500||response.status===408;
          const detail=await response.json().catch(()=>({}));
          throw Error(detail.detail||'Connection interrupted. Retry analysis to resume.');
        }
        return await response.json();
      }catch(error){
        if(!retryable)throw error;
        if(attempt===2)throw Error('Connection interrupted. Retry analysis to resume.');
      }finally{clearTimeout(timer)}
      await new Promise(resolve=>setTimeout(resolve,300*(attempt+1)));
    }
  }
  async function documentTask(studyId,kind,payload={}) {
    if(!window.CONTINGENCY_PUBLIC_APP)return appel(`/api/${studyId}/${kind==='analysis'?'extraire':'documents'}`,payload);
    const start=await taskRequest(`/api/${studyId}/tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,...payload,request_id:crypto.randomUUID()})});
    const deadline=Date.now()+300000;
    while(Date.now()<deadline){
      await new Promise(resolve=>setTimeout(resolve,1000));
      const job=await taskRequest(`/api/tasks/${start.job}`);
      if(job.progress)analysisProgress=job.progress;
      if(job.status==='failed')throw Error(job.error);
      if(job.status==='complete')return job.study;
    }
    throw Error('Analysis is taking too long. Please retry.');
  }
  try { studies = JSON.parse(localStorage.getItem('contingency-machines-v2')||'[]').filter(s=>/^[a-f0-9]{32}$/.test(s.id)).slice(0,100); } catch {}
  const icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 20V9l6-4v6l6-4v13M15 20V3h5v17M6 15h2m3 0h2m-7 3h2m3 0h2"/></svg>';

  function loaded(d) {
    if (!id('factory-home')) return;
    afficherModeAnalyse(d);
    ready=true;
    if(!factoryBase||factoryBase.profil_sha256!==d.profil_sha256||factoryBase.origine_demo!==d.origine_demo)factoryBase=structuredClone(d);
    id('factory-home').hidden=false;
    const scene=document.querySelector('.system-scene');if(scene)id('factory-map').append(scene);
    document.querySelectorAll('#depart>.hero-copy,#depart>.start-layout').forEach(el=>el.hidden=true);
    if(!id('mode-demo')){document.querySelector('.factory-section-title>span').textContent='First day in the supplied profile';}
    renderHome(d);
    id('add-machine').disabled=false;
    if(!welcomeSeen&&id('mode-demo')&&!id('factory-welcome').open)id('factory-welcome').showModal();
  }
  function afficherModeAnalyse(etude) {
    const notice=id('provenance-analyse');
    if(!notice)return;
    id('retour-etude').hidden=!etude.repli_de;
    const enregistre=etude.extraction_ia?.execution==='recorded';
    notice.hidden=!(enregistre||window.CONTINGENCY_LIVE_AI||etude.extraction_ia?.execution==='live');
    notice.textContent=enregistre
      ? 'Recorded demonstration: DeepSeek response from 24 September 2026. Sample documents and simulated demand.'
      : etude.extraction_ia?.execution==='live'
        ? 'Documents analysed with Nebius. Review the proposed values and their sources.'
        : 'Analysis on request: your document text is sent to Nebius when you start the analysis.';
  }
  async function ouvrirRepliDemo() {
    await action(async()=>{
      const identifiant=uploadedStudy?.id||dossier.id;
      const repli=await appel(`/api/${identifiant}/demo-repli`);
      // Le repli possède ses propres documents, mesures et hypothèses de machine.
      machine=null;factoryBase=null;pendingFiles=[];uploadedStudy=null;reviewedStudyId=null;
      afficher(repli);queueFiles([]);parcours.open(0);
      id('document-error').hidden=true;id('review-without-ai').hidden=true;id('demo-repli').hidden=true;
      const message=id('message');message.className='';
      message.textContent='Recorded demonstration opened. Your previous study has been kept separately.';
      window.scrollTo({top:0,behavior:'instant'});
    });
  }
  async function reprendreEtude() {
    await action(async()=>{
      const identifiant=dossier.repli_de;
      if(!identifiant)return;
      const reponse=await fetch(`/api/${identifiant}/study`);
      if(!reponse.ok)throw Error('Your previous study could not be opened.');
      const etude=await reponse.json();
      const sauvegarde=studies.find(entree=>entree.id===identifiant);
      machine=sauvegarde?{...sauvegarde}:null;factoryBase=null;
      pendingFiles=[];uploadedStudy=null;reviewedStudyId=null;
      afficher(etude);queueFiles([]);
      if(machine)applyMachine(machine);
      parcours.open(machine?4:0);
      id('document-error').hidden=true;id('review-without-ai').hidden=true;id('demo-repli').hidden=true;
      id('message').textContent='Your previous study is open. You can retry its analysis.';
      window.scrollTo({top:0,behavior:'instant'});
    });
  }
  function onStep(step) {
    document.body.classList.toggle('is-factory-home',step===0&&ready);
    if(step===0&&ready)renderHome(dossier);
    if(step===4&&ready)renderDocuments(dossier);
  }
  function renderHome(d) {
    if(factoryBase?.profil_sha256===d.profil_sha256&&factoryBase.origine_demo===d.origine_demo)d=factoryBase;
    const grid=d.faits.plafond_kw.valeur??d.extraction_ia?.propositions?.plafond_kw?.valeur;
    const peak=Math.max(...d.profil_apercu);
    id('factory-grid').textContent=grid==null?'Needs review':`${format(grid)} kW`;
    id('factory-peak').textContent=`${format(peak)} kW`;
    id('factory-energy').textContent=`${format(d.profil_apercu.reduce((a,b)=>a+b,0)/4,0)} kWh`;
    id('factory-demand').innerHTML=demandSvg(d.profil_apercu,grid);
    const schedule=(start,end)=>`<div class="machine-schedule"><span>${hour(start)}–${hour(end)}</span><div class="schedule-track"><i style="left:${start/24*100}%;width:${(end-start)/24*100}%"></i></div></div>`;
    id('factory-studies').innerHTML=`<div class="machine-table"><div class="machine-table-head"><span>Machine</span><span>Power</span><span>Energy / day</span><span>Schedule</span></div><div class="machine-table-row existing-production"><div><strong>Existing production</strong><small>Combined factory demand</small></div><span>${format(Math.min(...d.profil_apercu))}–${format(peak)} kW</span><span>${format(d.profil_apercu.reduce((a,b)=>a+b,0)/4,0)} kWh</span><span class="muted">From the demand profile</span></div>${studies.filter(record=>record.factoryProfile===d.profil_sha256&&(record.origineDemo||null)===(d.origine_demo||null)).map(record=>{
      const solved=record.status==='simulated';
      const start=solved?record.chosenStart:record.start,end=solved?start+record.runtime:record.end;
      return `<div class="machine-table-row"><div><button class="machine-link" data-machine-id="${record.id}">${echappe(record.name)}</button><small>${solved?'Proposed addition · simulated':'Proposed addition · needs review'}</small></div><span>${format(record.power)} kW</span><span>${format(record.power*record.runtime)} kWh</span><div>${solved&&Number.isFinite(start)?schedule(start,end):`<span>${hour(start)}–${hour(end)}</span><small>${format(record.runtime)} h to schedule</small>`}</div></div>`;
    }).join('')}</div>`;
    id('factory-studies').querySelectorAll('[data-machine-id]').forEach(button=>button.onclick=()=>action(async()=>{
      const record=studies.find(s=>s.id===button.dataset.machineId);
      const response=await fetch(`/api/${record.id}/study`);if(!response.ok)throw Error('This saved machine could not be opened.');
      const d=await response.json(),revision=d.revision;machine={...record};pendingFiles=[];uploadedStudy=null;reviewedStudyId=revision&&d.resultat?d.id:null;
      afficher(d);d.revision=revision;
      if(d.resultat&&revision){afficherResultat(d)}else{applyMachine(machine);parcours.open(4)}
    }));
  }
  function saveMachine(d,status='needs-review') {
    if(!machine)return;
    const old=studies.find(s=>s.id===d.id)||{};
    const record={...old,...machine,id:d.id,status,factoryProfile:d.profil_sha256,origineDemo:d.origine_demo||null};
    if(status==='simulated'){
      record.power=d.faits.puissance_kw.valeur;record.runtime=d.faits.duree_heures.valeur;
      record.start=d.faits.ouverture_heure.valeur;record.end=d.faits.echeance_heure.valeur;
      record.chosenStart=d.resultat.retenu.statut===0?d.resultat.debuts_heures[0]:null;
      record.energy=d.resultat.retenu.statut===0?d.resultat.retenu.capacite_utile_kwh:null;
    }
    const index=studies.findIndex(s=>s.id===record.id);if(index<0)studies.push(record);else studies[index]=record;
    try{localStorage.setItem('contingency-machines-v2',JSON.stringify(studies));}catch{}
    renderHome(d);
  }
  function documentRole(doc) {
    const name=doc.nom.toLowerCase();
    if(/liander|contrat|contract|grid/.test(name))return ['Grid connection','The power your factory can draw.'];
    if(/atlas|kaeser|machine|compressor|spec/.test(name))return ['Machine specifications','Power and operating requirements.'];
    if(/batter|batterie|devis/.test(name))return ['Battery','Storage capacity and power limits.'];
    if(/planning|maintenance|schedule|meetrapport/.test(name))return ['Operations','Working hours and site conditions.'];
    return ['Other documents','Supporting evidence for this machine.'];
  }
  function renderDocuments(d) {
    const groups=new Map();d.documents.forEach((doc,index)=>{const [name,purpose]=documentRole(doc);if(!groups.has(name))groups.set(name,{purpose,docs:[]});groups.get(name).docs.push({doc,index})});
    id('document-packs').innerHTML=[...groups].map(([name,group])=>`<section class="document-group"><h3>${name}</h3><p>${group.purpose}</p>${group.docs.map(({doc,index})=>`<div class="document-file"><input type="checkbox" class="keep-document" value="${index}" checked aria-label="Include ${echappe(doc.nom)}"><details><summary>${echappe(doc.nom)}</summary><pre class="original-content">${echappe(doc.texte)}</pre></details></div>`).join('')}</section>`).join('');
    id('document-packs').insertAdjacentHTML('beforeend',`<section class="document-group profile-document"><h3>Electricity demand</h3><p>Existing factory consumption, every 15 minutes.</p><span>${d.nombre_mesures} readings · ${d.nombre_mesures/96} day${d.nombre_mesures===96?'':'s'}</span><p><a href="/import-compteur" target="_blank" rel="noopener">Prepare a meter CSV</a></p></section>`);
    id('analyze-documents').textContent=machine?(d.mode_extraction==='demo_archivee'?'Review recorded findings →':'Analyze documents →'):'Add a machine →';
  }
  function queueFiles(files) {
    reviewedStudyId=null;
    for(const file of files){if(!/\.(pdf|txt)$/i.test(file.name)||file.size>5*1024*1024){id('document-error').classList.remove('sr-only');id('document-error').textContent='PDF or TXT, up to 5 MB.';id('document-error').hidden=false;return;}}
    pendingFiles=[...pendingFiles,...files];
    id('pending-files').innerHTML=pendingFiles.map((file,i)=>`<div><span>${echappe(file.name)}</span><button type="button" data-remove-file="${i}" aria-label="Remove ${echappe(file.name)}">×</button></div>`).join('');
    id('pending-files').querySelectorAll('button').forEach(button=>button.onclick=()=>{pendingFiles.splice(Number(button.dataset.removeFile),1);const remaining=[...pendingFiles];pendingFiles=[];queueFiles(remaining)});
    parcours.sync();
  }
  async function analyzeDocuments() {
    if(!machine){id('machine-dialog').showModal();return;}
    reviewedStudyId=null;parcours.sync();
    id('document-error').hidden=true;id('review-without-ai').hidden=true;id('demo-repli').hidden=true;
    await action(async()=>{
      let study=dossier;
      const keep=[...document.querySelectorAll('.keep-document:checked')].map(el=>Number(el.value));
      const changed=pendingFiles.length||keep.length!==dossier.documents.length;
      if(changed){
        const documents=[];for(const file of pendingFiles){const bytes=new Uint8Array(await file.arrayBuffer());let b='';for(let i=0;i<bytes.length;i+=8192)b+=String.fromCharCode(...bytes.subarray(i,i+8192));documents.push({nom:file.name,base64:btoa(b)})}
        study=await process('import',()=>documentTask(dossier.id,'documents',{documents,keep}),true);
        const previous=dossier.id;studies=studies.filter(s=>s.id!==previous);uploadedStudy=study;
        afficher(study);if(machine)applyMachine(machine);saveMachine(study);pendingFiles=[];queueFiles([]);parcours.open(4);
      }
      if(study.extraction_ia&&(!window.CONTINGENCY_LIVE_AI||study.mode_extraction==='demo_archivee')){
        study=await process('analysis',async()=>study);
      }else{
        try{study=await process('analysis',()=>documentTask(study.id,'analysis'),true)}
        catch(error){uploadedStudy=study;id('document-error').textContent=error.message||'Analysis unavailable. Please retry.';id('document-error').classList.remove('sr-only');id('document-error').hidden=false;id('analyze-documents').textContent='Retry analysis →';id('review-without-ai').hidden=false;id('demo-repli').hidden=!id('mode-demo');return;}
      }
      reviewedStudyId=study.id;afficher(study);if(machine)applyMachine(machine);parcours.review('issues');parcours.open(1);
    });
  }

  function demandSvg(profile,grid) {
    const max=Math.max(...profile,grid||0)*1.12;
    const width=Math.max(280,Math.min(748,(id('factory-demand')?.clientWidth||innerWidth-100)));
    const right=width-16;
    const x=i=>42+i*(right-42)/96,y=v=>158-v/max*130;
    const path=profile.map((v,i)=>`${i?'L':'M'}${x(i)},${y(v)}L${x(i+1)},${y(v)}`).join(' ');
    return `<svg viewBox="0 0 ${width} 195" role="img" aria-label="Existing factory electricity demand over a simulated day"><path d="${path}" fill="none" stroke="#3859f5" stroke-width="2.5"/>${grid==null?'':`<path d="M42 ${y(grid)}H${right}" stroke="#a93c48" stroke-dasharray="6 5"/><text x="${right}" y="${y(grid)-8}" text-anchor="end">Grid limit · ${format(grid)} kW</text>`}${[0,6,12,18,24].map(h=>`<text x="${x(h*4)}" y="184" text-anchor="middle">${hour(h)}</text>`).join('')}</svg>`;
  }
  function applyMachine(spec) {
    for(const [key,value] of Object.entries({puissance_kw:spec.power,duree_heures:spec.runtime,ouverture_heure:spec.start,echeance_heure:spec.end})) {
      const row=document.querySelector(`[data-cle="${key}"]`),proposal=dossier.extraction_ia?.propositions?.[key];
      // Public studies retain newly extracted machine inputs for explicit review.
      // A prefilled sample machine must not overwrite the judge's document.
      if(window.CONTINGENCY_PUBLIC_APP&&dossier.extraction_ia)continue;
      const sourced=proposal?.valeur===value;
      row.querySelector('.val').value=value;
      row.querySelector('.doc').value=sourced?proposal.document:-1;
      row.querySelector('.ligne').value=sourced?proposal.ligne:0;
      row.querySelector('.motif').value=sourced?'Machine input confirmed against the supplied documents.':`Machine scenario: ${spec.name}. ${parcours.label(key)} set to ${value}; site applicability requires confirmation.`;
      row.dispatchEvent(new Event('input',{bubbles:true}));
      if(sourced){const checkbox=row.querySelector('.accepter-ia');if(checkbox)checkbox.checked=true;}
    }
    parcours.sync();
  }
  async function addMachine(event) {
    event.preventDefault();
    const form=event.currentTarget;
    const spec={name:id('machine-name').value.trim(),power:Number(id('machine-power').value),runtime:Number(id('machine-runtime').value),start:Number(id('machine-start').value),end:Number(id('machine-end').value)};
    id('machine-name').setCustomValidity(spec.name?'':'Enter a machine name.');
    id('machine-end').setCustomValidity(spec.end-spec.start<spec.runtime?'The time window must fit the full runtime.':'');
    if(!form.reportValidity())return;
    id('machine-dialog').close();
    await action(async()=>{
      const study=await appel(`/api/${dossier.id}/scenario`);
      machine=spec;reviewedStudyId=null;uploadedStudy=null;dismissWelcome();
      afficher(study);applyMachine(spec);saveMachine(study);parcours.open(4);
    });
  }
  async function process(kind,request,fresh=false) {
    const demo=dossier?.mode_extraction==='demo_archivee'||!!id('mode-demo')&&!window.CONTINGENCY_LIVE_AI;
    const duration=kind==='simulation'?10000:kind==='analysis'&&demo&&!fresh?4200:0;
    const dialog=id('processing-dialog');
    analysisProgress=null;
    id('process-documents').innerHTML='';
    let renderedFiles='';
    const simulation=kind==='simulation';
    dialog.classList.toggle('processing-simulation',simulation);
    const visual=id('simulation-visual');visual.hidden=!simulation;visual.innerHTML='';
    if(simulation){
      const grid=dossier.faits.plafond_kw.valeur;
      const scene=document.querySelector('.energy-map')?.outerHTML.replaceAll('node-blue','simulation-blue').replaceAll('node-shadow','simulation-shadow')||'';
      visual.innerHTML=`<div class="simulation-network">${scene}</div><div class="simulation-demand">${demandSvg(dossier.profil_apercu,grid)}<i class="simulation-sweep" aria-hidden="true"></i></div>`;
    }
    let finished=false;
    const steps=kind==='simulation'?[
      ['Factory demand','Your existing consumption and grid limit'],
      ['Machine schedule','Finding room inside the allowed operating hours'],
      ['Battery support','Power peaks, charging and energy losses'],
      ['Scenario comparison','Earlier start versus the suggested schedule']
    ]:[
      ['Reading the machine documents',`${dossier.documents.length} documents in this study`],
      ['Checking document values','Matching the numbers to their source passages'],
      ['Checking the evidence','Source citations, conflicting values and missing conditions'],
      ['Opening the findings','Every finding stays linked to its source']
    ];
    id('process-mode').textContent=demo&&!fresh?'Recorded response from 24 September 2026.':'Document analysis with Nebius.';
    id('process-mode').hidden=kind!=='analysis';
    id('process-steps').innerHTML=duration?steps.map(([title],i)=>`<li><span>${i+1}</span>${title}</li>`).join(''):'';
    dialog.classList.toggle('processing-live',!duration);
    dialog.showModal();
    const begin=performance.now();
    const update=()=>{
      const elapsed=performance.now()-begin;
      const progress=duration?Math.min(elapsed/duration,.96):.35;
      const index=Math.min(steps.length-1,Math.floor(progress*steps.length));
      if(simulation){
        visual.dataset.stage=String(index);
        dialog.classList.toggle('processing-live',elapsed>=duration&&!finished);
      }
      id('process-title').textContent=duration?steps[index][0]:kind==='simulation'?'Calculating the schedule':kind==='import'?'Reading your files':'Analyzing your documents';
      id('process-detail').textContent=duration?steps[index][1]:`${Math.floor(elapsed/1000)} s`;
      if(kind==='analysis'&&!duration){
        const stage=analysisProgress?.stage;
        id('process-title').textContent=stage==='checking'?'Checking citations and numbers':stage==='analyzing'?'Comparing your documents together':'Preparing your documents';
        const files=analysisProgress?.documents||dossier.documents.map(doc=>({name:doc.nom,lines:doc.texte.split('\n').length}));
        const signature=JSON.stringify(files);
        if(signature!==renderedFiles){
          id('process-documents').innerHTML=files.map(doc=>`<li><span>${echappe(doc.name)}</span><small>${doc.lines} lines</small></li>`).join('');
          renderedFiles=signature;
        }
        id('process-detail').textContent=`${stage==='checking'?'Matching claims to the original text':stage==='analyzing'?'Looking for values, missing information and contradictions':'Collecting the source text'} · ${Math.floor(elapsed/1000)} s`;
      }
      if(simulation&&elapsed>=duration&&!finished){
        id('process-title').textContent='Calculating the schedule';
        id('process-detail').textContent='The calculation is still running';
      }
      id('process-fill').style.width=`${progress*100}%`;
      [...id('process-steps').children].forEach((el,i)=>{el.classList.toggle('active',i===index);el.classList.toggle('done',i<index)});
    };
    update();const timer=setInterval(update,160);
    try {
      const result=await request();finished=true;
      const remaining=duration-(performance.now()-begin);
      if(remaining>0)await new Promise(resolve=>setTimeout(resolve,remaining));
      id('process-fill').style.width='100%';return result;
    } finally {clearInterval(timer);dialog.close();}
  }
  function completed(d) {saveMachine(d,'simulated');}
  function explainResult(d) {
    const zone=id('why-schedule');if(!zone)return;
    const data=donneesGraphique(d);
    if(!data||d.resultat.retenu.statut!==0){zone.hidden=true;return;}
    const initialPeak=Math.max(...data.initial),newPeak=Math.max(...data.retenu);
    const beforeExcess=Math.max(0,initialPeak-data.plafond),afterExcess=Math.max(0,newPeak-data.plafond);
    const countBefore=data.initial.filter(n=>n>data.plafond+1e-6).length/4,countAfter=data.retenu.filter(n=>n>data.plafond+1e-6).length/4;
    const v=d.faits,duration=v.duree_heures.valeur;
    const baseAverage=start=>d.profil_apercu.slice(Math.round(start*4),Math.round((start+duration)*4)).reduce((a,b)=>a+b,0)/(duration*4);
    const earlier=baseAverage(v.ouverture_heure.valeur),chosen=baseAverage(data.debut);
    zone.hidden=false;
    id('why-title').textContent=chosen<earlier?'The other machines use less power in this time window.':'The schedule is checked against your factory’s existing demand.';
    id('why-detail').textContent=`Same new machine: ${format(v.puissance_kw.valeur)} kW for ${format(duration)} h. Existing production averages ${format(earlier)} kW during ${hour(v.ouverture_heure.valeur)}–${hour(v.ouverture_heure.valeur+duration)}, versus ${format(chosen)} kW during ${hour(data.debut)}–${hour(data.fin)}.`;
    id('why-metrics').innerHTML=`<div><span>Peak above the grid limit</span><strong>${format(beforeExcess)} → ${format(afterExcess)} kW</strong></div><div><span>Time above the limit</span><strong>${format(countBefore)} → ${format(countAfter)} h</strong></div>`;
    id('why-footnote').textContent='First simulated day, before the battery acts. Shorter or smaller peaks leave less energy for the battery to cover.';
    const chart=id('graphique-planning');zone.querySelector('.why-chart').append(chart);
  }
  function init() {
    const provenance=document.createElement('p');provenance.id='provenance-analyse';provenance.hidden=true;
    provenance.setAttribute('role','status');id('message').after(provenance);
    const retour=document.createElement('button');retour.id='retour-etude';retour.type='button';retour.className='secondaire';retour.hidden=true;
    retour.textContent='Return to your previous study';retour.onclick=reprendreEtude;provenance.after(retour);
    const repli=document.createElement('button');repli.id='demo-repli';repli.type='button';repli.className='secondaire';repli.hidden=true;
    repli.textContent='Open recorded demonstration (24 September)';repli.onclick=ouvrirRepliDemo;
    id('review-without-ai').after(repli);
    const home=document.createElement('div');home.id='factory-home';home.hidden=true;
    home.innerHTML=`<div class="factory-heading"><div><h1>Your factory.</h1></div><div class="factory-heading-actions"><button class="secondaire" id="factory-docs">Factory documents</button><button id="add-machine" disabled>+ Add a machine</button></div></div>
      <div class="factory-overview"><section class="factory-demand-panel"><div class="factory-section-title"><h2>Existing production</h2><span>Simulated day</span></div><div class="factory-metrics"><div><span>Grid power limit</span><strong id="factory-grid">—</strong></div><div><span>Peak demand</span><strong id="factory-peak">—</strong></div><div><span>Energy per day</span><strong id="factory-energy">—</strong></div></div><div id="factory-demand"></div></section><div id="factory-map"></div></div>
      <section class="factory-studies"><div class="factory-section-title"><h2>Machines</h2><button type="button" id="add-machine-inline" class="add-machine-inline" aria-label="Add a machine">+</button></div><div id="factory-studies"></div></section>`;
    id('depart').append(home);
    const welcome=document.createElement('dialog');welcome.id='factory-welcome';welcome.setAttribute('aria-labelledby','welcome-title');welcome.setAttribute('aria-describedby','welcome-description');
    welcome.innerHTML='<h2 id="welcome-title">Start with a sample factory.</h2><p id="welcome-description">A new machine and its documents are ready. See what the AI finds.</p><div class="welcome-actions"><button type="button" id="try-sample" autofocus>Explore sample →</button><button type="button" id="dismiss-welcome" class="secondaire">View factory</button></div>';
    welcome.addEventListener('cancel',event=>{event.preventDefault();dismissWelcome()});document.body.append(welcome);
    document.querySelector('.review-content').append(id('demo-tools'));
    let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(ready)renderHome(dossier)},120)});
    const why=document.createElement('section');why.id='why-schedule';why.hidden=true;why.innerHTML='<h3 id="why-title"></h3><p id="why-detail"></p><div id="why-metrics"></div><div class="why-chart"></div><small id="why-footnote"></small>';
    id('outcome-story').after(why);
    const add=document.createElement('dialog');add.id='machine-dialog';add.innerHTML=`<form id="machine-form"><div class="dialog-heading"><h2>Add a machine</h2><button class="icon-button" type="button" id="close-machine" aria-label="Close">×</button></div><label for="machine-name">Machine name</label><input id="machine-name" required maxlength="80" value="Compressor group"><div class="grille"><div><label for="machine-power">Power (kW)</label><input id="machine-power" type="number" min="0.01" max="1000000" step="any" required value="73"></div><div><label for="machine-runtime">Runtime per day (h)</label><input id="machine-runtime" type="number" min="0.25" max="24" step="0.25" required value="4"></div><div><label for="machine-start">Earliest start (hour)</label><input id="machine-start" type="number" min="0" max="23.75" step="0.25" required value="8"></div><div><label for="machine-end">Latest finish (hour)</label><input id="machine-end" type="number" min="0.25" max="24" step="0.25" required value="16"></div></div><button type="submit">Continue to documents →</button></form>`;document.body.append(add);
    const busy=document.createElement('dialog');busy.id='processing-dialog';busy.setAttribute('aria-labelledby','process-title');busy.innerHTML=`<p id="process-mode"></p><div class="processing-art" aria-hidden="true"><div class="scan-document"><i></i><i></i><i></i><i></i><b></b></div><div class="processing-path"></div><div class="processing-core">${icon}</div></div><div id="simulation-visual" hidden aria-label="Factory demand and energy flow illustration"></div><h2 id="process-title"></h2><p id="process-detail"></p><div class="process-track" aria-hidden="true"><i id="process-fill"></i></div><ol id="process-steps"></ol><ul id="process-documents" aria-label="Documents included in this analysis"></ul>`;busy.addEventListener('cancel',e=>e.preventDefault());document.body.append(busy);
    id('dismiss-welcome').onclick=dismissWelcome;
    id('try-sample').onclick=()=>{
      if(!ready||document.body.classList.contains('busy'))return;
      for(const [key,value] of Object.entries({'machine-name':'Compressor group','machine-power':73,'machine-runtime':4,'machine-start':8,'machine-end':16}))id(key).value=value;
      id('machine-form').requestSubmit();
    };
    id('machine-name').addEventListener('input',()=>id('machine-name').setCustomValidity(''));
    id('machine-form').addEventListener('submit',addMachine);id('close-machine').onclick=()=>add.close();id('machine-end').addEventListener('input',()=>id('machine-end').setCustomValidity(''));
    id('add-machine').onclick=id('add-machine-inline').onclick=()=>{if(ready)add.showModal()};
    id('factory-docs').onclick=()=>parcours.open(4);id('back-to-factory').onclick=()=>parcours.open(0);
    id('analyze-documents').onclick=analyzeDocuments;
    id('document-packs').addEventListener('change',()=>{reviewedStudyId=null;parcours.sync()});
    id('use-own-documents').onclick=()=>{document.querySelectorAll('.keep-document').forEach(input=>input.checked=false);reviewedStudyId=null;parcours.sync();id('machine-files').click()};
    id('machine-files').onchange=e=>{queueFiles([...e.target.files]);e.target.value=''};
    const drop=document.querySelector('.file-drop');drop.ondragover=e=>{e.preventDefault();drop.classList.add('drag-over')};drop.ondragleave=()=>drop.classList.remove('drag-over');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('drag-over');queueFiles([...e.dataTransfer.files])};
    id('review-without-ai').onclick=()=>{if(uploadedStudy&&machine){reviewedStudyId=uploadedStudy.id;afficher(uploadedStudy);if(machine)applyMachine(machine);parcours.review('issues');parcours.open(1)}};
    document.querySelector('.brand').onclick=event=>{event.preventDefault();if(!document.body.classList.contains('busy'))parcours.open(0)};
    if(id('mode-demo')){
      id('mode-demo').hidden=true;
      const scene=document.querySelector('.system-scene');id('factory-map').append(scene);
      document.querySelectorAll('#depart>.hero-copy,#depart>.start-layout').forEach(el=>el.hidden=true);
      const start=id('exemple');delete start.dataset.primaryStep;start.hidden=true;
      home.hidden=false;document.body.classList.add('is-factory-home');
      action(async()=>{const d=await appel('/api/demo/archive');afficher(d);parcours.open(0)});
    }
  }
  window.factory={loaded,onStep,completed,process,explainResult,get machine(){return machine},get canReview(){return !!machine&&reviewedStudyId===dossier?.id}};
  document.addEventListener('DOMContentLoaded',init,{once:true});
})();
