#!/bin/bash
# Immich 镜像入口包装：注入中文 geodata 后再执行原始启动命令。
set -euo pipefail

build_root="${IMMICH_BUILD_DATA:-/build}"
target="${build_root%/}/geodata"
source_dir="${IMMICH_CN_GEODATA_DIR:-/opt/immich-cn/geodata}"
langs_dir="${IMMICH_CN_LANGS_DIR:-/opt/immich-cn/i18n-iso-countries/langs}"
patterns_table="${IMMICH_CN_PATTERNS_TABLE:-/opt/immich-cn/immich-cn-patterns-tsv-v1.gz}"
# 注意：默认值里不要直接写 {admin_2}，bash 会在第一个 } 处结束参数展开，
# 导致显式设置 IMMICH_CN_PATTERN 时多出一个右花括号。
pattern="${IMMICH_CN_PATTERN:-}"
if [ -z "$pattern" ]; then
  pattern='{admin_2}'
fi

# Immich 导入需要这 6 个文件；源数据不完整时必须立刻报错，
# 否则容器会带着残缺数据启动，问题被推迟到 Immich 导入阶段才暴露。
REQUIRED_FILES="admin1CodesASCII.txt admin2Codes.txt cities500.txt countryInfo.txt geodata-date.txt ne_10m_admin_0_countries.geojson"
missing_required_files() {
  local dir="$1"
  local missing=""
  local name
  for name in $REQUIRED_FILES; do
    if [ ! -s "$dir/$name" ]; then
      missing="${missing} ${name}"
    fi
  done
  printf '%s' "$missing"
}

missing_files="$(missing_required_files "$source_dir")"
if [ -n "$missing_files" ]; then
  echo "immich-cn: 数据源缺少必需文件或文件为空：${missing_files# }" >&2
  echo "immich-cn: 请检查 IMMICH_CN_GEODATA_DIR=${source_dir}" >&2
  exit 1
fi

mkdir -p "$target"

# 目标目录可能来自宿主机挂载；先移除同名符号链接，避免 cp 跟随链接写出目录。
for source_path in "$source_dir"/*; do
  [ -e "$source_path" ] || [ -L "$source_path" ] || continue
  destination="$target/${source_path##*/}"
  if [ -L "$destination" ]; then
    if ! rm -f "$destination"; then
      echo "immich-cn: 无法安全替换符号链接 ${destination}" >&2
      exit 1
    fi
  fi
done

if [ "$source_dir" = "$target" ]; then
  echo "immich-cn: 源目录与目标目录相同，跳过复制，直接使用 ${target}" >&2
elif ! cp -a "$source_dir/." "$target/" 2>/dev/null; then
  # 用户可能把 /build/geodata 以只读方式挂载进来
  target_missing="$(missing_required_files "$target")"
  if [ -z "$target_missing" ]; then
    echo "immich-cn: ${target} 不可写，沿用其中已有的 geodata" >&2
  else
    echo "immich-cn: 无法写入 ${target}，且现有 geodata 缺少必需文件或文件为空：${target_missing# }" >&2
    exit 1
  fi
fi

# 旧版 Immich 通过 i18n-iso-countries 读取国家名，存在时才覆盖 en.json。
for candidate in \
  /usr/src/app/server/node_modules/i18n-iso-countries/langs \
  /usr/src/app/node_modules/i18n-iso-countries/langs; do
  if [ -d "$candidate" ] && [ -f "$langs_dir/en.json" ]; then
    cp -f "$langs_dir/en.json" "$candidate/en.json"
  fi
done

if [ "$pattern" != "{admin_2}" ]; then
  immich-cn-apply-pattern --source "$target" --table "$patterns_table" --pattern "$pattern"
fi

# Immich 只在 geodata-date.txt 与上次记录相等时跳过导入，这里给出显式刷新开关。
if [ "${IMMICH_CN_FORCE_RELOAD:-0}" = "1" ]; then
  # 源数据可能把该文件写成符号链接；写前先删除，避免追随到目标目录之外。
  rm -f "$target/geodata-date.txt"
  if china_time="$(date -u -d "@$(( $(date +%s) + 28800 ))" +"%Y-%m-%dT%H:%M:%S+08:00" 2>/dev/null)"; then
    :
  elif china_time="$(date -u -v+8H +"%Y-%m-%dT%H:%M:%S+08:00" 2>/dev/null)"; then
    :
  else
    echo "immich-cn: 无法生成北京时间戳" >&2
    exit 1
  fi
  printf '%s\n' "$china_time" > "$target/geodata-date.txt"
  echo "immich-cn: 已将 geodata-date.txt 更新为北京时间，Immich 会重新导入数据"
fi

exec "$@"
