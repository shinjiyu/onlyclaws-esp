import * as esbuild from "esbuild";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const root = dirname(fileURLToPath(import.meta.url));

await esbuild.build({
  absWorkingDir: root,
  entryPoints: ["src/entry.js"],
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "es2022",
  outfile: resolve(root, "../app/src/main/assets/agent/pi.js"),
  legalComments: "none",
  logLevel: "info",
  define: {
    "process.env.NODE_ENV": '"production"',
  },
  alias: {
    "node:fs": "./src/empty.js",
    "node:http": "./src/empty.js",
    "node:crypto": "./src/empty.js",
    "node:zlib": "./src/empty.js",
    child_process: "./src/empty.js",
  },
  banner: {
    js: `
var process = globalThis.process || { env: {}, versions: {} };
if (typeof globalThis.TextEncoder !== "function") {
  globalThis.TextEncoder = class {
    encode(s) {
      s = String(s ?? "");
      var u = unescape(encodeURIComponent(s)), a = new Uint8Array(u.length);
      for (var i = 0; i < u.length; i++) a[i] = u.charCodeAt(i);
      return a;
    }
  };
}
if (typeof globalThis.TextDecoder !== "function") {
  globalThis.TextDecoder = class {
    decode(buf) {
      var u8 = buf instanceof ArrayBuffer ? new Uint8Array(buf) : (buf || new Uint8Array());
      var s = "";
      for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
      try { return decodeURIComponent(escape(s)); } catch (e) { return s; }
    }
  };
}
`,
  },
});

// Javet's Android V8 is built without ICU, so \\p{…} regexes fail to parse.
const out = resolve(root, "../app/src/main/assets/agent/pi.js");
const ascii = {
  "ID_Start": "A-Za-z",
  "ID_Continue": "A-Za-z0-9",
  ASCII: "\\x00-\\x7F",
  Mn: "\\x00",
  Mc: "\\x00",
  Me: "\\x00",
  L: "A-Za-z",
  N: "0-9",
  Nd: "0-9",
};
let js = readFileSync(out, "utf8");
js = js.replace(/\\p\{([^}]+)\}/g, (_, name) => ascii[name] || ascii[name.split("=")[0]] || "\\x00");
writeFileSync(out, js);
