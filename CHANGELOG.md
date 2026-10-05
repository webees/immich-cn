# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.0.0] - 2026-10-06

### 新增

- 独立的 MIT 许可实现，支持零密钥的离线中文地名构建；
- 从 GeoNames `ADM3`/`ADM4` 自建区县、乡镇层级表；
- 可选 provider：高德、Nominatim，均带限速与磁盘缓存；
- 7 种展示粒度 × full/非 full 共 14 个数据制品；
- `manifest.json` 记录上游 SHA256、统计数据；
- 发布前自动校验（文件齐全、去重、中文覆盖率）；
- GHCR 数据镜像与开箱即用的 Immich 覆盖镜像，支持运行时切换展示粒度；
- GitHub Actions：CI、每周自动更新、版本化发布；
- 完整中文文档：架构、数据源、部署、开发、许可、FAQ。
