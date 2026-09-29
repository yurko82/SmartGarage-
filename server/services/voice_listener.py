#!/usr/bin/env python3
"""
Smart Garage - Local Low-CPU Voice Listener Service
Detects wake word via `openwakeword` and transcribes speech using `faster-whisper` (int8).
Captures audio through PipeWire virtual source (`pipewire-virtual-source`) and enqueues
commands into the AI pipeline with priority: source="voice".
"""
import os
import sys
import time
import signal
import asyncio
import logging
import argparse
import subprocess
import collections
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [VoiceListener] %(message)s"
)
logger = logging.getLogger("VoiceListener")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CUSTOM_MODELS_DIR = PROJECT_ROOT / "models" / "wakeword"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


class PipeWireAudioCapture:
    """
    Manages robust PipeWire audio capture with virtual-source binding
    and automatic reconnection resilience.
    """

    def __init__(self, virtual_source_name: str = "pipewire-virtual-source", sample_rate: int = 16000, chunk_size: int = 1280):
        self.virtual_source_name = virtual_source_name
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size  # 80ms at 16000Hz
        self.stream = None
        self._sd = None
        self._ensure_pipewire_virtual_source()

    def _ensure_pipewire_virtual_source(self) -> bool:
        """
        Verify that pipewire-virtual-source exists; if not, create it dynamically
        via pactl module-remap-source mapped to the active physical microphone.
        """
        try:
            res = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True, timeout=3.0)
            if self.virtual_source_name in res.stdout:
                logger.info(f"PipeWire virtual source '{self.virtual_source_name}' is already active.")
                return True

            logger.info(f"Creating PipeWire virtual source '{self.virtual_source_name}'...")
            # Discover active analog/USB input microphone
            master_source = None
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[1]
                    if ("input" in name or "mic" in name) and not name.endswith(".monitor"):
                        master_source = name
                        break

            cmd = [
                "pactl", "load-module", "module-remap-source",
                f"source_name={self.virtual_source_name}",
                f"source_properties=device.description=PipeWire-Virtual-Source"
            ]
            if master_source:
                cmd.append(f"master={master_source}")
                logger.info(f"Mapping virtual source to master physical source: {master_source}")

            create_res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
            if create_res.returncode == 0:
                logger.info(f"Successfully loaded PipeWire virtual source module: {create_res.stdout.strip()}")
                return True
            else:
                logger.warning(f"Could not load module-remap-source ({create_res.stderr.strip()}). Using default PipeWire source.")
        except Exception as e:
            logger.warning(f"PipeWire virtual source check warning: {e}. Will rely on default audio source.")
        return False

    def open_stream(self):
        """Open low-latency input stream with sounddevice."""
        import sounddevice as sd
        self._sd = sd

        # Configure environment to route through virtual source if supported
        os.environ["PULSE_SOURCE"] = self.virtual_source_name

        device_index = None
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            dname = dev.get("name", "").lower()
            if self.virtual_source_name.lower() in dname:
                device_index = idx
                logger.info(f"Found dedicated virtual source device at index {idx}: {dev.get('name')}")
                break

        self.stream = sd.InputStream(
            device=device_index,
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size
        )
        self.stream.start()
        logger.info(f"Audio capture stream started ({self.sample_rate}Hz, 16-bit PCM, chunk={self.chunk_size}).")

    def read_chunk(self) -> np.ndarray:
        """Read a single audio chunk from the stream."""
        if not self.stream or not self.stream.active:
            raise IOError("Audio stream is not active.")
        data, overflowed = self.stream.read(self.chunk_size)
        if overflowed:
            logger.debug("Audio buffer overflow occurred (ignoring to prevent latency).")
        return data.flatten()

    def close(self):
        """Close audio stream cleanly."""
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            logger.info("Audio stream closed.")


class LowCpuWakeWordDetector:
    """
    Wake word detector powered by openwakeword.
    Optimized for < 10% CPU usage with single-threaded ONNX inference and RMS energy gating.
    """

    def __init__(self, model_name_or_path: str = "hey_jarvis", threshold: float = 0.55, energy_gate: int = 150):
        self.threshold = threshold
        self.energy_gate = energy_gate  # RMS amplitude threshold below which inference is skipped
        self.model = None
        self.target_model_key = None
        self._init_model(model_name_or_path)

    def _init_model(self, target: str):
        import openwakeword
        from openwakeword.model import Model

        # Limit ONNX runtime to 1 CPU thread for strict slice compliance
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
        except Exception:
            pass

        model_paths = []
        # Check custom models folder
        custom_candidate = CUSTOM_MODELS_DIR / f"{target}.onnx"
        if custom_candidate.exists():
            model_paths.append(str(custom_candidate))
            logger.info(f"Using custom wake word model: {custom_candidate}")
        elif Path(target).is_file():
            model_paths.append(str(Path(target).resolve()))
            logger.info(f"Using custom wake word model from path: {target}")
        else:
            # Check built-in models
            builtins_dir = Path(openwakeword.__file__).parent / "resources" / "models"
            matched_builtin = None
            for f in builtins_dir.glob("*.onnx"):
                if target.lower() in f.stem.lower():
                    matched_builtin = str(f)
                    break

            if matched_builtin:
                model_paths.append(matched_builtin)
                logger.info(f"Loaded built-in openwakeword model: {matched_builtin}")
            else:
                logger.info(f"Model '{target}' not specifically found. Loading default openwakeword models.")

        # Initialize openwakeword Model
        self.model = Model(wakeword_model_paths=model_paths, inference_framework="onnx")
        loaded_keys = list(self.model.models.keys())
        logger.info(f"Wake word detector initialized with models: {loaded_keys}")

        # Choose primary target key
        for k in loaded_keys:
            if target.lower() in k.lower():
                self.target_model_key = k
                break
        if not self.target_model_key and loaded_keys:
            self.target_model_key = loaded_keys[0]

        logger.info(f"Active wake word target key: '{self.target_model_key}' (Threshold: {self.threshold})")

    def process_chunk(self, chunk: np.ndarray) -> Tuple[bool, float, str]:
        """
        Process an 80ms int16 chunk.
        Returns: (detected: bool, score: float, model_name: str)
        """
        # Low-CPU Energy Gate: Skip inference completely if chunk is ambient silence
        rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))
        if rms < self.energy_gate:
            return False, 0.0, ""

        predictions = self.model.predict(chunk)
        for name, score in predictions.items():
            if score >= self.threshold:
                return True, float(score), name
        return False, 0.0, ""

    def reset(self):
        """Reset internal buffers after detection."""
        if hasattr(self.model, "reset"):
            self.model.reset()


class LowCpuSpeechTranscriber:
    """
    Speech-to-Text engine using faster-whisper with INT8 CPU quantization
    and single-thread greedy decoding (beam_size=1).
    """

    def __init__(self, model_size: str = "base", language: str = "uk", cpu_threads: int = 1):
        self.model_size = model_size
        self.language = language
        self.cpu_threads = cpu_threads
        self.model = None
        self._load_model()

    def _load_model(self):
        from faster_whisper import WhisperModel
        logger.info(f"Loading faster-whisper '{self.model_size}' (device=cpu, compute_type=int8, threads={self.cpu_threads})...")
        t0 = time.time()
        self.model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=self.cpu_threads
        )
        logger.info(f"faster-whisper model loaded in {time.time() - t0:.2f}s.")

    def transcribe(self, audio_data: np.ndarray) -> str:
        """
        Transcribes 16kHz float32 audio array.
        Uses beam_size=1 (greedy) for maximum speed and lowest CPU consumption.
        """
        if len(audio_data) < 4000:  # Less than 0.25s
            return ""

        t0 = time.time()
        segments, info = self.model.transcribe(
            audio_data,
            language=self.language,
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        elapsed = time.time() - t0
        logger.info(f"Transcription finished in {elapsed:.2f}s (lang: {info.language}): «{text}»")
        return text


class VoiceListenerService:
    """
    Main background voice interface service.
    Coordinates audio capture, wake word detection, STT transcription,
    and priority message queue dispatch.
    """

    def __init__(
        self,
        wake_word: str = "hey_jarvis",
        wake_word_threshold: float = 0.55,
        whisper_model: str = "base",
        whisper_lang: str = "uk",
        api_url: str = "http://127.0.0.1:5000/api/voice/command",
        max_record_sec: float = 8.0,
        silence_timeout_sec: float = 1.3
    ):
        self.wake_word = wake_word
        self.wake_word_threshold = wake_word_threshold
        self.whisper_model_name = whisper_model
        self.whisper_lang = whisper_lang
        self.api_url = api_url
        self.max_record_sec = max_record_sec
        self.silence_timeout_sec = silence_timeout_sec

        self.running = False
        self.audio = PipeWireAudioCapture()
        self.detector = None
        self.transcriber = None

        # Asynchronous Queue for recognized commands
        from server.services.voice_queue import voice_command_queue
        self.queue = voice_command_queue

        self._debounce_until = 0.0

    def init_engines(self):
        """Initialize AI models with memory and CPU efficiency."""
        self.detector = LowCpuWakeWordDetector(
            model_name_or_path=self.wake_word,
            threshold=self.wake_word_threshold
        )
        self.transcriber = LowCpuSpeechTranscriber(
            model_size=self.whisper_model_name,
            language=self.whisper_lang,
            cpu_threads=1
        )

    def _record_speech_after_wakeword(self) -> np.ndarray:
        """
        Record audio following wake word detection until speech pauses
        (silence_timeout_sec) or max_record_sec is reached.
        """
        logger.info("🎙️ Wake word detected! Listening for garage command...")
        recorded_chunks = []
        silence_start = None
        speech_started = False
        start_time = time.time()

        speech_energy_threshold = 220

        while time.time() - start_time < self.max_record_sec:
            try:
                chunk = self.audio.read_chunk()
                recorded_chunks.append(chunk)
                rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))

                if rms > speech_energy_threshold:
                    speech_started = True
                    silence_start = None
                else:
                    if speech_started:
                        if silence_start is None:
                            silence_start = time.time()
                        elif time.time() - silence_start >= self.silence_timeout_sec:
                            logger.info(f"Silence detected after command ({time.time() - silence_start:.2f}s). Finalizing recording.")
                            break
                    else:
                        # Allow up to 2.5s of initial pause before aborting
                        if time.time() - start_time > 2.5:
                            logger.info("No speech detected after wake word.")
                            break
            except Exception as e:
                logger.warning(f"Error while recording speech chunk: {e}")
                break

        if not recorded_chunks:
            return np.array([], dtype=np.float32)

        # Concatenate and normalize int16 to float32 [-1.0, 1.0]
        full_pcm = np.concatenate(recorded_chunks, axis=0)
        audio_float32 = full_pcm.astype(np.float32) / 32768.0
        return audio_float32

    async def _dispatch_command(self, text: str):
        """
        Enqueue command into asyncio.Queue and post to webapp / Open Interpreter pipeline.
        """
        if not text:
            return

        # 1. Enqueue into local priority queue
        await self.queue.put(text=text, source="voice", priority=1)

        # 2. Dispatch via HTTP to server API
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                payload = {"command": text, "text": text, "source": "voice"}
                async with session.post(self.api_url, json=payload, timeout=aiohttp.ClientTimeout(total=6.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        resp_text = data.get("response") or "Виконано"
                        logger.info(f"✅ AI Response for voice command: «{resp_text}»")
                    else:
                        logger.warning(f"Server returned status {resp.status} for voice command.")
        except Exception as e:
            logger.warning(f"Could not forward voice command to {self.api_url}: {e} (Enqueued in local queue)")

    async def run_loop(self):
        """Main listening loop with automatic reconnection resilience."""
        self.running = True
        logger.info("Starting local voice listening loop...")
        backoff_sec = 1.0

        while self.running:
            try:
                # Open audio stream if not open
                if not self.audio.stream or not self.audio.stream.active:
                    logger.info("Connecting to PipeWire audio stream...")
                    self.audio.open_stream()
                    backoff_sec = 1.0  # Reset backoff on success

                chunk = self.audio.read_chunk()

                # Check debounce period
                if time.time() < self._debounce_until:
                    await asyncio.sleep(0.01)
                    continue

                # Process wake word detection
                detected, score, model_name = self.detector.process_chunk(chunk)
                if detected:
                    logger.info(f"⚡ Wake word TRIGGERED ('{model_name}', score={score:.2f})!")
                    self._debounce_until = time.time() + 2.5  # Prevent immediate double trigger

                    # Record command audio
                    speech_audio = self._record_speech_after_wakeword()

                    if len(speech_audio) > 0:
                        # Transcribe with faster-whisper
                        transcript = self.transcriber.transcribe(speech_audio)
                        if transcript:
                            await self._dispatch_command(transcript)

                    # Reset detector internal history
                    self.detector.reset()

                # Yield control briefly to event loop
                await asyncio.sleep(0.005)

            except (IOError, Exception) as e:
                logger.error(f"PipeWire audio stream error: {e}. Reconnecting in {backoff_sec:.1f}s...")
                self.audio.close()
                await asyncio.sleep(backoff_sec)
                backoff_sec = min(backoff_sec * 2.0, 10.0)

        self.audio.close()
        logger.info("Voice listener service stopped.")

    def stop(self):
        """Signal service termination."""
        self.running = False


def load_config() -> Dict[str, Any]:
    """Load configuration from config/config.yaml."""
    cfg = {}
    if DEFAULT_CONFIG_PATH.exists():
        try:
            import yaml
            with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    return cfg


def main():
    parser = argparse.ArgumentParser(description="Smart Garage Low-CPU Voice Listener")
    parser.add_argument("--wake-word", type=str, default="hey_jarvis", help="Wake word model name or path")
    parser.add_argument("--threshold", type=float, default=0.55, help="Wake word detection threshold")
    parser.add_argument("--whisper-model", type=str, default="base", help="faster-whisper model (tiny, base, small)")
    parser.add_argument("--lang", type=str, default="uk", help="Whisper language code (default: uk)")
    parser.add_argument("--api-url", type=str, default="http://127.0.0.1:5000/api/voice/command", help="Endpoint to send commands")
    args = parser.parse_args()

    # Merge config file settings
    cfg = load_config()
    voice_cfg = cfg.get("voice", {})
    wake_word = voice_cfg.get("wake_word", args.wake_word)
    threshold = float(voice_cfg.get("wake_word_threshold", args.threshold))
    whisper_model = voice_cfg.get("whisper_model", args.whisper_model)
    whisper_lang = voice_cfg.get("whisper_language", args.lang)
    api_url = voice_cfg.get("api_endpoint", args.api_url)

    service = VoiceListenerService(
        wake_word=wake_word,
        wake_word_threshold=threshold,
        whisper_model=whisper_model,
        whisper_lang=whisper_lang,
        api_url=api_url
    )

    service.init_engines()

    # Handle system signals for clean exit
    def _sig_handler(sig, frame):
        logger.info(f"Received exit signal ({sig}). Stopping voice service...")
        service.stop()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        asyncio.run(service.run_loop())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Exiting on keyboard interrupt.")


if __name__ == "__main__":
    main()
