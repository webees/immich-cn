# 制品命名规范 v3

v3 只发布 canonical 文件名，不生成任何历史别名。Release tag 承载版本与日期，
文件名承载制品类型、adapter、profile、scope 与 schema。

## Canonical ID

```text
geodata.immich.<profile>.<scope>.v<schema>
```

| 字段 | 说明 |
|:--|:--|
| `profile` | 稳定 profile ID，例如 `admin2`、`admin2-admin3` |
| `scope` | `default` 或 `full` |
| `schema` | 制品 schema 版本，当前为 `v1` |

## 发布资产名

| 制品 | 文件名 |
|:--|:--|
| Immich geodata | `immich-cn-geodata-immich-<profile>-<scope>-v1.zip` |
| SQLite 规范数据集 | `immich-cn-dataset-sqlite-v1.zip` |
| 变体表 | `immich-cn-patterns-tsv-v1.gz` |
| i18n 兼容包 | `immich-cn-i18n-json-v1.zip` |
| Manifest | `immich-cn-manifest-json-v1.json` |
| 校验和 | `immich-cn-checksums-sha256-v1.txt` |

示例：

```text
immich-cn-geodata-immich-admin2-default-v1.zip
immich-cn-geodata-immich-admin2-admin3-full-v1.zip
```

文件名不使用 `{}`、空格、下划线或历史别名。

## Manifest

`immich-cn-manifest-json-v1.json` 的 `artifactSpecVersion` 为 `3`。

`artifacts` 只列 geodata canonical 制品：

```json
{
  "artifactSpecVersion": 3,
  "artifacts": [
    {
      "id": "geodata.immich.admin2-admin3.full.v1",
      "file": "immich-cn-geodata-immich-admin2-admin3-full-v1.zip",
      "canonicalFile": "immich-cn-geodata-immich-admin2-admin3-full-v1.zip",
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

`assets` 是完整发布文件索引；`artifacts` 是 canonical geodata 索引。manifest 与
checksums 文件自身不列入 `assets`，由 `immich-cn-checksums-sha256-v1.txt` 覆盖。

## 解析 canonical 制品

```bash
immich-cn artifact resolve --manifest immich-cn-manifest-json-v1.json \
  --id geodata.immich.admin2-admin3.full.v1

immich-cn artifact resolve --manifest immich-cn-manifest-json-v1.json \
  --profile admin2-admin3 --scope full
```

输出包含 `id`、`file`、`canonicalFile`、`profile`、`scope`、`sha256` 等字段。
