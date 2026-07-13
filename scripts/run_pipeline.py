"""End-to-end pipeline: ingest -> score -> forecast -> insights.

Usage:
    python -m scripts.run_pipeline --all
    python -m scripts.run_pipeline --ingest --sentiment
    python -m scripts.run_pipeline --forecast --insights
"""
from __future__ import annotations

import argparse

# Only lightweight, always-available modules are imported at top level. Each stage
# imports its own (often heavy) dependencies lazily inside main(), so you can run a
# subset — e.g. offline insights — without installing pytrends/praw/torch/prophet.
from solesight import config, db


def main() -> None:
    p = argparse.ArgumentParser(description="Run the SoleSight pipeline stages.")
    p.add_argument("--all", action="store_true", help="run every stage")
    p.add_argument("--reddit", action="store_true", help="ingest Reddit chatter")
    p.add_argument("--trends", action="store_true", help="ingest Google Trends")
    p.add_argument("--social", action="store_true", help="ingest social buzz")
    p.add_argument("--resale", action="store_true", help="ingest resale prices")
    p.add_argument("--wiki", action="store_true", help="ingest Wikipedia attention")
    p.add_argument("--boutiques", action="store_true", help="ingest boutique availability")
    p.add_argument("--sentiment", action="store_true", help="score sentiment")
    p.add_argument("--forecast", action="store_true", help="Prophet forecast")
    p.add_argument("--insights", action="store_true", help="marketing insights")
    p.add_argument("--offline-insights", action="store_true",
                   help="force the offline rule engine even if OPENAI_API_KEY is set")
    args = p.parse_args()

    db.init_db()

    run_all = args.all or not any(
        [args.reddit, args.trends, args.social, args.resale, args.wiki,
         args.boutiques, args.sentiment,
         args.forecast, args.insights, args.offline_insights]
    )
    want_insights = run_all or args.insights or args.offline_insights

    def _try_stage(module):
        try:
            module.run()
        except NotImplementedError as exc:
            print(f"  ! skipped: {exc}")

    if run_all or args.reddit:
        from solesight.ingest import reddit
        print("[1/9] Reddit ingestion"); reddit.run()
    if run_all or args.trends:
        from solesight.ingest import google_trends
        print("[2/9] Google Trends ingestion"); google_trends.run()
    if run_all or args.social:
        from solesight.ingest import bluesky, social
        print("[3/9] Social + community ingestion (Bluesky, keyless)")
        try:
            bluesky.run()
        except Exception as exc:
            print(f"  ! bluesky failed: {exc}")
        _try_stage(social)   # YouTube (key-gated); IG/TikTok stay modeled
    if run_all or args.wiki:
        from solesight.ingest import wikipedia
        print("[4/9] Wikipedia attention"); _try_stage(wikipedia)
    if run_all or args.boutiques:
        from solesight.ingest import boutiques
        print("[5/9] Boutique availability"); _try_stage(boutiques)
    if run_all or args.resale:
        from solesight.ingest import resale
        print("[6/9] Resale ingestion"); _try_stage(resale)
    if run_all or args.sentiment:
        from solesight.nlp import sentiment
        print("[7/9] Sentiment scoring"); sentiment.run()
    if run_all or args.forecast:
        from solesight.forecast import prophet_model
        print("[8/9] Prophet forecasting"); prophet_model.run()
    if want_insights:
        if args.offline_insights or not config.OPENAI_API_KEY:
            from solesight.insights import rules
            why = ("forced by --offline-insights" if args.offline_insights
                   else "no OPENAI_API_KEY set")
            print(f"[9/9] Insights: offline rule engine ({why})"); rules.run()
        else:
            from solesight.insights import llm
            print("[9/9] Insights: OpenAI"); llm.run()

    print("Done.")


if __name__ == "__main__":
    main()
