"""GitHub source adapter — searches trending repos and recent issues via public API (no auth required)."""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote_plus
from urllib.request import Request, urlopen

from .base import Post, SourceAdapter

USER_AGENT = "xscout/1.0 (ai-intel-scout; stdlib)"

# GitHub unauthenticated: 10 req/min for search API
_MIN_REQUEST_INTERVAL = 7.0
_last_request_time = 0.0


def _rate_limit():
    """Sleep if needed to respect GitHub's search API rate limit."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _github_get(url: str) -> dict:
    """Fetch a GitHub API endpoint with rate limiting and optional auth."""
    _rate_limit()
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/vnd.github.v3+json")

    # Use GITHUB_TOKEN for higher rate limits (30 req/min authenticated)
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"token {token}")

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠ GitHub request failed: {e}", file=sys.stderr)
        return {}


def _cutoff_date(lookback_hours: int) -> str:
    """ISO 8601 date string for the lookback window."""
    dt = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class GitHubAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "github"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        search_terms = self._build_search_terms(topic, queries)
        cutoff = _cutoff_date(lookback_hours)

        posts: list[Post] = []
        seen_urls: set[str] = set()

        # Search repositories (trending / recently updated)
        for i, term in enumerate(search_terms, 1):
            print(f"  [github {i}/{len(search_terms)}] repos: {term[:50]}...", file=sys.stderr)
            results = self._search_repos(term, cutoff, max_results)
            for post in results:
                if post.url not in seen_urls:
                    seen_urls.add(post.url)
                    posts.append(post)

        # Search issues/discussions for each term
        for i, term in enumerate(search_terms, 1):
            print(f"  [github {i}/{len(search_terms)}] issues: {term[:50]}...", file=sys.stderr)
            results = self._search_issues(term, cutoff, max_results)
            for post in results:
                if post.url not in seen_urls:
                    seen_urls.add(post.url)
                    posts.append(post)

        print(f"  -> {len(posts)} posts from GitHub", file=sys.stderr)
        return posts

    def _build_search_terms(self, topic: str, queries: list[str] | None) -> list[str]:
        """Build GitHub search terms from topic string."""
        if queries:
            return queries
        terms = [t.strip() for t in topic.split(",") if t.strip()]
        if not terms:
            terms = [topic]
        return terms

    def _search_repos(self, query: str, cutoff: str, limit: int) -> list[Post]:
        """Search GitHub repositories sorted by stars, recently updated."""
        per_page = min(limit, 30)
        q = f"{query} pushed:>{cutoff[:10]}"
        params = urlencode({
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
        })
        url = f"https://api.github.com/search/repositories?{params}"
        data = _github_get(url)
        return self._normalize_repos(data)

    def _search_issues(self, query: str, cutoff: str, limit: int) -> list[Post]:
        """Search GitHub issues sorted by creation date."""
        per_page = min(limit, 30)
        q = f"{query} is:issue created:>{cutoff[:10]}"
        params = urlencode({
            "q": q,
            "sort": "created",
            "order": "desc",
            "per_page": per_page,
        })
        url = f"https://api.github.com/search/issues?{params}"
        data = _github_get(url)
        return self._normalize_issues(data)

    def _normalize_repos(self, data: dict) -> list[Post]:
        """Convert GitHub repository search response into normalized Post objects."""
        posts = []
        for item in data.get("items", []):
            name = item.get("full_name", "")
            description = item.get("description", "") or ""
            owner = item.get("owner", {}).get("login", "unknown")
            html_url = item.get("html_url", "")
            stars = item.get("stargazers_count", 0)
            forks = item.get("forks_count", 0)
            language = item.get("language", "") or ""

            # Use pushed_at (last activity) as timestamp
            pushed_at = item.get("pushed_at", "")
            created_at = item.get("created_at", "")
            timestamp = pushed_at or created_at or datetime.now(timezone.utc).isoformat()

            # Build descriptive text
            parts = [name]
            if language:
                parts.append(f"[{language}]")
            if description:
                parts.append(f"— {description}")

            topics = item.get("topics", [])
            if topics:
                parts.append(f"(topics: {', '.join(topics[:5])})")

            text = " ".join(parts)

            posts.append(Post(
                source="github",
                author=owner,
                text=text,
                url=html_url,
                timestamp=timestamp,
                score=stars,
                metadata={
                    "type": "repository",
                    "full_name": name,
                    "stars": stars,
                    "forks": forks,
                    "language": language,
                    "created_at": created_at,
                    "pushed_at": pushed_at,
                    "topics": topics,
                    "open_issues": item.get("open_issues_count", 0),
                },
            ))

        return posts

    def _normalize_issues(self, data: dict) -> list[Post]:
        """Convert GitHub issue search response into normalized Post objects."""
        posts = []
        for item in data.get("items", []):
            title = item.get("title", "")
            body = item.get("body", "") or ""
            user = item.get("user", {}).get("login", "unknown")
            html_url = item.get("html_url", "")
            created_at = item.get("created_at", "")

            # Truncate body to keep posts concise
            if len(body) > 500:
                body = body[:500].rsplit(" ", 1)[0] + "..."

            text = f"{title}\n\n{body}".strip() if body else title

            # Extract repo name from repository_url
            repo_url = item.get("repository_url", "")
            repo_name = "/".join(repo_url.split("/")[-2:]) if repo_url else ""

            labels = [l.get("name", "") for l in item.get("labels", [])]
            reactions = item.get("reactions", {})
            reaction_count = reactions.get("total_count", 0) if reactions else 0

            posts.append(Post(
                source="github",
                author=user,
                text=text,
                url=html_url,
                timestamp=created_at or datetime.now(timezone.utc).isoformat(),
                score=reaction_count + item.get("comments", 0),
                metadata={
                    "type": "issue",
                    "repo": repo_name,
                    "state": item.get("state", "open"),
                    "labels": labels,
                    "comments": item.get("comments", 0),
                    "reactions": reaction_count,
                },
            ))

        return posts
