from .base import Post, SourceAdapter
from .x import XAdapter
from .reddit import RedditAdapter
from .civitai import CivitAIAdapter
from .producthunt import ProductHuntAdapter

ADAPTERS = {
    "x": XAdapter,
    "reddit": RedditAdapter,
    "civitai": CivitAIAdapter,
    "producthunt": ProductHuntAdapter,
}

__all__ = ["Post", "SourceAdapter", "XAdapter", "RedditAdapter", "CivitAIAdapter", "ProductHuntAdapter", "ADAPTERS"]
