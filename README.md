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

Open `http://127.0.0.1:43417`. The swarm runs without keys (Hacker News + Wikipedia; Reddit if the host allows it), but that path is a **heuristic fallback**. Do not judge question quality until `ANTHROPIC_API_KEY` and `BRAVE_API_KEY` are set — HN alone is too narrow for Health and Business, and the writer is template-shaped by design.

- `ANTHROPIC_MODEL` (default `claude-sonnet-5`) — scouts and smiths
- `JUDGMENT_MODEL` (default `claude-fable-5`) — cross-pollinator and curator
- Dedup is **lexical** (no Voyage, no pgvector). See `docs/OPEN-QUESTIONS-for-CP.md` Q1.

`DASHBOARD_TOKEN` (or `ACCESS_TOKEN`) locks the dashboard. Leave it empty locally.

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

`render.yaml` is the whole deploy. It creates three things in one Blueprint:

| Resource | Name | Role |
|---|---|---|
| Postgres | `question-engine-db` | Canonical store (digests, questions, ratings, run lock) |
| Web | `question-engine-dashboard` | FastAPI UI, binds `0.0.0.0:$PORT`, health at `/healthz` |
| Cron | `question-engine-swarm` | `python -m swarm.run_daily` at 10:00 UTC |

### Hand this to Claude Cowork (or apply it yourself)

1. Put this repo on GitHub (Render cannot clone a Cursor-only remote).
2. In the Render dashboard, open **My Workspace** → **New Blueprint** → point it at this repo / `render.yaml`.
3. When prompted, paste:
   - `ANTHROPIC_API_KEY` (required for a real digest)
   - `BRAVE_API_KEY` (required for Health and Business scouts)
   - `PERPLEXITY_API_KEY` (optional — leave blank)
4. `DASHBOARD_TOKEN` is auto-generated. Copy it from the env group after deploy and open `https://<service>.onrender.com/?token=…`.
5. Prove infra before trusting a digest: `GET /healthz` on the web service, and `python -m swarm.run_daily --healthcheck` on the cron (look for `CRON_HEALTHCHECK_PASS`).
6. After the first deploy is live, trigger an immediate run from **Controls** (do not wait for 10:00 UTC). Check source health: Brave and HN should be up; Reddit may be DOWN — leave it.

Do not add an ideator, resurrection agent, or extra verticals on this deploy. Three keyed digests first.

Suggested order: keys in → Blueprint apply → three real Opus-curated days → rate everything → then prompts vs ideator.

Replace `data/taste_seed.yaml` with your own voice, or drop `taste/seed.yaml` (preferred if present). That file needs you, not a stand-in.

## Tests

```bash
pytest -q
```

## What is intentionally not here yet

Ideator, resurrection timeline, weekly taste-profile compressor, eval harness, Perplexity-backed coverage, and extra verticals/lenses. Held until three keyed digests have been read and rated. If those are generic, the fix is prompt work, not more agents.
