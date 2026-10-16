# Poland Energy Market Intelligence — GitHub update toolkit (v6)

Refreshes the Live News Feed every 30 minutes with GitHub Actions.
Signal categories are applied by the dashboard itself, so the news feed stays uncategorised.

## What's in the toolkit
| File | Purpose |
|---|---|
| `.github/workflows/update-news.yml` | Runs every 30 min (and on demand), commits new articles |
| `scripts/fetch_news.py` | Reads RSS feeds, keeps Poland energy news, translates Polish → English, tags company / technology / region, removes duplicates |
| `config/sources.json` | Feed list and relevance keywords — edit here to add or remove sources |
| `data/signals.json` | The live feed file the dashboard reads |
| `requirements.txt` | Python dependency (translator) |
| `.nojekyll` | Makes GitHub Pages serve files as they are |

## Set-up (one time)
1. **Dashboard:** in your repo, upload `poland-energy-market-intelligence-v6.html` and rename it to **`index.html`** (replace the old one).
2. **Check the data path:** open `index.html`, search for `fetch(` near `d.signals`, and note the file name it loads (e.g. `data/signals.json`). If it's different, change `DATA_PATH` in `update-news.yml` to match.
3. **Upload the toolkit:** *Add file → Upload files*, drag in all toolkit folders/files (keep the `.github/workflows` folder structure), then *Commit changes*.
4. **Allow the bot to commit:** *Settings → Actions → General → Workflow permissions →* **Read and write permissions** → *Save*.
5. **GitHub Pages:** *Settings → Pages → Deploy from a branch → main / (root)*.
6. **First run:** *Actions → Update Poland Energy news feed → Run workflow*. When it turns green, refresh the dashboard.

## Day-to-day
- New articles arrive automatically every 30 minutes (GitHub may delay scheduled runs by a few minutes).
- **Add a source:** add a line to `config/sources.json` (`publisher`, RSS `url`, `lang` = `en`/`pl`, `type`).
- **Manual refresh:** *Actions → Run workflow*.
- **Troubleshooting:** open the latest run in *Actions*; each feed logs how many items it read. A feed showing `!` is unreachable — replace or remove it.

## Notes
- English items must mention Poland; Polish items are kept if they are energy-related. Polish items are only shown once translated (`PL → EN`).
- Scheduled workflows pause after 60 days without repo activity — the bot's commits normally keep it active.
