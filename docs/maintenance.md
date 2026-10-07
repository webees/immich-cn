# Cleanup and retention

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

受保护标签命中的镜像版本会额外保留，不占“最近 20 个”之外的删除范围。没有标签的 GHCR 版本通常是多架构索引的子 manifest 或 attestation；`sha256-*` / `sha256:*` 这类 digest-like tag 也可能是 attestation 或索引。当前策略不会直接删除这两类版本，避免破坏仍受保护的父镜像索引。单个删除失败不会阻断其他清理项，脚本会继续执行并在最后汇总失败数量。

滚动 Release `auto-release` 由 `update-data.yml` 在每次上传后自我收敛：先调用 `scripts/cleanup.py --prune-release-assets auto-release --dist-dir dist --apply` 删除不在本次 `dist` 清单里的资产，再调用 `scripts/cleanup.py --verify-release-assets auto-release --dist-dir dist` 验证 Release 资产与 `dist` 完全一致。清理脚本默认 dry-run；清单为空、或清单与 Release 资产没有任何交集时直接拒绝执行，避免因为目录路径写错而清空整个 Release。不可变快照 `data-*` 不受影响。

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

每次 dry-run 会先打印**真实读到的数量**，再打印待删除项：

```text
[DRY-RUN] 观察到 Release 6 个、Actions 运行 132 次、GHCR 版本 immich-cn=21、immich-cn-server=22
[DRY-RUN] 待删除 Release：0
...
```

这样「没有可删项」与「什么都没读到」不会长得一样：如果某个包返回 0 个版本，脚本直接失败，因为 token 缺 `read:packages`、API 结构变化或 owner 写错都会产生空列表，而只打印四行 `0` 的计划看起来和「一切受保护」完全相同。确认包确实尚未创建时才用 `--allow-empty-packages` 显式放行。

## 失败告警

清理失败时会创建或更新带 `automation` 标签的 GitHub issue，标题为 `自动清理失败（YYYY-MM-DD）`，正文包含运行记录和触发方式；同一类告警只保留一个 open issue。后续清理成功后，工作流会评论并关闭该 issue。告警搜索始终限定 `automation` 标签与标题范围，避免误改用户 issue。

## 更新新鲜度监控

`monitor-update.yml` 每 6 小时（UTC 每 6 小时的 `:41`）检查一次 **Auto Data Update** 的真实执行情况。GitHub 的 `schedule` 事件在高负载时会被延迟甚至整轮跳过，而「调度没跑」与「跑了但上游无变化」在 Actions 页面上看起来完全一样；没有这层监控时，静默停摆可以持续到有人手动发现。

判定状态互斥且穷尽，`ok` 以外都会创建或更新带 `automation` 标签的 issue（标题 `自动更新停摆（YYYY-MM-DD）`），恢复后自动评论并关闭：

| 状态 | 含义 |
|:--|:--|
| `ok` | 最近运行、最近成功与最近一次定时触发都在阈值内 |
| `never_run` | 该工作流从未有任何运行记录 |
| `no_run` | 最近一次运行超过 `--max-age-hours` 没有出现，调度没有触发 |
| `stalled` | 最近一次运行长时间停在未完成状态 |
| `failed` | 最近一次已完成运行的结论是失败 |
| `stale_success` | 最近一段时间内没有任何成功运行 |
| `schedule_stalled` | 最近一段时间内没有 `schedule` 事件触发的运行 |

`schedule_stalled` 单独建模的原因：手动 `workflow_dispatch` 成功只说明「现在能跑」，不能证明「定时任务还活着」。因此监控同时检查两类年龄——任意运行的新鲜度，以及 `schedule` 事件运行的新鲜度。`cancelled` 是操作者动作，不直接判失败，但也不会被当作成功。

本地复现（需要 `actions:read` 权限的 token）：

```bash
GITHUB_TOKEN=<token> python -m scripts.check_update_freshness \
  --repository webees/immich-cn \
  --workflow update-data.yml \
  --max-age-hours 30 --stall-grace-hours 3
```

默认 30 小时阈值对应每天一次的调度：留出 6 小时给 GitHub 的定时延迟与重试。退出码 `0` 表示健康，`1` 表示已确认的不健康状态，`2` 表示配置或 API 错误——三者在工作流里都不会被当成成功。

## 审计账本

「连续 N 轮 clean」这个结论的证据是审计账本（发布在 `audit` 分支的 `work/audit/state.json`）。账本的汇总值一旦与明细脱钩，结论就无法被第三方复核，因此校验器把口径固定成**按轮次从 `history` 复算**：

- `round` = `history` 的最大轮次，且各轮次唯一、按顺序严格递增；
- `totals.findings` / `totals.clean_rounds` = 对应 verdict 的条目数；
- `totals.p0`~`p3` = severity 中包含该级别的条目数（`P1/P2` 同时计入两者）；
- `consecutive_clean` = 从最后一轮向前连续 `clean` 的条目数。

账本不在仓库树内（它记录的是被测 SHA 之外的审计过程），所以该检查不进 `make check`，需要显式执行：

```bash
make audit-ledger
```

2026-10-07 的复核发现过两类真实漂移：声明的 `findings` 是 184 而明细只有 170；以及三轮记录了确认的 P3 却仍标为 `clean`。前者按上述口径重算并把旧值保留在账本的 `totalsSuperseded`；后者按「clean 须无 P0-P3 已确认缺陷」改判为 `findings`，并在条目里写入 `reclassifiedFrom` 与理由。这类调整只会让 clean 变少，方向是收紧而不是放宽。

## Action pin 校验

`scripts/check_workflows.py` 只能离线校验 `uses:` 是否带 40 位十六进制 SHA，发现不了「SHA 存在但与注释里的版本不一致」——例如 pin 停在旧版本，或指到同名仓库的另一个提交，此时文件看起来完全合规。`scripts/check_action_pins.py` 用 GitHub API 把每个 pin 与注释里的 tag 对拍：

- 非本地 `uses:` 缺少 40 位 SHA → 失败；
- pin 没有 `# <version>` 注释 → 失败（无法复核版本含义）；
- 注释里的 tag 在上游不存在 → 失败；
- tag 解析出的 commit 与 pin 不一致 → 失败。

该检查需要网络与 token，因此不进 `make check`，按需执行：

```bash
make audit-pins
```

2026-10-07 实测：6 个工作流共 25 个固定引用，全部与上游 tag 一致（11 个不同 action，含 `actions/*`、`docker/*`、`aquasecurity/setup-trivy`、`sigstore/cosign-installer`）。

## 死代码扫描

「死代码与未使用配置」是固定的审计焦点，但此前每轮都靠手写扫描脚本，结论无法对拍：第 63/73/83 轮连续命中同一个零引用常量 `SHELL_SUFFIXES`，直到第 262 轮才真正删除。`scripts/check_dead_symbols.py` 把口径固定成：

- 扫描 `src/**/*.py` 与 `scripts/*.py` 的模块级 `def` / `async def` / `class` 与大写常量；
- 在仓库文本范围内（源码、测试、工作流、Makefile、文档、CHANGELOG）搜索名字；只在定义行出现即视为零引用；
- `__dunder__` 名字忽略；确认是外部入口（Protocol 方法、`__all__` 导出、被宿主反射调用）的写进 `ALLOWED` 并注明原因，而不是放宽规则。

```bash
make audit-dead-symbols
```

2026-10-07 的基线：501 个模块级定义里唯一零引用项是 `SHELL_SUFFIXES`（已删除）；删除后复查为「没有零引用定义」。
