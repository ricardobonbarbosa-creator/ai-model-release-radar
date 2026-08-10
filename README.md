# AI Model Release Radar

A fully automated daily monitoring agent for new AI model releases.

## What it does
- Every day at **08:00 BRT (11:00 UTC)**, a GitHub Action runs `fetch_digest.py`.
- It pulls new items from OpenAI, Anthropic, Google AI/DeepMind, Meta AI, Mistral AI,
  Stability AI, Hugging Face blog + trending models API, and arXiv (cs.AI/cs.CL).
- Results are deduplicated, saved to `data/history.json` and `data/latest.json`.
- A **GitHub Issue** is opened with the day's digest (title: `AI Model Release Digest — YYYY-MM-DD`),
  which GitHub emails to you automatically as a notification.
- The dashboard in `docs/index.html` is redeployed to **GitHub Pages**, reading from `data/history.json`.

## One-time setup
1. Go to **Settings → Pages** in this repo.
2. Under "Build and deployment", set Source to **GitHub Actions**.
3. (Optional) Make sure your GitHub notification settings send issue emails to your inbox
   (Settings → Notifications → "Issues" → Email).
4. Trigger the first run manually: **Actions → Daily AI Model Release Digest → Run workflow**.

## Files
- `fetch_digest.py` — the fetch/aggregation agent.
- `.github/workflows/daily-digest.yml` — the daily scheduler + issue + Pages deploy.
- `docs/index.html` — the live dashboard.
- `data/history.json` — rolling 90-day history (auto-updated).
- `data/latest.json` — most recent day's digest (auto-updated).

## Customizing sources
Edit the `RSS_SOURCES` dict and `HF_TRENDING_API` / `ARXIV_API` constants at the top of
`fetch_digest.py` to add or remove providers.
