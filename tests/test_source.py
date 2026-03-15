from __future__ import annotations

import unittest

from app.models import SourcePlatform
from app.services.source import SourceResolver, extract_first_url


class SourceResolverTest(unittest.IsolatedAsyncioTestCase):
    async def test_youtube_canonical(self) -> None:
        resolver = SourceResolver()
        source = await resolver.resolve("https://youtu.be/abc123?t=10")
        self.assertEqual(source.platform, SourcePlatform.youtube)
        self.assertEqual(source.canonical_url, "https://www.youtube.com/watch?v=abc123")

    async def test_bilibili_canonical(self) -> None:
        resolver = SourceResolver()
        source = await resolver.resolve("https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=333")
        self.assertEqual(source.platform, SourcePlatform.bilibili)
        self.assertEqual(source.canonical_url, "https://www.bilibili.com/video/BV1xx411c7mD")

    async def test_rss_hint(self) -> None:
        resolver = SourceResolver()
        source = await resolver.resolve("https://example.com/feed", source_hint="rss")
        self.assertEqual(source.platform, SourcePlatform.rss)
        self.assertEqual(source.feed_url, "https://example.com/feed")


class UrlExtractTest(unittest.TestCase):
    def test_extract_first_url(self) -> None:
        text = "check this https://example.com/a?b=1 and this https://x.com"
        self.assertEqual(extract_first_url(text), "https://example.com/a?b=1")


if __name__ == "__main__":
    unittest.main()
