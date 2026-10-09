#!/bin/sh
# 数据镜像入口：把镜像内的 geodata 释放到目标目录。
#
# 用法：immich-cn-install --target ./immich-cn [--pattern '{admin_2}'] [--geodata-only]
#   --geodata-only  只释放 geodata/，不复制 i18n-iso-countries/ 国家名覆盖（Immich >= 3.3.0 不再需要）
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
. "$script_dir/immich-cn-common.sh"

target="${IMMICH_CN_TARGET:-/out}"
pattern="${IMMICH_CN_PATTERN:-}"
geodata_root="${IMMICH_CN_GEODATA_DIR:-/opt/immich-cn/geodata}"
langs_root="${IMMICH_CN_LANGS_DIR:-/opt/immich-cn/i18n-iso-countries}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      [ "$#" -ge 2 ] || { echo "缺少 --target 参数" >&2; exit 2; }
      target="$2"; shift 2 ;;
    --pattern)
      [ "$#" -ge 2 ] || { echo "缺少 --pattern 参数" >&2; exit 2; }
      pattern="$2"; shift 2 ;;
    --geodata-only) langs_root=""; shift ;;
    -h|--help)
      sed -n '2,5p' "$0"
      exit 0
      ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

if [ -z "$target" ]; then
  echo "错误：--target 不能为空（收到：空）" >&2
  exit 2
fi

if [ -L "$target" ]; then
  echo "错误：--target 不能是符号链接：$target" >&2
  exit 2
fi

if ! mkdir -p "$target"; then
  echo "错误：无法创建目标目录 $target" >&2
  exit 1
fi
target="$(cd "$target" && pwd -P)" || {
  echo "错误：无法解析目标目录 $target" >&2
  exit 1
}
if [ "$target" = "/" ]; then
  echo "错误：--target 不能是根目录（收到：/）" >&2
  exit 2
fi

missing_files="$(missing_required_files "$geodata_root")"
if [ -n "$missing_files" ]; then
  echo "错误：geodata 源缺少必需文件或文件为空：${missing_files# }" >&2
  echo "      请检查 IMMICH_CN_GEODATA_DIR=${geodata_root}" >&2
  exit 1
fi

geodata_root="$(cd "$geodata_root" && pwd -P)" || {
  echo "错误：无法解析数据源目录 $geodata_root" >&2
  exit 1
}
# 源与目标互相嵌套时，下面的 `rm -rf "$target/geodata"` 会先删掉源数据再 cp 失败，
# 造成不可逆的数据丢失。必须在任何删除之前拒绝。
case "$geodata_root/" in
  "$target/"*)
    echo "错误：数据源 $geodata_root 位于目标目录 $target 内，删除目标会先删掉源数据" >&2
    exit 2 ;;
esac
case "$target/" in
  "$geodata_root/"*)
    echo "错误：目标目录 $target 位于数据源 $geodata_root 内，复制会递归写入自身" >&2
    exit 2 ;;
esac

langs_missing=""
if [ -n "$langs_root" ] && [ -d "$langs_root" ]; then
  for name in LICENSE en.json; do
    if [ ! -s "$langs_root/langs/$name" ]; then
      langs_missing="${langs_missing} ${name}"
    fi
  done
  if [ -n "$langs_missing" ]; then
    echo "错误：国家名称目录缺少必需文件：${langs_missing# }" >&2
    exit 1
  fi
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
    --table "${IMMICH_CN_PATTERNS_TABLE:-/opt/immich-cn/immich-cn-patterns-tsv-v1.gz}" \
    --pattern "$pattern"
fi

# README 是普通文件：先删除同名符号链接，避免 cat 跟随链接写出目标目录。
rm -f "$target/README.md"
cat > "$target/README.md" <<'EOF'
本目录由 immich-cn 数据镜像生成。

- geodata/                放到 Immich 的 /build/geodata
- i18n-iso-countries/     放到 Immich 的 node_modules/i18n-iso-countries：
                          Immich < 1.136.0        -> /usr/src/app/node_modules/i18n-iso-countries
                          Immich 1.136.0 ~ 3.2.x  -> /usr/src/app/server/node_modules/i18n-iso-countries
                          Immich 3.3.0 及以上     不再需要（改读 geodata/countryInfo.txt）

数据来源与许可见 https://github.com/webees/immich-cn/blob/main/docs/licensing.md
EOF

echo "geodata 已写入 $target"
ls -la "$target"
