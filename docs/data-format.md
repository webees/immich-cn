# 数据格式与制品命名

本项目的第一等数据制品是 `immich-cn-dataset-sqlite-v1.zip`：一个可查询的 SQLite 3 数据库归档，用于分析、审计、二次开发或编写新的适配器。Immich 文本目录只是其中一个导出格式。

## 规范数据

归档成员固定为：

| 成员 | 用途 |
|:--|:--|
| `immich-cn-dataset-v1.sqlite` | 规范数据、索引与查询视图 |
| `schema.json` | 格式版本、表、视图与兼容边界 |
| `NOTICE.txt` | 上游数据来源与再分发署名 |
| `README.txt` | 最小查询示例与 Immich 适配器边界 |

`places` 保存规范地点记录，一条记录对应一个 GeoNames ID：

| 字段 | 说明 |
|:--|:--|
| `geoname_id` | 稳定主键 |
| `name` / `ascii_name` | 上游名称与 ASCII 名称 |
| `country_code` | ISO 3166-1 alpha-2 |
| `latitude` / `longitude` | WGS-84 坐标，含边界约束 |
| `population` | 上游人口数，缺失按 0 处理 |
| `feature_class` / `feature_code` | GeoNames 要素分类 |
| `admin1_code` ~ `admin4_code` | 原始行政代码 |
| `source` | `cities500` 或 `extra` |
| `in_default` | 是否进入默认非完整变体 |

`place_names` 保存每个地点对应的国家与四级中文名；`admin_areas` 保存可从地点记录推导的行政层级名称；`countries` 保存国家代码与名称；`sources` 保存本次构建使用的上游 URL、SHA256、ETag 与 Last-Modified；`dataset_meta` 保存格式版本、工具版本、提供方与地点数。`localized_places` 视图把 `places`、`place_names` 与 `countries` 联起来，查询时不必手工拼接表。

```bash
unzip immich-cn-dataset-sqlite-v1.zip
sqlite3 immich-cn-dataset-v1.sqlite \
  "SELECT geoname_name, country_name, admin1_name, admin2_name, source
   FROM localized_places WHERE geoname_id = 1816670;"
```

也可以用 DuckDB、Python `sqlite3`、BI 工具或 SQL 导出程序读取。规范数据库不要求用户理解 Immich 的制表符列位置。`schema.json` 与 `dataset_meta` 里的 `schemaVersion` 是规范结构版本，与项目版本、数据日期标签相互独立；破坏性字段变更必须提升该版本。

### 适配器差异

规范数据集的 `admin_areas` 与适配器的 `admin1CodesASCII.txt` 由同一次构建产出，正常情况下逐条一致（2026-10-06 的发布里二级有 33,661 条可比记录、0 处差异）。唯一例外是 **HK/MO 的一级**：GeoNames 把区与堂区当作 admin1，而 Immich 会把 `admin1Name` 当省/州展示，因此适配器按 `SPECIAL_ADMIN_TOP_LEVEL` 把这两个地区的一级写成 `香港特别行政区` / `澳门特别行政区`，规范数据集保留可从地点记录推导的 `香港` / `澳门`（2026-10-06 发布中正好 26 条：HK 18 + MO 8）。`scripts/check_artifacts.py` 会比对两份制品，除该覆盖之外的任何差异都会失败，覆盖被静默去掉同样失败。

## 制品命名

当前规范只发布规范文件名，不生成别名。发布标签承载版本与日期，文件名承载制品类型、适配器、展示粒度、数据规模与结构版本。

```text
immich-cn.geodata.<profile>.<scope>.v<schema>
```

| 字段 | 说明 |
|:--|:--|
| `profile` | 稳定展示粒度 ID，例如 `admin2`、`admin2-admin3` |
| `scope` | `default` 或 `full` |
| `schema` | 制品结构版本，当前为 `v1` |

| 制品 | 文件名 |
|:--|:--|
| Immich 地理数据 | `immich-cn-geodata-<profile>-<scope>-v1.zip` |
| SQLite 规范数据集 | `immich-cn-dataset-sqlite-v1.zip` |
| 变体表 | `immich-cn-patterns-tsv-v1.gz` |
| i18n 兼容包 | `immich-cn-i18n-json-v1.zip` |
| 清单 | `immich-cn-manifest-json-v1.json` |
| 校验和 | `immich-cn-checksums-sha256-v1.txt` |

文件名不使用 `{}`、空格、下划线或别名。运行时占位符 `{admin_2}` 与制品展示粒度 ID `admin2` 是不同契约：前者必须保留花括号与下划线，后者只用于规范 ID、文件名与清单，两者不能互相替换。

```bash
immich-cn artifact resolve --manifest immich-cn-manifest-json-v1.json \
  --id immich-cn.geodata.admin2-admin3.full.v1
immich-cn artifact resolve --manifest immich-cn-manifest-json-v1.json \
  --profile admin2-admin3 --scope full
```

## 清单字段

`immich-cn-manifest-json-v1.json` 的 `artifactSpecVersion` 为 `4`，顶层字段如下（下面的 JSON 只展示命名与摘要相关部分）：

| 字段 | 内容 |
|:--|:--|
| `schemaVersion` | 规范数据集结构版本 |
| `tool` | 生成工具的名称、版本与提交修订 |
| `generatedAt` | 本次构建时间，使用北京时间 `+08:00` |
| `providers` | 本次使用的提供方列表 |
| `stats` | 规范层口径的各级记录数、去重与覆盖率统计 |
| `index` | 中文名称索引规模 |
| `adminEntries` | 行政层级条目数 |
| `config` | 构建配置快照 |
| `sources` | 每个上游文件的 URL、SHA256、大小、ETag 与 Last-Modified |
| `artifactSpecVersion` | 制品命名规范版本，当前为 `4` |
| `artifacts` | 规范地理数据制品索引 |
| `assets` | 完整发布文件索引 |
| `patternsTable` | 运行时变体表文件名 |
| `dataset` | 规范数据集的文件名、格式、结构版本、大小与摘要 |
| `license` | 代码与数据许可说明 |

`artifacts` 的元素包含 `pattern`、`full`、`file`、`id`、`profile`、`scope`、`schemaVersion`、`canonicalFile`、`sizeBytes` 与 `sha256`；`assets` 的元素包含 `file`、`kind`、`sizeBytes` 与 `sha256`。清单与校验和文件自身不列入 `assets`，由 `immich-cn-checksums-sha256-v1.txt` 覆盖。

### 统计口径

`stats` 描述的是**规范层（完整名称表）**，不是某一个压缩包的文件内容：

- `sourcePlaces + extraPlaces == outputPlaces`；
- `perCountry` 各项之和等于 `outputPlaces`，按同一完整口径统计；
- `droppedPlaces = droppedCities + droppedExtra`：前者是 cities500 中缺少有效一级行政区代码而丢弃的噪声行，后者是国家数据转储在额外点位筛选阶段因 GeoNames ID 已存在或经纬度冲突而丢弃的记录；两者来源不同，合并计数会掩盖差异；
- 默认变体在打包时按人口阈值过滤 extra 记录，因此变体行数小于 `outputPlaces`；每个变体的展示粒度与数据规模记录在包内 `geodata/build-info.json`，行数以包内 `cities500.txt` 为准。

实测示例（发布 `data-2026-10-06`）：`outputPlaces=1318848`、`perCountry.CN=956792`，而 `immich-cn-geodata-admin2-default-v1.zip` 内 `cities500.txt` 为 256,644 行、其中 CN 34,897 行（= `sourcePlaces` 235,649 + 人口 ≥100 的 extra 20,995）。把 `stats` 当作「这个 zip 有多少条记录」会高估。

## 目录约束

发布路径使用 `gh release upload ... dist/*`，因此 `dist/` 必须只包含本次构建登记的制品：

- `immich-cn-checksums-sha256-v1.txt` 只登记清单里的 `artifacts` 与 `assets`（外加清单自身），不扫描目录，非登记文件不会被签名；
- `scripts/check_artifacts.py` 会拒绝任何未登记的残留文件（非规范命名、临时文件），并提示清理或改用 `immich-cn all --clean`。
