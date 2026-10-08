#!/bin/bash
# Vernis — one-time repair for already-deployed devices.
# Scopes Caddy's global no-cache header so it no longer applies to
# /api/thumbnail/*, letting browsers cache thumbnails instead of re-downloading
# 2500+ images on every gallery/manage visit. Thumbnails set their own
# Cache-Control in Flask (backend/app.py); without this scoping the global
# header overwrites it. Idempotent: safe to run multiple times.
#
# Usage:
#   sudo bash /opt/vernis/scripts/fix-caddy-cache.sh

set -e

CADDYFILE="/etc/caddy/Caddyfile"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

if [ ! -f "$CADDYFILE" ]; then
    echo "ERROR: $CADDYFILE not found — is Caddy installed?" >&2
    exit 1
fi

if grep -q '@nocache' "$CADDYFILE"; then
    echo "Caddyfile already scoped (@nocache present) — nothing to do."
    exit 0
fi

# Transform the global `header { Cache-Control "no-cache..." }` block into a
# matcher-scoped block that excludes /api/thumbnail/*. Done in Python for a
# precise, whitespace-tolerant edit rather than fragile sed.
python3 - "$CADDYFILE" <<'PYEOF'
import re, sys

path = sys.argv[1]
src = open(path).read()

# Match an un-scoped `header {` block whose body sets the no-cache Cache-Control.
pattern = re.compile(
    r'(?P<indent>[ \t]*)header\s*\{\s*\n'
    r'(?P<body>(?:[ \t]*Cache-Control[^\n]*\n))'
    r'(?P=indent)\}',
    re.MULTILINE,
)

def repl(m):
    indent = m.group('indent')
    body = m.group('body')
    return (f'{indent}@nocache not path /api/thumbnail/*\n'
            f'{indent}header @nocache {{\n'
            f'{body}'
            f'{indent}}}')

new, n = pattern.subn(repl, src, count=1)
if n != 1:
    sys.stderr.write(
        "Could not find the global no-cache header block to patch.\n"
        "Patch the Caddyfile by hand: add `@nocache not path /api/thumbnail/*`\n"
        "above the header block and change `header {` to `header @nocache {`.\n")
    sys.exit(2)

open(path, 'w').write(new)
print("Caddyfile patched: no-cache header now excludes /api/thumbnail/*")
PYEOF

# Validate before reloading so a bad edit never takes Caddy down.
if ! caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1; then
    echo "ERROR: caddy validate failed after patching — NOT restarting Caddy." >&2
    echo "Review $CADDYFILE manually." >&2
    exit 1
fi

systemctl restart caddy
echo "Caddy restarted. Thumbnails are now browser-cacheable."
