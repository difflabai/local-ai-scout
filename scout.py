#!/usr/bin/env python3
"""
xscout — Multi-Source AI Intel Pipeline

Pulls posts from X, Reddit, CivitAI, HackerNews, and other sources → sends to NanoGPT LLM API → outputs intel brief.

Usage:
  python3 scout.py                                        # X source (default)
  python3 scout.py --source reddit --topic "SDXL"         # Reddit source
  python3 scout.py --source civitai --topic "SDXL"        # CivitAI models
  python3 scout.py --source hackernews --topic "LLMs"     # HackerNews
  python3 scout.py --source all --topic "local LLMs"      # All sources
  python3 scout.py --save                                 # Save brief to briefs/
  python3 scout.py --from-file posts.json                 # Replay from saved data

Required env vars:
  NANOGPT_API_KEY     — NanoGPT API key

Source-specific env vars:
  X_BEARER_TOKEN      — X API bearer token (or X_CONSUMER_KEY + X_API_KEY)
"""

import json
import os
import sys
import argparse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from config import (
    DEFAULT_QUERIES, LOOKBACK_HOURS, MAX_RESULTS_PER_QUERY,
    LLM_MODEL, MAX_TOKENS, SCOUT_FOCUS,
)
from prompt import build_system_prompt
from queries import build_topic_queries
from sources import ADAPTERS, Post


# ─── FETCH POSTS ─────────────────────────────────────────────────────────────

def fetch_posts(source_names: list[str], topic: str, queries: list[str] | None) -> list[Post]:
    """Fetch posts from one or more source adapters."""
    all_posts: list[Post] = []

    for name in source_names:
        adapter_cls = ADAPTERS.get(name)
        if not adapter_cls:
            print(f"❌ Unknown source: {name!r}. Available: {', '.join(ADAPTERS)}", file=sys.stderr)
            sys.exit(1)

        adapter = adapter_cls()
        # Only pass raw queries to X adapter (Reddit uses topic directly)
        adapter_queries = queries if name == "x" else None
        try:
            posts = adapter.fetch(
                topic=topic,
                lookback_hours=LOOKBACK_HOURS,
                max_results=MAX_RESULTS_PER_QUERY,
                queries=adapter_queries,
            )
            all_posts.extend(posts)
        except Exception as e:
            print(f"⚠ {name} source failed: {e}", file=sys.stderr)

    return all_posts


def posts_to_json(posts: list[Post], topic: str) -> str:
    """Serialize posts to JSON for the LLM."""
    data = {
        "pulled_at": datetime.now().isoformat(),
        "topic": topic,
        "total_posts": len(posts),
        "posts": [asdict(p) for p in posts],
    }
    return json.dumps(data, indent=2)


# ─── GENERATE BRIEF ─────────────────────────────────────────────────────────

def generate_brief(posts_json: str, system_prompt: str) -> str:
    api_key = os.environ.get("NANOGPT_API_KEY", "")
    if not api_key:
        print("❌ NANOGPT_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    from urllib.request import Request, urlopen

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
    parser = argparse.ArgumentParser(description="xscout — Multi-Source AI Intel Pipeline")
    parser.add_argument("--save", action="store_true", help="Save brief to briefs/ directory")
    parser.add_argument("--save-posts", action="store_true", help="Also save raw posts JSON")
    parser.add_argument("--save-tweets", action="store_true", help="Alias for --save-posts (backwards compat)")
    parser.add_argument("--from-file", help="Use saved JSON instead of pulling fresh")
    parser.add_argument(
        "--topic", default="",
        help="Topic/domain to scout (default: local AI). Also via SCOUT_FOCUS env var",
    )
    parser.add_argument(
        "--queries", nargs="+", default=None,
        help="Raw X API query strings (bypass query builder entirely)",
    )
    parser.add_argument(
        "--source", default="x",
        choices=["x", "reddit", "civitai", "hackernews", "arxiv", "github", "lobsters", "producthunt", "huggingface", "bluesky", "all"],
        help="Source to pull from (default: x)",
    )
    args = parser.parse_args()

    # Resolve topic: CLI --topic > SCOUT_FOCUS env var > default
    topic = args.topic or SCOUT_FOCUS or ""
    if topic:
        print(f"🎯 Focus: {topic}", file=sys.stderr)
        system_prompt = build_system_prompt(topic=topic, topic_description=topic)
    else:
        system_prompt = build_system_prompt()

    # Resolve queries: --queries flag > topic builder > defaults (X only)
    if args.queries:
        queries = args.queries
        print(f"🔎 Using {len(queries)} raw quer{'y' if len(queries)==1 else 'ies'}", file=sys.stderr)
    elif topic:
        queries = build_topic_queries(topic)
    else:
        queries = DEFAULT_QUERIES

    # Resolve source list
    if args.source == "all":
        source_names = list(ADAPTERS.keys())
    else:
        source_names = [args.source]

    # Step 1: Get posts
    if args.from_file:
        print(f"📂 Loading {args.from_file}", file=sys.stderr)
        posts_json = Path(args.from_file).read_text()
    else:
        print(f"📡 Pulling from: {', '.join(source_names)}", file=sys.stderr)
        posts = fetch_posts(source_names, topic or "local AI", queries)
        if not posts:
            print("⚠ No posts found from any source.", file=sys.stderr)
        posts_json = posts_to_json(posts, topic or "local AI")
        total = len(posts)
        print(f"  ✅ {total} total posts", file=sys.stderr)

    # Step 2: Generate brief
    brief = generate_brief(posts_json, system_prompt)

    # Step 3: Output
    print(brief)

    save_posts = args.save_posts or args.save_tweets
    if args.save or save_posts:
        briefs_dir = Path(__file__).parent / "briefs"
        briefs_dir.mkdir(exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")

        if args.save:
            brief_path = briefs_dir / f"{date_str}.md"
            brief_path.write_text(brief)
            print(f"  💾 Brief → {brief_path}", file=sys.stderr)

        if save_posts:
            posts_path = briefs_dir / f"{date_str}-posts.json"
            posts_path.write_text(posts_json)
            print(f"  💾 Posts → {posts_path}", file=sys.stderr)

    print("✅ Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
