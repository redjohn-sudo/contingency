"""Garanties de sécurité du parcours guidé, réécrites le 26/09/2026 après la relecture d'Instinct (PR n°2).

Reprend sur l'interface guidée ce que vérifiaient les tests rangés dans tests_perimes/ :
A. une preuve invalide est marquée refusée et sa valeur n'est pas acceptable ; une autre valeur ne
   s'applique qu'après acceptation explicite (ex-verifier_structure_navigateur l. 45 à 70) ;
B. les points chiffrés du graphique et le rapport lisible (ex-verifier_demo_archivee l. 58 à 80) ;
C. modifier une valeur efface le résultat ; la variante 16 h vers 17 h crée une nouvelle révision,
   garde documents, profil, machine et durée, source l'hypothèse (document -1), et le rapport cite
   l'accord opérationnel (ex-verifier_demo_archivee l. 86 à 120 et verifier_structure_navigateur l. 89 à 92).
L'interdiction d'appel payant est couverte par verifier_revue_simplifiee (rejeu « recorded »).
Archive DeepSeek du 24/09, aucun appel IA.
"""
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import lancer_demo_archivee as demo
import serveur
from verifier_revue_simplifiee import ETAPE, URL, position, sans_defilement_horizontal

MOTIF = ("Hypothèse de variante : fin autorisée à 17 h au lieu de 16 h ; accord opérationnel à obtenir, "
         "document non modifié.")
# Libellés en français et leur traduction de english.js : l'interface guidée s'affiche en anglais.
REFUS = ('preuve refusée', 'rejected evidence', 'evidence rejected')
ALERTES_RAPPORT = ('Alertes documentaires maintenues', 'Unresolved document issues')
echecs = []


def verifier(condition, message):
    print(("ok   " if condition else "ÉCHEC ") + message)
    if not condition:
        echecs.append(message)


def ouvrir_analyse(page):
    page.goto(URL + '/demo')
    page.locator('#try-sample').wait_for()
    page.locator('#try-sample').click()
    page.wait_for_function(ETAPE.format(2))
    page.locator('#analyze-documents').click()
    page.wait_for_function(ETAPE.format(3), timeout=120000)


def main():
    ancien = serveur.DOSSIERS
    with tempfile.TemporaryDirectory() as temporaire:
        demo.configurer(temporaire)
        try:
            with TestClient(serveur.app) as client, sync_playwright() as outil:
                navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
                try:
                    contexte = navigateur.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                    erreurs = []

                    def servir(route):
                        requete = route.request
                        if not requete.url.startswith(URL + '/'):
                            route.abort()
                            return
                        adresse = urlsplit(requete.url)
                        reponse = client.request(requete.method, adresse.path + ('?' + adresse.query if adresse.query else ''),
                                                 content=requete.post_data_buffer,
                                                 headers={'content-type': requete.headers.get('content-type', 'application/json')})
                        route.fulfill(status=reponse.status_code, body=reponse.content,
                                      headers={k: v for k, v in reponse.headers.items()
                                               if k.lower() not in {'content-length', 'content-encoding', 'transfer-encoding'}})

                    contexte.route('**/*', servir)

                    def contexte_neuf():
                        # L'accueil ne s'affiche qu'à la première visite : un contexte neuf par partie.
                        c = navigateur.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                        c.route('**/*', servir)
                        return c

                    # A. Preuve invalide refusée, valeur appliquée seulement après acceptation.
                    page = contexte.new_page()
                    page.on('pageerror', lambda e: erreurs.append(str(e)))
                    ouvrir_analyse(page)
                    page.evaluate("""() => {
                      const p = dossier.extraction_ia.propositions;
                      p.plafond_kw = {...p.plafond_kw, valeur: null,
                        preuves: [...(p.plafond_kw.preuves || []), {repere: 'D1:P99:L1', citation: 'Autre référence invalide.', valide: false}]};
                      afficherPropositions();
                    }""")
                    # afficherPropositions() ajoute un nouveau rendu : on juge le dernier, celui de la preuve invalide.
                    bloc = page.locator('[data-proposition="plafond_kw"]').last
                    verifier('bloquee' in (bloc.get_attribute('class') or ''), "A. la proposition à preuve invalide est bloquée")
                    verifier(bloc.locator('.accepter-ia').is_disabled(), "A. valeur à preuve invalide : acceptation impossible")
                    texte_bloc = bloc.evaluate('e => e.textContent')
                    verifier(any(m in texte_bloc for m in REFUS), "A. la preuve invalide est marquée refusée")
                    # Un champ que l'archive propose avec une preuve valide : sa valeur ne doit s'appliquer
                    # qu'après la coche explicite (la réponse archivée n'a que 4 valeurs sur 7 utilisables).
                    champ, propose = page.evaluate("""() => {
                      for (const [cle, p] of Object.entries(dossier.extraction_ia.propositions)) {
                        const blocs = document.querySelectorAll(`[data-proposition="${cle}"]`);
                        const c = blocs.length && blocs[blocs.length - 1].querySelector('.accepter-ia');
                        if (c && !c.disabled && p.valeur !== null) return [cle, String(p.valeur)];
                      }
                      return [null, null];
                    }""")
                    verifier(champ is not None, f"A. un champ acceptable existe ({champ} = {propose})")
                    if champ:
                        page.evaluate(f"document.getElementById('v-{champ}').value = ''")
                        avant = page.locator(f'#v-{champ}').input_value()
                        page.evaluate(f"""() => {{ const b = document.querySelectorAll('[data-proposition="{champ}"]');
                          b[b.length - 1].querySelector('.accepter-ia').click(); }}""")
                        apres = page.locator(f'#v-{champ}').input_value()
                        verifier(avant == '' and float(apres) == float(propose),
                                 f"A. {champ} vide avant la coche, {apres} après acceptation explicite")
                    page.close()

                    # Parcours complet jusqu'au premier résultat (voir verifier_revue_simplifiee).
                    contexte = contexte_neuf()
                    page = contexte.new_page()
                    page.on('pageerror', lambda e: erreurs.append(str(e)))
                    ouvrir_analyse(page)
                    for _ in range(4):
                        page.locator('.accord-alerte:visible').check()
                        page.locator('#preparer').click()
                    for _ in range(7):
                        if page.locator('#hypotheses-demo:visible').count():
                            page.locator('#hypotheses-demo').click()
                        page.locator('#preparer').click()
                    page.wait_for_function(ETAPE.format(4))
                    page.locator('#accord').check()
                    page.locator('#calculer').click()
                    page.wait_for_function(ETAPE.format(5), timeout=120000)
                    identifiant = page.evaluate('dossier.id')
                    initial = client.get(f'/api/{identifiant}/donnees').json()

                    # D. Apports de l'équipe fusionnés le 26/09 (main du 23/09) : sensibilité et passages exacts.
                    verifier(page.locator('#sensibilite').count() == 1, "D. la section de sensibilité du planning s'affiche après le résultat")
                    verifier(page.evaluate("typeof boutonPreuve === 'function' && typeof boutonRepere === 'function'"),
                             "D. les boutons « Voir le passage exact » sont chargés")
                    # Clic réel sur la sensibilité : motif, accord, calcul local, résultats affichés.
                    zone = page.locator('#sensibilite')
                    zone.locator('summary').click()
                    zone.locator('#motif-sensibilite').fill('Test de bout en bout de la sensibilité du planning.')
                    zone.locator('#accord-sensibilite').check()
                    zone.locator('#calculer-sensibilite').click()
                    zone.locator('.resultats-sensibilite').wait_for(state='visible', timeout=120000)
                    verifier(zone.locator('.resultats-sensibilite').inner_text().strip() != '',
                             "D. comparaison de sensibilité calculée et affichée après accord")
                    # Clic réel sur un passage exact : le dialogue montre la citation dans son document.
                    boutons = page.locator('.preuve-contexte')
                    if boutons.count() == 0:
                        page.evaluate("document.body.insertAdjacentHTML('beforeend', (()=>{const f=Object.values(dossier.faits).find(x=>x.document>=0&&x.ligne>0);const l=dossier.documents[f.document].texte.split('\\n')[f.ligne-1];return boutonPreuve(f.document,f.ligne,l.trim().slice(0,40));})())")
                    citation = page.locator('.preuve-contexte').first.get_attribute('data-citation')
                    page.locator('.preuve-contexte').first.dispatch_event('click')  # bouton dans une étape repliée
                    dialogue = page.locator('#passage-preuve')
                    dialogue.wait_for(state='attached', timeout=10000)
                    verifier(dialogue.count() == 1 and citation and citation in dialogue.inner_text(),
                             "D. « Voir le passage exact » ouvre la citation dans son document")
                    page.evaluate("document.getElementById('passage-preuve')?.close?.(); document.getElementById('passage-preuve')?.remove()")

                    # B. Graphique et rapport lisible.
                    courbes = page.evaluate('donneesGraphique(dossier)')
                    verifier(len(courbes['retenu']) == 96, "B. 96 quarts d'heure dans le graphique")
                    verifier(courbes['initial'][32] == 553 and courbes['retenu'][32] == 480,
                             f"B. quart 32 : 553 kW avant, 480 kW après (lu {courbes['initial'][32]} et {courbes['retenu'][32]})")
                    verifier(courbes['retenu'][48] == 693 and courbes['plafond'] == 650,
                             f"B. quart 48 : 693 kW, plafond 650 kW (lu {courbes['retenu'][48]} et {courbes['plafond']})")
                    verifier(courbes['debut'] == 12 and courbes['fin'] == 16, "B. fenêtre 12 h à 16 h")
                    lien = page.locator('#rapport-lisible').get_attribute('href')
                    rapport_page = contexte.new_page()
                    rapport_page.goto(URL + lien if lien.startswith('/') else lien)
                    texte = rapport_page.locator('body').inner_text()
                    verifier(any(m in texte for m in ALERTES_RAPPORT), "B. le rapport lisible garde les alertes documentaires")
                    for largeur in (600, 2000):
                        rapport_page.set_viewport_size({'width': largeur, 'height': 1000})
                        verifier(sans_defilement_horizontal(rapport_page), f"B. rapport sans défilement horizontal à {largeur} px")
                    rapport_page.close()

                    # C. Modifier une valeur efface le résultat ; variante 16 h vers 17 h.
                    page.locator('#compare-again').click()
                    page.locator('#v-echeance_heure').fill('17')
                    page.locator('#v-echeance_heure').dispatch_event('input')
                    verifier(page.locator('#resultat').is_hidden() and page.locator('#validation').is_hidden(),
                             "C. valeur modifiée : ancien résultat et validation effacés")
                    page.locator('#s-echeance_heure').select_option('-1')
                    page.locator('#l-echeance_heure').fill('0')
                    page.locator('#m-echeance_heure').fill(MOTIF)
                    for _ in range(20):
                        if page.locator('#validation').is_visible():
                            break
                        for case in page.locator('.accord-alerte:visible').all():
                            if not case.is_checked():
                                case.check()
                        if page.locator('#hypotheses-demo:visible').count():
                            page.locator('#hypotheses-demo').click()
                        if page.locator('#preparer:visible').count():
                            page.locator('#preparer').click()
                        elif page.locator('#review-remaining:visible').count():
                            page.locator('#review-remaining').click()
                    page.wait_for_function(ETAPE.format(4))
                    verifier(page.locator('#calculer').is_disabled(), "C. nouveau calcul bloqué sans nouvel accord")
                    page.locator('#accord').check()
                    page.locator('#calculer').click()
                    page.wait_for_function(ETAPE.format(5), timeout=120000)
                    variante = client.get(f"/api/{page.evaluate('dossier.id')}/donnees").json()
                    verifier(variante['revision'] != initial['revision'], "C. nouvelle révision")
                    verifier([d['texte'] for d in variante['documents']] == [d['texte'] for d in initial['documents']],
                             "C. documents inchangés")
                    verifier(variante['profil'] == initial['profil'], "C. profil inchangé")
                    verifier(all(variante['faits'][k] == initial['faits'][k] for k in ('duree_heures', 'puissance_kw')),
                             "C. machine et durée inchangées")
                    verifier(variante['faits']['echeance_heure']['document'] == -1, "C. 17 h sourcée comme hypothèse (document -1)")
                    verifier(abs(variante['resultat']['retenu']['capacite_utile_kwh']) < 1e-6
                             and variante['resultat']['debuts_heures'] == [13.0], "C. départ 13 h, besoin de batterie nul")
                    verifier('Allow a 17:00 finish instead of 16:00' in page.locator('#outcome-story').inner_text(),
                             "C. le résultat compare 16 h et 17 h")
                    rapport = client.get(f"/api/{page.evaluate('dossier.id')}/rapport").text
                    verifier('accord opérationnel à obtenir' in rapport, "C. le rapport cite l'accord opérationnel à obtenir")
                    verifier(not erreurs, f"aucune erreur JavaScript ({erreurs[:2]})")
                finally:
                    navigateur.close()
        finally:
            serveur.DOSSIERS = ancien
    print(f"\n{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    sys.exit(1 if echecs else 0)


if __name__ == '__main__':
    main()
