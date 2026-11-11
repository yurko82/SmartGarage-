"""
tests/test_voice_subsystem.py — Модульні тести голосової підсистеми Smart Garage
Перевірка WakeWordDetector, SpeechTranscriber, VoiceSynthesizer, PipeWireAudioCapture та VoiceService.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from server.voice.listener import LowCpuWakeWordDetector, WakeWordDetector
from server.voice.service import (
    PipeWireAudioCapture,
    VoiceListenerService,
    VoiceService,
)
from server.voice.synthesizer import VoiceSynthesizer
from server.voice.transcriber import LowCpuSpeechTranscriber, SpeechTranscriber


class TestWakeWordDetector:
    """Тестування компонента виявлення активаційної фрази."""

    def test_alias_equivalence(self):
        assert LowCpuWakeWordDetector is WakeWordDetector

    def test_init_without_openwakeword(self):
        with patch.dict("sys.modules", {"openwakeword": None, "openwakeword.model": None}):
            detector = WakeWordDetector("test_model")
            assert detector.threshold == 0.55
            assert detector.model is None

    def test_energy_gate_silence(self):
        detector = WakeWordDetector("dummy", threshold=0.5, energy_gate=150)
        detector.model = MagicMock()
        # Silent chunk: all zeros
        silent_chunk = np.zeros(1280, dtype=np.int16)
        detected, score, name = detector.process_chunk(silent_chunk)
        assert not detected
        assert score == 0.0
        # Model.predict should not be invoked due to energy gate
        detector.model.predict.assert_not_called()

    def test_detection_success(self):
        detector = WakeWordDetector("hey_jarvis", threshold=0.5, energy_gate=50)
        detector.model = MagicMock()
        detector.model.predict.return_value = {"hey_jarvis": 0.85}

        # Loud enough signal
        loud_chunk = np.full(1280, 500, dtype=np.int16)
        detected, score, name = detector.process_chunk(loud_chunk)
        assert detected is True
        assert score == 0.85
        assert name == "hey_jarvis"

    def test_detection_below_threshold(self):
        detector = WakeWordDetector("hey_jarvis", threshold=0.7, energy_gate=50)
        detector.model = MagicMock()
        detector.model.predict.return_value = {"hey_jarvis": 0.4}

        loud_chunk = np.full(1280, 500, dtype=np.int16)
        detected, score, name = detector.process_chunk(loud_chunk)
        assert detected is False
        assert score == 0.0

    def test_reset(self):
        detector = WakeWordDetector("dummy")
        detector.model = MagicMock()
        detector.reset()
        detector.model.reset.assert_called_once()


class TestSpeechTranscriber:
    """Тестування компонента розпізнавання мовлення."""

    def test_alias_equivalence(self):
        assert LowCpuSpeechTranscriber is SpeechTranscriber

    def test_transcribe_short_audio(self):
        transcriber = SpeechTranscriber(model_size="tiny", language="uk")
        # Audio too short (< 4000 samples)
        short_audio = np.zeros(500, dtype=np.float32)
        assert transcriber.transcribe(short_audio) == ""

    def test_transcribe_none_model(self):
        transcriber = SpeechTranscriber(model_size="tiny")
        transcriber.model = None
        audio = np.zeros(8000, dtype=np.float32)
        assert transcriber.transcribe(audio) == ""

    def test_transcribe_success(self):
        transcriber = SpeechTranscriber(model_size="tiny")
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "відкрий гараж"
        mock_model.transcribe.return_value = ([mock_segment], None)
        transcriber.model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        text = transcriber.transcribe(audio)
        assert text == "відкрий гараж"


class TestVoiceSynthesizer:
    """Тестування синтезу мовлення."""

    def test_synthesize_empty(self):
        synth = VoiceSynthesizer()
        assert synth.synthesize("") is None
        assert synth.synthesize("   ") is None

    def test_synthesize_success(self):
        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.audio_bytes = b"fake_mp3_audio"
        mock_manager.synthesize.return_value = mock_result

        synth = VoiceSynthesizer(tts_manager=mock_manager)
        audio = synth.synthesize("Гараж відкрито")
        assert audio == b"fake_mp3_audio"
        mock_manager.synthesize.assert_called_once_with("Гараж відкрито", provider="edge")

    def test_synthesize_to_file(self, tmp_path):
        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.audio_bytes = b"mp3_data_test"
        mock_manager.synthesize.return_value = mock_result

        synth = VoiceSynthesizer(tts_manager=mock_manager)
        target_file = tmp_path / "speech.mp3"
        ok = synth.synthesize_to_file("Тест", str(target_file))
        assert ok is True
        assert target_file.read_bytes() == b"mp3_data_test"


class TestPipeWireAudioCapture:
    """Тестування захоплення аудіо."""

    @patch("subprocess.run")
    def test_init_check_source(self, mock_subproc):
        mock_subproc.return_value = MagicMock(returncode=0, stdout="pipewire-virtual-source")
        capture = PipeWireAudioCapture(virtual_source_name="pipewire-virtual-source")
        assert capture.virtual_source_name == "pipewire-virtual-source"
        assert capture.sample_rate == 16000
        assert capture.chunk_size == 1280

    def test_read_chunk_inactive_stream_raises(self):
        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = MagicMock(returncode=0, stdout="pipewire-virtual-source")
            capture = PipeWireAudioCapture()
            capture.stream = None
            with pytest.raises(OSError, match="не активний"):
                capture.read_chunk()

    def test_close_stream(self):
        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = MagicMock(returncode=0, stdout="pipewire-virtual-source")
            capture = PipeWireAudioCapture()
            mock_stream = MagicMock()
            capture.stream = mock_stream
            capture.close()
            mock_stream.stop.assert_called_once()
            mock_stream.close.assert_called_once()
            assert capture.stream is None


class TestVoiceService:
    """Тестування координатора VoiceService."""

    def test_alias_equivalence(self):
        assert VoiceListenerService is VoiceService

    def test_init_defaults(self):
        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = MagicMock(returncode=0, stdout="pipewire-virtual-source")
            service = VoiceService(wake_word="jarvis", whisper_model="tiny")
            assert service.wake_word == "jarvis"
            assert service.whisper_model_name == "tiny"
            assert service.running is False

    def test_record_speech_after_wakeword_captures_audio(self):
        mock_capture = MagicMock()
        # Return 2 loud chunks followed by silence
        loud_chunk = np.full(1280, 600, dtype=np.int16)
        silent_chunk = np.zeros(1280, dtype=np.int16)
        mock_capture.read_chunk.side_effect = [loud_chunk, loud_chunk, silent_chunk, silent_chunk, silent_chunk]

        service = VoiceService(audio_capture=mock_capture, max_record_sec=2.0, silence_timeout_sec=0.05)

        audio = service.record_speech_after_wakeword()
        assert len(audio) > 0
        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.float32

    def test_dispatch_command_success(self):
        service = VoiceService(api_url="http://test-server/api/voice/command")
        service.queue = AsyncMock()

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"response": "Гараж закрито"})

        mock_session_inst = MagicMock()
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session_inst.post.return_value = mock_post_cm

        mock_session_cls = MagicMock()
        mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_cls.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cls):
            reply = asyncio.run(service.dispatch_command("закрий гараж"))
            assert reply == "Гараж закрито"
            service.queue.put.assert_awaited_once_with(text="закрий гараж", source="voice", priority=1)
