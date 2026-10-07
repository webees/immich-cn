# Immich integration contract

本文记录 `immich-cn` 对 Immich 上游的实际依赖、可配置点、wrapper 边界和不能在本项目中安全解决的问题。核验基线为 2026-10-07 的上游源码，以及本仓库声明的 Immich 版本边界。

## Integration classes

| 类型 | 本项目策略 | 示例 |
|:--|:--|:--|
| Data adapter | 生成 Immich 固定的 geodata 文件 | `cities500.txt`、`admin1CodesASCII.txt`、`admin2Codes.txt`、`countryInfo.txt` |
| Config/env | 通过 Immich 官方 environment variable 或 config file 改变行为 | `TZ`、`IMMICH_CONFIG_FILE`、`IMMICH_HELMET_FILE`、`IMMICH_TRUSTED_PROXIES` |
| Container wrapper | 在启动前复制数据、设置粒度或生成时间戳 | `immich-cn-server`、`immich-cn-install` |
| Delivery layer | Nginx/CDN 只处理公开 static asset 和网络可达性 | `/_app/immutable/*`、GHCR mirror |
| API utility | 通过 Immich public API 对已有 metadata 做显式操作；v3.3.0+ 优先 `PATCH /api/assets`，旧版仅在 404/405 时回退 `PUT` | `scripts/set_asset_timezone.py` |
| Upstream built-in locale | 使用 Immich 已提供的界面语言，不 fork UI | `zh_Hans`、`zh_Hant` |
| Upstream change required | 不在本项目做不安全 patch 或 UI fork | 全局 UI timezone、任意地图瓦片 |

## Reverse geocoding contract

上游 `server/src/repositories/map.repository.ts` 读取以下文件：

| 文件 | 关键字段/行为 |
|:--|:--|
| `cities500.txt` | `name` 来自 0-based column 1；`alternateNames` 来自 0-based column 3；坐标来自 0-based column 4/5 |
| `admin1CodesASCII.txt` | Immich 以 0-based column 0 为 key、0-based column 1 为名称建立 admin1 map |
| `admin2Codes.txt` | Immich 以 0-based column 0 为 key、0-based column 1 为名称建立 admin2 map |
| `countryInfo.txt` | 国家名来自 0-based column 4；alpha-2/alpha-3 分别位于 0-based column 0/1 |
| `geodata-date.txt` | 与 Immich metadata 中的 `lastUpdate` **相等时跳过 import**，不等时重新 import |
| `ne_10m_admin_0_countries.geojson` | 没有城市点时的 country fallback |

本文的 `column` 一律指 `line.split('\t')` 的 0-based index，避免把 `column 1` 误读成自然语言中的“第一列”。本项目的职责是让这些文件始终符合上述 column contract，并通过 validation 和 artifact checksum 阻止坏数据发布。我们不在 Immich 数据库中直接写 `geodata_places`，也不覆盖 Immich 的 migration。

### Import filter and search radius

读取 `cities500.txt` 时，上游会先按 `feature code` 丢掉一部分记录，这一步发生在本项目无法干预的 import 阶段：

- `feature code`（0-based column 7）为 `PPLX` 且 `country code`（0-based column 8）不是 `AU` 的记录被跳过；
- `feature code` 为 `PPLH` 的记录在所有国家都被跳过；
- 只有落在 `reverseGeocodeMaxDistance`（上游常量，25 km）内、且未被上述规则丢弃的城市点才参与 reverse geocoding；没有命中时回退到 `ne_10m_admin_0_countries.geojson`，此时 `state` 与 `city` 为 `null`。

所以制品行数不等于 Immich 实际写入 `geodata_places` 的行数。2026-10-07 对当时全量制品实测：256,626 行中有 7,307 行会被跳过（7,278 行 `PPLX` 非 `AU`，29 行 `PPLH`），其中 `CN` 77 行。复算方式：解压任一 geodata 制品，对 `geodata/cities500.txt` 按 0-based column 7/8 统计。

本项目不预先删除这些行。过滤规则是 Immich 的版本行为，制品仍需保持 GeoNames 语义完整；差异只在上文量化，不作为“全部记录都会出现在 Immich”的依据。

## Config and environment

以下变量属于 Immich upstream contract，可用于部署层调整：

| Variable | 用途 | 本项目处理 |
|:--|:--|:--|
| `TZ` | server process 和部分运行时的 timezone | Compose 默认 `Asia/Shanghai` |
| `IMMICH_BUILD_DATA` | 固定 geodata/web/plugin 的 build root | wrapper 保留并支持覆盖 |
| `IMMICH_CONFIG_FILE` | 使用 Immich YAML/JSON config file | 文档记录，默认不启用 |
| `IMMICH_HELMET_FILE` | 配置 CSP/helmet，自定义 map origin 时使用 | 文档记录，默认不启用 |
| `IMMICH_TRUSTED_PROXIES` | reverse proxy 后的 trusted proxy 范围 | 可选部署参数，默认交给 Immich |
| `IMMICH_WORKERS_INCLUDE` / `IMMICH_WORKERS_EXCLUDE` | 控制 API/microservices worker | 不在本项目默认改写 |
| `IMMICH_ALLOW_SETUP` | 是否允许初次 setup | 不在本项目默认改写 |
| `IMMICH_IGNORE_MOUNT_CHECK_ERRORS` | storage mount check 策略 | 仅在用户显式配置时使用 |
| `IMMICH_ALLOW_EXTERNAL_PLUGINS` | external plugin 开关 | 默认不启用 |

改变这些变量会改变 Immich 的运行时行为，不应被包装脚本静默覆盖。项目只提供明确默认值或文档说明。

## UI locale and experience

Immich 当前 `release` 线 v3.2.4 与 v3.3.0 都已内置 [zh_Hans.json](https://github.com/immich-app/immich/blob/v3.3.0/i18n/zh_Hans.json) 与 [zh_Hant.json](https://github.com/immich-app/immich/blob/v3.3.0/i18n/zh_Hant.json)。Web 端还会把浏览器 locale 别名映射到内置语言：`zh-CN` / `zh-SG` → `zh-Hans`，`zh-TW` / `zh-HK` / `zh-MO` → `zh-Hant`。用户可在 **User Settings → App Settings → Language** 中选择语言；这是 per-user preference，上游没有提供统一强制所有用户的 server 环境变量。

本项目不维护 Immich UI translation fork，也不通过字符串替换修改前端 bundle。中文地名、检索和 reverse geocoding 数据与 UI locale 是独立契约：前者由本项目提供，后者由 Immich 上游和用户设置决定。

## Static assets and cache

上游对 `/_app/immutable` 设置 `public,max-age=31536000,immutable`，HTML 使用 `no-store` 或短时策略。Nginx/Delivery layer 只能对 immutable static asset 做 shared cache，不能把 `/api/*`、照片、缩略图、视频流或认证响应放入公共 cache。

可执行配置和 cache matrix 见 [中国网络与加速](china-acceleration.md)。

## EXIF time and timezone

照片详情页使用 `exifInfo.dateTimeOriginal` 和 `exifInfo.timeZone`，不是在页面渲染时统一套用 container `TZ`。如果目标是让已有照片详情统一显示为北京时间，必须显式更新 asset metadata；对应工具和风险见 [照片拍摄时间与时区](timezone.md)。

本项目不在 Immich server 启动时自动批量改写所有照片 timezone，因为这会改变用户可见的拍摄时间语义。新导入照片仍应保留原始 EXIF timezone，除非用户明确运行工具。

## Map and CSP

Immich 支持通过 Map Settings 配置 Light/Dark map style。默认 tile service 和 CSP allowlist 属于上游行为；自定义 map origin 需要同时处理地图服务许可和 `IMMICH_HELMET_FILE` CSP，否则浏览器可能拦截 tile request。

本项目不托管、复制或再分发第三方地图瓦片，也不承诺 GCJ-02 坐标转换。只提供同源 proxy、坐标系说明和可选部署边界。

## Release compatibility

当前文档区分以下 Immich 版本边界：

- `< 1.136.0`：语言覆盖路径为 `/usr/src/app/node_modules/...`；
- `1.136.0 ~ 3.2.x`：语言覆盖路径为 `/usr/src/app/server/node_modules/...`，国家名仍由 `i18n-iso-countries` 参与；
- `3.3.0+`：国家名读取 `countryInfo.txt`，不再需要旧语言覆盖文件。

这些边界来自上游源码核对，不替代真实镜像 smoke test。发布流程中的 full-stack smoke 会验证 PostgreSQL `geodata_places`、苏州样本和 `/api/server/config`，作为最终运行级验证层。

## Explicit non-goals

- 不 fork Immich UI 或 server 源码；
- 不通过字符串替换 patch 压缩后的 web bundle；
- 不强制所有用户使用同一个地图或 timezone；
- 不在没有备份和用户确认的情况下批量写 Immich 数据库；
- 不把 `ghcr.io`、第三方 mirror、CDN 或 tile provider 写成永久可用保证。
