#!/usr/bin/python3
"""Check or set the Vernis owner's Linux password.

vernis-api runs as the owner's own account, which can neither read
/etc/shadow nor run chpasswd. install-password-helper.sh installs this file
root-owned as /usr/local/sbin/vernis-device-password and allows that account
to run it with sudo - nothing else.

  vernis-device-password check   stdin: password      exit 0 = correct, 1 = wrong
  vernis-device-password set     stdin: new password  exit 0 = changed

Only ever touches the account that called sudo (SUDO_USER, set by sudo
itself), never root or anyone else. Exit 2 = refused or error.
"""
import ctypes
import ctypes.util
import os
import subprocess
import sys


def main():
    user = os.environ.get("SUDO_USER", "")
    if os.geteuid() != 0 or not user or user == "root" or len(sys.argv) != 2:
        return 2
    password = sys.stdin.readline().rstrip("\n")
    if not password or len(password) > 128:
        return 2

    if sys.argv[1] == "check":
        stored = None
        with open("/etc/shadow") as shadow:
            for line in shadow:
                fields = line.rstrip("\n").split(":")
                if fields[0] == user and len(fields) > 1:
                    stored = fields[1]
                    break
        # Locked or passwordless accounts never match
        if not stored or stored in ("*", "x") or stored.startswith("!"):
            return 1
        libcrypt = ctypes.CDLL(ctypes.util.find_library("crypt") or "libcrypt.so.1")
        libcrypt.crypt.restype = ctypes.c_char_p
        computed = libcrypt.crypt(password.encode(), stored.encode())
        return 0 if computed and computed.decode() == stored else 1

    if sys.argv[1] == "set":
        result = subprocess.run(["chpasswd"], input=f"{user}:{password}\n",
                                text=True, capture_output=True)
        return 0 if result.returncode == 0 else 2

    return 2


if __name__ == "__main__":
    sys.exit(main())
