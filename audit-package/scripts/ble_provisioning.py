#!/usr/bin/env python3
"""
BLE WiFi Provisioning for Vernis
Allows users to configure WiFi via Bluetooth Low Energy from their phone.
"""

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import subprocess
import time
import json
import os
import signal
import sys
from gi.repository import GLib

# BLE UUIDs
VERNIS_SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'
WIFI_SSID_UUID = '12345678-1234-5678-1234-56789abcdef1'
WIFI_PASS_UUID = '12345678-1234-5678-1234-56789abcdef2'
WIFI_STATUS_UUID = '12345678-1234-5678-1234-56789abcdef3'
DEVICE_INFO_UUID = '12345678-1234-5678-1234-56789abcdef4'

BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
GATT_DESC_IFACE = 'org.bluez.GattDescriptor1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotSupported'


class NotPermittedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotPermitted'


class Application(dbus.service.Object):
    """BLE Application containing our service."""

    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)
        self.add_service(VernisWiFiService(bus, 0))

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
                descs = chrc.get_descriptors()
                for desc in descs:
                    response[desc.get_path()] = desc.get_properties()
        return response


class Service(dbus.service.Object):
    """BLE GATT Service base class."""

    PATH_BASE = '/org/bluez/vernis/service'

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

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    """BLE GATT Characteristic base class."""

    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.descriptors = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Descriptors': dbus.Array(
                    self.get_descriptor_paths(),
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_descriptor(self, descriptor):
        self.descriptors.append(descriptor)

    def get_descriptor_paths(self):
        result = []
        for desc in self.descriptors:
            result.append(desc.get_path())
        return result

    def get_descriptors(self):
        return self.descriptors

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        print('Default ReadValue called, returning error')
        raise NotSupportedException()

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        print('Default WriteValue called, returning error')
        raise NotSupportedException()

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        print('Default StartNotify called, returning error')
        raise NotSupportedException()

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        print('Default StopNotify called, returning error')
        raise NotSupportedException()

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class VernisWiFiService(Service):
    """Vernis WiFi Provisioning Service."""

    def __init__(self, bus, index):
        Service.__init__(self, bus, index, VERNIS_SERVICE_UUID, True)
        self.wifi_ssid = ''
        self.wifi_pass = ''
        self.status = 'ready'

        self.add_characteristic(WiFiSSIDCharacteristic(bus, 0, self))
        self.add_characteristic(WiFiPasswordCharacteristic(bus, 1, self))
        self.add_characteristic(WiFiStatusCharacteristic(bus, 2, self))
        self.add_characteristic(DeviceInfoCharacteristic(bus, 3, self))


class WiFiSSIDCharacteristic(Characteristic):
    """Characteristic for receiving WiFi SSID."""

    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index, WIFI_SSID_UUID,
            ['write'], service)

    def WriteValue(self, value, options):
        ssid = bytes(value).decode('utf-8')
        print(f'Received SSID: {ssid}')
        self.service.wifi_ssid = ssid


class WiFiPasswordCharacteristic(Characteristic):
    """Characteristic for receiving WiFi password and triggering connection."""

    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index, WIFI_PASS_UUID,
            ['write'], service)

    def WriteValue(self, value, options):
        password = bytes(value).decode('utf-8')
        print(f'Received password (length: {len(password)})')
        self.service.wifi_pass = password

        # Trigger WiFi connection
        self.connect_wifi()

    def connect_wifi(self):
        """Configure and connect to WiFi."""
        ssid = self.service.wifi_ssid
        password = self.service.wifi_pass

        if not ssid:
            self.service.status = 'error:no_ssid'
            return

        self.service.status = 'connecting'
        print(f'Attempting to connect to: {ssid}')

        try:
            # Create wpa_supplicant config
            # Escape special characters to prevent config injection
            safe_ssid = ssid.replace('\\', '\\\\').replace('"', '\\"')
            safe_pass = password.replace('\\', '\\\\').replace('"', '\\"')
            wpa_config = f'''ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={{
    ssid="{safe_ssid}"
    psk="{safe_pass}"
    key_mgmt=WPA-PSK
}}
'''
            # Write to temp file with restricted permissions (WiFi password inside)
            import os as _os
            fd = _os.open('/tmp/wpa_supplicant.conf', _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
            with _os.fdopen(fd, 'w') as f:
                f.write(wpa_config)

            # Copy to actual location with sudo
            subprocess.run(
                ['sudo', 'cp', '/tmp/wpa_supplicant.conf', '/etc/wpa_supplicant/wpa_supplicant.conf'],
                check=True
            )

            # Restart networking
            subprocess.run(['sudo', 'wpa_cli', '-i', 'wlan0', 'reconfigure'], check=True)

            # Wait for connection
            time.sleep(5)

            # Check if connected
            result = subprocess.run(
                ['iwgetid', '-r'],
                capture_output=True, text=True
            )

            if result.stdout.strip() == ssid:
                # Get IP address
                ip_result = subprocess.run(
                    ['hostname', '-I'],
                    capture_output=True, text=True
                )
                ip = ip_result.stdout.strip().split()[0] if ip_result.stdout.strip() else 'unknown'
                self.service.status = f'connected:{ip}'
                print(f'Connected! IP: {ip}')

                # Schedule shutdown of BLE after successful connection
                GLib.timeout_add_seconds(10, self.shutdown_ble)
            else:
                self.service.status = 'error:connection_failed'
                print('Connection failed')

        except Exception as e:
            self.service.status = f'error:{str(e)}'
            print(f'Error: {e}')

    def shutdown_ble(self):
        """Shutdown BLE provisioning after successful WiFi connection."""
        print('WiFi connected, shutting down BLE provisioning...')
        # Stop the service gracefully
        subprocess.run(['sudo', 'systemctl', 'stop', 'vernis-ble'], capture_output=True)
        return False


class WiFiStatusCharacteristic(Characteristic):
    """Characteristic for reading connection status."""

    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index, WIFI_STATUS_UUID,
            ['read', 'notify'], service)
        self.notifying = False

    def ReadValue(self, options):
        status = self.service.status
        print(f'Status read: {status}')
        return dbus.Array([dbus.Byte(b) for b in status.encode('utf-8')])

    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        GLib.timeout_add(1000, self.notify_status)

    def StopNotify(self):
        self.notifying = False

    def notify_status(self):
        if not self.notifying:
            return False
        value = [dbus.Byte(b) for b in self.service.status.encode('utf-8')]
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])
        return True


class DeviceInfoCharacteristic(Characteristic):
    """Characteristic for reading device info (name, version)."""

    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index, DEVICE_INFO_UUID,
            ['read'], service)

    def ReadValue(self, options):
        info = {
            'name': 'Vernis',
            'version': '3.0',
            'type': 'petit'
        }
        info_str = json.dumps(info)
        return dbus.Array([dbus.Byte(b) for b in info_str.encode('utf-8')])


class Advertisement(dbus.service.Object):
    """BLE Advertisement."""

    PATH_BASE = '/org/bluez/vernis/advertisement'

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = None
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.local_name = None
        self.include_tx_power = False
        self.data = None
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        if self.service_uuids is not None:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        if self.solicit_uuids is not None:
            properties['SolicitUUIDs'] = dbus.Array(self.solicit_uuids, signature='s')
        if self.manufacturer_data is not None:
            properties['ManufacturerData'] = dbus.Dictionary(self.manufacturer_data, signature='qv')
        if self.service_data is not None:
            properties['ServiceData'] = dbus.Dictionary(self.service_data, signature='sv')
        if self.local_name is not None:
            properties['LocalName'] = dbus.String(self.local_name)
        if self.include_tx_power:
            properties['Includes'] = dbus.Array(["tx-power"], signature='s')
        if self.data is not None:
            properties['Data'] = dbus.Dictionary(self.data, signature='yv')
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        print('Advertisement released')


class VernisAdvertisement(Advertisement):
    """Vernis-specific BLE advertisement."""

    def __init__(self, bus, index):
        Advertisement.__init__(self, bus, index, 'peripheral')
        self.local_name = 'Vernis-Setup'
        self.service_uuids = [VERNIS_SERVICE_UUID]
        self.include_tx_power = True


def find_adapter(bus):
    """Find the Bluetooth adapter."""
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props.keys():
            return o

    return None


def main():
    """Main entry point."""
    global mainloop

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter = find_adapter(bus)
    if not adapter:
        print('BLE adapter not found')
        return

    adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter)
    adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)

    # Power on the adapter
    adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))

    # Get managers
    service_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
    ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)

    # Create application and advertisement
    app = Application(bus)
    adv = VernisAdvertisement(bus, 0)

    mainloop = GLib.MainLoop()

    def register_app_cb():
        print('GATT application registered')

    def register_app_error_cb(error):
        print(f'Failed to register application: {error}')
        mainloop.quit()

    def register_ad_cb():
        print('Advertisement registered')

    def register_ad_error_cb(error):
        print(f'Failed to register advertisement: {error}')
        mainloop.quit()

    # Register GATT application
    print('Registering GATT application...')
    service_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=register_app_cb,
        error_handler=register_app_error_cb
    )

    # Register advertisement
    print('Registering advertisement...')
    ad_manager.RegisterAdvertisement(
        adv.get_path(), {},
        reply_handler=register_ad_cb,
        error_handler=register_ad_error_cb
    )

    # Handle signals for graceful shutdown
    def signal_handler(sig, frame):
        print('\nShutting down...')
        mainloop.quit()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print('Vernis BLE WiFi Provisioning started')
    print('Advertising as "Vernis-Setup"')

    mainloop.run()

    # Cleanup
    ad_manager.UnregisterAdvertisement(adv.get_path())
    print('Advertisement unregistered')


if __name__ == '__main__':
    main()
