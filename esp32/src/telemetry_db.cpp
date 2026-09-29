#include "telemetry_db.h"

TelemetryDB telemetryDB;

TelemetryDB::TelemetryDB() : db(nullptr), is_open(false), last_vacuum_timestamp(0), pending_inserts(0) {}

TelemetryDB::~TelemetryDB() {
    close();
}

bool TelemetryDB::init(const char* db_path) {
    if (is_open) {
        close();
    }

    int rc = sqlite3_open(db_path, &db);
    if (rc != SQLITE_OK) {
        Serial.printf("[TelemetryDB] Failed to open SQLite database: %s\n", sqlite3_errmsg(db));
        if (db) {
            sqlite3_close(db);
            db = nullptr;
        }
        is_open = false;
        return false;
    }

    // 1. Performance and Integrity Pragmas
    sqlite3_exec(db, "PRAGMA journal_mode=WAL;", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA synchronous=NORMAL;", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA cache_size=1000;", NULL, NULL, NULL);

    // 2. Create tables and indices
    const char* schema_sql =
        "CREATE TABLE IF NOT EXISTS climate_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp REAL NOT NULL, "
        "datetime_str TEXT NOT NULL, "
        "floor TEXT NOT NULL, "
        "mac TEXT, "
        "sensor_name TEXT, "
        "temperature REAL, "
        "humidity REAL, "
        "battery REAL);"
        "CREATE INDEX IF NOT EXISTS idx_climate_timestamp ON climate_history(timestamp);"
        "CREATE INDEX IF NOT EXISTS idx_climate_floor_ts ON climate_history(floor, timestamp);";

    char* err_msg = nullptr;
    rc = sqlite3_exec(db, schema_sql, NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        Serial.printf("[TelemetryDB] SQL Schema Error: %s\n", err_msg ? err_msg : "unknown");
        sqlite3_free(err_msg);
        close();
        return false;
    }

    is_open = true;
    Serial.println("[TelemetryDB] SQLite initialized in WAL mode with synchronous=NORMAL.");

    // Initial check for cleanup on boot
    cleanOldRecords(7);
    return true;
}

void TelemetryDB::close() {
    if (db && is_open) {
        sqlite3_close(db);
        db = nullptr;
        is_open = false;
        Serial.println("[TelemetryDB] Database connection closed.");
    }
}

bool TelemetryDB::insertRecord(const TelemetryRecord& rec) {
    if (!is_open || !db) return false;

    const char* insert_sql =
        "INSERT INTO climate_history (timestamp, datetime_str, floor, mac, sensor_name, temperature, humidity, battery) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db, insert_sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        Serial.printf("[TelemetryDB] Prepare failed: %s\n", sqlite3_errmsg(db));
        return false;
    }

    sqlite3_bind_double(stmt, 1, rec.timestamp);
    sqlite3_bind_text(stmt, 2, rec.datetime_str, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, rec.floor, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 4, rec.mac, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 5, rec.sensor_name, -1, SQLITE_STATIC);
    sqlite3_bind_double(stmt, 6, rec.temperature);
    sqlite3_bind_double(stmt, 7, rec.humidity);
    sqlite3_bind_double(stmt, 8, rec.battery);

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);

    if (rc != SQLITE_DONE) {
        Serial.printf("[TelemetryDB] Insert failed: %s\n", sqlite3_errmsg(db));
        return false;
    }

    pending_inserts++;
    if (pending_inserts >= 100) {
        vacuumIfNeeded();
        pending_inserts = 0;
    }
    return true;
}

bool TelemetryDB::insertBatch(const std::vector<TelemetryRecord>& records) {
    if (!is_open || !db || records.empty()) return false;

    const char* insert_sql =
        "INSERT INTO climate_history (timestamp, datetime_str, floor, mac, sensor_name, temperature, humidity, battery) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?);";

    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db, insert_sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        Serial.printf("[TelemetryDB] Prepare failed: %s\n", sqlite3_errmsg(db));
        return false;
    }

    // Begin Transaction
    char* err_msg = nullptr;
    rc = sqlite3_exec(db, "BEGIN TRANSACTION;", NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        Serial.printf("[TelemetryDB] BEGIN TRANSACTION failed: %s\n", err_msg ? err_msg : "unknown");
        sqlite3_free(err_msg);
        sqlite3_finalize(stmt);
        return false;
    }

    int batch_count = 0;
    for (size_t i = 0; i < records.size(); ++i) {
        const auto& rec = records[i];

        sqlite3_reset(stmt);
        sqlite3_bind_double(stmt, 1, rec.timestamp);
        sqlite3_bind_text(stmt, 2, rec.datetime_str, -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, rec.floor, -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 4, rec.mac, -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 5, rec.sensor_name, -1, SQLITE_STATIC);
        sqlite3_bind_double(stmt, 6, rec.temperature);
        sqlite3_bind_double(stmt, 7, rec.humidity);
        sqlite3_bind_double(stmt, 8, rec.battery);

        rc = sqlite3_step(stmt);
        if (rc != SQLITE_DONE) {
            Serial.printf("[TelemetryDB] Error at row %d: %s. Rolling back.\n", (int)i, sqlite3_errmsg(db));
            sqlite3_finalize(stmt);
            sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
            return false;
        }

        batch_count++;
        // Commit and reopen transaction every 100 records
        if (batch_count >= 100 && (i + 1) < records.size()) {
            sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
            sqlite3_exec(db, "BEGIN TRANSACTION;", NULL, NULL, NULL);
            batch_count = 0;
        }
    }

    sqlite3_finalize(stmt);

    // Final Commit
    rc = sqlite3_exec(db, "COMMIT;", NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        Serial.printf("[TelemetryDB] COMMIT failed: %s. Executing ROLLBACK.\n", err_msg ? err_msg : "unknown");
        sqlite3_free(err_msg);
        sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
        return false;
    }

    return true;
}

int TelemetryDB::cleanOldRecords(int days_to_keep) {
    if (!is_open || !db) return 0;

    // Cutoff: current timestamp minus (days_to_keep * 86400 seconds)
    // In ESP32, if NTP is synchronized, time(nullptr) is epoch seconds
    time_t now = time(nullptr);
    if (now < 1700000000) { // NTP not yet synced
        return 0;
    }

    double cutoff_ts = (double)(now - (days_to_keep * 86400));
    char delete_sql[128];
    snprintf(delete_sql, sizeof(delete_sql), "DELETE FROM climate_history WHERE timestamp < %f;", cutoff_ts);

    char* err_msg = nullptr;
    int rc = sqlite3_exec(db, delete_sql, NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        Serial.printf("[TelemetryDB] Delete old records failed: %s\n", err_msg ? err_msg : "unknown");
        sqlite3_free(err_msg);
        return -1;
    }

    int changes = sqlite3_changes(db);
    if (changes > 0) {
        Serial.printf("[TelemetryDB] Cleaned %d records older than %d days.\n", changes, days_to_keep);
    }
    return changes;
}

bool TelemetryDB::vacuum() {
    if (!is_open || !db) return false;

    Serial.println("[TelemetryDB] Executing VACUUM to reclaim space and defragment database...");
    char* err_msg = nullptr;
    int rc = sqlite3_exec(db, "VACUUM;", NULL, NULL, &err_msg);
    if (rc != SQLITE_OK) {
        Serial.printf("[TelemetryDB] VACUUM failed: %s\n", err_msg ? err_msg : "unknown");
        sqlite3_free(err_msg);
        return false;
    }

    last_vacuum_timestamp = time(nullptr);
    Serial.println("[TelemetryDB] VACUUM completed successfully.");
    return true;
}

bool TelemetryDB::vacuumIfNeeded(unsigned long max_interval_seconds) {
    time_t now = time(nullptr);
    if (now < 1700000000) return false;

    if (last_vacuum_timestamp == 0) {
        last_vacuum_timestamp = now;
        return false;
    }

    if ((unsigned long)(now - last_vacuum_timestamp) >= max_interval_seconds) {
        cleanOldRecords(7);
        return vacuum();
    }
    return false;
}
