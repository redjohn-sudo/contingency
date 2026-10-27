/* Configuration locale commune aux vérifications navigateur. */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {execFileSync} = require('node:child_process');

function chargerChromium() {
  if (process.env.CONTINGENCY_PLAYWRIGHT) return require(process.env.CONTINGENCY_PLAYWRIGHT).chromium;
  for (const nom of ['playwright', 'playwright-core']) {
    try { return require(nom).chromium; }
    catch (erreur) { if (erreur.code !== 'MODULE_NOT_FOUND') throw erreur; }
  }
  // Playwright Python contient le même pilote Node, sans seconde installation.
  const candidats = process.env.CONTINGENCY_PYTHON ? [process.env.CONTINGENCY_PYTHON] :
    [path.join(__dirname, '..', '.venv', 'bin', 'python'), 'python3'];
  for (const python of candidats) {
    try {
      const paquet = execFileSync(python, ['-c',
        'import pathlib,playwright; print(pathlib.Path(playwright.__file__).parent / "driver/package")'],
        {encoding:'utf8', stdio:['ignore', 'pipe', 'pipe']}).trim();
      return require(paquet).chromium;
    } catch {}
  }
  throw new Error('Playwright absent. Installer playwright ou playwright-core pour Node, ou définir CONTINGENCY_PYTHON vers le Python où Playwright est installé. CONTINGENCY_PLAYWRIGHT accepte aussi le chemin du module.');
}

async function lancerNavigateur() {
  const chromium = chargerChromium();
  const candidats = (process.env.PATH || '').split(path.delimiter)
    .flatMap(repertoire => ['brave-browser', 'brave', 'chromium', 'chromium-browser'].map(nom => path.join(repertoire, nom)));
  candidats.push('/Applications/Brave Browser.app/Contents/MacOS/Brave Browser');
  const executablePath = process.env.CONTINGENCY_NAVIGATEUR || candidats.find(chemin => fs.existsSync(chemin));
  return chromium.launch({headless:true, ...(executablePath ? {executablePath} : {})});
}

function dossierCaptures(nom) {
  const dossier = process.env.CONTINGENCY_CAPTURES || path.join(os.tmpdir(), 'contingency-' + nom);
  fs.mkdirSync(dossier, {recursive:true});
  return dossier;
}

const urlApplication = (process.env.URL_APPLICATION || 'http://127.0.0.1:8766').replace(/\/$/, '');

async function ouvrirDemo(page) {
  const reponse = await page.goto(urlApplication + '/demo');
  if (!reponse.ok()) throw new Error('Ouverture de la démo : HTTP ' + reponse.status());
  await page.waitForFunction(() => typeof factory !== 'undefined', null, {timeout:10000});
  await page.locator('#try-sample').click();
  await page.locator('#analyze-documents').click();
  await page.locator('.alerte-documentaire:visible').first().waitFor();
}

async function revoirAlertes(page) {
  const nombre = await page.locator('.alerte-documentaire').count();
  for (let i=0; i<nombre; i++) {
    await page.locator('.accord-alerte:visible').check();
    await page.locator('#preparer').click();
  }
}

async function revoirValeurs(page, nombre=7) {
  for (let i=0; i<nombre; i++) {
    if (await page.locator('#hypotheses-demo').isVisible()) await page.locator('#hypotheses-demo').click();
    await page.locator('#preparer').click();
  }
  await page.locator('#validation').waitFor({state:'visible'});
}

module.exports = {lancerNavigateur, dossierCaptures, urlApplication, ouvrirDemo, revoirAlertes, revoirValeurs};
