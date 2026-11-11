"""
Smart Garage Voice Subsystem — локальний модуль голосового керування.
"""

from server.voice.listener import LowCpuWakeWordDetector, WakeWordDetector
from server.voice.service import (
    PipeWireAudioCapture,
    VoiceListenerService,
    VoiceService,
    main,
)
from server.voice.synthesizer import VoiceSynthesizer
from server.voice.transcriber import LowCpuSpeechTranscriber, SpeechTranscriber

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
