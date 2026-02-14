#!/usr/bin/env python3
"""
xscout — Multi-Source AI Intel Scout

Pulls posts from X, HackerNews (and more) → sends to LLM via NanoGPT → outputs intel brief.

Usage:
  python3 scout.py                                      # twitter (default)
  python3 scout.py --source hackernews --topic "LLMs"   # HackerNews
  python3 scout.py --source all --topic "robotics"      # all sources
  python3 scout.py --save                               # save to briefs/
  python3 scout.py --from-file posts.json               # replay saved data

Required env vars:
  NANOGPT_API_KEY     — NanoGPT API key

Source-specific env vars:
  X_BEARER_TOKEN      — X API bearer token (for twitter source)
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

from config import (
    DEFAULT_QUERIES, LOOKBACK_HOURS,
    LLM_MODEL, MAX_TOKENS, SCOUT_FOCUS,
)
from prompt import build_system_prompt
from queries import build_topic_queries
from sources import TwitterSource, HackerNewsSource


# ─── SOURCE REGISTRY ────────────────────────────────────────────────────────

SOURCE_MAP = {
    "twitter": TwitterSource,
    "x": TwitterSource,
    "hackernews": HackerNewsSource,
    "hn": HackerNewsSource,
}

ALL_SOURCES = [TwitterSource, HackerNewsSource]

VALID_SOURCE_NAMES = sorted(set(SOURCE_MAP.keys()) | {"all"})


def _build_plain_queries(topic: str) -> list[str]:
    """Build simple keyword queries from a topic string (for non-Twitter sources).

    Splits comma-separated topic into individual search terms.
    """
    terms = [t.strip() for t in topic.split(",") if t.strip()]
    return terms if terms else [topic]


# ─── GENERATE BRIEF ─────────────────────────────────────────────────────────

def generate_brief(posts_json: str, system_prompt: str) -> str:
    from urllib.request import Request, urlopen

    api_key = os.environ.get("NANOGPT_API_KEY", "")
    if not api_key:
        print("❌ NANOGPT_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    body = json.dumps({
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Brief me.\n\n{posts_json}"},
        ],
    }).encode()

    req = Request("https://nano-gpt.com/api/v1/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    print("  🧠 Generating brief...", file=sys.stderr)

    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"❌ LLM API error: {e}", file=sys.stderr)
        sys.exit(1)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="xscout — Multi-Source AI Intel Scout")
    parser.add_argument("--save", action="store_true", help="Save brief to briefs/ directory")
    parser.add_argument("--save-tweets", action="store_true", help="Also save raw post data JSON")
    parser.add_argument("--from-file", help="Use saved JSON instead of fetching fresh")
    parser.add_argument(
        "--topic", default="",
        help="Topic/domain to scout (default: local AI). Also via SCOUT_FOCUS env var",
    )
    parser.add_argument(
        "--queries", nargs="+", default=None,
        help="Raw query strings (bypass query builder entirely)",
    )
    parser.add_argument(
        "--source", default="twitter",
        choices=VALID_SOURCE_NAMES,
        help="Source to pull from: twitter, hackernews (hn), or all (default: twitter)",
    )
    args = parser.parse_args()

    # Resolve topic: CLI --topic > SCOUT_FOCUS env var > default
    topic = args.topic or SCOUT_FOCUS or ""
    if topic:
        print(f"🎯 Focus: {topic}", file=sys.stderr)
        system_prompt = build_system_prompt(topic=topic, topic_description=topic)
    else:
        system_prompt = build_system_prompt()

    # Step 1: Get posts
    if args.from_file:
        print(f"📂 Loading {args.from_file}", file=sys.stderr)
        posts_json = Path(args.from_file).read_text()
    else:
        # Determine which sources to use
        if args.source == "all":
            adapters = [cls() for cls in ALL_SOURCES]
        else:
            adapter_cls = SOURCE_MAP.get(args.source)
            if not adapter_cls:
                print(f"❌ Unknown source: {args.source}", file=sys.stderr)
                sys.exit(1)
            adapters = [adapter_cls()]

        all_posts = []
        for adapter in adapters:
            print(f"📡 Pulling from {adapter.name}...", file=sys.stderr)

            # Build queries appropriate for this source
            if args.queries:
                queries = args.queries
                print(f"🔎 Using {len(queries)} raw quer{'y' if len(queries)==1 else 'ies'}",
                      file=sys.stderr)
            elif adapter.name == "twitter":
                queries = build_topic_queries(topic) if topic else DEFAULT_QUERIES
            else:
                # Non-Twitter sources use plain keyword queries
                queries = _build_plain_queries(topic) if topic else DEFAULT_QUERIES

            posts = adapter.fetch(queries, LOOKBACK_HOURS)
            all_posts.extend(posts)

        # Serialize to JSON for the LLM
        posts_data = {
            "pulled_at": datetime.now().isoformat(),
            "lookback_hours": LOOKBACK_HOURS,
            "sources": [a.name for a in adapters],
            "total_posts": len(all_posts),
            "posts": [p.to_dict() for p in all_posts],
        }
        posts_json = json.dumps(posts_data, indent=2)

    # Step 2: Generate brief
    brief = generate_brief(posts_json, system_prompt)

    # Step 3: Output
    print(brief)

    if args.save or args.save_tweets:
        briefs_dir = Path(__file__).parent / "briefs"
        briefs_dir.mkdir(exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")

        if args.save:
            brief_path = briefs_dir / f"{date_str}.md"
            brief_path.write_text(brief)
            print(f"  💾 Brief → {brief_path}", file=sys.stderr)

        if args.save_tweets:
            tweets_path = briefs_dir / f"{date_str}-posts.json"
            tweets_path.write_text(posts_json)
            print(f"  💾 Posts → {tweets_path}", file=sys.stderr)

    print("✅ Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
