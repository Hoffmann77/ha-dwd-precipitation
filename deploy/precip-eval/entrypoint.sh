#!/bin/sh
# Start as root only to hand the data directory to the service's user
# (PRECIP_EVAL_UID/GID), which Docker may have created as root, then drop to
# that user for good.
set -eu
uid="${PRECIP_EVAL_UID:-1000}"
gid="${PRECIP_EVAL_GID:-1000}"
if [ "$(id -u)" = 0 ]; then
    chown "$uid:$gid" /data
    exec setpriv --reuid="$uid" --regid="$gid" --clear-groups "$@"
fi
exec "$@"
