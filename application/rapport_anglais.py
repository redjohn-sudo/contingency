"""English presentation of a checked study; citations and user notes stay verbatim."""
from html import escape

LABELS = {
    'plafond_kw': ('Grid power limit', 'kW'),
    'puissance_kw': ('Added machine power', 'kW'),
    'duree_heures': ('Required consecutive runtime', 'h'),
    'ouverture_heure': ('Earliest start', 'h'),
    'echeance_heure': ('Latest finish', 'h'),
    'puissance_max_kw': ('Maximum battery power', 'kW'),
    'rendement': ('Per-direction efficiency', 'ratio'),
}
ISSUES = {
    'capacite_incoherente': 'The quoted usable capacity conflicts with nominal capacity multiplied by depth of discharge.',
    'reserve_prioritaire': 'Mandatory backup reserve is specified but is not represented by this model.',
    'rendement_cycle': 'Round-trip efficiency does not establish efficiency in each direction.',
    'donnees_preliminaires': 'A generic or preliminary document requires confirmation of its applicability to this site.',
    'horaire_fragmente': 'A time contains separated digits. Check the original document.',
    'capacites_a_confirmer': 'The active-power limit and apparent-power capacity require a scope and physical-limit check.',
    'condition_site_absente': 'Site operating conditions are missing.',
    'notation_ambigue': 'Confirm the decimal or thousands separator.',
    'portee_a_confirmer': 'Document applicability to the site must be confirmed.',
    'valeurs_a_concilier': 'Conflicting values or conditions require review.',
    'document_generique': 'A generic document requires confirmation of applicability to this site.',
    'instruction_parasite': 'An instruction addressed to the model is not accepted as numeric evidence.',
}


def render(d, control, result_hash):
    e = lambda v: escape(str(v), quote=True)
    r = d['resultat']
    valid = control['statut'] in ('realisable', 'optimal')
    status = {'optimal': 'Optimal within the stated model', 'realisable': 'Feasible within the stated model'}.get(control['statut'], 'Result suspended: review the inputs and unresolved issues')
    body = ['<h1>Grid capacity study</h1>', '<p class="important-limit">Exploratory simulation, not a purchase recommendation or certification of site feasibility.</p>', '<h2>Simulation result</h2>', f'<p>{e(status)}</p>']
    if valid:
        body += [f'<p class="valeur">{r["retenu"]["capacite_utile_kwh"]:.2f} kWh</p>', '<p>Usable capacity for peak smoothing. Start times within each 24-hour block: '+e(', '.join(map(str,r['debuts_heures'])))+' h.</p>']
    body += ['<h2>Reviewed inputs</h2><div class="tableau"><table><thead><tr><th>Input</th><th>Value</th><th>Evidence / declared assumption</th></tr></thead><tbody>']
    for key, (label, unit) in LABELS.items():
        f=d['faits'][key]
        source='Declared assumption' if f['document']<0 else d['documents'][f['document']]['nom']+', line '+str(f['ligne'])
        body += [f'<tr><td>{e(label)}</td><td>{e(f["valeur"])} {e(unit)}</td><td>{e(source)}<blockquote>{e(f.get("citation", ""))}</blockquote><p>{e(f.get("motif", ""))}</p></td></tr>']
    body += ['</tbody></table></div><h2>Unresolved document issues</h2><p>Sources and user-written reasons below are preserved in their original language. Approval records a simulation assumption; it does not independently resolve the engineering uncertainty.</p>']
    for issue in control['audit_documentaire']['anomalies']:
        body += [f'<h3>{e(ISSUES.get(issue["code"], issue["code"].replace("_", " ")))}</h3>']
        for proof in issue['preuves']:
            body += [f'<blockquote>D{proof["document"]+1}, line {proof["ligne"]}: {e(proof["citation"])}</blockquote>']
        review=d.get('revue_documentaire',{}).get(issue['id'],{})
        decision='Declared not applicable by the reviewer' if review.get('decision')=='non_applicable' else 'Explicit simulation assumption'
        body += [f'<p>{decision}: {e(review.get("motif", "REVIEW MISSING"))}</p>']
    if any(a['code']=='reserve_prioritaire' for a in control['audit_documentaire']['anomalies']):
        body += ['<p class="important-limit">Mandatory backup reserve is not modelled. Zero capacity for peak smoothing does not mean the site needs no battery.</p>']
    body += ['<h2>Model scope</h2><p>Demand known in advance, average power at 15-minute intervals. One machine cycle per 24-hour block, no excluded days. Constant efficiency in each direction, free and cyclic initial battery state. Ageing, startup transients, tariffs and staffing constraints are excluded. Baseline strategies are heuristic. A failed heuristic does not prove all schedules infeasible. Any optimality claim applies only to the stated discrete model and solver tolerances. Joint search is limited to seven blocks and four seconds.</p><p>No financial savings or human time savings have been measured. The result is theoretical usable capacity, not a commercial battery size.</p><h2>Traceability</h2>']
    for label,value in [('Validated revision',d['revision']),('Demand profile SHA-256',d['profil_sha256']),('Result SHA-256',result_hash),('Calculation engine',r.get('moteur','')),('Solver status',r.get('preuve_solveur',{}).get('statut','not tested'))]:
        body += [f'<p>{label}: <code>{e(value)}</code></p>']
    extraction=d.get('extraction_ia')
    if extraction:
        mode = ('This study was analyzed through the live Nebius API.' if extraction.get('execution') == 'live'
                else 'This study uses an archived model response, not a live AI call.')
        body += [f'<p>Model: {e(extraction["modele"])}. Extraction fingerprint: <code>{e(extraction["empreinte"])}</code></p>', f'<p>Document values proposed via Nebius, checked locally and reviewed by a human. {mode}</p>']
    for doc in d['documents']:
        body += [f'<p>{e(doc["nom"])} SHA-256: <code>{e(doc["sha256"])}</code></p>']
    for anomaly in control['anomalies']:
        body += [f'<p>Original audit detail: {e(anomaly)}</p>']
    ident=e(d['id'])
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Contingency | Simulation report</title><link rel="stylesheet" href="/interface.css"><style>main{padding-top:36px;padding-bottom:50px}h1{margin-top:35px}h2{margin-top:40px}h3{margin-top:28px}code{overflow-wrap:anywhere}td{min-width:100px}blockquote{font-size:14px}.report-actions{display:flex;gap:14px;flex-wrap:wrap}@media print{.report-actions{display:none}main{padding:0}body{font-size:11pt}h1{font-size:26pt}h2{font-size:18pt;break-after:avoid}tr{break-inside:avoid}.tableau{overflow:visible}@page{size:A4;margin:15mm}}</style></head><body><main><div class="report-actions"><button onclick="window.print()">Print / save PDF</button><a class="lien secondaire" href="/api/'''+ident+'''/donnees">Download study data</a></div>'''+''.join(body)+'</main></body></html>'
