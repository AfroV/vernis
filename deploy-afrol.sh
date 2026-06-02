#!/bin/bash
# Deploy all changed files to afrol (10.0.0.28).
# Password is read from secrets.env (gitignored). See secrets.env.template.
set -e
cd "$(dirname "$0")"

[ -f secrets.env ] || { echo "secrets.env missing; copy secrets.env.template" >&2; exit 1; }
set -a; . ./secrets.env; set +a
PASS="${VERNIS_PASS_afrol:?VERNIS_PASS_afrol not set in secrets.env}"

bash deploy/deploy-pi.sh 10.0.0.28 afrol "$PASS"
