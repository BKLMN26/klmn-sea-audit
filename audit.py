"""
SEA Audit Tool
Leest keyword-performance data uit een CSV, analyseert via de Claude API,
en genereert een gestructureerd Markdown-auditrapport.

Structuur van de output volgt de branche-gangbare indeling voor
account-audits (Diagnose & Audit, Waste, Fix & Optimize, Copy,
PMax & Scale, Report). Deze CSV-gebaseerde tool dekt:
- Diagnose & Audit: totalen + impression share-diagnose
- Waste: volledig
- Report: periode-vergelijking (indien vorige-periode-data is aangeleverd)
De overige categorieën (Fix & Optimize, Copy, PMax & Scale) worden in het
rapport expliciet als buiten scope benoemd, omdat daarvoor andere databronnen
nodig zijn dan dit CSV-schema kan bevatten.
"""

import os
from datetime import datetime

import pandas as pd


def load_keywords(csv_path: str) -> pd.DataFrame:
    """
    Leest een CSV met keyword-performance data in en valideert de kolommen.

    Verwachte kolommen: keyword, match_type, impressions, clicks, cost,
    conversions, CPA, impression_share. match_type moet exact "Exact",
    "Phrase" of "Broad" zijn. impression_share is een percentage (0-100).

    Bekende beperking: dit valideert niet tegen Google Ads' eigen "--"
    placeholder voor impression share bij te laag zoekvolume — een echte
    export kan die waarde bevatten en zou hier stuklopen op de numerieke
    check. Niet opgelost in deze versie.

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
        "keyword", "match_type", "impressions", "clicks",
        "cost", "conversions", "CPA", "impression_share",
    ]
    ontbrekende_kolommen = [kolom for kolom in verplichte_kolommen if kolom not in df.columns]
    if ontbrekende_kolommen:
        raise ValueError(
            f"CSV mist verplichte kolommen: {ontbrekende_kolommen}. "
            f"Gevonden kolommen: {list(df.columns)}"
        )

    numerieke_kolommen = ["impressions", "clicks", "cost", "conversions", "CPA", "impression_share"]
    for kolom in numerieke_kolommen:
        if not pd.api.types.is_numeric_dtype(df[kolom]):
            raise ValueError(
                f"Kolom '{kolom}' bevat niet-numerieke waarden. "
                f"Check op valutasymbolen, komma's als scheidingsteken, "
                f"'--'-placeholders, of lege cellen."
            )

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
    niet aan het LLM overgelaten.

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
    tekstregels — voorkomt dat het model categorieën samenvoegt of
    herbenoemt bij het overnemen in het rapport.

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
    letters), ongeacht matchtype.

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


def analyze_impression_share(df: pd.DataFrame, gemiddelde_cpa) -> dict:
    """
    Berekent de gemiddelde impression share van het account en identificeert
    keywords met onbenut groeipotentieel: efficiënte CPA (op of onder het
    accountgemiddelde) gecombineerd met een impression share onder 80%.

    Drempel van 80% is een vuistregel, geen brancheconstante — keywords
    die al ruim boven die grens zitten, hebben weinig extra volume te
    winnen via een hoger bod/budget.

    Args:
        df: DataFrame zoals geretourneerd door load_keywords()
        gemiddelde_cpa: accountgemiddelde CPA, of None als er geen
            conversies zijn

    Returns:
        Dict met gemiddelde impression share en een lijst groeikansen,
        gesorteerd op kosten aflopend (grootste budget-impact eerst),
        gelimiteerd tot de top 5.
    """
    gemiddelde_is = round(float(df["impression_share"].mean()), 1)

    groeikansen = []
    if gemiddelde_cpa is not None:
        groeikansen = (
            df[
                (df["conversions"] > 0)
                & (df["CPA"] <= gemiddelde_cpa)
                & (df["impression_share"] < 80)
            ]
            .sort_values("cost", ascending=False)
            .head(5)
            [["keyword", "match_type", "CPA", "impression_share", "clicks", "cost", "conversions"]]
            .to_dict("records")
        )

    return {
        "gemiddelde_impression_share": gemiddelde_is,
        "groeikansen": groeikansen,
    }


def format_impression_share(is_data: dict) -> str:
    """
    Formatteert de impression share-analyse als leesbare tekst voor de prompt.

    Args:
        is_data: output van analyze_impression_share()

    Returns:
        Multi-line string.
    """
    regels = [f"Gemiddelde impression share over het account: {is_data['gemiddelde_impression_share']}%"]
    if is_data["groeikansen"]:
        regels.append(
            "Keywords met efficiënte CPA (op of onder accountgemiddelde) maar "
            "impression share onder 80% — mogelijk groeipotentieel bij hoger bod/budget:"
        )
        for kw in is_data["groeikansen"]:
            regels.append(
                f"- {kw['keyword']} ({kw['match_type']}): CPA €{kw['CPA']}, "
                f"impression share {kw['impression_share']}%, {kw['clicks']} clicks, "
                f"€{kw['cost']} kosten, {kw['conversions']} conversies"
            )
    else:
        regels.append("Geen keywords voldoen aan de groeikans-criteria (efficiënte CPA + impression share onder 80%).")
    return "\n".join(regels)


def compare_totals(huidige_totalen: dict, vorige_totalen: dict) -> dict:
    """
    Vergelijkt accounttotalen tussen twee periodes en berekent absolute en
    procentuele verandering per metric. Delta's worden hier al berekend,
    zodat het model dit niet zelf hoeft uit te rekenen.

    Args:
        huidige_totalen: "totalen"-dict van de huidige periode
        vorige_totalen: "totalen"-dict van de vorige periode

    Returns:
        Dict per metric met huidige waarde, vorige waarde, absolute delta
        en procentuele delta.
    """
    metrics = [
        "impressions", "clicks", "cost", "conversions",
        "ctr_procent", "cvr_procent", "gemiddelde_cpa",
    ]
    vergelijking = {}
    for metric in metrics:
        huidige_waarde = huidige_totalen.get(metric)
        vorige_waarde = vorige_totalen.get(metric)
        if huidige_waarde is None or vorige_waarde is None:
            vergelijking[metric] = {
                "huidig": huidige_waarde, "vorig": vorige_waarde,
                "delta_abs": None, "delta_procent": None,
            }
            continue
        delta_abs = round(huidige_waarde - vorige_waarde, 2)
        delta_procent = round((delta_abs / vorige_waarde) * 100, 1) if vorige_waarde != 0 else None
        vergelijking[metric] = {
            "huidig": huidige_waarde, "vorig": vorige_waarde,
            "delta_abs": delta_abs, "delta_procent": delta_procent,
        }
    return vergelijking


def format_totals_comparison(vergelijking: dict) -> str:
    """
    Formatteert de periode-vergelijking van accounttotalen als expliciete
    tekstregels met vooraf berekende delta's.

    Args:
        vergelijking: output van compare_totals()

    Returns:
        Multi-line string, één regel per metric.
    """
    labels = {
        "impressions": "Impressions",
        "clicks": "Clicks",
        "cost": "Kosten (€)",
        "conversions": "Conversies",
        "ctr_procent": "CTR (%)",
        "cvr_procent": "CVR (%)",
        "gemiddelde_cpa": "Gemiddelde CPA (€)",
    }
    regels = []
    for key, label in labels.items():
        data = vergelijking[key]
        if data["delta_abs"] is None:
            regels.append(f"- {label}: huidig {data['huidig']}, vorig {data['vorig']} (geen vergelijking mogelijk)")
            continue
        richting = "+" if data["delta_abs"] >= 0 else ""
        regels.append(
            f"- {label}: huidig {data['huidig']}, vorig {data['vorig']}, "
            f"verschil {richting}{data['delta_abs']} ({richting}{data['delta_procent']}%)"
        )
    return "\n".join(regels)


def compare_keyword_shifts(huidige_df: pd.DataFrame, vorige_df: pd.DataFrame) -> dict:
    """
    Vergelijkt keywords tussen twee periodes: welke zijn nieuw, welke zijn
    verdwenen, en welke bestaande keywords hebben de grootste CPA-verschuiving.

    Matching gebeurt op genormaliseerde keyword-tekst (kleine letters,
    getrimd). CPA-vergelijking geldt alleen voor keywords met conversies
    in BEIDE periodes — anders is een CPA-delta niet zinvol interpreteerbaar.

    Args:
        huidige_df: DataFrame van de huidige periode
        vorige_df: DataFrame van de vorige periode

    Returns:
        Dict met nieuwe keywords, verdwenen keywords, grootste CPA-stijgers
        en grootste CPA-dalers (elk top 3).
    """
    huidige = huidige_df.copy()
    vorige = vorige_df.copy()
    huidige["_norm"] = huidige["keyword"].str.strip().str.lower()
    vorige["_norm"] = vorige["keyword"].str.strip().str.lower()

    huidige_set = set(huidige["_norm"])
    vorige_set = set(vorige["_norm"])

    nieuwe_keywords = (
        huidige[huidige["_norm"].isin(huidige_set - vorige_set)]
        [["keyword", "match_type", "clicks", "cost", "conversions"]]
        .to_dict("records")
    )
    verdwenen_keywords = (
        vorige[vorige["_norm"].isin(vorige_set - huidige_set)]
        [["keyword", "match_type", "clicks", "cost", "conversions"]]
        .to_dict("records")
    )

    gemeenschappelijk = huidige_set & vorige_set
    merge = pd.merge(
        huidige[huidige["_norm"].isin(gemeenschappelijk)][["_norm", "keyword", "CPA", "conversions", "cost"]],
        vorige[vorige["_norm"].isin(gemeenschappelijk)][["_norm", "CPA", "conversions", "cost"]],
        on="_norm",
        suffixes=("_huidig", "_vorig"),
    )
    merge = merge[(merge["conversions_huidig"] > 0) & (merge["conversions_vorig"] > 0)].copy()
    merge["cpa_delta"] = (merge["CPA_huidig"] - merge["CPA_vorig"]).round(2)

    grootste_stijgers = (
        merge[merge["cpa_delta"] > 0]
        .sort_values("cpa_delta", ascending=False)
        .head(3)
        [["keyword", "CPA_vorig", "CPA_huidig", "cpa_delta"]]
        .to_dict("records")
    )
    grootste_dalers = (
        merge[merge["cpa_delta"] < 0]
        .sort_values("cpa_delta", ascending=True)
        .head(3)
        [["keyword", "CPA_vorig", "CPA_huidig", "cpa_delta"]]
        .to_dict("records")
    )

    return {
        "nieuwe_keywords": nieuwe_keywords,
        "verdwenen_keywords": verdwenen_keywords,
        "grootste_stijgers": grootste_stijgers,
        "grootste_dalers": grootste_dalers,
    }


def summarize_performance(df: pd.DataFrame, vorige_df: pd.DataFrame = None) -> dict:
    """
    Structureert de ruwe keyword-data tot een samenvatting die geschikt is
    om als context aan een LLM te geven: totalen, impression share,
    matchtype-verdeling, duplicaten, uitschieters, en optioneel een
    periode-vergelijking.

    Args:
        df: DataFrame zoals geretourneerd door load_keywords() (huidige periode)
        vorige_df: optioneel, DataFrame van de vorige periode. Als None,
            bevat de output geen periode-vergelijking.

    Returns:
        Een dict met samenvattende statistieken, top/underperformer-lijsten,
        en (indien vorige_df gegeven) een periode-vergelijking.
    """
    totaal_impressions = int(df["impressions"].sum())
    totaal_clicks = int(df["clicks"].sum())
    totaal_cost = round(float(df["cost"].sum()), 2)
    totaal_conversions = int(df["conversions"].sum())

    ctr = round((totaal_clicks / totaal_impressions) * 100, 2) if totaal_impressions > 0 else 0.0
    cvr = round((totaal_conversions / totaal_clicks) * 100, 2) if totaal_clicks > 0 else 0.0
    gemiddelde_cpa = round(totaal_cost / totaal_conversions, 2) if totaal_conversions > 0 else None

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

    resultaat = {
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
        "impression_share": analyze_impression_share(df, gemiddelde_cpa),
        "zonder_conversies": zonder_conversies,
        "hoge_cpa_uitschieters": hoge_cpa,
        "top_performers": top_performers,
        "match_type_verdeling": analyze_match_types(df),
        "duplicate_keywords": find_duplicate_keywords(df),
        "periode_vergelijking": None,
    }

    if vorige_df is not None:
        vorige_samenvatting = summarize_performance(vorige_df)
        resultaat["periode_vergelijking"] = {
            "totalen_vergelijking": compare_totals(resultaat["totalen"], vorige_samenvatting["totalen"]),
            "keyword_verschuivingen": compare_keyword_shifts(df, vorige_df),
        }

    return resultaat


def load_intake_context(intake_path: str) -> str:
    """
    Leest het ingevulde intake-bestand in als platte tekst.

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
    heeft_periode_data = samenvatting.get("periode_vergelijking") is not None

    intake_blok = ""
    if intake_context.strip():
        intake_blok = f"""
KLANTCONTEXT (uit intake, door de consultant ingevuld)
{intake_context}

Gebruik deze context om terminologie en interpretatie aan te passen.
Gebruik budget/CPA-doelen uit de intake als referentiepunt bij
interpretatie, niet als vervanging van de brondata hieronder.
"""

    periode_blok = ""
    if heeft_periode_data:
        pv = samenvatting["periode_vergelijking"]
        periode_blok = f"""
PERIODE-VERGELIJKING (huidige versus vorige periode — delta's zijn al berekend, reken dit niet zelf opnieuw uit)

Accounttotalen:
{format_totals_comparison(pv['totalen_vergelijking'])}

Nieuwe keywords deze periode:
{pv['keyword_verschuivingen']['nieuwe_keywords']}

Verdwenen keywords (niet meer aanwezig deze periode):
{pv['keyword_verschuivingen']['verdwenen_keywords']}

Grootste CPA-stijgingen (keywords met conversies in beide periodes):
{pv['keyword_verschuivingen']['grootste_stijgers']}

Grootste CPA-dalingen (keywords met conversies in beide periodes):
{pv['keyword_verschuivingen']['grootste_dalers']}
"""

    scope_uitsluitingen = [
        "Quality Score-componenten", "advertentietekst", "PMax-asset groups",
        "biedstrategie-mechaniek", "landingspagina's", "audiences", "geo/schedule-instellingen",
    ]
    if not heeft_periode_data:
        scope_uitsluitingen.append("periode-vergelijkingen")
    scope_tekst = ", ".join(scope_uitsluitingen)

    prompt = f"""Je bent een senior Google Ads-specialist die een keyword-performance audit uitvoert voor een klant. Je krijgt hieronder samengevatte campagnedata{" en klantcontext" if intake_context.strip() else ""}. Schrijf een auditrapport in het Nederlands, gestructureerd in Markdown.

BELANGRIJK:
- Baseer al je conclusies uitsluitend op de cijfers hieronder. Verzin geen aannames over de klant, de branche of de website die niet uit de data volgen.
- Gebruik geen externe benchmarks, branchegemiddelden of vergelijkingen die niet expliciet in de data hieronder staan.
- Schrijf direct en concreet. Geen marketing-taal. Elk cijfer krijgt uitleg waarom het relevant is.
- Als de data te beperkt is voor een conclusie, zeg dat expliciet in plaats van te gokken.
- Neem structureel berekende cijfers (matchtype-verdeling, totalen, periode-delta's) exact over zoals aangeleverd. Voeg categorieën nooit samen, hernoem ze niet, verander de gegeven aantallen niet, en reken delta's niet zelf opnieuw uit.
- Voor negative keyword-suggesties: leid per suggestie een term af die LETTERLIJK voorkomt in de tekst van het genoemde keyword. Gebruik geen synoniemen, verwante woorden of vertalingen (bijvoorbeeld: als het keyword "gratis" bevat, stel dan "gratis" voor — niet "voor niets", "kosteloos" of andere varianten die niet letterlijk in de keyword-tekst staan).
- Deze audit dekt Diagnose & Audit (inclusief impression share) en Waste volledig, en Periode-vergelijking indien aangeleverd. Doe GEEN uitspraken over {scope_tekst} — daar is in deze data geen basis voor. Benoem deze expliciet als buiten scope in de laatste sectie.
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

Impression share:
{format_impression_share(samenvatting['impression_share'])}
{periode_blok}
Matchtype-verdeling (structureel berekend — EXACT drie aparte categorieën: Broad, Exact en Phrase. Rapporteer alle drie apart, voeg nooit samen):
{format_match_type_breakdown(samenvatting['match_type_verdeling'])}

Keywords zonder conversies (kandidaten voor negative keywords of pauzeren):
{samenvatting['zonder_conversies']}

Keywords met CPA meer dan 2x boven het accountgemiddelde:
{samenvatting['hoge_cpa_uitschieters']}

Mogelijke duplicate keywords:
{samenvatting['duplicate_keywords']}

Best presterende keywords:
{samenvatting['top_performers']}

GEVRAAGDE OUTPUT-STRUCTUUR

Schrijf het rapport met exact deze koppen:

## Diagnose & Audit
Twee tot drie zinnen op basis van de totalen. Bespreek daarna de impression share: het gemiddelde, en concreet de keywords met groeipotentieel als die lijst niet leeg is. Vermeld tot slot dat accountscore, conversion tracking-controle en campagnestructuur buiten deze data-audit vallen.

## Periode-vergelijking
Als er periode-vergelijkingsdata is aangeleverd: bespreek de belangrijkste verschuivingen in totalen (spend, conversies, CPA-trend), nieuwe/verdwenen keywords, en de grootste CPA-stijgers en -dalers met een korte verklaring per stijger (koppel aan matchtype of aan wat al bekend is uit de Waste-sectie). Als er GEEN periode-data is aangeleverd: schrijf één zin dat deze audit een single-snapshot is zonder periode-vergelijking, en sla de rest van deze sectie over.

## Waste
Behandel in deze volgorde: (1) keywords zonder conversies met negative-keyword-suggesties uitsluitend gebaseerd op die exacte keywords, letterlijk afgeleid zoals hierboven geïnstrueerd; (2) keywords met hoge CPA, per keyword concreet waarom; (3) matchtype-verdeling — rapporteer Broad, Exact en Phrase apart; (4) duplicate keywords indien niet leeg.

## Aanbevelingen
3 tot 5 concrete, genummerde, direct uitvoerbare actiepunten.

## Buiten scope van deze audit
Eén compacte alinea over wat nog ontbreekt voor een volledige account-audit en welke data daarvoor nodig zou zijn.
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
        max_tokens=4000,
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
    print(f"Ingelezen: {len(keywords_df)} keywords (huidige periode)")

    vorige_periode_pad = "data/voorbeeld_keywords_vorige_periode.csv"
    vorige_df = None
    if os.path.exists(vorige_periode_pad):
        vorige_df = load_keywords(vorige_periode_pad)
        print(f"Vorige periode geladen: {len(vorige_df)} keywords")
    else:
        print(f"Geen vorige-periode-bestand gevonden op '{vorige_periode_pad}' — audit draait zonder periode-vergelijking.")
    print()

    samenvatting = summarize_performance(keywords_df, vorige_df=vorige_df)

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