"""
server/services/voice_listener.py — Шар зворотної сумісності для голосового сервісу.
Перенаправляє виклики до модульної підсистеми server/voice/.
"""
import logging

from server.voice.listener import LowCpuWakeWordDetector, WakeWordDetector
from server.voice.service import (
    PipeWireAudioCapture,
    VoiceListenerService,
    VoiceService,
    main,
)
from server.voice.synthesizer import VoiceSynthesizer
from server.voice.transcriber import LowCpuSpeechTranscriber, SpeechTranscriber

logger = logging.getLogger("VoiceListener")

__all__ = [
    "WakeWordDetector",
    "LowCpuWakeWordDetector",
    "SpeechTranscriber",
    "LowCpuSpeechTranscriber",
    "VoiceSynthesizer",
    "PipeWireAudioCapture",
    "VoiceService",
    "VoiceListenerService",
    "main",
]

if __name__ == "__main__":
    main()
