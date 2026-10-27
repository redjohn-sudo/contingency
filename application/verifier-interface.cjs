const {lancerNavigateur, dossierCaptures, urlApplication, ouvrirDemo, revoirAlertes, revoirValeurs} = require('./outils-navigateur.cjs');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const navigateur = await lancerNavigateur();
  const captures = dossierCaptures('interface');
  try {
    const contexte = await navigateur.newContext({reducedMotion:'reduce'});
    await contexte.addInitScript(() => {try {localStorage.removeItem('contingency-welcome-v2');} catch {}});
    const page = await contexte.newPage();
    const erreurs = [];
    page.on('pageerror', erreur => {erreurs.push(erreur.message); console.error('Erreur navigateur :', erreur.message);});
    await ouvrirDemo(page);
    assert.equal(await page.locator('.proposition').count(), 7);
    assert.equal(await page.locator('#v-plafond_kw').inputValue(), '');
    await revoirAlertes(page);
    // Le bouton visible confirme la proposition avant de passer à la valeur suivante.
    await page.locator('#preparer').click();
    assert.equal(await page.locator('#v-plafond_kw').inputValue(), '650');
    assert.match(await page.locator('#m-plafond_kw').inputValue(), /Nebius/);
    await revoirValeurs(page, 6);
    assert(await page.locator('#calculer').isDisabled());
    await page.locator('#accord').check();
    await page.locator('#calculer').click();
    await page.locator('#resultat').waitFor({state:'visible'});
    assert.match(await page.locator('#outcome-story').innerText(), /45[.,]84 kWh/);
    for (const largeur of [600, 2000]) {
      await page.setViewportSize({width:largeur, height:1000});
      await page.screenshot({path:path.join(captures, `parcours-${largeur}.png`), fullPage:true});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.locator('#compare-again').click();
    await page.locator('#v-echeance_heure').fill('17');
    assert.equal(await page.locator('#resultat').isVisible(), false);
    assert.equal(await page.locator('#validation').isVisible(), false);

    const pdf = path.join(__dirname, '../evaluation-rag/sources/atlas.pdf');
    if (fs.existsSync(pdf)) {
      const importation = await contexte.newPage();
      importation.on('pageerror', erreur => erreurs.push(erreur.message));
      await importation.goto(urlApplication);
      await importation.locator('#documents').setInputFiles(pdf);
      let csv = 'fin_intervalle,puissance_kw\n';
      for (let i=1; i<=96; i++) csv += new Date(Date.UTC(2026,0,1,0,15*i)).toISOString()+',60\n';
      await importation.locator('#profil').setInputFiles({name:'profil-test.csv', mimeType:'text/csv', buffer:Buffer.from(csv)});
      const reponse = importation.waitForResponse(r => r.url().endsWith('/api/importer'));
      await importation.locator('#importer').click();
      const dossier = await (await reponse).json();
      assert.match(dossier.documents[0].texte, /181/);
      // Les tableaux sont rendus dans le panneau des sources, même quand il est replié.
      await importation.waitForFunction(() => document.querySelector('#sources summary')?.textContent.includes('atlas.pdf'));
      assert.equal(await importation.locator('#sources table').count(), 2);
      await importation.close();
    } else {
      console.log('SKIP tableaux PDF Atlas : evaluation-rag/sources/atlas.pdf absent.');
    }

    const mobile = await contexte.newPage();
    mobile.on('pageerror', erreur => erreurs.push(erreur.message));
    await mobile.setViewportSize({width:1000, height:1000});
    await mobile.setContent('<iframe title="mobile" style="width:390px;height:900px;border:0"></iframe>');
    const cadre = mobile.frames()[1];
    await ouvrirDemo(cadre);
    assert.equal(await cadre.evaluate(() => innerWidth), 390);
    assert(await cadre.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await mobile.locator('iframe').screenshot({path:path.join(captures, 'mobile-390.png')});
    assert.deepEqual(erreurs, []);
    console.log('Parcours réussi : accord explicite, calcul, invalidation et largeurs 390/600/2000 px.');
  } finally { await navigateur.close(); }
})().catch(erreur => {console.error(erreur); process.exitCode=1;});
