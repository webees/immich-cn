#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "用法：docker-imagetools-inspect-retry.sh <image> <format>" >&2
  exit 2
fi

image="$1"
format="$2"
max_attempts=3
base_delay="${DOCKER_RETRY_BASE_DELAY_SECONDS:-5}"
if ! [[ "$base_delay" =~ ^[0-9]+$ ]]; then
  echo "DOCKER_RETRY_BASE_DELAY_SECONDS 必须是非负整数" >&2
  exit 2
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
attempt=1

while true; do
  stdout_file="$tmp_dir/stdout"
  stderr_file="$tmp_dir/stderr"
  if docker buildx imagetools inspect "$image" --format "$format" >"$stdout_file" 2>"$stderr_file"; then
    [ ! -s "$stderr_file" ] || cat "$stderr_file" >&2
    cat "$stdout_file"
    exit 0
  else
    status=$?
  fi

  [ ! -s "$stderr_file" ] || cat "$stderr_file" >&2
  if ! grep -Eqi \
    '(429|too many requests| 50[0-9] |bad gateway|gateway timeout|service unavailable|timed out|timeout|connection reset|temporar)' \
    "$stderr_file"; then
    exit "$status"
  fi
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "docker imagetools inspect 连续失败 ${max_attempts} 次：${image}" >&2
    exit "$status"
  fi

  delay=$((base_delay * (1 << (attempt - 1))))
  echo "::warning::docker imagetools inspect 瞬时限流，${delay} 秒后重试（${attempt}/${max_attempts}）：${image}" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done
