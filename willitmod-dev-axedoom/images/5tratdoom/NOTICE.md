# 5tratDoom third-party software

5tratDoom packages two free software projects. It contains no id Software game
data.

## Chocolate Doom (WebAssembly port)

- Project: https://github.com/cloudflare/doom-wasm (based on
  https://github.com/chocolate-doom/chocolate-doom)
- Source revision: 65e0d3ae2ffa604155eebd96ed40da6567bd08f4
- Licence: GNU General Public License v2 (see `chocolate-doom-COPYING.md`)
- Build changes: source maps removed and the Emscripten IndexedDB filesystem
  linked (`-lidbfs.js`) so save games persist in the browser. The exact build
  recipe is `willitmod-dev-axedoom/images/5tratdoom/Dockerfile` in
  https://github.com/WillItMod/5tratStore-dev.

## Freedoom

- Project: https://freedoom.github.io/
- Release: 0.13.0 (`freedoom1.wad`, `freedoom2.wad`)
- Licence: BSD-style (see `freedoom-COPYING.txt`)
