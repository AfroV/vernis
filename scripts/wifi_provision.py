#!/usr/bin/env python3
"""
Vernis v3 - Bluetooth LE Wi-Fi Provisioner
Uses BlueZ D-Bus API to expose a GATT server for Wi-Fi configuration.
Dependencies: python3-dbus, python3-gi, bluez
"""

import sys
import os
import dbus
import dbus.mainloop.glib
import dbus.service
import subprocess
import time
from gi.repository import GLib

# Constants
BLUEZ_SERVICE_NAME = 'org.bluez'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

# Vernis Service UUIDs (Randomly generated for this project)
# Service: 12345678-1234-5678-1234-56789abcdef0
# SSID Char: 12345678-1234-5678-1234-56789abcdef1
# Pass Char: 12345678-1234-5678-1234-56789abcdef2
# Status Char: 12345678-1234-5678-1234-56789abcdef3

VERNIS_SVC_UUID = '12345678-1234-5678-1234-56789abcdef0'
SSID_CHRC_UUID = '12345678-1234-5678-1234-56789abcdef1'
PASS_CHRC_UUID = '12345678-1234-5678-1234-56789abcdef2'
STATUS_CHRC_UUID = '12345678-1234-5678-1234-56789abcdef3'

mainloop = None

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotSupported'

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
        return response

class Service(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/service'
    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, chrc):
        self.characteristics.append(chrc)

    def get_characteristic_paths(self):
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    def get_characteristics(self):
        return self.characteristics

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Value': dbus.Array(self.value, signature='y')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='a{sv}',
                        out_signature='ay')
    def ReadValue(self, options):
        print(f'Read request on {self.uuid}')
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        print(f'Write request on {self.uuid}')
        self.value = value
        self.on_write(value)

    def on_write(self, value):
        pass

class WifiProvisioningService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, VERNIS_SVC_UUID, True)
        self.add_characteristic(SsidCharacteristic(bus, 0, self))
        self.add_characteristic(PassCharacteristic(bus, 1, self))
        self.add_characteristic(StatusCharacteristic(bus, 2, self))

class SsidCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, SSID_CHRC_UUID,
                                ['read', 'write'], service)
        self.value = [ord(c) for c in "Current-SSID"]

    def on_write(self, value):
        ssid = ''.join([chr(c) for c in value])
        print(f"Received SSID: {ssid}")
        # Store with restricted permissions (0600)
        fd = os.open("/tmp/vernis_wifi_ssid", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(ssid)

class PassCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, PASS_CHRC_UUID,
                                ['write'], service)

    def on_write(self, value):
        password = ''.join([chr(c) for c in value])
        print("Received Password")
        # Store with restricted permissions (0600)
        fd = os.open("/tmp/vernis_wifi_pass", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(password)
        
        # Trigger Connection Attempt
        # We need SSID first, so check if it exists
        try:
            with open("/tmp/vernis_wifi_ssid", "r") as f:
                ssid = f.read().strip()

            print(f"Attempting connection to {ssid}...")
            # Run nmcli commands (using list args to prevent shell injection)
            res = subprocess.run(
                ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", password],
                capture_output=True
            )
            
            if res.returncode == 0:
                print("Connection Successful!")
                # Update status
                status_char = self.service.characteristics[2] # Status is index 2
                status_char.value = [ord(c) for c in "Success"]
                # In a real scenario, you might stop the BLE service here
            else:
                print(f"Connection Failed: {res.stderr}")
                status_char = self.service.characteristics[2]
                status_char.value = [ord(c) for c in "Failed"]

        except Exception as e:
            print(f"Error: {e}")

class StatusCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, STATUS_CHRC_UUID,
                                ['read', 'notify'], service)
        self.value = [ord(c) for c in "Ready"]

# Advertisement Class (Standard BlueZ)
class Advertisement(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = None
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.local_name = 'Vernis Setup'
        self.include_tx_power = False
        self.data = None
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        properties['LocalName'] = self.local_name
        if self.service_uuids is not None:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids,
                                                    signature='s')
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)
    
    def add_service_uuid(self, uuid):
        if not self.service_uuids:
            self.service_uuids = []
        self.service_uuids.append(uuid)

    @dbus.service.method(DBUS_PROPERTIES_IFACE,
                         in_signature='s',
                         out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]
    
    @dbus.service.method(LE_ADVERTISEMENT_IFACE,
                         in_signature='',
                         out_signature='')
    def Release(self):
        print('%s: Released!' % self.path)

DBUS_PROPERTIES_IFACE = 'org.freedesktop.DBus.Properties'

def register_ad_cb():
    print('Advertisement registered')

def register_ad_error_cb(error):
    print('Failed to register advertisement: ' + str(error))
    mainloop.quit()

def register_app_cb():
    print('GATT application registered')

def register_app_error_cb(error):
    print('Failed to register application: ' + str(error))
    mainloop.quit()

def main():
    global mainloop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter = bus.get_object(BLUEZ_SERVICE_NAME, '/org/bluez/hci0')

    # LE Advertisement
    ad_manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)
    advertisement = Advertisement(bus, 0, 'peripheral')
    advertisement.add_service_uuid(VERNIS_SVC_UUID)
    
    ad_manager.RegisterAdvertisement(advertisement.get_path(), {},
                                     reply_handler=register_ad_cb,
                                     error_handler=register_ad_error_cb)

    # GATT Service
    service_manager = dbus.Interface(adapter, GATT_MANAGER_IFACE)
    app = Application(bus)
    app.add_service(WifiProvisioningService(bus, 0))
    
    service_manager.RegisterApplication(app.get_path(), {},
                                        reply_handler=register_app_cb,
                                        error_handler=register_app_error_cb)

    mainloop = GLib.MainLoop()
    print("Vernis BLE Provisioning Service Started...")
    mainloop.run()

if __name__ == '__main__':
    main()
