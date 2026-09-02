#!/usr/bin/env bash
# Put the machine into recording state, in one command.
#
# The point is that take two looks exactly like take one. Three things have to be
# identical every time or the script's timestamps drift: the stack must be UP and
# HEALTHY before the browser opens (a recording that starts on a spinner is a retake),
# the core must already hold history (an empty dashboard reads as broken), and the
# window must be the same width (the layout is responsive, so a different width moves
# every panel and invalidates the scroll timings).
set -euo pipefail

VIEWPORT_W="${VIEWPORT_W:-1440}"
VIEWPORT_H="${VIEWPORT_H:-900}"
URL="${URL:-http://localhost:3000/demo?pace=slow}"
CORE="${CORE:-http://localhost:8000}"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

say "bringing the stack up"
docker compose up -d --build >/dev/null

say "waiting for health (core, three connectors, web)"
for endpoint in "$CORE/health" \
                "http://localhost:8101/health" \
                "http://localhost:8102/health" \
                "http://localhost:8103/health" \
                "http://localhost:3000"; do
  for attempt in $(seq 1 90); do
    if curl -sf -o /dev/null "$endpoint"; then
      printf '    ok  %s\n' "$endpoint"; break
    fi
    if [ "$attempt" -eq 90 ]; then
      printf '    !!  %s never came up\n' "$endpoint" >&2
      docker compose ps
      exit 1
    fi
    sleep 2
  done
done

# The demo itself files two incidents, but a reviewer opening a cold dashboard sees an
# empty correlations table until it does. Seed only when the core has nothing, so a
# second take does not pile up duplicate history.
submissions=$(curl -sf "$CORE/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["submissions"])')
if [ "$submissions" -eq 0 ]; then
  say "core is empty — seeding history"
  python3 deploy/seed_history.py >/dev/null
else
  say "core already holds $submissions submission(s) — not re-seeding"
fi

correlations=$(curl -sf "$CORE/v1/correlations" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
say "core: $(curl -sf "$CORE/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["submissions"])') submissions, $correlations correlation(s)"

say "opening $URL at ${VIEWPORT_W}x${VIEWPORT_H}"
case "$(uname -s)" in
  Darwin)
    # A dedicated window at a fixed size. --app drops the tab strip and omnibox, so
    # the frame is the same every take and the recording has no browser chrome in it.
    for chrome in \
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
      if [ -x "$chrome" ]; then
        "$chrome" --new-window --app="$URL" \
                  --window-size="${VIEWPORT_W},${VIEWPORT_H}" --window-position=0,0 \
                  >/dev/null 2>&1 &
        opened=1; break
      fi
    done
    [ "${opened:-0}" = 1 ] || { say "Chrome not found — open $URL manually at ${VIEWPORT_W}px"; }
    ;;
  *)
    xdg-open "$URL" >/dev/null 2>&1 || say "open $URL manually at ${VIEWPORT_W}px"
    ;;
esac

cat <<'READY'

    READY. Do not click yet.

      1. Start the screen capture.
      2. Hold ~10s on the header and the six-step rail.
      3. Click "▶ Run the guided demo" and do not touch anything for ~52s.
      4. Scroll through the panels as they settle; close on the boundary columns.

    Full shot list with timestamps: docs/recording.md
    When you are done:  docker compose down -v
READY
