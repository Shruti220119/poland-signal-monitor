# FlexGen Signal Monitor · Poland — hosting & automation

## How it works
```
 Sources (APIs / RSS)  ──►  feed_fetcher.py  ──►  signals.json  ──►  index.html (browser)
  TED · Sejm ELI ·          runs every 30 min      new items          re-reads signals.json on load
  allow-listed news         (GitHub Actions)       tagged & merged    and every 5 min
```
Users only ever press F5 (refresh). The page loads the latest `signals.json`; the 85 curated
signals stay built in and live items (marked **LIVE FEED**) are merged on top.

> `index.html` must be served over http(s). Opening it by double-click (file://) shows only the built-in signals.

---
## Option A — GitHub Pages (quickest)
1. Create a repository and upload: `index.html`, `feed_fetcher.py`, `requirements.txt`, `.github/workflows/update-feed.yml`.
2. **Settings → Pages →** Source: *Deploy from a branch*, branch `main`, folder `/ (root)`.
3. **Actions →** "Update signal feed" **→ Run workflow** once to create `signals.json`.
4. Open `https://<org>.github.io/<repo>/` — the workflow then refreshes the feed every 30 minutes.

Public repositories make the site public. For client material use a private repo on GitHub Enterprise with private Pages, or Option B.

## Option B — Azure Static Web Apps (recommended for client use)
1. Put the same files in a GitHub or Azure DevOps repository.
2. Azure portal → **Create Static Web App** → link the repo (app location `/`, no build/output folder).
3. Azure adds its own deploy workflow; keep `update-feed.yml` too, so every feed commit redeploys the site.
4. Add login: a `staticwebapp.config.json` route rule `"allowedRoles": ["authenticated"]` with Microsoft Entra ID sign-in.
   Locking access to your own tenant requires custom authentication, available on the Standard plan.

## Option C — internal server / Azure App Service
Copy `index.html` to any web server (IIS, nginx) and run `python feed_fetcher.py` every 30 minutes
in the same folder (Windows Task Scheduler, cron or an Azure Functions timer trigger).

**Not suitable:** SharePoint/OneDrive document libraries don't run custom HTML pages — they download them instead.

---
## APIs and feeds used by `feed_fetcher.py`
| Source | Access | What it provides |
|---|---|---|
| **TED Search API v3** — `POST https://api.ted.europa.eu/v3/notices/search` | Free, no key | Polish tenders: power-plant construction, generating sets, gas turbines, CHP, nuclear |
| **Sejm ELI API** — `https://api.sejm.gov.pl/eli/acts/DU/{year}` | Free, public | Laws and regulations in Dziennik Ustaw (energy, capacity market, RES, nuclear) |
| **Google News RSS**, filtered by allow-list | Free | Items **only** from approved publishers: gov.pl, URE, PSE, company newsrooms, WNP, PAP, Reuters, WNN … everything else is discarded |
| **Direct RSS** (`DIRECT_RSS` list) | Free | Add feeds from company and government sites after confirming their RSS URLs |
| **Azure OpenAI** (optional) | Your Azure subscription | 50–60-word English summaries, better tagging and an off-topic filter |

Also available for later extensions:
- **PSE data API** (`https://api.raporty.pse.pl/`) — free REST API for system data such as load, generation and market prices; useful for a "market indicators" strip rather than news.
- **ENTSO-E Transparency Platform** — free security token; outages and generation by unit.
- ESPI/EBI company filings have no free official API; licensed vendor feeds exist, and company IR pages are the free route.

### Enable AI summaries
Repository **Settings → Secrets → Actions**: add `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT`.
Without them the fetcher still works and uses the publisher's own snippet.

### Tuning
- Frequency: `cron` in `update-feed.yml` (`*/30 * * * *` = every 30 min, UTC). GitHub may delay scheduled runs at busy times.
- Topics: edit `QUERIES`, `RULES` (category keywords) and `COMPANIES` in `feed_fetcher.py`.
- Trusted sources: edit `PRIMARY` and `MEDIA` (the allow-list).
- History kept: `LOOKBACK_DAYS` (default 30) and `MAX_SIGNALS` (default 400).

### Governance
- Live items are machine-tagged. Have an analyst review them before they go into client newsletters, especially items with investment relevance.
- Respect each site's terms of use; the fetcher uses APIs and RSS only and does no page scraping.
- Get IT/security approval before hosting client-facing material outside your corporate tenant.
