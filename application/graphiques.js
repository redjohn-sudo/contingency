/* Comparaison des demandes avant stockage, limitée au premier bloc de 24 heures. */
function donneesGraphique(d) {
  const profil = d.profil_apercu;
  if (!Array.isArray(profil) || profil.length !== 96 || !d.resultat) return null;
  const valeurs = Object.fromEntries(Object.entries(d.faits).map(([cle, fait]) => [cle, fait.valeur]));
  const debutInitial = Math.round(valeurs.ouverture_heure * 4);
  const debutRetenu = Math.round(d.resultat.debuts_heures[0] * 4);
  const duree = Math.round(valeurs.duree_heures * 4);
  const ajouterMachine = debut => profil.map((puissance, i) =>
    puissance + (i >= debut && i < debut + duree ? valeurs.puissance_kw : 0));
  return {initial: ajouterMachine(debutInitial), retenu: ajouterMachine(debutRetenu),
    plafond: valeurs.plafond_kw, debut: debutRetenu / 4, fin: (debutRetenu + duree) / 4};
}

function afficherGraphique(d) {
  const zone = document.getElementById('graphique-planning');
  const donnees = donneesGraphique(d);
  if (!donnees) { zone.hidden = true; return; }
  zone.hidden = false;
  zone.innerHTML = `<h3>Pourquoi le planning change le besoin de stockage</h3>
    <p>Demande électrique avant stockage, premier bloc de 24 heures. Les dépassements du plafond doivent être couverts par le stockage dans ce scénario.</p>
    <div class="dessin-planning"></div>
    <p class="legende-planning"><span><i style="background:#92a0b9"></i>Départ au début de la fenêtre</span><span><i style="background:#3859f5"></i>Planning retenu</span><span><i style="background:#a93c48"></i>Plafond réseau</span></p>
    <small>Cycle machine retenu : ${donnees.debut.toLocaleString('en-GB')} à ${donnees.fin.toLocaleString('en-GB')} h. Courbes de demande, pas de flux réseau après action de la batterie.</small>`;
  const dessin = zone.querySelector('.dessin-planning');
  let derniereLargeur = -1;
  const tracer = () => {
    const largeur = Math.max(260, Math.round(dessin.clientWidth));
    if (largeur === derniereLargeur) return;
    derniereLargeur = largeur;
    const hauteur = 270, gauche = 45, droite = largeur - 14, haut = 24, bas = 234;
    const maximum = Math.max(1, Math.ceil(Math.max(donnees.plafond, ...donnees.initial, ...donnees.retenu) / 100) * 100);
    const x = i => gauche + (droite - gauche) * i / 96;
    const y = puissance => bas - (bas - haut) * puissance / maximum;
    const courbe = valeurs => valeurs.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)} L${x(i + 1)},${y(v)}`).join(' ');
    let grille = '';
    for (let i = 0; i <= 4; i++) {
      const puissance = maximum * i / 4;
      grille += `<line x1="${gauche}" y1="${y(puissance)}" x2="${droite}" y2="${y(puissance)}" stroke="#e4e9f2"/><text x="${gauche - 8}" y="${y(puissance) + 4}" text-anchor="end">${puissance}</text>`;
    }
    for (const heure of [0, 6, 12, 18, 24]) {
      grille += `<text x="${x(heure * 4)}" y="258" text-anchor="${heure === 24 ? 'end' : 'middle'}">${heure} h</text>`;
    }
    dessin.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${largeur} ${hauteur}" role="img" aria-labelledby="titre-courbe description-courbe" style="width:100%;display:block;font:12px system-ui;fill:#647087">
      <title id="titre-courbe">Demande électrique selon le planning</title>
      <desc id="description-courbe">First 24-hour block, 15-minute intervals. Grid limit: ${donnees.plafond} kilowatts. Machine scheduled from ${donnees.debut} to ${donnees.fin} hours. Demand before storage.</desc>
      <text x="${gauche}" y="14">kW</text>${grille}
      <path d="${courbe(donnees.initial)}" fill="none" stroke="#92a0b9" stroke-width="2" stroke-dasharray="5 4"/>
      <path d="${courbe(donnees.retenu)}" fill="none" stroke="#3859f5" stroke-width="2.5"/>
      <line x1="${gauche}" y1="${y(donnees.plafond)}" x2="${droite}" y2="${y(donnees.plafond)}" stroke="#a93c48" stroke-width="2" stroke-dasharray="8 5"/>
      </svg>`;
  };
  if (zone.observateur) zone.observateur.disconnect();
  zone.observateur = new ResizeObserver(() => requestAnimationFrame(tracer));
  zone.observateur.observe(dessin);
  tracer();
}
