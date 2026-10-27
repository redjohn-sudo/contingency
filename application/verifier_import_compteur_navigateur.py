"""Import CSV dans Brave, fichiers fictifs et réseau extérieur bloqué."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import serveur
from verifier_csv_compteur import export_synthetique
from verifier_live import demo_temporaire

URL = 'http://127.0.0.1:8766'
SORTIE = Path(__file__).resolve().parents[1] / '.local/import-compteur'


def export_heure_locale():
    """Export fictif en heure locale sans décalage autour du 26/10/2025 : l'heure répétée apparaît deux fois, en ordre."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    zone, t = ZoneInfo('Europe/Amsterdam'), datetime(2025, 10, 25, tzinfo=ZoneInfo('Europe/Amsterdam')).astimezone(timezone.utc)
    lignes = ['tijdstip;afname']
    while t < datetime(2025, 10, 28, tzinfo=zone).astimezone(timezone.utc):
        lignes.append(f"{t.astimezone(zone).strftime('%d-%m-%Y %H:%M')};{12.5 + t.hour % 3}")
        t += timedelta(minutes=15)
    return '\n'.join(lignes) + '\n'


def heure_repetee(navigateur, servir, erreurs, largeur=1200, cadre=False, encodage='utf-8'):
    """FB5 : l'heure répétée est proposée avec ses lignes, ses deux décalages et les empreintes des octets et du texte
    (P2-N), sans débordement avant confirmation (P2-O), confirmée d'un clic, tracée dans l'audit."""
    import hashlib
    contexte = navigateur.new_context(viewport={'width': 600 if cadre else largeur, 'height': 1100}, reduced_motion='reduce')
    contexte.route('**/*', servir)
    parent = contexte.new_page()
    parent.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
    if cadre:
        parent.goto(URL + '/verification-cadre')
        page = parent.frames[-1]
        page.wait_for_selector('#fichier')
    else:
        parent.goto(URL + '/import-compteur')
        page = parent
    octets = export_heure_locale().encode('utf-16-le' if encodage == 'utf-16le' else 'utf-8')
    page.locator('#fichier').set_input_files({'name': 'heure-locale.csv', 'mimeType': 'text/csv', 'buffer': octets})
    page.locator('#encodage').select_option(encodage)
    page.locator('#voir').click()
    page.locator('#conversion').wait_for(state='visible')
    page.locator('#fournisseur').fill('Portail fictif, test uniquement')
    for identifiant, valeur in {'colonne-temps': 'tijdstip', 'colonne-valeur': 'afname', 'unite': 'kwh_par_quart',
                                'marque': 'debut', 'format': '%d-%m-%Y %H:%M', 'decimal': '.'}.items():
        page.locator('#' + identifiant).select_option(valeur)
    page.locator('#compteur-unique').check()
    page.locator('#intervalles').check()
    page.locator('#convertir').click()
    page.locator('#heure').wait_for(state='visible')
    texte = page.locator('#heure-texte').inner_text()
    assert 'summer time (+02:00)' in texte and 'winter time (+01:00)' in texte, texte
    assert hashlib.sha256(octets).hexdigest() in texte, texte
    assert hashlib.sha256(export_heure_locale().encode()).hexdigest() in texte, texte
    # Les quatre heures répétées avec leurs deux mesures (12.5 en été, 13.5 en hiver) avant confirmation (FB5).
    rangees = page.locator('#heure-paires tr')
    assert rangees.count() == 5, rangees.count()
    for i in range(1, 5):
        rangee = rangees.nth(i).inner_text()
        assert '12.5' in rangee and '13.5' in rangee and '+02:00' in rangee and '+01:00' in rangee, rangee
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), largeur
    assert page.locator('#resultat').is_hidden()
    page.locator('#heure-confirmer').click()
    page.locator('#resultat').wait_for(state='visible')
    assert '100' in page.locator('#jours').inner_text() and 'winter time' in page.locator('#jours').inner_text()
    with parent.expect_download() as attente:  # le téléchargement appartient à la page, même depuis un cadre
        page.locator('#telecharger-audit').click()
    attente.value.save_as(SORTIE / 'import-heure-repetee.json')
    audit = json.loads((SORTIE / 'import-heure-repetee.json').read_text())
    assert [c['code'] for c in audit['journal']] == ['HEURE_REPETEE_INTERPRETEE']
    assert audit['provenance']['configuration']['heure_repetee_confirmee'] == audit['journal'][0]['parametres']['identite']
    assert audit['provenance']['empreinte_fichier_source'] == hashlib.sha256(octets).hexdigest()
    contexte.close()


def panne_reseau(navigateur, servir, erreurs):
    """P2-P : une requête qui n'aboutit pas donne un message de panne, pas une erreur de traitement des constats."""
    contexte = navigateur.new_context(viewport={'width': 1200, 'height': 1100}, reduced_motion='reduce')
    contexte.route('**/*', lambda route: route.abort('failed') if route.request.url.endswith('/api/compteur/convertir') else servir(route))
    page = contexte.new_page()
    page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
    page.goto(URL + '/import-compteur')
    page.locator('#fichier').set_input_files({'name': 'heure-locale.csv', 'mimeType': 'text/csv',
                                              'buffer': export_heure_locale().encode()})
    page.locator('#voir').click()
    page.locator('#conversion').wait_for(state='visible')
    page.locator('#fournisseur').fill('Portail fictif, test uniquement')
    for identifiant, valeur in {'colonne-temps': 'tijdstip', 'colonne-valeur': 'afname', 'unite': 'kwh_par_quart',
                                'marque': 'debut', 'format': '%d-%m-%Y %H:%M', 'decimal': '.'}.items():
        page.locator('#' + identifiant).select_option(valeur)
    page.locator('#compteur-unique').check()
    page.locator('#intervalles').check()
    page.locator('#convertir').click()
    page.wait_for_function('document.getElementById("erreur").textContent.length > 0')
    message = page.locator('#erreur').inner_text()
    assert 'could not be reached' in message and 'Cannot read' not in message, message
    # Réponse non JSON (passerelle en panne) : message clair avec le code HTTP.
    contexte.unroute('**/*')
    contexte.route('**/*', lambda route: route.fulfill(status=502, body='Bad gateway', content_type='text/plain')
                   if route.request.url.endswith('/api/compteur/convertir') else servir(route))
    page.locator('#convertir').click()
    page.wait_for_function('document.getElementById("erreur").textContent.includes("HTTP 502")')
    contexte.close()


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    erreurs, captures = [], []
    with demo_temporaire() as client, sync_playwright() as outil, patch.object(
            serveur, 'extraire_avec_nebius', side_effect=AssertionError('Aucun appel IA autorisé.')) as fournisseur:
        def servir(route):
            requete = route.request
            if not requete.url.startswith(URL + '/'):
                route.abort()
                return
            adresse = urlsplit(requete.url)
            if adresse.path == '/verification-cadre':
                route.fulfill(content_type='text/html', body=f'<iframe src="{URL}/import-compteur" style="width:390px;height:1000px;border:0"></iframe>')
                return
            reponse = client.request(requete.method, adresse.path,
                                     content=requete.post_data_buffer,
                                     headers={'content-type': requete.headers.get('content-type', 'application/json')})
            route.fulfill(status=reponse.status_code, body=reponse.content,
                          headers={k: v for k, v in reponse.headers.items()
                                   if k.lower() not in {'content-length', 'content-encoding', 'transfer-encoding'}})

        def importer(cadre):
            cadre.locator('#fichier').set_input_files({'name': 'export-fictif.csv', 'mimeType': 'text/csv',
                                                      'buffer': export_synthetique(autres=True).encode()})
            cadre.locator('#voir').click()
            cadre.locator('#conversion').wait_for(state='visible')
            assert '288 rows' in cadre.locator('#nombre-lignes').inner_text()
            cadre.locator('#fournisseur').fill('Portail fictif, test uniquement')
            for identifiant, valeur in {'colonne-temps': 'Tijd', 'colonne-valeur': 'Verbruik',
                                      'colonne-compteur': 'EAN', 'colonne-canal': 'Kanaal',
                                      'unite': 'kwh_par_quart', 'marque': 'debut', 'format': 'ISO8601',
                                      'colonne-statut': 'Status'}.items():
                cadre.locator('#' + identifiant).select_option(valeur)
            cadre.locator('#filtre-compteur').fill('SITE-A-FICTIF')
            cadre.locator('#filtre-canal').fill('Afname')
            cadre.locator('#statuts-valides').fill('V')
            cadre.locator('#statuts-estimes').fill('E')
            cadre.locator('#intervalles').check()
            cadre.locator('#convertir').click()
            cadre.locator('#resultat').wait_for(state='visible')
            assert '96 readings retained, 192 rows excluded' in cadre.locator('#resume').inner_text()
            assert '200.5 kW' in cadre.locator('#resume').inner_text()
            assert '4,812 kWh' in cadre.locator('#resume').inner_text()
            assert not cadre.locator('#erreur').inner_text()
            # FB5 : pointes du mois sous l'unité déclarée et sous l'autre unité, puis part du droit si on le saisit.
            pointes = cadre.locator('#pointes').inner_text()
            assert 'Peak if the values were average power (kW), kW' in pointes and '200.5' in pointes and '50.125' in pointes
            cadre.locator('#gtv').fill('400')
            assert '50.125 %' in cadre.locator('#pointes').inner_text()
            assert 'First day' in cadre.locator('#jours').inner_text()

        navigateur = outil.chromium.launch(executable_path='/usr/bin/brave-browser', headless=True)
        try:
            contexte = navigateur.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
            contexte.route('**/*', servir)
            page = contexte.new_page()
            page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
            page.goto(URL + '/import-compteur')
            importer(page)
            for identifiant, nom in [('telecharger-csv', 'profil.csv'), ('telecharger-audit', 'import.json')]:
                with page.expect_download() as attente:
                    page.locator('#' + identifiant).click()
                assert attente.value.suggested_filename == nom
                attente.value.save_as(SORTIE / nom)
            profil = (SORTIE / 'profil.csv').read_text()
            assert len(profil.splitlines()) == 97
            assert '2026-01-01T00:15:00+01:00,200.5' in profil
            audit = json.loads((SORTIE / 'import.json').read_text())
            assert audit['provenance']['statuts_source'] == {'V': 95, 'E': 1}
            assert audit['qualites'][5]['ligne_source'] == 17
            # Même audit que la commande : contrôle et journal compris (P2-D, FB5).
            assert audit['controle']['pointes_mensuelles'][0]['pointe_kw'] == 200.5 and audit['journal'] == []
            for largeur in (600, 2000):
                page.set_viewport_size({'width': largeur, 'height': 1100})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), largeur
                chemin = SORTIE / f'import-{largeur}.png'
                page.screenshot(path=str(chemin), full_page=True)
                captures.append(str(chemin))
            # Changer les conventions annule les anciens liens de téléchargement.
            page.locator('#statuts-estimes').fill('AUTRE')
            assert page.locator('#resultat').is_hidden()
            page.locator('#convertir').click()
            page.wait_for_function('document.getElementById("erreur").textContent.includes("Statut inconnu")')
            assert page.locator('#resultat').is_hidden()
            contexte.close()

            mobile = navigateur.new_context(viewport={'width': 600, 'height': 1100}, reduced_motion='reduce')
            mobile.route('**/*', servir)
            parent = mobile.new_page()
            parent.on('pageerror', lambda erreur: erreurs.append(str(erreur)))
            parent.goto(URL + '/verification-cadre')
            cadre = parent.frames[-1]
            cadre.wait_for_selector('#fichier')
            importer(cadre)
            assert cadre.evaluate('innerWidth') == 390
            assert cadre.evaluate('document.documentElement.scrollWidth <= innerWidth')
            chemin = SORTIE / 'import-390.png'
            parent.locator('iframe').screenshot(path=str(chemin))
            captures.append(str(chemin))
            mobile.close()
            for largeur in (600, 2000):
                heure_repetee(navigateur, servir, erreurs, largeur)
            heure_repetee(navigateur, servir, erreurs, cadre=True)
            heure_repetee(navigateur, servir, erreurs, encodage='utf-16le')
            panne_reseau(navigateur, servir, erreurs)
            fournisseur.assert_not_called()
        finally:
            navigateur.close()
    assert not erreurs, erreurs
    resultat = {'largeurs_verifiees': [600, 2000, 390], 'erreurs_javascript': erreurs,
                'telechargements_verifies': ['profil.csv', 'import.json'],
                'appels_ia': 0, 'captures': captures}
    (SORTIE / 'verification.json').write_text(json.dumps(resultat, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(resultat, ensure_ascii=False))


if __name__ == '__main__':
    main()
