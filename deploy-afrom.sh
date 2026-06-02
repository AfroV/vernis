#!/bin/bash
# Deploy all changed files to afrom (10.0.0.39).
# Password is read from secrets.env (gitignored). See secrets.env.template.
set -e
cd "$(dirname "$0")"

[ -f secrets.env ] || { echo "secrets.env missing; copy secrets.env.template" >&2; exit 1; }
set -a; . ./secrets.env; set +a
PASS="${VERNIS_PASS_afrom:?VERNIS_PASS_afrom not set in secrets.env}"

bash deploy/deploy-pi.sh 10.0.0.39 afrom "$PASS"
