FROM debian:bookworm AS builder

# Use the final upstream Guix release binaries. The architecture-specific SHA256
# pins the downloaded bytes even if the upstream tag or asset URL is replaced.
ARG TARGETARCH

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    case "${TARGETARCH:-}" in \
      amd64) platform="x86_64-linux-gnu"; expected="cdbd6ed7efdb006b91b76389db79d2a3db2593f05e56dd789f394a1b4366c211" ;; \
      arm64) platform="aarch64-linux-gnu"; expected="05cc75f57e934882673b941f1c9c0b99eaddc2fd7fa797224b7187c95db61e96" ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH:-<unset>}"; exit 1 ;; \
    esac; \
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
      "https://github.com/DigiByte-Core/digibyte/releases/download/v9.26.6/digibyte-9.26.6-${platform}.tar.gz" \
      --output /tmp/digibyte.tar.gz; \
    printf '%s  /tmp/digibyte.tar.gz\n' "$expected" | sha256sum --check --strict -; \
    mkdir -p /release/bin; \
    tar --extract --gzip --file /tmp/digibyte.tar.gz --directory /release/bin --strip-components=2 \
      digibyte-9.26.6/bin/digibyted \
      digibyte-9.26.6/bin/digibyte-cli \
      digibyte-9.26.6/bin/digibyte-tx \
      digibyte-9.26.6/bin/digibyte-util \
      digibyte-9.26.6/bin/digibyte-wallet; \
    rm /tmp/digibyte.tar.gz

FROM debian:bookworm-slim

LABEL org.opencontainers.image.source="https://github.com/DigiByte-Core/digibyte" \
      org.opencontainers.image.version="9.26.6" \
      org.opencontainers.image.revision="92330d952625e20aef2ee40671a179ef03872ac1"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates libstdc++6 libgcc-s1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /release/bin/digibyted /usr/local/bin/digibyted
COPY --from=builder /release/bin/digibyte-cli /usr/local/bin/digibyte-cli
COPY --from=builder /release/bin/digibyte-tx /usr/local/bin/digibyte-tx
COPY --from=builder /release/bin/digibyte-util /usr/local/bin/digibyte-util
COPY --from=builder /release/bin/digibyte-wallet /usr/local/bin/digibyte-wallet

RUN groupadd -g 1000 umbrel 2>/dev/null || true && \
    useradd -m -u 1000 -g 1000 umbrel 2>/dev/null || true && \
    mkdir -p /data && chown -R 1000:1000 /data

USER 1000:1000

EXPOSE 12024 14022

CMD ["digibyted", "-datadir=/data", "-printtoconsole"]
