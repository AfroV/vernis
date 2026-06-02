#!/usr/bin/env python3
"""
Vernis Development File Server
Run this on your development machine to serve files to the Pi for testing
Usage: python3 dev-server.py [port]
"""
import http.server
import socketserver
import sys
import os

# Change to the vernisv3 directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS for easier API access
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def log_message(self, format, *args):
        # Colorful logging
        print(f"\033[92m[DEV SERVER]\033[0m {format % args}")

print("\n" + "="*60)
print("🚀 Vernis Development File Server")
print("="*60)
print(f"\nServing files from: {os.getcwd()}")
print(f"Server running at: http://0.0.0.0:{PORT}")
print(f"\nOn your Pi, run:")
print(f"  sudo bash /opt/vernis/scripts/dev-update.sh YOUR_DEV_MACHINE_IP:{PORT}")
print("\nOr use the settings page update endpoint.")
print("\nPress Ctrl+C to stop\n")

with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n✅ Development server stopped")
        sys.exit(0)
