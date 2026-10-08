# 运维与常见问题

## 数据生效

Immich 只在 `geodata-date.txt` 与上次导入记录的值**不同**时才重新导入（上游 `server/src/repositories/map.repository.ts` 是「相等就返回」），因此写入不同的新值即可触发：

```bash
TZ=Asia/Shanghai date +"%Y-%m-%dT%H:%M:%S+08:00" > ./geodata/geodata-date.txt
```

使用镜像时可设置 `IMMICH_CN_FORCE_RELOAD=1`。日志出现 `geodata records imported` 表示导入完成。

## 地点英文

按顺序排查：`cities500.txt` 第 1 列是否已是中文；Immich 是否真的导入新数据（重启并看日志）；是否执行过「提取元数据 → 全部」；Immich 版本是否属于 1.136.0 ~ 3.2.x（需要 `i18n-iso-countries` 覆盖）或低于 1.136.0（挂载路径不同）而漏挂载。

## 边界粒度

Immich 用「最近的点」做反向地理编码，边界误差是原理性的。可改用 `immich-cn-geodata-admin2-full-v1.zip`（点位更多、导入更慢），或到 [GeoNames](https://www.geonames.org/) 补充缺失地点，下次构建会自动收录。

粒度用 `IMMICH_CN_PATTERN` 或直接下载对应 zip：

| 想要的结果 | 建议 |
|:--|:--|
| 只到城市 | `{admin_2}` |
| 城市 + 区县 | `{admin_2} {admin_3}` |
| 到乡镇 | `{admin_2} {admin_3} {admin_4}` |

默认不启用高德：其 API 密钥属于个人账号，服务条款可能限制结果再分发；离线 GeoNames 层级表无需密钥即可自动运行与再分发。需要乡镇粒度时配置 `AMAP_API_KEY` 并加 `--provider amap`（`--provider auto` 缺密钥会打印降级告警）。

## 坐标偏移

项目输出的是 WGS-84 坐标；OpenStreetMap 及其衍生底图通常同为 WGS-84，不会系统性偏移，高德、腾讯等 GCJ-02 底图会有约数百米偏移。Immich 不负责坐标转换，本项目也不在数据里混入 GCJ-02 坐标，请优先选 WGS-84 底图，或在瓦片、代理、独立转换层处理。详见 [中国本地化与加速](china.md)。

## 网络镜像

国内拉取 GHCR 不稳定时，使用 `IMMICH_CN_GHCR_MIRROR` 选择镜像源，并从官方源确认摘要后按同一摘要拉取；第三方镜像源不是可信回源，必须校验 TLS 与内容摘要。CDN 与静态资源加速的边界、地图瓦片加速、镜像体积差异见 [中国本地化与加速](china.md)。

镜像内置的是默认非完整数据集（`build/geodata`），因此体积远小于完整变体；需要更多点位时改用 `immich-cn-geodata-admin2-full-v1.zip` 或发布里的其他完整变体。

## 拍摄时间

照片详情页使用 `exifInfo.dateTimeOriginal` 与 `exifInfo.timeZone`，不会套用容器 `TZ`。要让已有照片显示为北京时间，必须显式更新照片元数据，见 [照片拍摄时间与时区](timezone.md)。

## 更新频率

设计频率为每天一次（北京时间 13:23，UTC 05:23）。GitHub 的 `schedule` 会被延迟甚至整轮跳过：2026-10-06 起两天内仓库只有一次 `schedule` 运行。因此「每天」是设计频率，不等于「每天必有一次运行」；可追踪性由 `monitor-update.yml` 保证。

## 清理保留

仓库会持续产生发布快照、Actions 运行记录与 GHCR 版本，`cleanup.yml` 每周自动执行一次，也支持手动试运行与受控执行。

默认不会删除：语义版本发布与镜像标签、滚动发布 `auto-release`、镜像标签 `latest` 与 `release`、当前正在执行的 Actions 运行、语义版本发布对应提交上的运行。

| 对象 | 默认规则 |
|:--|:--|
| `data-*` 发布快照 | 保留最近 3 个 |
| Actions 运行 | 保留最近 30 天，且每个工作流至少保留最近 20 次 |
| GHCR 包版本 | 每个包保留最近 20 个版本 |

受保护标签命中的版本额外保留；无标签版本通常是多架构索引的子清单或证明对象，`sha256-*` / `sha256:*` 这类摘要形式标签可能是证明或索引，当前策略不会直接删除这两类版本。单项删除失败不阻断其他项，脚本会在最后汇总失败数量。

滚动发布 `auto-release` 由 `update-data.yml` 自我收敛：先执行 `scripts/cleanup.py --prune-release-assets auto-release --dist-dir dist --apply` 删除不在本次 `dist` 清单里的资产，再执行 `--verify-release-assets` 验证完全一致。清理脚本默认试运行；清单为空、或与发布资产没有任何交集时直接拒绝执行。

尚未形成稳定版本时可手动触发 `cleanup.yml` 并启用 `prune-all`：`data-*` 只保留最新一个、每个工作流只保留最新一次运行、每个包只保留最新一个版本，语义版本与 `auto-release`、`latest`、`release` 仍受保护。

`prune-legacy-assets` 用于回收语义版本发布中的非规范命名资产。它默认只做试运行，且仅当仓库中已经存在规范替代品时才删除；没有规范替代品时只报告、不删除，避免把唯一分发入口清空。定时清理只有在仓库变量 `PRUNE_LEGACY_ASSETS=true` 时才启用该模式，默认关闭；手动触发仍可单次选择。

`prune-superseded-versions` 用于回收三段式版本标签（`1.0.x`）的 GHCR 版本：默认只做试运行，且仅当同一个包里已经存在四段式 Immich 对齐版本时才删除。只有「三段式版本标签 + 同一提交的 `sha-<短提交>`」这一种组合会被回收；带 `latest`、`release`、日期、`sha256-*` 或第二个版本号标签的版本一律不动。定时清理只有在仓库变量 `PRUNE_SUPERSEDED_VERSIONS=true` 时才启用该模式，默认关闭；手动触发仍可单次选择。

手动检查默认先试运行：

```bash
GITHUB_REPOSITORY=webees/immich-cn GITHUB_TOKEN=<token> \
python scripts/cleanup.py --release-retention 14 \
  --run-retention-days 30 --run-keep-per-workflow 20 --package-retention 20
```

确认计划后再加 `--apply`。GHCR 删除使用 GitHub Packages API；工作流优先使用 `GITHUB_TOKEN`，若仓库策略不允许访问用户级软件包，可配置具备 `read:packages` / `delete:packages` 的 `PACKAGE_ADMIN_TOKEN`，没有权限时任务失败并保留日志。试运行会先打印真实读到的数量，再打印待删除项；某个包返回 0 个版本时直接失败（`--allow-empty-packages` 才放行），避免「没有可删项」与「什么都没读到」看起来一样。

## 告警监控

清理失败与自动更新失败都会创建或更新带 `automation` 标签的议题，并在恢复后自动评论关闭。`monitor-update.yml` 每 6 小时检查自动更新的新鲜度：超过 30 小时没有触发、运行长时间停住、最近一次失败或长期没有成功时告警，恢复后关闭。单次跳过落在 30 小时容忍窗口内不会告警，这是留给 GitHub 定时延迟的余量。

## 审计工具

- `make audit-ledger`：审计账本的汇总必须能按轮次从明细复算；CI 的 Docker 冒烟作业会从 `audit` 分支读取账本并执行同一校验；
- `make audit-pins`：Action 固定引用必须与注释里的版本标签指向同一提交（需要网络与令牌）；CI 的 Python 作业也会执行同一脚本，防止 pin 漂移；
- `make audit-dead-symbols`：扫描 `src/` 与 `scripts/` 的零引用模块级定义；CI 的 Python 作业也会执行同一扫描。
