# 开箱即用的 Immich 镜像：在官方镜像基础上注入中文 geodata。
# 构建：docker build -f docker/immich.Dockerfile \
#         --build-arg IMMICH_VERSION=release -t ghcr.io/webees/immich-cn-server:local .
ARG IMMICH_BASE=ghcr.io/immich-app/immich-server
ARG IMMICH_VERSION=release

FROM ${IMMICH_BASE}:${IMMICH_VERSION}

LABEL org.opencontainers.image.title="immich-cn server" \
      org.opencontainers.image.description="Immich server with bundled Chinese reverse geocoding data" \
      org.opencontainers.image.source="https://github.com/webees/immich-cn" \
      org.opencontainers.image.licenses="AGPL-3.0-only AND MIT"

ARG GEODATA_DIR=build/geodata
ARG LANGS_DIR=build/langs
ARG PATTERNS_TABLE=dist/patterns.tsv.gz
ARG IMMICH_CN_DATA_DATE=unknown

USER root

COPY ${GEODATA_DIR} /opt/immich-cn/geodata
COPY ${LANGS_DIR} /opt/immich-cn/i18n-iso-countries/langs
COPY ${PATTERNS_TABLE} /opt/immich-cn/patterns.tsv.gz
COPY docker/entrypoint.sh /usr/local/bin/immich-cn-entrypoint
COPY docker/apply-pattern.sh /usr/local/bin/immich-cn-apply-pattern

RUN chmod 0755 /usr/local/bin/immich-cn-entrypoint /usr/local/bin/immich-cn-apply-pattern \
 && mkdir -p /build/geodata

ENV IMMICH_CN_GEODATA_DIR=/opt/immich-cn/geodata \
    IMMICH_CN_LANGS_DIR=/opt/immich-cn/i18n-iso-countries/langs \
    IMMICH_CN_PATTERNS_TABLE=/opt/immich-cn/patterns.tsv.gz \
    IMMICH_CN_PATTERN="{admin_2}" \
    IMMICH_CN_DATA_DATE=${IMMICH_CN_DATA_DATE}

ENTRYPOINT ["tini", "--", "/usr/local/bin/immich-cn-entrypoint"]
CMD ["start.sh"]
