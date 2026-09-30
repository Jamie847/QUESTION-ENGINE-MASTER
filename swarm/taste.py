from __future__ import annotations

from pathlib import Path

import yaml

from swarm.models import TasteExample, TasteProfile

ROOT = Path(__file__).resolve().parent.parent
# Operator file wins. Ratings are next. The bundled file is a labelled stand-in.
OPERATOR_SEED = ROOT / "taste" / "seed.yaml"
STAND_IN_SEED = ROOT / "data" / "taste_seed.yaml"

STEERING = {
    "operator-file": "Curator steering by: Operator seed",
    "operator-ratings": "Curator steering by: Operator ratings",
    "stand-in": "Curator steering by: stand-in seed (not the Operator's)",
}

_KEEP_STARS = {4, 5}
_KILL_STARS = {1, 2}


def load_seed_profile() -> TasteProfile:
    return load_taste()[0]


def load_taste() -> tuple[TasteProfile, str]:
    if OPERATOR_SEED.exists() and OPERATOR_SEED.stat().st_size > 0:
        return _from_yaml(OPERATOR_SEED), "operator-file"
    rated = _ratings_profile()
    if rated is not None:
        return rated, "operator-ratings"
    return _from_yaml(STAND_IN_SEED), "stand-in"


def steering_label(source: str | None = None) -> str:
    if source is None:
        _profile, source = load_taste()
    return STEERING.get(source, STEERING["stand-in"])


def ratings_seed_ready() -> bool:
    return _ratings_profile() is not None


def _from_yaml(path: Path) -> TasteProfile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    keeps = [
        TasteExample(
            stars=row["stars"],
            question=_clean(row["question"]),
            why=row.get("why", ""),
            keep=True,
        )
        for row in raw.get("keeps") or []
    ]
    kills = [
        TasteExample(
            stars=row["stars"],
            question=_clean(row["question"]),
            why=row.get("why", ""),
            keep=False,
        )
        for row in raw.get("kills") or []
    ]
    return TasteProfile(
        keep_exemplars=keeps,
        kill_exemplars=kills,
        anti_patterns=_anti_patterns(),
        notes=str(raw.get("notes") or "").strip(),
    )


def _ratings_profile() -> TasteProfile | None:
    """Most recent 6 keeps and 5 kills that carry a why. No model summarises them."""
    try:
        from sqlalchemy import select

        from swarm.db import session_scope
        from swarm.orm import QuestionRow, RatingRow
    except Exception:
        return None
    try:
        with session_scope() as session:
            rows = session.execute(
                select(QuestionRow.text, RatingRow.stars, RatingRow.why, RatingRow.updated_at)
                .join(RatingRow, RatingRow.question_id == QuestionRow.id)
                .where(RatingRow.why.is_not(None))
                .where(RatingRow.why != "")
                .order_by(RatingRow.updated_at.desc())
            ).all()
    except Exception:
        return None
    keeps = [row for row in rows if int(row.stars) in _KEEP_STARS]
    kills = [row for row in rows if int(row.stars) in _KILL_STARS]
    if len(keeps) < 5 or len(kills) < 5:
        return None
    return TasteProfile(
        keep_exemplars=[
            TasteExample(stars=int(row.stars), question=_clean(row.text), why=_clean(row.why), keep=True)
            for row in keeps[:6]
        ],
        kill_exemplars=[
            TasteExample(stars=int(row.stars), question=_clean(row.text), why=_clean(row.why), keep=False)
            for row in kills[:5]
        ],
        anti_patterns=_anti_patterns(),
        notes="Built from the Operator's ratings. No model summarised them.",
    )


def _anti_patterns() -> list[str]:
    return [
        "implications of",
        "how will X affect",
        "opportunities at the intersection",
        "ethical concerns around",
        "is this the year of",
        "how can nonprofits use",
    ]


def _clean(text: str) -> str:
    return " ".join(str(text).split())


def profile_for_prompt(profile: TasteProfile, *, keep_n: int = 6, kill_n: int = 5) -> str:
    """Compressed few-shot block. Exemplars rotate later when ratings exist."""
    lines = [profile.notes, "", "KEEP (examples of the user's taste):"]
    for ex in profile.keep_exemplars[:keep_n]:
        lines.append(f"- ({ex.stars}★) {ex.question}")
        if ex.why:
            lines.append(f"  why: {ex.why}")
    lines.append("")
    lines.append("KILL (do not produce these shapes):")
    for ex in profile.kill_exemplars[:kill_n]:
        lines.append(f"- ({ex.stars}★) {ex.question}")
        if ex.why:
            lines.append(f"  why: {ex.why}")
    return "\n".join(lines)
