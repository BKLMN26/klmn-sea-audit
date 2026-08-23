# SEA Audit Tool

Python-tool die Google Ads keyword-performance data (CSV) analyseert via de Claude API en een gestructureerd Markdown-auditrapport genereert: performance-samenvatting, top/underperformers, negative keyword-suggesties en concrete aanbevelingen.

Gebouwd als portfolio-project om SEA-analysekennis te combineren met praktische Python- en LLM-integratie-ervaring.

## Wat het doet

1. Leest keyword-performance data in uit een CSV (keyword, match_type, impressions, clicks, cost, conversions, CPA)
2. Structureert de data: totalen, matchtype-verdeling, top performers, underperformers, hoge-CPA-uitschieters, duplicate keywords
3. Stuurt een gestructureerde prompt naar de Claude API voor analyse
4. Genereert een auditrapport in Markdown, opgeslagen in `output/`

## Waarom deze aanpak

- **Data-samenvatting vóór de LLM-call, niet de ruwe CSV.** Voorkomt dat het model zelf (foutgevoelig) gaat optellen over ruwe rijen.
- **Structureel berekende cijfers (matchtype-verdeling, totalen) worden expliciet en geëtiketteerd aangeleverd, niet als ruwe data.** Eerste versie liet matchtype afleiden uit haakjes/quotes-notatie in de keyword-tekst zelf — een CSV-parser strip aanhalingstekens automatisch, waardoor phrase-match-keywords stil verkeerd werden geclassificeerd als broad match. Fix: matchtype is nu een aparte, expliciete kolom in de brondata, met validatie die onverwachte waarden direct laat falen in plaats van ze stil fout te classificeren.
- **Prompt met expliciete anti-verzinnen-instructies.** Eerste versie van de prompt liet het model externe benchmarks en niet-onderbouwde negative-keyword-suggesties toevoegen. Prompt is aangescherpt om conclusies strikt te binden aan de meegegeven cijfers — zie `audit.py` voor de instructies.
- **Vaste output-structuur.** Elk rapport heeft dezelfde koppen (Diagnose & Audit, Waste, Aanbevelingen, Buiten scope), wat consistentie en herbruikbaarheid geeft.

## Installatie

```bash
git clone https://github.com/BKLMN26/klmn-sea-audit.git
cd klmn-sea-audit
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Maak een `.env`-bestand aan (zie `.env.example`) met je eigen Anthropic API-key:ANTHROPIC_API_KEY=jouw-eigen-key-hier

Een key aanmaken kan via [console.anthropic.com](https://console.anthropic.com).

## Gebruik

```bash
python audit.py
```

Dit leest `data/voorbeeld_keywords.csv` in en genereert een rapport in `output/`.

Om je eigen data te analyseren: vervang de CSV of pas het pad aan in `audit.py` (regel met `load_keywords(...)`). Verwachte kolommen: `keyword, match_type, impressions, clicks, cost, conversions, CPA`. De kolom `match_type` moet exact `Exact`, `Phrase` of `Broad` bevatten.

Let op: dit is een vereenvoudigd, zelf ontworpen CSV-schema om de audit-logica te demonstreren — geen directe parser voor een ruwe Google Ads-export. Een echte export gebruikt andere kolomnamen, volledige matchtype-labels (`Exact match` in plaats van `Exact`) en mogelijk andere getalnotatie. Voor gebruik met een echte export is een mapping-stap nodig die kolomnamen en notatie normaliseert.

## Voorbeeldoutput

Zie `output/audit_rapport_20260823_183932.md` voor een gegenereerd voorbeeldrapport op basis van de meegeleverde test-data.

## Scope

Bewust uitgesloten om dit een gericht, af te ronden weekend-project te houden:
- Geen webinterface — command-line only
- Geen live Google Ads API-koppeling — werkt op CSV-export
- Geen database — bestandsgebaseerd
- Geen deployment — lokaal uit te voeren
- Geen visualisaties/grafieken — tekstueel Markdown-rapport

## Tech stack

- Python 3.14
- [Anthropic Claude API](https://docs.claude.com) (claude-sonnet-4-5)
- pandas — data-verwerking
- python-dotenv — configuratiebeheer

## Auteur

Bram Koeleman — [KLMN Digital](https://klmndigital.nl)