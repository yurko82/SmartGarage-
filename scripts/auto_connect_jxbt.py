#!/usr/bin/env python3
"""
Continuous auto-connection script for JX-BT (41:42:62:69:51:9B).
Keeps trying to pair & connect in background.
As soon as connection succeeds, automatically configures PipeWire and launches Hit FM!
"""
import sys
import time
import subprocess
import dbus

TARGET_MAC = "41:42:62:69:51:9B"
TARGET_NAME = "JX-BT"
A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"
DEV_PATH = f"/org/bluez/hci0/dev_{TARGET_MAC.replace(':', '_')}"

bus = dbus.SystemBus()
adapter_obj = bus.get_object("org.bluez", "/org/bluez/hci0")
adapter = dbus.Interface(adapter_obj, "org.bluez.Adapter1")

print(f"📡 Авто-підключення до {TARGET_NAME} ({TARGET_MAC}) активне...")
try:
    adapter.SetDiscoveryFilter({})
    adapter.StartDiscovery()
except Exception:
    pass

start_time = time.time()
TIMEOUT = 900  # 15 minutes
connected = False
attempt = 0

while time.time() - start_time < TIMEOUT:
    attempt += 1
    target_path = None
    try:
        # Periodic discovery refresh every 10 seconds
        if attempt % 5 == 1:
            try:
                adapter.StartDiscovery()
            except Exception:
                pass

        # 1. Search DBus managed objects for matching MAC or Name
        manager = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = manager.GetManagedObjects()
        for path, ifaces in objects.items():
            if "org.bluez.Device1" in ifaces:
                dev = ifaces["org.bluez.Device1"]
                addr = str(dev.get("Address", "")).upper()
                name = str(dev.get("Name", dev.get("Alias", ""))).lower()
                if TARGET_MAC in addr or TARGET_NAME.lower() in name or "jx-bt" in name or "jxbt" in name:
                    target_path = path
                    break

        if not target_path:
            target_path = DEV_PATH

        dev_obj = bus.get_object("org.bluez", target_path)
        props = dbus.Interface(dev_obj, "org.freedesktop.DBus.Properties")
        dev_iface = dbus.Interface(dev_obj, "org.bluez.Device1")

        # 2. Ensure Trusted
        try:
            if not bool(props.Get("org.bluez.Device1", "Trusted")):
                props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
        except Exception:
            pass

        # 3. Check if already connected
        try:
            if bool(props.Get("org.bluez.Device1", "Connected")):
                print(f"[{time.strftime('%H:%M:%S')}] 🎉 JX-BT ПІДКЛЮЧЕНО!")
                connected = True
                break
        except Exception:
            pass

        # 4. Connect / Pair attempt
        try:
            dev_iface.Connect()
            print(f"[{time.strftime('%H:%M:%S')}] 🎉 Connect() успішний!")
            connected = True
            break
        except dbus.DBusException:
            try:
                if not bool(props.Get("org.bluez.Device1", "Paired")):
                    dev_iface.Pair()
                    print(f"[{time.strftime('%H:%M:%S')}] ✓ Спарено з JX-BT!")
            except Exception:
                pass

    except Exception:
        pass

    time.sleep(2.0)

try:
    adapter.StopDiscovery()
except Exception:
    pass

if connected:
    print(f"[{time.strftime('%H:%M:%S')}] 🔊 Налаштування PipeWire та аудіоканалу...")
    time.sleep(2)
    sink = f"bluez_output.{TARGET_MAC.replace(':', '_')}.1"
    subprocess.run(["pactl", "set-default-sink", sink], capture_output=True)
    subprocess.run(["pactl", "set-sink-volume", sink, "80%"], capture_output=True)
    # Inform SmartGarage core & trigger radio playback
    try:
        subprocess.run(["curl", "-s", "-X", "POST", "http://127.0.0.1:5000/api/speaker/connect", "-H", "Content-Type: application/json", "-d", f'{{"mac": "{TARGET_MAC}"}}'], capture_output=True)
        time.sleep(1)
        subprocess.run([
            "curl", "-s", "-X", "POST", "http://127.0.0.1:5000/api/radio/play",
            "-H", "Content-Type: application/json",
            "-d", f'{{"url": "https://online.hitfm.ua/HitFM", "name": "Hit FM", "mac": "{TARGET_MAC}"}}'
        ], capture_output=True)
    except Exception:
        pass
    print("📻 JX-BT готовий, музику (Hit FM) запущено!")
    sys.exit(0)
else:
    print("❌ Таймаут очікування.")
    sys.exit(1)
