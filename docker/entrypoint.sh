#!/bin/bash
# Immich 镜像入口包装：注入中文 geodata 后再执行原始启动命令。
set -euo pipefail

build_root="${IMMICH_BUILD_DATA:-/build}"
target="${build_root%/}/geodata"
source_dir="${IMMICH_CN_GEODATA_DIR:-/opt/immich-cn/geodata}"
langs_dir="${IMMICH_CN_LANGS_DIR:-/opt/immich-cn/i18n-iso-countries/langs}"
patterns_table="${IMMICH_CN_PATTERNS_TABLE:-/opt/immich-cn/patterns.tsv.gz}"
pattern="${IMMICH_CN_PATTERN:-{admin_2}}"

mkdir -p "$target"
cp -a "$source_dir/." "$target/"

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

# Immich 只在 geodata-date.txt 比上次导入更新时才重新导入，这里给出显式开关。
if [ "${IMMICH_CN_FORCE_RELOAD:-0}" = "1" ]; then
  date -u +"%Y-%m-%dT%H:%M:%S+00:00" > "$target/geodata-date.txt"
  echo "immich-cn: 已将 geodata-date.txt 更新为当前时间，Immich 会重新导入数据"
fi

exec "$@"
