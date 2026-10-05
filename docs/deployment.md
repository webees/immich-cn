# 部署指南

## 前置条件

- Immich 1.136.0 及以上使用 `/build/geodata`；
- 1.136.0 以下额外需要覆盖 `i18n-iso-countries` 的语言文件；
- 数据文件在容器内需要**可读**，镜像方案会自动复制一份到 `/build/geodata`。

## 方案 A：开箱即用的 Immich 镜像

```yaml
# compose.yaml
name: immich

services:
  immich-server:
    image: ghcr.io/webees/immich-cn-server:latest
    container_name: immich_server
    env_file:
      - .env
    environment:
      IMMICH_CN_PATTERN: "{admin_2}"
      # 数据更新后强制重新导入（镜像内 geodata-date.txt 已是构建时间，一般不需要）
      IMMICH_CN_FORCE_RELOAD: "0"
    volumes:
      - ${UPLOAD_LOCATION}:/usr/src/app/upload
      - /etc/localtime:/etc/localtime:ro
    ports:
      - 2283:2283
    depends_on:
      - redis
      - database
    restart: always
```

镜像标签：

| 标签 | 含义 |
|:--|:--|
| `latest` | 最近一次成功构建的数据 + `release` 版 Immich |
| `release` | 与 Immich `release` 标签对齐 |
| `release-<日期>` | 固定到某个数据快照 |

### 环境变量

| 变量 | 默认值 | 说明 |
|:--|:--|:--|
| `IMMICH_CN_PATTERN` | `{admin_2}` | 展示粒度，取值见 README |
| `IMMICH_CN_FORCE_RELOAD` | `0` | 设为 `1` 时把 `geodata-date.txt` 更新为当前时间，强制 Immich 重新导入 |
| `IMMICH_CN_GEODATA_DIR` | `/opt/immich-cn/geodata` | 镜像内数据源目录，一般无需修改 |
| `IMMICH_BUILD_DATA` | `/build` | Immich 自身的构建数据目录，跟随官方镜像即可 |

## 方案 B：官方镜像 + 数据镜像

```bash
# 1. 把数据释放到宿主机
docker run --rm -v "$PWD/immich-cn:/out" ghcr.io/webees/immich-cn:latest \
  --target /out --pattern '{admin_2} {admin_3}'

# 2. compose 中挂载
```

```yaml
services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:release
    volumes:
      - ./immich-cn/geodata:/build/geodata:ro
      # Immich < 1.136.0 需要下面这一行
      - ./immich-cn/i18n-iso-countries/langs:/usr/src/app/server/node_modules/i18n-iso-countries/langs:ro
```

## 方案 C：只用 Release 数据

```bash
curl -fsSL -o geodata.zip \
  https://github.com/webees/immich-cn/releases/latest/download/geodata.zip
unzip -o geodata.zip -d .
```

解压后得到 `geodata/` 目录，按方案 B 的方式挂载即可。

## 让中文地名立即生效

1. 重启 Immich，确认日志出现 `geodata records imported`；
2. 进入「系统管理 → 任务」，执行一次「提取元数据 → 全部」刷新历史照片；
3. 之后新增照片会自动使用新的地名，无需再次刷新。

如果替换数据后 Immich 没有重新导入，说明 `geodata-date.txt` 不新于上次导入时间：

```bash
# 官方镜像 + 挂载方案
date -u +"%Y-%m-%dT%H:%M:%S+00:00" > ./immich-cn/geodata/geodata-date.txt

# 镜像方案
# 把 IMMICH_CN_FORCE_RELOAD 设为 1 后重启容器
```

## 更新数据

- **镜像方案**：`docker compose pull && docker compose up -d`；
- **挂载方案**：重新执行方案 B 的第一步，然后 `docker compose restart immich-server`；
- **自动更新**：沿用自己的定时任务，例如每周执行一次上面的命令。

### 数据更新频率

上游数据由 GitHub Actions **每天自动更新**（UTC 05:23 / 北京时间 13:23）：

- 每天用 ETag 条件请求检查 GeoNames、Natural Earth、i18n-iso-countries；
- 只有数据或构建配置真正变化时才重新构建、发布 Release 与推送镜像；
- 因此每周甚至每月拉取一次镜像，也能一次拿到累积的全部更新。

判断当前数据版本：查看 Release 标题日期，或容器内 `/build/geodata/geodata-date.txt`。

### 让镜像自动跟随更新

如果希望主机自动跟随每日数据：

```bash
# 例如每天凌晨拉取并重建容器
0 5 * * * cd /opt/immich && docker compose pull immich-server && docker compose up -d immich-server
```

也可以使用 Watchtower 等工具监听 `ghcr.io/webees/immich-cn-server:latest`。
注意：数据变化后 `geodata-date.txt` 会更新，Immich 会在启动时重新导入 geodata；
若显式设置 `IMMICH_CN_FORCE_RELOAD=1`，则每次启动都会强制重新导入。

## 非官方 Immich 镜像

`imagegenius/immich` 等第三方镜像的目录结构不同，请把 `geodata` 挂载到它实际使用的 geodata 路径，
并参考镜像自身的文档。`IMAGES` 目录不一致时，`IMMICH_BUILD_DATA` 也可以显式覆盖。

## 回滚

- 镜像方案：`docker compose pull ghcr.io/webees/immich-cn-server:release-<日期>`；
- 数据方案：从 [Releases](https://github.com/webees/immich-cn/releases) 下载对应日期的 `data-<日期>` 快照。
