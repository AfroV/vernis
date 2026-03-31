#!/bin/bash
##############################################
# Vernis Screen Watchdog
# Restarts Chromium if it stops running
# Detects renderer crashes (Aw, Snap!) and reloads
# Checks every 10 seconds for fast recovery
# Supports both X11 and Wayland (labwc)
##############################################

# Wait for graphical session to be ready
sleep 15

# Detect display environment once at startup
USERNAME=$(logname 2>/dev/null || whoami)
USER_ID=$(id -u "$USERNAME" 2>/dev/null || echo 1000)
XDG_DIR="/run/user/$USER_ID"

if [ -S "$XDG_DIR/wayland-0" ]; then
    export XDG_RUNTIME_DIR="$XDG_DIR"
    export WAYLAND_DISPLAY=wayland-0
    echo "[$(date)] Watchdog: Wayland session detected"
else
    export DISPLAY=:0
    echo "[$(date)] Watchdog: X11 session detected"
fi

CDP_PORT=9222
CRASH_CHECK_INTERVAL=15  # Check renderer health every 15s
LAST_CRASH_CHECK=0
CONSECUTIVE_FAILS=0

# Reload crashed page via CDP — reload current page, not always gallery
reload_via_cdp() {
    local WS_URL="$1"
    python3 -c "
import json, websocket
try:
    ws = websocket.create_connection('$WS_URL', timeout=10)
    # Get current URL first
    ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':'window.location.href','timeout':5000}}))
    ws.settimeout(10)
    r = json.loads(ws.recv())
    url = r.get('result',{}).get('result',{}).get('value','')
    # If on lab.html, reload in place (user sent content there intentionally)
    if 'lab.html' in url:
        ws.send(json.dumps({'id':2,'method':'Page.reload'}))
    else:
        ws.send(json.dumps({'id':2,'method':'Page.navigate','params':{'url':'http://localhost/index.html'}}))
    ws.settimeout(10)
    r = json.loads(ws.recv())
    ws.close()
    print('OK' if 'result' in r else 'FAIL')
except Exception as e:
    print('ERR: ' + str(e))
" 2>/dev/null
}

# Check if renderer is alive by evaluating JS via CDP
# Uses longer timeout to avoid false positives during heavy JS (ethers.js RPC calls)
check_renderer_alive() {
    local WS_URL="$1"
    local TIMEOUT="${2:-8}"   # connection timeout (default 8s, lab uses 20s)
    local JS_TIMEOUT="${3:-6000}"  # JS eval timeout ms (default 6s, lab uses 15s)
    local RECV_TIMEOUT="${4:-12}"  # recv timeout (default 12s, lab uses 25s)
    python3 -c "
import json, websocket
try:
    ws = websocket.create_connection('$WS_URL', timeout=$TIMEOUT)
    ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':'1+1','timeout':$JS_TIMEOUT}}))
    ws.settimeout($RECV_TIMEOUT)
    r = json.loads(ws.recv())
    ws.close()
    if 'result' in r and r['result'].get('result',{}).get('value') == 2:
        print('ALIVE')
    else:
        print('DEAD')
except:
    print('DEAD')
" 2>/dev/null
}

while true; do
    sleep 10

    # Check if chromium is running in kiosk mode
    if ! pgrep -f 'chromium.*kiosk' > /dev/null; then
        echo "[$(date)] Chromium not running, restarting via launcher..."
        bash /opt/vernis/scripts/kiosk-launcher.sh &
        # Wait extra time after restart to let Chromium stabilize
        sleep 20
        LAST_CRASH_CHECK=$(date +%s)
        CONSECUTIVE_FAILS=0
        continue
    fi

    # Renderer crash check (every CRASH_CHECK_INTERVAL seconds)
    NOW=$(date +%s)
    if [ $((NOW - LAST_CRASH_CHECK)) -ge $CRASH_CHECK_INTERVAL ]; then
        LAST_CRASH_CHECK=$NOW

        # Get CDP WebSocket URL
        CDP_JSON=$(curl -s --max-time 3 "http://localhost:$CDP_PORT/json" 2>/dev/null)
        # Find the main page tab (prefer localhost page, skip empty/devtools tabs)
        WS_URL=$(echo "$CDP_JSON" | python3 -c "
import sys, json
pages = json.load(sys.stdin)
# Prefer page with localhost URL (the actual kiosk content)
for p in pages:
    url = p.get('url', '')
    if 'localhost' in url and p.get('webSocketDebuggerUrl'):
        print(p['webSocketDebuggerUrl'])
        break
else:
    if pages and pages[0].get('webSocketDebuggerUrl'):
        print(pages[0]['webSocketDebuggerUrl'])
" 2>/dev/null)

        if [ -n "$WS_URL" ]; then
            # Detect if lab.html is active — use longer timeouts and higher
            # failure threshold since burner/pixelchain iframes are CPU-heavy
            CURRENT_URL=$(echo "$CDP_JSON" | python3 -c "
import sys,json
pages=json.load(sys.stdin)
for p in pages:
    u=p.get('url','')
    if 'localhost' in u:
        print(u); break
else:
    print(pages[0].get('url','') if pages else '')
" 2>/dev/null)
            IS_LAB=false
            if echo "$CURRENT_URL" | grep -q "lab.html"; then
                IS_LAB=true
            fi

            if [ "$IS_LAB" = true ]; then
                # Lab: generous timeouts (20s connect, 15s JS, 25s recv)
                STATUS=$(check_renderer_alive "$WS_URL" 20 15000 25)
                KILL_THRESHOLD=6  # ~90s of failures before kill
            else
                STATUS=$(check_renderer_alive "$WS_URL")
                KILL_THRESHOLD=3
            fi

            if [ "$STATUS" != "ALIVE" ]; then
                CONSECUTIVE_FAILS=$((CONSECUTIVE_FAILS + 1))
                echo "[$(date)] Renderer unresponsive (attempt $CONSECUTIVE_FAILS/$KILL_THRESHOLD, lab=$IS_LAB)..."

                if [ $CONSECUTIVE_FAILS -ge $KILL_THRESHOLD ]; then
                    # Truly stuck — kill and restart
                    echo "[$(date)] Renderer stuck after $CONSECUTIVE_FAILS checks, killing Chromium..."
                    pkill -9 -f 'chromium.*kiosk' 2>/dev/null
                    sleep 3
                    bash /opt/vernis/scripts/kiosk-launcher.sh &
                    sleep 20
                    CONSECUTIVE_FAILS=0
                    LAST_CRASH_CHECK=$(date +%s)
                elif [ "$IS_LAB" = false ]; then
                    # Non-lab: try CDP reload on first failure
                    echo "[$(date)] Attempting CDP reload..."
                    RESULT=$(reload_via_cdp "$WS_URL")
                    echo "[$(date)] Reload result: $RESULT"
                    sleep 10
                fi
                # Lab: no reload attempt — just wait and recheck with longer intervals
            else
                CONSECUTIVE_FAILS=0
            fi
        fi
    fi
done
