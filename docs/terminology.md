# 术语规范

项目面向中国用户，但技术细节统一使用英文术语。中文用于解释用户目标、使用场景、风险和操作结果，不用于创造新的技术名词。

## 使用规则

1. 命令、路径、环境变量、字段名、文件名、workflow/job 名、状态、协议和 API 名称保持原文。
2. 技术概念优先使用英文术语，例如 `artifact`、`manifest`、`checksum`、`workflow`、`pipeline`、`cache`、`coverage`、`validation`、`fingerprint`、`release`、`image`、`digest`、`provenance`、`SBOM`。
3. 同一篇文档首次出现英文术语时，可以用中文短句解释，但后续不要反复改写为中文技术名词。
4. 面向用户的叙述、注意事项、风险和结论继续使用中文；代码注释和日志可以使用中文，但变量、函数、类型和外部契约使用英文。
5. 纯中文 workflow 标题、badge alt text 或已有外部 job 名不应作为新增技术术语继续扩散；需要显示在仓库页面上的短标签使用英文。

## 核心术语

| English | 说明 |
|:--|:--|
| `artifact` | 构建或发布产物，包括 zip、SQLite dataset、manifest 等 |
| `checksum` | 内容摘要文件，例如 `immich-cn-checksums-sha256-v1.txt` |
| `manifest` | 描述 release、artifact、source 和 stat 的结构化文件 |
| `workflow` | GitHub Actions workflow |
| `pipeline` | 从 fetch 到 validate、package、release 的完整处理链 |
| `fingerprint` | 由 source hash、build config 和 publisher revision 计算的发布判断值 |
| `publisher revision` | 发布器代码 revision，用于判断构建逻辑是否变化 |
| `build config` | 影响输出的构建配置快照 |
| `cache` | 上游文件、HTTP response、CDN 或运行时资源的缓存 |
| `coverage` | 中文名、admin level 或 country name 的覆盖率指标 |
| `validation` | schema、完整性、引用、coverage 和负向输入检查 |
| `release` | GitHub Release 及其 asset |
| `asset` | GitHub Release 中的发布文件 |
| `image` | OCI/Docker container image |
| `digest` | 不可变 OCI image digest |
| `registry` | GHCR 等 container registry |
| `provenance` | 构建来源证明 |
| `SBOM` | Software Bill of Materials |
| `cache key` | CDN 或 Actions cache 的键 |
| `origin` | CDN 回源目标 |
| `TTL` | cache time-to-live |
| `rate limit` | provider 或 API 请求速率限制 |
| `read-only` | 只允许读取、不允许写入的挂载或文件 |
| `EXIF` | 照片元数据中的拍摄信息 |
| `timeZone` | Immich EXIF metadata 中的 IANA timezone 字段 |
| `dateTimeOriginal` | EXIF 原始拍摄时间字段 |
