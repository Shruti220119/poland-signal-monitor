# Poland Energy Market Intelligence — GitHub update toolkit (v6.1)

Refreshes the Live News Feed every 30 minutes with GitHub Actions. All sources are free (no API keys).
Signal categories are applied by the dashboard, so the news feed stays uncategorised.

## Files
| File | Purpose |
|---|---|
| `.github/workflows/update-news.yml` | Runs every 30 min / on demand; commits new articles (retries on push conflicts) |
| `scripts/fetch_news.py` | Reads feeds, filters Poland energy news, translates PL→EN, tags company/technology/region, de-duplicates. A failing feed or item never stops the run |
| `config/sources.json` | Feed list and keywords |
| `data/signals.json` | Live feed file read by the dashboard |

## Set-up
1. Upload the v6 dashboard as `index.html` (repo root).
2. In `index.html` search `fetch(` — the path must match `DATA_PATH` in the workflow (default `data/signals.json`).
3. Upload all toolkit files, keeping `.github/workflows/`.
4. Settings → Actions → General → Workflow permissions → **Read and write** → Save.
5. Settings → Pages → Deploy from branch → main / (root).
6. Actions → Update Poland Energy news feed → **Run workflow**.

## Troubleshooting
| Error in Actions log | Fix |
|---|---|
| `Permission ... denied to github-actions[bot]` / `403` | Step 4 |
| `No such file or directory: config/sources.json` | Upload `config/` folder to repo root |
| `! <feed>: HTTPError 403/404` | Feed blocked/moved — remove or replace in `sources.json` (run still succeeds) |
| `No feed could be reached` | Temporary network issue — re-run |
| Workflow not in Actions tab | File must be at `.github/workflows/update-news.yml` exactly |
| Dashboard shows update error but Actions is green | Path in `index.html` `fetch(...)` ≠ `DATA_PATH`; or page opened locally (`file://`) instead of the github.io URL; hard refresh (Ctrl+F5) |
