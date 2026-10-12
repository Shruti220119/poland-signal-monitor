"""
FlexGen Signal Monitor · Poland — live feed fetcher
---------------------------------------------------
Keeps signals.json up to date for the dashboard (index.html).

* The 85 curated signals already in signals.json (curated: true) are always kept.
* New articles from authentic sources are added with:
    title (English) · 30–40-word English summary · region · pillar / category ·
    companies · source link
* Polish articles are ALWAYS translated. If no translation engine is configured,
  Polish items are skipped — they are never published in Polish.

Engines (first available is used; set as GitHub repository secrets):
  1. Azure OpenAI       AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT
                        -> translation + 30–40-word summary + tagging
  2. Azure Translator   AZURE_TRANSLATOR_KEY, AZURE_TRANSLATOR_REGION
                        -> translation; summary = translated description trimmed to 40 words
  3. None               -> English-language items only
"""
import json, os, re, html, hashlib, datetime as dt
from urllib.parse import quote_plus, urlparse
import requests, feedparser

OUT       = os.getenv("OUT_FILE", "signals.json")
LOOKBACK  = int(os.getenv("LOOKBACK_DAYS", "30"))
MAX_AUTO  = int(os.getenv("MAX_AUTO_SIGNALS", "300"))   # cap on live items kept (curated never dropped)
MAX_NEW   = int(os.getenv("MAX_NEW_PER_RUN", "60"))     # caps translation / AI cost per run
UA        = {"User-Agent": "Mozilla/5.0 (FlexGenSignalMonitor/2.1; research use)"}
TODAY     = dt.date.today()
SINCE     = TODAY - dt.timedelta(days=LOOKBACK)

# ─────────── authentic-source allow-list ───────────
PRIMARY = {"gov.pl":"gov","ure.gov.pl":"gov","pse.pl":"gov","tge.pl":"gov","sejm.gov.pl":"gov","eur-lex.europa.eu":"gov",
 "ec.europa.eu":"gov","eib.org":"gov","ted.europa.eu":"gov","uokik.gov.pl":"gov","gkpge.pl":"official","enea.pl":"official",
 "energa.pl":"official","orlen.pl":"official","tauron.pl":"official","zepak.com.pl":"filing","pej.pl":"official",
 "polenergia.pl":"official","fortum.com":"official","axpo.com":"official","engie-polska.pl":"official",
 "energa-operator.pl":"official","pgedystrybucja.pl":"official"}
MEDIA = {"wnp.pl","wysokienapiecie.pl","pap.pl","bankier.pl","rp.pl","energetyka24.com","reuters.com","world-nuclear-news.org",
 "renewablesnow.com","enerdata.net","ess-news.com","energy-storage.news","pv-magazine.com","ceenergynews.com",
 "polskieradio.pl","utilitydive.com"}
NAMES = {"WNP.PL":"wnp.pl","wnp.pl":"wnp.pl","Wysokie Napięcie":"wysokienapiecie.pl","Bankier.pl":"bankier.pl",
 "Rzeczpospolita":"rp.pl","Reuters":"reuters.com","World Nuclear News":"world-nuclear-news.org","Renewables Now":"renewablesnow.com",
 "Energetyka24":"energetyka24.com","PAP Biznes":"pap.pl","Polskie Radio":"polskieradio.pl","CEENERGYNEWS":"ceenergynews.com",
 "gov.pl":"gov.pl","PSE":"pse.pl","ORLEN":"orlen.pl","PGE":"gkpge.pl","TAURON":"tauron.pl","Enea":"enea.pl"}

def domain_of(x):
    if x in NAMES: return NAMES[x]
    h = urlparse(x).netloc.lower().removeprefix("www.")
    return next((d for d in list(PRIMARY) + list(MEDIA) if h == d or h.endswith("." + d)), None)

# ─────────── taxonomy (matches the dashboard) ───────────
PILLAR = {"capacity":"policy","strategic":"policy","political":"policy","mktreform":"policy","support":"policy",
 "gasnew":"thermal","chp":"thermal","coal":"thermal","fid":"thermal","delays":"thermal","nuclear":"thermal",
 "leadership":"company","strategy":"company","project":"company","contracts":"company","partnerships":"company",
 "financial":"company","ma":"company"}
RULES = [("nuclear",r"nuclear|SMR|BWRX|AP1000|Lubiatowo|jądrow|atomow"),
 ("delays",r"delay|postpone|cancel|missed|opóźni|anulow"),
 ("fid",r"\bFID\b|final investment|financing|loan|tender|EPC|turbine|finansow|kredyt|przetarg"),
 ("gasnew",r"\bCCGT\b|\bOCGT\b|gas-fired|gas engine|peaker|gazowo-parow|szczytow"),
 ("chp",r"\bCHP\b|combined heat|district heat|biomass|elektrociepł|ciepłown"),
 ("coal",r"\bcoal\b|lignite|closure|decommission|węgl"),
 ("capacity",r"capacity market|capacity auction|rynek mocy|rynku mocy"),
 ("support",r"\bCfD\b|contract for difference|support scheme|subsid|dotacj"),
 ("mktreform",r"Energy Law|amendment|regulation|tariff|\bURE\b|ustaw|nowelizac"),
 ("strategic",r"energy policy|PEP2040|NECP|KPEiK"),
 ("political",r"minister|government|Sejm|election|rząd|premier"),
 ("ma",r"acqui|takeover|buyout|merger|stake|przejęc"),
 ("leadership",r"\bCEO\b|management board|supervisory board|appoint|dismiss|prezes|zarząd"),
 ("financial",r"results|EBITDA|profit|revenue|dividend|wyniki|zysk"),
 ("contracts",r"contract|award|umow"),
 ("partnerships",r"letter of intent|partnership|memorandum|cooperation|porozumien"),
 ("strategy",r"strategy|capex|strategi")]
COMPANIES = {"PGE":r"\bPGE\b","ENEA":r"\bEnea\b","ENERGA":r"\bEnerg(a|i|ę|ą)\b","ORLEN":r"\bORLEN\b|\bOrlen\b",
 "TAURON":r"\bTAURON\b|\bTauron\b","ZEPAK":r"ZE PAK","PEJ":r"\bPEJ\b|Polskie Elektrownie Jądrowe","OSGE":r"Synthos Green|OSGE|BWRX",
 "POLENERGIA":r"Polenergi","FORTUM":r"Fortum","AXPO":r"\bAxpo\b","ENGIE":r"\bENGIE\b|\bEngie\b"}
REGIONS = {"Masovia":r"Masovia|Mazowieck|Warsaw|Kozienice|Ostrołęka|Siedlce","Silesia":r"Silesia|Śląsk|Rybnik|Jaworzno|Zabrze|Katowice",
 "Pomerania":r"Pomerania|Pomorsk|Gdańsk|Lubiatowo|Żarnowiec","West Pomerania":r"West Pomerania|Gryfino|Szczecin",
 "Kuyavia-Pomerania":r"Kuyavia|Kujawsk|Grudziądz|Włocławek","Lesser Poland":r"Lesser Poland|Małopolsk|Kraków|Rożnów",
 "Subcarpathia":r"Subcarpath|Podkarpack|Stalowa Wola|Nowa Sarzyna","Greater Poland":r"Greater Poland|Wielkopolsk|Konin|Pątnów",
 "Świętokrzyskie":r"Świętokrzysk|Połaniec","Łódź":r"Łódź|Łódzk|Bełchatów","Lower Silesia":r"Lower Silesia|Dolnośląsk|Turów",
 "Baltic Sea":r"Baltic Sea|offshore"}

def tag(text):
    cat = next((c for c, rx in RULES if re.search(rx, text, re.I)), "project")
    cos = [c for c, rx in COMPANIES.items() if re.search(rx, text)] or ["ALL"]
    reg = " · ".join([r for r, rx in REGIONS.items() if re.search(rx, text, re.I)][:3]) or "National"
    return cat, cos, reg

# ─────────── language & summary helpers ───────────
PL_HINT = re.compile(r"[ąćęłńśźż]|\b(się|oraz|który|która|które|jest|został|została|przez|dla|będzie|roku)\b", re.I)
is_polish = lambda t: len(PL_HINT.findall(t or "")) >= 2
clean = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
def trim40(t):
    w = t.split()
    return " ".join(w[:40]).rstrip(",;:") + ("…" if len(w) > 40 else "")

def meta_description(url):
    try:
        h = requests.get(url, headers=UA, timeout=20).text[:200000]
        m = re.search(r'<meta[^>]+(?:property="og:description"|name="description")[^>]+content="([^"]+)"', h, re.I) \
            or re.search(r'<meta[^>]+content="([^"]+)"[^>]+(?:property="og:description"|name="description")', h, re.I)
        return clean(m.group(1)) if m else ""
    except Exception:
        return ""

def ai_enrich(title, text):
    ep, key, dep = os.getenv("AZURE_OPENAI_ENDPOINT"), os.getenv("AZURE_OPENAI_KEY"), os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not (ep and key and dep): return None
    prompt = ("You are a Polish power-sector analyst. The article may be in Polish. ALWAYS answer in ENGLISH.\n"
      f"TITLE: {title}\nTEXT: {text[:4000]}\n\nReturn JSON with keys:\n"
      "title_en: accurate English headline, max 16 words\n"
      "summary_en: factual English summary of 30 to 40 words, only facts stated in the text\n"
      f"category: one of {list(PILLAR)}\n"
      "region: Polish voivodeship(s) in English separated by ' · ', or 'National'\n"
      "relevant: true only if about the Polish power sector, energy policy, nuclear, CHP or PGE, Enea, Energa, ORLEN, "
      "TAURON, ZE PAK, PEJ, OSGE, Polenergia, Fortum, Axpo or ENGIE")
    r = requests.post(f"{ep.rstrip('/')}/openai/deployments/{dep}/chat/completions?api-version=2024-06-01",
        headers={"api-key": key}, timeout=60,
        json={"messages":[{"role":"user","content":prompt}], "temperature":0, "response_format":{"type":"json_object"}})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])

def translate(texts):
    key = os.getenv("AZURE_TRANSLATOR_KEY")
    if not key: return None
    r = requests.post("https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&from=pl&to=en",
        headers={"Ocp-Apim-Subscription-Key": key, "Ocp-Apim-Subscription-Region": os.getenv("AZURE_TRANSLATOR_REGION","westeurope"),
                 "Content-Type": "application/json"}, json=[{"text": t[:4000]} for t in texts], timeout=40)
    r.raise_for_status()
    return [x["translations"][0]["text"] for x in r.json()]

def build(raw):
    title, text = clean(raw["title"]), clean(raw.get("text", ""))
    if len(text.split()) < 20: text = (text + " " + meta_description(raw["url"])).strip()
    pl = is_polish(title + " " + text)
    item = {"id": "auto_" + hashlib.sha1(raw["url"].encode()).hexdigest()[:10], "date": raw["date"], "auto": True,
            "lang": "pl" if pl else "en", "translated": pl,
            "links": [{"label": raw["publisher"] + (" (Polish, translated)" if pl else ""), "url": raw["url"], "type": raw["ltype"]}]}
    try: ai = ai_enrich(title, text)
    except Exception as ex: print("  AI error:", ex); ai = None
    if ai:
        if not ai.get("relevant", True): return None
        summary = ai.get("summary_en", "")
        if not summary or is_polish(summary): return None
        cat0, cos, reg0 = tag(f"{ai.get('title_en','')} {summary} {title} {text}")
        cat = ai.get("category") if ai.get("category") in PILLAR else cat0
        item.update(title=ai.get("title_en") or title, summary=trim40(summary), cat=cat, pillar=PILLAR[cat], cos=cos, region=ai.get("region") or reg0)
        return item
    if pl:
        try: tr = translate([title, text or title])
        except Exception as ex: print("  translate error:", ex); tr = None
        if not tr: return None                    # rule: never publish untranslated Polish
        title, text = tr
    if is_polish(title) or len(text.split()) < 12: return None
    cat, cos, reg = tag(f"{title} {text}")
    item.update(title=title, summary=trim40(text), cat=cat, pillar=PILLAR[cat], cos=cos, region=reg)
    return item

# ─────────── collectors ───────────
def from_ted():
    q = ("buyer-country=POL AND (classification-cpv=45251* OR classification-cpv=31121* OR FT~\"turbina gazowa\" "
         "OR FT~\"blok gazowo-parowy\" OR FT~\"elektrociepłownia\" OR FT~\"elektrownia jądrowa\") "
         f"AND publication-date>={SINCE:%Y%m%d} SORT BY publication-date DESC")
    r = requests.post("https://api.ted.europa.eu/v3/notices/search", headers=UA, timeout=40, json={"query": q,
        "fields": ["publication-number","notice-title","buyer-name","publication-date"], "limit": 40, "page": 1,
        "scope": "ALL", "paginationMode": "PAGE_NUMBER"})
    r.raise_for_status()
    pick = lambda v: (v.get("eng") or v.get("pol") or next(iter(v.values()), "")) if isinstance(v, dict) else v
    one = lambda v: (v[0] if isinstance(v, list) and v else v) or ""
    for n in r.json().get("notices", []):
        pub = n.get("publication-number"); title = one(pick(n.get("notice-title"))); buyer = one(pick(n.get("buyer-name")))
        yield dict(title="Tender: " + title, url=f"https://ted.europa.eu/en/notice/-/detail/{pub}",
                   text=f"{buyer} published public procurement notice {pub} on the EU TED portal: {title}. "
                        f"The notice relates to power-generation or heat infrastructure in Poland.",
                   date=str(n.get("publication-date",""))[:10] or str(TODAY), publisher="TED (EU tenders)", ltype="gov")

QUERIES = ["rynek mocy aukcja PSE", "elektrownia gazowa CCGT OR OCGT", "elektrociepłownia modernizacja OR konwersja",
 "elektrownia jądrowa PEJ OR SMR", "blok węglowy wyłączenie OR zamknięcie", "kontrakt różnicowy CfD energia",
 "URE decyzja taryfa OR koncesja", "Ministerstwo Energii projekt ustawy energia",
 "PGE OR Enea OR Energa OR ORLEN OR TAURON elektrownia", "ZE PAK OR Polenergia OR Fortum OR Axpo OR ENGIE energia Polska",
 "Poland power plant gas OR nuclear", "Poland capacity market auction", "Poland energy policy electricity"]
def from_news():
    for q in QUERIES:
        loc = "&hl=en-GB&gl=GB&ceid=GB:en" if q.startswith("Poland") else "&hl=pl&gl=PL&ceid=PL:pl"
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:{LOOKBACK}d{loc}"
        for e in feedparser.parse(requests.get(url, headers=UA, timeout=30).content).entries:
            src = getattr(e, "source", {}) or {}
            dom = domain_of(src.get("href","")) or domain_of(src.get("title",""))
            if not dom: continue                                   # not an approved source -> skip
            date = dt.date(*e.published_parsed[:3]).isoformat() if getattr(e,"published_parsed",None) else str(TODAY)
            yield dict(title=re.sub(r"\s+-\s+[^-]+$", "", e.title), text=clean(e.get("summary","")), url=e.link,
                       date=date, publisher=src.get("title", dom), ltype=PRIMARY.get(dom, "press"))

DIRECT_RSS = []   # add verified RSS feeds: ("Publisher", "https://…/rss", "official")
def from_rss():
    for pub, url, lt in DIRECT_RSS:
        for e in feedparser.parse(url).entries:
            date = dt.date(*e.published_parsed[:3]).isoformat() if getattr(e,"published_parsed",None) else str(TODAY)
            yield dict(title=e.title, text=clean(e.get("summary","")), url=e.link, date=date, publisher=pub, ltype=lt)

SCOPE = re.compile(r"energ|elektrown|power|gaz|gas|jądrow|nuclear|węgl|coal|ciepł|CHP|mocy|capacity|URE|PSE|SMR|CCGT|OCGT|turbin", re.I)

def main():
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"signals": []}
    curated = [s for s in data["signals"] if s.get("curated")]
    auto    = [s for s in data["signals"] if not s.get("curated")]
    known   = {s["id"] for s in data["signals"]}
    titles  = {s["title"].lower()[:70] for s in data["signals"]}
    raws = []
    for name, fn in [("TED", from_ted), ("News", from_news), ("RSS", from_rss)]:
        try:
            got = [r for r in fn() if r["date"] >= str(SINCE) and SCOPE.search(r["title"] + " " + r.get("text",""))]
            raws += got; print(f"{name}: {len(got)} candidates")
        except Exception as ex: print(f"{name} failed: {ex}")      # one source failing never stops the run
    new = []
    for r in sorted(raws, key=lambda x: x["date"], reverse=True):
        sid = "auto_" + hashlib.sha1(r["url"].encode()).hexdigest()[:10]
        if sid in known or len(new) >= MAX_NEW: continue
        it = build(r)
        if not it or it["title"].lower()[:70] in titles: continue
        known.add(sid); titles.add(it["title"].lower()[:70]); new.append(it)
    auto = sorted(new + auto, key=lambda s: s["date"], reverse=True)[:MAX_AUTO]
    data.update(generated=dt.datetime.now(dt.timezone.utc).isoformat(),
                signals=sorted(curated + auto, key=lambda s: s["date"], reverse=True))
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"added {len(new)} new · curated {len(curated)} · live {len(auto)} → {OUT}")

if __name__ == "__main__":
    main()
