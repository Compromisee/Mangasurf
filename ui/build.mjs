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

import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import { mkdirSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
let esbuild;
try {
    esbuild = require("esbuild");
} catch (e) {
    try {
        console.log("Installing build dependencies (esbuild)…");
        execSync("npm install", { stdio: "inherit", cwd: dirname(fileURLToPath(import.meta.url)) });
        esbuild = require("esbuild");
    } catch (err) {
        console.error("Could not load or install esbuild:", err);
        process.exit(1);
    }
}

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../readerm/reader/app/vendor");
mkdirSync(outDir, { recursive: true });

const watch = process.argv.includes("--watch");

const options = {
    entryPoints: [resolve(here, "src/widgets.jsx")],
    outfile: resolve(outDir, "heroui.js"),
    bundle: true,
    format: "iife",
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
    const prebuilt = resolve(here, "node_modules/@heroui/styles/dist/heroui.min.css");
    let scoped = "";
    if (existsSync(prebuilt)) {
        scoped = readFileSync(prebuilt, "utf8");
    }
    const local = readFileSync(resolve(here, "src/overrides.css"), "utf8");
    writeFileSync(resolve(outDir, "heroui.css"), (scoped ? scoped + "\n" : "") + local);
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
        try {
            const bytes = statSync(resolve(outDir, name)).size;
            console.log(`${name}: ${(bytes / 1024).toFixed(1)} KB`);
        } catch {}
    }
}
