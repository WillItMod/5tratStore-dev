# 5tratDoom: Chocolate Doom compiled to WebAssembly and played in the browser.
#
# The container only serves static files. The game itself runs in the
# viewer's browser, so there is no X server, VNC session or emulator here.

# The build output (JavaScript + WebAssembly) is the same on every platform,
# so it is always built on amd64, the only platform this Emscripten release
# is published for. The final stage below is a multi-arch nginx image.
FROM --platform=linux/amd64 emscripten/emsdk:2.0.24@sha256:81ec54b7a096d28f24d906955dbf98ff336cca47658d980c243baa36f6484f9f AS build

# Cloudflare's Chocolate Doom 3.0 WebAssembly port (GPL-2.0).
ARG DOOM_WASM_REPO=https://github.com/cloudflare/doom-wasm.git
ARG DOOM_WASM_COMMIT=65e0d3ae2ffa604155eebd96ed40da6567bd08f4
# Freedoom game data (BSD-style licence). The checksum is the one published
# in the signed freedoom-0.13.0-CHECKSUM release file.
ARG FREEDOOM_VERSION=0.13.0
ARG FREEDOOM_SHA256=3f9b264f3e3ce503b4fb7f6bdcb1f419d93c7b546f4df3e874dd878db9688f59

RUN apt-get update \
  && apt-get install -y --no-install-recommends autoconf automake ca-certificates curl git libtool pkg-config unzip \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git init -q doom-wasm \
  && git -C doom-wasm fetch -q --depth 1 "${DOOM_WASM_REPO}" "${DOOM_WASM_COMMIT}" \
  && git -C doom-wasm checkout -q FETCH_HEAD \
  && test "$(git -C doom-wasm rev-parse HEAD)" = "${DOOM_WASM_COMMIT}"

WORKDIR /src/doom-wasm
# Release build changes to the upstream flags: no source maps, and link the
# IndexedDB filesystem so save games survive a page reload.
RUN sed -i -e 's/-gsource-map //' -e 's/ --source-map-base \///' -e 's/-lwebsocket\.js/-lwebsocket.js -lidbfs.js/' configure.ac \
  && grep -q -- '-lidbfs.js' configure.ac \
  && ! grep -q -- 'source-map' configure.ac \
  && emconfigure autoreconf -fi \
  && ac_cv_exeext=".html" emconfigure ./configure --host=none-none-none \
  && emmake make -j"$(nproc)"

RUN mkdir -p /out/licenses \
  && cp src/websockets-doom.js src/websockets-doom.wasm /out/ \
  && cp COPYING.md /out/licenses/chocolate-doom-COPYING.md \
  && curl -fsSL --proto '=https' -o /tmp/freedoom.zip \
    "https://github.com/freedoom/freedoom/releases/download/v${FREEDOOM_VERSION}/freedoom-${FREEDOOM_VERSION}.zip" \
  && echo "${FREEDOOM_SHA256}  /tmp/freedoom.zip" | sha256sum -c - \
  && unzip -q -j /tmp/freedoom.zip -d /tmp/freedoom \
    "freedoom-${FREEDOOM_VERSION}/freedoom1.wad" \
    "freedoom-${FREEDOOM_VERSION}/freedoom2.wad" \
    "freedoom-${FREEDOOM_VERSION}/COPYING.txt" \
  && mv /tmp/freedoom/freedoom1.wad /tmp/freedoom/freedoom2.wad /out/ \
  && mv /tmp/freedoom/COPYING.txt /out/licenses/freedoom-COPYING.txt \
  && rm -rf /tmp/freedoom /tmp/freedoom.zip

COPY web/ /out/
COPY NOTICE.md /out/licenses/NOTICE.md

# The page shows download progress from these uncompressed sizes, and nginx
# serves the pre-compressed copies to browsers that accept gzip.
RUN cd /out \
  && printf '{"freedoom1.wad":%s,"freedoom2.wad":%s,"websockets-doom.wasm":%s}\n' \
    "$(stat -c %s freedoom1.wad)" "$(stat -c %s freedoom2.wad)" "$(stat -c %s websockets-doom.wasm)" > assets.json \
  && find /out -type f \( -name '*.html' -o -name '*.js' -o -name '*.json' -o -name '*.wasm' -o -name '*.wad' -o -name '*.cfg' \) \
    -exec gzip -9 -k -n {} + \
  && chmod -R a+rX,go-w /out

FROM nginxinc/nginx-unprivileged:1.28-alpine@sha256:7377697a821c131a924a7105fafbe7414db4e9fcc77a6f08f776f33f141ec3f8

ARG APP_VERSION=0.2.1
LABEL org.opencontainers.image.title="5tratDoom" \
  org.opencontainers.image.description="Chocolate Doom (WebAssembly) with Freedoom, played natively in the browser" \
  org.opencontainers.image.version="${APP_VERSION}" \
  org.opencontainers.image.source="https://github.com/WillItMod/5tratStore-dev" \
  org.opencontainers.image.licenses="GPL-2.0-or-later AND BSD-3-Clause"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /out/ /usr/share/nginx/html/

EXPOSE 8080
