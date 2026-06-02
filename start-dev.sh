#!/bin/bash
##############################################
# Convenience script to start development mode
# Shows your IP and starts the dev server
##############################################

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Vernis Development Mode Starting...   ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Get IP address
echo "📍 Your Local IP Address:"
echo "   ────────────────────────"
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    LOCAL_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -n 1)
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    LOCAL_IP=$(hostname -I | awk '{print $1}')
else
    LOCAL_IP="localhost"
fi

PORT=8081
echo "   $LOCAL_IP:$PORT"
echo ""

echo "📝 Quick Setup:"
echo "   1. On your Pi, open: http://vernis.local/settings-local.html"
echo "   2. Go to 🛠️ Developer Tools section"
echo "   3. Enter: $LOCAL_IP:$PORT"
echo "   4. Click 'Pull Development Update'"
echo ""

echo "🚀 Starting development file server..."
echo "   Press Ctrl+C to stop"
echo ""
echo "════════════════════════════════════════════"
echo ""

# Start the dev server
python3 dev-server.py $PORT
