# Question Engine

A daily agentic swarm that **interrogates** emerging trends instead of summarizing them. It pulls signals across AI, Health, Business/Finance, Science, Education, Geopolitics, and Commodities & Industry, hunts for non-obvious intersections, writes questions through three lenses (contrarian, second-order, opportunity), and lets a curator kill anything generic.

Output is a structured digest in **Postgres** (SQLite locally) plus an interactive dashboard. Download any day as markdown for project knowledge. There are no GitHub commits from the cron — Render's filesystem is ephemeral, and the deploy repo is the wrong archive.

Phase 1 on purpose: thinner swarm, Pydantic contracts, checkpoints, a run lock, a hard dollar budget, degraded-run tolerance, **lexical** dedup (no Voyage, no pgvector), a seeded taste file, rejected intersections next to the curator's kill floor, and a near-miss sample so paraphrase can be flagged by a person.

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

```bash
python -m swarm.run_correspondent   # draft this week's essay; never publishes
```

The Correspondent reads stored digests only. Fill `content/voice.md` yourself — an AI-written voice under Jamie's name is the same failure as an AI-written taste seed. Drafts stay drafts until the publish gate clears (Operator taste seed + three rated weeks), and even then there is no send path.

If the Anthropic key **is** set and every model call fails (a 400 is the usual culprit: Claude 5 adaptive thinking plus a forced `tool_choice`), the run **fails closed**. It will not archive a template digest and pretend Fable wrote it. Cron logs will include the API error body.

- `ANTHROPIC_MODEL` (default `claude-sonnet-5`) — scouts and smiths
- `JUDGMENT_MODEL` (default `claude-fable-5`) — cross-pollinator, curator, and the opportunity desk
- `ANTHROPIC_WORKSPACE_ID` — required if the key is identity-linked / multi-workspace (`wrkspc_…`). A key scoped to one workspace does not need it.
- Dedup is **lexical** (no Voyage, no pgvector). `/healthz` reports `pgvector_installed: false` on purpose. See `docs/CP-RULING-dedup.md`.

The dashboard is open (`DASHBOARD_AUTH=off`). That is the intended posture (WO-005), not a defect. Spend is bounded by `RUN_BUDGET_USD` per run, `MAX_RUNS_PER_DAY` (default 5), and a per-IP cooldown on `POST /api/run`. Set `DASHBOARD_AUTH` to any other value to turn the token gate back on.

## Daily pipeline

1. **Fetch** — Brave (if keyed), HN, Wikipedia, Federal Register (final/proposed rules only), arXiv, journals, GDELT, ReliefWeb, CFTC, and EIA/FRED when those free keys are set. A dead source (N consecutive zeros) is named **dead**, not quiet. It does not abort the run. No Perplexity.
2. **Scout** — one pass per enabled vertical → structured briefs.
3. **Cross-pollinator** — intersections with surprise, plausibility, and a **coverage** score (`none` / `thin` / `crowded` / `unknown`). Coverage is visible. It cannot promote a question. Rejected pairings are persisted.
4. **Smiths** — one lens each.
5. **Dedup** — lexical (content-token Jaccard) against the batch and the last 45 days. Does not catch paraphrase. The digest samples adjacent-day survivors so a person can flag a miss.
6. **Curator** — taste seed (later: weekly compressed profile + rotating exemplars).
7. **Desk** — optional. Assays the top linked questions (and anything saved since the last run), checks the premise, and writes a Pursue/Park/Kill card. Skipped when the run budget is spent. Cited pages are not fetched; cards say so.
8. **Archivist** — markdown digest written to the database.

`--resume <run_id>` continues from the last finished stage. Runs are **manual only until the Operator rates the five existing digests** (CP 2026-09-08). After that the weekday cron is `0 10 * * 1-5`. Until then the Blueprint schedule stays 29 February (Render requires a schedule field). Both manual paths stay: Controls → Run swarm now (`POST /api/run`) and Render → cron → Trigger Run. A lock prevents overlap. Digests are unique per **run**, not per date — a second same-day click keeps the first digest. Today and the digest footer show how old the last run is.

## Dashboard

- **Today** — opportunities from this run, digest, 1–5★ ratings, Assay this, promote-to-ideation, coverage flags, rejects, kill floor.
- **Opportunities** — every checked card, newest first, filterable by verdict.
- **Archive** — search/filter the question bank; per-day `.md` download.
- **Taste** — seeded keep/kill exemplars, the Operator's assets profile, your ratings, and a lexical-duplicate count that is labeled as token overlap only.
- **Issues** — The Correspondent. Weekly essay draft from the week's best question. Never auto-published. `GET /issues/{date}.md`.
- **Controls** — manual run, source health, verticals/lenses.

## Deploy on Render

`render.yaml` is the whole deploy. It creates three things in one Blueprint:

| Resource | Name | Role |
|---|---|---|
| Postgres | `question-engine-db` | Canonical store (digests, questions, ratings, run lock) |
| Web | `question-engine-dashboard` | FastAPI UI, binds `0.0.0.0:$PORT`, health at `/healthz` |
| Cron | `question-engine-swarm` | Manual Trigger Run only. Schedule is `0 0 29 2 *` (leap-day) because Render requires a schedule. |

### Hand this to Claude Cowork (or apply it yourself)

1. Put this repo on GitHub (Render cannot clone a Cursor-only remote).
2. In the Render dashboard, open **My Workspace** → **New Blueprint** → point it at this repo / `render.yaml`.
3. When prompted, paste:
   - `ANTHROPIC_API_KEY` (required for a real digest)
   - `BRAVE_API_KEY` (required for Health and Business scouts)
   - `EIA_API_KEY` / `FRED_API_KEY` (optional; Commodities movers stay dark without them)
   - `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` (application-only OAuth; without them Reddit errors instead of returning a silent zero)
   - Leave `PERPLEXITY_API_KEY` blank. CP ruled no Perplexity.
4. Open `https://question-engine-dashboard.onrender.com/controls` and click **Run swarm now**.
5. Prove infra before trusting a digest: `GET /healthz` on the web service, and `python -m swarm.run_daily --healthcheck` on the cron (look for `CRON_HEALTHCHECK_PASS`).
6. After the first deploy is live, trigger an immediate run from **Controls** (do not wait for 10:00 UTC). Check source health: Brave and HN should be up; Reddit may be DOWN — leave it.

Do not add an ideator, resurrection agent, or extra verticals on this deploy. Three keyed digests first.

Suggested order: keys in → Blueprint apply → three real Opus-curated days → rate everything → then prompts vs ideator.

Replace `data/taste_seed.yaml` with your own voice, or drop `taste/seed.yaml` (preferred if present). That file needs you, not a stand-in.

## Tests

```bash
pytest -q
python scripts/measure_paraphrase_leak.py   # gray-zone pairs; official after 21 digest days
```

## What is intentionally not here yet

Ideator, resurrection timeline, weekly taste-profile compressor, eval harness, Perplexity-backed coverage, and extra verticals/lenses. Held until three keyed digests have been read and rated. If those are generic, the fix is prompt work, not more agents.
