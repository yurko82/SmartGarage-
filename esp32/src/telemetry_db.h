#ifndef TELEMETRY_DB_H
#define TELEMETRY_DB_H

#include <Arduino.h>
#include <sqlite3.h>
#include <vector>

struct TelemetryRecord {
    float timestamp;
    char datetime_str[24];
    char floor[16];
    char mac[20];
    char sensor_name[32];
    float temperature;
    float humidity;
    float battery;
};

class TelemetryDB {
private:
    sqlite3* db;
    bool is_open;
    unsigned long last_vacuum_timestamp;
    int pending_inserts;

public:
    TelemetryDB();
    ~TelemetryDB();

    bool init(const char* db_path = "/spiffs/telemetry.db");
    void close();

    bool insertRecord(const TelemetryRecord& rec);
    bool insertBatch(const std::vector<TelemetryRecord>& records);
    
    // Automatic maintenance
    int cleanOldRecords(int days_to_keep = 7);
    bool vacuumIfNeeded(unsigned long max_interval_seconds = 7 * 86400);
    bool vacuum();

    bool isOpen() const { return is_open; }
};

extern TelemetryDB telemetryDB;

#endif // TELEMETRY_DB_H
