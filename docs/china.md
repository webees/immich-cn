# 中国本地化与加速

本文是项目范围、本地化现状与加速边界的唯一出处。数据格式与制品命名见 [数据格式与制品命名](data-format.md)，部署细节见 [部署指南](deployment.md)。

## 规范定位

`immich-cn` 为 Immich 提供中国本地化的反向地理编码地理数据。它不复刻 Immich，也不把界面、地图、CDN 或容器运行时全部纳入本地化范围。

## 核心范围

- 中文地名、四级行政区层级与逐级回退；
- 中文、拼音、英文与繁体的可检索别名；
- 规范 SQLite 数据集与 Immich 地理数据适配输出；
- 自动数据更新工作流；
- GitHub 发布与多架构容器镜像；
- 来源哈希、制品哈希、覆盖率、校验、来源证明与保留策略。

核心能力必须通过发布校验；单项覆盖率不足时，文档必须写出缺口，不能把路线图写成已完成事实。

## 可选支持

- 地图样式、WGS-84/GCJ-02 说明与同源瓦片代理；
- EXIF `timeZone` 批量设置工具；
- CDN 与缓存策略、Nginx 回源示例、jsDelivr 端点配置；
- 国内部署、镜像源、时区与故障排查说明。

可选能力可以独立升级、替换或禁用，不应改变核心地理数据输出契约。

## 排除范围

- 不维护 Immich 界面翻译分支；
- 不托管公共 CDN、地图瓦片服务或对象存储；
- 不缓存私有照片、缩略图、视频流或认证 API；
- 不承诺第三方镜像源的中国大陆线路质量或可用性；
- 不以路线图代替校验证据。

## 本地边界

- 本项目不维护 Immich 核心分支；Immich 文本目录与文件格式属于消费端适配层，规范数据模型仍以本项目的 SQLite 数据集为准；
- 默认输出简体中文；繁体可通过 `--chinese-variant hant` 生成，地区用字以数据源与覆盖表为准；
- 中国地图瓦片与 GCJ-02 坐标转换不修改 Immich 核心，本项目只说明影响并给出可选部署方案；
- 数据质量结论必须能由已发布制品、清单或独立复算复核，不能只靠项目介绍中的断言。

## 现状缺口

| 领域 | 类型 | 目标 | 证据与缺口 |
|:--|:--|:--|:--|
| 显示 | 核心 | 中文地名并按省/市/区县/乡镇逐级回退 | CN/HK/TW/MO 打包期零缺失；`{admin_3}`/`{admin_4}` 只改变能解析到区县/乡镇的记录，离线数据大多止于市级，具体差异以对应变体为准 |
| 检索 | 核心 | 中文、拼音、英文与繁体均可检索 | 苏州市可命中 `Suzhou`、`Suzhou Shi`、`su zhou`、`蘇州`；质量取决于 GeoNames `alternateNamesV2` 覆盖率，项目未逐地名生成拼音 |
| 地图 | 可选 | 可配置底图、坐标一致、来源可追溯 | Immich 支持浅色/深色地图样式，项目说明 WGS-84 与 GCJ-02 差异；上游默认依赖 `tiles.immich.cloud`，自定义域名还受 CSP 限制 |
| 体验 | 可选 | 时区、刷新与排障路径一致 | Immich v3.2.4 与 v3.3.0 内置 `zh_Hans`/`zh_Hant`，示例 Compose 默认 `TZ: Asia/Shanghai`；界面本体来自上游 |
| 加速 | 可选 | 面向中国网络的 CDN 与静态资源缓存 | Immich 已对 `/_app/immutable` 设置一年不可变缓存，项目提供 Nginx 回源与 CDN 接入边界；不提供公共节点 |
| 数据 | 核心 | 四级行政区可追溯、可量化、可复核 | 快照、来源 SHA256、覆盖率与制品摘要进入清单；GeoNames CN 数据转储包含 `ADM3`/`ADM4` 要素，能否进入四级回退取决于当前记录中的 `admin3`/`admin4` 代码与匹配策略，发布校验以清单统计为准 |

表中覆盖率与数据质量结论以当前发布清单和校验结果为准；上游为滚动数据，重新发布后应重新测量。项目生成的发布日期、作业摘要、清单里的 `generatedAt` 与 `geodata-date.txt` 使用北京时间 `+08:00`。

## 演进路线

- **阶段 1（已完成）**：中文展示名与逐级回退、别名检索、展示粒度切换、每日自动检查与发布；
- **阶段 2（进行中）**：默认时区、坐标系差异说明、自定义地图样式与 CSP 边界、部署与回滚文档；
- **阶段 3（进行中）**：CDN 源站接入规范、Nginx 缓存策略、静态资源与地图服务的校验边界；
- **阶段 4（待办）**：行政区划补全，先确认数据来源与许可、匹配策略、覆盖标准与负向控制，条件满足前不宣称“全国四级行政区已完整”。

## 加速边界

```text
浏览器 / 移动端 → 国内 CDN 或 WAF（可选）→ Nginx 源站（示例）
    /_app/immutable/*  长缓存，可进入共享缓存
    /api/*、照片、视频  默认不缓存
```

可复制示例：[examples/compose.acceleration.yml](../examples/compose.acceleration.yml) 与 [examples/nginx/immich-cn.conf](../examples/nginx/immich-cn.conf)。示例只提供 Nginx 源站，不绑定任何 CDN 供应商。

| 请求类型 | 缓存策略 |
|:--|:--|
| `/_app/immutable/*` | `Cache-Control: public, max-age=31536000, immutable`，可缓存到 CDN |
| 其他前端静态资源 | 保留上游 `Cache-Control`，先观察再按实测调整 |
| HTML 与 SPA 入口 | 不进入共享缓存，保留上游 `no-store` 或只做短时私有缓存 |
| `/api/*` | 默认不缓存，不忽略 Cookie、Authorization 与 `Set-Cookie` |
| 缩略图、原图、视频流 | 默认不进入公共 CDN |
| 发布数据与镜像 | 按内容摘要或镜像摘要校验后使用 |
| 地图样式与瓦片 | 仅在自有或明确授权的服务上开启缓存 |

配置要点：回源遵循响应头，CDN 不自行把 HTML 或 API 变成公共缓存；缓存键包含 Host、路径与必要查询参数；只对 `/_app/immutable/*` 开启长缓存；对 `/api/*`、上传、WebSocket 与认证端点禁用共享缓存；启用 HTTP/2 或 HTTP/3 前先确认客户端兼容；保留命中率、回源率、5xx 与首字节时间等可观测性；源站只对 CDN 开放。

Nginx 示例按 Immich 上游建议设置 `proxy_request_buffering off`、`client_body_buffer_size 1024k`、`client_max_body_size 50000M` 与 600 秒超时，且只对成功响应追加 `Cache-Control`。上述规则是部署参考，不同 CDN 对 Cookie 旁路、HTTP/3 与大陆节点的配置不同，必须按实际产品验证。

## 加速通道

jsDelivr 只作为 GitHub 分支、标签或提交中静态文件的**可选**通道，适合 README、文档与小型配置；它不是数据发布依赖，也不承诺中国大陆线路质量。项目提供的 [jsdelivr_url.py](../scripts/jsdelivr_url.py) 默认使用 `cdn.jsdmirror.com`，可用 `--base` 或 `IMMICH_CN_JSDELIVR_BASE` 替换。

2026-10-07 实测：`cdn.jsdmirror.com`、`cdn.jsdmirror.cn`、`jsd.onmicrosoft.cn`、`cdn.jsdelivr.net`、`gcore.jsdelivr.net`、`fastly.jsdelivr.net` 对主分支的 README 文件返回 `200`；`cdn.jsdelivr.us` 返回 `302`；`jsd.cdn.zzko.cn` 证书已过期，不纳入默认回退；`test.jsdelivr.us` 未验证。分支与提交路径缓存时间较短，生产引用应固定到提交 SHA 或语义化标签。

**jsDelivr 不能代理 GitHub 发布资产**：`immich-cn-geodata-admin2-default-v1.zip` 与 `immich-cn-manifest-json-v1.json` 通过 jsDelivr 请求均返回 `404`，因此发布资产不能写成 jsDelivr 地址。第三方镜像源不是可信回源，必须使用 HTTPS、固定到提交 SHA，并在下载后用 SHA256 校验。

地图方面：Immich 默认地图样式指向 `tiles.immich.cloud`，自定义底图需同时处理服务条款与 `IMMICH_HELMET_FILE` 的 CSP 白名单，否则浏览器会拦截瓦片请求；推荐把自有地图服务放在同源路径（例如由 Nginx 代理到 `/maps/`）。不要把第三方瓦片复制到本项目 CDN 后公开再分发。

## 验证方法

```bash
curl -sSI https://immich.example.com/_app/immutable/example.js   # 应看到 long max-age 与 immutable
curl -sSI https://immich.example.com/api/server/config           # 不应被共享缓存
curl -sSI https://immich.example.com/                            # 不应被共享缓存
```

如果 API 或 HTML 返回公共长缓存，应先停止 CDN 规则并回滚，而不是继续扩大缓存范围。静态资源命中率提升不能以绕过认证或泄露照片为代价。
