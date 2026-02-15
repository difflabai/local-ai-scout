# xscout — Multi-Source AI Intel Pipeline

Automated intel brief on AI developments from X (Twitter), Reddit, CivitAI, HackerNews, and more.

Pulls posts from multiple platforms → sends to LLM via NanoGPT → outputs a structured, opinionated brief. Zero dependencies beyond Python stdlib.

## Quick Start

```bash
# Set your keys
export NANOGPT_API_KEY="..."
export X_BEARER_TOKEN="AAAA..."  # only needed for X source

# Run it
python3 scout.py --source reddit --topic "stable diffusion"
```

## Sources

| Source | Flag | Auth Required | Notes |
|--------|------|---------------|-------|
| X (Twitter) | `--source x` (default) | `X_BEARER_TOKEN` | Uses X API v2 recent search |
| Reddit | `--source reddit` | None | Public JSON API, ~10 req/min |
| CivitAI | `--source civitai` | None | Public REST API for model releases |
| Arxiv | `--source arxiv` | None | Academic papers |
| Lobsters | `--source lobsters` | None | Tech community |
| HackerNews | `--source hackernews` | None | Free Algolia API, no auth |
| All | `--source all` | X token if available | Fetches from all sources, merges results |

## Options

```bash
python3 scout.py                                        # Default: X source, local AI topic
python3 scout.py --source reddit --topic "SDXL"         # Reddit only
python3 scout.py --source civitai --topic "SDXL lora"   # CivitAI models
python3 scout.py --source hackernews --topic "LLMs"     # HackerNews
python3 scout.py --source all --topic "local LLMs"      # All sources combined
python3 scout.py --save                                 # Save brief to briefs/YYYY-MM-DD.md
python3 scout.py --save --save-posts                    # Also save raw posts JSON
python3 scout.py --from-file posts.json                 # Replay from saved data
python3 scout.py --topic "robotics"                     # Scout a different topic
python3 scout.py --queries "custom X query" "another"   # Raw X API queries
```

## Custom Topic / Domain

By default the scout tracks local AI developments. You can point it at any topic:

```bash
# Via CLI argument
python3 scout.py --source reddit --topic "open source robotics"

# Via environment variable
export SCOUT_FOCUS="distributed databases"
python3 scout.py --source all
```

CLI `--topic` takes priority over the `SCOUT_FOCUS` env var. When a custom topic is set, the scout automatically builds relevant search queries and adapts the system prompt.

## Architecture

```
scout.py              Main pipeline (fetch → brief → output)
sources/
  base.py             SourceAdapter ABC + Post dataclass
  x.py                X/Twitter adapter (API v2)
  reddit.py           Reddit adapter (public JSON API)
  civitai.py          CivitAI adapter (public REST API)
  arxiv.py            Arxiv adapter
  lobsters.py         Lobsters adapter
  hackernews.py       HackerNews adapter (Algolia API)
config.py             Search queries, lookback window, model settings
prompt.py             System prompt for the LLM call
queries.py            X API query builder from freeform topics
briefs/               Saved briefs and raw post JSON (gitignored)
```

Adding a new source: create `sources/newsource.py` implementing `SourceAdapter`, register it in `sources/__init__.py`, and add it to the `--source` choices in `scout.py`.

## Customize

| What | Where |
|------|-------|
| Topic / domain focus | `--topic` CLI arg or `SCOUT_FOCUS` env var |
| Source platform | `--source` CLI arg (x, reddit, civitai, arxiv, lobsters, hackernews, all) |
| Search queries (X) | `config.py` → `DEFAULT_QUERIES` |
| Lookback window | `config.py` → `LOOKBACK_HOURS` |
| LLM model | `config.py` → `LLM_MODEL` |
| Brief format & tone | `prompt.py` → `build_system_prompt()` |
| Reddit subreddits | `sources/reddit.py` → `DEFAULT_SUBREDDITS` |

## Cost

~$0.001/run with MiniMax M2.5 via NanoGPT.

## License

MIT
