#!/bin/sh
# Netlify build step: write js/config.js from the APEXRX_API_BASE environment
# variable (the backend URL, for example https://apexrx-api.onrender.com).
# Fails the deploy if the variable is missing or malformed, so a site that
# cannot reach its API is never published.
set -eu

base="${APEXRX_API_BASE:-}"
base="${base%/}"

if [ -z "$base" ]; then
  echo "ERROR: set APEXRX_API_BASE in Netlify (Site configuration > Environment variables)." >&2
  exit 1
fi

# Only a plain https URL (http allowed for localhost testing): this value is
# written into JavaScript, so nothing else is accepted.
if ! printf '%s' "$base" | grep -Eq '^(https://[A-Za-z0-9.-]+(:[0-9]+)?|http://(localhost|127\.0\.0\.1)(:[0-9]+)?)(/[A-Za-z0-9._~/-]*)?$'; then
  echo "ERROR: APEXRX_API_BASE must be an https URL like https://apexrx-api.onrender.com (got: $base)" >&2
  exit 1
fi

cd "$(dirname "$0")/.."
printf "/* Generated at deploy time by scripts/write-config.sh. */\nwindow.APEXRX_API_BASE = '%s';\n" "$base" > js/config.js
echo "API base set to $base"
