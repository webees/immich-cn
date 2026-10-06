# 规范数据格式

本项目的第一等数据制品是 `dataset.sqlite.zip`。它是一个可查询的 SQLite 3 数据库归档，
用于直接分析、审计、二次开发或给新的消费者编写适配器；Immich 文本目录只是其中一个导出格式。

归档成员固定为：

| 成员 | 用途 |
|:--|:--|
| `dataset.sqlite` | 规范数据、索引与查询视图 |
| `schema.json` | 格式版本、表、视图和兼容边界说明 |
| `NOTICE.txt` | 上游数据来源与再分发署名 |
| `README.txt` | 最小查询示例与 Immich 适配器边界 |

## 核心表

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
| `in_default` | 是否进入默认非 full 变体 |

`place_names` 保存每个地点对应的国家与四级中文名；`admin_areas` 保存可从地点记录推导的
行政层级名称；`countries` 保存国家代码与名称；`sources` 保存本次构建使用的上游 URL、
SHA256、ETag 与 Last-Modified；`dataset_meta` 保存格式版本、工具版本、provider 与地点数。

`localized_places` 视图把 `places`、`place_names` 与 `countries` 联起来，查询时不必手工拼接表。

## 直接查询

```bash
unzip dataset.sqlite.zip
sqlite3 dataset.sqlite \
  "SELECT geoname_name, country_name, admin1_name, admin2_name, source
   FROM localized_places WHERE geoname_id = 1816670;"
```

也可以用 DuckDB、Python `sqlite3`、BI 工具或 SQL 导出程序读取。规范数据库不要求用户理解
Immich 的制表符列位置，也不要求把数据挂载到 Immich 目录。

## 版本与适配器

`schema.json` 与 `dataset_meta` 中的 `schemaVersion` 是规范结构版本；它与项目版本、
数据日期标签相互独立。规范字段的破坏性变更必须提升该版本。

需要 Immich 时，使用同一 Release 中的 `geodata.zip` 或 `geodata_full.zip`。它们由规范模型
导出，并通过 `docs/architecture.md` 中的制品契约校验；不能反过来要求规范模型复制 Immich
的文本列布局。
