"""Reddit source adapter — uses Reddit's public JSON API (no auth required)."""

import json
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from .base import Post, SourceAdapter

# Subreddits to search for AI/ML topics
DEFAULT_SUBREDDITS = [
    "StableDiffusion",
    "LocalLLaMA",
    "comfyui",
    "sdforall",
]

# Reddit asks bots to identify themselves
USER_AGENT = "xscout/1.0 (local-ai-scout; stdlib)"

# Reddit public API: ~10 requests/min without auth
_MIN_REQUEST_INTERVAL = 6.5  # seconds between requests
_last_request_time = 0.0

TIME_FILTER_MAP = {
    24: "day",
    168: "week",
    720: "month",
}


def _rate_limit():
    """Sleep if needed to respect Reddit's rate limit."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _reddit_get(url: str) -> dict:
    """Fetch a Reddit JSON endpoint with rate limiting and error handling."""
    _rate_limit()
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠ Reddit request failed: {e}", file=sys.stderr)
        return {}


def _time_filter(lookback_hours: int) -> str:
    """Map lookback hours to Reddit's time filter parameter."""
    for threshold, label in sorted(TIME_FILTER_MAP.items()):
        if lookback_hours <= threshold:
            return label
    return "month"


class RedditAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "reddit"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        search_terms = self._build_search_terms(topic, queries)
        time_filter = _time_filter(lookback_hours)

        posts: list[Post] = []
        seen_ids: set[str] = set()

        # Search across all of Reddit
        for i, term in enumerate(search_terms, 1):
            print(f"  [reddit {i}/{len(search_terms)}] r/all: {term[:50]}...", file=sys.stderr)
            results = self._search_all(term, time_filter, max_results)
            for post in results:
                if post.url not in seen_ids:
                    seen_ids.add(post.url)
                    posts.append(post)

        # Also search specific subreddits
        for sub in DEFAULT_SUBREDDITS:
            print(f"  [reddit] r/{sub}: {search_terms[0][:40]}...", file=sys.stderr)
            results = self._search_subreddit(sub, search_terms[0], time_filter, max_results)
            for post in results:
                if post.url not in seen_ids:
                    seen_ids.add(post.url)
                    posts.append(post)

        print(f"  -> {len(posts)} posts from Reddit", file=sys.stderr)
        return posts

    def _build_search_terms(self, topic: str, queries: list[str] | None) -> list[str]:
        """Build Reddit search terms from topic string.

        Unlike X queries, Reddit search is simpler — just use the topic
        keywords directly. Split comma-separated topics into separate searches.
        """
        if queries:
            return queries

        # Split on commas, strip whitespace
        terms = [t.strip() for t in topic.split(",") if t.strip()]
        if not terms:
            terms = [topic]
        return terms

    def _search_all(self, query: str, time_filter: str, limit: int) -> list[Post]:
        """Search across all of Reddit."""
        encoded = quote_plus(query)
        limit = min(limit, 100)
        url = f"https://www.reddit.com/search.json?q={encoded}&sort=new&t={time_filter}&limit={limit}"
        data = _reddit_get(url)
        return self._normalize(data)

    def _search_subreddit(self, subreddit: str, query: str, time_filter: str, limit: int) -> list[Post]:
        """Search within a specific subreddit."""
        encoded = quote_plus(query)
        limit = min(limit, 100)
        url = f"https://www.reddit.com/r/{subreddit}/search.json?q={encoded}&sort=new&t={time_filter}&limit={limit}&restrict_sr=on"
        data = _reddit_get(url)
        return self._normalize(data)

    def _normalize(self, data: dict) -> list[Post]:
        """Convert Reddit API response into normalized Post objects."""
        posts = []
        children = data.get("data", {}).get("children", [])

        for child in children:
            item = child.get("data", {})
            if not item:
                continue

            # Combine title + selftext for the post content
            title = item.get("title", "")
            selftext = item.get("selftext", "")
            text = f"{title}\n\n{selftext}".strip() if selftext else title

            created_utc = item.get("created_utc", 0)
            timestamp = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()

            permalink = item.get("permalink", "")
            url = f"https://www.reddit.com{permalink}" if permalink else ""

            posts.append(Post(
                source="reddit",
                author=f"u/{item.get('author', '[deleted]')}",
                text=text,
                url=url,
                timestamp=timestamp,
                score=item.get("score", 0),
                metadata={
                    "subreddit": item.get("subreddit", ""),
                    "num_comments": item.get("num_comments", 0),
                    "upvote_ratio": item.get("upvote_ratio", 0),
                    "is_self": item.get("is_self", True),
                    "link_url": item.get("url", ""),
                },
            ))

        return posts
