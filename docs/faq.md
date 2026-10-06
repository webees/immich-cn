# 常见问题

## 数据没有生效，日志里没有 `geodata records imported`

Immich 只在 `geodata-date.txt` 与上次导入时记录的值**不同**时才重新导入——上游代码（`server/src/repositories/map.repository.ts`）是「相等就 return」，因此换成更新或更旧的不同值都会触发导入：

```bash
date -u +"%Y-%m-%dT%H:%M:%S+00:00" > ./geodata/geodata-date.txt
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

## 为什么镜像里的数据比 Release zip 大？

镜像内置的是默认非 full 数据集，点位口径与 `immich-cn-geodata-admin2-default-v1.zip` 一致；镜像还附带未压缩的 geodata 文件和用于运行时切换粒度的 `immich-cn-patterns-tsv-v1.gz`，因此不能直接与只下载一个 zip 的体积比较。需要 full 点位时请下载 `immich-cn-geodata-admin2-full-v1.zip`。

## 构建耗时多久？

GitHub Actions 上一次完整构建（7 种粒度 × full/非 full）通常在 8~25 分钟。实测各阶段开销：首次下载上游压缩包约 260 MiB，解析 `alternateNamesV2.txt`（749 MiB 文本）约 10 秒，打包 14 个变体（名称组合 + zip 压缩）约 1.5 分钟；开启 `--revalidate` 后日常运行只下载发生变化的数据源，其余返回 304。

## 数据多久更新一次？

按设计每天检查一次。`全自动更新数据` 工作流在 UTC 05:23（北京时间 13:23）自动运行，实际执行取决于仓库权限与上游服务可用性：

1. 用 ETag/Last-Modified 条件校验上游，未变化时不下载正文；
2. 计算「上游文件摘要 + 构建配置 + 发布器修订」的发布指纹并与上次发布对比；
3. 有变化才重新构建、发布 Release 并推送镜像；无变化则跳过发布。

所以数据的新鲜度是「每天检查、随变随发」，你只需要定期拉取镜像或 Release 文件。也可以在 Actions 页面手动触发一次（勾选 `force-publish` 可强制重新发布）。

## 可以只用某一个国家吗？

可以，通过 `--extra-countries CN,HK` 控制需要附带国家全量 dump 的地区。全球 `cities500` 记录都会进入构建流程；非中国地区的显示质量取决于 GeoNames 中文名称覆盖和 Immich 导入结果。
