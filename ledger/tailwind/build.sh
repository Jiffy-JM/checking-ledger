#!/bin/sh
# Rebuild static/app.css from the templates. Needs Node (npx) on your Mac,
# only for this step -- nothing Node-related ships in the Docker image.
set -e
cd "$(dirname "$0")/.."
npx -y tailwindcss@3.4.17 -c tailwind/tailwind.config.js -i tailwind/input.css -o static/app.css --minify
