#!/usr/bin/env python3
"""
Smart Garage - SQLite Database Optimization & Analysis Tool
Optimizes `devices/telemetry.db`:
- Executes ANALYZE to update query planner statistics
- Executes VACUUM to defragment and reclaim unused disk pages
- Prints comprehensive DB statistics (file size, table counts, indices)
"""
import os
import sys
import time
import sqlite3
import argparse
from pathlib import Path


def format_bytes(size: float) -> str:
    """Format bytes into human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(size) < 1024.0:
            return f"{size:3.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def get_db_stats(cursor: sqlite3.Cursor, db_path: Path) -> dict:
    """Collect internal database statistics."""
    stats = {}
    stats["file_size"] = db_path.stat().st_size if db_path.exists() else 0

    # Page size and counts
    cursor.execute("PRAGMA page_size;")
    stats["page_size"] = cursor.fetchone()[0]

    cursor.execute("PRAGMA page_count;")
    stats["page_count"] = cursor.fetchone()[0]

    cursor.execute("PRAGMA freelist_count;")
    stats["freelist_count"] = cursor.fetchone()[0]

    cursor.execute("PRAGMA journal_mode;")
    stats["journal_mode"] = cursor.fetchone()[0]

    cursor.execute("PRAGMA synchronous;")
    stats["synchronous"] = cursor.fetchone()[0]

    # Tables and row counts
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row[0] for row in cursor.fetchall()]
    stats["tables"] = {}

    for tbl in tables:
        cursor.execute(f"SELECT COUNT(*) FROM \"{tbl}\";")
        count = cursor.fetchone()[0]

        # Check date range if climate_history
        time_range = None
        if tbl == "climate_history":
            cursor.execute(f"SELECT MIN(datetime_str), MAX(datetime_str) FROM \"{tbl}\";")
            row = cursor.fetchone()
            if row and row[0]:
                time_range = f"[{row[0]} -> {row[1]}]"

        stats["tables"][tbl] = {"count": count, "range": time_range}

    # Indices
    cursor.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%';")
    stats["indices"] = cursor.fetchall()

    return stats


def optimize_database(db_path: Path, verbose: bool = True):
    """Run ANALYZE and VACUUM on database."""
    if not db_path.exists():
        print(f"[!] Database file does not exist: {db_path}")
        return

    print("==========================================================")
    print(f" [SmartGarage] Оптимізація бази даних: {db_path.name}")
    print(f" Шлях: {db_path.resolve()}")
    print("==========================================================")

    # Initial connection
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Pre-optimization statistics
    pre_stats = get_db_stats(cursor, db_path)
    print("\n--- [1] СТАН ДО ОПТИМІЗАЦІЇ ---")
    print(f"• Розмір файлу:      {format_bytes(pre_stats['file_size'])}")
    print(f"• Режим журналу:     {pre_stats['journal_mode']}")
    print(f"• Кількість сторінок: {pre_stats['page_count']} (Розмір сторінки: {pre_stats['page_size']}B)")
    print(f"• Вільних сторінок:  {pre_stats['freelist_count']}")

    print("\nТаблиці та записи:")
    for tbl, info in pre_stats["tables"].items():
        range_str = f" {info['range']}" if info['range'] else ""
        print(f"  • {tbl}: {info['count']} записів{range_str}")

    print("\nІндекси:")
    for idx_name, tbl_name, sql in pre_stats["indices"]:
        print(f"  • {idx_name} (на таблиці {tbl_name})")

    # 1. Run Integrity Check
    print("\n--- [2] ПЕРЕВІРКА ЦІЛІСНОСТІ (INTEGRITY CHECK) ---")
    cursor.execute("PRAGMA integrity_check;")
    check_result = cursor.fetchone()[0]
    print(f"• Результат integrity_check: {check_result}")

    # 2. Run ANALYZE
    print("\n--- [3] ВИКОНАННЯ ANALYZE ---")
    t0 = time.time()
    cursor.execute("ANALYZE;")
    conn.commit()
    print(f"✓ ANALYZE виконано успішно за {time.time() - t0:.3f}с (оновлено статистику sqlite_stat1).")

    # 3. Run VACUUM
    print("\n--- [4] ВИКОНАННЯ VACUUM ---")
    t0 = time.time()
    # VACUUM cannot be run inside a transaction
    cursor.execute("VACUUM;")
    conn.commit()
    print(f"✓ VACUUM виконано успішно за {time.time() - t0:.3f}с (дефрагментація та звільнення сторінок).")

    # 4. PRAGMA optimize
    cursor.execute("PRAGMA optimize;")
    conn.commit()
    print("✓ PRAGMA optimize виконано.")

    # Post-optimization statistics
    post_stats = get_db_stats(cursor, db_path)
    conn.close()

    freed_bytes = pre_stats["file_size"] - post_stats["file_size"]
    print("\n==========================================================")
    print(" [РЕЗУЛЬТАТИ ОПТИМІЗАЦІЇ]")
    print("==========================================================")
    print(f"• Початковий розмір: {format_bytes(pre_stats['file_size'])}")
    print(f"• Фінальний розмір:   {format_bytes(post_stats['file_size'])}")
    print(f"• Звільнено місця:    {format_bytes(max(0, freed_bytes))}")
    print(f"• Вільних сторінок:   {post_stats['freelist_count']} (було {pre_stats['freelist_count']})")
    print("✓ Базу даних успішно оптимізовано для швидких вибірок!")
    print("==========================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optimize SQLite database for Smart Garage")
    default_db = Path(__file__).resolve().parent.parent / "devices" / "telemetry.db"
    parser.add_argument("--db", type=str, default=str(default_db), help="Path to SQLite database")
    args = parser.parse_args()

    optimize_database(Path(args.db))
