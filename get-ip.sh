#!/bin/bash
##############################################
# Quick script to get your local IP address
# For use with the dev server
##############################################

echo ""
echo "🌐 Your Local IP Addresses:"
echo "================================"

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}'
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    hostname -I | tr ' ' '\n' | grep -v "^$"
else
    # Try to work on Windows Git Bash
    ipconfig | grep "IPv4" | awk '{print $NF}'
fi

echo "================================"
echo ""
echo "💡 Use one of these addresses with the dev server"
echo "   Example: 192.168.1.100:8080"
echo ""
