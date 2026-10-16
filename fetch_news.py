#!/usr/bin/env python3
"""
Poland Energy Market Intelligence - live news updater.

Reads RSS feeds in config/sources.json, keeps Poland energy news, translates Polish
items to English, tags companies/technologies, removes duplicates and merges
everything into the JSON file the dashboard reads (default: data/signals.json).

Signal categories are NOT assigned here - the dashboard classifies each item into
the 5 signal categories itself, so the Live News Feed stays uncategorised.
"""
import email.utils, hashlib, html, json, os, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("DATA_PATH", os.path.join(ROOT, "data", "signals.json"))
CFG = json.load(open(os.path.join(ROOT, "config", "sources.json"), encoding="utf-8"))
START = os.environ.get("START_DATE", "2024-01-01")
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "3000"))
UA = {"User-Agent": "Mozilla/5.0 (PolandEnergyMI news updater; +https://github.com)"}

COMPANIES = {
    "PGE": r"\bpge\b", "ORLEN": r"\borlen\b", "TAURON": r"\btauron\b", "ENEA": r"\benea\b",
    "ENERGA": r"\benerga\b", "ZEPAK": r"ze pak|zepak", "PEJ": r"polskie elektrownie j|\bpej\b",
    "OSGE": r"orlen synthos|\bosge\b", "POLENERGIA": r"polenergi", "ENGIE": r"\bengie\b",
    "AXPO": r"\baxpo\b", "ALL": r"\bpse\b|\bure\b|ministry of (climate|energy)|ministerstw|government|rząd",
}
TECH = {  # dashboard 'cats' codes used to derive technology tags
    "NUC": r"nuclear|\bsmr\b|atom|jądrow|ap1000|bwrx",
    "BESS": r"battery|storage|\bbess\b|magazyn",
    "GAS": r"\bgas\b|ccgt|ocgt|gazow|\blng\b",
    "REN": r"wind|solar|photovolt|\bpv\b|wiatr|fotowolt|offshore|biomethane|biogas|renewable|oze",
    "GRID": r"\bgrid\b|transmission|distribution|interconnect|substation|sieci|sieć",
    "COAL": r"\bcoal\b|lignite|węgl",
    "H2": r"hydrogen|wodór|wodor",
}
REGIONS = ["Masovia","Silesia","Lesser Poland","Greater Poland","Pomerania","West Pomerania","Łódź","Lublin",
           "Subcarpathia","Podlaskie","Lower Silesia","Opole","Świętokrzyskie","Warmia-Masuria","Kuyavia-Pomerania","Lubusz","Baltic Sea"]

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()

def clean(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()

def parse_date(s):
    if not s: return None
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(timezone.utc).date().isoformat()
    except Exception:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s.strip())
        return m.group(1) if m else None

def parse_feed(raw):
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for it in root.iter("item"):
        out.append({"title": clean(it.findtext("title")), "url": (it.findtext("link") or "").strip(),
                    "desc": clean(it.findtext("description")), "date": parse_date(it.findtext("pubDate")),
                    "source": clean(it.findtext("source"))})
    for it in root.findall("a:entry", ns):
        l = it.find("a:link", ns)
        out.append({"title": clean(it.findtext("a:title", namespaces=ns)), "url": l.get("href") if l is not None else "",
                    "desc": clean(it.findtext("a:summary", namespaces=ns)),
                    "date": parse_date(it.findtext("a:updated", namespaces=ns) or it.findtext("a:published", namespaces=ns)), "source": ""})
    return out

def words(t, n):
    w = t.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")

_tr = None
def translate(t):
    global _tr
    if not t: return t, False
    try:
        if _tr is None:
            from deep_translator import GoogleTranslator
            _tr = GoogleTranslator(source="pl", target="en")
        return _tr.translate(t[:4500]), True
    except Exception as e:
        print("  translate failed:", e, file=sys.stderr)
        return t, False

def norm_title(t):
    t = re.sub(r"\s+-\s+[^-]{2,40}$", "", t)          # strip ' - Publisher' (Google News)
    return re.sub(r"[^a-z0-9ąćęłńóśźż ]", "", t.lower()).strip()

def main():
    existing = []
    if os.path.exists(OUT):
        try:
            d = json.load(open(OUT, encoding="utf-8"))
            existing = d.get("signals", d if isinstance(d, list) else [])
        except Exception as e:
            print("Could not read existing data, starting fresh:", e)
    seen_url = {l["url"] for s in existing for l in s.get("links", [])}
    seen_title = {norm_title(s.get("title_pl") or s.get("title", "")) for s in existing}
    rel = re.compile("|".join(map(re.escape, CFG["relevance_keywords"])), re.I)
    pol = re.compile("|".join(map(re.escape, CFG["poland_keywords"])), re.I)
    added = []
    for f in CFG["feeds"]:
        try:
            items = parse_feed(get(f["url"]))
        except Exception as e:
            print(f"! {f['publisher']}: {e}"); continue
        print(f"- {f['publisher']}: {len(items)} items")
        for it in items:
            if not it["title"] or not it["url"] or not it["date"] or it["date"] < START: continue
            text = it["title"] + " " + it["desc"]
            if not rel.search(text): continue
            if f["lang"] == "en" and not pol.search(text): continue
            nt = norm_title(it["title"])
            if it["url"] in seen_url or nt in seen_title: continue
            seen_url.add(it["url"]); seen_title.add(nt)
            publisher = it["source"] or f["publisher"]
            title = re.sub(r"\s+-\s+" + re.escape(publisher) + r"$", "", it["title"]) if it["source"] else it["title"]
            rec = {"id": "live-" + hashlib.sha1(it["url"].encode()).hexdigest()[:12], "date": it["date"],
                   "publisher": publisher, "auto": True}
            summary = words(it["desc"] if it["desc"] and norm_title(it["desc"]) != nt else title, 40)
            if f["lang"] == "pl":
                en_t, ok1 = translate(title); en_s, ok2 = translate(summary)
                rec.update({"title": en_t, "title_pl": title, "summary": words(en_s, 40), "lang": "pl", "translated": ok1 and ok2})
            else:
                rec.update({"title": title, "summary": summary, "lang": "en"})
            full = title + " " + it["desc"]
            rec["cos"] = [c for c, r in COMPANIES.items() if re.search(r, full, re.I)] or ["OTHER"]
            rec["cats"] = [c for c, r in TECH.items() if re.search(r, full, re.I)]
            rec["region"] = next((r for r in REGIONS if r.lower() in full.lower()), "National")
            rec["unit"] = ""; rec["change"] = ""; rec["why"] = ""
            rec["links"] = [{"label": f"{publisher}", "url": it["url"], "type": f.get("type", "press")}]
            added.append(rec)
    allx = sorted(existing + added, key=lambda s: s["date"], reverse=True)[:MAX_ITEMS]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(allx), "signals": allx},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Added {len(added)} new items; total {len(allx)} -> {OUT}")

if __name__ == "__main__":
    main()
