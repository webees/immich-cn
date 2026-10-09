#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "用法：docker-pull-retry.sh <image>..." >&2
  exit 2
fi

for image in "$@"; do
  attempt=1
  while ! docker pull "$image"; do
    if [ "$attempt" -ge 3 ]; then
      echo "::error::拉取 ${image} 连续 3 次失败" >&2
      exit 1
    fi
    sleep $((attempt * 15))
    attempt=$((attempt + 1))
  done
done
