#!/usr/bin/env bash
# Ask APIHUB which nodes already exist, before anything is created.
#
#   bash "$SKILL_DIR/scripts/check_ids.sh" --parent <parentId>
#   bash "$SKILL_DIR/scripts/check_ids.sh" <plan-dir>
#
# --parent checks the target parent alone and is the first request of the whole
# flow. Every id in a plan is computed from that parent, so a parent that is
# missing, moved, or not a container makes the entire plan void — and one GET
# answers that before a tree is walked, request bodies are written, or fifty
# further ids are asked about.
#
# <plan-dir> checks the parent and every id in <plan-dir>/plan.tsv, writing
# <plan-dir>/status.tsv as: packageId <tab> http <tab> kind
# Fold it back into the table with: plan_tree.py <same args> --status
#
# A node's id is always parentId + "." + alias, so the expected id is computable
# and fetched directly — there is no search step and no pagination.
#
# Redirects are NOT followed (no -L). A 301 means the id was renamed or moved,
# which is a different answer from "it exists" and must reach the user as one.
#
# Exit codes:
#   0  --parent: the parent exists and can hold nodes.
#      <plan-dir>: every id answered 200 or 404 — render the plan and confirm it.
#   1  something needs a human. When the server sent a body it is kept next to
#      the run (parent.json, or <plan-dir>/get-<idx>.json) — render it and stop.
#      A 301 and a dead connection carry no body; there the status line is the
#      whole answer.
#   2  cannot run as given: bad arguments, no plan, or no url= / no credential

usage="usage: check_ids.sh --parent <parentId>  |  check_ids.sh <plan-dir>"

if [ "$1" = "--parent" ]; then
  parent=$2
  [ -n "$parent" ] || { echo "$usage"; exit 2; }
  dir=""
else
  dir=$1
  [ -n "$dir" ] || { echo "$usage"; exit 2; }
  [ -f "$dir/plan.tsv" ] || { echo "no plan: $dir/plan.tsv — run plan_tree.py first"; exit 2; }
  [ -s "$dir/plan.tsv" ] || { echo "nothing planned in $dir/plan.tsv"; exit 2; }
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/apihub_env.sh"

http=""
kind=""

# GET one id, leaving the body in $2. Sets $http and $kind, and prints the line
# the user reads. kind is matched against a closed whitelist so a body that is
# not a package object cannot be mistaken for one.
ask() {
  local id=$1 out=$2 body compact
  http=$(curl -sS -o "$out" -w '%{http_code}' \
    "$base/api/v2/packages/$id" \
    -H "$hdr: $tok" < /dev/null)

  kind="-"
  if [ "$http" = 200 ]; then
    body=$(<"$out")
    compact=${body//[[:space:]]/}
    case "$compact" in
      *'"kind":"workspace"'*) kind=workspace ;;
      *'"kind":"group"'*)     kind=group ;;
      *'"kind":"package"'*)   kind=package ;;
      *'"kind":"dashboard"'*) kind=dashboard ;;
    esac
  fi
  echo "$http $kind $id"
}

if [ -n "$parent" ]; then
  ask "$parent" parent.json
  case "$http $kind" in
    "200 workspace" | "200 group")
      rm -f parent.json
      exit 0 ;;
    "200 package" | "200 dashboard")
      echo "$parent is a $kind — groups and packages are created under a workspace or a group"
      exit 1 ;;
    "404 "*)
      echo "$parent does not exist — name an existing workspace or group, and note that this skill"
      echo "does not create workspaces"
      exit 1 ;;
    "301 "*)
      echo "$parent redirects elsewhere; it was renamed or moved. Confirm the current id first —"
      echo "every id in the plan would be computed from this one"
      exit 1 ;;
    *)
      # A connection that never answered reports 000 and leaves no body behind,
      # which is a different problem from a server that answered unhelpfully.
      if [ -s parent.json ]; then
        echo "$parent could not be checked; the response is in parent.json"
      else
        rm -f parent.json
        echo "no response from $base — check the url= in your config, and that the host is reachable"
      fi
      exit 1 ;;
  esac
fi

rc=0
: > "$dir/status.tsv"

# The parent is the parentId of any depth-1 row; they all share it. It is asked
# about again here so status.tsv stands on its own — create_plan.sh reads it
# without assuming any earlier command ran.
parent=""
while IFS=$'\t' read -r idx depth planned alias pkgid parentid name relpath || [ -n "$idx" ]; do
  [ "$depth" = 1 ] && { parent=$parentid; break; }
done < "$dir/plan.tsv"
[ -n "$parent" ] || { echo "no top-level row in $dir/plan.tsv"; exit 2; }

record() {
  printf '%s\t%s\t%s\n' "$1" "$http" "$kind" >> "$dir/status.tsv"
  case "$http" in
    200|404) rm -f "$2" ;;
    # Keep the body only when there is one — a 000 leaves an empty file, and a
    # message pointing at an empty file sends the reader looking for nothing.
    *) [ -s "$2" ] || rm -f "$2"; rc=1 ;;
  esac
}

ask "$parent" "$dir/get-parent.json"
record "$parent" "$dir/get-parent.json"

while IFS=$'\t' read -r idx depth planned alias pkgid parentid name relpath || [ -n "$idx" ]; do
  [ -n "$pkgid" ] || continue
  ask "$pkgid" "$dir/get-$idx.json"
  record "$pkgid" "$dir/get-$idx.json"
done < "$dir/plan.tsv"

exit "$rc"
