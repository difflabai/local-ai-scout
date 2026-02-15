"""Bluesky source adapter — uses the public AT Protocol API (no auth required)."""

import json
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from .base import Post, SourceAdapter

API_BASE = "https://public.api.bsky.app/xrpc"
USER_AGENT = "xscout/1.0 (local-ai-scout; stdlib)"


def _bsky_get(url: str) -> dict:
    """Fetch a Bluesky API endpoint."""
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠ Bluesky request failed: {e}", file=sys.stderr)
        return {}


def _post_url(uri: str, did: str) -> str:
    """Build a bsky.app web URL from an AT URI.

    AT URI format: at://did:plc:xxx/app.bsky.feed.post/RKEY
    Web URL format: https://bsky.app/profile/DID/post/RKEY
    """
    parts = uri.rsplit("/", 1)
    rkey = parts[-1] if len(parts) == 2 else ""
    return f"https://bsky.app/profile/{did}/post/{rkey}"


class BlueskyAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "bluesky"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        search_terms = self._build_search_terms(topic, queries)
        since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

        posts: list[Post] = []
        seen_uris: set[str] = set()

        for i, term in enumerate(search_terms, 1):
            print(f"  [bluesky {i}/{len(search_terms)}] {term[:50]}...", file=sys.stderr)
            results = self._search(term, since, min(max_results, 100))
            for post in results:
                if post.url not in seen_uris:
                    seen_uris.add(post.url)
                    posts.append(post)

        print(f"  -> {len(posts)} posts from Bluesky", file=sys.stderr)
        return posts

    def _build_search_terms(self, topic: str, queries: list[str] | None) -> list[str]:
        """Build search terms from topic string.

        Split comma-separated topics into separate searches.
        """
        if queries:
            return queries
        terms = [t.strip() for t in topic.split(",") if t.strip()]
        if not terms:
            terms = [topic]
        return terms

    def _search(self, query: str, since: str, limit: int) -> list[Post]:
        """Search Bluesky for posts matching the query."""
        encoded = quote_plus(query)
        url = f"{API_BASE}/app.bsky.feed.searchPosts?q={encoded}&sort=latest&limit={limit}&since={since}"
        data = _bsky_get(url)
        return self._normalize(data)

    def _normalize(self, data: dict) -> list[Post]:
        """Convert Bluesky API response into normalized Post objects."""
        posts = []

        for item in data.get("posts", []):
            author_info = item.get("author", {})
            did = author_info.get("did", "")
            handle = author_info.get("handle", "unknown")

            record = item.get("record", {})
            text = record.get("text", "")
            created_at = record.get("createdAt", "")

            uri = item.get("uri", "")
            url = _post_url(uri, did)

            like_count = item.get("likeCount", 0)
            repost_count = item.get("repostCount", 0)

            posts.append(Post(
                source="bluesky",
                author=f"@{handle}",
                text=text,
                url=url,
                timestamp=created_at,
                score=like_count,
                metadata={
                    "did": did,
                    "repost_count": repost_count,
                    "reply_count": item.get("replyCount", 0),
                    "quote_count": item.get("quoteCount", 0),
                },
            ))

        return posts
