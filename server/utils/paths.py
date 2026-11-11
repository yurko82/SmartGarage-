"""
server/utils/paths.py — Централізоване управління шляхами до даних проєкту
Підтримує перенаправлення через SMARTGARAGE_DATA_DIR для ізоляції тестів.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

def get_data_dir() -> Path:
    env_dir = os.getenv("SMARTGARAGE_DATA_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return REPO_ROOT

def get_devices_dir() -> Path:
    env_dir = os.getenv("SMARTGARAGE_DATA_DIR")
    if env_dir:
        p = Path(env_dir) / "devices"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return REPO_ROOT / "devices"

def get_memory_dir() -> Path:
    env_dir = os.getenv("SMARTGARAGE_DATA_DIR")
    if env_dir:
        p = Path(env_dir) / "memory"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return REPO_ROOT / "memory"

def get_rf_mappings_file() -> Path:
    env_dir = os.getenv("SMARTGARAGE_DATA_DIR")
    if env_dir:
        p = Path(env_dir) / "config" / "rf_mappings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return REPO_ROOT / "config" / "rf_mappings.json"
