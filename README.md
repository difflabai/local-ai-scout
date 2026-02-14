# xscout

Multi-source AI intel scout. Pulls posts from X (Twitter), HackerNews, and more → sends to LLM via NanoGPT → outputs a structured, opinionated brief. Zero dependencies beyond Python stdlib.

## Quick Start

```bash
# Set your keys
export NANOGPT_API_KEY="..."
export X_BEARER_TOKEN="AAAA..."  # only needed for twitter source

# Run it
python3 scout.py --source hackernews --topic "local AI, LLMs"
```

## Sources

| Source | Flag | Auth Required |
|--------|------|---------------|
| X / Twitter | `--source twitter` (default) | `X_BEARER_TOKEN` |
| HackerNews | `--source hackernews` or `--source hn` | None (free Algolia API) |
| All sources | `--source all` | Varies per source |

## Options

```bash
python3 scout.py                                        # Twitter (default source)
python3 scout.py --source hackernews --topic "robotics" # HackerNews
python3 scout.py --source hn --topic "LLMs"             # HackerNews (short alias)
python3 scout.py --source all --topic "edge AI"         # All sources combined
python3 scout.py --save                                 # Save to briefs/YYYY-MM-DD.md
python3 scout.py --save --save-tweets                   # Also save raw post JSON
python3 scout.py --from-file posts.json                 # Replay without hitting APIs
python3 scout.py --topic "robotics"                     # Scout a different topic
```

## Custom Topic / Domain

By default the scout tracks local AI developments. You can point it at any topic:

```bash
# Via CLI argument
python3 scout.py --topic "open source robotics"

# Via environment variable
export SCOUT_FOCUS="distributed databases"
python3 scout.py
```

CLI `--topic` takes priority over the `SCOUT_FOCUS` env var. When a custom topic is set, the scout automatically builds relevant search queries and adapts the system prompt.

## HackerNews Source

The HackerNews adapter uses the free [Algolia HN Search API](https://hn.algolia.com/api) — no API key required.

It searches three endpoints per query:
- **Stories by relevance** — `search` endpoint filtered to stories
- **Stories by date** — `search_by_date` to catch very recent posts
- **Comments with signal** — top 50 comments matching the query

Posts are deduplicated by ID and normalized to a common format including title, body, score (points), author, comment count, and permalink.

## Automate with Cron

```bash
# Daily at 8am
0 8 * * * cd /path/to/xscout && python3 scout.py --save >> scout.log 2>&1
```

Or use the included GitHub Actions workflow (`.github/workflows/daily-scout.yml`) — set `NANOGPT_API_KEY` and `X_BEARER_TOKEN` as repository secrets.

## Customize

| What | Where |
|------|-------|
| Topic / domain focus | `--topic` CLI arg or `SCOUT_FOCUS` env var |
| Source | `--source` CLI arg (`twitter`, `hackernews`/`hn`, `all`) |
| Search queries | `config.py` → `DEFAULT_QUERIES` |
| Lookback window | `config.py` → `LOOKBACK_HOURS` |
| LLM model | `config.py` → `LLM_MODEL` |
| Brief format & tone | `prompt.py` → `build_system_prompt()` |

## Architecture

```
scout.py              — Main pipeline: source → LLM → brief
config.py             — Search queries, lookback window, model settings
prompt.py             — System prompt for the LLM call
queries.py            — X/Twitter query builder from topic strings
sources/
  base.py             — Post dataclass + SourceAdapter ABC
  twitter.py          — X/Twitter adapter (API v2)
  hackernews.py       — HackerNews adapter (Algolia API)
briefs/               — Saved briefs and raw post JSON (gitignored)
```

## Cost

~$0.001/run with MiniMax M2.5 via NanoGPT.

## License

MIT
