# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 变更

- 数据更新频率由每周提升为**每天全自动检查并更新**；
- 新增 `--revalidate`：用 ETag/Last-Modified 条件校验上游，未变化时返回 304、不传输正文；
- 新增 `immich-cn fingerprint` 与 `manifest.json` 的 `config` 字段，
  用「上游文件摘要 + 构建配置 + 发布器修订」判断是否需要发布，避免无意义版本与重复导入；
- 发布指纹纳入 `manifest` schema、构建器版本与 CI 修订；只改构建逻辑时不会被误判为
  “无变化”而跳过新镜像发布；
- 镜像推送后按最终 digest 重新拉取并执行入口 smoke test，增加 Trivy 漏洞/许可证扫描与
  Cosign keyless 签名；server 覆盖镜像只阻断相对官方基础镜像新增的漏洞，并记录继承例外；
- 日期快照只记录当日首次发布；同日后续修订使用 `data-YYYY-MM-DD-sha-<短提交>`，
  避免覆盖不可变历史或让日期快照与 auto-release 的语义失真；
- 版本化 Release 同时给数据镜像与 Immich 覆盖镜像追加项目语义化版本标签；
- 项目定位改为完全独立实现，移除“重写”和上游横向比较；新增 ADR，明确 Immich
  外部读取契约与项目内部模型的边界；
- 新增 `no-change` 与 `notify-failure` 作业：无变化时明确记录并跳过发布，
  失败时自动创建/更新带 `automation` 标签的 issue；
- 新增日期快照保留策略（默认保留最近 14 个），自动清理过期快照。

## [1.0.0] - 2026-10-06

### 新增

- 独立的 MIT 许可实现，支持零密钥的离线中文地名构建；
- 从 GeoNames `ADM3`/`ADM4` 自建区县、乡镇层级表；
- 可选 provider：高德、Nominatim，均带限速与磁盘缓存；
- 7 种展示粒度 × full/非 full 共 14 个数据制品；
- `manifest.json` 记录上游 SHA256、统计数据；
- 发布前自动校验（文件齐全、去重、中文覆盖率）；
- GHCR 数据镜像与开箱即用的 Immich 覆盖镜像，支持运行时切换展示粒度；
- GitHub Actions：CI、自动更新、版本化发布；
- 完整中文文档：架构、数据源、部署、开发、许可、FAQ。
