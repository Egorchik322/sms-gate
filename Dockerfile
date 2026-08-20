# syntax=docker/dockerfile:1
FROM debian:12-slim

ARG DIALOUT_GID=20
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-gammu gammu gammu-smsd ca-certificates gcc pkg-config libc6-dev libgammu-dev \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid ${DIALOUT_GID} serialhost || true \
    && groupadd --system --gid 10001 gateway \
    && useradd --system --uid 10001 --gid gateway --groups ${DIALOUT_GID} gateway

WORKDIR /opt/sms-gateway
COPY helpers ./helpers
RUN gcc -O2 -Wall -Wextra -Werror -o /usr/local/bin/gammu-smsd-status helpers/gammu-smsd-status.c $(pkg-config --cflags --libs gammu-smsd) \
    && chmod 0755 /usr/local/bin/gammu-smsd-status \
    && rm -rf helpers /usr/include/gammu /usr/lib/*/libgsmsd.so /usr/lib/*/libgammu.so
COPY app ./app
COPY migrations ./migrations
COPY config ./config
COPY scripts ./scripts
RUN chmod 0755 scripts/*.sh scripts/*.py \
    && mkdir -p /data/gammu/inbox /data/gammu/outbox /data/gammu/sent /data/gammu/error /data/gammu/processed \
    && chown -R gateway:gateway /opt/sms-gateway /data

ENV PYTHONPATH=/opt/sms-gateway
USER gateway
ENTRYPOINT ["/opt/sms-gateway/scripts/entrypoint.sh"]
