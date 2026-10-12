"""
FlexGen Signal Monitor · Poland — feed fetcher
Pulls new items from authentic sources, tags them to the dashboard taxonomy
and writes signals.json next to index.html.  Run on a schedule (GitHub Actions / Azure).

Sources used
  1. TED Search API v3 (EU tenders, anonymous)      -> procurement signals
  2. Sejm ELI API (Dziennik Ustaw, public)          -> laws & regulations
  3. Google News RSS, FILTERED to an allow-list of authentic publishers
     (company newsrooms, gov.pl, URE, PSE, WNP, PAP, Reuters, WNN ...)
  4. Optional: any direct RSS feeds you add to DIRECT_RSS
  5. Optional: Azure OpenAI for 50-60 word summaries + better tagging
"""
import json, os, re, hashlib, datetime as dt, html
from urllib.parse import quote_plus, urlparse
import requests, feedparser

OUT        = os.getenv("OUT_FILE", "signals.json")
LOOKBACK   = int(os.getenv("LOOKBACK_DAYS", "30"))
MAX_KEEP   = int(os.getenv("MAX_SIGNALS", "400"))
UA         = {"User-Agent": "FlexGenSignalMonitor/1.0 (research; contact: your-team@company.com)"}
TODAY      = dt.date.today()
SINCE      = TODAY - dt.timedelta(days=LOOKBACK)

# ───────────────────────── allow-list (authentic sources only) ─────────────────────────
PRIMARY = {  # domain -> link type used by the dashboard
 "gov.pl":"gov","ure.gov.pl":"gov","bip.ure.gov.pl":"gov","pse.pl":"gov","tge.pl":"gov","sejm.gov.pl":"gov",
 "eur-lex.europa.eu":"gov","ec.europa.eu":"gov","eib.org":"gov","ted.europa.eu":"gov","uokik.gov.pl":"gov",
 "gkpge.pl":"official","ir.enea.pl":"filing","media.enea.pl":"official","media.energa.pl":"official",
 "orlen.pl":"official","media.tauron.pl":"official","tauron.pl":"official","ri.zepak.com.pl":"filing",
 "pej.pl":"official","polenergia.pl":"official","fortum.com":"official","axpo.com":"official",
 "engie-polska.pl":"official","energa-operator.pl":"official","pgedystrybucja.pl":"official",
}
MEDIA = {"wnp.pl","wysokienapiecie.pl","biznes.pap.pl","pap.pl","bankier.pl","energia.rp.pl","rp.pl",
 "energetyka24.com","reuters.com","world-nuclear-news.org","renewablesnow.com","enerdata.net",
 "ess-news.com","energy-storage.news","pv-magazine.com","ceenergynews.com","polskieradio.pl","utilitydive.com"}
PUBLISHER_NAMES = {  # Google News <source> titles -> domain (fallback when only a name is given)
 "WNP.PL":"wnp.pl","wnp.pl":"wnp.pl","Wysokie Napięcie":"wysokienapiecie.pl","Bankier.pl":"bankier.pl",
 "Rzeczpospolita":"rp.pl","Reuters":"reuters.com","World Nuclear News":"world-nuclear-news.org",
 "Renewables Now":"renewablesnow.com","Energetyka24":"energetyka24.com","PAP Biznes":"biznes.pap.pl",
 "gov.pl":"gov.pl","Polskie Radio":"polskieradio.pl","CEENERGYNEWS":"ceenergynews.com"}

def base_domain(u):
    h = urlparse(u).netloc.lower().removeprefix("www.")
    for d in list(PRIMARY) + list(MEDIA):
        if h == d or h.endswith("." + d): return d
    return None

def link_type(dom): return PRIMARY.get(dom, "press")

# ───────────────────────── taxonomy rules ─────────────────────────
COMPANIES = {
 "PGE":[r"\bPGE\b"], "ENEA":[r"\bEnea\b"], "ENERGA":[r"\bEnerg(a|i|ę)\b"], "ORLEN":[r"\bORLEN\b"],
 "TAURON":[r"\bTAURON\b"], "ZEPAK":[r"ZE PAK|Zespół Elektrowni Pątnów"], "PEJ":[r"\bPEJ\b|Polskie Elektrownie Jądrowe"],
 "OSGE":[r"Synthos Green|OSGE|BWRX"], "POLENERGIA":[r"Polenergi"], "FORTUM":[r"Fortum"],
 "AXPO":[r"\bAxpo\b"], "ENGIE":[r"\bENGIE\b|\bEngie\b"],
}
# (pillar, category, regex) — first match wins, order = priority
RULES = [
 ("thermal","nuclear",  r"jądrow|nuclear|SMR|BWRX|AP1000|Lubiatowo|atomow"),
 ("thermal","delays",   r"opóźni|delay|cancel|anulow|wstrzyma|termin.*nie.*dotrzym|postponed"),
 ("thermal","fid",      r"\bFID\b|decyzj\w* inwestycyjn|final investment|financing|finansowani|kredyt|loan|przetarg|tender|EPC|turbin"),
 ("thermal","gasnew",   r"\bCCGT\b|\bOCGT\b|gazow\w*[- ]parow|gas[- ]fired|silnik\w* gazow|gas engine|blok gazowy|peaker|szczytow"),
 ("thermal","chp",      r"\bCHP\b|elektrociepłowni|ciepłowni|kogenera|biomas|fuel switch|konwersj"),
 ("thermal","coal",     r"węgl|coal|lignite|wyłącz\w* blok|closure|decommission"),
 ("policy","capacity",  r"rynek mocy|rynku mocy|capacity market|aukcj\w* mocy|capacity auction"),
 ("policy","support",   r"\bCfD\b|kontrakt\w* różnicow|contract for difference|wsparci|support scheme|aukcj\w* OZE|dotacj|subsid"),
 ("policy","mktreform", r"prawo energetyczne|Energy Law|ustaw\w*|nowelizac|rozporządzeni|regulation|taryf|URE\b|market reform"),
 ("policy","strategic", r"PEP2040|KPEiK|NECP|strategi\w* energetyczn|polityk\w* energetyczn|energy policy"),
 ("policy","political", r"minister|rząd|government|Sejm|Senat|wybor|election|premier"),
 ("company","ma",       r"przejęci|acquisi|acquire|sprzeda\w* udział|merger|buyout|wezwani"),
 ("company","leadership",r"prezes|CEO|zarząd|management board|rada nadzorcza|supervisory board|appoint|odwoł"),
 ("company","financial",r"wyniki|results|EBITDA|zysk|profit|revenue|przychod|dywidend|dividend"),
 ("company","contracts",r"umow\w*|contract|award|zlecen|agreement"),
 ("company","partnerships",r"porozumieni|list intencyjny|letter of intent|partnership|współprac|MoU"),
 ("company","strategy", r"strategi|strategy|plan inwestycyjny|capex"),
 ("company","project",  r".*"),
]
SCOPE = re.compile(r"energ|elektrown|power|gaz|gas|jądrow|nuclear|węgl|coal|ciepł|CHP|rynek mocy|capacity|URE|PSE|SMR|CCGT|OCGT", re.I)

def tag(text):
    cos = [c for c, pats in COMPANIES.items() if any(re.search(p, text, re.I) for p in pats)]
    for pillar, cat, rx in RULES:
        if re.search(rx, text, re.I): return pillar, cat, (cos or ["ALL"])
    return "company", "project", (cos or ["ALL"])

def sid(url): return "auto_" + hashlib.sha1(url.encode()).hexdigest()[:10]
def clean(t): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()

def make(title, desc, url, date, label, unit=""):
    pillar, cat, cos = tag(f"{title} {desc}")
    return {"id": sid(url), "date": date, "pillar": pillar, "cat": cat, "cos": cos, "unit": unit,
            "title": clean(title)[:220], "desc": clean(desc)[:700], "auto": True,
            "links": [{"label": label, "url": url, "type": link_type(base_domain(url) or "")}]}

# ───────────────────────── 1. TED Search API v3 ─────────────────────────
def fetch_ted():
    q = ("buyer-country=POL AND (classification-cpv=45251* OR classification-cpv=31121* "
         "OR FT~\"turbina gazowa\" OR FT~\"blok gazowo-parowy\" OR FT~\"elektrociepłownia\" OR FT~\"elektrownia jądrowa\") "
         f"AND publication-date>={SINCE:%Y%m%d} SORT BY publication-date DESC")
    body = {"query": q, "fields": ["publication-number","notice-title","buyer-name","publication-date"],
            "limit": 50, "page": 1, "scope": "ALL", "paginationMode": "PAGE_NUMBER"}
    r = requests.post("https://api.ted.europa.eu/v3/notices/search", json=body, headers=UA, timeout=40)
    r.raise_for_status()
    out = []
    for n in r.json().get("notices", []):
        pick = lambda v: (v.get("eng") or v.get("pol") or next(iter(v.values()), [""])) if isinstance(v, dict) else v
        title = pick(n.get("notice-title")); title = title[0] if isinstance(title, list) else title
        buyer = pick(n.get("buyer-name"));   buyer = buyer[0] if isinstance(buyer, list) else buyer
        pub = n.get("publication-number"); date = str(n.get("publication-date",""))[:10] or str(TODAY)
        url = f"https://ted.europa.eu/en/notice/-/detail/{pub}"
        s = make(f"Tender: {title}", f"Public procurement notice published on TED by {buyer}.", url, date,
                 f"TED — notice {pub}", unit=str(buyer or ""))
        s["pillar"], s["cat"] = "thermal", "fid"
        out.append(s)
    return out

# ───────────────────────── 2. Sejm ELI API (Dziennik Ustaw) ─────────────────────────
ELI_KEYS = re.compile(r"energetyczn|rynku mocy|odnawialnych źródeł|energii jądrowej|atomow|ciepł|gazow|elektroenerget", re.I)
def fetch_eli():
    out = []
    r = requests.get(f"https://api.sejm.gov.pl/eli/acts/DU/{TODAY.year}", headers=UA, timeout=40)
    r.raise_for_status()
    for a in r.json().get("items", []):
        title = a.get("title", ""); date = (a.get("promulgation") or a.get("announcementDate") or "")[:10]
        if not ELI_KEYS.search(title) or (date and date < str(SINCE)): continue
        pos = a.get("pos"); url = f"https://api.sejm.gov.pl/eli/acts/DU/{TODAY.year}/{pos}/text.pdf"
        s = make(title, f"Published in Dziennik Ustaw {TODAY.year} item {pos}.", url, date or str(TODAY),
                 f"Dziennik Ustaw {TODAY.year} poz. {pos}", unit="Dziennik Ustaw")
        s["pillar"] = "policy"; s["cat"] = "nuclear" if re.search("jądrow|atomow", title, re.I) else "mktreform"
        if s["cat"] == "nuclear": s["pillar"] = "thermal"
        s["links"][0]["type"] = "gov"
        out.append(s)
    return out

# ───────────────────────── 3. Google News RSS → allow-listed publishers only ─────────────────────────
QUERIES = [
 "rynek mocy PSE aukcja", "elektrownia gazowa CCGT OR OCGT Polska", "elektrociepłownia modernizacja gaz OR biomasa",
 "elektrownia jądrowa PEJ OR SMR OSGE", "blok węglowy wyłączenie OR konwersja", "kontrakt różnicowy CfD energia Polska",
 "URE decyzja energia", "Ministerstwo Energii projekt ustawy",
 "PGE OR Enea OR Energa OR ORLEN OR TAURON elektrownia", "ZE PAK OR Polenergia OR Fortum OR Axpo OR ENGIE Polska energia",
 "Poland power plant gas nuclear", "Poland capacity market auction",
]
def fetch_news():
    out = []
    for q in QUERIES:
        lang = ("en","US","US:en") if re.search(r"Poland", q) else ("pl","PL","PL:pl")
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:{LOOKBACK}d&hl={lang[0]}&gl={lang[1]}&ceid={lang[2]}"
        feed = feedparser.parse(requests.get(url, headers=UA, timeout=30).content)
        for e in feed.entries:
            src = getattr(e, "source", {}) or {}
            dom = base_domain(src.get("href","")) or PUBLISHER_NAMES.get(src.get("title",""))
            if not dom: continue                                  # ← drop anything not on the allow-list
            title = re.sub(r"\s+-\s+[^-]+$", "", e.title)         # strip " - Publisher"
            if not SCOPE.search(title): continue
            date = dt.date(*e.published_parsed[:3]).isoformat() if getattr(e,"published_parsed",None) else str(TODAY)
            s = make(title, e.get("summary", ""), e.link, date, f"{src.get('title', dom)}")
            s["links"][0]["type"] = link_type(dom)
            out.append(s)
    return out

# ───────────────────────── 4. Direct RSS feeds (add verified feed URLs here) ─────────────────────────
DIRECT_RSS = [
 # ("PSE — news", "https://www.pse.pl/...rss..."),   # add after confirming the RSS URL on the site
]
def fetch_direct():
    out = []
    for label, url in DIRECT_RSS:
        for e in feedparser.parse(url).entries:
            date = dt.date(*e.published_parsed[:3]).isoformat() if getattr(e,"published_parsed",None) else str(TODAY)
            out.append(make(e.title, e.get("summary",""), e.link, date, label))
    return out

# ───────────────────────── 5. Optional AI summary/tagging (Azure OpenAI) ─────────────────────────
def ai_enrich(items):
    ep, key, dep = os.getenv("AZURE_OPENAI_ENDPOINT"), os.getenv("AZURE_OPENAI_KEY"), os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not (ep and key and dep): return items
    cats = [c for _, c, _ in RULES]
    for s in items[:60]:
        prompt = (f"Polish power-sector news item.\nTitle: {s['title']}\nText: {s['desc']}\n"
                  f"Return JSON: summary (English, 50-60 words, facts only, no speculation), "
                  f"category (one of {cats}), relevant (true if about Polish power generation, policy, nuclear, CHP or the companies PGE, Enea, Energa, ORLEN, TAURON, ZE PAK, PEJ, OSGE, Polenergia, Fortum, Axpo, ENGIE).")
        try:
            r = requests.post(f"{ep}/openai/deployments/{dep}/chat/completions?api-version=2024-06-01",
                headers={"api-key": key}, timeout=60,
                json={"messages":[{"role":"user","content":prompt}], "temperature":0, "response_format":{"type":"json_object"}})
            j = json.loads(r.json()["choices"][0]["message"]["content"])
            if not j.get("relevant", True): s["_drop"] = True; continue
            s["desc"] = j.get("summary", s["desc"])
            if j.get("category") in cats:
                s["cat"] = j["category"]; s["pillar"] = next(p for p, c, _ in RULES if c == s["cat"])
        except Exception as ex: print("AI skip:", ex)
    return [s for s in items if not s.get("_drop")]

# ───────────────────────── run ─────────────────────────
def main():
    old = []
    if os.path.exists(OUT):
        try: old = json.load(open(OUT, encoding="utf-8")).get("signals", [])
        except Exception: pass
    new = []
    for name, fn in [("TED", fetch_ted), ("ELI", fetch_eli), ("News", fetch_news), ("RSS", fetch_direct)]:
        try:
            got = fn(); new += got; print(f"{name}: {len(got)}")
        except Exception as ex: print(f"{name} failed: {ex}")   # one source failing never breaks the feed
    seen, merged = set(), []
    for s in ai_enrich(new) + old:                       # newest first, dedupe on id and title
        k = (s["id"], s["title"].lower()[:80])
        if s["id"] in seen or k[1] in seen: continue
        seen.update(k); merged.append(s)
    merged.sort(key=lambda s: s["date"], reverse=True)
    json.dump({"generated": dt.datetime.now(dt.timezone.utc).isoformat(), "signals": merged[:MAX_KEEP]},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {len(merged[:MAX_KEEP])} signals → {OUT}")

if __name__ == "__main__": main()
