# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 变更（含破坏性）

- **制品命名升到 v4**：发布资产改为 canonical-only，不再生成历史别名。`immich-cn-geodata-<profile>-<scope>-v1.zip` 取代 `geodata_admin_2.zip`、`geodata_admin_2_full.zip` 等旧名，也取代过渡期的 `immich-cn-geodata-immich-*`；其他资产统一为 `immich-cn-dataset-sqlite-v1.zip`、`immich-cn-patterns-tsv-v1.gz`、`immich-cn-i18n-json-v1.zip`、`immich-cn-manifest-json-v1.json`、`immich-cn-checksums-sha256-v1.txt`。manifest 的 `artifactSpecVersion` 为 `4`，固定引用旧文件名的使用者需要迁移；
- 内部模块按职责重命名（`config.py` → `settings.py`、`build.py` → `pipeline.py`、`verify.py` → `validation.py` 等），命名规范见 `docs/naming-conventions.md`；
- manifest 的 `stats` 明确为规范层 full 口径，并新增 `droppedCities` / `droppedExtra` 分段记录丢弃原因；`docs/artifact-spec.md` 说明该口径与变体行数的差异；
- 滚动 Release `auto-release` 现在会按本次构建的 `dist` 清单回收不再发布的资产（此前 `upload --clobber` 只增不删，导致 21 个 pre-v4 资产长期残留）。

### 新增

- 项目定位升级为面向中国用户的 Immich 本地化项目，新增 `docs/china-localization.md` 说明显示、检索、部署、数据四个支柱、实测缺口与分阶段验收标准；
- 部署示例默认设置 `TZ: Asia/Shanghai`，并补充国内镜像获取、digest 验证、WGS-84/GCJ-02 偏移与故障排查说明；
- 规范 SQLite 数据集 `immich-cn-dataset-sqlite-v1.zip` 作为一等制品，Immich 文本格式改由适配器导出，详见 `docs/data-format.md` 与 ADR 0001；
- `immich-cn artifact resolve` CLI：按 canonical ID、profile+scope 或历史别名解析制品；
- 自动清理工作流 `cleanup.yml`：按保留策略清理 `data-*` 快照、Actions 运行与 GHCR 版本，并保护语义版本、`auto-release`、`latest`/`release` 标签与 untagged 子 manifest；
- 发布流水线新增完整 Immich 服务栈 smoke（PostgreSQL + Valkey + Immich，等待 `Geodata import completed`）与发布后自检文档承诺的固定下载地址；
- 打包期中文地名校验：CN/HK/TW/MO 的记录若展示名不含中文直接失败，并给出样例，避免英文/葡文地名进入制品；
- 文档与实现的一致性护栏：资产名、上游数据源清单、命名规范表、环境变量默认值、manifest 顶层字段、stats 口径、Markdown 链接、中文软换行、Immich 版本分界、required check 名、`hashFiles` 路径、checkout 凭据等。

### 修复

- 缓存键引用了已重命名的模块（`config.py`），导致哈希维度静默为空；现改为 `settings.py` 并由护栏拦截同类死路径；
- 所有 `actions/checkout` 显式关闭凭据持久化（`persist-credentials: false`）；
- 校验和只登记本次构建的制品：不再把 `dist/` 里的历史残留（旧名 `SHA256SUMS`、`geodata_*.zip` 等）写进 `immich-cn-checksums-sha256-v1.txt` 并随之发布，`check_artifacts` 也会拒绝未登记文件；
- GHCR 清理不再直接删除 untagged 子 manifest/attestation；清理 API 遇到 408/425/429/5xx 会退避重试，404 视为幂等成功；
- Release 说明与 Issue 模板引用了不存在的 `immich-cn-geodata-immich-*` 名称；Release 路径还缺少独立的 `immich-cn-i18n-json-v1.zip` 说明，Immich 1.136.0 ~ 3.2.x 用户会缺失国家名覆盖；
- 中国与澳门地名显示成英文/葡文（`Jiaojiang Shi`、`Nossa Senhora de Fátima` 等）：补 35 条 `[admins]` 覆盖并新增打包期校验；
- `--skip-fetch` 下国家 dump 缺失或名不副实时会静默产出空 `admin3`/`admin4`，现在直接报错；
- 缓存残行不再吞掉后续 JSONL 记录；归档解压新增单成员/整包/压缩比预算；
- 文档中的绝对化声明、中文软换行渲染空格、Immich 版本分界（实为 3.3.0）、数据集归档成员名、ADM4 覆盖口径等。

### 移除

- 不再生成历史资产别名与 legacy 变体（v4 canonical-only）；`data-*` 旧快照按保留策略清理。

## [1.0.4] - 2026-10-06

### 修复

- `immich-cn-server` 组合镜像的 OCI 许可元数据改为 `AGPL-3.0-only AND MIT`，不再把包含上游 Immich 代码的镜像错误声明为纯 MIT；

## [1.0.3] - 2026-10-06

### 修复

- geodata zip 与镜像数据目录新增 `NOTICE.txt`，使 GeoNames CC BY 4.0 等署名随再分发文件提供；

## [1.0.2] - 2026-10-06

### 修复

- 镜像 OCI 元数据将项目版本与数据日期分开记录：`org.opencontainers.image.version` 表示项目版本，`org.immich-cn.data-date` 表示数据批次；

## [1.0.1] - 2026-10-06

### 变更

- 数据更新频率由每周提升为**每天全自动检查并更新**；
- 新增 `--revalidate`：用 ETag/Last-Modified 条件校验上游，未变化时返回 304、不传输正文；
- 新增 `immich-cn fingerprint` 与 `immich-cn-manifest-json-v1.json` 的 `config` 字段，用「上游文件摘要 + 构建配置 + 发布器修订」判断是否需要发布，避免无意义版本与重复导入；
- 发布指纹纳入 `manifest` schema、构建器版本与 CI 修订；只改构建逻辑时不会被误判为 “无变化”而跳过新镜像发布；
- 镜像推送后按最终 digest 重新拉取并执行入口 smoke test，增加 Trivy 漏洞/许可证扫描与 Cosign keyless 签名；server 覆盖镜像只阻断相对官方基础镜像新增的漏洞，并记录继承例外；
- 日期快照只记录当日首次发布；同日后续修订使用 `data-YYYY-MM-DD-sha-<短提交>`，避免覆盖不可变历史或让日期快照与 auto-release 的语义失真；
- 版本化 Release 同时给数据镜像与 Immich 覆盖镜像追加项目语义化版本标签；
- 项目定位改为独立实现，移除“重写”和上游横向比较；新增 ADR，明确 Immich 外部读取契约与项目内部模型的边界；
- 发布制品与镜像语言目录现在保留 i18n-iso-countries 的上游 MIT `LICENSE`，避免再分发时遗漏版权声明；
- 新增 `no-change` 与 `notify-failure` 作业：无变化时明确记录并跳过发布，失败时自动创建/更新带 `automation` 标签的 issue；
- 新增日期快照保留策略（当时默认保留最近 14 个），自动清理过期快照；后续默认值已调整为 3。

## [1.0.0] - 2026-10-06

### 新增

- 独立的 MIT 许可实现，支持无需 API Key 的默认离线中文地名构建；
- 从 GeoNames `ADM3`/`ADM4` 自建区县、乡镇层级表；
- 可选 provider：高德、Nominatim，均带限速与磁盘缓存；
- 7 种展示粒度 × full/非 full 共 14 个数据制品；
- `immich-cn-manifest-json-v1.json` 记录上游 SHA256、统计数据；
- 发布前自动校验（文件齐全、去重、中文覆盖率）；
- GHCR 数据镜像与开箱即用的 Immich 覆盖镜像，支持运行时切换展示粒度；
- GitHub Actions：CI、自动更新、版本化发布；
- 中文文档：架构、数据源、部署、开发、许可、FAQ。
