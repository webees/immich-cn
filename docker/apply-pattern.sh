#!/bin/sh
# 在容器内按指定展示粒度重写 geodata/cities500.txt 的第 1、2 列。
#
# 用法：immich-cn-apply-pattern --source <geodata 目录> --table <immich-cn-patterns-v1.tsv[.gz]> --pattern '{admin_2} {admin_3}'
set -eu

source_dir=""
table=""
pattern=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      [ "$#" -ge 2 ] || { echo "缺少 --source 参数" >&2; exit 2; }
      source_dir="$2"; shift 2 ;;
    --table)
      [ "$#" -ge 2 ] || { echo "缺少 --table 参数" >&2; exit 2; }
      table="$2"; shift 2 ;;
    --pattern)
      [ "$#" -ge 2 ] || { echo "缺少 --pattern 参数" >&2; exit 2; }
      pattern="$2"; shift 2 ;;
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

source_dir="$(cd "$source_dir" && pwd -P)" || {
  echo "无法解析 --source 目录：$source_dir" >&2
  exit 1
}
if [ "$source_dir" = "/" ]; then
  echo "错误：--source 不能是根目录" >&2
  exit 2
fi

cities="$source_dir/cities500.txt"
if [ ! -f "$cities" ]; then
  echo "未找到 $cities" >&2
  exit 1
fi
if [ ! -f "$table" ]; then
  echo "未找到变体表：$table" >&2
  exit 1
fi

work="$(mktemp -d)"
# 保留退出码：EXIT trap 的最后一条命令可能覆盖脚本原本的失败状态
status=0
trap 'status=$?; rm -rf "$work"; exit $status' EXIT INT TERM

case "$table" in
  *.gz) gzip -dc "$table" > "$work/immich-cn-patterns-v1.tsv" ;;
  *)    cp "$table" "$work/immich-cn-patterns-v1.tsv" ;;
esac

column="$(awk -F'\t' -v wanted="$pattern" '
  NR == 1 { for (i = 1; i <= NF; i++) if ($i == wanted) found = i }
  END { print found }
' "$work/immich-cn-patterns-v1.tsv")"

if [ -z "$column" ]; then
  echo "未知展示粒度：$pattern" >&2
  echo "可用粒度：$(head -n 1 "$work/immich-cn-patterns-v1.tsv")" >&2
  exit 2
fi

awk -F'\t' -v OFS='\t' -v column="$column" -v countfile="$work/matched" -v totalfile="$work/total" '
  FNR == NR {
    if (FNR > 1) names[$1] = $column
    next
  }
  {
    total++
    name = names[$1]
    if (name != "") {
      $2 = name
      $3 = name
      matched++
    }
    print
  }
  END {
    print matched + 0 > countfile
    print total + 0 > totalfile
  }
' "$work/immich-cn-patterns-v1.tsv" "$cities" > "$work/cities500.txt"

matched="$(cat "$work/matched")"
total="$(cat "$work/total")"
if [ "$total" -eq 0 ]; then
  # cities500.txt 为空时 matched 与 total 同时为 0，会让下面的"完整匹配"判断恒真，
  # 脚本会"成功"地把空文件写回去。空输入必须显式失败。
  echo "错误：${cities} 没有任何记录，无法应用展示粒度" >&2
  exit 1
fi
if [ "$matched" -ne "$total" ]; then
  # 部分匹配同样是"假成功"：只改少数行会让绝大多数地点保留错误粒度。
  echo "错误：变体表仅匹配 ${matched}/${total} 条，展示粒度未完整生效" >&2
  echo "      请确认变体表与 geodata 来自同一次构建" >&2
  exit 1
fi

mv "$work/cities500.txt" "$cities"
echo "已应用展示粒度：${pattern}（匹配 ${matched} 条）"
exit 0
