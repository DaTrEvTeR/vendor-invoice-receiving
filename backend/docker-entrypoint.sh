#!/bin/sh
# Run the command as the owner of the bind-mounted project files, so what the app writes
# there (backend/db.sqlite3, results/outcomes.json) is owned by the developer on any host.
#
#   - Linux, rootful Docker: the files belong to your uid (1000 or any other); run as it.
#   - Docker Desktop (macOS, Windows): mounts look root-owned but any user may write;
#     run as the unprivileged "app" user.
#   - Rootless Docker or Podman: mounts look root-owned and only container root maps to
#     you on the host; stay root (it has no privileges outside the container).
set -eu

if [ "$(id -u)" != "0" ]; then
    exec "$@"  # started with an explicit --user: respect it
fi

owner_uid=$(stat -c %u /app)
owner_gid=$(stat -c %g /app)

if [ "$owner_uid" != "0" ]; then
    export HOME=/tmp  # the developer's uid has no home directory in the image
    exec setpriv --reuid="$owner_uid" --regid="$owner_gid" --clear-groups "$@"
fi

if setpriv --reuid=app --regid=app --init-groups test -w /app; then
    export HOME=/home/app
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"
