#!/bin/sh
set -eu
expected=$(cat /usr/share/nginx/html/build-id.txt)
attempt=0
while [ "$attempt" -lt 30 ]; do
    actual=$(wget -q -T 2 -O - http://public-pages:8081/__public-pages/build 2>/dev/null || true)
    if [ "$actual" = "$expected" ]; then
        exec nginx -g 'daemon off;'
    fi
    attempt=$((attempt + 1))
    sleep 1
done
echo 'Public page/client build mismatch or service unavailable' >&2
exit 1
