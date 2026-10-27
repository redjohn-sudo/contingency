/* Navigation exacte dans le texte lu. Aucune géométrie PDF n'est inventée. */
function textePreuve(fr, en) {
  return new URLSearchParams(location.search).get('lang') === 'en' ? en : fr;
}

function boutonPreuve(numero, ligne, citation) {
  const texte = dossier?.documents?.[numero]?.texte?.split('\n')[ligne - 1];
  if (!Number.isInteger(numero) || !Number.isInteger(ligne) || ligne < 1 ||
      typeof citation !== 'string' || !citation.trim() || !texte?.includes(citation)) return '';
  return `<button type="button" class="preuve-contexte secondaire" data-document="${numero}" data-ligne="${ligne}" data-citation="${echappe(citation)}">${textePreuve('Voir le passage exact', 'See the exact passage')}</button>`;
}

function boutonRepere(preuve) {
  const repere = /^D([1-9]\d*):(?:P([1-9]\d*):)?L([1-9]\d*)$/.exec(preuve.repere || '');
  if (!preuve.valide || !repere) return '';
  const numero = Number(repere[1]) - 1, ligne = Number(repere[3]);
  if (repere[2] && !dossier.documents[numero]?.lecture_ocr?.pages?.some(p =>
    p.page === Number(repere[2]) && p.plages_lignes?.some(plage => ligne >= plage.debut && ligne <= plage.fin))) return '';
  return boutonPreuve(numero, ligne, preuve.citation);
}

document.addEventListener('click', evenement => {
  const bouton = evenement.target.closest('.preuve-contexte');
  if (!bouton) return;
  const numero = Number(bouton.dataset.document), ligne = Number(bouton.dataset.ligne);
  const citation = bouton.dataset.citation, doc = dossier?.documents?.[numero];
  const lignes = doc?.texte?.split('\n');
  if (!citation || !lignes?.[ligne - 1]?.includes(citation)) return;
  document.getElementById('passage-preuve')?.remove();
  const dialogue = document.createElement('dialog');
  dialogue.id = 'passage-preuve';
  dialogue.setAttribute('aria-labelledby', 'titre-preuve');
  const titre = document.createElement('h2');
  titre.id = 'titre-preuve';
  titre.textContent = `${doc.nom} · ${textePreuve('ligne', 'line')} ${ligne}`;
  const fermer = document.createElement('button');
  fermer.textContent = textePreuve('Fermer', 'Close');
  fermer.onclick = () => dialogue.close();
  dialogue.append(titre, fermer);
  const contexte = document.createElement('pre');
  let occurrences = 0;
  for (let index = Math.max(0, ligne - 3); index < Math.min(lignes.length, ligne + 2); index++) {
    const element = document.createElement('div');
    element.append(document.createTextNode(`${index + 1}  `));
    let reste = lignes[index];
    if (index === ligne - 1) {
      while (reste.includes(citation)) {
        const position = reste.indexOf(citation), marque = document.createElement('mark');
        element.append(document.createTextNode(reste.slice(0, position)));
        marque.textContent = citation;
        element.append(marque);
        occurrences++;
        reste = reste.slice(position + citation.length);
      }
    }
    element.append(document.createTextNode(reste));
    contexte.append(element);
  }
  const limite = document.createElement('p');
  limite.textContent = textePreuve(
    'Correspondance exacte dans le texte extrait, pas une validation de la valeur. Pour un scan, vérifiez aussi le PDF original.',
    'Exact match in the extracted text, not validation of the value. For a scan, also check the original PDF.');
  dialogue.append(contexte, limite);
  if (occurrences > 1) {
    const ambiguite = document.createElement('p');
    ambiguite.textContent = textePreuve(`${occurrences} occurrences identiques sur cette ligne : toutes sont surlignées.`,
      `${occurrences} identical occurrences on this line: all are highlighted.`);
    dialogue.append(ambiguite);
  }
  if (doc.source_pdf) {
    const original = document.createElement('div');
    original.innerHTML = lienOriginal(numero, ligne);
    dialogue.append(original);
  }
  dialogue.addEventListener('close', () => { dialogue.remove(); bouton.focus(); });
  document.body.append(dialogue);
  dialogue.showModal();
});
