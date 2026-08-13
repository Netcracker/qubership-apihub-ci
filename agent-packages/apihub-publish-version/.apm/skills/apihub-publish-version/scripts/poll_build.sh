#!/usr/bin/env bash
# Poll one publish until it reaches a terminal status, or until this window elapses.
#
#   bash "$SKILL_DIR/scripts/poll_build.sh" <packageId> <publishId> [window_seconds]
#
# Keep window_seconds (default 240) comfortably below your own command timeout: a large
# build runs far longer than one invocation may, so the build is covered by repeating
# this command, not by lengthening it.
#
# Writes the most recent response body to ./status.json, so a failed request can be
# rendered with the error recipe in reference.md.
#
# Exit codes:
#   0  terminal status reached (complete or error) — stop polling and report it
#   1  the status request itself failed — render status.json and stop; repeating will not help
#   2  cannot run as given: bad arguments, or no url= / no credential — the message says which
#   3  the window elapsed and the build is still going — run the identical command again

pkg=$1
pub=$2
WINDOW=${3:-240}

[ -n "$pkg" ] && [ -n "$pub" ] || {
  echo "usage: poll_build.sh <packageId> <publishId> [window_seconds]"
  exit 2
}
case "$WINDOW" in
  '' | *[!0-9]*) echo "window_seconds must be a positive integer, got: $WINDOW"; exit 2 ;;
esac

# Resolve this script's own directory so the prelude is found however the script is
# invoked. A failing prelude exits 2 from here, which is the documented code.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/apihub_env.sh"

END=$(( $(date +%s) + WINDOW ))
delay=2

while :; do
  # Remove the previous body first, so a failed write cannot be re-read as current.
  rm -f status.json
  http=$(curl -sS -o status.json -w '%{http_code}' \
    "$base/api/v2/packages/$pkg/publish/$pub/status" \
    -H "$hdr: $tok")
  # 000 is a connection that never answered — transient over ~60 requests, so keep polling.
  case "$http" in
    200|000) ;;
    *) echo "$(date +%H:%M:%S) status request failed, HTTP $http"; exit 1 ;;
  esac

  # Closed whitelist of the four build statuses: an HTTP error body such as
  # {"status":404,...} matches none of them and falls through to unreadable, rather
  # than passing as a build that has simply not finished yet.
  body=$(<status.json)
  compact=${body//[[:space:]]/}
  case "$compact" in
    *'"status":"complete"'*) s=complete ;;
    *'"status":"error"'*)    s=error ;;
    *'"status":"running"'*)  s=running ;;
    *'"status":"none"'*)     s=none ;;
    *)                       s=unreadable ;;
  esac
  echo "$(date +%H:%M:%S) $s"
  case "$s" in complete|error) exit 0 ;; esac

  now=$(date +%s)
  [ "$now" -ge "$END" ] && exit 3
  # Backoff doubles to a 30s ceiling, never overshooting the end of the window.
  nap=$delay
  [ $(( END - now )) -lt "$nap" ] && nap=$(( END - now ))
  sleep "$nap"
  delay=$(( delay * 2 ))
  [ "$delay" -gt 30 ] && delay=30
done
