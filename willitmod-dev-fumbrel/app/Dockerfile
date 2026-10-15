# Retain the actual tested Python/runtime/UI/auth/dependency blobs. Only the
# reviewed engine and immutable recipe bundle are added in this release.
FROM ghcr.io/willitmod/fumbrel:0.1.1-dev@sha256:290a91f5e8f42e51af4b9c715c449bda96071b98eb4c2de0ef97e52d9d4fba7a
ARG SOURCE_COMMIT
LABEL org.opencontainers.image.source="https://github.com/WillItMod/5tratStore-dev" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.version="0.1.2-dev" \
      org.opencontainers.image.base.digest="sha256:290a91f5e8f42e51af4b9c715c449bda96071b98eb4c2de0ef97e52d9d4fba7a"
COPY --chown=0:0 --chmod=0644 engine.py catalog.json /app/
