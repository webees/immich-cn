# Immich 集成契约

本文记录 `immich-cn` 对 Immich 上游的实际依赖、可配置点、包装层边界，以及不能在本项目中安全解决的问题。核验基线为 2026-10-07 的上游源码，以及本仓库声明的 Immich 版本边界。

## 集成类别

| 类型 | 本项目策略 | 示例 |
|:--|:--|:--|
| 数据适配 | 生成 Immich 固定的地理数据文件 | `cities500.txt`、`admin1CodesASCII.txt`、`admin2Codes.txt`、`countryInfo.txt` |
| 配置与环境变量 | 通过 Immich 官方环境变量或配置文件改变行为 | `TZ`、`IMMICH_CONFIG_FILE`、`IMMICH_HELMET_FILE`、`IMMICH_TRUSTED_PROXIES` |
| 容器包装层 | 在启动前复制数据、设置粒度或生成时间戳 | `immich-cn-server`、`immich-cn-install` |
| 分发层 | Nginx 与 CDN 只处理公开静态资源和网络可达性 | `/_app/immutable/*`、GHCR 镜像源 |
| API 工具 | 通过 Immich 公开 API 对已有元数据做显式操作；v3.3.0 起优先 `PATCH /api/assets`，旧版仅在 404/405 时回退 `PUT` | `scripts/set_asset_timezone.py` |
| 上游内置语言 | 使用 Immich 已提供的界面语言，不复刻界面 | `zh_Hans`、`zh_Hant` |
| 必须由上游修改 | 不在本项目做不安全补丁或界面复刻 | 全局界面时区、任意地图瓦片 |

## 地理编码

上游 `server/src/repositories/map.repository.ts` 读取以下文件；其中 `cities500.txt` 的第 1 列（0 基）作为展示名、第 3 列（0 基）作为检索别名：

| 文件 | 关键字段/行为 |
|:--|:--|
| `cities500.txt` | `name` 来自第 1 列（0 基）；`alternateNames` 来自第 3 列（0 基）；坐标来自第 4、5 列（0 基） |
| `admin1CodesASCII.txt` | Immich 以第 0 列（0 基）为键、第 1 列（0 基）为名称建立 admin1 映射 |
| `admin2Codes.txt` | Immich 以第 0 列（0 基）为键、第 1 列（0 基）为名称建立 admin2 映射 |
| `countryInfo.txt` | 国家名来自第 4 列（0 基）；alpha-2 与 alpha-3 分别位于第 0、1 列（0 基） |
| `geodata-date.txt` | 与 Immich 元数据中的 `lastUpdate` **相等时跳过导入**，不等时重新导入 |
| `ne_10m_admin_0_countries.geojson` | 没有城市点时回退到国家边界；Immich 读取每个要素的 `properties.ADMIN` / `ADM0_A3` / `TYPE` 与 `geometry.coordinates`，写入 `naturalearth_countries` 的 NOT NULL 列 |

本文的「列」一律指 `line.split('\t')` 的 0 基下标，避免把「第 1 列」误读成自然语言中的“第一列”。本项目的职责是让这些文件始终符合上述列契约，并通过校验与制品校验和阻止坏数据发布。我们不在 Immich 数据库中直接写 `geodata_places`，也不覆盖 Immich 的数据库迁移。

### 导入过滤

读取 `cities500.txt` 时，上游会先按要素代码（`feature code`）丢掉一部分记录，这一步发生在本项目无法干预的导入阶段：

- 要素代码（第 7 列，0 基）为 `PPLX` 且国家代码（第 8 列，0 基）不是 `AU` 的记录被跳过；
- 要素代码为 `PPLH` 的记录在所有国家都被跳过；
- 只有落在 `reverseGeocodeMaxDistance`（上游常量，25 km）内、且未被上述规则丢弃的城市点才参与反向地理编码；没有命中时回退到 `ne_10m_admin_0_countries.geojson`，此时 `state` 与 `city` 为 `null`。

所以制品行数不等于 Immich 实际写入 `geodata_places` 的行数。2026-10-07 对当时全量制品实测：256,626 行中有 7,307 行会被跳过（7,278 行 `PPLX` 非 `AU`，29 行 `PPLH`），其中 `CN` 77 行。复算方式：解压任一地理数据制品，对 `geodata/cities500.txt` 按第 7、8 列（0 基）统计。

本项目不预先删除这些行。过滤规则是 Immich 的版本行为，制品仍需保持 GeoNames 语义完整；差异只在上文量化，不作为“全部记录都会出现在 Immich”的依据。

### 字段约束

导入后的记录写入 Immich `geodata_places`，该表的列宽与非空约束构成硬上限；超限会让整个导入失败，而不是丢弃单条记录：

| 文件字段（0 基） | Immich 列 | 约束 |
|:--|:--|:--|
| `cities500.txt` 第 1 列 | `name` | `varchar(200) NOT NULL` |
| `cities500.txt` 第 8 列 | `countryCode` | `char(2) NOT NULL` |
| `cities500.txt` 第 10 列 | `admin1Code` | `varchar(20)` |
| `cities500.txt` 第 11 列 | `admin2Code` | `varchar(80)` |
| `cities500.txt` 第 18 列 | `modificationDate` | `date NOT NULL` |

`validation.py` 对以上四项做构建期校验：`cities500-immich-columns` 检查长度上限与两字符 `countryCode`，`cities500-modification-date` 检查 `YYYY-MM-DD` 可解析性。这两项在 2026-10-07 的真实制品上均为 0 违规。

### 地点检索

上游 `server/src/repositories/search.repository.ts:searchPlaces` 用严格词相似度匹配四个字段，而不是 `LIKE`：

```sql
f_unaccent(name) %>> f_unaccent($1)
OR f_unaccent("admin2Name") %>> f_unaccent($1)
OR f_unaccent("admin1Name") %>> f_unaccent($1)
OR f_unaccent("alternateNames") %>> f_unaccent($1)
```

这四个字段分别来自 `cities500.txt` 第 1 列、`admin2Codes.txt`、`admin1CodesASCII.txt` 与 `cities500.txt` 第 3 列。因此中文检索同时依赖展示名、行政层级中文名与别名列，三者任一缺失都会让对应查询无结果。

`%>>` 与 `LIKE` 的召回并不等价：以 2026-10-07 的制品实测，`name = '苏州市'` 时 `name LIKE '苏州市%'` 为真，但 `name %>> '苏州'` 为假（严格词相似度 0.4 低于默认阈值 0.5），此时查询能命中只是因为别名列里存在独立的 `苏州` 词元。完整服务栈冒烟因此直接执行上面的谓词，并断言 `苏州市`、`苏州`、`Suzhou`、`蘇州`、`昆山` 都至少有 1 条命中，而不是用 `LIKE` 代替。

## 配置变量

以下变量属于 Immich 上游契约，可用于部署层调整：

| 变量 | 用途 | 本项目处理 |
|:--|:--|:--|
| `TZ` | 服务端进程与部分运行时的时区 | Compose 默认 `Asia/Shanghai` |
| `IMMICH_BUILD_DATA` | 固定地理数据、前端与插件的构建根目录 | 包装层保留并支持覆盖 |
| `IMMICH_CONFIG_FILE` | 使用 Immich 的 YAML/JSON 配置文件 | 文档记录，默认不启用 |
| `IMMICH_HELMET_FILE` | 配置 CSP/helmet，自定义地图回源时使用 | 文档记录，默认不启用 |
| `IMMICH_TRUSTED_PROXIES` | 反向代理后的可信代理范围 | 可选部署参数，默认交给 Immich |
| `IMMICH_WORKERS_INCLUDE` / `IMMICH_WORKERS_EXCLUDE` | 控制 API 与微服务工作进程 | 不在本项目默认改写 |
| `IMMICH_ALLOW_SETUP` | 是否允许初次初始化 | 不在本项目默认改写 |
| `IMMICH_IGNORE_MOUNT_CHECK_ERRORS` | 存储挂载检查策略 | 仅在用户显式配置时使用 |
| `IMMICH_ALLOW_EXTERNAL_PLUGINS` | 外部插件开关 | 默认不启用 |

改变这些变量会改变 Immich 的运行时行为，不应被包装脚本静默覆盖。项目只提供明确默认值或文档说明。

## 界面语言

2026-10-08 实测：Immich `release` 线为 v3.3.0；v3.2.4 与 v3.3.0 都已内置 [zh_Hans.json](https://github.com/immich-app/immich/blob/v3.3.0/i18n/zh_Hans.json) 与 [zh_Hant.json](https://github.com/immich-app/immich/blob/v3.3.0/i18n/zh_Hant.json)。Web 端还会把浏览器语言别名映射到内置语言标识：`zh-CN` / `zh-SG` → `zh-Hans`，`zh-TW` / `zh-HK` / `zh-MO` → `zh-Hant`。用户可在**用户设置 → 应用设置 → 语言**中选择语言；这是按用户保存的偏好，上游没有提供统一强制所有用户的服务端环境变量。

本项目不维护 Immich 界面翻译分支，也不通过字符串替换修改前端产物。中文地名、检索与反向地理编码数据同界面语言是两套独立契约：前者由本项目提供，后者由 Immich 上游与用户设置决定。

## 静态缓存

上游对 `/_app/immutable` 设置 `public,max-age=31536000,immutable`，HTML 使用 `no-store` 或短时策略。Nginx 与 CDN 只能对不可变静态资源做共享缓存，不能把 `/api/*`、照片、缩略图、视频流或认证响应放入公共缓存。

可执行配置与缓存矩阵见 [中国本地化与加速](china.md)。

## 拍摄时区

照片详情页使用 `exifInfo.dateTimeOriginal` 与 `exifInfo.timeZone`，不是在页面渲染时统一套用容器 `TZ`。如果目标是让已有照片详情统一显示为北京时间，必须显式更新照片元数据；对应工具与风险见 [照片拍摄时间与时区](timezone.md)。

本项目不在 Immich 服务端启动时自动批量改写所有照片时区，因为这会改变用户可见的拍摄时间语义。新导入照片仍应保留原始 EXIF 时区，除非用户明确运行工具。

## 地图配置

Immich 支持通过地图设置配置浅色与深色地图样式。默认瓦片服务与 CSP 白名单属于上游行为；自定义地图回源需要同时处理地图服务许可与 `IMMICH_HELMET_FILE` 的 CSP，否则浏览器可能拦截瓦片请求。

本项目不托管、复制或再分发第三方地图瓦片，也不承诺 GCJ-02 坐标转换。只提供同源代理、坐标系说明与可选部署边界。

## 兼容边界

当前文档区分以下 Immich 版本边界：

- `< 1.136.0`：语言覆盖路径为 `/usr/src/app/node_modules/...`；
- `1.136.0 ~ 3.2.x`：语言覆盖路径为 `/usr/src/app/server/node_modules/...`，国家名仍由 `i18n-iso-countries` 参与；
- `3.3.0+`：国家名读取 `countryInfo.txt`，不再需要旧语言覆盖文件。

这些边界来自上游源码核对，不替代真实镜像冒烟测试。发布流程中的完整服务栈冒烟会验证 PostgreSQL `geodata_places`、苏州样本和 `/api/server/config`，作为最终运行级验证层。

## 排除范围

- 不复刻 Immich 界面或服务端源码；
- 不通过字符串替换修改压缩后的前端产物；
- 不强制所有用户使用同一个地图或时区；
- 不在没有备份和用户确认的情况下批量写 Immich 数据库；
- 不把 `ghcr.io`、第三方镜像源、CDN 或瓦片提供方写成永久可用保证。
