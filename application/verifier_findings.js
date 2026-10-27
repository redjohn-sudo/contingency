const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={echappe:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),uiText:s=>s};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/revue_documentaire.js','utf8'),context);
const a={code:'sources_contradictoires',message:'conflict',champs:['plafond_kw'],preuves:[{document:0,ligne:1,citation:'Grid import: 640 kW'},{document:1,ligne:3,citation:'Grid import: 615 kW'}]};
const d={documents:[{nom:'signed-grid.pdf'},{nom:'second-grid.pdf'}],extraction_ia:{propositions:{plafond_kw:{valeur_modele:null}}}};
let html=context.findingStory(a,d);assert(html.includes('640 kW')&&html.includes('615 kW'));assert(html.includes('AI left grid power unset.'));assert.equal((html.match(/class="evidence-card"/g)||[]).length,2);
d.extraction_ia.propositions.plafond_kw.valeur_modele=640;html=context.findingStory(a,d);assert(!html.includes('AI left'));
a.preuves[0].citation='<img src=x onerror=alert(1)>';d.documents[0].nom='<script>bad</script>';html=context.findingStory(a,d);assert(!html.includes('<img'));assert(!html.includes('<script>'));
const battery={code:'capacite_incoherente',champs:['rendement'],preuves:[{document:0,ligne:1,citation:'Nominal capacity: 250 kWh'},{document:0,ligne:2,citation:'Usable capacity: 225 kWh'},{document:0,ligne:3,citation:'Maximum depth of discharge: 80 %'}]};
html=context.findingStory(battery,d);assert(html.includes('200 kWh')&&html.includes('225 kWh'));assert(!html.includes('AI left'));
console.log('4 finding checks passed: real opposing evidence, model attribution, escaping, battery arithmetic.');

const dutch={...battery,preuves:[{document:0,ligne:4,citation:'Nominale capaciteit: 250 kWh.'},{document:0,ligne:5,citation:'Bruikbare capaciteit: 225 kWh.'},{document:0,ligne:6,citation:'Maximale ontlaaddiepte: 80 % van de nominale capaciteit.'}]};
html=context.findingStory(dutch,d);assert(html.includes('Nominal capacity: 250 kWh'));assert(!html.includes('Bruikbare'));assert(html.includes('Maximum depth of discharge: 80%'));
assert(context.limitedStudyReason(battery).length>=30);assert(context.limitedStudyReason(battery).includes('unresolved'));
console.log('English facts preserve the numeric evidence; limited simulation has an explicit reason.');
