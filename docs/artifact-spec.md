# Artifact naming spec v4

v4 只发布 canonical 文件名，不生成历史别名。Release tag 承载版本与日期，文件名承载制品类型、adapter、profile、scope 与 schema。

## Canonical ID

```text
immich-cn.geodata.<profile>.<scope>.v<schema>
```

| 字段 | 说明 |
|:--|:--|
| `profile` | 稳定 profile ID，例如 `admin2`、`admin2-admin3` |
| `scope` | `default` 或 `full` |
| `schema` | 制品 schema 版本，当前为 `v1` |

## Release asset names

| Artifact | File name |
|:--|:--|
| Immich geodata | `immich-cn-geodata-<profile>-<scope>-v1.zip` |
| SQLite 规范数据集 | `immich-cn-dataset-sqlite-v1.zip` |
| 变体表 | `immich-cn-patterns-tsv-v1.gz` |
| i18n 兼容包 | `immich-cn-i18n-json-v1.zip` |
| Manifest | `immich-cn-manifest-json-v1.json` |
| 校验和 | `immich-cn-checksums-sha256-v1.txt` |

示例：

```text
immich-cn-geodata-admin2-default-v1.zip
immich-cn-geodata-admin2-admin3-full-v1.zip
```

文件名不使用 `{}`、空格、下划线或历史别名。

### `{admin_2}` 与 `admin2`

- `{admin_2}` 是运行时 `IMMICH_CN_PATTERN` 的占位符语法，用户配置中必须保留花括号与下划线；
- `admin2` 是制品 profile ID，只用于 canonical ID、文件名和 manifest；
- 两者表达同一行政层级，但属于不同契约，不能互相替换。

## Manifest

`immich-cn-manifest-json-v1.json` 的 `artifactSpecVersion` 为 `4`。下面的 JSON 是命名与摘要相关字段的节选，完整 manifest 还包含构建元数据。

`artifacts` 只列 geodata canonical 制品：

```json
{
  "artifactSpecVersion": 4,
  "artifacts": [
    {
      "id": "immich-cn.geodata.admin2-admin3.full.v1",
      "file": "immich-cn-geodata-admin2-admin3-full-v1.zip",
      "canonicalFile": "immich-cn-geodata-admin2-admin3-full-v1.zip",
      "profile": "admin2-admin3",
      "scope": "full",
      "schemaVersion": 1,
      "sha256": "..."
    }
  ],
  "assets": [
    {
      "file": "immich-cn-dataset-sqlite-v1.zip",
      "kind": "dataset",
      "sha256": "..."
    }
  ],
  "patternsTable": "immich-cn-patterns-tsv-v1.gz",
  "dataset": {
    "file": "immich-cn-dataset-sqlite-v1.zip"
  }
}
```

### 顶层字段

| 字段 | 内容 |
|:--|:--|
| `schemaVersion` | 规范数据集 schema 版本 |
| `tool` | 生成工具的名称、版本与 CI 修订 |
| `generatedAt` | 本次构建时间，使用北京时间 `+08:00` |
| `providers` | 本次使用的 provider 列表 |
| `stats` | **规范层口径**的各级记录数、去重与覆盖率统计（见下文「stats 口径」） |
| `index` | 中文名称索引规模 |
| `adminEntries` | 行政层级条目数 |
| `config` | 构建配置快照 |
| `sources` | 每个上游文件的 URL、SHA256、大小、ETag 与 Last-Modified |
| `artifactSpecVersion` | 制品命名规范版本，当前为 `4` |
| `artifacts` | canonical geodata 制品索引 |
| `assets` | 完整发布文件索引 |
| `patternsTable` | 运行时变体表文件名 |
| `dataset` | 规范数据集的文件名、格式、schema 版本、大小与摘要 |
| `license` | 代码与数据许可说明 |

`artifacts` 的元素包含 `pattern`、`full`、`file`、`id`、`profile`、`scope`、 `schemaVersion`、`canonicalFile`、`sizeBytes` 与 `sha256`；`assets` 的元素包含 `file`、`kind`、`sizeBytes` 与 `sha256`。上面的 JSON 只展示命名与摘要相关字段。

### `stats` 口径

`stats` 描述的是**规范层（full 名称表）**，不是某一个 zip 的文件内容：

- `sourcePlaces + extraPlaces == outputPlaces`；
- `perCountry` 各项之和等于 `outputPlaces`，按同一 full 口径统计；
- `droppedPlaces = droppedCities + droppedExtra`：前者是 cities500 中缺少有效一级行政区代码而丢弃的噪声行，后者是 country dump 在额外点位筛选阶段因 GeoNames ID 已存在或经纬度冲突而丢弃的记录；两者来源不同，合并计数会掩盖差异；
- 非 full 变体在打包时按人口阈值过滤 extra 记录，因此变体的实际行数小于 `outputPlaces`；每个变体的 pattern 与 full 状态记录在包内 `geodata/build-info.json`，行数以包内 `cities500.txt` 为准。

实测示例（Release `data-2026-10-06`）：`outputPlaces=1318848`、`perCountry.CN=956792`，而 `immich-cn-geodata-admin2-default-v1.zip` 内 `cities500.txt` 为 256,644 行、其中 CN 34,897 行（= `sourcePlaces` 235,649 + 人口 ≥100 的 extra 20,995）。把 `stats` 当作“这个 zip 有多少条记录”会高估。同一次独立比对（上游 `cities500.zip` 的 sha256 与 manifest 记录一致）：上游 235,989 行中有 235,649 行进入制品，即 `droppedCities=340`；manifest 记录的 `droppedPlaces=31,277`，其余 30,937 来自 extra 阶段。

`assets` 是完整发布文件索引；`artifacts` 是 canonical geodata 索引。manifest 与 checksums 文件自身不列入 `assets`，由 `immich-cn-checksums-sha256-v1.txt` 覆盖。

### 输出目录不变量

发布路径使用 `gh release upload ... dist/*` 与 `gh release create ... dist/*`，因此 `dist/` 必须只包含本次构建登记的制品：

- `immich-cn-checksums-sha256-v1.txt` 只登记 manifest 的 `artifacts` 与 `assets`（外加 manifest 自身），不扫描目录，历史残留不会被签名；
- `scripts/check_artifacts.py` 会拒绝任何未登记的残留文件（旧命名、临时文件），并提示清理或改用 `immich-cn all --clean`。

## Resolve canonical artifact

```bash
immich-cn artifact resolve --manifest immich-cn-manifest-json-v1.json \
  --id immich-cn.geodata.admin2-admin3.full.v1

immich-cn artifact resolve --manifest immich-cn-manifest-json-v1.json \
  --profile admin2-admin3 --scope full
```

输出包含 `id`、`file`、`canonicalFile`、`profile`、`scope`、`sha256` 等字段。
