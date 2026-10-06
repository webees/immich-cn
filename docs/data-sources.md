# 数据源与处理流程

## 上游数据源

| 文件 | 来源 | 许可 | 用途 |
|:--|:--|:--|:--|
| `cities500.zip` | GeoNames | CC BY 4.0 | 全球人口 > 500 的地点 |
| `admin1CodesASCII.txt` | GeoNames | CC BY 4.0 | 一级行政区代码表 |
| `admin2Codes.txt` | GeoNames | CC BY 4.0 | 二级行政区代码表 |
| `countryInfo.txt` | GeoNames | CC BY 4.0 | 国家名称与元数据 |
| `alternateNamesV2.zip` | GeoNames | CC BY 4.0 | 中文别名来源 |
| `{CC}.zip`（CN/HK/TW/MO/JP） | GeoNames | CC BY 4.0 | 国家全量 dump，用于补充点位与 `ADM3`/`ADM4` |
| `ne_10m_admin_0_countries.geojson` | Natural Earth v5.1.2 | Public Domain | 国家边界回退 |
| `i18n-iso-countries@7.0.0` | npm | MIT | 国家名称中文覆盖（旧版 Immich） |

所有版本都在 `src/immich_cn/config.py` 中固定，Natural Earth 与 i18n-iso-countries 使用不可变标签/版本号，
GeoNames 为滚动数据，其指纹会记录在每次构建的 `manifest.json` 中。

## 处理流程

### 1. 下载与缓存

`immich_cn.http.Fetcher` 负责：

- 下载到 `.cache/immich-cn/`，支持断点续传（`Range`）；
- 指数退避重试（默认 4 次，覆盖 408/425/429/5xx）；
- 把 ETag、Last-Modified、SHA256、大小写入 `.cache/immich-cn/.meta/<name>.json`，命中缓存时跳过重复下载；
- 在 `--revalidate` 模式下用 `If-None-Match` / `If-Modified-Since` 校验上游：
  GeoNames 支持强 ETag，未更新时返回 **304 且不传输正文**，更新时才重新下载；
  校验过程出错会自动回退到本地缓存，不阻断流水线；
- 解压 `cities500.zip`、`alternateNamesV2.zip`、国家 dump 与 npm tarball。

CI 中 `.cache/immich-cn` 由 `actions/cache` 缓存，配合条件校验，
每日构建通常只需传输真正发生变化的少数文件。

### 2. 确定地点集合

1. 过滤 `cities500.txt`：丢弃缺少有效一级行政区代码的噪声记录（`SG`、`VA` 除外）；
2. 扫描各国家 dump，把不在 `cities500` 中、且 GeoNames ID 与经纬度都未出现过的记录写入 `extra_all.txt`；
3. `extra_all.txt` 是 full 与非 full 的超集，非 full 打包时按人口阈值过滤；
4. 顺带从国家 dump 中抽取 `ADM3`/`ADM4` 要素，构造 `CC.A1.A2[.A3[.A4]]` 形式的行政区代码表。

> 第 4 步是本项目不依赖付费 API 也能给出区县、乡镇粒度的关键：GeoNames 只发布 admin1/admin2 的代码表，
> 但各国全量数据里带有完整的 `ADM3`/`ADM4` 记录与代码。

实际覆盖情况（2026-10 数据）：中国大陆 `ADM3`（区县）约 2,900 条，`ADM4`（乡镇）在 GeoNames 中仅 73 条，
因此**默认的 `{admin_4}` 变体在中国大陆通常会回退到区县**。如果必须精确到乡镇，请配置 `AMAP_API_KEY`
并使用 `--provider amap`；此时高德会补齐乡镇层级，其余国家/地区仍由 GeoNames 与 Nominatim 负责。

### 3. 中文名称索引

`alternateNamesV2.txt` 有上千万行，直接全量载入既慢又占内存，因此：

1. 先收集本次构建真正需要的 GeoNames ID（地点、行政区、`ADM3`/`ADM4`）；
2. 单次流式扫描 `alternateNamesV2.txt`，只保留命中的记录；
3. 按语言优先级选择名称：

   ```
   zh-Hans > zh-CN > zh-SG > zh-MY > zh > zh-Hant > zh-TW > zh-HK > zh-MO
   ```

   同一语言内优先 `isPreferredName=1`，并忽略 `isHistoric=1`；
4. 日本行政区缺少中文别名时，回退到 `ja`/`ja-*` 中可显示的汉字名称（如 `座間市`）；
   纯罗马字与 `jam` 等非日语标签不会被当作日文汉字；
5. 用 `zhconv` 统一转换为简体（可通过 `--chinese-variant hant` 输出繁体）；
6. 应用 `config/overrides.toml` 中的人工覆盖。

### 4. 人工覆盖表

`config/overrides.toml` 分为四段：

```toml
[places]      # GeoNames ID → 名称
[admins]      # 行政代码（如 CN.22、TW.04）→ 名称
[countries]   # ISO 3166-1 alpha-2 → 名称

[rules.strip_suffixes]   # 需要裁剪的行政区后缀
[rules.hk_districts]     # 香港 18 区 → 新界/九龙/香港岛
```

只有在 GeoNames 中文别名缺失或明显不符合中文习惯时才需要在此补充。

### 5. provider 增强（可选）

| provider | 触发条件 | 粒度 | 速率控制 |
|:--|:--|:--|:--|
| `offline` | 默认 | 国家/省/市/区县/乡镇（依 GeoNames 覆盖） | 无网络请求 |
| `amap` | 设置 `AMAP_API_KEY` | 高德标准的省/市/区/乡镇 | `IMMICH_CN_AMAP_QPS`（默认 3） |
| `nominatim` | `--provider nominatim` | OSM 行政层级 | 默认 1 QPS，真实 User-Agent |

高德使用 GCJ-02 坐标，调用前会用 WGS-84 → GCJ-02 转换；provider 结果按坐标写入 JSONL 缓存，
重复构建不会重复计费。

### 6. 规范数据集

构建阶段先把全部地点、国家、行政层级、中文名、来源和统计写入 `dataset.sqlite`，
再打包为 `dataset.sqlite.zip`。该 SQLite 数据库使用主键、外键、边界约束和索引，
并提供 `localized_places` 查询视图；它不依赖 Immich 的制表符列布局。完整结构见
[数据格式](data-format.md)。

### 7. Immich 适配器打包

对每个 `pattern × full` 组合：

1. 流式读取 `cities500.txt` 与 `extra_all.txt`；
2. 从 `levels.tsv` 取四级名称，按 pattern 组合成展示名，写入第 1、2 列；
3. 直接写进 zip（不在磁盘上落中间文件），zip 内目录结构为 `geodata/`，与 Immich 读取约定一致；
4. 追加 `geodata/build-info.json` 说明该变体的 pattern 与 full 状态。

最后生成 `manifest.json`、`SHA256SUMS`、`patterns.tsv.gz` 与 `i18n-iso-countries.zip`。
130 MiB 级的明文 `patterns.tsv` 默认不会生成；需要排查时可用 `--keep-raw` 同时保留明文表，
镜像构建使用直接流式生成的压缩表 `patterns.tsv.gz`。

`dataset.sqlite.zip` 自带 `NOTICE.txt`；`i18n-iso-countries.zip` 与 `build/langs/` 保留上游
`LICENSE`，避免再分发语言文件时丢失 MIT 版权声明；每个 geodata zip 和镜像数据目录同时包含
`NOTICE.txt`，保留 GeoNames 等数据源署名。
