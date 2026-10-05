# 常见问题

## 数据没有生效，日志里没有 `geodata records imported`

Immich 只在 `geodata-date.txt` 比上次导入时间更新时才重新导入：

```bash
date -u +"%Y-%m-%dT%H:%M:%S+00:00" > ./geodata/geodata-date.txt
```

或在使用镜像时设置 `IMMICH_CN_FORCE_RELOAD=1`。

## 地点显示的还是英文

按以下顺序排查：

1. `cities500.txt` 第 1 列是否已经是中文（`head -n 1 cities500.txt`）；
2. Immich 是否真的导入了新数据（重启并观察日志）；
3. 是否执行过「提取元数据 → 全部」；
4. Immich 版本是否低于 1.136.0 而漏掉了 `i18n-iso-countries` 挂载。

## 边界位置识别不准

Immich 使用"最近的点"做反向地理编码，边界处的误差是原理性的。可以：

- 换用 `geodata_full.zip`（点位更多，通常更准，导入更慢）；
- 到 [GeoNames](https://www.geonames.org/) 补充缺失地点，下次构建会自动收录。

## 地名粒度太粗/太细

用 `IMMICH_CN_PATTERN` 或下载对应粒度的 zip：

| 想要的结果 | 建议 |
|:--|:--|
| 只到城市 | `{admin_2}` |
| 城市 + 区县 | `{admin_2} {admin_3}` |
| 到乡镇 | `{admin_2} {admin_3} {admin_4}` |

## 为什么默认不启用高德？

高德 API Key 属于个人账号，且其服务条款对结果再分发有限制。默认使用 GeoNames 离线层级表，
可以做到零密钥、可完全自动、可自由再分发。配置 `AMAP_API_KEY` 后即可获得更精细的数据。

## 为什么镜像里的数据比 Release zip 大？

镜像内置的是 full 数据集（点位更多），并附带用于运行时切换粒度的 `patterns.tsv.gz`。
zip 则同时提供 full 与非 full 两种规模。

## 构建耗时多久？

GitHub Actions 上一次完整构建（7 种粒度 × full/非 full）通常在 10~25 分钟，
其中约 1/3 时间花在解析 `alternateNamesV2.txt`。

## 可以只用某一个国家吗？

可以，通过 `--extra-countries CN,HK` 控制需要附带国家全量 dump 的地区。
全球 `cities500` 始终会被处理，因此世界范围的地点仍可正确显示。
