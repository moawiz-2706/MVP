// Produce the SPA fallback and inject the exact Vite build assets into the
// service-worker precache. This avoids a first offline launch depending on a
// prior runtime request for every hashed JavaScript/CSS chunk.
import { copyFileSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";

copyFileSync("dist/index.html", "dist/404.html");

const manifest = JSON.parse(readFileSync("dist/.vite/manifest.json", "utf8"));
const assets = new Set([
  "/", "/index.html", "/404.html", "/manifest.webmanifest", "/offline.html",
  "/icons/icon-192.png", "/icons/icon-512.png", "/icons/maskable-512.png",
]);
for (const entry of Object.values(manifest)) {
  for (const value of Object.values(entry)) {
    if (typeof value === "string" && /\.(?:js|css|svg|png|webp|jpg|jpeg|woff2?)$/i.test(value)) assets.add(`/${value}`);
    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === "string" && /\.(?:js|css|svg|png|webp|jpg|jpeg|woff2?)$/i.test(item)) assets.add(`/${item}`);
      }
    }
  }
}
const version = createHash("sha256").update(JSON.stringify([...assets].sort())).digest("hex").slice(0, 12);
const swPath = "dist/sw.js";
let serviceWorker = readFileSync(swPath, "utf8");
serviceWorker = serviceWorker.replace(/const CACHE_NAME = "[^"]+";/, `const CACHE_NAME = "passport-staff-shell-${version}";`);
serviceWorker = serviceWorker.replace(/const SHELL_ASSETS = \[[^\n]*\];/, `const SHELL_ASSETS = ${JSON.stringify([...assets].sort())};`);
writeFileSync(swPath, serviceWorker);
console.log(`postbuild: SPA fallback and ${assets.size} PWA shell assets precached (${version})`);
