# 常见问题

## 数据没有生效，日志里没有 `geodata records imported`

Immich 只在 `geodata-date.txt` 与上次导入时记录的值**不同**时才重新导入——上游代码（`server/src/repositories/map.repository.ts`）是「相等就 return」，因此换成更新或更旧的不同值都会触发导入：

```bash
TZ=Asia/Shanghai date +"%Y-%m-%dT%H:%M:%S+08:00" > ./geodata/geodata-date.txt
```

或在使用镜像时设置 `IMMICH_CN_FORCE_RELOAD=1`。

## 地点显示的还是英文

按以下顺序排查：

1. `cities500.txt` 第 1 列是否已经是中文（`head -n 1 cities500.txt`）；
2. Immich 是否真的导入了新数据（重启并观察日志）；
3. 是否执行过「提取元数据 → 全部」；
4. Immich 是否属于 1.136.0 ~ 3.2.x（需要 `i18n-iso-countries` 覆盖）或低于 1.136.0（路径不同）而漏掉了挂载。

## 边界位置识别不准

Immich 使用"最近的点"做反向地理编码，边界处的误差是原理性的。可以：

- 换用 `immich-cn-geodata-admin2-full-v1.zip`（点位更多，通常更准，导入更慢）；
- 到 [GeoNames](https://www.geonames.org/) 补充缺失地点，下次构建会自动收录。

## 地名粒度太粗/太细

用 `IMMICH_CN_PATTERN` 或下载对应粒度的 zip：

| 想要的结果 | 建议 |
|:--|:--|
| 只到城市 | `{admin_2}` |
| 城市 + 区县 | `{admin_2} {admin_3}` |
| 到乡镇 | `{admin_2} {admin_3} {admin_4}` |

## 为什么默认不启用高德？

高德 API Key 属于个人账号，且其服务条款可能限制结果再分发。默认使用 GeoNames 离线层级表，无需 API Key，可在满足上游数据许可的前提下自动运行和再分发。配置 `AMAP_API_KEY` 后可使用高德增强。

需要特别说明：GeoNames 的中国大陆 dump 里其实有上万个 `ADM4` 要素，但**带 `admin4` 代码的极少**（2026-10-07 实测 11,878 条里只有 73 条），而本项目靠 `CC.A1.A2.A3.A4` 代码拼层级，所以默认数据的 `{admin_4}` 通常回退到区县。若确实需要乡镇粒度，请启用高德 provider。

## 地图上点位和底图有偏移怎么办？

项目使用的 GeoNames 坐标是 WGS-84。OpenStreetMap 及其衍生底图通常也使用 WGS-84，不会产生系统性偏移；高德、腾讯等 GCJ-02 底图会有约数百米的偏移。Immich 不负责坐标转换，本项目也不在地名数据中混入 GCJ-02 坐标。请优先选择 WGS-84 底图，或在瓦片、代理或独立转换层处理坐标。细节见 [中国本地化方向](china-localization.md)。

## 国内拉取 GHCR 镜像不稳定怎么办？

可以配置你信任的 registry mirror，但必须验证它同步的是同一 digest；不要把任意镜像站当作官方来源。长期部署请固定到 `@sha256:<digest>`。数据 Release 下载后应使用 `immich-cn-checksums-sha256-v1.txt` 复核，具体命令见 [部署指南](deployment.md)。

## 可以把 Immich 放在国内 CDN 后面吗？

可以，但必须严格区分内容：`/_app/immutable/*` 可以长缓存，HTML、`/api/*`、原始照片、缩略图和视频流默认不能进入公共 CDN。项目提供 [examples/compose.acceleration.yml](../examples/compose.acceleration.yml) 和 [examples/nginx/immich-cn.conf](../examples/nginx/immich-cn.conf)，完整边界见 [中国网络与加速](china-acceleration.md)。

## 静态资源加速会不会拖慢或不安全？

`/_app/immutable/*` 的文件名带构建摘要，适合一年 immutable 缓存；HTML 和 API 不缓存，避免版本错配和登录态泄漏。命中率提升不能以缓存私有照片为代价。项目不提供公共 CDN 节点，CDN 供应商的备案、合规、节点质量和计费需自行确认。

## 地图瓦片也能加速吗？

可以在自有或明确授权的瓦片服务前增加 CDN 和 Nginx 缓存，并把地图入口代理到同源路径，例如 `/maps/`。不要直接缓存并公开再分发商业瓦片；Immich 的 CSP 也可能限制外部地图域名，需要按上游配置方式显式调整。细节见 [中国网络与加速](china-acceleration.md)。

## 项目只适合中国大陆数据吗？

不是。默认构建仍处理全球 `cities500`，但优先级和验证标准面向中国用户：CN/HK/TW/MO 有严格中文零缺失检查，中国大陆的区县、乡镇覆盖率被单独量化。海外地名能否显示中文，取决于 GeoNames 中文别名覆盖率与可选 provider；这不会阻止中国地区的名字正常显示。

## 为什么镜像里的数据比 Release zip 大？

镜像内置的是默认非 full 数据集，点位口径与 `immich-cn-geodata-admin2-default-v1.zip` 一致；镜像还附带未压缩的 geodata 文件和用于运行时切换粒度的 `immich-cn-patterns-tsv-v1.gz`，因此不能直接与只下载一个 zip 的体积比较。需要 full 点位时请下载 `immich-cn-geodata-admin2-full-v1.zip`。

## 构建耗时多久？

GitHub Actions 上一次完整构建（7 种粒度 × full/非 full）通常在 8~25 分钟。实测各阶段开销：首次下载上游压缩包约 260 MiB，解析 `alternateNamesV2.txt`（749 MiB 文本）约 10 秒，打包 14 个变体（名称组合 + zip 压缩）约 1.5 分钟；开启 `--revalidate` 后日常运行只下载发生变化的数据源，其余返回 304。

## 数据多久更新一次？

按设计每天检查一次。`全自动更新数据` 工作流在北京时间 13:23（UTC 05:23）自动运行，实际执行取决于仓库权限与上游服务可用性：

1. 用 ETag/Last-Modified 条件校验上游，未变化时不下载正文；
2. 计算「上游文件摘要 + 构建配置 + 发布器修订」的发布指纹并与上次发布对比；
3. 有变化才重新构建、发布 Release 并推送镜像；无变化则跳过发布。

所以数据的新鲜度是「每天检查、随变随发」，你只需要定期拉取镜像或 Release 文件。也可以在 Actions 页面手动触发一次（勾选 `force-publish` 可强制重新发布）。

## 可以只用某一个国家吗？

可以，通过 `--extra-countries CN,HK` 控制需要附带国家全量 dump 的地区。全球 `cities500` 记录都会进入构建流程；非中国地区的显示质量取决于 GeoNames 中文名称覆盖和 Immich 导入结果。
