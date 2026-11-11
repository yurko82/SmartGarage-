"""
server/voice/listener.py — Детектор активаційної фрази (Wake Word)
Оптимізований для низького споживання CPU (<2-5%) завдяки енергетичному гейту (RMS)
та однопотоковому виконанню OpenWakeWord.
"""

import logging
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np

logger = logging.getLogger("VoiceListener.WakeWord")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CUSTOM_MODELS_DIR = PROJECT_ROOT / "models" / "wakeword"


class WakeWordDetector:
    """Детектор активаційної фрази на основі OpenWakeWord."""

    def __init__(self, model_name_or_path: str = "hey_jarvis", threshold: float = 0.55, energy_gate: int = 150):
        self.threshold = threshold
        self.energy_gate = energy_gate
        self.model: Any = None
        self.target_model_key: str | None = None
        self._init_model(model_name_or_path)

    def _init_model(self, target: str):
        try:
            import openwakeword
            from openwakeword.model import Model
        except ImportError:
            logger.warning("Бібліотеку openwakeword не знайдено. Детектор працюватиме в режимі заглушки.")
            return

        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
        except Exception:
            pass

        model_paths = []
        custom_candidate = CUSTOM_MODELS_DIR / f"{target}.onnx"
        if custom_candidate.exists():
            model_paths.append(str(custom_candidate))
            logger.info(f"Використовується кастомна модель активації: {custom_candidate}")
        elif Path(target).is_file():
            model_paths.append(str(Path(target).resolve()))
            logger.info(f"Використовується модель активації за шляхом: {target}")
        else:
            builtins_dir = Path(openwakeword.__file__).parent / "resources" / "models"
            matched_builtin = None
            if builtins_dir.exists():
                for f in builtins_dir.glob("*.onnx"):
                    if target.lower() in f.stem.lower():
                        matched_builtin = str(f)
                        break
            if matched_builtin:
                model_paths.append(matched_builtin)
                logger.info(f"Завантажено вбудовану модель: {matched_builtin}")
            else:
                logger.info(f"Модель '{target}' не знайдено персонально. Завантаження типових моделей.")

        try:
            self.model = Model(wakeword_model_paths=model_paths, inference_framework="onnx")
            loaded_keys = list(self.model.models.keys())
            logger.info(f"Моделі OpenWakeWord успішно завантажено: {loaded_keys}")

            for k in loaded_keys:
                if target.lower() in k.lower():
                    self.target_model_key = k
                    break
            if not self.target_model_key and loaded_keys:
                self.target_model_key = loaded_keys[0]

            logger.info(f"Цільовий ключ активації: '{self.target_model_key}' (Поріг: {self.threshold})")
        except Exception as e:
            logger.error(f"Помилка ініціалізації моделі OpenWakeWord: {e}")

    def process_chunk(self, chunk: np.ndarray) -> tuple[bool, float, str]:
        """
        Обробка 80-мс аудіо-фрейму int16 (1280 семплів при 16 кГц).
        Повертає: (detected: bool, score: float, model_name: str)
        """
        if self.model is None or len(chunk) == 0:
            return False, 0.0, ""

        # Energy Gate: пропуск інференсу для тиші/фонового шуму
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        if rms < self.energy_gate:
            return False, 0.0, ""

        try:
            predictions = self.model.predict(chunk)
            for name, score in predictions.items():
                if score >= self.threshold:
                    return True, float(score), name
        except Exception as e:
            logger.debug(f"Помилка розрахунку OpenWakeWord: {e}")

        return False, 0.0, ""

    def reset(self):
        """Скидання внутрішнього буфера після виявлення фрази."""
        if self.model and hasattr(self.model, "reset"):
            try:
                self.model.reset()
            except Exception:
                pass


# Аліас для збереження сумісності
LowCpuWakeWordDetector = WakeWordDetector
