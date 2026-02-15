"""HuggingFace source adapter — searches models, papers, and daily papers via public API."""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote_plus
from urllib.request import Request, urlopen

from .base import Post, SourceAdapter

USER_AGENT = "xscout/1.0 (ai-intel-scout; stdlib)"

# HuggingFace public API is generous — light rate limiting
_MIN_REQUEST_INTERVAL = 1.0
_last_request_time = 0.0


def _rate_limit():
    """Sleep if needed to respect rate limits."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _hf_get(url: str) -> list | dict:
    """Fetch a HuggingFace API endpoint with rate limiting."""
    _rate_limit()
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠ HuggingFace request failed: {e}", file=sys.stderr)
        return []


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if not text:
        return ""
    text = " ".join(text.split())  # normalize whitespace
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


class HuggingFaceAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "huggingface"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        search_terms = self._build_search_terms(topic, queries)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        posts: list[Post] = []
        seen_urls: set[str] = set()

        def _add(post: Post):
            if post.url not in seen_urls:
                seen_urls.add(post.url)
                posts.append(post)

        # Search models (trending)
        for i, term in enumerate(search_terms, 1):
            print(f"  [huggingface {i}/{len(search_terms)}] models: {term[:50]}...", file=sys.stderr)
            for post in self._search_models(term, max_results, cutoff):
                _add(post)

        # Search papers
        for i, term in enumerate(search_terms, 1):
            print(f"  [huggingface {i}/{len(search_terms)}] papers: {term[:50]}...", file=sys.stderr)
            for post in self._search_papers(term, cutoff):
                _add(post)

        # Daily papers (trending/recent, not query-specific)
        print(f"  [huggingface] daily papers...", file=sys.stderr)
        for post in self._fetch_daily_papers(max_results, cutoff):
            _add(post)

        print(f"  -> {len(posts)} posts from HuggingFace", file=sys.stderr)
        return posts

    def _build_search_terms(self, topic: str, queries: list[str] | None) -> list[str]:
        """Build search terms from topic string."""
        if queries:
            return queries
        terms = [t.strip() for t in topic.split(",") if t.strip()]
        if not terms:
            terms = [topic]
        return terms

    # ─── Models ──────────────────────────────────────────────────────────

    def _search_models(self, query: str, limit: int, cutoff: datetime) -> list[Post]:
        """Search HuggingFace models sorted by trending score."""
        params = urlencode({
            "search": query,
            "sort": "trendingScore",
            "direction": "-1",
            "limit": min(limit, 50),
        })
        url = f"https://huggingface.co/api/models?{params}"
        data = _hf_get(url)
        if not isinstance(data, list):
            return []

        posts = []
        for item in data:
            created = item.get("createdAt", "")
            if created:
                try:
                    ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass

            model_id = item.get("id", "")
            pipeline = item.get("pipeline_tag", "")
            tags = item.get("tags", [])
            downloads = item.get("downloads", 0)
            likes = item.get("likes", 0)
            trending = item.get("trendingScore", 0)

            # Build informative text
            parts = [model_id]
            if pipeline:
                parts.append(f"[{pipeline}]")
            tag_str = ", ".join(t for t in tags[:5] if t not in ("transformers", "safetensors", "pytorch"))
            if tag_str:
                parts.append(f"({tag_str})")
            text = " ".join(parts)

            posts.append(Post(
                source="huggingface",
                author=model_id.split("/")[0] if "/" in model_id else model_id,
                text=text,
                url=f"https://huggingface.co/{model_id}",
                timestamp=created or datetime.now(timezone.utc).isoformat(),
                score=downloads + likes,
                metadata={
                    "type": "model",
                    "pipeline_tag": pipeline,
                    "downloads": downloads,
                    "likes": likes,
                    "trending_score": trending,
                },
            ))

        return posts

    # ─── Papers search ───────────────────────────────────────────────────

    def _search_papers(self, query: str, cutoff: datetime) -> list[Post]:
        """Search HuggingFace papers."""
        encoded = quote_plus(query)
        url = f"https://huggingface.co/api/papers/search?q={encoded}"
        data = _hf_get(url)
        if not isinstance(data, list):
            return []

        posts = []
        for item in data:
            paper = item.get("paper", {})
            published = paper.get("publishedAt", "") or item.get("publishedAt", "")
            if published:
                try:
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass

            paper_id = paper.get("id", "")
            title = item.get("title", "") or paper.get("title", "")
            summary = _truncate(paper.get("ai_summary", "") or paper.get("summary", ""))
            upvotes = paper.get("upvotes", 0)
            authors = paper.get("authors", [])
            author_name = authors[0].get("name", "unknown") if authors else "unknown"

            text = title
            if summary:
                text = f"{title}\n\n{summary}"

            posts.append(Post(
                source="huggingface",
                author=author_name,
                text=text,
                url=f"https://huggingface.co/papers/{paper_id}",
                timestamp=published or datetime.now(timezone.utc).isoformat(),
                score=upvotes,
                metadata={
                    "type": "paper",
                    "paper_id": paper_id,
                    "upvotes": upvotes,
                    "num_comments": item.get("numComments", 0),
                },
            ))

        return posts

    # ─── Daily papers ────────────────────────────────────────────────────

    def _fetch_daily_papers(self, limit: int, cutoff: datetime) -> list[Post]:
        """Fetch trending daily papers."""
        url = f"https://huggingface.co/api/daily_papers?limit={min(limit, 50)}"
        data = _hf_get(url)
        if not isinstance(data, list):
            return []

        posts = []
        for item in data:
            paper = item.get("paper", {})
            published = paper.get("publishedAt", "") or item.get("publishedAt", "")
            if published:
                try:
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass

            paper_id = paper.get("id", "")
            title = item.get("title", "") or paper.get("title", "")
            summary = _truncate(paper.get("ai_summary", "") or paper.get("summary", ""))
            upvotes = paper.get("upvotes", 0)
            authors = paper.get("authors", [])
            author_name = authors[0].get("name", "unknown") if authors else "unknown"

            text = title
            if summary:
                text = f"{title}\n\n{summary}"

            posts.append(Post(
                source="huggingface",
                author=author_name,
                text=text,
                url=f"https://huggingface.co/papers/{paper_id}",
                timestamp=published or datetime.now(timezone.utc).isoformat(),
                score=upvotes,
                metadata={
                    "type": "daily_paper",
                    "paper_id": paper_id,
                    "upvotes": upvotes,
                    "num_comments": item.get("numComments", 0),
                },
            ))

        return posts
