"""Exécute les trois vérificateurs CJS avec des serveurs locaux temporaires."""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

import uvicorn
import lancer_demo_archivee as demo
import serveur

RACINE = Path(__file__).resolve().parents[1]


def main():
    specification = importlib.util.spec_from_file_location('traction_isolee', RACINE / 'traction/serveur.py')
    traction = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(traction)
    ancien = serveur.DOSSIERS
    with tempfile.TemporaryDirectory() as temporaire, socket.socket() as prise:
        demo.configurer(temporaire)
        prise.bind(('127.0.0.1', 0))
        adresse_locale = f'http://127.0.0.1:{prise.getsockname()[1]}'

        async def application_de_test(scope, receive, send):
            # L'atelier n'autorise que le port 8766 et TestClient. L'adaptateur
            # de test présente ce port temporaire comme TestClient, uniquement
            # pour ses propres Host/Origin. Les autres origines restent refusées.
            if scope['type'] == 'http':
                entetes = []
                for cle, valeur in scope['headers']:
                    if cle == b'host' and valeur == adresse_locale.removeprefix('http://').encode():
                        valeur = b'testserver'
                    elif cle == b'origin' and valeur == adresse_locale.encode():
                        valeur = b'http://127.0.0.1:8766'
                    entetes.append((cle, valeur))
                scope = dict(scope, headers=entetes)
            await serveur.app(scope, receive, send)

        application = uvicorn.Server(uvicorn.Config(application_de_test, log_level='warning'))
        fil_application = threading.Thread(target=application.run, kwargs={'sockets': [prise]}, daemon=True)
        accueil = ThreadingHTTPServer(('127.0.0.1', 0), traction.Gestionnaire)
        fil_accueil = threading.Thread(target=accueil.serve_forever, daemon=True)
        fil_application.start()
        fil_accueil.start()
        try:
            limite = time.monotonic() + 15
            while not application.started:
                if not fil_application.is_alive() or time.monotonic() > limite:
                    raise RuntimeError('Le serveur temporaire ne démarre pas.')
                time.sleep(.05)
            environnement = dict(os.environ,
                CONTINGENCY_PYTHON=sys.executable,
                URL_APPLICATION=adresse_locale,
                URL_TRACTION=f'http://127.0.0.1:{accueil.server_port}/')
            for script in ('application/verifier-interface.cjs',
                           'application/verifier-revue-interface.cjs',
                           'traction/verifier-interface.cjs'):
                print('Exécution : ' + script, flush=True)
                subprocess.run(['node', str(RACINE / script)], cwd=RACINE,
                               env=environnement, check=True, timeout=180)
        finally:
            application.should_exit = True
            accueil.shutdown()
            accueil.server_close()
            fil_application.join(timeout=10)
            fil_accueil.join(timeout=10)
            serveur.DOSSIERS = ancien


if __name__ == '__main__':
    main()
