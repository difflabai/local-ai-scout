"""HackerNews source adapter for xscout.

Uses the free Algolia HN Search API (no auth required):
  https://hn.algolia.com/api/v1/search
  https://hn.algolia.com/api/v1/search_by_date
"""

import sys
import json
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote

from .base import Post, SourceAdapter

BASE_URL = "https://hn.algolia.com/api/v1"


class HackerNewsSource(SourceAdapter):
    name = "hackernews"

    def fetch(self, queries: list[str], lookback_hours: int) -> list[Post]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        cutoff_ts = int(cutoff.timestamp())

        seen_ids: set[str] = set()
        posts: list[Post] = []

        for i, query in enumerate(queries, 1):
            print(f"  [{i}/{len(queries)}] HN: {query[:60]}...", file=sys.stderr)

            # Search by relevance (stories)
            story_hits = self._search(query, cutoff_ts, tags="story", endpoint="search")
            # Search by date (stories) — catches very recent posts
            recent_hits = self._search(query, cutoff_ts, tags="story", endpoint="search_by_date")
            # Search comments for signal
            comment_hits = self._search(query, cutoff_ts, tags="comment",
                                        endpoint="search", hits_per_page=50)

            for hit in story_hits + recent_hits:
                post = self._hit_to_post(hit)
                if post and post.id not in seen_ids:
                    seen_ids.add(post.id)
                    posts.append(post)

            for hit in comment_hits:
                post = self._comment_to_post(hit)
                if post and post.id not in seen_ids:
                    seen_ids.add(post.id)
                    posts.append(post)

        print(f"  ✅ {len(posts)} HN posts across {len(queries)} queries", file=sys.stderr)
        return posts

    @staticmethod
    def _search(query: str, cutoff_ts: int, tags: str = "story",
                endpoint: str = "search", hits_per_page: int = 20) -> list[dict]:
        params = urlencode({
            "query": query,
            "tags": tags,
            "numericFilters": f"created_at_i>{cutoff_ts}",
            "hitsPerPage": hits_per_page,
        })
        url = f"{BASE_URL}/{endpoint}?{params}"
        req = Request(url)
        req.add_header("User-Agent", "xscout/1.0")

        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                return data.get("hits", [])
        except Exception as e:
            print(f"    ⚠ HN API error: {e}", file=sys.stderr)
            return []

    @staticmethod
    def _hit_to_post(hit: dict) -> Post | None:
        object_id = hit.get("objectID", "")
        if not object_id:
            return None

        title = hit.get("title") or ""
        body = hit.get("story_text") or hit.get("url") or ""
        author = hit.get("author", "")
        points = hit.get("points") or 0
        num_comments = hit.get("num_comments") or 0
        created_at_i = hit.get("created_at_i")

        created_at = ""
        if created_at_i:
            created_at = datetime.fromtimestamp(created_at_i, tz=timezone.utc).isoformat()

        return Post(
            source="hackernews",
            id=object_id,
            title=title,
            body=body,
            url=f"https://news.ycombinator.com/item?id={object_id}",
            author=author,
            score=points,
            created_at=created_at,
            metadata={
                "num_comments": num_comments,
                "story_url": hit.get("url", ""),
            },
        )

    @staticmethod
    def _comment_to_post(hit: dict) -> Post | None:
        object_id = hit.get("objectID", "")
        if not object_id:
            return None

        comment_text = hit.get("comment_text") or ""
        author = hit.get("author", "")
        story_id = hit.get("story_id")
        story_title = hit.get("story_title") or ""
        created_at_i = hit.get("created_at_i")

        created_at = ""
        if created_at_i:
            created_at = datetime.fromtimestamp(created_at_i, tz=timezone.utc).isoformat()

        return Post(
            source="hackernews",
            id=f"comment-{object_id}",
            title=f"[Comment on: {story_title}]" if story_title else "[Comment]",
            body=comment_text,
            url=f"https://news.ycombinator.com/item?id={object_id}",
            author=author,
            score=hit.get("points") or 0,
            created_at=created_at,
            metadata={
                "type": "comment",
                "story_id": str(story_id) if story_id else "",
                "story_title": story_title,
            },
        )
