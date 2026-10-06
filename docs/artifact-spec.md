# 制品命名规范 v2

当前 Release 中的 `geodata.zip`、`geodata_admin_2.zip` 等名称是兼容层。规范 v2 将
机器可读的 canonical ID 与文件名分离，避免消费者解析内部 pattern 字符串。

## Canonical ID

```text
geodata.immich.<profile>.<scope>.v<schema>
```

| 字段 | 说明 |
|:--|:--|
| `profile` | 稳定 profile ID，例如 `admin2`、`admin2-admin3` |
| `scope` | `default` 或 `full` |
| `schema` | 制品 schema 版本，当前为 `v1` |

示例：

```text
geodata.immich.admin2.default.v1
geodata.immich.admin2-admin3.full.v1
```

## Canonical 文件名

```text
immich-cn-geodata-immich-<profile>-<scope>-v<schema>.zip
```

示例：

```text
immich-cn-geodata-immich-admin2-default-v1.zip
immich-cn-geodata-immich-admin2-admin3-full-v1.zip
```

文件名不使用 `{}`、空格或下划线；Release tag 继续承载日期与发布版本，文件名只承载
schema 版本。

## Manifest 与兼容别名

`manifest.json` 的 `artifactSpecVersion` 为 `2`，`artifacts` 是 canonical 索引，
每个条目同时包含：

- `id`：canonical ID；
- `canonicalFile`：v2 规范文件名；
- `file`：当前实际下载的兼容文件名；
- `profile`、`scope`、`schemaVersion`、`pattern`、`sha256`、`sizeBytes`。

`aliases` 把稳定入口映射到 canonical ID：

```json
{
  "artifactSpecVersion": 2,
  "aliases": {
    "geodata.zip": "geodata.immich.admin2.default.v1",
    "geodata_full.zip": "geodata.immich.admin2.full.v1"
  }
}
```

稳定入口 `geodata.zip` 与 `geodata_full.zip` 继续保留；其他旧变体名只作为迁移期兼容名，
不再新增重复的默认 profile 资产。

## 解析 canonical 制品

使用 CLI 解析 manifest，不需要手写 JSON：

```bash
immich-cn artifact resolve --manifest dist/manifest.json \
  --id geodata.immich.admin2-admin3.full.v1

immich-cn artifact resolve --manifest dist/manifest.json \
  --alias geodata.zip

immich-cn artifact resolve --manifest dist/manifest.json \
  --profile admin2-admin3 --scope full
```

输出包含 `id`、`file`、`canonicalFile`、`profile`、`scope`、`sha256` 等字段，适合脚本和
下载器直接消费。

## 迁移规则

1. 当前 Release 继续发布兼容文件名，同时在 manifest 中发布 canonical ID。
2. 下一阶段只对新 immutable snapshot 发布 canonical 文件名。
3. 旧变体名至少保留一个发布周期，并通过 `aliases` 说明替代目标。
4. 删除旧名之前必须先通过制品契约、文档引用和回滚路径验证。
