#!/usr/bin/env bash
#
# Vernis Remote Renderer
#
# Renders a URL (e.g. Art Blocks Gazer) and streams it to a Vernis device.
#
#   Mac:   Opens Chrome in app mode, captures the window, streams via RTSP
#   Linux: Headless — uses Xvfb virtual display, no screen recording needed
#
# Usage:
#   ./vernis-stream.sh <url> <pi-ip>
#   ./vernis-stream.sh "https://artblocks.io/..." 10.0.0.28
#   ./vernis-stream.sh <url> <pi-ip> [--resolution 1920x1080] [--fps 30] [--bitrate 8M]
#
# Requirements:
#   Mac:   ffmpeg, Google Chrome
#   Linux: ffmpeg, chromium-browser, Xvfb

set -euo pipefail

# Defaults
RESOLUTION="1920x1080"
FPS="30"
BITRATE="8M"
RTSP_PORT="8554"
STREAM_PATH="live"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[vernis]${NC} $*"; }
warn() { echo -e "${YELLOW}[vernis]${NC} $*"; }
err()  { echo -e "${RED}[vernis]${NC} $*" >&2; }

# Parse arguments
URL=""
PI_IP=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --resolution) RESOLUTION="$2"; shift 2 ;;
        --fps)        FPS="$2"; shift 2 ;;
        --bitrate)    BITRATE="$2"; shift 2 ;;
        --port)       RTSP_PORT="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: vernis-stream.sh <url> <pi-ip> [options]"
            echo ""
            echo "Options:"
            echo "  --resolution WxH   Stream resolution (default: 1920x1080)"
            echo "  --fps N            Frame rate (default: 30)"
            echo "  --bitrate N        Encoding bitrate (default: 8M)"
            echo "  --port N           RTSP port (default: 8554)"
            echo ""
            echo "Examples:"
            echo "  ./vernis-stream.sh \"https://artblocks.io/...\" 10.0.0.28"
            echo "  ./vernis-stream.sh \"https://artblocks.io/...\" 10.0.0.28 --resolution 1280x720 --fps 60"
            exit 0
            ;;
        *)
            if [[ -z "$URL" ]]; then
                URL="$1"
            elif [[ -z "$PI_IP" ]]; then
                PI_IP="$1"
            fi
            shift
            ;;
    esac
done

if [[ -z "$URL" || -z "$PI_IP" ]]; then
    err "Usage: vernis-stream.sh <url> <pi-ip>"
    err "Example: ./vernis-stream.sh \"https://artblocks.io/...\" 10.0.0.28"
    exit 1
fi

RTSP_URL="rtsp://${PI_IP}:${RTSP_PORT}/${STREAM_PATH}"
WIDTH="${RESOLUTION%x*}"
HEIGHT="${RESOLUTION#*x}"

# Cleanup on exit
PIDS_TO_KILL=()
XVFB_DISPLAY=""

cleanup() {
    log "Shutting down..."
    for pid in "${PIDS_TO_KILL[@]}"; do
        kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null || true
    done
    # Remove Xvfb lock file if we created one
    if [[ -n "$XVFB_DISPLAY" ]]; then
        rm -f "/tmp/.X${XVFB_DISPLAY}-lock" 2>/dev/null || true
    fi
    log "Done."
}
trap cleanup EXIT INT TERM

# Check ffmpeg
if ! command -v ffmpeg &>/dev/null; then
    err "ffmpeg not found. Install it:"
    err "  Mac:   brew install ffmpeg"
    err "  Linux: sudo apt install ffmpeg"
    exit 1
fi

# Check connectivity to Pi
if ! nc -z -w 3 "$PI_IP" "$RTSP_PORT" 2>/dev/null; then
    err "Cannot reach ${PI_IP}:${RTSP_PORT}"
    err "Make sure Remote Rendering is enabled in Vernis Settings."
    exit 1
fi

log "Streaming ${CYAN}${URL}${NC}"
log "To ${CYAN}${RTSP_URL}${NC} at ${RESOLUTION} ${FPS}fps ${BITRATE}"
echo ""

OS="$(uname -s)"

if [[ "$OS" == "Darwin" ]]; then
    # ===== macOS: Chrome app mode + avfoundation capture =====

    CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if [[ ! -x "$CHROME" ]]; then
        CHROME="/Applications/Chromium.app/Contents/MacOS/Chromium"
    fi
    if [[ ! -x "$CHROME" ]]; then
        err "Google Chrome or Chromium not found."
        exit 1
    fi

    # Separate profile so kiosk flags work even if Chrome is already open
    CHROME_PROFILE="/tmp/vernis-stream-profile"
    mkdir -p "$CHROME_PROFILE"

    log "Opening Chrome (${WIDTH}x${HEIGHT})..."
    "$CHROME" \
        --user-data-dir="$CHROME_PROFILE" \
        --app="$URL" \
        --window-size="${WIDTH},${HEIGHT}" \
        --window-position=0,0 \
        --disable-features=RendererCodeIntegrity \
        --autoplay-policy=no-user-gesture-required \
        --no-first-run \
        --no-default-browser-check \
        &>/dev/null &
    CHROME_PID=$!
    PIDS_TO_KILL+=("$CHROME_PID")

    sleep 3
    log "Chrome started (PID $CHROME_PID)"

    # List capture devices to help user
    log "Capturing screen — if this is the first time, macOS will ask for"
    log "Screen Recording permission for Terminal/ffmpeg."
    echo ""
    warn "Press Ctrl+C to stop streaming."
    echo ""

    # Capture main screen, scale to target resolution
    # setpts=N/(FPS*TB) forces clean sequential timestamps (fixes avfoundation DTS issues)
    # For square displays (e.g. 720x720): center-crop to square first, then scale
    if [[ "$WIDTH" -eq "$HEIGHT" ]]; then
        VF="crop=min(iw\,ih):min(iw\,ih),scale=${WIDTH}:${HEIGHT},setpts=N/(${FPS}*TB)"
    else
        VF="scale=${WIDTH}:${HEIGHT},setpts=N/(${FPS}*TB)"
    fi

    ffmpeg \
        -f avfoundation \
        -framerate "$FPS" \
        -capture_cursor 0 \
        -pixel_format uyvy422 \
        -i "1:none" \
        -vf "$VF" \
        -c:v libx264 \
        -preset ultrafast \
        -tune zerolatency \
        -b:v "$BITRATE" \
        -pix_fmt yuv420p \
        -r "$FPS" \
        -f rtsp \
        -rtsp_transport tcp \
        "$RTSP_URL" &
    FFMPEG_PID=$!
    PIDS_TO_KILL+=("$FFMPEG_PID")

    wait "$FFMPEG_PID" 2>/dev/null || true

elif [[ "$OS" == "Linux" ]]; then
    # ===== Linux: Xvfb headless + chromium + x11grab =====

    # Check dependencies
    for cmd in Xvfb; do
        if ! command -v "$cmd" &>/dev/null; then
            err "$cmd not found. Install it:"
            err "  sudo apt install xvfb"
            exit 1
        fi
    done

    CHROMIUM=""
    for candidate in chromium-browser chromium google-chrome-stable google-chrome; do
        if command -v "$candidate" &>/dev/null; then
            CHROMIUM="$candidate"
            break
        fi
    done
    if [[ -z "$CHROMIUM" ]]; then
        err "No Chromium/Chrome found. Install with: sudo apt install chromium-browser"
        exit 1
    fi

    # Find a free display number
    DISPLAY_NUM=99
    while [[ -e "/tmp/.X${DISPLAY_NUM}-lock" ]]; do
        DISPLAY_NUM=$((DISPLAY_NUM + 1))
    done
    XVFB_DISPLAY="$DISPLAY_NUM"

    log "Starting virtual display :${DISPLAY_NUM} (${RESOLUTION})"
    Xvfb ":${DISPLAY_NUM}" -screen 0 "${WIDTH}x${HEIGHT}x24" \
        -ac +extension GLX +render -noreset &>/dev/null &
    XVFB_PID=$!
    PIDS_TO_KILL+=("$XVFB_PID")
    sleep 1

    export DISPLAY=":${DISPLAY_NUM}"

    log "Launching headless Chromium..."
    "$CHROMIUM" \
        --no-sandbox \
        --disable-dev-shm-usage \
        --disable-software-rasterizer \
        --use-gl=angle \
        --use-angle=swiftshader \
        --window-size="${WIDTH},${HEIGHT}" \
        --kiosk \
        --autoplay-policy=no-user-gesture-required \
        --disable-features=RendererCodeIntegrity \
        "$URL" &>/dev/null &
    CHROME_PID=$!
    PIDS_TO_KILL+=("$CHROME_PID")
    sleep 3
    log "Chromium started (PID $CHROME_PID)"

    warn "Streaming headlessly — no screen recording, no desktop access."
    warn "Press Ctrl+C to stop."
    echo ""

    # Capture virtual framebuffer
    ffmpeg \
        -f x11grab \
        -framerate "$FPS" \
        -video_size "${WIDTH}x${HEIGHT}" \
        -i ":${DISPLAY_NUM}.0" \
        -c:v libx264 \
        -preset ultrafast \
        -tune zerolatency \
        -b:v "$BITRATE" \
        -pix_fmt yuv420p \
        -f rtsp \
        -rtsp_transport tcp \
        "$RTSP_URL" &
    FFMPEG_PID=$!
    PIDS_TO_KILL+=("$FFMPEG_PID")

    wait "$FFMPEG_PID" 2>/dev/null || true

else
    err "Unsupported OS: $OS"
    exit 1
fi
