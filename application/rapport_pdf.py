"""Export PDF des rapports HTML (scan de flexibilité, scan de groupe), pour un dépôt Flex-e ou un envoi.

Imprime la page HTML avec un navigateur Chromium sans affichage (Playwright), au format A4. Le navigateur est
celui de CONTINGENCY_NAVIGATEUR, sinon Brave s'il est installé, sinon le Chromium de Playwright.
"""
from __future__ import annotations

import os
from pathlib import Path

BRAVE = Path("/usr/bin/brave-browser")


def navigateur() -> str | None:
    choix = os.environ.get("CONTINGENCY_NAVIGATEUR")
    if choix:
        return choix
    return str(BRAVE) if BRAVE.exists() else None


def html_vers_pdf(html: Path, pdf: Path) -> Path:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        chemin = navigateur()
        nav = p.chromium.launch(executable_path=chemin, args=["--headless=new"]) if chemin else p.chromium.launch()
        page = nav.new_page()
        page.goto(html.resolve().as_uri())
        page.emulate_media(media="print")
        page.pdf(path=str(pdf), format="A4", print_background=True,
                 margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        nav.close()
    return pdf
