#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /protected/path/coordinator.env" >&2
  exit 2
fi

ENV_FILE=$1
if [ ! -f "$ENV_FILE" ]; then
  echo "protected coordinator environment file is missing" >&2
  exit 2
fi

MODE=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%Lp' "$ENV_FILE")
case "$MODE" in
  600|400) ;;
  *)
    echo "environment file permissions must be 0600 or 0400" >&2
    exit 2
    ;;
esac

sha256sum -c SHA256SUMS
docker load --input artifacts/coordinator-arm64-image/rarelink-coordinator-arm64.tar
docker load --input artifacts/web-arm64-image/rarelink-web-arm64.tar

echo "Images loaded and bundle checksums verified."
echo "Review the environment file, provision external volumes and protected mounts,"
echo "then run:"
echo "docker compose --env-file $ENV_FILE -f deploy/offline/compose.yml up -d"
