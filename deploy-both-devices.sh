#!/bin/bash
# Deploy all changed files to every known Pi.
# Skips devices that aren't reachable.

set -e
cd "$(dirname "$0")"

echo "=========================================="
echo "Deploying changed files to all devices"
echo "=========================================="

for script in deploy-afrol.sh deploy-afrom.sh deploy-afroz.sh; do
  echo ""
  echo "Running $script ..."
  bash "$script" || echo "   (skipped or failed)"
done

echo ""
echo "=========================================="
echo "Done."
echo "Tip: after pushing to git, you can also use the device's"
echo "     in-app Update feature instead of these scripts."
echo "=========================================="
