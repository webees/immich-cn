#!/usr/bin/env bash
# 校验 docker/entrypoint.sh：模拟 /build 目录，确认默认粒度与显式粒度都能正确注入。
#
# 依赖：先执行 `python -m scripts.smoke_data` 生成 build/ 与 dist/。
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT INT TERM

mkdir -p "$work/bin" "$work/build/geodata"
ln -sf "$repo_root/docker/apply-pattern.sh" "$work/bin/immich-cn-apply-pattern"

run_case() {
  local pattern="$1"
  local expected="$2"

  rm -rf "$work/build/geodata"
  mkdir -p "$work/build/geodata"

  PATH="$work/bin:$PATH" \
    IMMICH_BUILD_DATA="$work/build" \
    IMMICH_CN_GEODATA_DIR="$repo_root/build/geodata" \
    IMMICH_CN_LANGS_DIR="$repo_root/build/langs" \
    IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/patterns.tsv.gz" \
    IMMICH_CN_PATTERN="$pattern" \
    IMMICH_CN_FORCE_RELOAD=1 \
    bash "$repo_root/docker/entrypoint.sh" true

  local actual
  actual="$(awk -F'\t' '$1==9100 {print $2}' "$work/build/geodata/cities500.txt")"
  if [ "$actual" != "$expected" ]; then
    echo "失败：pattern='$pattern' 期望 '$expected'，实际 '$actual'" >&2
    exit 1
  fi
  if ! grep -q . "$work/build/geodata/geodata-date.txt"; then
    echo "失败：未写入 geodata-date.txt" >&2
    exit 1
  fi
  echo "通过：pattern='$pattern' -> $actual"
}

run_case "" "苏州市"
run_case "{admin_2}" "苏州市"
run_case "{admin_2} {admin_3}" "苏州市 昆山市"

echo "入口脚本校验通过"
