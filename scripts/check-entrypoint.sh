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
    IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
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
    expected_date="$(TZ=Asia/Shanghai date +%Y-%m-%dT%H:%M)"
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
      IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
      bash "$repo_root/docker/entrypoint.sh" true 2>&1)"; then
    echo "失败：源目录缺失时不应成功" >&2
    exit 1
  fi
  # 源目录缺失现在由"必需文件校验"更早拦下（比旧的"无法写入"提示更明确）
  if ! printf '%s' "$output" | grep -q "缺少必需文件"; then
    echo "失败：源目录缺失时未给出明确提示：${output}" >&2
    exit 1
  fi
  echo "通过：源目录缺失时给出明确错误提示"
}

missing_source_case

# 源目录与目标目录相同时应明确跳过复制，而不是误报“目标不可写”。
same_source_target_case() {
  local root="$work/same-source-target"
  mkdir -p "$root/build/geodata"
  cp -a "$repo_root/build/geodata/." "$root/build/geodata/"
  local output
  output="$(IMMICH_BUILD_DATA="$root/build" \
      IMMICH_CN_GEODATA_DIR="$root/build/geodata" \
      IMMICH_CN_LANGS_DIR="$repo_root/build/langs" \
      IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
      bash "$repo_root/docker/entrypoint.sh" true 2>&1)"
  if ! printf '%s' "$output" | grep -q "源目录与目标目录相同"; then
    echo "失败：源目录与目标目录相同时未给出明确提示：${output}" >&2
    exit 1
  fi
  echo "通过：源目录与目标目录相同时明确跳过复制"
}

same_source_target_case

# 目标目录不可写且没有现成数据时，必须给出"无法写入"提示（第 6 轮修过的分支）。
unwritable_target_case() {
  if [ "$(id -u)" = "0" ]; then
    echo "跳过：以 root 运行，文件权限不生效"
    return
  fi
  local root="$work/ro-target"
  mkdir -p "$root/geodata"
  # 让目标 geodata 目录本身不可写（只读挂载的效果），而不是它的父目录
  chmod 0555 "$root/geodata"
  local output
  if output="$(IMMICH_BUILD_DATA="$root" \
      IMMICH_CN_GEODATA_DIR="$repo_root/build/geodata" \
      IMMICH_CN_LANGS_DIR="$repo_root/build/langs" \
      IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
      bash "$repo_root/docker/entrypoint.sh" true 2>&1)"; then
    chmod 0755 "$root/geodata"
    echo "失败：目标不可写且无数据时不应成功" >&2
    exit 1
  fi
  chmod 0755 "$root/geodata"
  if ! printf '%s' "$output" | grep -q "无法写入"; then
    echo "失败：目标不可写时未给出「无法写入」提示：${output}" >&2
    exit 1
  fi
  echo "通过：目标不可写且无数据时给出明确错误"
}

unwritable_target_case

# 变体表与数据不匹配时必须失败，而不是"看起来成功但一字未改"。
mismatch_case() {
  local data="$work/mismatch/geodata"
  # 必须是"完整但版本不一致"的数据：只改 cities500 的 id，其余文件保持齐全，
  # 否则会被"必需文件校验"先拦下，测不到变体表不匹配这条路径。
  mkdir -p "$work/mismatch"
  cp -a "$repo_root/build/geodata" "$data"
  awk -F'\t' -v OFS='\t' '{ $1 = $1 + 900000000; print }' "$data/cities500.txt" > "$data/cities500.txt.shifted"
  mv "$data/cities500.txt.shifted" "$data/cities500.txt"
  local output
  if output="$(PATH="$work/bin:$PATH" \
      IMMICH_BUILD_DATA="$work/mismatch/build" \
      IMMICH_CN_GEODATA_DIR="$data" \
      IMMICH_CN_LANGS_DIR="$work/mismatch/langs" \
      IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
      IMMICH_CN_PATTERN='{admin_2} {admin_3}' \
      bash "$repo_root/docker/entrypoint.sh" true 2>&1)"; then
    echo "失败：变体表与数据不匹配时不应成功" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "仅匹配"; then
    echo "失败：不匹配时未给出明确提示：${output}" >&2
    exit 1
  fi
  echo "通过：变体表与数据不匹配时明确失败"
}

mismatch_case

# 只匹配部分地点同样是假成功：必须整表匹配，不能悄悄保留大多数错误粒度。
partial_match_case() {
  local data="$work/partial/geodata"
  mkdir -p "$data"
  cp "$repo_root/build/geodata/cities500.txt" "$data/cities500.txt"
  gzip -dc "$repo_root/dist/immich-cn-patterns-tsv-v1.gz" | head -n 2 > "$work/partial-table.tsv"

  local output
  if output="$(PATH="$work/bin:$PATH" \
      immich-cn-apply-pattern \
      --source "$data" \
      --table "$work/partial-table.tsv" \
      --pattern '{admin_2}' 2>&1)"; then
    echo "失败：变体表只匹配部分地点时不应成功" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "仅匹配"; then
    echo "失败：部分匹配时未给出明确提示：${output}" >&2
    exit 1
  fi
  echo "通过：变体表仅部分匹配时明确失败"
}

partial_match_case

# 源数据不完整时必须立刻失败，而不是把残缺数据复制进去让 Immich 报错。
incomplete_source_case() {
  local partial="$work/incomplete"
  mkdir -p "$partial"
  cp "$repo_root/build/geodata/cities500.txt" "$partial/cities500.txt"
  local output
  if output="$(IMMICH_BUILD_DATA="$work/incomplete/build" \
      IMMICH_CN_GEODATA_DIR="$partial" \
      IMMICH_CN_LANGS_DIR="$work/incomplete/langs" \
      IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
      bash "$repo_root/docker/entrypoint.sh" true 2>&1)"; then
    echo "失败：源数据不完整时不应成功" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "缺少必需文件"; then
    echo "失败：源数据不完整时未给出明确提示：${output}" >&2
    exit 1
  fi
  if [ -e "$work/incomplete/build/geodata/admin1CodesASCII.txt" ]; then
    echo "失败：源数据不完整时不应复制任何文件" >&2
    exit 1
  fi
  echo "通过：源数据不完整时拒绝启动"
}

# install.sh：langs 源缺失必须给出警告，而不是静默跳过。
install_missing_langs_case() {
  local output
  output="$(IMMICH_CN_GEODATA_DIR="$repo_root/build/geodata" \
    IMMICH_CN_LANGS_DIR="$work/missing-langs-dir" \
    sh "$repo_root/docker/install.sh" --target "$work/install-warn" 2>&1)"
  if ! printf '%s' "$output" | grep -q "警告：未找到国家名称目录"; then
    echo "失败：langs 源缺失时未告警：${output}" >&2
    exit 1
  fi
  if [ ! -f "$work/install-warn/geodata/cities500.txt" ]; then
    echo "失败：langs 缺失不应影响 geodata 释放" >&2
    exit 1
  fi
  echo "通过：langs 源缺失时给出警告并继续释放 geodata"
}

incomplete_source_case
install_missing_langs_case

# 参数缺少值时必须给出明确错误，不能被 set -u 的裸 $2 报错覆盖。
missing_option_value_case() {
  local output
  if output="$(sh "$repo_root/docker/install.sh" --target 2>&1)"; then
    echo "失败：install.sh 缺少 --target 参数时不应成功" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "缺少 --target 参数"; then
    echo "失败：install.sh 未给出明确参数错误：${output}" >&2
    exit 1
  fi

  if output="$(sh "$repo_root/docker/apply-pattern.sh" --source 2>&1)"; then
    echo "失败：apply-pattern.sh 缺少 --source 参数时不应成功" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "缺少 --source 参数"; then
    echo "失败：apply-pattern.sh 未给出明确参数错误：${output}" >&2
    exit 1
  fi
  echo "通过：缺失参数值给出明确错误"
}

root_target_case() {
  local output
  if output="$(IMMICH_CN_GEODATA_DIR="$repo_root/build/geodata" \
      sh "$repo_root/docker/install.sh" --target / 2>&1)"; then
    echo "失败：根目录必须被拒绝" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "不能是根目录"; then
    echo "失败：根目录目标未给出明确错误：${output}" >&2
    exit 1
  fi

  if output="$(sh "$repo_root/docker/apply-pattern.sh" \
      --source / \
      --table "$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
      --pattern '{admin_2}' 2>&1)"; then
    echo "失败：根目录 source 必须被拒绝" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -q "不能是根目录"; then
    echo "失败：根目录 source 未给出明确错误：${output}" >&2
    exit 1
  fi
  echo "通过：根目录 target/source 被拒绝"
}

missing_option_value_case
root_target_case

# 目标目录中的符号链接不能被 cp / cat 跟随，否则会写出目标目录之外。
symlink_target_case() {
  local root="$work/symlink-target"
  mkdir -p "$root/geodata"
  printf 'sentinel\n' > "$root/outside.txt"
  ln -s "$root/outside.txt" "$root/geodata/cities500.txt"

  IMMICH_BUILD_DATA="$root" \
    IMMICH_CN_GEODATA_DIR="$repo_root/build/geodata" \
    IMMICH_CN_LANGS_DIR="$repo_root/build/langs" \
    IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
    bash "$repo_root/docker/entrypoint.sh" true >/dev/null

  if [ "$(cat "$root/outside.txt")" != "sentinel" ]; then
    echo "失败：入口脚本跟随符号链接写出了目标目录" >&2
    exit 1
  fi
  if [ -L "$root/geodata/cities500.txt" ]; then
    echo "失败：入口脚本未替换危险的符号链接" >&2
    exit 1
  fi
  echo "通过：入口脚本不会跟随目标目录中的符号链接"
}

source_symlink_force_reload_case() {
  local root="$work/source-symlink"
  mkdir -p "$root"
  cp -a "$repo_root/build/geodata" "$root/source"
  cp -a "$repo_root/build/langs" "$root/langs"
  printf 'sentinel\n' > "$root/outside.txt"
  rm "$root/source/geodata-date.txt"
  ln -s "$root/outside.txt" "$root/source/geodata-date.txt"

  IMMICH_BUILD_DATA="$root/build" \
    IMMICH_CN_GEODATA_DIR="$root/source" \
    IMMICH_CN_LANGS_DIR="$root/langs" \
    IMMICH_CN_PATTERNS_TABLE="$repo_root/dist/immich-cn-patterns-tsv-v1.gz" \
    IMMICH_CN_FORCE_RELOAD=1 \
    bash "$repo_root/docker/entrypoint.sh" true >/dev/null

  if [ "$(cat "$root/outside.txt")" != "sentinel" ]; then
    echo "失败：强制刷新跟随了源数据中的符号链接" >&2
    exit 1
  fi
  if [ -L "$root/build/geodata/geodata-date.txt" ]; then
    echo "失败：强制刷新后仍保留危险符号链接" >&2
    exit 1
  fi
  echo "通过：源数据符号链接不会被强制刷新跟随"
}

install_readme_symlink_case() {
  local root="$work/install-readme"
  mkdir -p "$root/out"
  printf 'sentinel\n' > "$root/outside.txt"
  ln -s "$root/outside.txt" "$root/out/README.md"

  IMMICH_CN_GEODATA_DIR="$repo_root/build/geodata" \
    IMMICH_CN_LANGS_DIR="$repo_root/build/langs" \
    sh "$repo_root/docker/install.sh" --target "$root/out" >/dev/null

  if [ "$(cat "$root/outside.txt")" != "sentinel" ]; then
    echo "失败：install.sh 跟随符号链接写出了目标目录" >&2
    exit 1
  fi
  if [ -L "$root/out/README.md" ]; then
    echo "失败：install.sh 未替换危险的符号链接" >&2
    exit 1
  fi
  echo "通过：install.sh 不会跟随目标目录中的符号链接"
}

symlink_target_case
source_symlink_force_reload_case
install_readme_symlink_case

echo "入口脚本校验通过"
