#!/usr/bin/env python3
"""Script to automatically discover, trust, pair, and connect JX-BT speaker."""
import sys
import time
import subprocess
import dbus
from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop

TARGET_MAC = "41:42:62:69:51:9B"
TARGET_NAME = "JX-BT"
A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"

DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()
adapter_obj = bus.get_object("org.bluez", "/org/bluez/hci0")
adapter = dbus.Interface(adapter_obj, "org.bluez.Adapter1")

print(f"📡 Setting auto discovery filter for {TARGET_NAME} ({TARGET_MAC})...")
try:
    adapter.SetDiscoveryFilter({})
except Exception as e:
    print(f"Warning setting filter: {e}")

loop = GLib.MainLoop()
connected = False

def do_connect(path):
    global connected
    print(f"\n🎯 Target detected on DBus: {path}")
    dev_obj = bus.get_object("org.bluez", path)
    props = dbus.Interface(dev_obj, "org.freedesktop.DBus.Properties")
    
    # 1. Trust
    try:
        props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
        print("  ✓ Device marked as Trusted")
    except Exception as e:
        print(f"  ✗ Trust error: {e}")

    dev_iface = dbus.Interface(dev_obj, "org.bluez.Device1")

    # 2. Pair if not paired
    try:
        is_paired = bool(props.Get("org.bluez.Device1", "Paired"))
        if not is_paired:
            print("  ⏳ Attempting Pair()...")
            dev_iface.Pair()
            print("  ✓ Paired successfully!")
    except Exception as e:
        print(f"  ℹ Pair notice: {e}")

    # 3. Connect A2DP profile
    print("  ⏳ Attempting ConnectProfile(A2DP)...")
    try:
        dev_iface.ConnectProfile(A2DP_SINK_UUID)
        print("  ✓ ConnectProfile(A2DP) successful!")
        connected = True
        loop.quit()
        return
    except Exception as e:
        print(f"  ℹ ConnectProfile: {e}")

    # 4. Fallback generic Connect
    print("  ⏳ Attempting generic Connect()...")
    try:
        dev_iface.Connect()
        print("  ✓ Connected successfully!")
        connected = True
        loop.quit()
        return
    except Exception as e:
        print(f"  ✗ Connect: {e}")

def on_interfaces_added(path, interfaces):
    if "org.bluez.Device1" in interfaces:
        dev = interfaces["org.bluez.Device1"]
        addr = str(dev.get("Address", "")).upper()
        name = str(dev.get("Name", dev.get("Alias", "")))
        print(f"  [+] Discovered: {addr} ({name})")
        if TARGET_MAC in addr or TARGET_NAME.lower() in name.lower():
            GLib.idle_add(do_connect, path)

bus.add_signal_receiver(
    on_interfaces_added,
    dbus_interface="org.freedesktop.DBus.ObjectManager",
    signal_name="InterfacesAdded"
)

def on_properties_changed(interface, changed_props, invalidated_props, path=""):
    if interface == "org.bluez.Device1":
        name = str(changed_props.get("Name", changed_props.get("Alias", "")))
        if TARGET_NAME.lower() in name.lower():
            print(f"  [+] PropertiesChanged identified: {path} -> {name}")
            GLib.idle_add(do_connect, path)

bus.add_signal_receiver(
    on_properties_changed,
    dbus_interface="org.freedesktop.DBus.Properties",
    signal_name="PropertiesChanged",
    path_keyword="path"
)

# Also check already known objects
manager = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
for path, ifaces in manager.GetManagedObjects().items():
    if "org.bluez.Device1" in ifaces:
        addr = str(ifaces["org.bluez.Device1"].get("Address", "")).upper()
        name = str(ifaces["org.bluez.Device1"].get("Name", ifaces["org.bluez.Device1"].get("Alias", "")))
        if TARGET_MAC in addr or TARGET_NAME.lower() in name.lower():
            print(f"Found existing registered device: {path}")
            GLib.idle_add(do_connect, path)
            break

print("🚀 Starting discovery (5 min window)... Please power-cycle JX-BT or disconnect it from phone!")
try:
    try:
        adapter.StopDiscovery()
    except Exception:
        pass
    adapter.StartDiscovery()
    GLib.timeout_add_seconds(300, loop.quit)
    loop.run()
finally:
    try:
        adapter.StopDiscovery()
    except Exception:
        pass

if connected:
    print("\n🎉 JX-BT IS CONNECTED! Setting PipeWire default sink...")
    sink = f"bluez_output.{TARGET_MAC.replace(':', '_')}.1"
    subprocess.run(["pactl", "set-default-sink", sink], capture_output=True)
    subprocess.run(["pactl", "set-sink-volume", sink, "80%"], capture_output=True)
    print("✓ PipeWire sink configured at 80% volume.")
    # Also notify SmartGarage server
    try:
        subprocess.run(["curl", "-s", "-X", "POST", "http://127.0.0.1:5000/api/speaker/connect", "-H", "Content-Type: application/json", "-d", f'{{"mac": "{TARGET_MAC}"}}'], capture_output=True)
    except Exception:
        pass
    sys.exit(0)
else:
    print("\n⏱ Timeout reached (300s). Device did not respond.")
    sys.exit(1)
