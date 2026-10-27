# Contingency

A grid-capacity diagnostic for Dutch businesses stuck behind grid congestion (*netcongestie*). From three documents, the export of quarter-hour meter values (*kwartierwaarden*), the connection contract (ATO), and a grid-operator invoice, it shows the headroom left under the current contract and the traps, and backs every conclusion with its source line. Reports come out in French and Dutch.

<p align="center"><img src="demos/contingency.gif" width="640" alt="Contingency reading a factory's grid documents and flagging that the battery quote's numbers do not add up"></p>

> A prototype, built at a hackathon in Amsterdam. No real client. It has been exercised on real public data: 5,358 German industrial sites (VEA), the same verdict as the ACM in the NorthC case, model Liander and Stedin invoices read by an LLM, the official Kenter API format parsed.

## What it does

- **Reads the three documents.** Meter export, connection contract, invoice; extraction is checked against the source, and nothing is asserted without a line reference.
- **Capacity headroom.** What the current contract allows, where the quarter-hour peaks are, and what fixes the contracted capacity and the battery size, recomputed without the heaviest days (a calculation, not a recommendation).
- **Flexibility scan** (`scan_flex.py`): from a year of quarter-hour values, a report shaped to the legal plan of a Flex-e flexibiliteitsscan (bijlage 4.12.1), with a checklist of what still has to be filled in.
- **Shared-connection sizing** (`scan_groupe.py`): a transport contract split between neighbouring businesses.
- **Explicit validation.** The user reviews and accepts each assumption before anything is computed; the report states what is measured and what is not (standby power is out of the model, a Flex-e scan still needs an on-site visit by an energieadviseur).

## Stack

Python. A local FastAPI/uvicorn workshop (`serveur.py`) drives a plain HTML/JS/CSS interface; `numpy`, `scipy` and OR-Tools do the sizing, `pypdfium2` reads the PDFs, the LLM call reads the documents. Bilingual (FR / NL) HTML and PDF reports.

## Run

Requires Python 3.12+.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python application/serveur.py
```

The LLM document reading expects an API key in the environment (see the brain configuration). The sizing and report code runs offline.

## License

Source-available under the **PolyForm Noncommercial License 1.0.0** ([`LICENSE`](LICENSE)). You may read, run and modify Contingency for any noncommercial purpose. Commercial use requires written permission from the author.
