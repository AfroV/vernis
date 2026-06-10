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

# Confirm the Pi's side of pairing immediately. Phones (iOS especially)
# abort pairing if the Pi delays its confirmation, so we must respond fast.
# A long delay was previously added to suit Windows PCs, but it broke iPhone
# pairing; this deployment is phone-only, so confirm right away.
CONFIRM_DELAY_MS = 0


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
    def __init__(self, bus, path):
        super().__init__(bus, path)
        # device path -> GLib timeout source id; lets us cancel a pending
        # auto-confirm if BlueZ sends Cancel() in the meantime.
        self._pending_confirms = {}

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

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="",
                         async_callbacks=("ok", "err"))
    def RequestConfirmation(self, device, passkey, ok, err):
        name = device_name(device)
        pin = f"{passkey:06d}"
        delay_s = CONFIRM_DELAY_MS / 1000
        print(f"[bt-agent] RequestConfirmation {pin} for {name} "
              f"(delaying confirm {delay_s:.0f}s)", flush=True)
        notify_backend(pin, name)

        def _confirm():
            self._pending_confirms.pop(device, None)
            print(f"[bt-agent] Auto-confirming pairing for {name}", flush=True)
            ok()
            return False  # don't repeat

        timer_id = GLib.timeout_add(CONFIRM_DELAY_MS, _confirm)
        self._pending_confirms[device] = timer_id

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        name = device_name(device)
        print(f"[bt-agent] RequestAuthorization from {name}", flush=True)

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        print("[bt-agent] Pairing cancelled", flush=True)
        # Drop any pending auto-confirm timers — the user (or remote) cancelled.
        for tid in list(self._pending_confirms.values()):
            try:
                GLib.source_remove(tid)
            except Exception:
                pass
        self._pending_confirms.clear()
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
