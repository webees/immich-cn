#!/bin/sh
# 在容器内按指定展示粒度重写 geodata/cities500.txt 的第 1、2 列。
#
# 用法：immich-cn-apply-pattern --source <geodata 目录> --table <patterns.tsv[.gz]> --pattern '{admin_2} {admin_3}'
set -eu

source_dir=""
table=""
pattern=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source) source_dir="$2"; shift 2 ;;
    --table) table="$2"; shift 2 ;;
    --pattern) pattern="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,6p' "$0"
      exit 0
      ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

if [ -z "$source_dir" ] || [ -z "$table" ] || [ -z "$pattern" ]; then
  echo "缺少 --source / --table / --pattern" >&2
  exit 2
fi

cities="$source_dir/cities500.txt"
if [ ! -f "$cities" ]; then
  echo "未找到 $cities" >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT INT TERM

case "$table" in
  *.gz) gzip -dc "$table" > "$work/patterns.tsv" ;;
  *)    cp "$table" "$work/patterns.tsv" ;;
esac

column="$(awk -F'\t' -v wanted="$pattern" '
  NR == 1 { for (i = 1; i <= NF; i++) if ($i == wanted) found = i }
  END { print found }
' "$work/patterns.tsv")"

if [ -z "$column" ]; then
  echo "未知展示粒度：$pattern" >&2
  echo "可用粒度：$(head -n 1 "$work/patterns.tsv")" >&2
  exit 2
fi

awk -F'\t' -v OFS='\t' -v column="$column" '
  FNR == NR {
    if (FNR > 1) names[$1] = $column
    next
  }
  {
    name = names[$1]
    if (name != "") {
      $2 = name
      $3 = name
    }
    print
  }
' "$work/patterns.tsv" "$cities" > "$work/cities500.txt"

mv "$work/cities500.txt" "$cities"
echo "已应用展示粒度：$pattern"
