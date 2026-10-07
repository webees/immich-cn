# Project scope

## Canonical positioning

`immich-cn` 为 Immich 提供中国本地化的 reverse geocoding geodata。它不 fork Immich，也不把 UI、地图、CDN 或容器运行时全部纳入本地化范围。

## Core scope

以下内容是项目必须交付和验证的核心：

- 中文 place name、四级 admin hierarchy 与逐级 fallback；
- 中文、拼音、英文和繁体的 searchable alias；
- canonical SQLite dataset 与 Immich geodata adapter；
- Auto Data Update workflow；
- GitHub Release 与 multi-arch container image；
- source hash、artifact hash、coverage、validation、provenance 与 retention。

核心能力必须通过 release validation；单项 coverage 不足时，文档必须写出缺口，不能把 roadmap 写成已完成事实。

## Optional support

以下内容是可选辅助能力，不属于 core geodata contract：

- map style、WGS-84/GCJ-02 说明与同源 tile proxy；
- EXIF `timeZone` 批量设置工具；
- CDN/cache 策略、Nginx origin 示例与 jsDelivr endpoint 配置；
- 国内部署、registry mirror、时区与故障排查说明。

上游 Immich 的固定契约、配置项与不可修改边界见 [Immich integration contract](immich-integration.md)。

可选能力可以独立升级、替换或禁用，不应改变 core geodata output contract，也不应被描述成 Immich 的完整本地化 fork。

## Non-goals

- 不维护 Immich UI translation fork；
- 不托管公共 CDN、地图 tile service 或对象存储；
- 不缓存私有照片、缩略图、视频流或认证 API；
- 不承诺第三方 mirror 的中国大陆线路质量或可用性；
- 不以 roadmap 代替 validation evidence。
