#!/usr/bin/env python3
"""
Local AI Scout — Automated Pipeline

Pulls tweets from X API → sends to NanoGPT LLM API → outputs intel brief.

Usage:
  python3 scout.py                          # print brief to stdout
  python3 scout.py --topic "robotics"       # scout a different topic
  python3 scout.py --save                   # save to briefs/ directory
  python3 scout.py --from-file tweets.json  # replay from saved tweets

Required env vars:
  X_BEARER_TOKEN      — X API bearer token (or set X_CONSUMER_KEY + X_API_KEY)
  NANOGPT_API_KEY     — NanoGPT API key

Optional env vars:
  SCOUT_FOCUS         — Topic/domain to scout (default: local AI / local LLMs)
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from pathlib import Path

from config import (
    DEFAULT_QUERIES, LOOKBACK_HOURS, MAX_RESULTS_PER_QUERY,
    LLM_MODEL, MAX_TOKENS, SCOUT_FOCUS,
)
from prompt import build_system_prompt
from queries import build_topic_queries


# ─── AUTH ─────────────────────────────────────────────────────────────────────

def get_bearer_token() -> str:
    """Get bearer token from env. If only consumer/api keys are set, exchange them."""
    token = os.environ.get("X_BEARER_TOKEN", "")
    if token:
        return token

    consumer_key = os.environ.get("X_CONSUMER_KEY", "")
    api_key = os.environ.get("X_API_KEY", "")
    if not consumer_key or not api_key:
        return ""

    import base64
    creds = base64.b64encode(f"{consumer_key}:{api_key}".encode()).decode()
    req = Request("https://api.twitter.com/oauth2/token")
    req.add_header("Authorization", f"Basic {creds}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")
    data = urlencode({"grant_type": "client_credentials"}).encode()

    with urlopen(req, data) as resp:
        result = json.loads(resp.read().decode())
        return result.get("access_token", "")


# ─── STEP 1: PULL TWEETS ─────────────────────────────────────────────────────

TWEET_FIELDS = "author_id,created_at,public_metrics,entities,referenced_tweets"
USER_FIELDS = "username,name,verified,public_metrics"
EXPANSIONS = "author_id"


def search_tweets(query: str, start_time: str, bearer_token: str) -> dict:
    params = urlencode({
        "query": query,
        "max_results": min(MAX_RESULTS_PER_QUERY, 100),
        "start_time": start_time,
        "tweet.fields": TWEET_FIELDS,
        "user.fields": USER_FIELDS,
        "expansions": EXPANSIONS,
    })
    url = f"https://api.twitter.com/2/tweets/search/recent?{params}"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {bearer_token}")

    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e), "query": query}


def _enrich_with_tweet_urls(result: dict) -> dict:
    """Add tweet_url field to each tweet in the result.

    Constructs https://x.com/{username}/status/{tweet_id} using
    the includes.users expansion data.
    """
    # Build author_id → username lookup
    users = result.get("includes", {}).get("users", [])
    author_map = {u["id"]: u["username"] for u in users}

    for tweet in result.get("data", []):
        tweet_id = tweet.get("id", "")
        author_id = tweet.get("author_id", "")
        username = author_map.get(author_id, "unknown")
        tweet["tweet_url"] = f"https://x.com/{username}/status/{tweet_id}"
        tweet["author_username"] = username

    return result


def pull_tweets(bearer_token: str, queries: list[str]) -> dict:
    start_time = (
        datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    all_results = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": LOOKBACK_HOURS,
        "queries": [],
    }

    for i, query in enumerate(queries, 1):
        print(f"  [{i}/{len(queries)}] {query[:60]}...", file=sys.stderr)
        result = search_tweets(query, start_time, bearer_token)
        result = _enrich_with_tweet_urls(result)
        all_results["queries"].append({
            "query": query,
            "result_count": result.get("meta", {}).get("result_count", 0),
            "data": result.get("data", []),
            "includes": result.get("includes", {}),
            "errors": result.get("errors", result.get("error", None)),
        })

    total = sum(q["result_count"] for q in all_results["queries"])
    print(f"  ✅ {total} tweets across {len(queries)} queries", file=sys.stderr)
    return all_results


# ─── STEP 2: GENERATE BRIEF ──────────────────────────────────────────────────

def generate_brief(tweets_json: str, system_prompt: str) -> str:
    api_key = os.environ.get("NANOGPT_API_KEY", "")
    if not api_key:
        print("❌ NANOGPT_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    body = json.dumps({
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Brief me.\n\n{tweets_json}"},
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
    parser = argparse.ArgumentParser(description="Local AI Scout")
    parser.add_argument("--save", action="store_true", help="Save brief to briefs/ directory")
    parser.add_argument("--save-tweets", action="store_true", help="Also save raw tweets JSON")
    parser.add_argument("--from-file", help="Use saved tweets JSON instead of pulling fresh")
    parser.add_argument(
        "--topic", default="",
        help="Topic/domain to scout (default: local AI). Also via SCOUT_FOCUS env var",
    )
    parser.add_argument(
        "--queries", nargs="+", default=None,
        help="Raw X API query strings (bypass query builder entirely)",
    )
    args = parser.parse_args()

    # Resolve topic: CLI --topic > SCOUT_FOCUS env var > default
    topic = args.topic or SCOUT_FOCUS or ""
    if topic:
        print(f"🎯 Focus: {topic}", file=sys.stderr)
        system_prompt = build_system_prompt(topic=topic, topic_description=topic)
    else:
        system_prompt = build_system_prompt()

    # Resolve queries: --queries flag > topic builder > defaults
    if args.queries:
        queries = args.queries
        print(f"🔎 Using {len(queries)} raw quer{'y' if len(queries)==1 else 'ies'}", file=sys.stderr)
    elif topic:
        queries = build_topic_queries(topic)
    else:
        queries = DEFAULT_QUERIES

    # Step 1: Get tweets
    if args.from_file:
        print(f"📂 Loading {args.from_file}", file=sys.stderr)
        tweets_json = Path(args.from_file).read_text()
    else:
        bearer_token = get_bearer_token()
        if not bearer_token:
            print("❌ Set X_BEARER_TOKEN (or X_CONSUMER_KEY + X_API_KEY)", file=sys.stderr)
            sys.exit(1)
        print("📡 Pulling tweets...", file=sys.stderr)
        tweets_data = pull_tweets(bearer_token, queries)
        tweets_json = json.dumps(tweets_data, indent=2)

    # Step 2: Generate brief
    brief = generate_brief(tweets_json, system_prompt)

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
            tweets_path = briefs_dir / f"{date_str}-tweets.json"
            tweets_path.write_text(tweets_json)
            print(f"  💾 Tweets → {tweets_path}", file=sys.stderr)

    print("✅ Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
