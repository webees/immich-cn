# 自动清理

仓库会持续产生 Release 快照、Actions 运行记录和 GHCR 镜像版本。为避免无限堆积， `cleanup.yml` 每周自动执行一次，也支持手动 dry-run 与受控 apply。

## 保护边界

默认策略不会删除以下内容；策略被修改或有人手动执行删除时不受此保证：

- 语义版本 Release 与镜像标签，例如 `v1.0.4`；
- 滚动数据 Release `auto-release`；
- 镜像标签 `latest` 与 `release`；
- 当前正在执行的 Actions 运行；
- 语义版本 Release 对应提交上的 Actions 运行。

## 默认保留策略

| 对象 | 默认规则 |
|:--|:--|
| `data-*` Release 快照 | 保留最近 3 个 `data-*` 快照 |
| Actions 运行 | 保留最近 30 天，且每个工作流至少保留最近 20 次 |
| GHCR 包版本 | 每个包保留最近 20 个版本 |

受保护标签命中的镜像版本会额外保留，不占“最近 20 个”之外的删除范围。没有标签的 GHCR 版本通常是多架构索引的子 manifest 或 attestation，当前策略不会直接删除，避免破坏仍受保护的父镜像索引。

## 稳定前激进清理

项目尚未形成稳定版本时，可手动触发 `cleanup.yml` 并启用 `prune-all`：

- `data-*` 只保留最新一个快照；
- 每个 Actions 工作流只保留最新一次运行；
- 每个 GHCR 包只保留最新一个版本；
- 语义版本、`auto-release`、`latest`、`release` 仍然保护。

## 手动检查

默认先做 dry-run：

```bash
GITHUB_REPOSITORY=webees/immich-cn \
GITHUB_TOKEN=<token> \
python scripts/cleanup.py --release-retention 14 \
  --run-retention-days 30 --run-keep-per-workflow 20 \
  --package-retention 20
```

确认计划后再加 `--apply`。定时任务会自动 apply；手动触发默认只列出计划。

GHCR 删除使用 GitHub Packages API。工作流优先使用 `GITHUB_TOKEN`，如仓库策略不允许访问用户级 Package，可配置具备 `read:packages` / `delete:packages` 的 `PACKAGE_ADMIN_TOKEN`；没有权限时清理任务会失败并保留日志，不会静默跳过。
