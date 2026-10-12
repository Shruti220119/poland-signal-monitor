# Adding the live feed to https://shruti220119.github.io/poland-signal-monitor/

## Upload (GitHub website → your repository)
1. **Add file → Upload files**: `index.html` (replaces the current one), `signals.json`, `feed_fetcher.py`, `requirements.txt`. Commit.
2. **Add file → Create new file**, name `.github/workflows/update-feed.yml`, paste the content of that file from this kit. Commit.
   (If the file already exists, open it, click the pencil and replace the content.)
3. **Settings → Actions → General → Workflow permissions → Read and write permissions → Save.**
4. **Settings → Secrets and variables → Actions** — add translation keys (needed for Polish news):
   - Azure OpenAI (recommended): `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT`
   - or Azure Translator: `AZURE_TRANSLATOR_KEY`, `AZURE_TRANSLATOR_REGION`
5. **Actions → Update signal feed → Run workflow.** After it turns green, reload the site (Ctrl+F5).
   The header will read **"Live feed · updated …"**.

## What signals.json contains
- 85 curated signals (`curated: true`) with a 30–40-word English summary.
  Edit any of these fields in signals.json on GitHub and the dashboard shows the change on the next reload.
- New articles (`auto: true`) added every 30 minutes, with the same fields, marked **LIVE FEED** on the dashboard.

## Rules enforced
- English only: Polish articles are translated (marked PL → EN); without a translation key they are skipped.
- Only approved authentic sources (allow-list in `feed_fetcher.py`: PRIMARY, MEDIA).
- Curated signals are never removed by the fetcher; live items are capped at 300 (`MAX_AUTO_SIGNALS`).

## Notes
- With Azure Translator only, summaries are the translated publisher description (max 40 words, may be shorter). Azure OpenAI writes full
  30–40-word summaries.
- Live items are machine-generated; review them before using in client newsletters.
