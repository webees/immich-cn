# Architecture design

## 目标

本项目先定义自己的规范数据集，再把它导出给不同消费者。Immich 的反向地理编码需要一组固定格式的文本文件（见 `server/src/repositories/map.repository.ts`），但那只是适配器契约，不是项目的数据模型。职责是：

1. 从公开数据源生成可查询、可版本化的规范数据集；
2. 把地名汉化到「国家 → 一级行政区 → 二级行政区 → 三级行政区 → 四级行政区」；
3. 通过适配器导出 Immich 文本包，并以 Release 与容器镜像发布；
4. 让整条链路可以在没有人工干预的情况下周期运行；
5. 为中国部署场景提供地图、CDN、静态资源和源站缓存的接入边界，但不把私有照片或未授权瓦片纳入公共缓存。

## Pipeline layers

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
   产出             │ SQLite 规范数据集 + Immich geodata/ 适配器    │
                    │ + levels.tsv + immich-cn-patterns-tsv-v1.gz                │
                    │ → 各展示粒度 zip、manifest、immich-cn-checksums-sha256-v1.txt         │
                    └───────────────────┬──────────────────────────┘
                                        ▼
                    ┌──────────────────────────────────────────────┐
   发布             │ GitHub Release  +  GHCR 数据镜像 / Immich 镜像 │
                    └──────────────────────────────────────────────┘
```

对应代码：

| 阶段 | 模块 |
|:--|:--|
| 下载与缓存 | `immich_cn.fetching`、`immich_cn.settings` |
| 解析 | `immich_cn.geonames` |
| 中文解析 | `immich_cn.localization` |
| 层级表 | `immich_cn.hierarchy` |
| 可选增强 | `immich_cn.providers.*` |
| 编排 | `immich_cn.pipeline` |
| 规范数据集 | `immich_cn.dataset` |
| 打包 | `immich_cn.packaging` |
| 校验 | `immich_cn.validation` |

## 关键设计决策

### 0. 规范模型优先，外部契约只做适配

`immich-cn-dataset-sqlite-v1.zip` 中的 SQLite 数据集是本项目的规范模型，定义字段语义、schema 版本、索引和查询视图；`geodata*.zip` 仅把该模型导出为 Immich 当前需要的文件名、列位置和目录结构。 `levels.tsv`、`immich-cn-patterns-tsv-v1.gz`、`immich-cn-manifest-json-v1.json` 和 provider 缓存则是构建与兼容层，不会反向约束规范字段。未来新增消费者时应增加适配器或导出器，而不是改变规范模型的数据含义。

规范字段和用法见 [数据格式](data-format.md)，决策见 [ADR 0001](adr/0001-immich-output-contract.md)。

### 1. 默认无需 API Key

本项目的默认设计目标是无需付费 API Key 即可生成国内数据，因此把 provider 拆成可选层：

- `offline`（默认）：只依赖 GeoNames，通过 `admin1CodesASCII.txt`、`admin2Codes.txt` 以及各国家 dump 中的 `ADM3`/`ADM4` 要素自建四级行政层级表。
- `amap`：配置 `AMAP_API_KEY` 后启用，用高德补充区县/乡镇，结果按坐标缓存到磁盘。
- `nominatim`：配置后启用，用 OSM 补充海外数据，严格遵守 1 QPS 与真实 User-Agent 的使用条款。
- `auto`：有 `AMAP_API_KEY` 时等价于 `amap`，否则等价于 `offline`。

在 GitHub Actions 已授予所需仓库权限、上游服务可访问且未启用可选 provider 的前提下，默认离线路径不额外依赖 Secret，可完成「数据更新 → 校验 → 发布」流程。

### 2. 规范数据、展示粒度与适配器解耦

规范数据集保存地点、原始名称、坐标、人口、行政代码和中文四级名称，不包含某个呈现 pattern 的拼接结果。项目再把 7 种粒度 × 2 种数据规模导出为 14 个 Immich zip：

- Python 侧按 `--patterns` 在打包时组合，产出 Immich 适配器 zip；
- 镜像侧额外附带 `immich-cn-patterns-tsv-v1.gz`，容器启动时用 `awk` 重写 `cities500.txt` 的第 1、2 列，因此**同一个镜像可以通过 `IMMICH_CN_PATTERN` 切换粒度**，不需要重新构建或下载。

### 3. full 与非 full

- 非 full（默认，`immich-cn-geodata-admin2-default-v1.zip`）：`cities500.txt` + 国家 dump 中人口 ≥ 100 的记录 + 四个直辖市下辖全部记录。
- full（`immich-cn-geodata-admin2-full-v1.zip`）：额外包含人口为 0 的行政要素，边界识别更准、导入更慢。

两者共用同一份 `levels.tsv`，打包时按人口阈值过滤，避免重复解析国家 dump。

### 4. 可审计

每次构建会在 `immich-cn-manifest-json-v1.json` 中记录：

- 每个上游文件的 URL、SHA256、大小、ETag、Last-Modified；
- 各级行政表条目数、源记录数、输出记录数、中文覆盖率；
- 规范数据集与 14 个兼容变体各自的 SHA256、格式版本与体积；
- 使用的 provider 列表；
- 构建日期与 `geodata-date.txt` 使用北京时间 `+08:00`。

镜像发布还附带 BuildKit provenance 与 SBOM；server 覆盖镜像在构建前把 Immich tag 解析为 base digest，并用 `tag@digest` 固定本次构建。base digest 参与 change detection，Immich base 更新时会触发 server image 重建。推送后按最终 digest 重新拉取执行入口 smoke test，再用 Trivy 扫描漏洞和许可证。在当次扫描数据库和扫描范围内，数据镜像阻断 `HIGH`/`CRITICAL`； Immich 覆盖镜像与同一 base digest 做差集，只阻断新增漏洞并把继承项写成例外报告。最后通过 GitHub OIDC 使用 Cosign 做 keyless 签名，并对两个最终 digest 执行 `cosign verify`。

### 5. 校验前置

`immich_cn.validation` 在发布前检查：

- 必需文件是否齐全；
- `geodata-date.txt` 是否为合法 ISO 时间；
- `cities500.txt` 列数、GeoNames ID 唯一性；
- 中国与香港记录的中文名称覆盖率是否达到阈值；
- 中文地区（CN/HK/TW/MO）记录的中文名称是否**零缺失**（`chinese-regions-cjk-strict`，与打包阶段的同名判断一致；阈值检查允许少量缺失，严格检查不允许）；
- `countryInfo.txt` 中文覆盖率；
- `ne_10m_admin_0_countries.geojson` 是否为合法 FeatureCollection。

任一已实现检查失败都会让 GitHub Actions 中断，阻止该次发布。该校验不等于对所有潜在数据错误的形式化证明。

## 全自动更新机制

数据更新按设计无需人工介入；实际运行依赖 GitHub Actions、上游服务和仓库权限正常：

```
每天 UTC 05:23（cron）
   │
   ├─ 1. 条件校验上游：ETag / Last-Modified → 未变化返回 304，0 字节正文
   ├─ 2. 计算发布指纹：sha256(上游文件 SHA256 + 构建配置 + 发布器修订)
   ├─ 3. 与上一次发布的 immich-cn-manifest-json-v1.json 对比
   │      ├─ 相同 → 跳过发布与镜像推送（no-change job 记录摘要）
   │      └─ 不同 → 继续
   ├─ 4. 构建 7 种粒度 × full/非 full，并执行发布前校验
   ├─ 5. 推送多架构镜像并更新 Release
   └─ 6. 清理超出保留数量的旧 data-* 快照
```

三个关键点：

1. **增量校验而不是全量下载**：`immich_cn.fetching.Fetcher` 在 `--revalidate` 下带 `If-None-Match` / `If-Modified-Since` 请求上游；数据源支持强 ETag，未更新时直接返回 304，因此上游返回 304 时正文传输为 0；请求连接和头部仍有少量开销。校验失败时会尝试回退到本地缓存，缓存缺失或损坏时仍会按错误路径失败。
2. **内容指纹而不是时间戳**：`immich_cn.fingerprint` 对"上游文件内容摘要 + 构建配置 + 发布器修订 + manifest schema"求哈希，不含构建时间。在实现与输入不变的前提下，同一份数据与同一版发布器重复计算会得到相同指纹；只有目标摘要、Immich base digest、data image digest、data image 存在性、`auto-release` asset 集合与最新 `data-*` 不可变快照全部匹配时，才可以跳过发布。构建逻辑修复后会主动发布新镜像，不会把旧制品误判成最新。
3. **失败可见**：任一环节失败会自动创建或更新带 `automation` 标签的 issue，附带运行链接，修复后可用 `workflow_dispatch` 立即重跑（`force-publish` 可强制发布）。

历史垃圾由独立的 `cleanup.yml` 每周清理：Release 快照、Actions 运行与 GHCR 版本按 [保留策略](maintenance.md) 处理，语义版本与稳定标签在默认策略下受保护。

可通过 `workflow_dispatch` 覆盖的参数：`provider`、`immich-version`、`push-images`、 `force-publish`、`snapshot-retention`（默认保留最近 3 个 `data-*` 快照）。

### 失败路径真值表

自动化任务之间有依赖关系，失败路径必须逐格确认（`update-data.yml`）：

| 场景 | `build` | `release` | 期望行为 |
|:--|:--|:--|:--|
| 构建失败 | ✗ | 跳过 | 创建/更新 `automation` issue 告警 |
| 上游无变化 | ✓ | 跳过 | `no-change` 记录摘要；关闭历史告警 |
| 有变化且发布成功 | ✓ | ✓ | 发布 Release 与镜像；关闭历史告警 |
| 有变化但发布失败 | ✓ | ✗ | **保留告警**（此时若关闭，会把刚创建的告警立刻关掉） |

`force-publish` 会把"无变化"也走发布分支，因此 `no-change` 与 `release` 必须互斥，否则同一次运行会同时输出"跳过发布"和"已发布"两份互相矛盾的摘要。

日期快照 `data-YYYY-MM-DD` 只代表当日第一次成功发布，不接受覆盖；同日因构建逻辑或上游数据再次变化而重跑时，会创建 `data-YYYY-MM-DD-sha-<短提交>`；在 GitHub 权限和仓库规则未被绕过的前提下，已创建的日期快照不会被覆盖。

`resolve-previous-failure` 的条件因此必须同时判断 `build` 与 `release` 的结果； `scripts/check_workflows.py` 会静态检查"用 `if` 判断依赖结果时是否遗漏了某个依赖"。

## 地名组合规则

`{admin_1}` ~ `{admin_4}` 为占位符，组合时：

1. 空值自动回退到上一级（`admin_4 → admin_3 → admin_2 → admin_1`）；至少一个层级非空时不会输出空名，全部层级为空时应被构建或校验流程拒绝；
2. 相邻重复的层级会被去掉，例如 `{admin_2} {admin_3}` 在 `admin_2 == admin_3` 时只输出一次；
3. 港澳在 GeoNames 中以堂区/区作为一级行政区，构建时重排为 `admin_1 = 香港/澳门`、`admin_2 = 区`，香港还会补充新界/九龙/香港岛前缀；
4. 台湾的一级行政区固定为 `台湾省`，市县级名称落在 `admin_2`。

## Immich 适配器输出

| 文件 | 用途 |
|:--|:--|
| `cities500.txt` | 反向地理编码点位，第 1 列（0 基）是展示名 |
| `admin1CodesASCII.txt` | 一级行政区名称；第 0 列（0 基）是键，第 1 列（0 基）是名称 |
| `admin2Codes.txt` | 二级行政区名称；第 0 列（0 基）是键，第 1 列（0 基）是名称 |
| `countryInfo.txt` | 国家名称；第 4 列（0 基）是名称（Immich **3.3.0** 起使用） |
| `geodata-date.txt` | 数据版本，Immich 用它决定是否重新导入 |
| `ne_10m_admin_0_countries.geojson` | 无城市点时的国家回退 |

分界点经上游源码核对：Immich **3.2.4 及以下**（含 3.0.0 ~ 3.2.4）在 `server/src/repositories/map.repository.ts` 里 `import { getName } from 'i18n-iso-countries'`，需要 `i18n-iso-countries/langs/en.json` 覆盖；**3.3.0 起**该 import 被移除，改为读取 `countryInfo.txt`（`resourcePaths.geodata.countryInfo`）。镜像中同时提供两种覆盖文件，切版本时按上表挂载即可。

## China localization delivery layer

数据构建与网络加速是两层不同职责：

- **数据层**：GeoNames、行政区划、中文别名、SQLite 规范数据集和 Immich geodata 适配器；
- **接入层**：Nginx、CDN、TLS、Brotli/HTTP2/3、静态资源缓存、地图同源代理和回源保护。

接入层只缓存 `/_app/immutable/*` 这类带构建摘要的公开资源。HTML、`/api/*`、原始照片、缩略图和视频流默认旁路；地图瓦片必须来自自有或明确授权的服务。可执行示例和完整缓存矩阵见 [中国本地化与加速](china.md)。
