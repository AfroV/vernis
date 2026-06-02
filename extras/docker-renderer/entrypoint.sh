#!/bin/bash
set -euo pipefail

# Generate API key if not provided
if [ -z "${VERNIS_API_KEY:-}" ]; then
    export VERNIS_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
fi

# Resolution from env (default 720x720)
RES="${VERNIS_RESOLUTION:-720x720}"
WIDTH="${RES%x*}"
HEIGHT="${RES#*x}"

# Start Xvfb virtual display
Xvfb :99 -screen 0 "${WIDTH}x${HEIGHT}x24" -ac +extension GLX +render -noreset &
XVFB_PID=$!
export DISPLAY=:99
sleep 1

# Verify Xvfb started
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "ERROR: Xvfb failed to start"
    exit 1
fi

# Hide cursor by moving it off-screen
xdotool mousemove --screen 0 9999 9999 2>/dev/null || true

echo "Vernis Remote Renderer"
echo "  Display: :99 (${WIDTH}x${HEIGHT})"
echo "  API Key: ${VERNIS_API_KEY}"
echo ""

# Cleanup handler
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $XVFB_PID 2>/dev/null || true
    # server.py handles its own Chrome/ffmpeg cleanup via signal handler
    exit 0
}
trap cleanup SIGTERM SIGINT

# Launch server (passes through all args, e.g. PI_IP from env)
exec python3 /home/vernis/server.py
