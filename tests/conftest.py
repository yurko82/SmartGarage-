"""
tests/conftest.py — Фікстури для герметичності та ізоляції тестів SmartGarage
Переспрямовує memory/, devices/, config/rf_mappings.json у tmp_path через SMARTGARAGE_DATA_DIR.
Будь-який тест, що модифікує робочі файли проєкту, падає.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTECTED_PATHS = [
    REPO_ROOT / "config" / "rf_mappings.json",
    REPO_ROOT / "devices",
    REPO_ROOT / "memory",
]

IGNORED_DEVICE_FILES = {
    "sensor_cache.json",
    "presence_log.json",
    "presence_devices.json",
    "ytmusic_cookies.txt",
    "ytmusic_playlists.json",
    "telemetry.db",
    "telemetry.db-wal",
    "telemetry.db-shm",
}

def _get_path_snapshot(path: Path):
    if not path.exists():
        return None
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot = {}
    for p in sorted(path.rglob("*")):
        if (
            p.is_file()
            and not p.name.endswith(".pyc")
            and "__pycache__" not in p.parts
            and p.name not in IGNORED_DEVICE_FILES
            and "ytmusic_cache" not in p.parts
        ):
            snapshot[str(p.relative_to(path))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snapshot

@pytest.fixture(autouse=True)
def isolate_smartgarage_data(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Налаштування тимчасової директорії memory/
    tmp_memory = data_dir / "memory"
    tmp_memory.mkdir(parents=True, exist_ok=True)
    real_memory = REPO_ROOT / "memory"
    if real_memory.exists():
        for f in real_memory.glob("*.json"):
            shutil.copy(f, tmp_memory / f.name)

    # 2. Налаштування тимчасової директорії devices/
    tmp_devices = data_dir / "devices"
    tmp_devices.mkdir(parents=True, exist_ok=True)
    real_devices = REPO_ROOT / "devices"
    if real_devices.exists():
        for f in real_devices.glob("*.json"):
            # Не копіюємо невідстежувані bluetooth_devices.json та presence_devices.json
            if f.name not in ("bluetooth_devices.json", "presence_devices.json"):
                shutil.copy(f, tmp_devices / f.name)

    # Забезпечити стандартні тестові фікстури bluetooth_devices.json та presence_devices.json
    fake_bt = {
        "00:11:22:33:44:01": {
            "name": "JX-BT",
            "in_garage": True,
            "alias": "Музика 1-й поверх",
            "floor": "floor1",
            "type": "speaker"
        },
        "00:11:22:33:44:02": {
            "name": "JBL Clip 5",
            "in_garage": True,
            "alias": "JBL Clip 5 (Гараж)",
            "floor": "garage",
            "type": "speaker"
        },
        "00:11:22:33:44:03": {
            "name": "LYWSD03MMC",
            "in_garage": True,
            "alias": "Підвал",
            "floor": "basement",
            "type": "temperature_sensor"
        },
        "00:11:22:33:44:04": {
            "name": "LYWSD03MMC",
            "in_garage": False,
            "alias": "2-й поверх",
            "floor": "floor2",
            "type": "temperature_sensor"
        }
    }
    (tmp_devices / "bluetooth_devices.json").write_text(json.dumps(fake_bt, indent=2, ensure_ascii=False), encoding="utf-8")

    fake_presence = {
        "owner_phone": {
            "id": "owner_phone",
            "name": "Юрій (Власник)",
            "role": "owner",
            "device_type": "phone",
            "device_name": "Motorola Edge 50 Pro",
            "classic_mac": "00:11:22:33:44:05",
            "ble_services": [],
            "recent_ble_rpa": [
                "00:11:22:33:44:05"
            ],
            "status": "away",
            "last_seen": 1794242789.0,
            "last_rssi": -50,
            "proximity": "immediate",
            "auto_welcome": True
        }
    }
    (tmp_devices / "presence_devices.json").write_text(json.dumps(fake_presence, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Налаштування тимчасового config/rf_mappings.json
    tmp_config = data_dir / "config"
    tmp_config.mkdir(parents=True, exist_ok=True)
    real_rf = REPO_ROOT / "config" / "rf_mappings.json"
    if real_rf.exists():
        shutil.copy(real_rf, tmp_config / "rf_mappings.json")

    # Встановлення змінної середовища
    monkeypatch.setenv("SMARTGARAGE_DATA_DIR", str(data_dir))

    # Перезавантажуємо стан garage.presence, якщо він вже імпортований
    try:
        from server.webapp import garage
        if hasattr(garage, "presence") and garage.presence:
            with garage.presence._lock:
                garage.presence._load_data()
                garage.presence._ensure_defaults()
    except Exception:
        pass

    # Перемикання devices_config на тестовий шаблон devices.yaml.example
    try:
        import server.devices_config as dev_cfg_mod
        monkeypatch.setattr(dev_cfg_mod, "DEVICES_CONFIG_FILE", REPO_ROOT / "config" / "devices.yaml.example")
        dev_cfg_mod.reload_devices_config()
    except Exception:
        pass

    # Фіксуємо початковий стан перед запуском тесту
    initial_snapshots = {p: _get_path_snapshot(p) for p in PROTECTED_PATHS}

    yield

    # Перевірка: жоден захищений файл не мав змінитись
    for path in PROTECTED_PATHS:
        before = initial_snapshots[path]
        after = _get_path_snapshot(path)
        assert before == after, (
            f"TEST ISOLATION VIOLATION: Test modified protected workspace file/directory '{path}'! "
            f"All writes must use SMARTGARAGE_DATA_DIR / tmp_path."
        )
