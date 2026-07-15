FROM debian:bookworm-slim

# DigiByte Core: install from official upstream release tarballs (amd64 + arm64).
ARG TARGETARCH
ARG DGB_RELEASE_TAG="v9.26.4"
ARG DGB_VERSION="9.26.4"
ARG DGB_AMD64_SHA256="523da7ac9ee0f1bcb38ff75da6f01997b9491a9eee1e2b0ce3c90f60b2aaa9b3"
ARG DGB_ARM64_SHA256="0ee31595a1dcbac56fcac7cabdb32be2d11acc9636deda134a58177beb8af113"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gzip tar libstdc++6 libgcc-s1 libevent-2.1-7 && \
    rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    case "${TARGETARCH:-}" in \
      amd64) asset="digibyte-${DGB_VERSION}-x86_64-linux-gnu.tar.gz"; sha="${DGB_AMD64_SHA256}" ;; \
      arm64) asset="digibyte-${DGB_VERSION}-aarch64-linux-gnu.tar.gz"; sha="${DGB_ARM64_SHA256}" ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH:-<unset>}"; exit 1 ;; \
    esac; \
    url="https://github.com/DigiByte-Core/digibyte/releases/download/${DGB_RELEASE_TAG}/${asset}"; \
    curl -fsSL -o /tmp/dgb.tar.gz "${url}"; \
    echo "${sha}  /tmp/dgb.tar.gz" | sha256sum -c -; \
    mkdir -p /opt/digibyte; \
    tar -xzf /tmp/dgb.tar.gz -C /opt/digibyte --strip-components=1; \
    rm -f /tmp/dgb.tar.gz; \
    if [ -f /opt/digibyte/lib/libdigibyteconsensus.so.0.0.0 ]; then \
      cp -f /opt/digibyte/lib/libdigibyteconsensus.so.0.0.0 /opt/digibyte/lib/libdigibyteconsensus.so.0 || true; \
      cp -f /opt/digibyte/lib/libdigibyteconsensus.so.0.0.0 /opt/digibyte/lib/libdigibyteconsensus.so || true; \
    fi; \
    mkdir -p /opt/digibyte; \
    install -m 0755 /opt/digibyte/bin/digibyted /usr/local/bin/digibyted; \
    install -m 0755 /opt/digibyte/bin/digibyte-cli /usr/local/bin/digibyte-cli; \
    install -m 0755 /opt/digibyte/bin/digibyte-tx /usr/local/bin/digibyte-tx; \
    install -m 0755 /opt/digibyte/bin/digibyte-util /usr/local/bin/digibyte-util; \
    if [ -f /opt/digibyte/bin/digibyte-wallet ]; then \
      install -m 0755 /opt/digibyte/bin/digibyte-wallet /usr/local/bin/digibyte-wallet; \
    fi

ENV LD_LIBRARY_PATH="/opt/digibyte/lib"

RUN groupadd -g 1000 umbrel 2>/dev/null || true && \
    useradd -m -u 1000 -g 1000 umbrel 2>/dev/null || true && \
    mkdir -p /data && chown -R 1000:1000 /data

USER 1000:1000

EXPOSE 12024 14022

CMD ["digibyted", "-datadir=/data", "-printtoconsole"]
