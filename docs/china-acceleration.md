# 中国网络与加速

本文件说明 **optional support**：自托管 Immich 的接入层、静态资源分发和 cache 边界。项目不运营公共 CDN，也不承诺跨运营商、跨地区的固定延迟；这些说明不改变 [Project scope](project-scope.md) 中 reverse geocoding geodata 的 core scope。

## 推荐链路

```text
浏览器 / 移动端
        │
        ▼
国内 CDN / WAF（可选，按你的合规与账号条件配置）
        │  origin pull，遵循 Cache-Control
        ▼
Nginx 源站（示例配置）
        │
        ├─ /_app/immutable/*  长缓存，可进入共享缓存
        ├─ 其他前端资源        按上游响应头，不擅自放大
        ├─ /api/*              默认不缓存，保留认证与 Cookie
        └─ 原始照片 / 视频     默认不缓存，避免隐私泄漏
```

可复制的文件：

- [examples/compose.acceleration.yml](../examples/compose.acceleration.yml)
- [examples/nginx/immich-cn.conf](../examples/nginx/immich-cn.conf)

示例只提供 Nginx 源站，不绑定某一家 CDN。CDN 供应商、备案、内容合规、跨境链路和回源计费都需要使用者自行确认。

## 缓存边界

| 请求类型 | 缓存策略 | 依据 |
|:--|:--|:--|
| `/_app/immutable/*` | `public, max-age=31536000, immutable`，可缓存到 CDN | Immich 上游会对该路径设置 immutable；文件名带构建摘要，内容变化会产生新路径 |
| 其他前端静态资源 | 保留上游 `Cache-Control`，先观察再按实测调整 | 上游不一定为所有资源设置长期缓存，贸然覆盖会让升级后的 HTML 加载旧资源 |
| HTML 导航与 SPA 入口 | 不进入共享缓存，保留上游 `no-store` 或只做短时私有缓存 | Immich 的 HTML 会随版本和运行时配置变化，缓存会造成版本错配 |
| `/api/*` | 默认不缓存，不忽略 Cookie、Authorization 和 `Set-Cookie` | API 包含登录态、用户配置、共享链接和隐私数据 |
| 缩略图、原图、视频流 | 默认不进入公共 CDN | Immich 通用接口没有为第三方 CDN 提供统一的可撤销签名 URL；共享缓存会造成越权读取风险 |
| Release 数据与镜像 | 按内容摘要或 digest 验证后使用 | 数据制品可长缓存，但必须用 SHA256 或镜像 digest 固定内容 |
| 地图 style 与瓦片 | 仅在自有或明确授权的服务上开启缓存 | 地图供应商许可、署名、配额和坐标转换要求不同，不能直接把商业瓦片变成本项目缓存资产 |

“不缓存 API”是安全和正确性的默认值，不是性能上限。确实要缓存公开接口时，应为每个端点单独定义缓存键、认证边界、失效策略和负向测试，不能使用通配符放开。

## CDN 配置要点

1. **回源遵循响应头**：先让 Nginx 和 Immich 决定 `Cache-Control`，CDN 不自行把 HTML 或 API 变成公共缓存。
2. **缓存键包含 Host、路径和必要查询参数**：不要跨域名复用响应，不要把登录 Cookie 当成公开缓存键。
3. **静态路径单独规则**：只对 `/_app/immutable/*` 开启长缓存、浏览器 immutable 和 CDN 长 TTL。
4. **默认旁路私有请求**：对 `/api/*`、上传、WebSocket 和认证端点禁用共享缓存；若使用 WAF，允许 WebSocket Upgrade。
5. **启用现代传输**：在确认客户端兼容后启用 HTTP/2 或 HTTP/3、Brotli 和 TLS；不要只依赖 CDN 的自动压缩覆盖所有响应。
6. **版本更新后按路径清除**：HTML 不缓存，静态资源使用新摘要路径；只有紧急回滚时才按键清理 CDN 缓存。
7. **保留可观测性**：记录命中率、回源率、5xx、首字节时间和缓存状态；不要把 `X-Cache-Status` 暴露为敏感信息。
8. **源站只对 CDN 开放**：生产环境应限制 Immich 源站端口，使用防火墙或私网回源，避免用户绕过 WAF 和缓存策略直连。

上述规则是部署参考，不代表任意 CDN 的一次配置即可生效。不同供应商对 Cookie 旁路、HTTP/3、动态加速和大陆节点准入的配置不同，必须按实际产品验证。

## 免费 CDN 可选通道：jsDelivr

jsDelivr 可以作为 GitHub 仓库静态文件的**可选**加速通道，适合 README、文档、小型配置或不含隐私的构建元数据。它不是数据发布依赖，也不承诺中国大陆线路质量。

可用形式是 `/gh/<owner>/<repo>@<ref>/<path>`。`ref` 可以是分支、Git tag 或提交 SHA：

```text
# 仅用于查看最新文档，不适合作为生产固定地址
https://cdn.jsdmirror.com/gh/webees/immich-cn@main/README.md

# 提交或语义化 tag：内容稳定，适合长期引用
https://cdn.jsdmirror.com/gh/webees/immich-cn@d04f0ee/docs/china-localization.md
https://cdn.jsdmirror.com/gh/webees/immich-cn@v1.0.4/README.md
```

项目提供的 [jsdelivr_url.py](../scripts/jsdelivr_url.py) 默认使用中国加速候选
`cdn.jsdmirror.com`，用户可用 `--base` 或 `IMMICH_CN_JSDELIVR_BASE` 替换：

```bash
python scripts/jsdelivr_url.py --ref v1.0.4 --path README.md
IMMICH_CN_JSDELIVR_BASE=https://cdn.jsdelivr.net \
  python scripts/jsdelivr_url.py --ref v1.0.4 --path README.md
```

节点可用性不能只看域名，必须验证 TLS、响应状态、内容摘要和实际线路。2026-10-07 对
`/gh/webees/immich-cn@main/README.md` 的探测结果如下：

| endpoint | 探测结果 | 默认策略 |
|:--|:--|:--|
| `cdn.jsdmirror.com` / `cdn.jsdmirror.cn` | `200` | 默认中国加速候选，仍须校验内容 |
| `jsd.onmicrosoft.cn` | `200` | 可选备用 |
| `cdn.jsdelivr.net` | `200` | 官方 fallback |
| `gcore.jsdelivr.net` / `fastly.jsdelivr.net` | `200` | 官方多 CDN fallback |
| `cdn.jsdelivr.us` | `302` | 仅作可选节点，先验证重定向目标 |
| `jsd.cdn.zzko.cn` | TLS certificate expired | 不纳入默认或自动 fallback |
| `test.jsdelivr.us` | 未验证 | 不纳入默认地址 |

- `@main`、提交 SHA 和 `v1.0.4` 的仓库文件返回 `200`；
- 语义化 tag 的响应带 `Cache-Control: public, max-age=31536000, immutable`，适合固定版本；
- 分支或提交路径的响应缓存时间可能更短，生产引用应固定到提交 SHA 或语义化 tag；
- GitHub Release 中的 `immich-cn-geodata-admin2-default-v1.zip` 和 `immich-cn-manifest-json-v1.json` 通过 jsDelivr 请求返回 `404`。jsDelivr 的 GitHub 通道服务的是 Git 树文件，不会自动镜像 Release 附件；
- 因此当前不能把本项目的大型 Release 资产写成 jsDelivr URL。若未来需要免费 CDN，可选择在仓库中发布小型指针文件，或把公开静态资产放到单独、许可清晰的静态仓库；不要把二进制 zip 提交进主仓库。

大陆线路质量必须实测，不能因为节点域名带 `.cn` 或任何服务商宣传“中国加速”就把它当成有 SLA 的中国大陆 CDN。至少应在主要省份、运营商和早晚高峰做多次测速，并观察 DNS 解析、TLS 握手、首字节和下载完成时间。第三方 mirror 不是可信 origin，必须使用 HTTPS，并优先固定到 commit SHA；下载后仍应用 SHA256 校验内容。线路不理想时，它应当只是可选 fallback，不应替换官方 Release、GHCR 或自有源站。

也不要让 jsDelivr 代理 Immich 的 `/_app/immutable` 构建资源、照片、缩略图、视频或认证 API。那些文件不在本 GitHub 仓库中，且私有媒体不应经过不受你控制的第三方缓存。

## 地图加速

Immich 默认 map style 指向 `tiles.immich.cloud`。自定义底图可通过「系统管理 → 设置 → 地图与 GPS 设置」填入 Light/Dark style URL；上游文档说明这可用于替换默认瓦片提供方。

需要注意：

- Immich 默认 CSP 的 `connect-src` 只包含自身、`static.immich.cloud` 和 `tiles.immich.cloud` 等来源。接入其他域名前，要用 `IMMICH_HELMET_FILE` 或上游支持的配置方式调整 CSP，否则浏览器会拦截瓦片请求；
- 更推荐把自有地图服务放在同源路径下，例如由 Nginx 代理到 `/maps/`，这样 CDN、缓存、TLS 和 CSP 边界更容易控制；
- 不要把高德、腾讯、MapTiler 等第三方瓦片直接复制到本项目 CDN 后公开再分发。先确认服务条款、配额、署名和坐标转换要求；
- WGS-84 底图不会与 GeoNames 点位产生系统性偏移；GCJ-02 底图需要额外的显示或瓦片坐标处理。

## 验证方法

部署后至少检查以下响应：

```bash
# 前端不可变资源：应看到 long max-age 与 immutable
curl -sSI https://immich.example.com/_app/immutable/example.js

# API 与 HTML：不应被共享缓存
curl -sSI https://immich.example.com/api/server/config
curl -sSI https://immich.example.com/

# Nginx 示例配置语法
docker run --rm \
  -v "$PWD/examples/nginx/immich-cn.conf:/etc/nginx/conf.d/default.conf:ro" \
  docker.io/nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de \
  nginx -t
```

如果 API 或 HTML 返回了公共长缓存，应先停止 CDN 规则并回滚，而不是继续扩大缓存范围。静态资源命中率提升不能以绕过认证或泄露照片为代价。

## 当前未提供的能力

- 不提供公共 CDN 地址、国内节点、对象存储网关或地图瓦片镜像；
- 不自动修改 Immich 的 CSP；自定义地图来源必须在部署侧显式配置；
- 不对 CDN 供应商的备案、跨境带宽、内容合规和计费作保证；
- 不把私有照片、缩略图和视频流作为公共静态资源分发。
