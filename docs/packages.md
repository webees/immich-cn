# Packages 说明

GHCR 中有两个容器包，它们不是重复镜像，也不是可互换别名：

| Package | 角色 | 基础 | 入口 | 目标平台 |
|:--|:--|:--|:--|:--|
| `ghcr.io/webees/immich-cn` | 纯数据镜像，把 geodata 释放到宿主机目录 | Alpine | `immich-cn-install` | `linux/amd64`, `linux/arm64` |
| `ghcr.io/webees/immich-cn-server` | 开箱即用的 Immich server 覆盖镜像 | 官方 `immich-server` | `immich-cn-entrypoint` + `start.sh` | `linux/amd64`, `linux/arm64` |

## China pull addresses

`ghcr.io` 是 canonical image source，也是签名和 digest 的比对基准；在中国大陆默认使用可覆盖的 registry mirror：

| Mirror | Pull prefix | 状态 |
|:--|:--|:--|
| `ghcr.nju.edu.cn` | `ghcr.nju.edu.cn/` | 默认，不是官方 origin |
| `docker.m.daocloud.io` | `docker.m.daocloud.io/ghcr.io/` | 可选 fallback |
| `ghcr.dockerproxy.net` | `ghcr.dockerproxy.net/` | 可选 fallback |
| `ghcr.io` | `ghcr.io/` | 官方源，最终 fallback 与 digest 基准 |

Compose 示例通过 `IMMICH_CN_GHCR_MIRROR` 选择 prefix。2026-10-07 对两个 package 的 `latest` 做了 manifest 对比，三个 mirror 与 `ghcr.io` 返回相同 digest；这不构成长期可用性或安全性保证。生产环境仍应从官方源确认 digest，再把 mirror 当作同一 digest 的传输通道。

## 为什么有两个

`immich-cn` 只负责分发数据，适合继续使用官方 Immich 镜像并挂载数据目录的用户。 `immich-cn-server` 在官方 server 镜像启动前注入数据，适合希望减少手工挂载步骤的用户。

两者都包含同一份 geodata，但用途、入口和升级边界不同。不要用数据镜像替换 Immich server，也不要假设两个包的 `latest` 摘要相同。

许可证也不同：`immich-cn` 的数据处理层按 MIT 发布；`immich-cn-server` 包含上游 Immich server 代码，按当前组合方式声明为 `AGPL-3.0-only AND MIT`。具体再分发义务应结合镜像内实际文件确认。

## Image size and tradeoffs

镜像大小要区分两个数字：

- `docker image ls` 显示的是本地解压后的近似大小；
- registry 实际传输的是压缩层，`docker buildx imagetools inspect` 或 registry manifest 才能看到拉取体积。

以 2026-10-07 的发布为例，数据镜像 `immich-cn` 本地显示约 111 MB，但其 amd64 压缩层合计约 29.6 MB；最大固定成本是 geodata 和运行时粒度表，不是入口脚本或基础系统。`immich-cn-server` 本地约 1.63 GB，主要来自上游 Immich server 基础镜像；本项目新增的数据层只占其中很小一部分。

当前针对尺寸的约束：

- 数据镜像使用 Alpine 自带工具，不额外安装 `gzip` 包；
- Dockerfile 用 `COPY --chmod` 设置脚本权限，避免额外的 `RUN chmod` 层；
- `build/langs`、Release 的 i18n 包和 Docker 镜像只保留旧版 Immich 实际读取的 `en.json` 与上游 `LICENSE`，不再复制整套语言包；
- `.dockerignore` 只放行 `build/geodata`、`build/langs` 和运行时粒度表，源码、缓存、测试和构建中间文件不会进入上下文；
- CI 对合成构建的两个镜像设置 10 MiB 尺寸预算，并检查镜像内不存在冗余 `zh.json`。

不采用“先把数据打成 tar.gz 再放入镜像”的方案：OCI 层本身已经压缩，重复压缩对拉取体积收益有限，却增加启动解压时间和临时磁盘占用。需要更小体积时，优先使用纯数据镜像或 `--geodata-only`，而不是删除运行时需要的 geodata、粒度表或许可证。

## 标签

| Package | 标签 | 用途 |
|:--|:--|:--|
| `immich-cn` | `latest` | 最近一次成功构建的数据 |
| `immich-cn` | `YYYY-MM-DD` | 当日最新数据，同日重跑可更新 |
| `immich-cn` | `sha-<短提交>` | 对应控制面代码提交 |
| `immich-cn` | `<语义化版本>` | `Release` 工作流创建的版本标签 |
| `immich-cn-server` | `latest` | 最近数据 + 默认 Immich `release` |
| `immich-cn-server` | `release` | 与 Immich `release` 标签对齐 |
| `immich-cn-server` | `release-YYYY-MM-DD` | 当日最新数据与 Immich `release`，同日重跑可更新 |
| `immich-cn-server` | `sha-<短提交>` | 对应控制面代码提交 |
| `immich-cn-server` | `<语义化版本>` | `Release` 工作流创建的版本标签 |

生产环境应固定到 Git SHA 或完整 digest；日期标签只用于当日跟踪。

## 供应链证据

每次镜像发布都会：

- 生成 BuildKit provenance 与 SBOM；
- 在构建前把 Immich tag 解析为 digest，并用 `tag@digest` 固定本次 server 基础镜像，同时写入 OCI `org.opencontainers.image.base.digest`；
- 在数据目录中保留 i18n 语言文件的上游 `LICENSE`；
- 执行 Trivy 漏洞和许可证扫描；在当次扫描数据库与扫描范围内，数据镜像的 `HIGH`/`CRITICAL` 阻断， Immich 覆盖镜像只阻断相对官方基础镜像新增的漏洞，继承项写入显式例外报告；
- 通过 GitHub OIDC 使用 Cosign keyless 签名；
- 推送后按最终 digest 重新拉取并执行入口 smoke test；full-stack smoke 还会验证 PostgreSQL 中的 `geodata_places` 记录、苏州样本和 `/api/server/config`。

OCI 元数据约定中，`org.opencontainers.image.version` 表示项目版本；数据日期单独写入 `org.immich-cn.data-date`，避免把软件版本和数据批次混为一谈。

验证签名时以最终 digest 为准：

```bash
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp 'https://github.com/webees/immich-cn/.github/workflows/.*' \
  ghcr.io/webees/immich-cn@sha256:<digest>
```

`healthcheck` 和运行时数据路径属于 `immich-cn-server` 的 Immich 兼容接口；数据镜像的约定是 `--target` 目录按当前契约提供可挂载的 geodata 文件，实际兼容性仍取决于目标 Immich 版本和部署方式。

## 自动清理

GHCR 版本、`data-*` Release 和 Actions 运行由 `cleanup.yml` 每周清理。默认保留语义版本、 `auto-release`、`latest`、`release` 与最近版本；稳定前可手动启用 `prune-all`。完整规则见 [自动清理与保留策略](maintenance.md)。

发布资产的 canonical ID、v4 文件名和唯一发布规则见 [制品命名规范 v4](artifact-spec.md)。

## 不可混用边界

- `immich-cn-server:release-YYYY-MM-DD` 固定的是本项目数据与该次构建使用的 Immich 标签；
- `immich-cn:YYYY-MM-DD` 的镜像内只有数据层文件，没有 Immich server 二进制，不能直接运行 server；
- 自定义 Immich 版本时使用 `release.yml` 或 `workflow_dispatch` 的 `immich-version` 输入；
- 回滚镜像前确认 Immich 数据目录与 `i18n-iso-countries` 路径仍匹配目标 Immich 版本。
