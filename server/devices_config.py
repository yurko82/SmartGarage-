"""
server/devices_config.py — Завантаження конфігурації фізичних пристроїв (MAC-адрес)
Читає config/devices.yaml, за відсутності бере config/devices.yaml.example.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVICES_CONFIG_FILE = REPO_ROOT / "config" / "devices.yaml"
DEVICES_EXAMPLE_FILE = REPO_ROOT / "config" / "devices.yaml.example"

_cached_config: Optional[Dict[str, Any]] = None

def get_devices_config() -> Dict[str, Any]:
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    
    cfg_file = DEVICES_CONFIG_FILE if DEVICES_CONFIG_FILE.exists() else DEVICES_EXAMPLE_FILE
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                _cached_config = yaml.safe_load(f) or {}
                return _cached_config
        except Exception:
            pass
    return {}

def reload_devices_config():
    global _cached_config
    _cached_config = None

def get_speaker_config(speaker_key: str) -> Dict[str, Any]:
    cfg = get_devices_config().get("speakers", {})
    return cfg.get(speaker_key, {})

def get_configured_speakers_list() -> List[Dict[str, Any]]:
    speakers_cfg = get_devices_config().get("speakers", {})
    res = []
    for key, info in speakers_cfg.items():
        mac = info.get("mac", "").upper().strip()
        if mac:
            res.append({
                "key": key,
                "mac": mac,
                "name": info.get("name", "Колонка"),
                "floor": info.get("floor", "garage")
            })
    return res

def get_sensor_config(sensor_key: str) -> Dict[str, Any]:
    cfg = get_devices_config().get("sensors", {})
    return cfg.get(sensor_key, {})

def get_owner_mac() -> str:
    return get_devices_config().get("owner", {}).get("phone_mac", "").upper().strip()
