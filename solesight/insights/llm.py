"""LLM-powered insight engine.

Turns raw demand signals (trend trajectory, forecast slope, Reddit sentiment and
volume) into a short plain-English marketing recommendation via the OpenAI API —
bridging data-science output and marketing execution.
"""
from __future__ import annotations

import time

from .. import config, models
from ..db import connect
from . import signals

SYSTEM_PROMPT = (
    "You are a retail consumer-insights analyst for a sneaker brand. Given demand "
    "signals for a single sneaker model, write a concise recommendation (3-4 "
    "sentences) for the marketing team: whether demand is rising or cooling, the "
    "best window to push marketing spend, and one concrete tactic. Be specific and "
    "avoid hedging. Do not invent numbers beyond what you are given."
)


def generate(model_slug: str) -> str:
    """Generate and persist a marketing recommendation for one model."""
    from openai import OpenAI

    model = models.get(model_slug)
    snap = signals.snapshot(model_slug)
    client = OpenAI(api_key=config.require("OPENAI_API_KEY"))

    user_prompt = (
        f"Sneaker model: {model.name} ({model.brand}).\n"
        f"Demand signals (Google Trends interest is a 0-100 index; "
        f"Reddit sentiment is -1 to 1):\n"
        + "\n".join(f"- {k}: {v}" for k, v in snap.items())
    )

    resp = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
    )
    summary = resp.choices[0].message.content.strip()

    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO insights (model_slug, generated_at, summary) "
            "VALUES (?, ?, ?)",
            (model_slug, int(time.time()), summary),
        )
    return summary


def run() -> None:
    for model in models.CATALOG:
        try:
            generate(model.slug)
            print(f"  insight: {model.slug} -> ok")
        except Exception as exc:
            print(f"  ! insight failed for {model.slug}: {exc}")
