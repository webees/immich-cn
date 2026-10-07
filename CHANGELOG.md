# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 变更（含破坏性）

- 文档改为**中文为主**：只有产品名、协议缩写与标识符保留英文，其余技术概念统一使用中文写法（发布、制品、清单、校验和、覆盖率、快照、缓存、指纹、镜像、摘要、标签、展示粒度等），并把术语表从「技术概念用英文」改成「英文 ↔ 中文对照」；
- 合并重叠文档：`project-scope.md` + `china-localization.md` + `china-acceleration.md` → `docs/china.md`；`terminology.md` + `naming-conventions.md` + `documentation-policy.md` → `docs/conventions.md`。文档数从 21 篇降到 16 篇，护栏锚点同步更新；
- 继续合并：`artifact-spec.md` → `docs/data-format.md`（数据格式与制品命名合为一篇）、`faq.md` + `maintenance.md` → `docs/operations.md`（运维与常见问题）；`docs/*.md` 降到 12 篇，README + docs 总行数降到约 1,640；
- 排版统一：README 只保留代码许可、构建入口、外部依赖、行政区粒度、发布方式五个维度；文档二级标题统一为 4 字左右，并列的「方式一 ~ 方式五」标题统一为 8 字；
- 继续中文化剩余文档：`architecture`、`deployment`、`data-sources`、`development`、`licensing`、`timezone`、`operations` 的散文英文（Release/digest/mirror/fallback/dump/full/provider/asset/timezone/container 等）改为中文，标题改为「架构设计」「部署」「数据来源与处理」「许可与署名」等；
- **制品命名升到 v4**：发布资产改为 canonical-only，不再生成历史别名。`immich-cn-geodata-<profile>-<scope>-v1.zip` 取代 `geodata_admin_2.zip`、`geodata_admin_2_full.zip` 等旧名，也取代过渡期的 `immich-cn-geodata-immich-*`；其他资产统一为 `immich-cn-dataset-sqlite-v1.zip`、`immich-cn-patterns-tsv-v1.gz`、`immich-cn-i18n-json-v1.zip`、`immich-cn-manifest-json-v1.json`、`immich-cn-checksums-sha256-v1.txt`。manifest 的 `artifactSpecVersion` 为 `4`，固定引用旧文件名的使用者需要迁移；
- 内部模块按职责重命名（`config.py` → `settings.py`、`build.py` → `pipeline.py`、`verify.py` → `validation.py` 等），命名规范见 `docs/naming-conventions.md`；
- manifest 的 `stats` 明确为规范层 full 口径，并新增 `droppedCities` / `droppedExtra` 分段记录丢弃原因；`docs/artifact-spec.md` 说明该口径与变体行数的差异；
- 滚动 Release `auto-release` 现在会按本次构建的 `dist` 清单回收不再发布的资产（此前 `upload --clobber` 只增不删，导致 21 个 pre-v4 资产长期残留）。

### 新增

- 新增 `scripts/check_dead_symbols.py` 与 `make audit-dead-symbols`：扫描 `src/` 与 `scripts/` 的模块级定义是否有零引用（`__dunder__` 忽略，外部入口写进 `ALLOWED` 并注明原因），把此前每轮手写的死代码扫描固化成可重复执行的资产；2026-10-07 基线 501 个定义、1 个零引用项（已删除），复查为 0；
- 文档护栏新增 README 维度表、英文标题、Markdown 表格结构与文档索引唯一性检查，防止排版再次漂移；
- 文档散文语言护栏新增通用英文词检查：发布、镜像、制品、清单、摘要、工作流、校验、覆盖率、指纹、快照、提供方、回退、展示粒度、来源、数据集、适配器等必须使用中文，只有代码标识符、协议缩写与专有名词保留英文；
- 新增 `scripts/check_action_pins.py` 与 `make audit-pins`：把每个 Action pin 与注释里的版本 tag 对拍（缺 40 位 SHA、缺版本注释、tag 不存在、tag 指向的 commit 与 pin 不一致都失败）；`check_workflows` 只做离线格式校验，发现不了「pin 停在旧版本但注释写着新版本」这类漂移。实测 6 个工作流 25 个固定引用全部与上游 tag 一致；
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

- 完整 Immich 服务栈冒烟在拉取 PostgreSQL、Valkey 与覆盖镜像时增加 5 次退避重试，避免单次镜像仓库限流把自动更新误判为失败；
- 容器入口在源数据目录与目标目录相同时明确跳过复制，不再误报“目标不可写”；
- `cleanup.py` 新增 `--prune-legacy-assets`：仅当仓库中已有规范 v4 替代品时回收旧命名 Release 资产，缺少替代品的历史发布保持不动；
- 更新 `actions/upload-artifact` 与 `actions/download-artifact` 的固定提交，使 25 个 Action 引用重新与上游版本标签一致；
- CI 的 Python 作业现在自动执行 Action 固定提交校验，不再只依赖人工运行 `make audit-pins`；
- CI 的 Python 作业同时执行死代码扫描，新增零引用模块级定义会在提交阶段被拦住；
- 增加过期/无效 GitHub 令牌的负向测试，确认 401 会立即失败而不是被重试掩盖；
- 完整服务栈冒烟同时识别 Immich 新旧地图配置字段（`map.lightStyle` / `mapLightStyleUrl` 等），修复当前 release 因契约升级导致的误失败；
- `cleanup.yml` 的旧命名资产清理支持仓库变量 `PRUNE_LEGACY_ASSETS=true` 开启定时自动模式，默认保持关闭；
- CI 的 Docker 冒烟作业会从 `audit` 分支读取审计账本并校验汇总值可由轮次明细复算；
- 数据镜像落地目录里的 `README.md` 补齐 i18n 挂载说明：此前只写「Immich < 1.136 的 `node_modules/i18n-iso-countries`」，1.136.0 ~ 3.2.x 的用户会照它把覆盖包放到错误位置；现在同时给出 `/usr/src/app/node_modules/...`、`/usr/src/app/server/node_modules/...` 与「3.3.0 起不再需要」，`check_docs.check_langs_mounts` 会强制这两个路径都保留；
- `check_artifacts` 现在校验 i18n 语言包的裁剪契约：`immich-cn-i18n-json-v1.zip` 必须且只能含 `LICENSE` 与 `langs/en.json`，出现其它 `langs/*.json` 或缺 `langs/en.json` 都失败（此前只检查 LICENSE 文本，裁剪是否生效无人把关）；同时把 README / docs/packages / docs/data-sources 的措辞限定为「自下一次数据发布起」——2026-10-07 实测已发布的 `data-2026-10-06` 与 `auto-release` 仍是 74 个成员、191,847 字节的整套语言包（sha256 与各自 manifest 一致），文档此前把未发布的行为写成了既成事实；
- `--provider auto` 在缺少 `AMAP_API_KEY` 时不再静默降级：新增显式 warning（产物与 `--provider offline` 完全相同，manifest 里 `config.provider` 记为 `offline`），避免「密钥缺失 / 改名 / secret 过期」伪装成一次成功的高德增强构建；`--provider amap` 仍然是硬要求，缺 Key 直接 `ConfigError`；`docs/development.md` 记录该行为；
- README 的展示粒度表补齐默认发布的 7 种 pattern（此前只有 5 种，`{admin_2} {admin_4}` 与 `{admin_3} {admin_4}` 对应的 `immich-cn-geodata-admin2-admin4-*.zip` / `admin3-admin4-*.zip` 已在 Release 里发布却无文档入口）；`check_docs` 新增 `check_pattern_table`，要求表格覆盖实现里的 `DEFAULT_PATTERNS`；
- 补上「固定摘要变化后不得复用旧缓存」的负向控制（`test_fetcher_ignores_cache_when_pinned_digest_changed`）：去掉缓存命中时的 `spec.expected_sha256` 比对后该测试会失败，证明 CI 里很宽的 `actions/cache` `restore-keys` 兜底不会让构建拿着旧内容成功；`docs/data-sources.md` 记录这条兜底为什么安全；
- `check_workflows` 新增 GHCR 包名护栏：发布路径里自有的 `ghcr.io/${GITHUB_REPOSITORY}` 只允许 `-server` 后缀，写死的引用只允许 `webees/immich-cn` 与 `webees/immich-cn-server`；此前把 `_build-data.yml` 里 18 处包名改成 `-typo` 仍能通过全部门禁与冒烟构建（冒烟只使用本地镜像名），错误包名只会在真实发布时暴露或静默发布到另一个包；
- `check_artifacts.py` 新增规范数据集与 Immich 适配器的 admin 层级一致性比对：`admin_areas` 与 `admin1CodesASCII.txt`/`admin2Codes.txt` 出现未记录差异即失败，HK/MO 的 level-1 特别行政区覆盖（2026-10-06 发布实测 26 条：HK 18 + MO 8）是唯一允许的例外，覆盖被静默去掉也会失败；`docs/data-format.md` 记录该已知差异；
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

- 删除 `check_shell.py` 里零引用的 `SHELL_SUFFIXES` 常量：文件发现用的是 `Path("docker").glob("*.sh") + Path("scripts").glob("*.sh")`，该常量从未参与判断（2026-10-07 全量扫描 501 个模块级定义，这是唯一的零外部引用项）；
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
