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
        self._cached_volume = 75

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
        """Check if the Bluetooth speaker is currently connected."""
        target_mac = (mac or self.mac).upper().strip()
        try:
            res = subprocess.run(
                ["bluetoothctl", "info", target_mac],
                capture_output=True,
                text=True,
                timeout=4.0
            )
            return "Connected: yes" in res.stdout
        except Exception as e:
            return False

    def connect(self, mac: Optional[str] = None) -> bool:
        """Connect to the Bluetooth speaker and set as default audio sink."""
        if mac:
            self.set_active_speaker(mac)

        self.logger.info(f"Connecting to Bluetooth speaker {self.name} ({self.mac})...")
        try:
            res = subprocess.run(
                ["bluetoothctl", "connect", self.mac],
                capture_output=True,
                text=True,
                timeout=8.0
            )
            time.sleep(1.0)
            if self.is_connected():
                # Set as default audio sink
                subprocess.run(
                    ["pactl", "set-default-sink", self.sink_name],
                    capture_output=True,
                    timeout=3.0
                )
                vol = self.get_volume()
                if vol == 0:
                    self.set_volume(self._cached_volume or 75)
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
                return True
            return False

    def stop(self) -> bool:
        """Stop current audio playback."""
        with self._lock:
            if self._player_proc:
                try:
                    self._player_proc.terminate()
                    self._player_proc.wait(timeout=2.0)
                except Exception:
                    try:
                        self._player_proc.kill()
                    except Exception:
                        pass
                self._player_proc = None
            self._current_track = None
            self._playback_start_time = None
            self._is_paused = False
        return True

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

        cmd = [
            "gst-launch-1.0",
            "playbin",
            f"uri={file_uri}",
            "video-sink=fakesink",
            f"audio-sink=pulsesink device={self.sink_name}"
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

    def play_youtube(self, query: str) -> bool:
        """Search and play a track from YouTube or local media cache."""
        target = query.strip()
        if not target:
            return False

        # Check local media matches first
        query_lower = target.lower()
        if self.media_dir.exists():
            for f in self.media_dir.iterdir():
                if f.is_file() and not f.name.endswith(".part"):
                    clean_name = f.stem.replace("_", " ").lower()
                    if all(word in clean_name for word in query_lower.split() if len(word) > 2):
                        return self.play_file(str(f), track_title=f.stem.replace("_", " ").title())

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

        return {
            "mac": self.mac,
            "name": self.name,
            "connected": connected,
            "volume": volume,
            "playing": playing,
            "paused": self._is_paused,
            "current_track": self._current_track if playing else None,
            "elapsed_seconds": elapsed,
            "sink_name": self.sink_name,
            "speakers": self.get_configured_speakers()
        }
