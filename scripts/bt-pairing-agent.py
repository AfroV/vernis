#!/usr/bin/env python3
"""
Vernis Bluetooth Pairing Agent
Custom BlueZ D-Bus agent with DisplayYesNo capability.
Relays pairing PIN to the Vernis backend for display on the kiosk screen.
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import subprocess
import json

AGENT_INTERFACE = "org.bluez.Agent1"
AGENT_PATH = "/vernis/bt_agent"
BACKEND_URL = "http://localhost:5000/api/bluetooth/pairing"
CAPABILITY = "DisplayYesNo"


def notify_backend(pin, device, event="pin"):
    """Post pairing event to Vernis backend."""
    try:
        data = json.dumps({"pin": str(pin), "device": device, "event": event})
        subprocess.Popen([
            "curl", "-s", "-X", "POST", BACKEND_URL,
            "-H", "Content-Type: application/json",
            "-d", data
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[bt-agent] Backend notify failed: {e}", flush=True)


def device_name(path):
    """Get friendly name for a device from its D-Bus path."""
    try:
        bus = dbus.SystemBus()
        obj = bus.get_object("org.bluez", path)
        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
        name = props.Get("org.bluez.Device1", "Name")
        return str(name)
    except Exception:
        return path.split("/")[-1] if "/" in path else "Unknown"


class Agent(dbus.service.Object):
    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        print("[bt-agent] Agent released", flush=True)

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[bt-agent] AuthorizeService {device} {uuid}", flush=True)

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        name = device_name(device)
        print(f"[bt-agent] RequestPinCode from {name}", flush=True)
        return "0000"

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        name = device_name(device)
        print(f"[bt-agent] RequestPasskey from {name}", flush=True)
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        name = device_name(device)
        pin = f"{passkey:06d}"
        print(f"[bt-agent] DisplayPasskey {pin} for {name}", flush=True)
        notify_backend(pin, name)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        name = device_name(device)
        pin = f"{passkey:06d}"
        print(f"[bt-agent] RequestConfirmation {pin} for {name}", flush=True)
        notify_backend(pin, name)
        # Auto-confirm (PIN is shown on screen for user verification)

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        name = device_name(device)
        print(f"[bt-agent] RequestAuthorization from {name}", flush=True)

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        print("[bt-agent] Pairing cancelled", flush=True)
        notify_backend("", "", "failed")


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    agent = Agent(bus, AGENT_PATH)
    manager = dbus.Interface(
        bus.get_object("org.bluez", "/org/bluez"),
        "org.bluez.AgentManager1"
    )

    manager.RegisterAgent(AGENT_PATH, CAPABILITY)
    manager.RequestDefaultAgent(AGENT_PATH)
    print(f"[bt-agent] Registered with capability={CAPABILITY}", flush=True)

    # Trust paired devices automatically
    def interfaces_added(path, interfaces):
        if "org.bluez.Device1" in interfaces:
            props = interfaces["org.bluez.Device1"]
            if props.get("Paired"):
                try:
                    obj = bus.get_object("org.bluez", path)
                    dev = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                    dev.Set("org.bluez.Device1", "Trusted", True)
                    name = props.get("Name", "Unknown")
                    print(f"[bt-agent] Auto-trusted {name}", flush=True)
                    notify_backend("", str(name), "complete")
                except Exception:
                    pass

    bus.add_signal_receiver(
        interfaces_added,
        dbus_interface="org.freedesktop.DBus.ObjectManager",
        signal_name="InterfacesAdded"
    )

    print("[bt-agent] Waiting for pairing requests...", flush=True)
    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        print("[bt-agent] Stopped", flush=True)
        manager.UnregisterAgent(AGENT_PATH)


if __name__ == "__main__":
    main()
