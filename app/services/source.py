from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse, urlunparse

import httpx

from app.models import SourceInfo, SourcePlatform

_URL_RE = re.compile(r"https?://\S+")
_APPLE_ID_RE = re.compile(r"id(\d+)")


def extract_first_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    return match.group(0) if match else None


class SourceResolver:
    def __init__(self, max_rss_items_scan: int = 20) -> None:
        self.max_rss_items_scan = max_rss_items_scan

    async def resolve(self, url: str, source_hint: str | None = None) -> SourceInfo:
        clean = self._clean_url(url)
        hint = (source_hint or "").strip().lower()

        if hint == "rss" or self._looks_like_rss(clean):
            return SourceInfo(platform=SourcePlatform.rss, original_url=url, canonical_url=clean, feed_url=clean)

        parsed = urlparse(clean)
        host = parsed.netloc.lower()

        if "podcasts.apple.com" in host:
            # Extract episode ID if present
            episode_id = self._extract_episode_id(url)  # Use original URL, not cleaned
            feed_url, entry_url = await self._resolve_apple_feed(clean)
            canonical = self._clean_url(feed_url)
            return SourceInfo(
                platform=SourcePlatform.apple_podcast,
                original_url=url,
                canonical_url=canonical,
                feed_url=canonical,
                entry_url=entry_url,
                episode_id=episode_id,
            )

        if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            canonical = self._canonical_youtube(clean)
            return SourceInfo(platform=SourcePlatform.youtube, original_url=url, canonical_url=canonical)

        if "bilibili.com" in host or host == "b23.tv":
            canonical = self._canonical_bilibili(clean)
            return SourceInfo(platform=SourcePlatform.bilibili, original_url=url, canonical_url=canonical)

        if hint == "youtube":
            return SourceInfo(platform=SourcePlatform.youtube, original_url=url, canonical_url=clean)
        if hint == "bilibili":
            return SourceInfo(platform=SourcePlatform.bilibili, original_url=url, canonical_url=clean)

        return SourceInfo(platform=SourcePlatform.unknown, original_url=url, canonical_url=clean)

    @staticmethod
    def _clean_url(url: str) -> str:
        raw = str(url).strip()
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        keep_keys = {"v", "p", "i", "t", "id"}
        kept = []
        for key in sorted(query):
            if key not in keep_keys:
                continue
            for val in query[key]:
                kept.append(f"{key}={val}")
        new_query = "&".join(kept)
        normalized = parsed._replace(fragment="", query=new_query)
        return urlunparse(normalized)

    @staticmethod
    def _looks_like_rss(url: str) -> bool:
        lowered = url.lower()
        return lowered.endswith(".xml") or lowered.endswith(".rss") or "/feed" in lowered or "rss" in lowered

    @staticmethod
    def _canonical_youtube(url: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc == "youtu.be":
            video_id = parsed.path.strip("/")
            return f"https://www.youtube.com/watch?v={video_id}"

        query = parse_qs(parsed.query)
        video_id = ""
        if "v" in query and query["v"]:
            video_id = query["v"][0]

        if not video_id and parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/shorts/")[-1].strip("/")

        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

        return url

    @staticmethod
    def _canonical_bilibili(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        return f"https://www.bilibili.com{path}" if path.startswith("/") else url

    async def _resolve_apple_feed(self, apple_page_url: str) -> tuple[str, str]:
        """Returns (feed_url, entry_url) tuple."""
        # Note: Apple episode IDs (?i=) are internal and can't be looked up via iTunes API
        # We use the podcast feed URL and let RSS fetcher handle episode selection

        # Get podcast ID
        apple_id = self._extract_apple_id(apple_page_url)
        if not apple_id:
            raise ValueError("APPLE_PODCAST_ID_NOT_FOUND")

        lookup_url = "https://itunes.apple.com/lookup"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(lookup_url, params={"id": apple_id})
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results") or []
        for row in results:
            if not isinstance(row, dict):
                continue
            feed = row.get("feedUrl")
            if feed:
                return str(feed), apple_page_url

        raise ValueError("APPLE_PODCAST_FEED_NOT_FOUND")

    @staticmethod
    def _extract_apple_id(url: str) -> str:
        match = _APPLE_ID_RE.search(url)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_episode_id(url: str) -> str:
        """Extract episode ID from ?i= parameter."""
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        episode_ids = params.get("i", [])
        return episode_ids[0] if episode_ids else ""
