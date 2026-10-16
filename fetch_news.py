#!/usr/bin/env python3
"""Poland Energy Market Intelligence - live news updater (v6.1, hardened).
Reads RSS feeds in config/sources.json, keeps Poland energy news, translates Polish
items to English, tags company/technology/region, de-duplicates and merges into
DATA_PATH (default data/signals.json). Signal categories are assigned by the dashboard.
A failing feed, item or translation never stops the run."""
import email.utils, hashlib, html, json, os, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, os.environ.get("DATA_PATH", "data/signals.json"))
CFG = json.load(open(os.path.join(ROOT, "config", "sources.json"), encoding="utf-8"))
START = os.environ.get("START_DATE", "2024-01-01")
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "3000"))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) PolandEnergyMI/1.1", "Accept": "application/rss+xml, application/xml, text/xml, */*"}

COMPANIES = {"PGE": r"\bpge\b", "ORLEN": r"\borlen\b", "TAURON": r"\btauron\b", "ENEA": r"\benea\b",
  "ENERGA": r"\benerga\b", "ZEPAK": r"ze pak|zepak", "PEJ": r"polskie elektrownie j|\bpej\b",
  "OSGE": r"orlen synthos|\bosge\b", "POLENERGIA": r"polenergi", "ENGIE": r"\bengie\b", "AXPO": r"\baxpo\b",
  "ALL": r"\bpse\b|\bure\b|ministry of (climate|energy)|ministerstw|government|rząd"}
TECH = {"NUC": r"nuclear|\bsmr\b|atom|jądrow|ap1000|bwrx", "BESS": r"battery|storage|\bbess\b|magazyn",
  "GAS": r"\bgas\b|ccgt|ocgt|gazow|\blng\b", "REN": r"wind|solar|photovolt|\bpv\b|wiatr|fotowolt|offshore|biogas|renewable|\boze\b",
  "GRID": r"\bgrid\b|transmission|distribution|interconnect|substation|sieci|sieć", "COAL": r"\bcoal\b|lignite|węgl", "H2": r"hydrogen|wodór|wodor"}
REGIONS = ["Masovia","Silesia","Lesser Poland","Greater Poland","West Pomerania","Pomerania","Łódź","Lublin","Subcarpathia","Podlaskie",
  "Lower Silesia","Opole","Świętokrzyskie","Warmia-Masuria","Kuyavia-Pomerania","Lubusz","Baltic Sea"]

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
        return r.read()

def clean(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()

def parse_date(s):
    if not s: return None
    try: return email.utils.parsedate_to_datetime(s).astimezone(timezone.utc).date().isoformat()
    except Exception:
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", s); return m.group(1) if m else None

def parse_feed(raw):
    raw = raw.lstrip()
    if raw.startswith(b"\xef\xbb\xbf"): raw = raw[3:]
    root = ET.fromstring(raw); A = "{http://www.w3.org/2005/Atom}"; out = []
    for it in root.iter("item"):
        out.append({"title": clean(it.findtext("title")), "url": (it.findtext("link") or "").strip(),
          "desc": clean(it.findtext("description")), "date": parse_date(it.findtext("pubDate")), "source": clean(it.findtext("source"))})
    for it in root.iter(A + "entry"):
        l = it.find(A + "link")
        out.append({"title": clean(it.findtext(A + "title")), "url": l.get("href", "") if l is not None else "",
          "desc": clean(it.findtext(A + "summary")), "date": parse_date(it.findtext(A + "updated") or it.findtext(A + "published")), "source": ""})
    return out

def words(t, n):
    w = (t or "").split(); return " ".join(w[:n]) + ("…" if len(w) > n else "")

_tr = None
def translate(t):
    global _tr
    if not t: return t, True
    try:
        if _tr is None:
            from deep_translator import GoogleTranslator
            _tr = GoogleTranslator(source="pl", target="en")
        r = _tr.translate(t[:4500]); return (r or t), bool(r)
    except Exception as e:
        print("  translate failed:", e); return t, False

def norm_title(t):
    t = re.sub(r"\s+-\s+[^-]{2,40}$", "", t or "")
    return re.sub(r"[^a-z0-9ąćęłńóśźż ]", "", t.lower()).strip()

def load_existing():
    if not os.path.exists(OUT): return []
    try:
        d = json.load(open(OUT, encoding="utf-8"))
        x = d if isinstance(d, list) else d.get("signals", [])
        return [s for s in x if isinstance(s, dict) and s.get("date")]
    except Exception as e:
        print("! Could not read existing data file, starting fresh:", e); return []

def main():
    existing = load_existing()
    seen_url = {l.get("url") for s in existing for l in (s.get("links") or []) if isinstance(l, dict)}
    seen_title = {norm_title(s.get("title_pl") or s.get("title", "")) for s in existing}
    rel = re.compile("|".join(map(re.escape, CFG["relevance_keywords"])), re.I)
    pol = re.compile("|".join(map(re.escape, CFG["poland_keywords"])), re.I)
    added, ok_feeds = [], 0
    for f in CFG["feeds"]:
        try:
            items = parse_feed(get(f["url"])); ok_feeds += 1
        except Exception as e:
            print(f"! {f['publisher']}: {type(e).__name__}: {e}"); continue
        print(f"- {f['publisher']}: {len(items)} items")
        for it in items:
            try:
                if not it["title"] or not it["url"] or not it["date"] or it["date"] < START: continue
                text = it["title"] + " " + it["desc"]
                if not rel.search(text): continue
                if f["lang"] == "en" and not pol.search(text): continue
                nt = norm_title(it["title"])
                if it["url"] in seen_url or nt in seen_title: continue
                seen_url.add(it["url"]); seen_title.add(nt)
                pub = it["source"] or f["publisher"]
                title = re.sub(r"\s+-\s+" + re.escape(pub) + r"$", "", it["title"])
                rec = {"id": "live-" + hashlib.sha1(it["url"].encode()).hexdigest()[:12], "date": it["date"], "publisher": pub, "auto": True}
                summary = words(it["desc"] if it["desc"] and norm_title(it["desc"]) != nt else title, 40)
                if f["lang"] == "pl":
                    et, a = translate(title); es, b = translate(summary)
                    rec.update({"title": et, "title_pl": title, "summary": words(es, 40), "lang": "pl", "translated": a and b})
                else:
                    rec.update({"title": title, "summary": summary, "lang": "en"})
                full = title + " " + it["desc"]
                rec["cos"] = [c for c, r in COMPANIES.items() if re.search(r, full, re.I)] or ["OTHER"]
                rec["cats"] = [c for c, r in TECH.items() if re.search(r, full, re.I)]
                rec["region"] = next((r for r in REGIONS if r.lower() in full.lower()), "National")
                rec.update({"unit": "", "change": "", "why": "", "links": [{"label": pub, "url": it["url"], "type": f.get("type", "press")}]})
                added.append(rec)
            except Exception as e:
                print(f"  skipped one item ({f['publisher']}): {e}")
    allx = sorted(existing + added, key=lambda s: s.get("date", ""), reverse=True)[:MAX_ITEMS]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(allx), "signals": allx},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Feeds OK: {ok_feeds}/{len(CFG['feeds'])} | added {len(added)} | total {len(allx)} -> {OUT}")
    if ok_feeds == 0: sys.exit("No feed could be reached - check network or feed URLs.")

if __name__ == "__main__":
    main()
