#!/bin/bash
# build_site.sh — assemble a static copy of the dashboards plus one project's
# night artifacts, for GitHub Pages (or any file server).
#
#   scripts/build_site.sh [project-dir] [out-dir]
#
# Layout mirrors the repo so web/shared.js's relative paths (../<project>/logs/)
# resolve the same way they do under `python3 -m http.server` at the root.

set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT="${1:-${BULLWHIP_PROJECT_DIR:-examples/github-health}}"
OUT="${2:-site}"

rm -rf "$OUT"
mkdir -p "$OUT/web" "$OUT/$PROJECT"
cp web/*.html web/*.js "$OUT/web/"
if [ -d "$PROJECT/logs" ]; then
    cp -R "$PROJECT/logs" "$OUT/$PROJECT/logs"
else
    mkdir -p "$OUT/$PROJECT/logs"
    echo "[]" > "$OUT/$PROJECT/logs/index.json"
fi

# Pages serves an index at the root; send it to the picker for this project.
cat > "$OUT/index.html" <<EOF
<!doctype html>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=web/index.html?project=${PROJECT}">
<title>bullwhip</title>
<a href="web/index.html?project=${PROJECT}">bullwhip dashboards</a>
EOF

# GitHub Pages runs Jekyll by default, which drops files it does not like.
touch "$OUT/.nojekyll"

echo "site: $OUT ($(find "$OUT" -type f | wc -l | tr -d ' ') files, $(du -sh "$OUT" | cut -f1))"
