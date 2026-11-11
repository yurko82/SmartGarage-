"""
tests/test_utils.py — Модульні тести для server/utils/jsonstore.py та server/utils/sysproc.py
"""
import json
import subprocess
from pathlib import Path

import pytest

from server.utils.jsonstore import JsonStore, atomic_dump, atomic_load
from server.utils.sysproc import SysProcError, safe_run


class TestJsonStore:
    def test_atomic_dump_and_load(self, tmp_path: Path):
        file_path = tmp_path / "test_data.json"
        payload = {"garage": "open", "temp": 21.5, "tags": ["rf", "ble"]}

        atomic_dump(payload, file_path)
        assert file_path.exists()

        loaded = atomic_load(file_path)
        assert loaded == payload

    def test_atomic_dump_creates_backup(self, tmp_path: Path):
        file_path = tmp_path / "config.json"
        atomic_dump({"version": 1}, file_path)

        # Overwrite with backup
        atomic_dump({"version": 2}, file_path, backup=True)
        bak_file = tmp_path / "config.json.bak"
        assert bak_file.exists()
        assert atomic_load(bak_file) == {"version": 1}
        assert atomic_load(file_path) == {"version": 2}

    def test_corrupted_json_fallback_and_backup(self, tmp_path: Path):
        file_path = tmp_path / "broken.json"
        file_path.write_text("{ broken json content: ", encoding="utf-8")

        res = atomic_load(file_path, default={"fallback": True})
        assert res == {"fallback": True}

        # Verify a .corrupted.*.bak was generated
        corrupted_files = list(tmp_path.glob("broken*.bak"))
        assert len(corrupted_files) >= 1

    def test_json_store_class_crud(self, tmp_path: Path):
        file_path = tmp_path / "store.json"
        store = JsonStore(file_path, default_factory=lambda: {"count": 0})

        data = store.load()
        assert data == {"count": 0}

        def increment(d):
            d["count"] += 5

        updated = store.update(increment)
        assert updated["count"] == 5

        # Check loaded again
        assert store.load()["count"] == 5


class TestSysProc:
    def test_safe_run_echo(self):
        proc = safe_run(["echo", "smartgarage_test"], timeout=2.0)
        assert proc.returncode == 0
        assert "smartgarage_test" in proc.stdout

    def test_safe_run_rejects_shell_true(self):
        with pytest.raises(ValueError, match="shell=True заборонено"):
            safe_run(["echo", "fail"], shell=True)  # type: ignore

    def test_safe_run_invalid_command(self):
        with pytest.raises(ValueError, match="непорожнім списком"):
            safe_run([])

    def test_safe_run_not_found(self):
        with pytest.raises(SysProcError, match="не знайдено"):
            safe_run(["non_existent_binary_xyz_12345"])

    def test_safe_run_timeout(self):
        with pytest.raises(SysProcError, match="Таймаут"):
            safe_run(["sleep", "2"], timeout=0.1)
