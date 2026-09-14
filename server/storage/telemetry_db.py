import os
import time
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional


class TelemetryDB:
    """Persistent SQLite-backed storage for sensor climate history (temperature, humidity, battery)."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            self.db_path = base_dir / "devices" / "telemetry.db"
        else:
            self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._last_record_per_floor: Dict[str, Dict[str, Any]] = {}
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS climate_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        datetime_str TEXT NOT NULL,
                        floor TEXT NOT NULL,
                        mac TEXT,
                        sensor_name TEXT,
                        temperature REAL,
                        humidity REAL,
                        battery REAL
                    );
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_climate_timestamp ON climate_history(timestamp);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_climate_floor_ts ON climate_history(floor, timestamp);")
                conn.commit()
            finally:
                conn.close()

    def record(self, floor: str, temperature: Optional[float], humidity: Optional[float] = None,
               battery: Optional[float] = None, mac: Optional[str] = None,
               sensor_name: Optional[str] = None, timestamp: Optional[float] = None,
               force: bool = False) -> bool:
        """Record a climate measurement into SQLite.
        
        Rate-limited to avoid database bloat if values don't change and less than 60s elapsed.
        """
        if temperature is None and humidity is None:
            return False

        now = timestamp if timestamp is not None else time.time()
        floor_key = str(floor or "garage").lower().strip()
        
        # Friendly floor name mapping if not provided
        if not sensor_name:
            if floor_key == "basement":
                sensor_name = "Підвал"
            elif floor_key == "floor2":
                sensor_name = "2-й поверх"
            elif floor_key == "floor1":
                sensor_name = "1-й поверх (Гараж)"
            else:
                sensor_name = floor_key

        with self._lock:
            last = self._last_record_per_floor.get(floor_key)
            if not force and last:
                time_diff = now - last["timestamp"]
                temp_diff = abs((temperature or 0) - (last.get("temperature") or 0)) if temperature is not None else 0
                hum_diff = abs((humidity or 0) - (last.get("humidity") or 0)) if humidity is not None else 0

                # Skip if less than 60 seconds elapsed and no noticeable change (>=0.1°C or >=1% hum)
                if time_diff < 60 and temp_diff < 0.1 and hum_diff < 1.0:
                    return False
                # If identical values and less than 5 minutes elapsed, skip duplicate logging
                if time_diff < 300 and temp_diff == 0.0 and hum_diff == 0.0:
                    return False

            dt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO climate_history (timestamp, datetime_str, floor, mac, sensor_name, temperature, humidity, battery)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """, (now, dt_str, floor_key, mac, sensor_name, temperature, humidity, battery))
                conn.commit()

                self._last_record_per_floor[floor_key] = {
                    "timestamp": now,
                    "temperature": temperature,
                    "humidity": humidity,
                    "battery": battery
                }
                return True
            except Exception as e:
                return False
            finally:
                conn.close()

    def get_history(self, floor: Optional[str] = None, hours: float = 24.0, limit: int = 500) -> Dict[str, Any]:
        """Fetch historical points and stats for a specific floor or primary sensor."""
        now = time.time()
        start_ts = now - (hours * 3600.0)

        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                params = [start_ts]

                query = """
                    SELECT id, timestamp, datetime_str, floor, mac, sensor_name, temperature, humidity, battery
                    FROM climate_history
                    WHERE timestamp >= ?
                """
                if floor:
                    query += " AND floor = ?"
                    params.append(floor.lower().strip())

                query += " ORDER BY timestamp ASC"

                cur.execute(query, params)
                rows = cur.fetchall()

                # If no records for specific floor or period, fallback to check latest record
                points = []
                temps = []
                hums = []

                for r in rows:
                    t_val = r["temperature"]
                    h_val = r["humidity"]
                    p = {
                        "id": r["id"],
                        "timestamp": r["timestamp"],
                        "time": time.strftime("%H:%M", time.localtime(r["timestamp"])),
                        "datetime": r["datetime_str"],
                        "floor": r["floor"],
                        "sensor_name": r["sensor_name"],
                        "temperature": round(t_val, 1) if t_val is not None else None,
                        "humidity": round(h_val, 1) if h_val is not None else None,
                        "battery": r["battery"]
                    }
                    points.append(p)
                    if t_val is not None:
                        temps.append(t_val)
                    if h_val is not None:
                        hums.append(h_val)

                # Downsample if too many points for responsive frontend charting
                if len(points) > limit:
                    step = len(points) / limit
                    downsampled = [points[int(i * step)] for i in range(limit)]
                    if points[-1] not in downsampled:
                        downsampled.append(points[-1])
                    points = downsampled

                # Compute statistics
                stats = {
                    "count": len(rows),
                    "current_temp": round(temps[-1], 1) if temps else None,
                    "min_temp": round(min(temps), 1) if temps else None,
                    "max_temp": round(max(temps), 1) if temps else None,
                    "avg_temp": round(sum(temps) / len(temps), 1) if temps else None,
                    "current_hum": round(hums[-1], 0) if hums else None,
                    "min_hum": round(min(hums), 0) if hums else None,
                    "max_hum": round(max(hums), 0) if hums else None,
                    "avg_hum": round(sum(hums) / len(hums), 0) if hums else None,
                    "trend": "stable"
                }

                if len(temps) >= 4:
                    recent_avg = sum(temps[-max(1, len(temps)//4):]) / max(1, len(temps)//4)
                    earlier_avg = sum(temps[:max(1, len(temps)//4)]) / max(1, len(temps)//4)
                    diff = recent_avg - earlier_avg
                    if diff > 0.3:
                        stats["trend"] = "rising"
                    elif diff < -0.3:
                        stats["trend"] = "falling"
                    else:
                        stats["trend"] = "stable"

                return {
                    "success": True,
                    "floor": floor,
                    "hours": hours,
                    "points": points,
                    "stats": stats
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "points": [],
                    "stats": {}
                }
            finally:
                conn.close()

    def get_latest_by_floor(self) -> Dict[str, Dict[str, Any]]:
        """Get the latest reading for each known floor."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT c1.*
                    FROM climate_history c1
                    JOIN (
                        SELECT floor, MAX(timestamp) as max_ts
                        FROM climate_history
                        GROUP BY floor
                    ) c2 ON c1.floor = c2.floor AND c1.timestamp = c2.max_ts
                """)
                rows = cur.fetchall()
                res = {}
                for r in rows:
                    res[r["floor"]] = {
                        "timestamp": r["timestamp"],
                        "datetime": r["datetime_str"],
                        "temperature": r["temperature"],
                        "humidity": r["humidity"],
                        "battery": r["battery"],
                        "mac": r["mac"],
                        "sensor_name": r["sensor_name"]
                    }
                return res
            finally:
                conn.close()
