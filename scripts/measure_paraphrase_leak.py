#!/usr/bin/env python3
"""Offline paraphrase-leak measurement. Not a production stage.

After three keyed weeks of real questions, this is the one-afternoon check
CW asked for: count what lexical dedup let through, against stored text,
with no schema change and no vendor in requirements.txt.

Without an embeddings key it still reports the gray-zone lexical band
(pairs that share verticals and sit below DEDUP_THRESHOLD). That is not
semantic evidence — it is the work you can do today. Pass --embed only
when you have a throwaway Voyage (or compatible) key for a one-shot cosine
pass. Do not add a column. Do not import this from run_daily.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from swarm.db import init_db, session_scope
from swarm.dedup import similarity
from swarm.orm import DigestRow, QuestionRow
from swarm.settings import get_settings


def _curated() -> list[QuestionRow]:
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(QuestionRow)
                .where(QuestionRow.status == "curated")
                .order_by(QuestionRow.created_at.asc())
            ).all()
        )
        for r in rows:
            session.expunge(r)
        return rows


def _digest_dates() -> list[str]:
    with session_scope() as session:
        rows = list(session.scalars(select(DigestRow.date).order_by(DigestRow.date)).all())
        return [str(d) for d in rows]


def _gray_zone(
    rows: list[QuestionRow],
    *,
    floor: float,
    threshold: float,
) -> list[dict]:
    by_day: dict[str, list[QuestionRow]] = defaultdict(list)
    for r in rows:
        created = r.created_at
        day = created.date().isoformat() if created is not None else "unknown"
        by_day[day].append(r)

    days = sorted(by_day)
    pairs: list[dict] = []
    for i, day in enumerate(days):
        if i == 0:
            continue
        prior_day = days[i - 1]
        for a in by_day[day]:
            for b in by_day[prior_day]:
                shared = sorted(set(a.verticals or []) & set(b.verticals or []))
                if not shared:
                    continue
                score = similarity(a.text, b.text)
                if floor <= score < threshold:
                    pairs.append(
                        {
                            "day": day,
                            "prior_day": prior_day,
                            "score": round(score, 3),
                            "shared_verticals": shared,
                            "today": a.text,
                            "prior": b.text,
                        }
                    )
    pairs.sort(key=lambda p: -p["score"])
    return pairs


def _voyage_embed(texts: list[str], key: str) -> list[list[float]]:
    body = json.dumps(
        {"input": texts, "model": os.environ.get("EMBED_MODEL", "voyage-4"), "input_type": "document"}
    ).encode()
    req = urllib.request.Request(
        "https://api.voyageai.com/v1/embeddings",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    data = sorted(payload["data"], key=lambda row: row["index"])
    return [row["embedding"] for row in data]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-days",
        type=int,
        default=21,
        help="Keyed digest days required before this is the official measurement.",
    )
    parser.add_argument("--floor", type=float, default=0.28)
    parser.add_argument(
        "--embed",
        action="store_true",
        help="One-shot Voyage cosine pass. Needs VOYAGE_API_KEY. Not production.",
    )
    parser.add_argument("--cosine-threshold", type=float, default=0.92)
    args = parser.parse_args(argv)

    init_db()
    settings = get_settings()
    dates = _digest_dates()
    rows = _curated()
    print(f"digest_days={len(dates)} curated_questions={len(rows)} today={date.today().isoformat()}")
    if len(dates) < args.min_days:
        print(
            f"not_yet: need {args.min_days} keyed digest days for the official leak count; "
            f"have {len(dates)}. Gray-zone pairs below are still listed."
        )

    gray = _gray_zone(rows, floor=args.floor, threshold=settings.dedup_threshold)
    print(
        f"gray_zone_pairs={len(gray)} "
        f"(Jaccard {args.floor:.2f}–{settings.dedup_threshold:.2f}, shared verticals, adjacent days)"
    )
    print("note: gray-zone is still lexical. It is not the paraphrase rate.")
    for pair in gray[:15]:
        print(
            f"  {pair['score']:.2f} {pair['prior_day']} → {pair['day']} "
            f"{' × '.join(pair['shared_verticals'])}"
        )
        print(f"    today: {pair['today']}")
        print(f"    prior: {pair['prior']}")

    if not args.embed:
        print(
            "embed_pass=skipped. Re-run with --embed and VOYAGE_API_KEY after three "
            "keyed weeks for a one-afternoon cosine count. Do not add a column."
        )
        return 0 if len(dates) >= args.min_days else 3

    key = os.environ.get("VOYAGE_API_KEY", "").strip()
    if not key:
        print(
            "embed_pass=blocked: VOYAGE_API_KEY is empty. This measurement stays "
            "offline and optional. Do not put Voyage in render.yaml."
        )
        return 2

    texts = [r.text for r in rows]
    if not texts:
        print("embed_pass=empty")
        return 0
    try:
        vectors = _voyage_embed(texts, key)
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        print(f"embed_pass=failed {type(exc).__name__}: {exc}")
        return 1

    leaks = 0
    compared = 0
    by_id = {i: rows[i] for i in range(len(rows))}
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            a, b = by_id[i], by_id[j]
            if not (set(a.verticals or []) & set(b.verticals or [])):
                continue
            lex = similarity(a.text, b.text)
            if lex >= settings.dedup_threshold:
                continue
            compared += 1
            if _cosine(vectors[i], vectors[j]) >= args.cosine_threshold:
                leaks += 1
    rate = (leaks / compared) if compared else 0.0
    print(
        f"embed_pass=ok compared={compared} cosine_leaks={leaks} "
        f"leak_rate={rate:.3f} threshold={args.cosine_threshold}"
    )
    print(
        "A leak here is two curated questions that mean the same thing to the "
        "embedder and that lexical dedup let through. That is the number that "
        "can fire the re-trigger. Quiet weeks cannot."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
