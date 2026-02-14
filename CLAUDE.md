# CLAUDE.md

## What this project does

xscout — multi-source AI intel scout. Pulls posts from X (Twitter), HackerNews, and other sources, sends them to an LLM via NanoGPT, and generates a structured intel brief.

## How to run

```bash
# HackerNews (no API key needed)
python3 scout.py --source hackernews --topic "local AI, LLMs"

# Twitter (needs X_BEARER_TOKEN)
python3 scout.py --source twitter

# All sources
python3 scout.py --source all --topic "robotics"

# Save brief + raw posts
python3 scout.py --source hn --topic "LLMs" --save --save-tweets

# Replay from saved data (no API call)
python3 scout.py --from-file briefs/2026-02-14-posts.json
```

## Required env vars

- `NANOGPT_API_KEY` — NanoGPT API key

## Source-specific env vars

- `X_BEARER_TOKEN` — X API bearer token (for twitter source only)

OR instead of X_BEARER_TOKEN:
- `X_CONSUMER_KEY` + `X_API_KEY` — will auto-exchange for bearer token

## Optional env vars

- `SCOUT_FOCUS` — Custom topic/domain to scout (default: local AI / local LLMs)

## Project structure

- `scout.py` — Main pipeline script (source → LLM → brief)
- `config.py` — Search queries, lookback window, model settings
- `prompt.py` — System prompt for the LLM call
- `queries.py` — X/Twitter query builder from topic strings
- `sources/` — Source adapter package
  - `base.py` — Post dataclass + SourceAdapter ABC
  - `twitter.py` — X/Twitter adapter
  - `hackernews.py` — HackerNews adapter (Algolia API, no auth)
- `briefs/` — Saved briefs and raw post JSON (gitignored except .gitkeep)

## Editing guide

- **Add a new source** → create `sources/newsource.py` implementing `SourceAdapter`, register in `scout.py` SOURCE_MAP
- **Add/remove search queries** → edit `config.py` QUERIES list
- **Change model or token budget** → edit `config.py` LLM_MODEL / MAX_TOKENS
- **Change topic/focus** → `--topic` CLI arg or `SCOUT_FOCUS` env var
- **Change brief format or tone** → edit `prompt.py` `build_system_prompt()`
- **Change lookback window** → edit `config.py` LOOKBACK_HOURS (max 168)

## No external dependencies

Stdlib only. No pip install needed.
