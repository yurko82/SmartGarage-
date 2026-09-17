import time
import requests
from typing import List, Dict, Any, Optional
import urllib.parse

# Fallback stations if external API is unreachable
DEFAULT_UKRAINIAN_STATIONS = [
    {
        "name": "Hit FM",
        "url": "https://online.hitfm.ua/HitFM",
        "favicon": "https://www.hitfm.ua/static/images/logo.png",
        "tags": "pop,hits,top40",
        "bitrate": 128
    },
    {
        "name": "Radio ROKS",
        "url": "https://online.radioroks.ua/RadioROKS",
        "favicon": "https://www.radioroks.ua/static/images/logo.png",
        "tags": "rock,classic rock",
        "bitrate": 128
    },
    {
        "name": "Kiss FM",
        "url": "https://online.kissfm.ua/KissFM",
        "favicon": "https://www.kissfm.ua/static/images/logo.png",
        "tags": "dance,electronic,club",
        "bitrate": 128
    },
    {
        "name": "Lounge FM",
        "url": "https://online.loungefm.ua/LoungeFM",
        "favicon": "https://loungefm.com.ua/favicon.ico",
        "tags": "lounge,chillout,downtempo",
        "bitrate": 128
    },
    {
        "name": "Радіо Байрактар",
        "url": "https://online.radiobayraktar.com.ua/RadioBayraktar",
        "favicon": "https://www.radiobayraktar.com.ua/static/images/logo.png",
        "tags": "ukrainian,patriot,pop",
        "bitrate": 128
    },
    {
        "name": "Люкс FM",
        "url": "http://lux.radio.tvstitch.com/kyiv/lux_audio_128k",
        "favicon": "https://lux.fm/static/images/lux_logo.png",
        "tags": "pop,dance,ukrainian",
        "bitrate": 128
    },
    {
        "name": "Радіо Relax",
        "url": "https://online.radiorelax.ua/RadioRelax",
        "favicon": "https://www.radiorelax.ua/static/images/logo.png",
        "tags": "relax,light,acoustic",
        "bitrate": 128
    },
    {
        "name": "Radio Jazz",
        "url": "https://online.radiojazz.ua/RadioJazz",
        "favicon": "https://www.radiojazz.ua/static/images/logo.png",
        "tags": "jazz,blues,smooth",
        "bitrate": 128
    },
    {
        "name": "Радіо НВ",
        "url": "http://91.218.212.84:8000/radionv.mp3",
        "favicon": "https://radio.nv.ua/favicon.ico",
        "tags": "news,talk,ukraine",
        "bitrate": 128
    },
    {
        "name": "Наше Радіо",
        "url": "https://online.nasheradio.ua/NasheRadio",
        "favicon": "https://nasheradio.ua/static/images/logo.png",
        "tags": "ukrainian,hits,pop",
        "bitrate": 128
    }
]

API_MIRRORS = [
    "https://de1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info"
]


CYRILLIC_ALIASES = {
    "рокс": "ROKS",
    "хіт": "Hit FM",
    "хіт фм": "Hit FM",
    "кісс": "Kiss FM",
    "кіс фм": "Kiss FM",
    "люкс": "Люкс FM",
    "люкс фм": "Люкс FM",
    "релакс": "Relax",
    "джаз": "Jazz",
    "байрактар": "Байрактар",
    "наше": "Наше Радіо",
    "нв": "Радио НВ",
    "промінь": "Промінь",
    "культура": "Культура",
}


class RadioService:
    """Service for interacting with Radio Browser open API (https://www.radio-browser.info/)."""

    def __init__(self):
        self._cache_top_stations: List[Dict[str, Any]] = []
        self._cache_timestamp: float = 0.0
        self._cache_ttl: float = 1800.0  # 30 minutes

    def _fetch_from_mirrors(self, endpoint_path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Try fetching data across redundant Radio Browser mirrors with timeout."""
        headers = {"User-Agent": "SmartGarage-Radio/1.0"}
        for base_url in API_MIRRORS:
            try:
                url = f"{base_url}{endpoint_path}"
                resp = requests.get(url, params=params, headers=headers, timeout=4.0)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return None

    def get_top_stations(self, limit: int = 24, country_code: str = "UA") -> List[Dict[str, Any]]:
        """Get popular radio stations for a specific country (default Ukraine)."""
        now = time.time()
        if self._cache_top_stations and (now - self._cache_timestamp < self._cache_ttl):
            return self._cache_top_stations[:limit]

        data = self._fetch_from_mirrors(
            f"/json/stations/bycountrycodeexact/{country_code}",
            params={"order": "clickcount", "reverse": "true", "limit": limit}
        )

        stations: List[Dict[str, Any]] = []
        if data and isinstance(data, list):
            for s in data:
                if (s.get("countrycode") or "").upper() == "RU":
                    continue
                stream_url = s.get("url_resolved") or s.get("url")
                if not stream_url:
                    continue
                stations.append({
                    "id": s.get("stationuuid"),
                    "name": s.get("name", "").strip(),
                    "url": stream_url,
                    "favicon": s.get("favicon", "").strip(),
                    "tags": s.get("tags", "").strip(),
                    "bitrate": s.get("bitrate", 0),
                    "codec": s.get("codec", "MP3"),
                    "country": s.get("countrycode", "")
                })

        if not stations:
            stations = DEFAULT_UKRAINIAN_STATIONS

        self._cache_top_stations = stations
        self._cache_timestamp = now
        return stations[:limit]

    def search_stations(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search stations by name or genre/tag, prioritizing Ukrainian stations."""
        raw_q = query.strip()
        if not raw_q:
            return self.get_top_stations(limit=limit)

        q_clean = raw_q.lower().replace("радіо", "").replace("radio", "").strip() or raw_q.lower()
        search_term = CYRILLIC_ALIASES.get(q_clean, raw_q)

        # First, check direct match in default top Ukrainian stations
        exact_defaults = []
        term_lower = search_term.lower()
        for st in DEFAULT_UKRAINIAN_STATIONS:
            if term_lower in st["name"].lower() or term_lower in st["tags"].lower():
                exact_defaults.append(st)

        params = {"order": "clickcount", "reverse": "true", "limit": limit * 2}
        if raw_q.startswith("tag:"):
            endpoint = f"/json/stations/bytag/{urllib.parse.quote(raw_q[4:].strip())}"
        else:
            endpoint = "/json/stations/search"
            params["name"] = search_term

        data = self._fetch_from_mirrors(endpoint, params=params)

        ua_results: List[Dict[str, Any]] = []
        other_results: List[Dict[str, Any]] = []

        if data and isinstance(data, list):
            for s in data:
                cc = (s.get("countrycode") or "").upper()
                if cc == "RU":
                    continue
                stream_url = s.get("url_resolved") or s.get("url")
                if not stream_url:
                    continue
                st_dict = {
                    "id": s.get("stationuuid"),
                    "name": s.get("name", "").strip(),
                    "url": stream_url,
                    "favicon": s.get("favicon", "").strip(),
                    "tags": s.get("tags", "").strip(),
                    "bitrate": s.get("bitrate", 0),
                    "codec": s.get("codec", "MP3"),
                    "country": cc
                }
                if cc == "UA":
                    ua_results.append(st_dict)
                else:
                    other_results.append(st_dict)

        combined = exact_defaults + ua_results + other_results
        # Deduplicate by URL
        seen_urls = set()
        deduped = []
        for item in combined:
            u = item["url"]
            if u not in seen_urls:
                seen_urls.add(u)
                deduped.append(item)

        return deduped[:limit]


# Global singleton instance
radio_service = RadioService()
