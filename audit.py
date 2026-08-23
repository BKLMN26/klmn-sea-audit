"""
SEA Audit Tool
Leest keyword-performance data uit een CSV, analyseert via de Claude API,
en genereert een gestructureerd Markdown-auditrapport.

Structuur van de output volgt de branche-gangbare indeling voor
account-audits (Diagnose & Audit, Waste, Fix & Optimize, Copy,
PMax & Scale, Report). Deze CSV-gebaseerde tool dekt alleen de
categorieën waarvoor keyword-performance-data een feitelijke basis
biedt: Diagnose & Audit (deels) en Waste. De overige categorieën
worden in het rapport expliciet als buiten scope benoemd.
"""

import os
from datetime import datetime

import pandas as pd


def load_keywords(csv_path: str) -> pd.DataFrame:
    """
    Leest een CSV met keyword-performance data in en valideert de kolommen.

    Verwachte kolommen: keyword, match_type, impressions, clicks, cost,
    conversions, CPA. match_type moet exact "Exact", "Phrase" of "Broad" zijn.

    Args:
        csv_path: pad naar de CSV-file (bijv. "data/voorbeeld_keywords.csv")

    Returns:
        Een pandas DataFrame met de ingelezen data.

    Raises:
        FileNotFoundError: als het CSV-bestand niet bestaat.
        ValueError: als verplichte kolommen ontbreken, numerieke kolommen
            niet numeriek zijn, of match_type onverwachte waarden bevat.
    """
    df = pd.read_csv(csv_path)

    verplichte_kolommen = [
        "keyword", "match_type", "impressions", "clicks", "cost", "conversions", "CPA"
    ]
    ontbrekende_kolommen = [kolom for kolom in verplichte_kolommen if kolom not in df.columns]
    if ontbrekende_kolommen:
        raise ValueError(
            f"CSV mist verplichte kolommen: {ontbrekende_kolommen}. "
            f"Gevonden kolommen: {list(df.columns)}"
        )

    numerieke_kolommen = ["impressions", "clicks", "cost", "conversions", "CPA"]
    for kolom in numerieke_kolommen:
        if not pd.api.types.is_numeric_dtype(df[kolom]):
            raise ValueError(
                f"Kolom '{kolom}' bevat niet-numerieke waarden. "
                f"Check op valutasymbolen, komma's als scheidingsteken, of lege cellen."
            )

    # match_type moet exact één van de drie toegestane waarden zijn.
    # Voorkomt stille verkeerde classificatie als een export een net
    # andere spelling gebruikt (bijv. "exact" met kleine letter, of
    # "Exact match" in plaats van "Exact").
    toegestane_match_types = {"Exact", "Phrase", "Broad"}
    onbekende_waarden = set(df["match_type"].unique()) - toegestane_match_types
    if onbekende_waarden:
        raise ValueError(
            f"Kolom 'match_type' bevat onverwachte waarden: {onbekende_waarden}. "
            f"Toegestaan: {toegestane_match_types}."
        )

    return df


def analyze_match_types(df: pd.DataFrame) -> list:
    """
    Groepeert performance per matchtype (Exact/Phrase/Broad) op basis van
    de match_type-kolom in de brondata. Structureel berekend in Python,
    niet aan het LLM overgelaten — voorkomt dat matchtype-conclusies
    inconsistent zijn tussen verschillende runs van dezelfde data.

    Args:
        df: DataFrame zoals geretourneerd door load_keywords()

    Returns:
        Lijst van dicts, één per matchtype, met aantal keywords, clicks,
        kosten, conversies en CPA.
    """
    breakdown = (
        df.groupby("match_type")
        .agg(
            aantal_keywords=("keyword", "count"),
            clicks=("clicks", "sum"),
            cost=("cost", "sum"),
            conversions=("conversions", "sum"),
        )
        .reset_index()
    )
    breakdown["cost"] = breakdown["cost"].round(2)
    breakdown["cpa"] = breakdown.apply(
        lambda row: round(row["cost"] / row["conversions"], 2) if row["conversions"] > 0 else None,
        axis=1
    )
    return breakdown.to_dict("records")


def format_match_type_breakdown(match_type_data: list) -> str:
    """
    Formatteert de matchtype-verdeling als expliciete, geëtiketteerde
    tekstregels in plaats van een ruwe lijst van dicts. Doel: voorkomen
    dat het model categorieën samenvoegt of herbenoemt bij het overnemen
    in het rapport — elke regel is ondubbelzinnig aan één matchtype
    gekoppeld.

    Args:
        match_type_data: output van analyze_match_types()

    Returns:
        Multi-line string, één regel per matchtype.
    """
    regels = []
    for groep in match_type_data:
        cpa_tekst = f"€{groep['cpa']}" if groep['cpa'] is not None else "n.v.t. (0 conversies)"
        regels.append(
            f"- Matchtype {groep['match_type']}: {groep['aantal_keywords']} keywords, "
            f"{groep['clicks']} clicks, €{groep['cost']} kosten, "
            f"{groep['conversions']} conversies, CPA {cpa_tekst}"
        )
    return "\n".join(regels)


def find_duplicate_keywords(df: pd.DataFrame) -> list:
    """
    Detecteert keywords met identieke tekst (na normaliseren naar kleine
    letters), ongeacht matchtype. Bewust over matchtypes heen gezocht:
    dezelfde term op meerdere matchtypes tegelijk is zelf een vorm van
    interne concurrentie (cannibalization), niet alleen letterlijke
    duplicaten binnen één matchtype.

    Beperking: vangt alleen exacte tekstduplicaten binnen deze CSV, geen
    semantische varianten en geen cross-campagne duplicaten.

    Args:
        df: DataFrame zoals geretourneerd door load_keywords()

    Returns:
        Lijst van dicts met keyword, matchtype, genormaliseerde vorm en
        performance, voor elk keyword dat een duplicaat heeft.
    """
    df = df.copy()
    df["genormaliseerd"] = df["keyword"].str.strip().str.lower()

    duplicaten = (
        df[df.duplicated("genormaliseerd", keep=False)]
        .sort_values("genormaliseerd")
        [["keyword", "match_type", "genormaliseerd", "clicks", "cost", "conversions"]]
        .to_dict("records")
    )
    return duplicaten


def summarize_performance(df: pd.DataFrame) -> dict:
    """
    Structureert de ruwe keyword-data tot een samenvatting die geschikt is
    om als context aan een LLM te geven: totalen, gemiddelden, matchtype-
    verdeling, duplicaten, en de duidelijkste uitschieters aan beide kanten.

    Args:
        df: DataFrame zoals geretourneerd door load_keywords()

    Returns:
        Een dict met samenvattende statistieken en top/underperformer-lijsten.
    """
    totaal_impressions = int(df["impressions"].sum())
    totaal_clicks = int(df["clicks"].sum())
    totaal_cost = round(float(df["cost"].sum()), 2)
    totaal_conversions = int(df["conversions"].sum())

    ctr = round((totaal_clicks / totaal_impressions) * 100, 2) if totaal_impressions > 0 else 0.0
    cvr = round((totaal_conversions / totaal_clicks) * 100, 2) if totaal_clicks > 0 else 0.0
    gemiddelde_cpa = round(totaal_cost / totaal_conversions, 2) if totaal_conversions > 0 else None

    # Keywords zonder conversies — inclusief matchtype, zodat het model
    # dat niet zelf hoeft af te leiden of te gokken.
    zonder_conversies = (
        df[df["conversions"] == 0]
        .sort_values("cost", ascending=False)
        [["keyword", "match_type", "impressions", "clicks", "cost"]]
        .to_dict("records")
    )

    hoge_cpa = []
    if gemiddelde_cpa is not None:
        drempel = gemiddelde_cpa * 2
        hoge_cpa = (
            df[(df["conversions"] > 0) & (df["CPA"] > drempel)]
            .sort_values("CPA", ascending=False)
            [["keyword", "match_type", "clicks", "cost", "conversions", "CPA"]]
            .to_dict("records")
        )

    top_performers = (
        df[df["conversions"] > 0]
        .sort_values("CPA", ascending=True)
        .head(5)
        [["keyword", "match_type", "clicks", "cost", "conversions", "CPA"]]
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
        "match_type_verdeling": analyze_match_types(df),
        "duplicate_keywords": find_duplicate_keywords(df),
    }


def load_intake_context(intake_path: str) -> str:
    """
    Leest het ingevulde intake-bestand in als platte tekst, zodat het als
    context-blok vóór de accountdata in de prompt kan worden geplaatst.

    Args:
        intake_path: pad naar het ingevulde intake-markdown-bestand.

    Returns:
        De volledige inhoud van het intake-bestand als string.
    """
    with open(intake_path, "r", encoding="utf-8") as f:
        return f.read()


def build_audit_prompt(samenvatting: dict, intake_context: str = "") -> str:
    """
    Bouwt de prompt die naar Claude gaat op basis van de samengevatte data.

    Args:
        samenvatting: de dict zoals geretourneerd door summarize_performance()
        intake_context: optionele vrije tekst uit het ingevulde
            intake-bestand. Leeg als er geen intake is meegegeven.

    Returns:
        De volledige prompt-string die naar de Claude API gaat.
    """
    totalen = samenvatting["totalen"]

    intake_blok = ""
    if intake_context.strip():
        intake_blok = f"""
KLANTCONTEXT (uit intake, door de consultant ingevuld)
{intake_context}

Gebruik deze context om terminologie en interpretatie aan te passen.
Gebruik budget/CPA-doelen uit de intake als referentiepunt bij
interpretatie, niet als vervanging van de brondata hieronder.
"""

    prompt = f"""Je bent een senior Google Ads-specialist die een keyword-performance audit uitvoert voor een klant. Je krijgt hieronder samengevatte campagnedata{" en klantcontext" if intake_context.strip() else ""}. Schrijf een auditrapport in het Nederlands, gestructureerd in Markdown.

BELANGRIJK:
- Baseer al je conclusies uitsluitend op de cijfers hieronder. Verzin geen aannames over de klant, de branche of de website die niet uit de data volgen.
- Gebruik geen externe benchmarks, branchegemiddelden of vergelijkingen die niet expliciet in de data hieronder staan.
- Schrijf direct en concreet. Geen marketing-taal. Elk cijfer krijgt uitleg waarom het relevant is.
- Als de data te beperkt is voor een conclusie, zeg dat expliciet in plaats van te gokken.
- Neem structureel berekende cijfers (matchtype-verdeling, totalen) exact over zoals aangeleverd. Voeg categorieën nooit samen, hernoem ze niet, en verander de gegeven aantallen niet.
- Deze audit dekt alleen de categorieën Diagnose & Audit (deels) en Waste. Doe GEEN uitspraken over Quality Score, advertentietekst, PMax, biedstrategie-mechaniek, landingspagina's, audiences, geo/schedule of periode-vergelijkingen — daar is in deze data geen basis voor. Benoem deze expliciet als buiten scope in de laatste sectie.
{intake_blok}
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

Matchtype-verdeling (structureel berekend uit de match_type-kolom — dit zijn EXACT drie aparte categorieën: Broad, Exact en Phrase. Rapporteer alle drie apart met hun eigen cijfers. Voeg nooit twee categorieën samen):
{format_match_type_breakdown(samenvatting['match_type_verdeling'])}

Keywords zonder conversies (kandidaten voor negative keywords of pauzeren):
{samenvatting['zonder_conversies']}

Keywords met CPA meer dan 2x boven het accountgemiddelde:
{samenvatting['hoge_cpa_uitschieters']}

Mogelijke duplicate keywords (identieke tekst, mogelijk over meerdere matchtypes):
{samenvatting['duplicate_keywords']}

Best presterende keywords:
{samenvatting['top_performers']}

GEVRAAGDE OUTPUT-STRUCTUUR

Schrijf het rapport met exact deze koppen:

## Diagnose & Audit
Twee tot drie zinnen op basis van de totalen. Vermeld daarna in één zin dat accountscore, conversion tracking-controle, campagnestructuur en impression share buiten deze data-audit vallen.

## Waste
Behandel in deze volgorde:
1. Keywords zonder conversies, met negative-keyword-suggesties uitsluitend gebaseerd op die exacte keywords.
2. Keywords met hoge CPA — per keyword concreet waarom.
3. Matchtype-verdeling — rapporteer Broad, Exact en Phrase apart zoals hierboven aangeleverd.
4. Duplicate keywords, indien niet leeg — wat dit betekent voor cannibalization.

## Aanbevelingen
3 tot 5 concrete, genummerde, direct uitvoerbare actiepunten.

## Buiten scope van deze audit
Eén compacte alinea over wat ontbreekt voor een volledige account-audit en welke data daarvoor nodig zou zijn.
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
    os.makedirs(output_dir, exist_ok=True)

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

    intake_pad = "intake_voorbeeld.md"
    intake_tekst = ""
    if os.path.exists(intake_pad):
        intake_tekst = load_intake_context(intake_pad)
        print(f"Intake-context geladen uit: {intake_pad}")
    else:
        print(f"Geen intake-bestand gevonden op '{intake_pad}' — audit draait zonder klantcontext.")

    prompt = build_audit_prompt(samenvatting, intake_context=intake_tekst)

    rapport = call_claude_api(prompt)
    save_report(rapport)

    print()
    print("=" * 60)
    print(rapport)
    print("=" * 60)