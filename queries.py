"""
Query builder for Local AI Scout.

Builds effective X API search queries from freeform topic strings.
Uses quoted phrases, OR chaining, community handles, and negative filters.
"""

import re

# ─── NOISE FILTERS ───────────────────────────────────────────────────────────
# Common spam/noise terms to exclude from all queries
NEGATIVE_FILTERS = [
    "-is:retweet",
    "-giveaway",
    "-airdrop",
    "-whitelist",
    "-presale",
    "-NFT",
    '-"join our"',
    '-"dm me"',
    '-"sign up"',
    "-is:nullcast",
]

NEGATIVE_FILTER_STR = " ".join(NEGATIVE_FILTERS)

# ─── KNOWN COMMUNITIES ──────────────────────────────────────────────────────
# Map of topic keywords → known community handles/accounts.
# Lowercase keys for matching.
COMMUNITY_HANDLES = {
    "sdxl": ["@StabilityAI", "@ClybAI", "@KohakuBlueleaf", "@ai_pictures"],
    "stable diffusion": ["@StabilityAI", "@ABORATORY1", "@comikidzz"],
    "pony": ["@PurpleSmartAI"],
    "ponydiffusion": ["@PurpleSmartAI"],
    "ponyxl": ["@PurpleSmartAI"],
    "illustrious": ["@aikiiin_", "@OrangeMixs"],
    "chroma": ["@LodestoneArt", "@lodestone_art"],
    "flux": ["@baboratory", "@bfl_ml"],
    "comfyui": ["@comaboratory", "@comfyanonymous"],
    "image generation": ["@StabilityAI", "@bfl_ml", "@midaboratory"],
    "local ai": ["@ggaboratory", "@ollama", "@LMStudioAI"],
    "llama": ["@ggaboratory", "@MetaAI"],
    "ollama": ["@ollama"],
    "mlx": ["@ml_explore"],
}

# ─── FILLER WORDS ────────────────────────────────────────────────────────────
FILLER = {
    "and", "the", "for", "with", "including", "models", "model",
    "such", "like", "also", "about", "from", "that", "this",
    "into", "using", "based", "their", "other", "these",
    "image", "generation",  # too generic on their own
}


def _extract_phrases_and_keywords(topic: str) -> tuple[list[str], list[str]]:
    """Parse a topic string into multi-word phrases and single keywords.

    Splits on commas first to get phrase-level chunks, then identifies
    which chunks are multi-word (quoted as phrases) vs single keywords.

    Returns (phrases, keywords) — phrases are multi-word, keywords are single-word.
    """
    phrases = []
    keywords = []

    # Split on commas to get natural phrase boundaries
    chunks = [c.strip() for c in topic.split(",") if c.strip()]

    for chunk in chunks:
        # Clean up each chunk
        words = chunk.split()
        # Remove pure filler words from edges
        cleaned = [w for w in words if w.lower() not in FILLER or len(words) <= 2]
        if not cleaned:
            cleaned = words  # fallback: keep original if all were "filler"

        text = " ".join(cleaned)

        if len(cleaned) >= 2:
            phrases.append(text)
        elif len(cleaned) == 1 and len(cleaned[0]) > 2:
            keywords.append(cleaned[0])

    # If no comma-separated chunks, fall back to word-level extraction
    if not phrases and not keywords:
        words = [w.strip().rstrip(",") for w in topic.split() if len(w.strip().rstrip(",")) > 2]
        for w in words:
            if w.lower() not in FILLER:
                keywords.append(w)

    return phrases, keywords


def _find_community_handles(phrases: list[str], keywords: list[str]) -> list[str]:
    """Find relevant community handles based on topic terms."""
    handles = set()
    all_terms = [p.lower() for p in phrases] + [k.lower() for k in keywords]

    for term in all_terms:
        for key, accounts in COMMUNITY_HANDLES.items():
            if key in term or term in key:
                handles.update(accounts)

    return sorted(handles)


def build_topic_queries(topic: str) -> list[str]:
    """Build effective X search queries from a freeform topic string.

    Strategy:
    1. Broad OR query — all phrases and keywords OR'd together
    2. Signal-filtered query — top terms + signal words (release, benchmark, etc.)
    3. Community query — from/mention known accounts for the topic
    4. Fallback — quoted full topic if nothing else worked
    """
    phrases, keywords = _extract_phrases_and_keywords(topic)
    handles = _find_community_handles(phrases, keywords)

    queries = []

    # Build quoted terms for OR chaining
    # Multi-word phrases get quotes, single keywords are quoted too for exactness
    all_terms = []
    for p in phrases:
        all_terms.append(f'"{p}"')
    for k in keywords:
        all_terms.append(f'"{k}"')

    # Query 1: Broad sweep — all terms OR'd
    if all_terms:
        or_chain = " OR ".join(all_terms[:10])
        queries.append(f"({or_chain}) {NEGATIVE_FILTER_STR}")

    # Query 2: Top terms + signal words (narrower, higher quality)
    top_terms = all_terms[:5]
    if top_terms:
        or_top = " OR ".join(top_terms)
        signal_words = '"release" OR "new" OR "benchmark" OR "comparison" OR "update" OR "workflow" OR "tutorial" OR "guide"'
        queries.append(f"({or_top}) ({signal_words}) {NEGATIVE_FILTER_STR}")

    # Query 3: Community accounts — from/mentioning known handles
    if handles:
        handle_or = " OR ".join(f"from:{h.lstrip('@')}" for h in handles[:6])
        # Pair with at least one topic term so we don't get all their tweets
        if all_terms:
            anchor = " OR ".join(all_terms[:3])
            queries.append(f"({handle_or}) ({anchor}) {NEGATIVE_FILTER_STR}")

    # Fallback: quote the whole topic
    if not queries:
        queries.append(f'"{topic}" {NEGATIVE_FILTER_STR}')

    return queries
