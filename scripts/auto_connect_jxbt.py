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
    adapter.SetDiscoveryFilter({"Transport": "bredr"})
    adapter.StartDiscovery()
except Exception:
    pass

start_time = time.time()
TIMEOUT = 300  # 5 minutes
connected = False

while time.time() - start_time < TIMEOUT:
    try:
        dev_obj = bus.get_object("org.bluez", DEV_PATH)
        props = dbus.Interface(dev_obj, "org.freedesktop.DBus.Properties")
        dev_iface = dbus.Interface(dev_obj, "org.bluez.Device1")

        # 1. Ensure Trusted
        try:
            if not bool(props.Get("org.bluez.Device1", "Trusted")):
                props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
        except Exception:
            pass

        # 2. Check if already connected
        try:
            if bool(props.Get("org.bluez.Device1", "Connected")):
                print("🎉 JX-BT ПІДКЛЮЧЕНО!")
                connected = True
                break
        except Exception:
            pass

        # 3. Try to Pair
        try:
            if not bool(props.Get("org.bluez.Device1", "Paired")):
                dev_iface.Pair()
                print("✓ Спарено з JX-BT!")
        except dbus.DBusException:
            pass

        # 4. Try Connect
        try:
            dev_iface.ConnectProfile(A2DP_SINK_UUID)
            print("🎉 ConnectProfile(A2DP) успішний!")
            connected = True
            break
        except dbus.DBusException:
            try:
                dev_iface.Connect()
                print("🎉 Connect() успішний!")
                connected = True
                break
            except Exception:
                pass

    except Exception:
        pass

    time.sleep(1.5)

try:
    adapter.StopDiscovery()
except Exception:
    pass

if connected:
    print("🔊 Налаштування PipeWire та запуск музики...")
    time.sleep(2)
    sink = f"bluez_output.{TARGET_MAC.replace(':', '_')}.1"
    subprocess.run(["pactl", "set-default-sink", sink], capture_output=True)
    subprocess.run(["pactl", "set-sink-volume", sink, "85%"], capture_output=True)
    # Start Hit FM via local API
    subprocess.run([
        "curl", "-s", "-X", "POST", "http://127.0.0.1:5000/api/radio/play",
        "-H", "Content-Type: application/json",
        "-d", f'{{"url": "https://online.hitfm.ua/HitFM", "name": "Hit FM", "mac": "{TARGET_MAC}"}}'
    ], capture_output=True)
    print("📻 Хіт FM запущено на JX-BT!")
    sys.exit(0)
else:
    print("❌ Таймаут 5 хв.")
    sys.exit(1)
