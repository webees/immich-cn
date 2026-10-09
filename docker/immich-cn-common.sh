#!/bin/sh
# 数据镜像入口与服务端入口共享的 geodata 文件契约。

REQUIRED_FILES="admin1CodesASCII.txt admin2Codes.txt cities500.txt countryInfo.txt geodata-date.txt ne_10m_admin_0_countries.geojson"

missing_required_files() {
  dir="$1"
  missing=""
  for name in $REQUIRED_FILES; do
    if [ ! -s "$dir/$name" ]; then
      missing="${missing} ${name}"
    fi
  done
  printf '%s' "$missing"
}
