#!/bin/sh
# Starts the frontend in Docker (see docker-compose.yml). npm install takes about a minute,
# so it only runs when package.json or package-lock.json changed since the last install.
set -e

stamp=node_modules/.installed-from
current=$(sha256sum package.json package-lock.json)

if [ "$current" != "$(cat "$stamp" 2>/dev/null)" ]; then
  npm install
  echo "$current" > "$stamp"
else
  echo "Packages unchanged since the last install; skipping npm install."
fi

exec npm run dev -- --hostname 0.0.0.0
