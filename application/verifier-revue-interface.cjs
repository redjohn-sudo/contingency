const {lancerNavigateur, dossierCaptures, ouvrirDemo, revoirAlertes, revoirValeurs} = require('./outils-navigateur.cjs');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const navigateur = await lancerNavigateur();
  const captures = dossierCaptures('revue');
  try {
    const contexte = await navigateur.newContext({viewport:{width:2000,height:1200}, reducedMotion:'reduce'});
    await contexte.addInitScript(() => {try {localStorage.removeItem('contingency-welcome-v2');} catch {}});
    const page = await contexte.newPage();
    const erreurs = [];
    page.on('pageerror', erreur => erreurs.push(erreur.message));
    await ouvrirDemo(page);
    assert(await page.locator('#preparer').isDisabled());
    const premiere = page.locator('.alerte-documentaire:visible');
    await premiere.locator('.detail-alerte summary').click();
    await premiere.locator('.motif-alerte').fill('');
    await premiere.locator('.accord-alerte').check();
    assert(await page.locator('#preparer').isDisabled());
    await premiere.locator('.motif-alerte').fill('Simulation de test uniquement. La contradiction reste à confirmer avant toute décision sur le site.');
    assert.equal(await premiere.locator('.accord-alerte').isChecked(), false);
    await revoirAlertes(page);
    await revoirValeurs(page);
    assert(await page.locator('#calculer').isDisabled());
    await page.locator('#accord').check();
    await page.locator('#calculer').click();
    await page.locator('#resultat').waitFor({state:'visible'});
    const lien = new URL(await page.locator('#rapport-lisible').getAttribute('href'), page.url());
    lien.pathname = lien.pathname.replace(/\/rapport-lisible$/, '/rapport');
    const rapport = await page.request.get(lien.href);
    assert.equal(rapport.status(), 200);
    assert.match(await rapport.text(), /Alertes documentaires maintenues/);
    for (const largeur of [600,2000]) {
      await page.setViewportSize({width:largeur,height:1000});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({path:path.join(captures, `revue-${largeur}.png`), fullPage:true});
    }
    await page.locator('[data-step="1"]').click();
    while (!await page.locator('.alerte-documentaire').first().isVisible()) {
      await page.locator('#review-remaining').click();
    }
    const alerte = page.locator('.alerte-documentaire:visible');
    if (!await alerte.locator('.decision-alerte').isVisible()) {
      await alerte.locator('.detail-alerte summary').click();
    }
    await alerte.locator('.decision-alerte').selectOption('non_applicable');
    assert.equal(await page.locator('#resultat').isVisible(), false);
    assert.equal(await page.locator('#validation').isVisible(), false);
    await alerte.locator('.motif-alerte').fill('Nouvelle hypothèse de test nécessitant une nouvelle validation explicite.');
    assert.equal(await alerte.locator('.accord-alerte').isChecked(), false);

    const mobile = await contexte.newPage();
    mobile.on('pageerror', erreur => erreurs.push(erreur.message));
    await mobile.setViewportSize({width:900,height:1000});
    await mobile.setContent('<iframe title="mobile" style="width:390px;height:900px;border:0"></iframe>');
    const cadre = mobile.frames()[1];
    await ouvrirDemo(cadre);
    assert.equal(await cadre.evaluate(() => innerWidth), 390);
    assert(await cadre.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await mobile.locator('iframe').screenshot({path:path.join(captures,'revue-390.png')});
    assert.deepEqual(erreurs, []);
    console.log('Revue bloquante, alertes dans le rapport, invalidation et 390/600/2000 px vérifiés.');
  } finally { await navigateur.close(); }
})().catch(erreur => {console.error(erreur); process.exitCode=1;});
