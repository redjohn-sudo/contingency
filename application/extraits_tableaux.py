"""Passages par ligne avec parent complet, sans interprétation des cellules."""

def construire(extraction):
    structure = extraction['structure']
    textes = structure.get('texts', [])
    tables = structure.get('tables', [])
    sources = {}
    passages = []
    empreinte = extraction['sha256']
    for numero, table in enumerate(tables):
        reference = table.get('self_ref', '#/tables/%s' % numero)
        identifiant = empreinte + ':' + reference
        pages = sorted({p['page_no'] for p in table.get('prov', [])})
        cellules = table['data']['table_cells']
        lignes = []
        for ligne in range(table['data']['num_rows']):
            presentes = [(i, c) for i, c in enumerate(cellules)
                         if c['start_row_offset_idx'] <= ligne < c['end_row_offset_idx']]
            presentes.sort(key=lambda paire: paire[1]['start_col_offset_idx'])
            if presentes:
                lignes.append({'ligne': ligne, 'texte': ' | '.join(c['text'] for _, c in presentes),
                               'cellules': [i for i, _ in presentes]})
        entetes = [c['text'] for c in cellules if c.get('column_header')]
        contexte = []
        explicites = {r['$ref'] for cle in ['captions', 'footnotes'] for r in table.get(cle, [])}
        for t in textes:
            if t.get('self_ref') in explicites or any(p['page_no'] in pages for p in t.get('prov', [])):
                contexte.append({'reference': t['self_ref'], 'texte': t['text'],
                                 'provenance': t.get('prov', []),
                                 'relation': 'lien_docling' if t.get('self_ref') in explicites else 'meme_page_non_validee'})
        sources[identifiant] = {'pages': pages, 'reference': reference, 'sha256': empreinte,
            'provenance': table.get('prov', []), 'cellules': cellules, 'lignes': lignes,
            'entetes_detectees': entetes, 'contexte': contexte,
            'statut': 'association_a_verifier',
            'limite': 'Le voisinage de page ne prouve pas qu’une note concerne cette ligne. Les renvois non explicites vers les autres pages restent à rechercher.'}
        for ligne in lignes:
            passages.append({'id': identifiant + ':r' + str(ligne['ligne']), 'parent': identifiant,
                'ligne': ligne['ligne'], 'cellules': ligne['cellules'],
                'texte': '\n'.join(entetes + [ligne['texte']]),
                'statut': 'association_a_verifier'})
    return {'sources': sources, 'passages': passages}


def contexte_passage(index, identifiant):
    """Restitue toute la table et son contexte sourcé, jamais une valeur isolée."""
    passage = next((p for p in index['passages'] if p['id'] == identifiant), None)
    if passage is None:
        raise ValueError('Passage inconnu')
    parent = index['sources'][passage['parent']]
    # Pas de troncature silencieuse : le futur appelant doit contrôler son budget.
    return {'passage': passage, 'source': parent,
            'texte': '\n'.join(['Ligne ciblée : ' + passage['texte'], 'Table complète :'] +
                [l['texte'] for l in parent['lignes']] + ['Contexte de page et liens, pertinence à vérifier :'] +
                [t['reference'] + ' : ' + t['texte'] for t in parent['contexte']])}
