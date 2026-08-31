# Question Engine

A daily agentic swarm that **interrogates** emerging trends instead of summarizing them. It pulls signals across a thin set of verticals (AI, Health, Business/Finance), hunts for non-obvious intersections, writes questions through three lenses (contrarian, second-order, opportunity), and lets a curator kill anything generic.

Output is a structured digest in **Postgres** (SQLite locally) plus an interactive dashboard. Download any day as markdown for project knowledge. There are no GitHub commits from the cron — Render's filesystem is ephemeral, and the deploy repo is the wrong archive.

Phase 1 on purpose: thinner swarm, Pydantic contracts, checkpoints, a run lock, a hard dollar budget, degraded-run tolerance, semantic dedup, a seeded taste file, and rejected intersections logged next to the curator's kill floor.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m swarm.run_daily
uvicorn dashboard.main:app --host 0.0.0.0 --port 43417
```

Open `http://127.0.0.1:43417`. The swarm works **without API keys**: Hacker News, Reddit, and Wikipedia are fetched live; a heuristic writer drafts briefs and questions; a seeded taste file keeps the curator opinionated. Add `ANTHROPIC_API_KEY` (and optionally `BRAVE_API_KEY` / `PERPLEXITY_API_KEY`) to upgrade quality.

`ACCESS_TOKEN` locks the dashboard. Leave it empty locally.

## Daily pipeline

1. **Fetch** — Brave (if keyed), HN, Reddit, Wikipedia. A dead source degrades the run; it does not abort it.
2. **Scout** — one pass per enabled vertical → structured briefs.
3. **Cross-pollinator** — intersections with surprise, plausibility, and a **coverage** score (`none` / `thin` / `crowded` / `unknown`). Coverage is visible. It cannot promote a question. Rejected pairings are persisted.
4. **Smiths** — one lens each.
5. **Dedup** — near-duplicates against the batch and the last 45 days.
6. **Curator** — taste seed (later: weekly compressed profile + rotating exemplars).
7. **Archivist** — markdown digest written to the database.

`--resume <run_id>` continues from the last finished stage. `POST /api/run` is the manual trigger; a lock prevents overlap with the cron.

## Dashboard

- **Today** — digest, 1–5★ ratings, promote-to-ideation, coverage flags, rejects, kill floor.
- **Archive** — search/filter the question bank; per-day `.md` download.
- **Taste** — seeded keep/kill exemplars and your ratings.
- **Controls** — manual run, source health, verticals/lenses.

## Deploy on Render

`render.yaml` defines the web service, the 10:00 UTC cron, and Postgres. On first deploy you will be prompted for the API keys (`sync: false`). The dashboard binds `0.0.0.0:$PORT`. Set `ANTHROPIC_API_KEY` when you want model-written questions; the rest can stay empty.

## Tests

```bash
pytest -q
```

## What is intentionally not here yet

Ideator, resurrection timeline, weekly taste-profile compressor, eval harness, Perplexity-backed coverage, and extra verticals/lenses. Use the first weeks of real digests and ratings to freeze an eval set — do not hand-write one before the swarm has a voice.
