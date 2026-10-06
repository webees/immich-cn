#!/bin/sh
# 数据镜像入口：把镜像内的 geodata 释放到目标目录。
#
# 用法：immich-cn-install --target ./immich-cn [--pattern '{admin_2}']
set -eu

target="${IMMICH_CN_TARGET:-/out}"
pattern="${IMMICH_CN_PATTERN:-}"
geodata_root="${IMMICH_CN_GEODATA_DIR:-/opt/immich-cn/geodata}"
langs_root="${IMMICH_CN_LANGS_DIR:-/opt/immich-cn/i18n-iso-countries}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) target="$2"; shift 2 ;;
    --pattern) pattern="$2"; shift 2 ;;
    --geodata-only) langs_root=""; shift ;;
    -h|--help)
      sed -n '2,5p' "$0"
      exit 0
      ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

mkdir -p "$target"

REQUIRED_FILES="admin1CodesASCII.txt admin2Codes.txt cities500.txt countryInfo.txt geodata-date.txt ne_10m_admin_0_countries.geojson"
missing_files=""
for name in $REQUIRED_FILES; do
  if [ ! -f "$geodata_root/$name" ]; then
    missing_files="${missing_files} ${name}"
  fi
done
if [ -n "$missing_files" ]; then
  echo "错误：geodata 源缺少必需文件：${missing_files# }" >&2
  echo "      请检查 IMMICH_CN_GEODATA_DIR=${geodata_root}" >&2
  exit 1
fi

rm -rf "$target/geodata"
cp -a "$geodata_root" "$target/geodata"
if [ -n "$langs_root" ]; then
  if [ -d "$langs_root" ]; then
    rm -rf "$target/i18n-iso-countries"
    cp -a "$langs_root" "$target/i18n-iso-countries"
  else
    # 旧版 Immich 才需要国家名称覆盖；静默跳过会让用户以为已经生效
    echo "警告：未找到国家名称目录，已跳过：${langs_root}" >&2
  fi
fi

if [ -n "$pattern" ] && [ "$pattern" != "{admin_2}" ]; then
  immich-cn-apply-pattern --source "$target/geodata" \
    --table "${IMMICH_CN_PATTERNS_TABLE:-/opt/immich-cn/patterns.tsv.gz}" \
    --pattern "$pattern"
fi

cat > "$target/README.md" <<'EOF'
本目录由 immich-cn 数据镜像生成。

- geodata/                放到 Immich 的 /build/geodata
- i18n-iso-countries/     放到 Immich < 1.136 的 node_modules/i18n-iso-countries

数据来源与许可见 https://github.com/webees/immich-cn/blob/main/docs/licensing.md
EOF

echo "geodata 已写入 $target"
ls -la "$target"
