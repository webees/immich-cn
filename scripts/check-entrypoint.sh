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
  local force_reload="${3:-1}"

  rm -rf "$work/build/geodata"
  mkdir -p "$work/build/geodata"

  local entrypoint_output
  entrypoint_output="$(PATH="$work/bin:$PATH" \
    IMMICH_BUILD_DATA="$work/build" \
    IMMICH_CN_GEODATA_DIR="$repo_root/build/geodata" \
    IMMICH_CN_LANGS_DIR="$repo_root/build/langs" \
    IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/patterns.tsv.gz" \
    IMMICH_CN_PATTERN="$pattern" \
    IMMICH_CN_FORCE_RELOAD="$force_reload" \
    bash "$repo_root/docker/entrypoint.sh" true 2>&1)"

  local actual
  actual="$(awk -F'\t' '$1==9100 {print $2}' "$work/build/geodata/cities500.txt")"
  if [ "$actual" != "$expected" ]; then
    echo "失败：pattern='$pattern' 期望 '$expected'，实际 '$actual'" >&2
    exit 1
  fi

  # 非默认粒度必须真的走完 apply-pattern 并打印匹配条数（防止"完成行没执行"被当成成功）
  if [ -n "$pattern" ] && [ "$pattern" != "{admin_2}" ]; then
    if ! printf '%s' "$entrypoint_output" | grep -q "已应用展示粒度.*匹配"; then
      echo "失败：未看到 apply-pattern 的完成输出：${entrypoint_output}" >&2
      exit 1
    fi
  fi

  local written expected_date
  written="$(cat "$work/build/geodata/geodata-date.txt")"
  if [ "$force_reload" = "1" ]; then
    # 强制刷新时必须写成当前时间（比较到分钟，避免跨秒误差）
    expected_date="$(date -u +%Y-%m-%dT%H:%M)"
    if [ "${written:0:16}" != "$expected_date" ]; then
      echo "失败：geodata-date.txt 未刷新为当前时间，实际 '$written'" >&2
      exit 1
    fi
  else
    # 未开启强制刷新时必须保留镜像内的原始时间
    local source_date
    source_date="$(cat "$repo_root/build/geodata/geodata-date.txt")"
    if [ "$written" != "$source_date" ]; then
      echo "失败：未开启强制刷新却改写了 geodata-date.txt（'$written' != '$source_date'）" >&2
      exit 1
    fi
  fi
  echo "通过：pattern='$pattern' force_reload=${force_reload} -> $actual"
}

run_case "" "苏州市" 1
run_case "{admin_2}" "苏州市" 0
run_case "{admin_2} {admin_3}" "苏州市 昆山市" 1

# 源目录缺失且目标为空时必须给出明确提示，
# 而不是被 bash 的 unbound variable 覆盖（多字节变量名陷阱的回归用例）。
missing_source_case() {
  local target="$work/missing/build/geodata"
  mkdir -p "$target"
  local output
  if output="$(IMMICH_BUILD_DATA="$work/missing/build" \
      IMMICH_CN_GEODATA_DIR="$work/does-not-exist" \
      IMMICH_CN_LANGS_DIR="$work/does-not-exist-langs" \
      IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/patterns.tsv.gz" \
      bash "$repo_root/docker/entrypoint.sh" true 2>&1)"; then
    echo "失败：源目录缺失时不应成功" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "无法写入"; then
    echo "失败：源目录缺失时未给出明确提示：${output}" >&2
    exit 1
  fi
  echo "通过：源目录缺失时给出明确错误提示"
}

missing_source_case

# 变体表与数据不匹配时必须失败，而不是"看起来成功但一字未改"。
mismatch_case() {
  local data="$work/mismatch/geodata"
  mkdir -p "$data"
  awk -F'\t' -v OFS='\t' '{ $1 = $1 + 900000000; print }' "$repo_root/build/geodata/cities500.txt" > "$data/cities500.txt"
  local output
  if output="$(PATH="$work/bin:$PATH" \
      IMMICH_BUILD_DATA="$work/mismatch/build" \
      IMMICH_CN_GEODATA_DIR="$data" \
      IMMICH_CN_LANGS_DIR="$work/mismatch/langs" \
      IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/patterns.tsv.gz" \
      IMMICH_CN_PATTERN='{admin_2} {admin_3}' \
      bash "$repo_root/docker/entrypoint.sh" true 2>&1)"; then
    echo "失败：变体表与数据不匹配时不应成功" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "没有匹配到任何条目"; then
    echo "失败：不匹配时未给出明确提示：${output}" >&2
    exit 1
  fi
  echo "通过：变体表与数据不匹配时明确失败"
}

mismatch_case

echo "入口脚本校验通过"
