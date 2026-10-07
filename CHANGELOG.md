# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 变更（含破坏性）

- **制品命名升到 v4**：发布资产改为 canonical-only，不再生成历史别名。`immich-cn-geodata-<profile>-<scope>-v1.zip` 取代 `geodata_admin_2.zip`、`geodata_admin_2_full.zip` 等旧名，也取代过渡期的 `immich-cn-geodata-immich-*`；其他资产统一为 `immich-cn-dataset-sqlite-v1.zip`、`immich-cn-patterns-tsv-v1.gz`、`immich-cn-i18n-json-v1.zip`、`immich-cn-manifest-json-v1.json`、`immich-cn-checksums-sha256-v1.txt`。manifest 的 `artifactSpecVersion` 为 `4`，固定引用旧文件名的使用者需要迁移；
- 内部模块按职责重命名（`config.py` → `settings.py`、`build.py` → `pipeline.py`、`verify.py` → `validation.py` 等），命名规范见 `docs/naming-conventions.md`；
- manifest 的 `stats` 明确为规范层 full 口径，并新增 `droppedCities` / `droppedExtra` 分段记录丢弃原因；`docs/artifact-spec.md` 说明该口径与变体行数的差异；
- 滚动 Release `auto-release` 现在会按本次构建的 `dist` 清单回收不再发布的资产（此前 `upload --clobber` 只增不删，导致 21 个 pre-v4 资产长期残留）。

### 新增

- 新增 `monitor-update.yml` 与 `scripts/check_update_freshness.py`：每 6 小时检查 **Auto Data Update** 的新鲜度，区分 `never_run` / `no_run` / `stalled` / `failed` / `stale_success` / `schedule_stalled` / `ok`，并把「手动 dispatch 成功」与「schedule 仍在触发」分开判定，停摆时创建 `automation` 告警、恢复后自动关闭；
- 项目定位收敛为“为 Immich 提供中国本地化的 reverse geocoding geodata”；新增 `docs/project-scope.md` 统一 core scope、optional support 与 non-goals，`docs/china-localization.md` 只记录实际证据、缺口和 roadmap；
- 新增 `docs/china-acceleration.md`、`examples/compose.acceleration.yml` 与 `examples/nginx/immich-cn.conf`：明确 CDN、HTML/API/照片/视频缓存边界，并提供可校验的 Nginx 静态资源缓存源站；
- 增加 jsDelivr 免费 CDN 可选说明：仅服务 GitHub 分支、tag 或提交中的静态文件，实测不能代理 GitHub Release 附件；中国线路质量需按地区、运营商和时段自行验证；
- 缩小 Docker 镜像与语言包：数据镜像移除不必要的 `gzip` 包和多条 `RUN` 层，`immich-cn-i18n-json-v1.zip` 只发布旧版 Immich 实际读取的 `en.json` 与上游 `LICENSE`，不再复制整个 i18n 语言包；
- CI 增加合成构建镜像 10 MiB 尺寸预算与语言包最小化检查；实测数据镜像本地显示由约 16.1 MB 降到约 14.5 MB（合成数据，具体值随基础镜像和数据变化）；
- 项目生成的 Release 日期、构建时间、`geodata-date.txt` 和作业摘要统一使用北京时间 `Asia/Shanghai (+08:00)`；GitHub 页面自身的时间仍由 GitHub 与浏览器时区决定；
- README 的更新 badge 改为英文 `Data Update`，新增 `docs/terminology.md`，明确技术术语优先使用英文、中文只用于用户目标、风险和操作说明；
- 新增 `scripts/set_asset_timezone.py` 与 `docs/timezone.md`：通过 Immich bulk asset API 将所有 asset 的 EXIF `timeZone` 设置为 `Asia/Shanghai`，默认 dry-run、需显式 `--apply`；日志和 Release 时间仍与照片 EXIF 显示时区分离；
- 新增 `scripts/jsdelivr_url.py`：jsDelivr URL 默认使用中国加速候选 `cdn.jsdmirror.com`，支持 `IMMICH_CN_JSDELIVR_BASE` 用户配置；文档记录多节点探测结果，并明确第三方 mirror 的信任与 SHA256 校验边界；
- `Auto Data Update` 在清理 `auto-release` 后新增 `--verify-release-assets` reconciliation：Release 资产与本次 `dist` 缺一或多一都会让 workflow 失败，避免旧资产静默残留；
- full-stack release smoke 增加 PostgreSQL `geodata_places`/`naturalearth_countries` 行数、苏州样本和 `/api/server/config` 检查，验证 geodata 不只是“日志导入成功”，而是真的可查询且 API 可启动；
- server image 构建前解析 Immich base tag digest，并使用 `tag@digest` 固定本次构建，同时写入 OCI base digest label；Trivy 差集扫描复用同一 digest，避免构建与扫描之间的 tag 漂移；
- Immich base digest 纳入 Auto Data Update 的 change detection：即使 geodata fingerprint 不变，base image 更新也会触发 server image 重建；
- Cosign 发布流程在签名后增加 `cosign verify`，对数据镜像和 server image 的最终 digest 验证 OIDC 签名可被独立读取；
- cleanup 保护 `sha256-*` / `sha256:*` digest-like GHCR tag，并在单个删除失败后继续清理其他 release/run/package，最后统一汇总失败，避免一次 HTTP 500 中断全部维护；
- 自动清理新增失败告警与恢复收敛：失败时创建或更新带 `automation` 标签的 issue，成功时评论并关闭历史告警；所有自动化 issue 标题搜索由静态护栏强制限定标签范围；
- 修正容器入口脚本对 Immich geodata 重新导入条件的过时注释，并把 `docker/*.sh` 纳入同一上游契约措辞护栏，避免容器维护说明与文档再次漂移；
- 统一 Immich TSV 字段说明为明确的 0-based column 口径，修正 `admin1CodesASCII.txt` / `admin2Codes.txt` 的 key/name 位置描述，并增加文档护栏；
- `set_asset_timezone.py` 改用 Immich v3.3.0 推荐的 `PATCH /api/assets`，仅在 `404`/`405` 时回退旧版 `PUT`，避免继续依赖已标记 deprecated 的 bulk update 方法；
- 校正 UI locale 契约：Immich v3.3.0 已内置 `zh_Hans` / `zh_Hant`，用户可在 User Settings 选择；项目不再把 UI translation 写成需要上游修改，并记录浏览器 locale 别名映射；
- Nginx 加速示例补齐 Immich reverse proxy 契约：上传旁路缓冲、50 GB body 上限、600 秒 WebSocket/传输超时；静态资源的 `Cache-Control` 不再用 `always` 污染 404/500 响应；
- Compose 示例对齐 Immich v3.3 官方拓扑：媒体卷改为 `/data`，补齐 machine-learning 与 model-cache，Valkey 升级并固定到官方 9.x digest；发布 smoke 同步使用同一 Valkey 摘要；
- 修正 timezone 文档残留的无条件 `PUT /api/assets` 描述，明确 PATCH 优先与 404/405 fallback，并增加文档-实现契约护栏；
- 滚动 Release 的旧资产 prune 现在遇到单个删除失败会继续处理其余资产，并在结束时统一汇总失败，避免一次瞬时 API 错误导致后续旧资产长期残留；
- 明确 Immich 当前 `release` 线 v3.2.4 与 v3.3.0 均已内置中文 UI locale，避免默认镜像用户误以为必须升级才能获得 `zh_Hans` / `zh_Hant`；
- Compose 示例与发布 smoke 的 Valkey digest 对齐当前 Immich release 线 v3.2.4 官方 compose；媒体目录 `/data` 的版本说明同步覆盖 v3.2.4 与 v3.3.0；
- 统一 `CONTRIBUTING.md` 与开发文档对 `make check` 的描述，明确包含 lint、typecheck、test、docs、workflows 与 shellcheck，并增加文档契约护栏；
- Auto Data Update 的 change detection 增加 data image `latest` digest 存在性检查，避免 data image 曾推送失败时因 fingerprint 未变而跳过重建并错误关闭告警；
- Auto Data Update 还会比较 `auto-release` 资产与本次 `dist` 清单；缺失、多余或 legacy 资产会强制重新发布并由 reconciliation 回收，避免 Release 不完整时错误进入 no-change；
- 版本化 Release 强制要求 `push-images=true`；拒绝创建没有对应 `immich-cn` / `immich-cn-server` semantic version tag 的 GitHub Release；
- 强化版本发布护栏：不仅检查错误文案，还要求真实存在 `push-images != true` 拒绝条件，防止恒假条件造成假通过；
- 版本化发布在创建 GitHub Release 前验证两个 `image:VERSION` tag 已存在，避免构建后追加版本标签被跳过时留下无镜像 Release；
- `prune-all` 现在真正忽略时间窗口，只保留每个 workflow 最新一次运行、当前运行与语义版本 Release 对应提交，和“稳定前激进清理”文档一致；
- Auto Data Update change detection 新增最新 `data-*` 不可变快照的 manifest fingerprint 校验；快照缺失或与当前内容不一致时会强制进入发布修复，避免快照创建失败后被 no-change 错误跳过；
- 版本化 Release 在创建 GitHub Release 前对两个 `image:VERSION` tag 的 registry digest 与本次 build 输出做比对，防止 tag 指向非本次构建镜像；
- 制品校验要求 checksum 清单完整覆盖 manifest assets，并拒绝重复或未登记条目，避免漏校验某个发布资产仍整体通过；
- manifest 校验要求全部 canonical artifacts 同时出现在 assets 清单中，避免变体只在 artifacts 中登记却绕过 assets/checksum 覆盖；
- 清理 `actionlint`/ShellCheck 告警：归档索引改用 `find`、合并 GITHUB_OUTPUT 重定向，并修正自动化 issue 正文中的字面反引号表达式；
- CI 新增固定 digest 的 `rhysd/actionlint` 校验，防止 workflow 语法与 shell 质量问题回归，并由工作流静态护栏强制保留；
- Immich integration contract 补充上游 import filter：`PPLX`（非 `AU`）与 `PPLH` 记录在导入阶段被丢弃，并记录 `reverseGeocodeMaxDistance` 与当前实测的跳过行数，避免把制品行数误读成 Immich 实际导入行数；
- full-stack smoke 的地点检索断言改为直接执行 Immich `searchPlaces` 的 `%>>` 谓词并对 `苏州市`、`苏州`、`Suzhou`、`蘇州`、`昆山` 断言命中，取代与上游召回不等价的 `name LIKE '苏州市%'`；`check_workflows` 增加对应护栏与负向用例，`docs/immich-integration.md` 记录该搜索契约；
- 校验器补齐 Immich `geodata_places` 列契约：`cities500-immich-columns` 拦截超过 `varchar(200)` 的展示名、非两字符 `countryCode`、超长 admin1/admin2 code，`cities500-modification-date` 拦截不可解析的 `date` 值；`natural-earth` 校验从「能解析」提升为「`properties.ADMIN` / `ADM0_A3` / `TYPE` 与面几何齐全」，避免 country fallback 在 import 阶段才失败；
- 文档护栏新增 CHANGELOG 重复 bullet 检查，并把 CHANGELOG 纳入中文软换行扫描；
- 部署示例默认设置 `TZ: Asia/Shanghai`，并补充国内镜像获取、digest 验证、WGS-84/GCJ-02 偏移与故障排查说明；
- 规范 SQLite 数据集 `immich-cn-dataset-sqlite-v1.zip` 作为一等制品，Immich 文本格式改由适配器导出，详见 `docs/data-format.md` 与 ADR 0001；
- `immich-cn artifact resolve` CLI：按 canonical ID、profile+scope 或历史别名解析制品；
- 自动清理工作流 `cleanup.yml`：按保留策略清理 `data-*` 快照、Actions 运行与 GHCR 版本，并保护语义版本、`auto-release`、`latest`/`release` 标签与 untagged 子 manifest；
- 发布流水线新增完整 Immich 服务栈 smoke（PostgreSQL + Valkey + Immich，等待 `Geodata import completed`）与发布后自检文档承诺的固定下载地址；
- 打包期中文地名校验：CN/HK/TW/MO 的记录若展示名不含中文直接失败，并给出样例，避免英文/葡文地名进入制品；
- 文档与实现的一致性护栏：资产名、上游数据源清单、命名规范表、环境变量默认值、manifest 顶层字段、stats 口径、Markdown 链接、中文软换行、Immich 版本分界、required check 名、`hashFiles` 路径、checkout 凭据等。

### 修复

- 清理脚本的 dry-run 现在会先打印真实读到的对象数量（Release / Actions 运行 / 每个 GHCR 包的版本数），并在某个 GHCR 包返回 0 个版本时直接失败：此前只打印「待删除 0」无法区分「没有可删项」与「token 缺 read:packages 或 API 结构变化导致读到空列表」；确认包尚未创建时用 `--allow-empty-packages` 显式放行；
- README 与 FAQ 明确 GitHub `schedule` 可能延迟甚至整轮跳过（2026-10-06/07 实测只有一次 `schedule` 运行），把「每天更新」限定为设计频率并指向 `monitor-update.yml` 的告警路径与 30 小时容忍窗口；`check_discoverable` 扩展到 `.github/workflows/*.yml`，新增工作流未在文档中被点名即失败；
- 新增 `scripts/check_audit_ledger.py` 与 `make audit-ledger`：审计账本的汇总值必须能按轮次从 `history` 复算，并校验 `round` 唯一递增、verdict/severity 匹配与 `consecutive_clean` 正确；据此修正账本两类真实漂移（`totals` 与明细脱钩、三轮带 P3 却标 clean），旧值保留在 `totalsSuperseded`、改判理由写入条目；
- `docs/packages.md` 明确镜像 tag 不带 `v` 前缀（Git Release 是 `vX.Y.Z`，镜像 tag 是 `X.Y.Z`，2026-10-07 实测带前缀返回 `not found`），补上可直接复制的拉取示例，并解释 Packages 页面上 `sha256-<digest>` 是 Cosign/attestation 的 OCI referrer tag 而非发布镜像；新增 `check_image_tag_examples` 护栏拒绝不符合发布契约的 tag 示例；
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
