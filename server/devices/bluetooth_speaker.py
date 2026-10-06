import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from server.logger.logger import Logger
except ImportError:
    import logging
    Logger = logging.getLogger


class BluetoothSpeakerController:
    """Controller for Bluetooth Audio Speakers (e.g. JX-BT 1st Floor, JBL Clip 5).
    Handles pairing/connection, volume adjustments, and audio playback via PipeWire/PulseAudio.
    """

    def __init__(self, mac: str = "41:42:62:69:51:9B", name: str = "JX-BT (1-й поверх)", logger=None):
        self.mac = mac.upper().strip()
        self.name = name
        self.logger = logger or Logger()
        self.sink_name = f"bluez_output.{self.mac.replace(':', '_')}.1"
        self._lock = threading.Lock()

        self.config_path = Path(__file__).resolve().parent.parent.parent / "devices" / "bluetooth_devices.json"
        self.media_dir = Path(__file__).resolve().parent.parent.parent / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)

        self._player_proc: Optional[subprocess.Popen] = None
        self._current_track: Optional[str] = None
        self._playback_start_time: Optional[float] = None
        self._is_paused = False
        self._cached_volume = 33
        self._last_stream_url: Optional[str] = None
        self._last_stream_title: Optional[str] = None

        self._auto_detect_active_speaker()

    def _auto_detect_active_speaker(self):
        """Auto-detect which configured speaker is currently connected."""
        speakers = self.get_configured_speakers()
        for s in speakers:
            m = s["mac"]
            try:
                res = subprocess.run(["bluetoothctl", "info", m], capture_output=True, text=True, timeout=2.0)
                if "Connected: yes" in res.stdout:
                    self.set_active_speaker(m, s["name"])
                    self.set_volume(33)
                    return
            except Exception:
                pass

    def get_configured_speakers(self) -> list:
        """Load list of configured speaker devices."""
        speakers = []
        if self.config_path.exists():
            try:
                import json
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for mac, info in data.items():
                    if info.get("type") == "speaker":
                        speakers.append({
                            "mac": mac.upper().strip(),
                            "name": info.get("alias") or info.get("name") or "Колонка",
                            "floor": info.get("floor", "garage")
                        })
            except Exception:
                pass
        if not speakers:
            speakers = [
                {"mac": "41:42:62:69:51:9B", "name": "JX-BT (1-й поверх)", "floor": "floor1"},
                {"mac": "F8:5C:7E:EE:7D:CC", "name": "Юрій: JBL Clip 5", "floor": "garage"}
            ]
        return speakers

    def set_active_speaker(self, mac: str, name: Optional[str] = None):
        """Switch active speaker target."""
        self.mac = mac.upper().strip()
        if name:
            self.name = name
        else:
            for s in self.get_configured_speakers():
                if s["mac"] == self.mac:
                    self.name = s["name"]
                    break
        self.sink_name = f"bluez_output.{self.mac.replace(':', '_')}.1"

    def is_connected(self, mac: Optional[str] = None) -> bool:
        """Check if the Bluetooth speaker is currently connected via PipeWire, HCI, or BlueZ."""
        target_mac = (mac or self.mac).upper().strip()
        sink_mac_str = target_mac.replace(":", "_")

        # 1. Direct check: PipeWire has an active registered sink for this Bluetooth device
        try:
            res_pw = subprocess.run(
                ["pactl", "list", "sinks", "short"],
                capture_output=True,
                text=True,
                timeout=1.5
            )
            if res_pw.returncode == 0 and sink_mac_str in res_pw.stdout:
                return True
        except Exception:
            pass

        # 2. Check active Bluetooth ACL baseband connections (instant kernel check)
        try:
            res_hci = subprocess.run(
                ["hcitool", "con"],
                capture_output=True,
                text=True,
                timeout=1.0
            )
            if res_hci.returncode == 0 and target_mac in res_hci.stdout:
                return True
        except Exception:
            pass

        # 3. Fallback: BlueZ management status via bluetoothctl
        try:
            res = subprocess.run(
                ["bluetoothctl", "info", target_mac],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            return "Connected: yes" in res.stdout
        except Exception:
            return False

    def connect(self, mac: Optional[str] = None) -> bool:
        """Connect to the Bluetooth speaker and set as default audio sink."""
        if mac:
            self.set_active_speaker(mac)

        if self.is_connected():
            subprocess.run(
                ["pactl", "set-default-sink", self.sink_name],
                capture_output=True,
                timeout=3.0
            )
            vol = self.get_volume()
            if vol == 0:
                self.set_volume(self._cached_volume or 33)
            self.logger.info(f"{self.name} is already connected.")
            return True

        self.logger.info(f"Connecting to Bluetooth speaker {self.name} ({self.mac})...")
        try:
            res = subprocess.run(
                ["bluetoothctl", "connect", self.mac],
                capture_output=True,
                text=True,
                timeout=8.0
            )
            time.sleep(1.0)
            if not self.is_connected():
                # Attempt pairing if not yet paired
                subprocess.run(["bluetoothctl", "pair", self.mac], capture_output=True, text=True, timeout=8.0)
                time.sleep(0.5)
                subprocess.run(["bluetoothctl", "connect", self.mac], capture_output=True, text=True, timeout=8.0)
                time.sleep(1.0)

            if self.is_connected():
                # Set as default audio sink
                subprocess.run(
                    ["pactl", "set-default-sink", self.sink_name],
                    capture_output=True,
                    timeout=3.0
                )
                vol = self.get_volume()
                if vol < 33:
                    self.set_volume(33)
                self.logger.info(f"Connected to {self.name} successfully.")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error connecting to speaker: {e}")
            return False

    def disconnect(self) -> bool:
        """Disconnect the Bluetooth speaker."""
        self.stop()
        try:
            subprocess.run(
                ["bluetoothctl", "disconnect", self.mac],
                capture_output=True,
                text=True,
                timeout=5.0
            )
            return True
        except Exception as e:
            self.logger.error(f"Error disconnecting speaker: {e}")
            return False

    def get_volume(self) -> int:
        """Get current volume percentage for the speaker sink."""
        try:
            res = subprocess.run(
                ["pactl", "get-sink-volume", self.sink_name],
                capture_output=True,
                text=True,
                timeout=3.0
            )
            if res.returncode == 0:
                # e.g., "Volume: front-left: 49152 /  75% / -7.50 dB,   front-right: 49152 /  75% / -7.50 dB"
                for part in res.stdout.split("/"):
                    part_clean = part.strip()
                    if part_clean.endswith("%"):
                        val_str = part_clean.replace("%", "").strip()
                        if val_str.isdigit():
                            self._cached_volume = int(val_str)
                            return self._cached_volume
        except Exception:
            pass
        return self._cached_volume

    def set_volume(self, volume_percent: int) -> bool:
        """Set volume (0..100%)."""
        vol = max(0, min(100, int(volume_percent)))
        self._cached_volume = vol
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", self.sink_name, f"{vol}%"],
                capture_output=True,
                timeout=3.0
            )
            # Also set default sink volume
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_AUDIO_SINK@", f"{vol}%"],
                capture_output=True,
                timeout=3.0
            )
            return True
        except Exception as e:
            self.logger.error(f"Error setting volume: {e}")
            return False


    def is_playing(self) -> bool:
        """Check if audio is actively playing."""
        with self._lock:
            if self._player_proc and self._player_proc.poll() is None:
                if not self.is_connected():
                    return False
                return True
            # Also check if an external or inherited audio stream is active in PipeWire
            if self.is_connected():
                try:
                    res = subprocess.run(
                        ["pactl", "list", "sink-inputs", "short"],
                        capture_output=True,
                        text=True,
                        timeout=1.0
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        return True
                except Exception:
                    pass
            return False

    def resume_or_replay_last(self) -> bool:
        """Resume paused playback or replay the last active stream on the active speaker."""
        if not self.is_connected():
            if not self.connect():
                return False
        if self._is_paused:
            return self.resume()
        if hasattr(self, "_last_stream_url") and self._last_stream_url:
            return self.play_stream(self._last_stream_url, track_title=getattr(self, "_last_stream_title", None))
        return False

    def stop(self) -> bool:
        """Stop current audio playback reliably."""
        with self._lock:
            if self._player_proc:
                try:
                    import signal
                    os.killpg(os.getpgid(self._player_proc.pid), signal.SIGKILL)
                except Exception:
                    try:
                        self._player_proc.kill()
                    except Exception:
                        pass
                self._player_proc = None
            try:
                subprocess.run(["pkill", "-9", "-f", "gst-launch-1.0"], capture_output=True, timeout=2.0)
            except Exception:
                pass
            self._current_track = None
            self._playback_start_time = None
            self._is_paused = False
            time.sleep(0.2)
        return True

    def switch_speaker(self, target_mac: str) -> bool:
        """Seamlessly switch active output to target Bluetooth speaker, transferring stream if active."""
        target_mac = target_mac.upper().strip()
        if not target_mac:
            return False

        if target_mac == self.mac and self.is_connected():
            return True

        old_mac = self.mac
        was_playing = self.is_playing()
        last_url = getattr(self, "_last_stream_url", None)
        last_title = getattr(self, "_last_stream_title", None)

        self.logger.info(f"Switching speaker from {old_mac} to {target_mac} (was_playing={was_playing})...")

        # 1. Stop playback on old speaker
        self.stop()

        # 2. Disconnect old speaker if different
        if old_mac and old_mac != target_mac:
            try:
                subprocess.run(["bluetoothctl", "disconnect", old_mac], capture_output=True, timeout=5.0)
                time.sleep(0.5)
            except Exception as e:
                self.logger.warning(f"Error disconnecting old speaker {old_mac}: {e}")

        # 3. Set active speaker and connect
        self.set_active_speaker(target_mac)
        connected = self.connect(target_mac)

        # 4. If playback was active, resume streaming on the new speaker seamlessly
        if connected and was_playing and last_url:
            time.sleep(0.5)
            self.play_stream(last_url, track_title=last_title)

        return connected

    def pause(self) -> bool:
        """Pause playback (SIGSTOP)."""
        with self._lock:
            if self._player_proc and self._player_proc.poll() is None:
                try:
                    import signal
                    os.kill(self._player_proc.pid, signal.SIGSTOP)
                    self._is_paused = True
                    return True
                except Exception as e:
                    self.logger.error(f"Error pausing audio: {e}")
        return False

    def resume(self) -> bool:
        """Resume paused playback (SIGCONT)."""
        with self._lock:
            if self._player_proc and self._player_proc.poll() is None and self._is_paused:
                try:
                    import signal
                    os.kill(self._player_proc.pid, signal.SIGCONT)
                    self._is_paused = False
                    return True
                except Exception as e:
                    self.logger.error(f"Error resuming audio: {e}")
        return False

    def play_file(self, filepath: str, track_title: Optional[str] = None) -> bool:
        """Play a local media file strictly on the active Bluetooth speaker."""
        p = Path(filepath)
        if not p.is_absolute():
            p = self.media_dir / p

        if not p.exists():
            self.logger.error(f"File not found: {p}")
            return False

        title = track_title or p.stem.replace("_", " ").title()

        # Ensure speaker is connected
        if not self.is_connected():
            self.logger.info(f"Speaker {self.name} not connected, attempting connect...")
            if not self.connect():
                self.logger.error(f"Cannot play '{title}': Bluetooth speaker {self.name} is not connected.")
                return False

        self.stop()
        file_uri = p.as_uri()

        sink_arg = f"pipewiresink target-object={self.sink_name}" if self.is_connected() else "pipewiresink"
        cmd = [
            "gst-launch-1.0",
            "playbin",
            f"uri={file_uri}",
            "video-sink=fakesink",
            f"audio-sink={sink_arg}"
        ]

        try:
            with self._lock:
                self._player_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self._current_track = title
                self._playback_start_time = time.time()
                self._is_paused = False
            self.logger.info(f"Playing '{title}' on {self.name} ({self.sink_name}).")
            return True
        except Exception as e:
            self.logger.error(f"Error starting playback: {e}")
            return False

    def play_stream(self, stream_url: str, track_title: Optional[str] = None) -> bool:
        """Play an internet audio stream (e.g. online radio) on the active Bluetooth speaker."""
        target_url = stream_url.strip()
        if not target_url:
            return False

        from urllib.parse import urlparse
        parsed = urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            self.logger.warning(f"Rejected invalid audio stream URL scheme '{parsed.scheme}': {target_url}")
            return False

        title = track_title or "Інтернет-радіо"

        # Ensure speaker is connected
        if not self.is_connected():
            self.logger.info(f"Speaker {self.name} not connected, attempting connect...")
            if not self.connect():
                self.logger.error(f"Cannot stream '{title}': Bluetooth speaker {self.name} is not connected.")
                return False

        self.stop()
        time.sleep(0.2)

        # Ensure volume is audible (at least 33% by default)
        vol = self.get_volume()
        if vol < 33:
            self.set_volume(33)

        sink_target = self.sink_name if self.is_connected() else "@DEFAULT_AUDIO_SINK@"
        loop_cmd = (
            f"while true; do "
            f"gst-launch-1.0 playbin uri=\"{target_url}\" video-sink=fakesink audio-sink=\"pipewiresink target-object={sink_target}\"; "
            f"sleep 1; "
            f"done"
        )
        cmd = ["/bin/bash", "-c", loop_cmd]

        try:
            with self._lock:
                self._player_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid
                )
                self._current_track = f"📻 {title}"
                self._last_stream_url = target_url
                self._last_stream_title = title
                self._playback_start_time = time.time()
                self._is_paused = False
            self.logger.info(f"Streaming radio '{title}' from {target_url} on {self.name}.")
            return True
        except Exception as e:
            self.logger.error(f"Error starting radio stream '{title}': {e}")
            return False

    def play_youtube(self, query: str) -> bool:
        """Search and play a track from YouTube or local media cache."""
        target = query.strip()
        if not target:
            return False

        # ЖОРСТКЕ ТАБУ НА РОСІЙСЬКУ МУЗИКУ ТА КОНТЕНТ
        RUSSIAN_CHARS = set("ёъыэЁЪЫЭ")
        if any(ch in RUSSIAN_CHARS for ch in target) or any(w in target.lower() for w in ("російськ", "русск", "по-русски", "російською")):
            self.logger.warning(f"Blocked Russian media playback query: '{target}' (Hard taboo policy)")
            return False

        # Check direct file path match first
        target_path = Path(target)
        if target_path.exists() and target_path.is_file():
            return self.play_file(str(target_path))
        if (self.media_dir / target).exists():
            return self.play_file(str(self.media_dir / target))

        # Check local media matches by name
        UA_LAT_TABLE = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ye', 'ж': 'zh', 'з': 'z',
            'и': 'y', 'і': 'i', 'ї': 'yi', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p',
            'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
            'ь': '', 'ю': 'yu', 'я': 'ya'
        }
        clean_target = target_path.stem.replace("_", " ").lower()
        translit_target = "".join(UA_LAT_TABLE.get(ch, ch) for ch in clean_target)

        is_laptop_local_query = any(k in clean_target for k in (
            "ноутбук", "ноута", "ноут", "диск", "локальн", "комп"
        ))

        if self.media_dir.exists():
            local_candidates = [
                f for f in sorted(self.media_dir.iterdir())
                if f.is_file() and not f.name.endswith(".part") and not f.name.startswith("stream_") and not f.name.startswith("test_")
            ]
            for f in local_candidates:
                clean_name = f.stem.replace("_", " ").lower()
                words = [w for w in clean_target.split() if len(w) > 2]
                t_words = [w for w in translit_target.split() if len(w) > 2]
                if (
                    clean_target in clean_name
                    or clean_name in clean_target
                    or translit_target in clean_name
                    or clean_name in translit_target
                    or (words and all(word in clean_name for word in words))
                    or (t_words and all(word in clean_name for word in t_words))
                    or any(w in clean_name for w in t_words if len(w) > 3)
                    or any(w in clean_name for w in words if len(w) > 3)
                ):
                    return self.play_file(str(f), track_title=f.stem.replace("_", " ").title())

            # If user explicitly asked for local song from laptop without specific name
            if is_laptop_local_query and local_candidates:
                return self.play_file(str(local_candidates[0]), track_title=local_candidates[0].stem.replace("_", " ").title())

        # If not found locally, download/stream via yt-dlp
        import hashlib
        hash_name = hashlib.md5(target.encode("utf-8")).hexdigest()[:10]
        cached_file = self.media_dir / f"stream_{hash_name}.mp4"

        if cached_file.exists() and cached_file.stat().st_size > 100000:
            return self.play_file(str(cached_file), track_title=target)

        search_target = target if (target.startswith("http://") or target.startswith("https://")) else f"ytsearch1:{target}"
        ffmpeg_bin = "/home/yurko/AI/OpenInterpreter/venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"

        cmd_dl = [
            "/home/yurko/AI/OpenInterpreter/venv/bin/yt-dlp",
            "--ffmpeg-location", ffmpeg_bin,
            "-f", "18/best[ext=mp4][height<=720]/136+140/best/bestaudio",
            "--no-playlist",
            "-o", str(cached_file),
            search_target
        ]

        try:
            subprocess.run(cmd_dl, capture_output=True, text=True, timeout=60)
            if cached_file.exists() and cached_file.stat().st_size > 10000:
                try:
                    all_streams = sorted([f for f in self.media_dir.glob("stream_*.mp4") if f.is_file()], key=lambda x: x.stat().st_mtime)
                    if len(all_streams) > 8:
                        for old_st in all_streams[:-8]:
                            old_st.unlink(missing_ok=True)
                except Exception:
                    pass
                return self.play_file(str(cached_file), track_title=target)
        except Exception as e:
            self.logger.error(f"Error downloading audio for JBL: {e}")

        return False

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive speaker status."""
        connected = self.is_connected()
        playing = self.is_playing()
        volume = self.get_volume()


        elapsed = 0
        if playing and self._playback_start_time:
            elapsed = int(time.time() - self._playback_start_time)

        track_title = self._current_track
        if not track_title and playing:
            last_t = getattr(self, "_last_stream_title", None)
            track_title = f"📻 {last_t}" if last_t else "Аудіопотік"

        speaker_items = []
        for s in self.get_configured_speakers():
            smac = s["mac"]
            speaker_items.append({
                "mac": smac,
                "name": s["name"],
                "floor": s.get("floor", "garage"),
                "active": (smac == self.mac),
                "connected": self.is_connected(smac)
            })

        return {
            "mac": self.mac,
            "name": self.name,
            "connected": connected,
            "volume": volume,
            "playing": playing,
            "paused": self._is_paused,
            "current_track": track_title if playing else None,
            "elapsed_seconds": elapsed,
            "sink_name": self.sink_name,
            "speakers": speaker_items
        }
