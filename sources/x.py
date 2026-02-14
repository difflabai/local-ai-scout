"""X (Twitter) source adapter — uses the X API v2 recent search endpoint."""

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import Post, SourceAdapter

TWEET_FIELDS = "author_id,created_at,public_metrics,entities,referenced_tweets"
USER_FIELDS = "username,name,verified,public_metrics"
EXPANSIONS = "author_id"


def _get_bearer_token() -> str:
    """Get bearer token from env. If only consumer/api keys are set, exchange them."""
    token = os.environ.get("X_BEARER_TOKEN", "")
    if token:
        return token

    consumer_key = os.environ.get("X_CONSUMER_KEY", "")
    api_key = os.environ.get("X_API_KEY", "")
    if not consumer_key or not api_key:
        return ""

    import base64
    creds = base64.b64encode(f"{consumer_key}:{api_key}".encode()).decode()
    req = Request("https://api.twitter.com/oauth2/token")
    req.add_header("Authorization", f"Basic {creds}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")
    data = urlencode({"grant_type": "client_credentials"}).encode()

    with urlopen(req, data) as resp:
        result = json.loads(resp.read().decode())
        return result.get("access_token", "")


class XAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "x"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        bearer_token = _get_bearer_token()
        if not bearer_token:
            raise RuntimeError("X API credentials not set. Set X_BEARER_TOKEN or X_CONSUMER_KEY + X_API_KEY.")

        if not queries:
            from queries import build_topic_queries
            queries = build_topic_queries(topic)

        start_time = (
            datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        posts: list[Post] = []
        per_query = min(max_results, 100)

        import sys
        for i, query in enumerate(queries, 1):
            print(f"  [x {i}/{len(queries)}] {query[:60]}...", file=sys.stderr)
            result = self._search(query, start_time, bearer_token, per_query)
            posts.extend(self._normalize(result))

        print(f"  -> {len(posts)} posts from X", file=sys.stderr)
        return posts

    def _search(self, query: str, start_time: str, bearer_token: str, max_results: int) -> dict:
        params = urlencode({
            "query": query,
            "max_results": max_results,
            "start_time": start_time,
            "tweet.fields": TWEET_FIELDS,
            "user.fields": USER_FIELDS,
            "expansions": EXPANSIONS,
        })
        url = f"https://api.twitter.com/2/tweets/search/recent?{params}"
        req = Request(url)
        req.add_header("Authorization", f"Bearer {bearer_token}")

        try:
            with urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e), "query": query}

    def _normalize(self, result: dict) -> list[Post]:
        """Convert X API response into normalized Post objects."""
        users = result.get("includes", {}).get("users", [])
        author_map = {u["id"]: u["username"] for u in users}

        posts = []
        for tweet in result.get("data", []):
            tweet_id = tweet.get("id", "")
            author_id = tweet.get("author_id", "")
            username = author_map.get(author_id, "unknown")
            metrics = tweet.get("public_metrics", {})

            posts.append(Post(
                source="x",
                author=f"@{username}",
                text=tweet.get("text", ""),
                url=f"https://x.com/{username}/status/{tweet_id}",
                timestamp=tweet.get("created_at", ""),
                score=metrics.get("like_count", 0) + metrics.get("retweet_count", 0),
                metadata={
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "replies": metrics.get("reply_count", 0),
                },
            ))
        return posts
