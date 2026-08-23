\# SEA Audit Tool



Python-tool die Google Ads keyword-performance data (CSV) analyseert via de Claude API en een gestructureerd Markdown-auditrapport genereert: performance-samenvatting, top/underperformers, negative keyword-suggesties en concrete aanbevelingen.



Gebouwd als portfolio-project om SEA-analysekennis te combineren met praktische Python- en LLM-integratie-ervaring.



\## Wat het doet



1\. Leest keyword-performance data in uit een CSV (keyword, impressions, clicks, cost, conversions, CPA)

2\. Structureert de data: totalen, top performers, underperformers, hoge-CPA-uitschieters

3\. Stuurt een gestructureerde prompt naar de Claude API voor analyse

4\. Genereert een auditrapport in Markdown, opgeslagen in `output/`



\## Waarom deze aanpak



\- \*\*Data-samenvatting vóór de LLM-call, niet de ruwe CSV.\*\* Voorkomt dat het model zelf (foutgevoelig) gaat optellen over ruwe rijen.

\- \*\*Prompt met expliciete anti-verzinnen-instructies.\*\* Eerste versie van de prompt liet het model externe benchmarks en niet-onderbouwde negative-keyword-suggesties toevoegen. Prompt is aangescherpt om conclusies strikt te binden aan de meegegeven cijfers — zie `audit.py` voor de instructies.

\- \*\*Vaste output-structuur.\*\* Elk rapport heeft dezelfde vijf secties, wat consistentie en herbruikbaarheid geeft.



\## Installatie



git clone https://github.com/BKLMN26/klmn-sea-audit.git

cd klmn-sea-audit

python -m venv venv

.\\venv\\Scripts\\Activate.ps1      # Windows PowerShell

pip install -r requirements.txt



Maak een `.env`-bestand aan (zie `.env.example`) met je eigen Anthropic API-key:



ANTHROPIC\_API\_KEY=jouw-eigen-key-hier



Een key aanmaken kan via console.anthropic.com



\## Gebruik



python audit.py



Dit leest `data/voorbeeld\_keywords.csv` in en genereert een rapport in `output/`.



Om je eigen data te analyseren: vervang de CSV of pas het pad aan in `audit.py` (regel met `load\_keywords(...)`). Verwachte kolommen: `keyword, impressions, clicks, cost, conversions, CPA`.



\## Voorbeeldoutput



Zie `output/audit\_rapport\_20260823\_101848.md` voor een gegenereerd voorbeeldrapport op basis van de meegeleverde test-data.



\## Scope



Bewust uitgesloten om dit een gericht, af te ronden weekend-project te houden:

\- Geen webinterface — command-line only

\- Geen live Google Ads API-koppeling — werkt op CSV-export

\- Geen database — bestandsgebaseerd

\- Geen deployment — lokaal uit te voeren

\- Geen visualisaties/grafieken — tekstueel Markdown-rapport



\## Tech stack



\- Python 3.14

\- Anthropic Claude API (claude-sonnet-4-5)

\- pandas — data-verwerking

\- python-dotenv — configuratiebeheer



\## Auteur



Bram Koeleman — KLMN Digital - (klmndigital.nl)

