# CLAUDE.md

## What this project does

xscout — multi-source AI intel pipeline. Pulls posts from X (Twitter), Reddit, CivitAI, and other platforms, sends them to an LLM via NanoGPT, and generates a structured intel brief.

## How to run

```bash
# Source env vars first
set -a && source .env && set +a

# Default (X source)
python3 scout.py

# Reddit source
python3 scout.py --source reddit --topic "SDXL, stable diffusion"

# CivitAI source
python3 scout.py --source civitai --topic "SDXL lora"

# All sources combined
python3 scout.py --source all --topic "local LLMs"

# Save brief + raw posts
python3 scout.py --source reddit --topic "SDXL" --save --save-posts

# Replay from saved posts (no API calls)
python3 scout.py --from-file briefs/2026-02-14-posts.json
```

## Required env vars

- `NANOGPT_API_KEY` — NanoGPT API key

## Source-specific env vars

- `X_BEARER_TOKEN` — X API bearer token (only needed for `--source x` or `--source all`)
- OR `X_CONSUMER_KEY` + `X_API_KEY` — will auto-exchange for bearer token

## Optional env vars

- `SCOUT_FOCUS` — Custom topic/domain to scout (default: local AI / local LLMs)

## Project structure

- `scout.py` — Main pipeline script (fetch → brief → output)
- `sources/` — Source adapter package
  - `base.py` — `SourceAdapter` ABC + `Post` dataclass
  - `x.py` — X/Twitter adapter (API v2 recent search)
  - `reddit.py` — Reddit adapter (public JSON API, no auth)
  - `civitai.py` — CivitAI adapter (public REST API, no auth)
- `config.py` — Search queries, lookback window, model settings
- `prompt.py` — System prompt for the LLM call
- `queries.py` — X API query builder from freeform topics
- `briefs/` — Saved briefs and raw post JSON (gitignored except .gitkeep)

## Editing guide

- **Add a new source** → Create `sources/newsource.py` implementing `SourceAdapter`, register in `sources/__init__.py`, add to `--source` choices in `scout.py`
- **Add/remove X search queries** → edit `config.py` DEFAULT_QUERIES list
- **Change model or token budget** → edit `config.py` LLM_MODEL / MAX_TOKENS
- **Change topic/focus** → `--topic` CLI arg or `SCOUT_FOCUS` env var
- **Change brief format or tone** → edit `prompt.py` `build_system_prompt()`
- **Change lookback window** → edit `config.py` LOOKBACK_HOURS (max 168)
- **Change Reddit subreddits** → edit `sources/reddit.py` DEFAULT_SUBREDDITS

## No external dependencies

Stdlib only. No pip install needed.
