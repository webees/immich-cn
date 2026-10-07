# 镜像发布

GHCR 中有两个容器包，它们不是重复镜像，也不是可互换别名：

| 包 | 角色 | 基础镜像 | 入口 | 目标平台 |
|:--|:--|:--|:--|:--|
| `ghcr.io/webees/immich-cn` | 纯数据镜像，把地理数据释放到宿主机目录 | Alpine | `immich-cn-install` | `linux/amd64`, `linux/arm64` |
| `ghcr.io/webees/immich-cn-server` | 开箱即用的 Immich 服务端覆盖镜像 | 官方 `immich-server` | `immich-cn-entrypoint` + `start.sh` | `linux/amd64`, `linux/arm64` |

## 拉取地址

`ghcr.io` 是规范镜像源，也是签名与摘要的比对基准；在中国大陆默认使用可覆盖的镜像源：

| 镜像源 | 拉取前缀 | 状态 |
|:--|:--|:--|
| `ghcr.nju.edu.cn` | `ghcr.nju.edu.cn/` | 默认，不是官方回源 |
| `docker.m.daocloud.io` | `docker.m.daocloud.io/ghcr.io/` | 可选回退 |
| `ghcr.dockerproxy.net` | `ghcr.dockerproxy.net/` | 可选回退 |
| `ghcr.io` | `ghcr.io/` | 官方源，最终回退与摘要基准 |

Compose 示例通过 `IMMICH_CN_GHCR_MIRROR` 选择前缀。2026-10-07 对两个包的 `latest` 做了清单对比，三个镜像源与 `ghcr.io` 返回相同摘要；这不构成长期可用性或安全性保证。生产环境仍应从官方源确认摘要，再把镜像源当作同一摘要的传输通道。

## 镜像差异

`immich-cn` 只负责分发数据，适合继续使用官方 Immich 镜像并挂载数据目录的用户。`immich-cn-server` 在官方服务端镜像启动前注入数据，适合希望减少手工挂载步骤的用户。

两者都包含同一份地理数据，但用途、入口和升级边界不同。不要用数据镜像替换 Immich 服务端，也不要假设两个包的 `latest` 摘要相同。

许可证也不同：`immich-cn` 的数据处理层按 MIT 发布；`immich-cn-server` 包含上游 Immich 服务端代码，按当前组合方式声明为 `AGPL-3.0-only AND MIT`。具体再分发义务应结合镜像内实际文件确认。

## 体积取舍

镜像大小要区分两个数字：

- `docker image ls` 显示的是本地解压后的近似大小；
- 镜像仓库实际传输的是压缩层，`docker buildx imagetools inspect` 或镜像仓库的清单才能看到拉取体积。

以 2026-10-07 的发布为例，数据镜像 `immich-cn` 本地显示约 111 MB，但其 amd64 压缩层合计约 29.6 MB；最大固定成本是地理数据与运行时粒度表，不是入口脚本或基础系统。`immich-cn-server` 本地约 1.63 GB，主要来自上游 Immich 服务端基础镜像；本项目新增的数据层只占其中很小一部分。

当前针对尺寸的约束：

- 数据镜像使用 Alpine 自带工具，不额外安装 `gzip` 包；
- Dockerfile 用 `COPY --chmod` 设置脚本权限，避免额外的 `RUN chmod` 层；
- `build/langs`、发布里的 i18n 包和 Docker 镜像只保留 Immich 1.136.0 ~ 3.2.x 实际读取的 `en.json` 与上游 `LICENSE`；`check_artifacts` 会拒绝构建产物中出现多余语言文件；
- `.dockerignore` 只放行 `build/geodata`、`build/langs` 和运行时粒度表，源码、缓存、测试和构建中间文件不会进入上下文；
- CI 对合成构建的两个镜像设置 10 MiB 尺寸预算，并检查镜像内不存在冗余 `zh.json`。

不采用“先把数据打成 tar.gz 再放入镜像”的方案：OCI 层本身已经压缩，重复压缩对拉取体积收益有限，却增加启动解压时间和临时磁盘占用。需要更小体积时，优先使用纯数据镜像或 `--geodata-only`，而不是删除运行时需要的地理数据、粒度表或许可证。

## 版本规范

项目版本采用四段式 `<Immich 版本>.<项目修订>`，前三段与 Immich 上游版本对齐，第四段只表示本项目在同一条 Immich 版本线上的修订号。例如上游 Immich `3.3.0` 对应本项目 `3.3.0.1`；上游升级到 `3.3.1` 后，本项目从 `3.3.1.1` 重新计数。Git 发布标签为 `v3.3.0.1`，GHCR 镜像标签为 `3.3.0.1`。

## 标签规范

| 包 | 标签 | 用途 |
|:--|:--|:--|
| `immich-cn` | `latest` | 最近一次成功构建的数据 |
| `immich-cn` | `YYYY-MM-DD` | 当日最新数据，同日重跑可更新 |
| `immich-cn` | `sha-<短提交>` | 对应控制面代码提交 |
| `immich-cn` | `<X.Y.Z.N>` | 发布工作流创建的 Immich 对齐版本标签 |
| `immich-cn-server` | `latest` | 最近数据 + 默认 Immich `release` |
| `immich-cn-server` | `release` | 与 Immich `release` 标签对齐 |
| `immich-cn-server` | `release-YYYY-MM-DD` | 当日最新数据与 Immich `release`，同日重跑可更新 |
| `immich-cn-server` | `sha-<短提交>` | 对应控制面代码提交 |
| `immich-cn-server` | `<X.Y.Z.N>` | 发布工作流创建的 Immich 对齐版本标签 |

镜像的版本标签**不带 `v` 前缀**：Git 侧的发布标签是 `vX.Y.Z.N`，GHCR 上的镜像标签是 `X.Y.Z.N`。2026-10-08 实测：带 `v` 前缀的镜像标签返回 `not found`，不带前缀的同一个版本可以正常解析。生产环境应固定到 Git 提交 SHA 或完整摘要；日期标签只用于当日跟踪。

```bash
# Immich 对齐版本（发布工作流推送）
docker pull ghcr.io/webees/immich-cn:3.3.0.1
# 某个控制面提交
docker pull ghcr.io/webees/immich-cn-server:sha-cdc0ba3
# 最可追溯的写法：固定摘要（摘要值以 imagetools inspect 的当前输出为准）
docker pull ghcr.io/webees/immich-cn@sha256:<digest>
```

在 GitHub Packages 页面上还会看到 `sha256-<digest>` 形式的标签。它们不是本项目的发布标签，而是 GHCR 为 Cosign 签名与证明对象这类 OCI 引用对象生成的引用标签：以镜像摘要命名的那个标签指向的是签名、证明对象，不是镜像本身。请勿把这类标签当作镜像拉取，也不要手动删除；`cleanup.yml` 会保护 `sha256-*` / `sha256:*` 版本。

Immich 对齐版本发布必须同时推送两个镜像；工作流在创建版本化发布前会拒绝 `push-images=false`，并对两个版本标签的镜像仓库摘要与本次构建输出做比对，避免出现只有 GitHub 发布、没有对应包标签，或标签指向其他镜像的半成品版本。

## 供应链

每次镜像发布都会：

- 生成 BuildKit 来源证明与 SBOM；
- 在构建前把 Immich 标签解析为摘要，并用 `tag@digest` 固定本次服务端基础镜像，同时写入 OCI `org.opencontainers.image.base.digest`；该摘要参与发布变化判断，Immich 基础镜像更新会触发服务端镜像重建；
- 在数据目录中保留 i18n 语言文件的上游 `LICENSE`；
- 执行 Trivy 漏洞与许可证扫描；在当次扫描数据库与扫描范围内，数据镜像的 `HIGH`/`CRITICAL` 阻断，Immich 覆盖镜像只阻断相对官方基础镜像新增的漏洞，继承项写入显式例外报告；
- 通过 GitHub OIDC 使用 Cosign 无密钥签名，并按最终摘要执行 `cosign verify`；
- 推送后按最终摘要重新拉取并执行入口冒烟测试；完整服务栈冒烟还会验证 PostgreSQL 中的 `geodata_places` 记录、苏州样本和 `/api/server/config`。

OCI 元数据约定中，`org.opencontainers.image.version` 表示项目版本；数据日期单独写入 `org.immich-cn.data-date`，避免把软件版本和数据批次混为一谈。

验证签名时以最终摘要为准：

```bash
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp 'https://github.com/webees/immich-cn/.github/workflows/.*' \
  ghcr.io/webees/immich-cn@sha256:<digest>
```

`healthcheck` 与运行时数据路径属于 `immich-cn-server` 的 Immich 兼容接口；数据镜像的约定是 `--target` 目录按当前契约提供可挂载的地理数据文件，实际兼容性仍取决于目标 Immich 版本和部署方式。

## 自动清理

GHCR 版本、`data-*` 发布和 Actions 运行由 `cleanup.yml` 每周清理。默认保留 Immich 对齐版本、兼容三段式稳定版本、`auto-release`、`latest`、`release` 与最近版本；稳定前可手动启用 `prune-all`。完整规则见 [运维与常见问题](operations.md)。

发布资产的规范 ID、v4 文件名与唯一发布规则见 [数据格式与制品命名](data-format.md)。

## 混用边界

- `immich-cn-server:release-YYYY-MM-DD` 固定的是本项目数据与该次构建使用的 Immich 标签；
- `immich-cn:YYYY-MM-DD` 的镜像内只有数据层文件，没有 Immich 服务端二进制，不能直接运行服务端；
- 自定义 Immich 版本时使用 `release.yml` 或 `workflow_dispatch` 的 `immich-version` 输入；
- 回滚镜像前确认 Immich 数据目录与 `i18n-iso-countries` 路径仍匹配目标 Immich 版本。
