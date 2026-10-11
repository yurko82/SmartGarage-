"""YouTube Music Service for SmartGarage.
Integrates user's personal playlists and Liked Music via local session.
"""

import json
import logging
import os
import random
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

RUSSIAN_CHARS = set("ёъыэЁЪЫЭ")

def is_russian_content(text: str) -> bool:
    """Check if title contains Russian-specific characters or taboo keywords."""
    if not text:
        return False
    lower = text.lower()
    if any(ch in RUSSIAN_CHARS for ch in text):
        return True
    return any(w in lower for w in ("російськ", "русск", "по-русски", "російською"))


class YTMusicService:
    """Manages YouTube Music playlists, Liked Songs, and track selection."""

    def __init__(self, devices_dir: Optional[Path] = None):
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self.devices_dir = devices_dir or (self.root_dir / "devices")
        self.cache_file = self.devices_dir / "ytmusic_playlists.json"
        self.tracks_cache_dir = self.devices_dir / "ytmusic_cache"
        self.tracks_cache_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._playlists_cache: List[Dict[str, Any]] = []
        self._last_playlists_fetch: float = 0.0

        self.current_playlist_id: Optional[str] = None
        self.current_playlist_title: Optional[str] = None
        self.current_track_index: int = -1
        self.current_shuffle_mode: bool = False
        self._last_played_tracks: List[str] = []

        self._load_cached_playlists()

    def _load_cached_playlists(self):
        """Load cached playlists from disk if available."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._playlists_cache = data.get("playlists", [])
                    self._last_playlists_fetch = data.get("timestamp", 0.0)
            except Exception as e:
                logger.warning(f"Failed to read playlists cache: {e}")

    def _save_cached_playlists(self):
        """Save cached playlists to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": self._last_playlists_fetch,
                    "playlists": self._playlists_cache
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save playlists cache: {e}")

    def get_user_playlists(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch all user playlists including Liked Music."""
        now = time.time()
        # Cache for 1 hour unless forced
        if not force_refresh and self._playlists_cache and (now - self._last_playlists_fetch < 3600):
            return self._playlists_cache

        ytdlp_bin = "/home/yurko/AI/OpenInterpreter/venv/bin/yt-dlp"
        if not Path(ytdlp_bin).exists():
            ytdlp_bin = "yt-dlp"

        # 1. Start with standard Liked Music playlist
        playlists: List[Dict[str, Any]] = [
            {
                "id": "LM",
                "title": "Улюблені пісні (Liked Music)",
                "url": "https://music.youtube.com/playlist?list=LM",
                "is_liked": True,
                "track_count": 0
            }
        ]

        # 2. Extract feed playlists from YouTube account via Firefox cookies
        cmd = [
            ytdlp_bin,
            "--cookies-from-browser", "firefox",
            "--flat-playlist",
            "-J",
            "https://www.youtube.com/feed/playlists"
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                entries = data.get("entries", [])
                for entry in entries:
                    p_id = entry.get("id")
                    title = entry.get("title", "")
                    if not p_id or not title:
                        continue
                    if p_id in ("WL", "LL"):
                        # Watch later or generic liked videos, skip or map
                        continue
                    if is_russian_content(title):
                        continue
                    playlists.append({
                        "id": p_id,
                        "title": title,
                        "url": entry.get("url") or f"https://www.youtube.com/playlist?list={p_id}",
                        "is_liked": False,
                        "track_count": entry.get("playlist_count", 0)
                    })
        except Exception as e:
            logger.error(f"Error fetching user playlists: {e}")

        with self._lock:
            self._playlists_cache = playlists
            self._last_playlists_fetch = now
            self._save_cached_playlists()

        return self._playlists_cache

    def get_playlist_tracks(self, playlist_id_or_url: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Get all safe tracks from a specific playlist with disk caching."""
        p_id = playlist_id_or_url
        if "list=" in p_id:
            p_id = p_id.split("list=")[-1].split("&")[0]

        cache_track_file = self.tracks_cache_dir / f"tracks_{p_id}.json"
        if not force_refresh and cache_track_file.exists():
            try:
                # 2 hour cache for tracks
                if time.time() - cache_track_file.stat().st_mtime < 7200:
                    with open(cache_track_file, "r", encoding="utf-8") as f:
                        cached_tracks = json.load(f)
                        if cached_tracks:
                            return cached_tracks
            except Exception:
                pass

        target_url = f"https://www.youtube.com/playlist?list={p_id}"
        ytdlp_bin = "/home/yurko/AI/OpenInterpreter/venv/bin/yt-dlp"
        if not Path(ytdlp_bin).exists():
            ytdlp_bin = "yt-dlp"

        cmd = [
            ytdlp_bin,
            "--cookies-from-browser", "firefox",
            "--flat-playlist",
            "-J",
            target_url
        ]

        tracks: List[Dict[str, Any]] = []
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                entries = data.get("entries", [])
                for entry in entries:
                    title = entry.get("title")
                    track_id = entry.get("id")
                    if not title or not track_id or title == "[Private video]" or title == "[Deleted video]":
                        continue
                    if is_russian_content(title):
                        continue
                    uploader = entry.get("uploader") or entry.get("channel") or ""
                    if is_russian_content(uploader):
                        continue

                    tracks.append({
                        "id": track_id,
                        "title": title,
                        "uploader": uploader,
                        "url": f"https://www.youtube.com/watch?v={track_id}",
                        "duration": entry.get("duration", 0)
                    })

                # Update track count in cache if playlist matches
                for p in self._playlists_cache:
                    if p["id"] == p_id:
                        p["track_count"] = len(tracks)
                        self._save_cached_playlists()
                        break

                if tracks:
                    with open(cache_track_file, "w", encoding="utf-8") as f:
                        json.dump(tracks, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error fetching tracks for playlist {p_id}: {e}")

        return tracks

    def find_playlist(self, query: str) -> Optional[Dict[str, Any]]:
        """Find a playlist matching user's voice or text query."""
        q = (query or "").lower().strip()
        if not q:
            return None

        # Check for Liked / Favorites keywords
        liked_keywords = (
            "улюблені", "улюблене", "улюблених", "улюблені пісні", "улюблені треки",
            "мої улюблені", "мої пісні", "лайки", "лайкнуті", "сподобалось", "мені сподобалось",
            "liked", "liked music", "favorites", "favourite"
        )
        if q in ("lm", "ll") or any(k in q for k in liked_keywords):
            for p in self.get_user_playlists():
                if p.get("is_liked") or p.get("id") == "LM":
                    return p
            return {
                "id": "LM",
                "title": "Улюблені пісні (Liked Music)",
                "url": "https://music.youtube.com/playlist?list=LM",
                "is_liked": True,
                "track_count": 0
            }

        playlists = self.get_user_playlists()

        # Direct ID match
        for p in playlists:
            if p["id"].lower() == q or p["id"] == query:
                return p

        # Exact or substring match
        for p in playlists:
            title_lower = p["title"].lower()
            if q in title_lower or title_lower in q:
                return p

        # Word match
        q_words = [w for w in q.split() if len(w) > 2]
        for p in playlists:
            title_lower = p["title"].lower()
            if any(w in title_lower for w in q_words):
                return p

        return None

    def get_track_to_play(
        self,
        playlist_id_or_name: str,
        shuffle: bool = False,
        track_id: Optional[str] = None,
        track_title: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a track to play from specified playlist (sequential by default or shuffle)."""
        pl = self.find_playlist(playlist_id_or_name)
        if pl:
            p_id = pl["id"]
            p_title = pl["title"]
        else:
            p_id = playlist_id_or_name
            p_title = playlist_id_or_name

        tracks = self.get_playlist_tracks(p_id)
        if not tracks:
            return None

        # Reset or update playlist tracking if new playlist
        if self.current_playlist_id != p_id:
            self.current_playlist_id = p_id
            self.current_playlist_title = p_title
            self.current_track_index = -1
            self._last_played_tracks.clear()

        self.current_shuffle_mode = shuffle

        # 1. User requested a specific track from playlist
        if track_id or track_title:
            found_idx = -1
            for idx, t in enumerate(tracks):
                if track_id and t.get("id") == track_id:
                    found_idx = idx
                    break
                if track_title and t.get("title") and t.get("title").lower() == track_title.lower():
                    found_idx = idx
                    break
            if found_idx != -1:
                self.current_track_index = found_idx
                chosen = tracks[found_idx]
                if chosen["id"] not in self._last_played_tracks:
                    self._last_played_tracks.append(chosen["id"])
                chosen_copy = dict(chosen)
                chosen_copy["playlist_id"] = p_id
                chosen_copy["playlist_title"] = p_title
                chosen_copy["total_tracks"] = len(tracks)
                chosen_copy["track_index"] = found_idx
                return chosen_copy

        # 2. Shuffle mode
        if shuffle:
            available = [t for t in tracks if t["id"] not in self._last_played_tracks]
            if not available:
                self._last_played_tracks.clear()
                available = tracks
            chosen = random.choice(available)
            try:
                self.current_track_index = tracks.index(chosen)
            except ValueError:
                self.current_track_index = 0
            self._last_played_tracks.append(chosen["id"])
            if len(self._last_played_tracks) > 50:
                self._last_played_tracks.pop(0)
            chosen_copy = dict(chosen)
            chosen_copy["playlist_id"] = p_id
            chosen_copy["playlist_title"] = p_title
            chosen_copy["total_tracks"] = len(tracks)
            chosen_copy["track_index"] = self.current_track_index
            return chosen_copy

        # 3. Sequential mode ("одна за одною по черзі")
        if self.current_track_index < 0:
            self.current_track_index = 0
        else:
            self.current_track_index = self.current_track_index % len(tracks)

        chosen = tracks[self.current_track_index]
        if chosen["id"] not in self._last_played_tracks:
            self._last_played_tracks.append(chosen["id"])
        chosen_copy = dict(chosen)
        chosen_copy["playlist_id"] = p_id
        chosen_copy["playlist_title"] = p_title
        chosen_copy["total_tracks"] = len(tracks)
        chosen_copy["track_index"] = self.current_track_index
        return chosen_copy

    def get_next_track_to_play(
        self,
        playlist_id_or_name: Optional[str] = None,
        shuffle: Optional[bool] = None
    ) -> Optional[Dict[str, Any]]:
        """Get the next track in order or shuffle for auto-advancing."""
        p_id = playlist_id_or_name or self.current_playlist_id or "LM"
        pl = self.find_playlist(p_id)
        if pl:
            p_id = pl["id"]
            p_title = pl["title"]
        else:
            p_title = p_id

        tracks = self.get_playlist_tracks(p_id)
        if not tracks:
            return None

        self.current_playlist_id = p_id
        self.current_playlist_title = p_title

        is_shuffle = shuffle if shuffle is not None else self.current_shuffle_mode

        if is_shuffle:
            return self.get_track_to_play(p_id, shuffle=True)

        # Advance to next sequential index ("одна за одною по черзі")
        if self.current_track_index < 0:
            self.current_track_index = 0
        else:
            self.current_track_index = (self.current_track_index + 1) % len(tracks)

        chosen = tracks[self.current_track_index]
        if chosen["id"] not in self._last_played_tracks:
            self._last_played_tracks.append(chosen["id"])
        chosen_copy = dict(chosen)
        chosen_copy["playlist_id"] = p_id
        chosen_copy["playlist_title"] = p_title
        chosen_copy["total_tracks"] = len(tracks)
        chosen_copy["track_index"] = self.current_track_index
        return chosen_copy


ytmusic_service = YTMusicService()
