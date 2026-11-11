volatile unsigned long g_rf_edge_count = 0;
#include <SPI.h>
#include "rf_subsystem.h"
#include "gate_controller.h"

RfSubsystem rfSubsystem;

bool RfSubsystem::autoDetectPins() {
    uint8_t perms[6][3] = {
        {11, 12, 13}, // 0: MOSI=11, SCK=12, MISO=13 (стандарт)
        {12, 11, 13}, // 1: MOSI=12, SCK=11, MISO=13
        {13, 12, 11}, // 2: MOSI=13, SCK=12, MISO=11
        {11, 13, 12}, // 3: MOSI=11, SCK=13, MISO=12
        {12, 13, 11}, // 4: MOSI=12, SCK=13, MISO=11
        {13, 11, 12}  // 5: MOSI=13, SCK=11, MISO=12
    };

    uint8_t csn_options[2] = {10, 7};

    for (int c = 0; c < 2; c++) {
        uint8_t csn = csn_options[c];
        uint8_t gdo0 = (csn == 10) ? 7 : 10;

        pinMode(csn, OUTPUT);
        digitalWrite(csn, HIGH);

        for (int p = 0; p < 6; p++) {
            uint8_t mosi = perms[p][0];
            uint8_t sck  = perms[p][1];
            uint8_t miso = perms[p][2];

            pinMode(sck, OUTPUT);
            pinMode(mosi, OUTPUT);
            pinMode(miso, INPUT_PULLUP);
            digitalWrite(sck, LOW);
            digitalWrite(mosi, LOW);

            digitalWrite(csn, LOW);
            delayMicroseconds(50);

            uint8_t cmd = 0xF1;
            for (int i = 7; i >= 0; i--) {
                digitalWrite(mosi, (cmd >> i) & 1);
                delayMicroseconds(5);
                digitalWrite(sck, HIGH);
                delayMicroseconds(5);
                digitalWrite(sck, LOW);
                delayMicroseconds(5);
            }

            uint8_t ver = 0;
            for (int i = 7; i >= 0; i--) {
                digitalWrite(mosi, 0);
                delayMicroseconds(5);
                digitalWrite(sck, HIGH);
                delayMicroseconds(5);
                ver = (ver << 1) | digitalRead(miso);
                digitalWrite(sck, LOW);
                delayMicroseconds(5);
            }
            digitalWrite(csn, HIGH);
            delayMicroseconds(50);

            if (ver == 0x14 || ver == 0x34 || (ver > 0 && ver != 0xFF && (ver & 0x0F) == 0x04)) {
                pin_csn = csn;
                pin_mosi = mosi;
                pin_sck = sck;
                pin_miso = miso;
                pin_gdo0 = gdo0;
                Serial.printf("[AUTO_DETECT] CC1101 (VER=0x%02X) знайдено на CSN=%d, MOSI=%d, SCK=%d, MISO=%d, GDO0=%d\n",
                              ver, csn, mosi, sck, miso, gdo0);
                return true;
            }
        }
    }
    return false;
}

static void bitbangWrite(uint8_t csn, uint8_t sck, uint8_t mosi, uint8_t miso, uint8_t addr, uint8_t val) {
    pinMode(csn, OUTPUT);
    pinMode(sck, OUTPUT);
    pinMode(mosi, OUTPUT);
    pinMode(miso, INPUT_PULLUP);
    digitalWrite(sck, LOW);
    digitalWrite(csn, LOW);
    delayMicroseconds(5);
    uint32_t to = 2000;
    while (digitalRead(miso) && --to) delayMicroseconds(1);
    
    // Send addr
    for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, (addr >> i) & 1);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
    }
    // Send val
    for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, (val >> i) & 1);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
    }
    digitalWrite(csn, HIGH);
    delayMicroseconds(10);
}

static uint8_t bitbangRead(uint8_t csn, uint8_t sck, uint8_t mosi, uint8_t miso, uint8_t addr) {
    pinMode(csn, OUTPUT);
    pinMode(sck, OUTPUT);
    pinMode(mosi, OUTPUT);
    pinMode(miso, INPUT_PULLUP);
    digitalWrite(sck, LOW);
    digitalWrite(csn, LOW);
    delayMicroseconds(5);
    uint32_t to = 2000;
    while (digitalRead(miso) && --to) delayMicroseconds(1);
    
    uint8_t cmd = addr | 0x80;
    for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, (cmd >> i) & 1);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
    }
    uint8_t val = 0;
    for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, 0);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        val = (val << 1) | digitalRead(miso);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
    }
    digitalWrite(csn, HIGH);
    delayMicroseconds(10);
    return val;
}

static uint8_t bitbangStrobe(uint8_t csn, uint8_t sck, uint8_t mosi, uint8_t miso, uint8_t strobe) {
    pinMode(csn, OUTPUT);
    pinMode(sck, OUTPUT);
    pinMode(mosi, OUTPUT);
    pinMode(miso, INPUT_PULLUP);
    digitalWrite(sck, LOW);
    digitalWrite(csn, LOW);
    delayMicroseconds(5);
    uint32_t to = 2000;
    while (digitalRead(miso) && --to) delayMicroseconds(1);
    
    uint8_t status = 0;
    for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, (strobe >> i) & 1);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        status = (status << 1) | digitalRead(miso);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
    }
    digitalWrite(csn, HIGH);
    delayMicroseconds(10);
    return status;
}

static uint8_t bitbangReadStatus(uint8_t csn, uint8_t sck, uint8_t mosi, uint8_t miso, uint8_t addr) {
    pinMode(csn, OUTPUT);
    pinMode(sck, OUTPUT);
    pinMode(mosi, OUTPUT);
    pinMode(miso, INPUT_PULLUP);
    digitalWrite(sck, LOW);
    digitalWrite(csn, LOW);
    delayMicroseconds(5);
    uint32_t to = 2000;
    while (digitalRead(miso) && --to) delayMicroseconds(1);
    
    uint8_t cmd = addr | 0xC0;
    for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, (cmd >> i) & 1);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
    }
    uint8_t val = 0;
    for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, 0);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        val = (val << 1) | digitalRead(miso);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
    }
    digitalWrite(csn, HIGH);
    delayMicroseconds(10);
    return val;
}

static void ccSpiWrite(uint8_t csn, uint8_t miso, uint8_t addr, uint8_t val) {
    SPI.beginTransaction(SPISettings(500000, MSBFIRST, SPI_MODE0));
    digitalWrite(csn, LOW);
    uint32_t to = 2000;
    while (digitalRead(miso) && --to) delayMicroseconds(1);
    SPI.transfer(addr);
    SPI.transfer(val);
    digitalWrite(csn, HIGH);
    SPI.endTransaction();
    delayMicroseconds(5);
}

static uint8_t ccSpiRead(uint8_t csn, uint8_t miso, uint8_t addr) {
    SPI.beginTransaction(SPISettings(500000, MSBFIRST, SPI_MODE0));
    digitalWrite(csn, LOW);
    uint32_t to = 2000;
    while (digitalRead(miso) && --to) delayMicroseconds(1);
    SPI.transfer(addr | 0x80);
    uint8_t val = SPI.transfer(0x00);
    digitalWrite(csn, HIGH);
    SPI.endTransaction();
    delayMicroseconds(5);
    return val;
}

static uint8_t ccSpiStrobe(uint8_t csn, uint8_t miso, uint8_t cmd) {
    SPI.beginTransaction(SPISettings(500000, MSBFIRST, SPI_MODE0));
    digitalWrite(csn, LOW);
    uint32_t to = 2000;
    while (digitalRead(miso) && --to) delayMicroseconds(1);
    uint8_t status = SPI.transfer(cmd);
    digitalWrite(csn, HIGH);
    SPI.endTransaction();
    delayMicroseconds(5);
    return status;
}

static uint8_t ccSpiReadStatus(uint8_t csn, uint8_t miso, uint8_t addr) {
    SPI.beginTransaction(SPISettings(500000, MSBFIRST, SPI_MODE0));
    digitalWrite(csn, LOW);
    uint32_t to = 2000;
    while (digitalRead(miso) && --to) delayMicroseconds(1);
    SPI.transfer(addr | 0xC0);
    uint8_t val = SPI.transfer(0x00);
    digitalWrite(csn, HIGH);
    SPI.endTransaction();
    delayMicroseconds(5);
    return val;
}

static int ccGetRssi(uint8_t csn, uint8_t miso) {
    int rssi = ccSpiReadStatus(csn, miso, 0x34);
    if (rssi >= 128) return (rssi - 256) / 2 - 74;
    return (rssi / 2) - 74;
}

void RfSubsystem::resetAndConfigure() {
    pinMode(pin_csn, OUTPUT);
    digitalWrite(pin_csn, HIGH);
    pinMode(pin_sck, OUTPUT);
    pinMode(pin_mosi, OUTPUT);
    pinMode(pin_miso, INPUT_PULLUP);

    // CC1101 Manual Reset per TI datasheet
    digitalWrite(pin_csn, LOW);
    delayMicroseconds(10);
    digitalWrite(pin_csn, HIGH);
    delayMicroseconds(50);
    digitalWrite(pin_csn, LOW);
    uint32_t to = 2000;
    while (digitalRead(pin_miso) && --to) delayMicroseconds(1);
    
    // Strobe SRES (0x30)
    bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x30);
    delay(25); // Час на внутрішній ресет та старт кварцу

    bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x36); // SIDLE
    delay(5);

    // Запис регістрів 433.92 МГц ASK/OOK (SmartRF Studio)
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x00, 0x0D); // IOCFG2: GDO2 = Serial Data Out
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x02, 0x0D); // IOCFG0: GDO0 = Serial Data Out
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x08, 0x32); // PKTCTRL0: Asynchronous serial mode
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x07, 0x04); // PKTCTRL1
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x0B, 0x06); // FSCTRL1: 152 kHz IF
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x0C, 0x00); // FSCTRL0
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x0D, 0x10); // FREQ2: 433.92 MHz
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x0E, 0xB0); // FREQ1
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x0F, 0x71); // FREQ0
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x10, 0x87); // MDMCFG4: BW 325 kHz
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x11, 0x32); // MDMCFG3
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x12, 0x30); // MDMCFG2: ASK/OOK, no sync mode
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x13, 0x22); // MDMCFG1
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x14, 0xF8); // MDMCFG0
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x15, 0x00); // DEVIATN
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x17, 0x3F); // MCSM1: stay in RX
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x18, 0x18); // MCSM0: autocal
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x19, 0x1D); // FOCCFG
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x1A, 0x1C); // BSCFG
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x1B, 0xC7); // AGCCTRL2: Max LNA gain
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x1C, 0x00); // AGCCTRL1
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x1D, 0xB2); // AGCCTRL0
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x21, 0xB6); // FREND1
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x22, 0x11); // FREND0: PA power index 1 (ASK)
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x23, 0xEA); // FSCAL3
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x24, 0x2A); // FSCAL2
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x25, 0x00); // FSCAL1
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x26, 0x1F); // FSCAL0
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x29, 0x59); // FSTEST
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x2C, 0x81); // TEST2
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x2D, 0x35); // TEST1
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x2E, 0x09); // TEST0

    // PA Table: +10 dBm
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x3E, 0xC0);
    delay(5);

    // Калібрування
    bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x33); // SCAL
    delay(5);
}

void RfSubsystem::init() {
    bool ccFound = autoDetectPins();

    if (ccFound) {
        resetAndConfigure();
        enableReceive();
        mySwitch.setReceiveTolerance(80);
        cc1101Available = true;
        gateCtrl.setLedColor(0, 160, 255);
        Serial.printf("[CC1101] Модуль 433.92 МГц налаштовано напряму (CSN=%d, MOSI=%d, SCK=%d, MISO=%d, GDO0=%d).\n",
                      pin_csn, pin_mosi, pin_sck, pin_miso, pin_gdo0);
    } else {
        cc1101Available = false;
        gateCtrl.setLedColor(40, 0, 0);
        Serial.println("[CC1101] Помилка: CC1101 не відповідає.");
    }
}

void RfSubsystem::enableReceive() {
    pinMode(pin_gdo0, INPUT);
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x02, 0x0D); // GDO0 = Serial Data Output
    bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x36); // SIDLE
    delayMicroseconds(500);
    bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x34); // SRX
    delayMicroseconds(800);
    mySwitch.enableReceive(digitalPinToInterrupt(pin_gdo0));
}

void RfSubsystem::disableReceive() {
    mySwitch.disableReceive();
}

void RfSubsystem::transmitCode(unsigned long code, unsigned int repeats) {
    if (!cc1101Available) return;
    disableReceive();

    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x02, 0x2E); // GDO0 = High-Z Input
    pinMode(pin_gdo0, OUTPUT);
    digitalWrite(pin_gdo0, LOW);

    bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x36); // SIDLE
    delayMicroseconds(500);
    bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x35); // STX
    delayMicroseconds(800);

    mySwitch.enableTransmit(pin_gdo0);
    mySwitch.setPulseLength(RF_PULSE_LENGTH);
    mySwitch.setRepeatTransmit(repeats);
    mySwitch.send(code, 24);
    mySwitch.disableTransmit();

    enableReceive();

    Serial.printf("[RF433] Сигнал 0x%lX (%lu) надіслано в ефір (повторів=%u)\n", code, code, repeats);
}

void RfSubsystem::transmitLight(bool state) {
    unsigned long code = state ? RF_CODE_LIGHT_ON : RF_CODE_LIGHT_OFF;
    transmitCode(code, 10);
    Serial.printf("[RF433] Сигнал світла %s надіслано в ефір (код: 0x%lX)\n", state ? "ON" : "OFF", code);
}

void RfSubsystem::setCarrier(bool enable) {
    if (!cc1101Available) return;
    disableReceive();
    if (enable) {
        bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x02, 0x2E);
        pinMode(pin_gdo0, OUTPUT);
        digitalWrite(pin_gdo0, HIGH);
        bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x36); // SIDLE
        delay(1);
        bitbangStrobe(pin_csn, pin_sck, pin_mosi, pin_miso, 0x35); // STX
        gateCtrl.setLedColor(180, 0, 0);
        Serial.println("RESP:{\"status\":\"ok\",\"carrier\":true,\"freq\":433.92}");
    } else {
        pinMode(pin_gdo0, INPUT);
        enableReceive();
        gateCtrl.setLedColor(0, 160, 255);
        Serial.println("RESP:{\"status\":\"ok\",\"carrier\":false}");
    }
}

void RfSubsystem::startPairing(unsigned long code, int durationSec) {
    rfPairingCode = code;
    rfPairingActive = true;
    rfPairingEndTime = millis() + (unsigned long)durationSec * 1000UL;
    lastPairSendTime = 0;
}

void RfSubsystem::stopPairing() {
    rfPairingActive = false;
    gateCtrl.setLedColor(0, 160, 255);
}

void RfSubsystem::startLearning(int durationSec) {
    rfLearningActive = true;
    rfLearningEndTime = millis() + (unsigned long)durationSec * 1000UL;
    gateCtrl.setLedColor(140, 0, 200);
}

void RfSubsystem::stopLearning() {
    rfLearningActive = false;
    gateCtrl.setLedColor(0, 160, 255);
}

int RfSubsystem::getLearningRemainingSec() const {
    if (!rfLearningActive) return 0;
    long rem = (long)((rfLearningEndTime - millis()) / 1000);
    return rem > 0 ? (int)rem : 0;
}

String RfSubsystem::getDiagnosticsJson() {
    // Тест біт-бенг запису та читання
    bitbangWrite(pin_csn, pin_sck, pin_mosi, pin_miso, 0x06, 0x42); // PKTLEN = 0x42
    uint8_t bb_tw = bitbangRead(pin_csn, pin_sck, pin_mosi, pin_miso, 0x06);

    byte ver = bitbangReadStatus(pin_csn, pin_sck, pin_mosi, pin_miso, 0x31);
    byte marc = bitbangReadStatus(pin_csn, pin_sck, pin_mosi, pin_miso, 0x35) & 0x1F;
    int rssi = -138;
    int gdo0 = digitalRead(pin_gdo0);
    unsigned long edges = g_rf_edge_count;

    byte freq2 = bitbangRead(pin_csn, pin_sck, pin_mosi, pin_miso, 0x0D);
    byte freq1 = bitbangRead(pin_csn, pin_sck, pin_mosi, pin_miso, 0x0E);
    byte freq0 = bitbangRead(pin_csn, pin_sck, pin_mosi, pin_miso, 0x0F);
    byte mdmcfg2 = bitbangRead(pin_csn, pin_sck, pin_mosi, pin_miso, 0x12);
    byte pktctrl0 = bitbangRead(pin_csn, pin_sck, pin_mosi, pin_miso, 0x08);
    byte iocfg0 = bitbangRead(pin_csn, pin_sck, pin_mosi, pin_miso, 0x02);

    char buf[256];
    snprintf(buf, sizeof(buf),
             "{\"diag\":\"spi_active\",\"ver\":\"0x%02X\",\"marc\":%d,\"rssi\":%d,\"gdo0\":%d,\"edges\":%lu,\"bb_tw\":%d,\"f\":[%d,%d,%d],\"m2\":%d,\"pk0\":%d,\"io0\":%d,\"csn\":%d,\"mosi\":%d,\"sck\":%d,\"miso\":%d}",
             ver, marc, rssi, gdo0, edges, (int)bb_tw, freq2, freq1, freq0, mdmcfg2, pktctrl0, iocfg0, pin_csn, pin_mosi, pin_sck, pin_miso);
    return String(buf);
}

void RfSubsystem::update() {
    unsigned long now = millis();

    // 1. Безперервне сполучення (Pairing Mode)
    if (rfPairingActive) {
        if (now < rfPairingEndTime) {
            if (now - lastPairSendTime >= 120) {
                lastPairSendTime = now;
                transmitCode(rfPairingCode, 4);
                gateCtrl.setLedColor(140, 0, 140);
            }
        } else {
            stopPairing();
            Serial.println("[RF_PAIR] Режим безперервного сполучення завершено (таймаут).");
        }
    }

    // 2. Таймаут навчання
    if (rfLearningActive && now > rfLearningEndTime) {
        stopLearning();
        Serial.println("[RF_LEARN] Режим навчання завершено (таймаут).");
    }

    if (!cc1101Available) return;

    // 3. Захист від переповнення RX FIFO (раз на 10 сек)
    if (!rfPairingActive && (now - lastRxKeepAlive >= 10000)) {
        lastRxKeepAlive = now;
        byte marc = ccSpiReadStatus(pin_csn, pin_miso, 0x35) & 0x1F;
        // 0x11 = RXFIFO_OVERFLOW, 0x16 = TXFIFO_UNDERFLOW
        if (marc == 0x11 || marc == 0x16) {
            ccSpiStrobe(pin_csn, pin_miso, 0x36); // SIDLE
            ccSpiStrobe(pin_csn, pin_miso, 0x3A); // SFRX
            enableReceive();
        }
    }

    // 4. Декодування через RCSwitch
    if (mySwitch.available()) {
        unsigned long val = mySwitch.getReceivedValue();
        unsigned int bits = mySwitch.getReceivedBitlength();
        unsigned int proto = mySwitch.getReceivedProtocol();
        unsigned int delayVal = mySwitch.getReceivedDelay();
        mySwitch.resetAvailable();
        g_rf_raw_capture.ready = false;

        if (val != 0) {
            Serial.printf("[RF_RX] Код: %lu (0x%lX) | Біти: %u | Протокол: %u | Затримка: %u\n", val, val, bits, proto, delayVal);
            if (rfLearningActive) {
                Serial.printf("[RF_LEARN] {\"code\":%lu,\"hex\":\"0x%lX\",\"bits\":%u,\"proto\":%u,\"delay\":%u,\"mode\":\"rcswitch\"}\n",
                              val, val, bits, proto, delayVal);
            }
            gateCtrl.setLedColor(0, 200, 0); // Зелений
            currentLedState = 2;
            ledResetTime = now + 1500;
        }
    }
    // 5. Адаптивне декодування raw пульсів
    else if (g_rf_raw_capture.ready) {
        unsigned int count = g_rf_raw_capture.count;
        unsigned int sync = g_rf_raw_capture.sync;
        unsigned long decodedCode = 0;
        unsigned int decodedBits = 0;
        bool decodeSuccess = false;

        if (count >= 16) {
            bool validPattern = true;
            for (unsigned int i = 1; i + 1 < count; i += 2) {
                unsigned int t1 = g_rf_raw_capture.timings[i];
                unsigned int t2 = g_rf_raw_capture.timings[i+1];
                unsigned int longer = (t1 > t2) ? t1 : t2;
                unsigned int shorter = (t1 > t2) ? t2 : t1;
                if (shorter < 80 || shorter > 950 || longer < 300 || longer > 2800 || (longer / shorter < 2)) {
                    validPattern = false;
                    break;
                }
                bool bitVal = (t1 > t2);
                decodedCode = (decodedCode << 1) | (bitVal ? 1 : 0);
                decodedBits++;
                if (decodedBits >= 32) break;
            }
            if (validPattern && decodedBits >= 12) {
                decodeSuccess = true;
            }
        }

        if (decodeSuccess) {
            Serial.printf("[RF_RX_RAW] Розпізнано: 0x%lX (%lu) | Біти: %u | Sync: %u us\n", decodedCode, decodedCode, decodedBits, sync);
            gateCtrl.setLedColor(0, 200, 0);
            currentLedState = 2;
            ledResetTime = now + 1500;
        } else if (rfLearningActive && count >= 16) {
            Serial.printf("[RF_RX_RAW] Спіймано імпульси в режимі навчання (%u імпульсів, sync=%u us)\n", count, sync);
        }
        g_rf_raw_capture.ready = false;
    }

    // 6. Скидання LED після індикації
    if (ledResetTime != 0 && now >= ledResetTime) {
        ledResetTime = 0;
        currentLedState = 0;
        if (!rfLearningActive && !rfPairingActive) {
            gateCtrl.setLedColor(0, 160, 255);
        }
    }
}