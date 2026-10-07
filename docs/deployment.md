# Deployment

## 前置条件

- Immich 1.136.0 及以上使用 `/build/geodata`；
- Immich 1.136.0 ~ 3.2.x 需要覆盖 `i18n-iso-countries` 的语言文件（路径随版本不同，见下文示例）；3.3.0 起改读 `countryInfo.txt`，不再需要该覆盖；
- 1.136.0 以下同样需要该覆盖，只是挂载路径不同；
- 数据文件在容器内需要**可读**，镜像方案会自动复制一份到 `/build/geodata`。

## 方案 A：开箱即用的 Immich 镜像

示例 compose 文件（含 immich-server、immich-machine-learning、redis 与 database，仍需提供 `.env` 与持久化目录）：[examples/compose.server.yml](../examples/compose.server.yml)。

```yaml
# compose.yaml
name: immich

services:
  immich-server:
    image: ${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/webees/immich-cn-server:latest
    container_name: immich_server
    env_file:
      - .env
    environment:
      TZ: Asia/Shanghai
      IMMICH_CN_PATTERN: "{admin_2}"
      # 数据更新后强制重新导入（镜像内 geodata-date.txt 已是构建时间，一般不需要）
      IMMICH_CN_FORCE_RELOAD: "0"
    volumes:
      - ${UPLOAD_LOCATION}:/data
      - /etc/localtime:/etc/localtime:ro
    ports:
      - 2283:2283
    depends_on:
      - redis
      - database
    restart: always
```

Immich v3.2.4 与 v3.3.0 官方 compose 均已将媒体目录挂载到 `/data`；不要把新部署继续写成旧路径 `/usr/src/app/upload`。machine-learning 服务需要持久化 `model-cache`，否则模型会在容器重建后重新下载。

镜像标签：

| 标签 | 含义 |
|:--|:--|
| `latest` | 最近一次成功构建的数据 + `release` 版 Immich |
| `release` | 与 Immich `release` 标签对齐 |
| `release-<日期>` | 当日最新数据，同日重跑可更新；长期固定请使用 digest |
| `<语义化版本>` | 由 `Release` 工作流生成，两个镜像使用同一项目版本 |

### Environment variables

| 变量 | 默认值 | 说明 |
|:--|:--|:--|
| `IMMICH_CN_PATTERN` | `{admin_2}` | 展示粒度，取值见 README |
| `IMMICH_CN_FORCE_RELOAD` | `0` | 设为 `1` 时把 `geodata-date.txt` 更新为当前时间，强制 Immich 重新导入 |
| `IMMICH_CN_GEODATA_DIR` | `/opt/immich-cn/geodata` | 镜像内数据源目录，一般无需修改 |
| `IMMICH_CN_LANGS_DIR` | `/opt/immich-cn/i18n-iso-countries/langs` | 镜像内国家名称目录（旧版 Immich 用） |
| `IMMICH_CN_PATTERNS_TABLE` | `/opt/immich-cn/immich-cn-patterns-tsv-v1.gz` | 运行时粒度切换用的变体表，一般无需修改 |
| `IMMICH_BUILD_DATA` | `/build` | Immich 自身的构建数据目录，跟随官方镜像即可 |

数据镜像（默认 pull 地址 `${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/webees/immich-cn`）额外支持：

| 变量 | 默认值 | 说明 |
|:--|:--|:--|
| `IMMICH_CN_TARGET` | `/out` | `--target` 的等价环境变量，指定释放目录 |

数据镜像入口 `immich-cn-install` 的参数：

| 参数 | 说明 |
|:--|:--|
| `--target <目录>` | 释放目标目录（等价 `IMMICH_CN_TARGET`） |
| `--pattern '<pattern>'` | 覆盖展示粒度，例如 `--pattern '{admin_2} {admin_3}'` |
| `--geodata-only` | 只释放 `geodata/`，不复制 `i18n-iso-countries/` 国家名覆盖（Immich 3.3.0 起改读 `countryInfo.txt`，不再需要该覆盖） |

> `IMMICH_CN_DATA_DATE` 是构建参数写入的只读元信息（镜像内可见），无需手动设置。

`TZ=Asia/Shanghai` 是面向中国用户的默认示例。若宿主机已正确设置时区，也可以保留 `/etc/localtime` 挂载；两者同时存在时，容器内的 `TZ` 环境变量优先。

## 方案 B：官方镜像 + 数据镜像

示例 compose 文件（需自行提供 `.env` 和持久化目录）：[examples/compose.volume.yml](../examples/compose.volume.yml)。

```bash
# 1. 把数据释放到宿主机
docker run --rm -v "$PWD/immich-cn:/out" \
  "${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/webees/immich-cn:latest" \
  --target /out --pattern '{admin_2} {admin_3}'

# 2. compose 中挂载
```

```yaml
services:
  immich-server:
    image: ${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/immich-app/immich-server:release
    volumes:
      - ./immich-cn/geodata:/build/geodata:ro
      # 国家名称覆盖：仅 Immich 1.136.0 ~ 3.2.x 需要（3.3.0 起改读 countryInfo.txt）
      # Immich >= 1.136.0
      - ./immich-cn/i18n-iso-countries/langs:/usr/src/app/server/node_modules/i18n-iso-countries/langs:ro
      # Immich < 1.136.0
      # - ./immich-cn/i18n-iso-countries/langs:/usr/src/app/node_modules/i18n-iso-countries/langs:ro
```

## 方案 C：只用 Release 数据

```bash
curl -fsSL -o immich-cn-geodata-admin2-default-v1.zip \
  https://github.com/webees/immich-cn/releases/latest/download/immich-cn-geodata-admin2-default-v1.zip
curl -fsSL -o immich-cn-i18n-json-v1.zip \
  https://github.com/webees/immich-cn/releases/latest/download/immich-cn-i18n-json-v1.zip
unzip -o immich-cn-geodata-admin2-default-v1.zip -d .
mkdir -p i18n-iso-countries
unzip -o immich-cn-i18n-json-v1.zip -d i18n-iso-countries
```

解压后得到 `geodata/` 与 `i18n-iso-countries/langs/en.json`，按方案 B 的方式挂载即可。注意国家名称覆盖是**独立资产**：`immich-cn-geodata-*.zip` 里没有 `langs/`，只下载它会缺失 Immich 1.136.0 ~ 3.2.x 需要的国家名覆盖（3.3.0 起 Immich 改读 `countryInfo.txt`，不再需要）。

## 让中文地名立即生效

1. 重启 Immich，确认日志出现 `geodata records imported`；
2. 进入「系统管理 → 任务」，执行一次「提取元数据 → 全部」刷新历史照片；
3. 之后新增照片会自动使用新的地名，无需再次刷新。

如果替换数据后 Immich 没有重新导入，说明 `geodata-date.txt` 与上次记录的值**完全相同**（判断条件是「相等就跳过」，不是「比它旧才跳过」）：

```bash
# 官方镜像 + 挂载方案
TZ=Asia/Shanghai date +"%Y-%m-%dT%H:%M:%S+08:00" > ./immich-cn/geodata/geodata-date.txt

# 镜像方案
# 把 IMMICH_CN_FORCE_RELOAD 设为 1 后重启容器
```

## 国内网络与镜像获取

Compose 示例默认使用中国可达的 GHCR mirror：

- `ghcr.nju.edu.cn`：默认；
- `docker.m.daocloud.io/ghcr.io`：可选 fallback；
- `ghcr.dockerproxy.net`：可选 fallback；
- `ghcr.io`：官方源，作为最终 fallback 或 digest 比对基准。

用 `IMMICH_CN_GHCR_MIRROR` 覆盖默认值：

```bash
export IMMICH_CN_GHCR_MIRROR=ghcr.nju.edu.cn
docker pull "${IMMICH_CN_GHCR_MIRROR}/webees/immich-cn-server:latest"
```

第三方 mirror 不是官方 origin。它们可能在当前时刻返回与 `ghcr.io` 相同的 digest，但可用性和信任状态会变化。生产环境应：

- 从官方 `ghcr.io` 或签名 Release 获取目标 digest；
- 对比 mirror 的 `docker buildx imagetools inspect` digest；
- 长期固定到 `@sha256:<digest>`，不要只写 `latest`；
- 从 Release 下载数据时使用 `immich-cn-checksums-sha256-v1.txt` 验证内容。

国内网络环境下，地图底图与坐标偏移是另一个问题：本项目输出的坐标来自 GeoNames（WGS-84）。若底图使用 GCJ-02，请阅读 [中国本地化与加速](china.md) 的坐标说明，或改用 WGS-84 底图。

## CDN 与静态资源加速

需要把 Immich 放在国内 CDN 或反向代理后面时，可使用：

- [examples/compose.acceleration.yml](../examples/compose.acceleration.yml)：在 Immich 前增加 Nginx 源站；
- [examples/nginx/immich-cn.conf](../examples/nginx/immich-cn.conf)：只缓存 `/_app/immutable/*`，其余请求默认旁路。

本项目只提供源站策略，不运营公共 CDN。HTML、API、Cookie、认证头、原始照片和视频不得进入公共共享缓存；地图瓦片只能缓存自有或明确授权的内容。完整缓存矩阵、地图同源代理、CSP 和验证命令见 [中国本地化与加速](china.md)。

## 更新数据

- **镜像方案**：`docker compose pull && docker compose up -d`；
- **挂载方案**：重新执行方案 B 的第一步，然后 `docker compose restart immich-server`；
- **自动更新**：沿用自己的定时任务，例如每周执行一次上面的命令。

### 数据更新频率

上游数据由 GitHub Actions 按设计每天自动检查更新（北京时间 13:23 / UTC 05:23）；实际执行取决于仓库权限与上游服务可用性：

- 每天用 ETag 条件请求检查 GeoNames、Natural Earth、i18n-iso-countries；
- 只有数据、构建配置或发布器修订真正变化时才重新构建、发布 Release 与推送镜像；
- 因此拉取最新镜像即可获得该 Release 当时的完整数据；拉取频率取决于你对数据新鲜度和保留策略的要求。

判断当前数据版本：查看 Release 标题日期，或容器内 `/build/geodata/geodata-date.txt`。

### 让镜像自动跟随更新

如果希望主机自动跟随每日数据：

```bash
# 例如每天凌晨拉取并重建容器
0 5 * * * cd /opt/immich && docker compose pull immich-server && docker compose up -d immich-server
```

也可以使用 Watchtower 等工具监听 `${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/webees/immich-cn-server:latest`。注意：数据变化后 `geodata-date.txt` 会更新，Immich 会在启动时重新导入 geodata；若显式设置 `IMMICH_CN_FORCE_RELOAD=1`，则每次启动都会强制重新导入。

## 非官方 Immich 镜像

`imagegenius/immich` 等第三方镜像的目录结构可能不同（未逐一验证），请把 `geodata` 挂载到它实际使用的 geodata 路径，并参考镜像自身的文档。`IMAGES` 目录不一致时，`IMMICH_BUILD_DATA` 也可以显式覆盖。

## Rollback

- 镜像方案：优先固定到 `sha-<短提交>` 或 digest；`release-<日期>` 只适合当日跟踪；
- 数据方案：从 [Releases](https://github.com/webees/immich-cn/releases) 下载 `data-<日期>` 或 `data-<日期>-sha-<短提交>` 不可变快照。
