# 纯数据镜像：把构建产物打成可以直接释放到宿主机的镜像。
# 构建：docker build -f docker/geodata.Dockerfile -t ghcr.io/webees/immich-cn:local .
FROM alpine:3.24

LABEL org.opencontainers.image.title="immich-cn geodata" \
      org.opencontainers.image.description="Immich 中文反向地理编码数据" \
      org.opencontainers.image.source="https://github.com/webees/immich-cn" \
      org.opencontainers.image.licenses="MIT"

ARG GEODATA_DIR=build/geodata
ARG LANGS_DIR=build/langs
ARG PATTERNS_TABLE=dist/patterns.tsv.gz

COPY ${GEODATA_DIR} /opt/immich-cn/geodata
COPY ${LANGS_DIR} /opt/immich-cn/i18n-iso-countries/langs
COPY ${PATTERNS_TABLE} /opt/immich-cn/patterns.tsv.gz
COPY docker/install.sh /usr/local/bin/immich-cn-install
COPY docker/apply-pattern.sh /usr/local/bin/immich-cn-apply-pattern

RUN chmod 0755 /usr/local/bin/immich-cn-install /usr/local/bin/immich-cn-apply-pattern \
 && apk add --no-cache gzip

ENV IMMICH_CN_GEODATA_DIR=/opt/immich-cn/geodata \
    IMMICH_CN_LANGS_DIR=/opt/immich-cn/i18n-iso-countries \
    IMMICH_CN_PATTERNS_TABLE=/opt/immich-cn/patterns.tsv.gz

ENTRYPOINT ["/usr/local/bin/immich-cn-install"]
CMD ["--target", "/out"]
