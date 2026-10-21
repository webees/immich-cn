# 纯数据镜像：把构建产物打成可以直接释放到宿主机的镜像。
# 构建：docker build -f docker/geodata.Dockerfile -t ghcr.io/webees/immich-cn:local .
# 默认使用 AWS Public ECR；CI 可在持续限流时切换到同摘要镜像源。
ARG BASE_IMAGE=public.ecr.aws/docker/library/alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="immich-cn geodata" \
      org.opencontainers.image.description="Immich 中文反向地理编码数据" \
      org.opencontainers.image.source="https://github.com/webees/immich-cn" \
      org.opencontainers.image.licenses="MIT"

ARG GEODATA_DIR=build/geodata
ARG LANGS_DIR=build/langs
ARG PATTERNS_TABLE=dist/immich-cn-patterns-tsv-v1.gz

COPY ${GEODATA_DIR} /opt/immich-cn/geodata
COPY ${LANGS_DIR} /opt/immich-cn/i18n-iso-countries/langs
COPY ${PATTERNS_TABLE} /opt/immich-cn/immich-cn-patterns-tsv-v1.gz
COPY docker/immich-cn-common.sh /usr/local/bin/immich-cn-common.sh
COPY --chmod=0755 docker/install.sh /usr/local/bin/immich-cn-install
COPY --chmod=0755 docker/apply-pattern.sh /usr/local/bin/immich-cn-apply-pattern

ENV IMMICH_CN_GEODATA_DIR=/opt/immich-cn/geodata \
    IMMICH_CN_LANGS_DIR=/opt/immich-cn/i18n-iso-countries \
    IMMICH_CN_PATTERNS_TABLE=/opt/immich-cn/immich-cn-patterns-tsv-v1.gz

ENTRYPOINT ["/usr/local/bin/immich-cn-install"]
CMD ["--target", "/out"]
