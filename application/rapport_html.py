"""Version imprimable du rapport généré : texte échappé, aucun HTML des documents exécuté."""
from html import escape


def texte_visible(texte):
    # Décoder seulement l'échappement produit par _texte_rapport, après avoir
    # reconnu les blocs. Un champ commençant par # ne devient donc pas un titre.
    return escape(texte.replace(r'\#', '#'))


def rendre_rapport(texte, identifiant):
    blocs, tableau = [], []

    def fermer_tableau():
        if not tableau:
            return
        lignes = []
        for i, cellules in enumerate(tableau):
            balise = 'th' if i == 0 else 'td'
            lignes.append('<tr>' + ''.join(f'<{balise}>{texte_visible(c)}</{balise}>' for c in cellules) + '</tr>')
        blocs.append('<div class="tableau"><table>' + ''.join(lignes) + '</table></div>')
        tableau.clear()

    for ligne in texte.splitlines():
        if ligne.startswith('|') and ligne.endswith('|'):
            cellules = [c.strip() for c in ligne[1:-1].split('|')]
            if all(c and set(c) <= set(':- ') for c in cellules):
                continue
            tableau.append(cellules)
            continue
        fermer_tableau()
        if ligne.startswith('## '):
            blocs.append('<h2>' + texte_visible(ligne[3:]) + '</h2>')
        elif ligne.startswith('# '):
            blocs.append('<h1>' + texte_visible(ligne[2:]) + '</h1>')
        elif ligne.strip():
            blocs.append('<p>' + texte_visible(ligne) + '</p>')
    fermer_tableau()
    return '''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Contingency · Rapport de simulation</title><style>
*{box-sizing:border-box}body{margin:0;color:#1f2926;background:white;font:16px/1.6 system-ui,sans-serif}
main{max-width:1050px;margin:auto;padding:clamp(20px,4vw,60px)}header{border-bottom:2px solid #2c6252;padding-bottom:18px}
h1{font-size:clamp(28px,4vw,42px);line-height:1.15}h2{font-size:22px;border-top:1px solid #ccd5d0;padding-top:20px;margin-top:32px}
p,td,th{overflow-wrap:anywhere}p{margin:12px 0}.tableau{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;vertical-align:top;border-bottom:1px solid #d9dfdc;padding:10px}th{font-weight:600;background:#f4f6f5}
button,a{font:inherit;color:#2c6252}button{background:white;border:1px solid #2c6252;padding:8px 14px;cursor:pointer;margin:8px 18px 8px 0}
@media print{body{font-size:10pt}main{padding:0;max-width:none}.outils{display:none}h1{font-size:22pt}h2{font-size:14pt;break-after:avoid}tr{break-inside:avoid}table{font-size:9pt}.tableau{overflow:visible}@page{size:A4;margin:15mm}}
</style></head><body><main><header><strong>Contingency</strong><div class="outils">
<button onclick="window.print()">Imprimer ou enregistrer en PDF</button>
<a href="/api/''' + escape(identifiant, quote=True) + '''/rapport">Télécharger la version Markdown</a>
</div></header>''' + '\n'.join(blocs) + '</main></body></html>'
