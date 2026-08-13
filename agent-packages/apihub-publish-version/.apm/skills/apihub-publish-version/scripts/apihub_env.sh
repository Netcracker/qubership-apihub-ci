# Shared prelude for every APIHub request in this skill.
#
#   . "$SKILL_DIR/scripts/apihub_env.sh"
#
# Sets: base (APIHub URL, no trailing slash), cred (credential file path),
#       hdr (auth header name), tok (the token).
# Exits 2 with a message when the configuration is unusable.
#
# Source it, do not execute it — an executed copy sets the variables in a
# subshell that dies immediately.
#
# Requires bash (uses $'\r'). Parses with shell builtins only, so nothing is
# assumed about which text utilities a given Git for Windows install carries.
#
# $HOME resolves the same way on macOS, Linux and Git Bash, with $USERPROFILE
# as the fallback: a Git Bash that reads no startup file may have no HOME at
# all, while Windows puts USERPROFILE in every process environment.
apihub="${HOME:-$USERPROFILE}/.apihub"
[ -f "$apihub/config" ] || { echo "no config file: $apihub/config"; exit 2; }
base=""
while IFS='=' read -r k v || [ -n "$k" ]; do
  [ "$k" = url ] && base="${v%$'\r'}"
done < "$apihub/config"
base="${base%/}"
[ -n "$base" ] || { echo "no url= in $apihub/config"; exit 2; }
cred="$apihub/pat"; hdr="X-Personal-Access-Token"
[ -f "$cred" ] || { cred="$apihub/api-key"; hdr="api-key"; }
[ -f "$cred" ] || { echo "no credential file: $apihub/pat"; exit 2; }
IFS= read -r tok < "$cred"; tok="${tok%$'\r'}"
[ -n "$tok" ] || { echo "empty credential file: $cred"; exit 2; }
