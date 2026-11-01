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
if (typeof globalThis.structuredClone !== "function") {
  globalThis.structuredClone = function structuredClone(value) {
    var seen = typeof WeakMap === "function" ? new WeakMap() : null;
    function clone(v) {
      if (v === null || typeof v !== "object") {
        if (typeof v === "function" || typeof v === "symbol") {
          throw new TypeError("structuredClone: " + typeof v + " is not cloneable");
        }
        return v;
      }
      if (seen) {
        if (seen.has(v)) throw new TypeError("structuredClone: circular");
      }
      if (v instanceof Date) return new Date(v.getTime());
      if (v instanceof RegExp) return new RegExp(v.source, v.flags);
      if (typeof ArrayBuffer !== "undefined" && v instanceof ArrayBuffer) return v.slice(0);
      if (typeof ArrayBuffer !== "undefined" && ArrayBuffer.isView(v)) return new v.constructor(v);
      if (typeof Map !== "undefined" && v instanceof Map) {
        var m = new Map();
        if (seen) seen.set(v, m);
        v.forEach(function (val, key) { m.set(clone(key), clone(val)); });
        return m;
      }
      if (typeof Set !== "undefined" && v instanceof Set) {
        var s = new Set();
        if (seen) seen.set(v, s);
        v.forEach(function (val) { s.add(clone(val)); });
        return s;
      }
      var out = Array.isArray(v) ? [] : {};
      if (seen) seen.set(v, out);
      if (Array.isArray(v)) {
        for (var i = 0; i < v.length; i++) out[i] = clone(v[i]);
        return out;
      }
      var keys = Object.keys(v);
      for (var j = 0; j < keys.length; j++) out[keys[j]] = clone(v[keys[j]]);
      return out;
    }
    return clone(value);
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
