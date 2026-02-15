"""Lobsters source adapter — uses Lobsters' public JSON API (no auth required)."""

import json
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from .base import Post, SourceAdapter

USER_AGENT = "xscout/1.0 (local-ai-scout; stdlib)"

# Lobsters is a small site — be polite
_MIN_REQUEST_INTERVAL = 2.0  # seconds between requests
_last_request_time = 0.0


def _rate_limit():
    """Sleep if needed to respect rate limits."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _lobsters_get(url: str) -> list | None:
    """Fetch a Lobsters JSON endpoint. Returns list of stories or None on error."""
    _rate_limit()
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠ Lobsters request failed: {e}", file=sys.stderr)
        return None


def _parse_timestamp(ts: str) -> datetime:
    """Parse Lobsters timestamp like '2026-02-14T13:32:17.000-06:00' to UTC datetime."""
    # Strip milliseconds for compatibility with fromisoformat on older Python
    ts = re.sub(r'\.\d+', '', ts)
    dt = datetime.fromisoformat(ts)
    return dt.astimezone(timezone.utc)


class LobstersAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "lobsters"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        search_terms = self._build_search_terms(topic, queries)
        tags = self._extract_tags(search_terms)
        cutoff = datetime.now(timezone.utc).timestamp() - (lookback_hours * 3600)

        posts: list[Post] = []
        seen: set[str] = set()

        # Strategy 1: Fetch by tag (most reliable on Lobsters)
        for tag in tags:
            print(f"  [lobsters] tag: {tag}", file=sys.stderr)
            new_posts = self._fetch_by_tag(tag, cutoff, max_results)
            for p in new_posts:
                if p.url not in seen:
                    seen.add(p.url)
                    posts.append(p)

        # Strategy 2: Scan newest pages and filter by keywords
        keywords = self._extract_keywords(search_terms)
        if keywords:
            print(f"  [lobsters] keyword scan: {keywords}", file=sys.stderr)
            new_posts = self._fetch_newest_filtered(keywords, cutoff, max_results, max_pages=4)
            for p in new_posts:
                if p.url not in seen:
                    seen.add(p.url)
                    posts.append(p)

        print(f"  -> {len(posts)} posts from Lobsters", file=sys.stderr)
        return posts

    def _build_search_terms(self, topic: str, queries: list[str] | None) -> list[str]:
        if queries:
            return queries
        terms = [t.strip() for t in topic.split(",") if t.strip()]
        return terms or [topic]

    def _extract_tags(self, terms: list[str]) -> list[str]:
        """Map search terms to plausible Lobsters tags.

        Lobsters uses short lowercase tags like 'rust', 'python', 'ai', 'ml',
        'security', 'linux', etc. We extract single lowercase words that are
        likely to be valid tags.
        """
        tags = set()
        for term in terms:
            for word in re.findall(r'[a-zA-Z0-9]+', term.lower()):
                # Skip very short/common words that aren't useful tags
                if len(word) >= 2 and word not in {"the", "and", "for", "with", "about", "from", "that", "this"}:
                    tags.add(word)
        return sorted(tags)

    def _extract_keywords(self, terms: list[str]) -> list[str]:
        """Extract keywords for title/description matching."""
        keywords = []
        for term in terms:
            for word in term.lower().split():
                word = re.sub(r'[^a-z0-9]', '', word)
                if len(word) >= 3:
                    keywords.append(word)
        return keywords

    def _fetch_by_tag(self, tag: str, cutoff: float, max_results: int) -> list[Post]:
        """Fetch stories by Lobsters tag."""
        posts = []
        for page in range(1, 4):  # up to 3 pages (75 stories)
            if page == 1:
                url = f"https://lobste.rs/t/{tag}.json"
            else:
                url = f"https://lobste.rs/t/{tag}/page/{page}.json"

            stories = _lobsters_get(url)
            if not stories:
                break

            page_posts, hit_cutoff = self._normalize(stories, cutoff)
            posts.extend(page_posts)

            if hit_cutoff or len(posts) >= max_results:
                break

        return posts[:max_results]

    def _fetch_newest_filtered(self, keywords: list[str], cutoff: float,
                               max_results: int, max_pages: int = 4) -> list[Post]:
        """Fetch newest stories and filter by keyword match in title/description."""
        posts = []
        for page in range(1, max_pages + 1):
            if page == 1:
                url = "https://lobste.rs/newest.json"
            else:
                url = f"https://lobste.rs/newest/page/{page}.json"

            stories = _lobsters_get(url)
            if not stories:
                break

            for story in stories:
                ts = _parse_timestamp(story.get("created_at", ""))
                if ts.timestamp() < cutoff:
                    return posts[:max_results]

                searchable = (story.get("title", "") + " " + story.get("description_plain", "")).lower()
                if any(kw in searchable for kw in keywords):
                    posts.append(self._story_to_post(story))

            if len(posts) >= max_results:
                break

        return posts[:max_results]

    def _normalize(self, stories: list, cutoff: float) -> tuple[list[Post], bool]:
        """Convert Lobsters stories to Post objects. Returns (posts, hit_cutoff)."""
        posts = []
        for story in stories:
            ts = _parse_timestamp(story.get("created_at", ""))
            if ts.timestamp() < cutoff:
                return posts, True
            posts.append(self._story_to_post(story))
        return posts, False

    def _story_to_post(self, story: dict) -> Post:
        """Convert a single Lobsters story dict to a Post."""
        title = story.get("title", "")
        desc = story.get("description_plain", "")
        text = f"{title}\n\n{desc}".strip() if desc else title

        ts = _parse_timestamp(story.get("created_at", ""))

        return Post(
            source="lobsters",
            author=story.get("submitter_user", ""),
            text=text,
            url=story.get("comments_url", "") or story.get("short_id_url", ""),
            timestamp=ts.isoformat(),
            score=story.get("comment_count", 0),  # comment count as engagement metric
            metadata={
                "tags": story.get("tags", []),
                "story_url": story.get("url", ""),
                "short_id": story.get("short_id", ""),
                "upvotes": story.get("score", 0),
                "comment_count": story.get("comment_count", 0),
                "user_is_author": story.get("user_is_author", False),
            },
        )
