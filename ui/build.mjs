/* build.mjs — bundle the HeroUI layer into a single static file.
 *
 * Output goes to readerm/reader/app/vendor/, which is committed. That is
 * deliberate: the packaged app must build with PyInstaller alone, and an end
 * user installing from pip or running the exe must never need Node. Node is a
 * developer tool here, nothing more.
 *
 *     npm --prefix ui install
 *     npm --prefix ui run build
 */

import * as esbuild from "esbuild";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../readerm/reader/app/vendor");
mkdirSync(outDir, { recursive: true });

const watch = process.argv.includes("--watch");

const options = {
    entryPoints: [resolve(here, "src/widgets.jsx")],
    outfile: resolve(outDir, "heroui.js"),
    bundle: true,
    format: "iife",
    // Everything is inlined: the page loads one file with no import map and
    // no bare specifiers to resolve.
    platform: "browser",
    target: ["chrome110", "edge110", "safari16", "firefox110"],
    jsx: "automatic",
    loader: { ".jsx": "jsx" },
    minify: !watch,
    sourcemap: false,
    legalComments: "none",
    define: { "process.env.NODE_ENV": '"production"' },
    logLevel: "info",
};

async function styles() {
    /* HeroUI ships its component CSS prebuilt in @heroui/styles. Running
     * Tailwind over the source only produced *utilities* -- measured zero
     * occurrences of `.slider`, `.switch`, `.chip`, `.tabs` or `.select` --
     * so the components mounted with correct markup and no styling at all.
     * The shipped sheet is the thing to use.
     *
     * It is copied rather than imported so the app loads one file from its
     * own origin, with no @import round trip and no node_modules at runtime.
     */
    const prebuilt = resolve(here, "node_modules/@heroui/styles/dist/heroui.min.css");
    const scoped = readFileSync(prebuilt, "utf8");
    const local = readFileSync(resolve(here, "src/overrides.css"), "utf8");
    writeFileSync(resolve(outDir, "heroui.css"), scoped + "\n" + local);
}

if (watch) {
    const ctx = await esbuild.context(options);
    await ctx.watch();
    await styles();
    console.log("watching…");
} else {
    await esbuild.build(options);
    await styles();
    for (const name of ["heroui.js", "heroui.css"]) {
        const bytes = statSync(resolve(outDir, name)).size;
        console.log(`${name}: ${(bytes / 1024).toFixed(1)} KB`);
    }
}
