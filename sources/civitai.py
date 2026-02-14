"""CivitAI source adapter — uses the CivitAI public REST API (no auth required)."""

import json
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote_plus
from urllib.request import Request, urlopen

from .base import Post, SourceAdapter

USER_AGENT = "xscout/1.0 (local-ai-scout; stdlib)"

# CivitAI is generous but let's be polite
_MIN_REQUEST_INTERVAL = 1.0
_last_request_time = 0.0

# Map topic keywords to CivitAI model types
TYPE_KEYWORDS = {
    "lora": "LORA",
    "checkpoint": "Checkpoint",
    "textual inversion": "TextualInversion",
    "embedding": "TextualInversion",
    "hypernetwork": "Hypernetwork",
    "controlnet": "Controlnet",
    "upscaler": "Upscaler",
}

# Map topic keywords to CivitAI base model filters
BASE_MODEL_KEYWORDS = {
    "sdxl": "SDXL 1.0",
    "sd 1.5": "SD 1.5",
    "sd1.5": "SD 1.5",
    "sd15": "SD 1.5",
    "pony": "Pony",
    "ponyxl": "Pony",
    "ponydiffusion": "Pony",
    "illustrious": "Illustrious",
    "flux": "Flux.1 D",
    "chroma": "Chroma",
}

PERIOD_MAP = {
    24: "Day",
    168: "Week",
    720: "Month",
}


def _rate_limit():
    """Sleep if needed to respect rate limits."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _civitai_get(url: str) -> dict:
    """Fetch a CivitAI API endpoint with rate limiting."""
    _rate_limit()
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠ CivitAI request failed: {e}", file=sys.stderr)
        return {}


def _period_filter(lookback_hours: int) -> str:
    """Map lookback hours to CivitAI's period parameter."""
    for threshold, label in sorted(PERIOD_MAP.items()):
        if lookback_hours <= threshold:
            return label
    return "Month"


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if not text:
        return ""
    # Strip HTML tags (CivitAI descriptions can contain HTML)
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


class CivitAIAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "civitai"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        search_terms = self._build_search_terms(topic, queries)
        period = _period_filter(lookback_hours)
        type_filter = self._detect_type_filter(topic)
        base_model_hints = self._detect_base_models(topic)

        posts: list[Post] = []
        seen_ids: set[int] = set()

        for i, term in enumerate(search_terms, 1):
            print(f"  [civitai {i}/{len(search_terms)}] models: {term[:50]}...", file=sys.stderr)
            results = self._search_models(term, period, max_results, type_filter)
            for post in results:
                model_id = post.metadata.get("model_id", 0)
                if model_id not in seen_ids:
                    seen_ids.add(model_id)
                    posts.append(post)

        # If we have base model hints, do additional filtered searches
        for base_model in base_model_hints:
            print(f"  [civitai] base model filter: {base_model}...", file=sys.stderr)
            results = self._search_models(
                search_terms[0] if search_terms else topic,
                period, max_results, type_filter, base_model,
            )
            for post in results:
                model_id = post.metadata.get("model_id", 0)
                if model_id not in seen_ids:
                    seen_ids.add(model_id)
                    posts.append(post)

        print(f"  -> {len(posts)} posts from CivitAI", file=sys.stderr)
        return posts

    def _build_search_terms(self, topic: str, queries: list[str] | None) -> list[str]:
        """Build CivitAI search terms from topic string."""
        if queries:
            return queries
        terms = [t.strip() for t in topic.split(",") if t.strip()]
        if not terms:
            terms = [topic]
        return terms

    def _detect_type_filter(self, topic: str) -> str | None:
        """Check if topic mentions a specific model type."""
        topic_lower = topic.lower()
        for keyword, type_val in TYPE_KEYWORDS.items():
            if keyword in topic_lower:
                return type_val
        return None

    def _detect_base_models(self, topic: str) -> list[str]:
        """Check if topic mentions specific base models."""
        topic_lower = topic.lower()
        found = []
        for keyword, base_model in BASE_MODEL_KEYWORDS.items():
            if keyword in topic_lower and base_model not in found:
                found.append(base_model)
        return found

    def _search_models(self, query: str, period: str, limit: int,
                       type_filter: str | None = None,
                       base_model: str | None = None) -> list[Post]:
        """Search CivitAI models API."""
        params = {
            "query": query,
            "sort": "Newest",
            "limit": min(limit, 20),
            "period": period,
            "nsfw": "false",
        }
        if type_filter:
            params["types"] = type_filter
        if base_model:
            params["baseModels"] = base_model

        url = f"https://civitai.com/api/v1/models?{urlencode(params)}"
        data = _civitai_get(url)
        return self._normalize(data)

    def _normalize(self, data: dict) -> list[Post]:
        """Convert CivitAI API response into normalized Post objects."""
        posts = []
        items = data.get("items", [])

        for item in items:
            model_id = item.get("id", 0)
            model_name = item.get("name", "")
            creator = item.get("creator", {})
            username = creator.get("username", "unknown")
            description = _truncate(item.get("description", "") or "")
            model_type = item.get("type", "")
            stats = item.get("stats", {})

            # Get base model from the latest model version
            versions = item.get("modelVersions", [])
            base_model = ""
            if versions:
                base_model = versions[0].get("baseModel", "")

            # Build informative text
            parts = [model_name]
            if model_type:
                parts.append(f"[{model_type}]")
            if base_model:
                parts.append(f"({base_model})")
            if description:
                parts.append(f"— {description}")
            text = " ".join(parts)

            downloads = stats.get("downloadCount", 0)
            thumbs_up = stats.get("thumbsUpCount", 0)
            rating = stats.get("rating", 0)

            created_at = item.get("createdAt", "")
            # Normalize timestamp to ISO 8601 if present
            timestamp = created_at if created_at else datetime.now(timezone.utc).isoformat()

            posts.append(Post(
                source="civitai",
                author=username,
                text=text,
                url=f"https://civitai.com/models/{model_id}",
                timestamp=timestamp,
                score=downloads + thumbs_up,
                metadata={
                    "model_id": model_id,
                    "type": model_type,
                    "base_model": base_model,
                    "downloads": downloads,
                    "thumbs_up": thumbs_up,
                    "rating": round(rating, 2),
                },
            ))

        return posts
