from __future__ import annotations

import json
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import certifi

from app.models import SourceInfo, SourcePlatform


class ExtractionError(RuntimeError):
    pass


class ExtractorService:
    def __init__(self, work_dir: str, max_rss_items_scan: int = 20) -> None:
        self.work_dir = Path(work_dir)
        self.max_rss_items_scan = max_rss_items_scan
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def fetch_audio(self, source: SourceInfo, job_id: str) -> tuple[Path, dict, SourceInfo]:
        # For Apple Podcast with specific episode ID, use yt-dlp directly
        if source.platform == SourcePlatform.apple_podcast and source.episode_id:
            return self._fetch_ytdlp_audio(source, job_id, use_original_url=True)
        if source.platform in {SourcePlatform.rss, SourcePlatform.apple_podcast} or source.feed_url:
            return self._fetch_rss_audio(source, job_id)
        return self._fetch_ytdlp_audio(source, job_id)

    def _fetch_ytdlp_audio(self, source: SourceInfo, job_id: str, use_original_url: bool = False) -> tuple[Path, dict, SourceInfo]:
        job_dir = self.work_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        output_template = str(job_dir / "audio.%(ext)s")
        info_path = job_dir / "info.json"

        # Use original URL if specified (e.g., for Apple Podcast with episode ID)
        url_to_fetch = source.original_url if use_original_url else source.canonical_url

        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "-f",
            "bestaudio/best",
            "--output",
            output_template,
            "--print-json",
            url_to_fetch,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ExtractionError(result.stderr.strip() or "yt-dlp failed")

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        metadata = json.loads(lines[-1]) if lines else {}
        info_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        audio_files = list(job_dir.glob("audio.*"))
        if not audio_files:
            raise ExtractionError("No audio file was produced")

        source.title = str(metadata.get("title") or metadata.get("fulltitle") or source.title)
        source.author = str(metadata.get("uploader") or metadata.get("channel") or source.author)
        source.published_at = str(metadata.get("upload_date") or source.published_at)
        source.duration_seconds = float(metadata.get("duration") or 0.0)

        return audio_files[0], metadata, source

    def _fetch_rss_audio(self, source: SourceInfo, job_id: str) -> tuple[Path, dict, SourceInfo]:
        if not source.feed_url:
            raise ExtractionError("RSS_FEED_URL_MISSING")

        ssl_context = ssl.create_default_context(cafile=certifi.where())
        job_dir = self.work_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        req = Request(source.feed_url, headers={"User-Agent": "PodExtract/1.0"})
        with urlopen(req, timeout=20, context=ssl_context) as resp:
            feed_bytes = resp.read()

        root = ElementTree.fromstring(feed_bytes)
        channel = root.find("channel")
        if channel is None:
            raise ExtractionError("RSS_CHANNEL_NOT_FOUND")

        channel_title = (channel.findtext("title") or "").strip()
        itunes_author = ""
        for child in channel:
            if child.tag.endswith("author") and (child.text or "").strip():
                itunes_author = (child.text or "").strip()
                break

        item = self._pick_latest_item(channel)
        enclosure_url = self._extract_enclosure_url(item)
        if not enclosure_url:
            raise ExtractionError("RSS_ENCLOSURE_NOT_FOUND")

        title = (item.findtext("title") or channel_title or "Podcast Episode").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        link = (item.findtext("link") or "").strip()

        suffix = self._suffix_from_url(enclosure_url)
        audio_path = job_dir / f"audio{suffix}"

        req_audio = Request(enclosure_url, headers={"User-Agent": "PodExtract/1.0"})
        with urlopen(req_audio, timeout=60, context=ssl_context) as resp:
            audio_path.write_bytes(resp.read())

        source.title = title
        source.author = itunes_author
        source.published_at = pub_date
        source.entry_url = link

        metadata = {
            "title": title,
            "uploader": itunes_author,
            "upload_date": pub_date,
            "feed_url": source.feed_url,
            "entry_url": link,
            "enclosure_url": enclosure_url,
        }

        (job_dir / "info.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return audio_path, metadata, source

    def _pick_latest_item(self, channel: ElementTree.Element) -> ElementTree.Element:
        items = list(channel.findall("item"))
        if not items:
            raise ExtractionError("RSS_ITEM_NOT_FOUND")
        return items[: self.max_rss_items_scan][0]

    @staticmethod
    def _extract_enclosure_url(item: ElementTree.Element) -> str:
        enclosure = item.find("enclosure")
        if enclosure is not None and enclosure.attrib.get("url"):
            return str(enclosure.attrib["url"])

        for child in list(item):
            if child.tag.endswith("content") and child.attrib.get("url"):
                return str(child.attrib["url"])

        return ""

    @staticmethod
    def _suffix_from_url(url: str) -> str:
        path = urlparse(url).path
        suffix = Path(path).suffix.lower()
        if suffix in {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".webm"}:
            return suffix
        return ".mp3"
