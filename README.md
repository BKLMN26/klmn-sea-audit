# SEA Audit Tool

Python-tool die Google Ads keyword-performance data (CSV) analyseert via de Claude API en een gestructureerd Markdown-auditrapport genereert: diagnose met impression share-analyse, periode-vergelijking, waste-detectie en concrete aanbevelingen.

Gebouwd als portfolio-project om SEA-analysekennis te combineren met praktische Python- en LLM-integratie-ervaring. De rapportstructuur volgt de branche-gangbare indeling voor account-audits (Diagnose & Audit, Waste, Report); categorieën waarvoor dit CSV-schema geen data bevat (Fix & Optimize, Copy, PMax & Scale) worden expliciet als buiten scope benoemd in plaats van door de AI ingevuld met aannames.

## Wat het doet

1. Leest keyword-performance data in uit een CSV (keyword, match_type, impressions, clicks, cost, conversions, CPA, impression_share)
2. Optioneel: leest een tweede CSV in met dezelfde structuur voor de vorige periode, voor month-over-month vergelijking
3. Structureert de data: totalen, impression share-diagnose met groeikansen, matchtype-verdeling, periode-delta's, top performers, underperformers, hoge-CPA-uitschieters, duplicate keywords
4. Stuurt een gestructureerde prompt naar de Claude API voor analyse
5. Genereert een auditrapport in Markdown, opgeslagen in `output/`

## Waarom deze aanpak

- **Data-samenvatting en alle berekeningen vóór de LLM-call, niet de ruwe CSV.** Totalen, matchtype-verdeling, impression share-groeikansen en periode-delta's worden in Python berekend en als expliciete, geëtiketteerde tekst aangeleverd. Voorkomt dat het model zelf (foutgevoelig) gaat optellen of categorieën door elkaar haalt.
- **Matchtype is een expliciete kolom in de brondata, niet afgeleid uit notatie.** Eerste versie leidde matchtype af uit haakjes/quotes in de keyword-tekst — een CSV-parser strip aanhalingstekens automatisch, waardoor phrase-match-keywords stil verkeerd werden geclassificeerd als broad match. Fix: matchtype is nu een aparte kolom, met validatie die onverwachte waarden direct laat falen.
- **Prompt met expliciete anti-verzinnen-instructies.** Eerste versie liet het model externe benchmarks en niet-onderbouwde negative-keyword-suggesties (synoniemen die niet letterlijk in de keyword-tekst voorkomen) toevoegen. Prompt is aangescherpt om conclusies en suggesties strikt te binden aan de letterlijke meegegeven cijfers en tekst.
- **Vaste output-structuur.** Elk rapport heeft dezelfde koppen (Diagnose & Audit, Periode-vergelijking, Waste, Aanbevelingen, Buiten scope), wat consistentie en herbruikbaarheid geeft.

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

Dit leest `data/voorbeeld_keywords.csv` in en genereert een rapport in `output/`. Als `data/voorbeeld_keywords_vorige_periode.csv` bestaat, wordt automatisch ook een periode-vergelijking meegenomen — anders draait de audit als single-snapshot.

Om je eigen data te analyseren: vervang de CSV('s) of pas het pad aan in `audit.py`. Verwachte kolommen: `keyword, match_type, impressions, clicks, cost, conversions, CPA, impression_share`. De kolom `match_type` moet exact `Exact`, `Phrase` of `Broad` bevatten. `impression_share` is een percentage (0-100).

Let op: dit is een vereenvoudigd, zelf ontworpen CSV-schema om de audit-logica te demonstreren — geen directe parser voor een ruwe Google Ads-export. Een echte export gebruikt andere kolomnamen, volledige matchtype-labels en mogelijk andere getalnotatie of een `--`-placeholder bij impression share op laag zoekvolume. Voor gebruik met een echte export is een mapping-stap nodig die kolomnamen en notatie normaliseert.

## Voorbeeldoutput

Zie `output/audit_rapport_20260824_201757.md` voor een gegenereerd voorbeeldrapport op basis van de meegeleverde test-data, inclusief periode-vergelijking.

## Scope

Bewust uitgesloten om dit een gericht, af te ronden project te houden:
- Geen webinterface — command-line only
- Geen live Google Ads API-koppeling — werkt op CSV-export
- Geen database — bestandsgebaseerd
- Geen deployment — lokaal uit te voeren
- Geen visualisaties/grafieken — tekstueel Markdown-rapport
- Geen Quality Score, advertentietekst, PMax, biedstrategie, landingspagina's, audiences of geo/schedule-analyse — vereist andere databronnen dan een keyword-CSV kan bevatten; het rapport benoemt dit expliciet als buiten scope in plaats van te gokken

## Tech stack

- Python 3.14
- [Anthropic Claude API](https://docs.claude.com) (claude-sonnet-4-5)
- pandas — data-verwerking
- python-dotenv — configuratiebeheer

## Auteur

Bram Koeleman — [KLMN Digital](https://klmndigital.nl)