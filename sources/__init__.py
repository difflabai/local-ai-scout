from .base import Post, SourceAdapter
from .x import XAdapter
from .reddit import RedditAdapter
from .civitai import CivitAIAdapter
from .arxiv import ArxivAdapter
from .lobsters import LobstersAdapter
from .hackernews import HackerNewsAdapter
from .github import GitHubAdapter
from .producthunt import ProductHuntAdapter
from .huggingface import HuggingFaceAdapter
from .bluesky import BlueskyAdapter

ADAPTERS = {
    "x": XAdapter,
    "reddit": RedditAdapter,
    "civitai": CivitAIAdapter,
    "arxiv": ArxivAdapter,
    "lobsters": LobstersAdapter,
    "hackernews": HackerNewsAdapter,
    "github": GitHubAdapter,
    "producthunt": ProductHuntAdapter,
    "huggingface": HuggingFaceAdapter,
    "bluesky": BlueskyAdapter,
}

__all__ = [
    "Post", "SourceAdapter", "ADAPTERS",
    "XAdapter", "RedditAdapter", "CivitAIAdapter",
    "ArxivAdapter", "LobstersAdapter", "HackerNewsAdapter",
    "GitHubAdapter", "ProductHuntAdapter", "HuggingFaceAdapter",
    "BlueskyAdapter",
]
