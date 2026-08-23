"""
SEA Audit Tool
Leest keyword-performance data uit een CSV, analyseert via de Claude API,
en genereert een gestructureerd Markdown-auditrapport.
"""

import pandas as pd


def load_keywords(csv_path: str) -> pd.DataFrame:
    """
    Leest een CSV met keyword-performance data in en valideert de kolommen.

    Verwachte kolommen: keyword, impressions, clicks, cost, conversions, CPA

    Args:
        csv_path: pad naar de CSV-file (bijv. "data/voorbeeld_keywords.csv")

    Returns:
        Een pandas DataFrame met de ingelezen data.

    Raises:
        FileNotFoundError: als het CSV-bestand niet bestaat.
        ValueError: als verplichte kolommen ontbreken.
    """
    # pandas leest de CSV in als een DataFrame — een tabel-achtige
    # structuur waar je makkelijk mee kunt filteren/sorteren/aggregeren.
    df = pd.read_csv(csv_path)

    # Verplichte kolommen die de rest van het script nodig heeft.
    verplichte_kolommen = ["keyword", "impressions", "clicks", "cost", "conversions", "CPA"]

    # Check of alle verplichte kolommen daadwerkelijk aanwezig zijn.
    # Dit voorkomt cryptische errors verderop in het script als iemand
    # een CSV aanlevert met net iets andere kolomnamen.
    ontbrekende_kolommen = [kolom for kolom in verplichte_kolommen if kolom not in df.columns]
    if ontbrekende_kolommen:
        raise ValueError(
            f"CSV mist verplichte kolommen: {ontbrekende_kolommen}. "
            f"Gevonden kolommen: {list(df.columns)}"
        )

    # Basale datatype-check: numerieke kolommen moeten ook echt numeriek zijn.
    # Als een CSV bijvoorbeeld "€ 486,50" i.p.v. "486.50" bevat, faalt dit
    # met een duidelijke foutmelding i.p.v. verderop stil verkeerd te rekenen.
    numerieke_kolommen = ["impressions", "clicks", "cost", "conversions", "CPA"]
    for kolom in numerieke_kolommen:
        if not pd.api.types.is_numeric_dtype(df[kolom]):
            raise ValueError(
                f"Kolom '{kolom}' bevat niet-numerieke waarden. "
                f"Check op valutasymbolen, komma's als scheidingsteken, of lege cellen."
            )

    return df


def summarize_performance(df: pd.DataFrame) -> dict:
    """
    Structureert de ruwe keyword-data tot een samenvatting die geschikt is
    om als context aan een LLM te geven: totalen, gemiddelden, en de
    duidelijkste uitschieters aan beide kanten.

    Args:
        df: DataFrame zoals geretourneerd door load_keywords()

    Returns:
        Een dict met samenvattende statistieken en top/underperformer-lijsten.
    """
    # --- Account-brede totalen ---
    totaal_impressions = int(df["impressions"].sum())
    totaal_clicks = int(df["clicks"].sum())
    totaal_cost = round(float(df["cost"].sum()), 2)
    totaal_conversions = int(df["conversions"].sum())

    # CTR en CVR opnieuw berekenen op accountniveau (niet het gemiddelde
    # van de losse CPA's pakken — dat vertekent bij ongelijke volumes).
    ctr = round((totaal_clicks / totaal_impressions) * 100, 2) if totaal_impressions > 0 else 0.0
    cvr = round((totaal_conversions / totaal_clicks) * 100, 2) if totaal_clicks > 0 else 0.0
    gemiddelde_cpa = round(totaal_cost / totaal_conversions, 2) if totaal_conversions > 0 else None

    # --- Underperformers: keywords met verkeer maar 0 conversies ---
    # Dit zijn de eerste kandidaten voor negative keywords of pauzeren.
    # Sorteer op cost aflopend, zodat de duurste "nul-resultaat"-keywords
    # bovenaan staan.
    zonder_conversies = (
        df[df["conversions"] == 0]
        .sort_values("cost", ascending=False)
        [["keyword", "impressions", "clicks", "cost"]]
        .to_dict("records")
    )

    # --- Underperformers: keywords met conversies maar CPA ver boven gemiddelde ---
    # Drempel: CPA hoger dan 2x het accountgemiddelde. Alleen zinvol als
    # er een gemiddelde CPA is (dus als er conversies zijn).
    hoge_cpa = []
    if gemiddelde_cpa is not None:
        drempel = gemiddelde_cpa * 2
        hoge_cpa = (
            df[(df["conversions"] > 0) & (df["CPA"] > drempel)]
            .sort_values("CPA", ascending=False)
            [["keyword", "clicks", "cost", "conversions", "CPA"]]
            .to_dict("records")
        )

    # --- Top performers: laagste CPA onder keywords met conversies ---
    top_performers = (
        df[df["conversions"] > 0]
        .sort_values("CPA", ascending=True)
        .head(5)
        [["keyword", "clicks", "cost", "conversions", "CPA"]]
        .to_dict("records")
    )

    return {
        "totalen": {
            "aantal_keywords": len(df),
            "impressions": totaal_impressions,
            "clicks": totaal_clicks,
            "cost": totaal_cost,
            "conversions": totaal_conversions,
            "ctr_procent": ctr,
            "cvr_procent": cvr,
            "gemiddelde_cpa": gemiddelde_cpa,
        },
        "zonder_conversies": zonder_conversies,
        "hoge_cpa_uitschieters": hoge_cpa,
        "top_performers": top_performers,
    }


def build_audit_prompt(samenvatting: dict) -> str:
    """
    Bouwt de prompt die naar Claude gaat op basis van de samengevatte data.

    Ontwerpprincipes van deze prompt:
    - Claude krijgt alleen de samenvatting, niet de ruwe CSV — voorkomt dat
      het model zelf (foutgevoelig) gaat optellen.
    - Een expliciete rol + duidelijke output-structuur, zodat het rapport
      voorspelbaar en herbruikbaar is.
    - Instructie om conclusies te onderbouwen met de cijfers die zijn
      meegegeven, niet met algemene SEA-wijsheden of externe benchmarks
      uit het model zelf.
    - Toon: direct, geen marketing-vaagtaal — vergelijkbaar met hoe een
      senior consultant het zelf zou opschrijven.

    Args:
        samenvatting: de dict zoals geretourneerd door summarize_performance()

    Returns:
        De volledige prompt-string die naar de Claude API gaat.
    """
    totalen = samenvatting["totalen"]

    prompt = f"""Je bent een senior Google Ads-specialist die een keyword-performance audit uitvoert voor een klant. Je krijgt hieronder samengevatte campagnedata. Schrijf een auditrapport in het Nederlands, gestructureerd in Markdown.

BELANGRIJK:
- Baseer al je conclusies uitsluitend op de cijfers hieronder. Verzin geen aannames over de klant, de branche of de website die niet uit de data volgen.
- Gebruik geen externe benchmarks, branchegemiddelden of vergelijkingen ("dit ligt boven/onder het gemiddelde van X%") die niet expliciet in de data hieronder staan. Interpreteer de cijfers alleen relatief aan elkaar (bijv. accountgemiddelde CPA versus keyword-CPA).
- Schrijf direct en concreet. Geen marketing-taal, geen "datagedreven full-funnel strategieën". Elk cijfer krijgt uitleg waarom het relevant is.
- Als de data te beperkt is voor een conclusie, zeg dat expliciet in plaats van te gokken.

ACCOUNTDATA

Totalen over de meetperiode:
- Aantal keywords: {totalen['aantal_keywords']}
- Impressions: {totalen['impressions']:,}
- Clicks: {totalen['clicks']:,}
- Kosten: €{totalen['cost']:,.2f}
- Conversies: {totalen['conversions']}
- CTR: {totalen['ctr_procent']}%
- CVR: {totalen['cvr_procent']}%
- Gemiddelde CPA: €{totalen['gemiddelde_cpa']}

Keywords zonder conversies (kandidaten voor negative keywords of pauzeren):
{samenvatting['zonder_conversies']}

Keywords met CPA meer dan 2x boven het accountgemiddelde (wel conversies, maar inefficiënt):
{samenvatting['hoge_cpa_uitschieters']}

Best presterende keywords (laagste CPA, met conversies):
{samenvatting['top_performers']}

GEVRAAGDE OUTPUT-STRUCTUUR

Schrijf het rapport met exact deze koppen:

## Performance-samenvatting
Twee tot drie zinnen: hoe presteert dit account op hoofdlijnen. Noem CTR, CVR en gemiddelde CPA met interpretatie (is dit gezond of niet, en waarom).

## Top performers
Bespreek de best presterende keywords. Wat maakt ze sterk (matchtype, CPA-niveau)? Wat is de aanbeveling (opschalen, budget prioriteren)?

## Underperformers
Bespreek de keywords zonder conversies en de keywords met hoge CPA apart. Wees concreet over welke keywords het probleem zijn en waarom (matchtype, mogelijke irrelevantie van de zoekterm).

## Negatieve keyword-suggesties
Baseer suggesties UITSLUITEND op de exacte keywords in de lijst "Keywords zonder conversies" hierboven. Leid per suggestie een negative keyword-term af die letterlijk in die keyword-tekst voorkomt. Voeg geen extra termen toe die niet direct uit die specifieke keywords zijn af te leiden, ook niet als ze plausibel lijken. Als de lijst leeg is, zeg dat er onvoldoende data is voor deze sectie.

## Aanbevelingen
3 tot 5 concrete, genummerde actiepunten. Elk actiepunt moet direct uitvoerbaar zijn (niet "verbeter de relevantie" maar bijvoorbeeld "zet keyword X op exact match en verlaag het bod met Y%").
"""
    return prompt


def call_claude_api(prompt: str) -> str:
    """
    Stuurt de audit-prompt naar de Claude API en retourneert het
    gegenereerde rapport als platte tekst (Markdown).

    Args:
        prompt: de volledige prompt-string van build_audit_prompt()

    Returns:
        De tekstinhoud van Claude's antwoord.
    """
    import os
    from dotenv import load_dotenv
    from anthropic import Anthropic

    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY niet gevonden. Check je .env-bestand.")

    client = Anthropic()

    print("Audit-analyse aanvragen bij Claude...")

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    rapport_tekst = message.content[0].text

    print(f"Rapport ontvangen ({message.usage.output_tokens} output-tokens).")

    return rapport_tekst


def save_report(rapport_tekst: str, output_dir: str = "output") -> str:
    """
    Schrijft het gegenereerde rapport weg als tijdgestempeld Markdown-bestand.

    Args:
        rapport_tekst: de tekstinhoud zoals geretourneerd door call_claude_api()
        output_dir: map waarin het rapport wordt opgeslagen

    Returns:
        Het volledige pad naar het opgeslagen bestand.
    """
    import os
    from datetime import datetime

    # Zorgt dat de output-map bestaat, ook als iemand hem per ongeluk
    # heeft verwijderd. exist_ok=True voorkomt een error als hij al bestaat.
    os.makedirs(output_dir, exist_ok=True)

    # Tijdstempel in bestandsnaam zodat je meerdere runs kunt vergelijken
    # zonder dat het vorige rapport wordt overschreven.
    tijdstempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    bestandsnaam = f"audit_rapport_{tijdstempel}.md"
    pad = os.path.join(output_dir, bestandsnaam)

    with open(pad, "w", encoding="utf-8") as f:
        f.write(rapport_tekst)

    print(f"Rapport opgeslagen: {pad}")
    return pad


# --- Tijdelijk testblok, verwijderen we straks als het script groeit ---
if __name__ == "__main__":
    keywords_df = load_keywords("data/voorbeeld_keywords.csv")
    print(f"Ingelezen: {len(keywords_df)} keywords")
    print()

    samenvatting = summarize_performance(keywords_df)

    prompt = build_audit_prompt(samenvatting)

    rapport = call_claude_api(prompt)
    save_report(rapport)

    print()
    print("=" * 60)
    print(rapport)
    print("=" * 60)