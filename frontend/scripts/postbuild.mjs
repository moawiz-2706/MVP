// SPA fallback: Vercel's static serving returns 404.html for paths that don't
// map to a built file. The multi-service gateway does not apply this project's
// rewrites, so we emit 404.html as a copy of index.html — every client-side
// route (/app, /book/*, deep links) then boots the SPA and React Router resolves
// the path client-side.
import { copyFileSync } from "node:fs";

copyFileSync("dist/index.html", "dist/404.html");
console.log("postbuild: dist/404.html written (SPA fallback)");
