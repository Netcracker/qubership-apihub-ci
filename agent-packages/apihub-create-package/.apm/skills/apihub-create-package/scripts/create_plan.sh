#!/usr/bin/env bash
# Create a confirmed plan, top-down, one node per POST.
#
#   bash "$SKILL_DIR/scripts/create_plan.sh" <plan-dir>
#
# Reads <plan-dir>/plan.tsv and <plan-dir>/status.tsv. Nodes that already exist
# with the planned kind are reused, not re-created. Everything else is POSTed
# from its <plan-dir>/body-<idx>.json, which plan_tree.py wrote — so the folder
# name reaches the server exactly as it is on disk, without passing through a
# shell string.
#
# Run it only on a plan the user has seen and confirmed. It refuses to start
# when the existence check reports anything the user has not resolved, because
# the preview is the only thing standing between a tree walk and fifty nodes
# nobody asked for.
#
# A failed create takes its descendants with it — their parent does not exist —
# but unrelated branches keep going, so one bad node does not block fifty good
# ones elsewhere in the tree. Nothing is ever retried with an altered alias or
# parent: a create that only succeeded after a silent change is a wrong create,
# not a recovered one.
#
# Exit codes:
#   0  every node was created or reused
#   1  at least one node failed; its body is in <plan-dir>/error-<idx>.json —
#      render it, fix the cause, and re-run. Re-running is safe: what exists is
#      reused, so only the failed branch is retried.
#   2  cannot run as given: bad arguments, no plan, an unresolved existence
#      check, or no url= / no credential

dir=$1

[ -n "$dir" ] || { echo "usage: create_plan.sh <plan-dir>"; exit 2; }
[ -f "$dir/plan.tsv" ] || { echo "no plan: $dir/plan.tsv — run plan_tree.py first"; exit 2; }
[ -s "$dir/plan.tsv" ] || { echo "nothing planned in $dir/plan.tsv"; exit 2; }
[ -f "$dir/status.tsv" ] || { echo "no existence check: $dir/status.tsv — run check_ids.sh"; exit 2; }

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/apihub_env.sh"

sep=$'\037'
blocked="$sep"

# Print "<http> <kind>" for one id, or "- -" when the check does not mention it.
status_of() {
  local want=$1 sid shttp skind
  while IFS=$'\t' read -r sid shttp skind || [ -n "$sid" ]; do
    if [ "$sid" = "$want" ]; then
      echo "$shttp $skind"
      return
    fi
  done < "$dir/status.tsv"
  echo "- -"
}

# Refuse to start on anything the user has not resolved. Every one of these was
# already shown in the preview; reaching them here means the plan moved on
# without them.
parent=""
while IFS=$'\t' read -r idx depth kind alias pkgid parentid name relpath || [ -n "$idx" ]; do
  [ "$depth" = 1 ] && { parent=$parentid; break; }
done < "$dir/plan.tsv"
[ -n "$parent" ] || { echo "no top-level row in $dir/plan.tsv"; exit 2; }

set -- $(status_of "$parent")
case "$1 $2" in
  "200 workspace" | "200 group") ;;
  *) echo "target parent $parent is not a usable parent (HTTP $1, kind $2) — re-check the plan"
     exit 2 ;;
esac

while IFS=$'\t' read -r idx depth kind alias pkgid parentid name relpath || [ -n "$idx" ]; do
  [ -n "$pkgid" ] || continue
  set -- $(status_of "$pkgid")
  case "$1" in
    404) ;;
    200) [ "$2" = "$kind" ] || {
           echo "$pkgid already exists as $2, not $kind — resolve it before creating anything"
           exit 2
         } ;;
    *) echo "$pkgid was not checked cleanly (HTTP $1) — re-run check_ids.sh"
       exit 2 ;;
  esac
done < "$dir/plan.tsv"

created=0
reused=0
failed=0
skipped=0
rc=0

while IFS=$'\t' read -r idx depth kind alias pkgid parentid name relpath || [ -n "$idx" ]; do
  [ -n "$pkgid" ] || continue

  case "$blocked" in
    *"$sep$parentid$sep"*)
      echo "blocked  $pkgid"
      blocked="$blocked$pkgid$sep"
      skipped=$((skipped + 1))
      rc=1
      continue ;;
  esac

  set -- $(status_of "$pkgid")
  if [ "$1" = 200 ]; then
    echo "reused   $pkgid"
    reused=$((reused + 1))
    continue
  fi

  http=$(curl -sS -o "$dir/error-$idx.json" -w '%{http_code}' -X POST \
    "$base/api/v2/packages" \
    -H "$hdr: $tok" \
    -H "Content-Type: application/json" \
    --data-binary @"$dir/body-$idx.json" < /dev/null)

  case "$http" in
    2??)
      rm -f "$dir/error-$idx.json"
      echo "created  $pkgid"
      created=$((created + 1)) ;;
    *)
      echo "failed   $pkgid (HTTP $http, body in $dir/error-$idx.json)"
      blocked="$blocked$pkgid$sep"
      failed=$((failed + 1))
      rc=1 ;;
  esac
done < "$dir/plan.tsv"

echo ""
echo "created $created, reused $reused, failed $failed, blocked by a failed parent $skipped"
exit "$rc"
