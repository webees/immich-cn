# 部署

## 前置条件

- Immich 1.136.0 及以上使用 `/build/geodata`；
- Immich 1.136.0 ~ 3.2.x 需要覆盖 `i18n-iso-countries` 的语言文件（路径随版本不同，见下文示例）；3.3.0 起改读 `countryInfo.txt`，不再需要该覆盖；
- 1.136.0 以下同样需要该覆盖，只是挂载路径不同；
- 数据文件在容器内需要**可读**，镜像方案会自动复制一份到 `/build/geodata`。

## 镜像方案

以 [examples/compose.server.yml](../examples/compose.server.yml) 为唯一可执行示例：它包含 immich-server、immich-machine-learning、redis 与数据库，默认 `TZ: Asia/Shanghai`，媒体目录挂载到 `/data`，machine-learning 的 `model-cache` 会持久化。复制后仍需提供 `.env` 与持久化目录；启动方式见 [README 方式一](../README.md#方式一镜像直用)。

镜像标签、版本规则与拉取源见 [镜像发布](packages.md)。部署时优先固定 `sha-<短提交>` 或完整摘要，`latest` 只用于试用。

### 环境变量

两个镜像的完整变量、默认值与数据镜像参数以 [README 配置总览](../README.md#配置总览) 为准。示例默认 `TZ: Asia/Shanghai`；与 `/etc/localtime` 挂载同时存在时，容器内 `TZ` 优先。

## 数据方案

使用官方 `immich-app/immich-server` 时，按 [README 方式二](../README.md#方式二数据挂载) 释放并挂载 `geodata/`。Immich 1.136.0 ~ 3.2.x 还需挂载独立的 `i18n-iso-countries/langs`；对应覆盖包为 `immich-cn-i18n-json-v1.zip`，下载与目录结构见 [README 方式三](../README.md#方式三发布下载)。完整 Compose 示例见 [examples/compose.volume.yml](../examples/compose.volume.yml)。

替换数据后按 [README 刷新生效](../README.md#刷新生效) 重新导入；若没有重新导入，说明 `geodata-date.txt` 与上次记录**完全相等**，处理方式见 [运维与常见问题](operations.md)。

## 国内网络

Compose 示例默认使用中国可达的 GHCR 镜像源；可用源、信任边界与摘要比对方式见 [镜像发布](packages.md)。

用 `IMMICH_CN_GHCR_MIRROR` 覆盖默认值：

```bash
export IMMICH_CN_GHCR_MIRROR=ghcr.nju.edu.cn
docker pull "${IMMICH_CN_GHCR_MIRROR}/webees/immich-cn-server:latest"
```

第三方镜像源不是官方回源。它们可能在当前时刻返回与 `ghcr.io` 相同的摘要，但可用性和信任状态会变化。生产环境应：

- 从官方 `ghcr.io` 或签名发布获取目标摘要；
- 对比镜像源的 `docker buildx imagetools inspect` 摘要；
- 长期固定到 `@sha256:<digest>`，不要只写 `latest`；
- 从发布下载数据时使用 `immich-cn-checksums-sha256-v1.txt` 验证内容。

国内网络环境下，地图底图与坐标偏移是另一个问题：本项目输出的坐标来自 GeoNames（WGS-84）。若底图使用 GCJ-02，请阅读 [中国本地化与加速](china.md) 的坐标说明，或改用 WGS-84 底图。

## 静态加速

需要把 Immich 放在国内 CDN 或反向代理后面时，使用 [加速 Compose 示例](../examples/compose.acceleration.yml) 与 [Nginx 配置](../examples/nginx/immich-cn.conf)。缓存矩阵、私有内容边界、地图瓦片、CSP 与验证命令见 [中国本地化与加速](china.md)。

## 数据更新

- **镜像方案**：`docker compose pull && docker compose up -d`；
- **挂载方案**：按 [README 方式二](../README.md#方式二数据挂载) 重新释放数据，然后 `docker compose restart immich-server`；
- **自动更新**：沿用自己的定时任务，例如每周执行一次上面的命令。

### 更新频率

上游数据由 GitHub Actions 按设计每天自动检查更新（北京时间 13:23 / UTC 05:23），只有数据、构建配置或发布器修订真正变化时才重新构建、发布与推送镜像；实际执行取决于仓库权限与上游服务可用性。机制细节见 [README 自动更新](../README.md#自动更新)。判断当前数据版本：查看发布标题日期，或容器内 `/build/geodata/geodata-date.txt`。

### 自动跟随

如果希望主机自动跟随每日数据：

```bash
# 例如每天凌晨拉取并重建容器
0 5 * * * cd /opt/immich && docker compose pull immich-server && docker compose up -d immich-server
```

也可以使用 Watchtower 等工具监听 `${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/webees/immich-cn-server:latest`。注意：数据变化后 `geodata-date.txt` 会更新，Immich 会在启动时重新导入 geodata；若显式设置 `IMMICH_CN_FORCE_RELOAD=1`，则每次启动都会强制重新导入。

## 非官方镜像

`imagegenius/immich` 等第三方镜像的目录结构可能不同（未逐一验证），请把 `geodata` 挂载到它实际使用的地理数据路径，并参考镜像自身的文档。`IMAGES` 目录不一致时，`IMMICH_BUILD_DATA` 也可以显式覆盖。

## 回滚方案

- 镜像方案：优先固定到 `sha-<短提交>` 或摘要；`release-<日期>` 只适合当日跟踪；
- 数据方案：从 [Releases](https://github.com/webees/immich-cn/releases) 下载 `data-<日期>` 或 `data-<日期>-sha-<短提交>` 不可变快照。
