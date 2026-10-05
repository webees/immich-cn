# 架构设计

## 目标

Immich 的反向地理编码需要一组固定格式的文本文件（见 `server/src/repositories/map.repository.ts`）。本项目的职责是：

1. 从公开数据源生成这组文件；
2. 把地名汉化到「国家 → 一级行政区 → 二级行政区 → 三级行政区 → 四级行政区」；
3. 以数据制品（Release zip）与容器镜像两种形式发布；
4. 让整条链路可以在没有人工干预的情况下周期运行。

## 流水线分层

```
                    ┌──────────────────────────────────────────────┐
   上游数据源        │ GeoNames  Natural Earth  i18n-iso-countries  │
                    └───────────────────┬──────────────────────────┘
                                        │ fetch（缓存 + SHA256 指纹）
                                        ▼
                    ┌──────────────────────────────────────────────┐
   数据准备          │ prepare cities500 / extra dumps / admin 表    │
                    └───────────────────┬──────────────────────────┘
                                        ▼
                    ┌──────────────────────────────────────────────┐
   翻译             │ alternateNamesV2 → 中文名索引                 │
                    │ admin1/2 代码表 + ADM3/ADM4 → 四级层级表      │
                    └───────────────────┬──────────────────────────┘
                                        ▼
                    ┌──────────────────────────────────────────────┐
   增强（可选）      │ provider 链：offline → amap / nominatim       │
                    └───────────────────┬──────────────────────────┘
                                        ▼
                    ┌──────────────────────────────────────────────┐
   产出             │ geodata/ + levels.tsv + patterns.tsv          │
                    │ → 各展示粒度 zip、manifest、SHA256SUMS         │
                    │ → patterns.tsv.gz（镜像运行时切换粒度）        │
                    └───────────────────┬──────────────────────────┘
                                        ▼
                    ┌──────────────────────────────────────────────┐
   发布             │ GitHub Release  +  GHCR 数据镜像 / Immich 镜像 │
                    └──────────────────────────────────────────────┘
```

对应代码：

| 阶段 | 模块 |
|:--|:--|
| 下载与缓存 | `immich_cn.http`、`immich_cn.config` |
| 解析 | `immich_cn.geonames` |
| 中文解析 | `immich_cn.chinese` |
| 层级表 | `immich_cn.hierarchy` |
| 可选增强 | `immich_cn.providers.*` |
| 编排 | `immich_cn.build` |
| 打包 | `immich_cn.package` |
| 校验 | `immich_cn.verify` |

## 关键设计决策

### 1. 默认零密钥

上游实现需要高德 API Key 才能生成国内数据。本项目把 provider 拆成可选层：

- `offline`（默认）：只依赖 GeoNames，通过 `admin1CodesASCII.txt`、`admin2Codes.txt` 以及各国家 dump 中的 `ADM3`/`ADM4` 要素自建四级行政层级表。
- `amap`：配置 `AMAP_API_KEY` 后启用，用高德补充区县/乡镇，结果按坐标缓存到磁盘。
- `nominatim`：配置后启用，用 OSM 补充海外数据，严格遵守 1 QPS 与真实 User-Agent 的使用条款。
- `auto`：有 `AMAP_API_KEY` 时等价于 `amap`，否则等价于 `offline`。

这样 GitHub Actions 在没有任何 Secret 的情况下依然可以完成「数据更新 → 校验 → 发布」全链路。

### 2. 展示粒度与数据解耦

上游把 7 种粒度 × 2 种数据规模预生成为 14 个 zip。本项目把「地点 → 四级名称」抽成 `levels.tsv`：

- Python 侧按 `--patterns` 在打包时组合，产出与上游一致的 zip；
- 镜像侧额外附带 `patterns.tsv.gz`，容器启动时用 `awk` 重写 `cities500.txt` 的第 1、2 列，
  因此**同一个镜像可以通过 `IMMICH_CN_PATTERN` 切换粒度**，不需要重新构建或下载。

### 3. full 与非 full

- 非 full（默认，`geodata.zip`）：`cities500.txt` + 国家 dump 中人口 ≥ 100 的记录 + 四个直辖市下辖全部记录。
- full（`geodata_full.zip`）：额外包含人口为 0 的行政要素，边界识别更准、导入更慢。

两者共用同一份 `levels.tsv`，打包时按人口阈值过滤，避免重复解析国家 dump。

### 4. 可审计

每次构建会在 `manifest.json` 中记录：

- 每个上游文件的 URL、SHA256、大小、ETag、Last-Modified；
- 各级行政表条目数、源记录数、输出记录数、中文覆盖率；
- 14 个变体各自的 SHA256 与体积；
- 使用的 provider 列表。

### 5. 校验前置

`immich_cn.verify` 在发布前检查：

- 必需文件是否齐全；
- `geodata-date.txt` 是否为合法 ISO 时间；
- `cities500.txt` 列数、GeoNames ID 唯一性；
- 中国记录中文名称覆盖率是否达到阈值；
- `countryInfo.txt` 中文覆盖率；
- `ne_10m_admin_0_countries.geojson` 是否为合法 FeatureCollection。

任何一项失败都会让 GitHub Actions 中断，不会发布坏数据。

## 全自动更新机制

数据更新是全自动的，不需要任何人工介入：

```
每天 UTC 05:23（cron）
   │
   ├─ 1. 条件校验上游：ETag / Last-Modified → 未变化返回 304，0 字节正文
   ├─ 2. 计算数据指纹：sha256(上游文件 SHA256 + 构建配置)
   ├─ 3. 与上一次发布的 manifest.json 对比
   │      ├─ 相同 → 跳过发布与镜像推送（no-change job 记录摘要）
   │      └─ 不同 → 继续
   ├─ 4. 构建 7 种粒度 × full/非 full，并执行发布前校验
   ├─ 5. 推送多架构镜像并更新 Release
   └─ 6. 清理超出保留数量的旧日期快照
```

三个关键点：

1. **增量校验而不是全量下载**：`immich_cn.http.Fetcher` 在 `--revalidate` 下带
   `If-None-Match` / `If-Modified-Since` 请求上游；数据源支持强 ETag，未更新时直接返回 304，
   因此每日运行的额外带宽几乎为零。校验失败时自动回退到本地缓存，保证流水线不会被网络抖动打断。
2. **内容指纹而不是时间戳**：`immich_cn.fingerprint` 只对"上游文件内容摘要 + 构建配置"求哈希，
   不含构建时间。这样只要数据与配置没变，无论跑多少次都会得到相同指纹，可以安全地跳过发布，
   也不会让用户被迫重新导入百万级 geodata 记录。
3. **失败可见**：任一环节失败会自动创建或更新带 `automation` 标签的 issue，附带运行链接，
   修复后可用 `workflow_dispatch` 立即重跑（`force-publish` 可强制发布）。

可通过 `workflow_dispatch` 覆盖的参数：`provider`、`immich-version`、`push-images`、
`force-publish`、`snapshot-retention`（默认保留最近 14 个日期快照）。

## 地名组合规则

`{admin_1}` ~ `{admin_4}` 为占位符，组合时：

1. 空值自动回退到上一级（`admin_4 → admin_3 → admin_2 → admin_1`），保证不会输出空名；
2. 相邻重复的层级会被去掉，例如 `{admin_2} {admin_3}` 在 `admin_2 == admin_3` 时只输出一次；
3. 港澳在 GeoNames 中以堂区/区作为一级行政区，构建时重排为
   `admin_1 = 香港/澳门`、`admin_2 = 区`，香港还会补充新界/九龙/香港岛前缀；
4. 台湾的一级行政区固定为 `台湾省`，市县级名称落在 `admin_2`。

## 与 Immich 的接口

| 文件 | 用途 |
|:--|:--|
| `cities500.txt` | 反向地理编码点位，第 1 列是展示名 |
| `admin1CodesASCII.txt` | 一级行政区名称（第 1 列是展示名） |
| `admin2Codes.txt` | 二级行政区名称 |
| `countryInfo.txt` | 国家名称（Immich 3.x 起使用） |
| `geodata-date.txt` | 数据版本，Immich 用它决定是否重新导入 |
| `ne_10m_admin_0_countries.geojson` | 无城市点时的国家回退 |

旧版 Immich（< 3.0）通过 `i18n-iso-countries/langs/en.json` 获取国家名，镜像中同时提供该覆盖文件。
