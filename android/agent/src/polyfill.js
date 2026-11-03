/** Enough of the web platform for pi-ai + the OpenAI SDK inside V8. */

export function installPolyfill(host) {
  if (typeof globalThis.process === "undefined") {
    globalThis.process = { env: {}, versions: {} };
  }
  if (typeof globalThis.queueMicrotask !== "function") {
    globalThis.queueMicrotask = (fn) => Promise.resolve().then(fn);
  }
  if (typeof globalThis.structuredClone !== "function") {
    globalThis.structuredClone = function structuredClone(value) {
      const seen = new WeakMap();
      const clone = (v) => {
        if (v === null || typeof v !== "object") {
          if (typeof v === "function" || typeof v === "symbol") {
            throw new TypeError("structuredClone: " + typeof v + " is not cloneable");
          }
          return v;
        }
        if (seen.has(v)) throw new TypeError("structuredClone: circular");
        if (v instanceof Date) return new Date(v.getTime());
        if (v instanceof RegExp) return new RegExp(v.source, v.flags);
        if (typeof ArrayBuffer !== "undefined" && v instanceof ArrayBuffer) return v.slice(0);
        if (typeof ArrayBuffer !== "undefined" && ArrayBuffer.isView(v)) return new v.constructor(v);
        if (v instanceof Map) {
          const out = new Map();
          seen.set(v, out);
          v.forEach((val, key) => out.set(clone(key), clone(val)));
          return out;
        }
        if (v instanceof Set) {
          const out = new Set();
          seen.set(v, out);
          v.forEach((val) => out.add(clone(val)));
          return out;
        }
        const out = Array.isArray(v) ? [] : {};
        seen.set(v, out);
        if (Array.isArray(v)) {
          for (let i = 0; i < v.length; i++) out[i] = clone(v[i]);
          return out;
        }
        for (const k of Object.keys(v)) out[k] = clone(v[k]);
        return out;
      };
      return clone(value);
    };
  }
  if (typeof globalThis.performance !== "object" || typeof globalThis.performance.now !== "function") {
    const origin = Date.now();
    globalThis.performance = {
      now() {
        return Date.now() - origin;
      },
      timeOrigin: origin,
    };
  }

  if (typeof globalThis.crypto === "undefined") {
    globalThis.crypto = {
      getRandomValues(arr) {
        const bytes = host.random(arr.length);
        for (let i = 0; i < arr.length; i++) arr[i] = bytes[i] & 255;
        return arr;
      },
      randomUUID() {
        return host.uuid();
      },
    };
  }

  const timers = new Map();
  let nextTimer = 1;
  globalThis.setTimeout = function (fn, ms) {
    const id = nextTimer++;
    timers.set(id, typeof fn === "function" ? fn : () => {});
    host.timerStart(id, Math.max(0, Number(ms) || 0));
    return id;
  };
  globalThis.clearTimeout = function (id) {
    timers.delete(id);
    host.timerClear(id);
  };
  globalThis.setInterval = function (fn, ms) {
    const id = nextTimer++;
    const delay = Math.max(1, Number(ms) || 0);
    const wrap = () => {
      if (!timers.has(id)) return;
      try {
        fn();
      } finally {
        if (timers.has(id)) host.timerStart(id, delay);
      }
    };
    timers.set(id, wrap);
    host.timerStart(id, delay);
    return id;
  };
  globalThis.clearInterval = globalThis.clearTimeout;
  host.onTimer = (id) => {
    const fn = timers.get(id);
    if (fn) fn();
  };

  class AbortSignalPolyfill {
    constructor() {
      this.aborted = false;
      this.reason = undefined;
      this.onabort = null;
      this._listeners = [];
    }
    addEventListener(type, fn) {
      if (type === "abort") this._listeners.push(fn);
    }
    removeEventListener(type, fn) {
      this._listeners = this._listeners.filter((x) => x !== fn);
    }
    throwIfAborted() {
      if (this.aborted) throw this.reason || new Error("aborted");
    }
  }
  AbortSignalPolyfill.timeout = function (ms) {
    const c = new AbortControllerPolyfill();
    setTimeout(() => c.abort(Object.assign(new Error("timeout"), { name: "TimeoutError" })), Math.max(0, Number(ms) || 0));
    return c.signal;
  };
  AbortSignalPolyfill.any = function (signals) {
    const c = new AbortControllerPolyfill();
    for (const s of signals || []) {
      if (!s) continue;
      if (s.aborted) {
        c.abort(s.reason);
        break;
      }
      s.addEventListener("abort", () => c.abort(s.reason));
    }
    return c.signal;
  };

  class AbortControllerPolyfill {
    constructor() {
      this.signal = new AbortSignalPolyfill();
    }
    abort(reason) {
      if (this.signal.aborted) return;
      this.signal.aborted = true;
      this.signal.reason = reason || new Error("aborted");
      const ev = { type: "abort" };
      if (typeof this.signal.onabort === "function") this.signal.onabort(ev);
      for (const fn of this.signal._listeners) fn(ev);
    }
  }

  if (typeof globalThis.AbortController === "undefined") {
    globalThis.AbortController = AbortControllerPolyfill;
    globalThis.AbortSignal = AbortSignalPolyfill;
  } else {
    if (typeof AbortSignal.timeout !== "function") AbortSignal.timeout = AbortSignalPolyfill.timeout;
    if (typeof AbortSignal.any !== "function") AbortSignal.any = AbortSignalPolyfill.any;
  }

  class HeadersPolyfill {
    constructor(init) {
      this._map = new Map();
      if (!init) return;
      if (typeof init.forEach === "function") {
        init.forEach((v, k) => this.set(k, v));
      } else {
        for (const [k, v] of Object.entries(init)) this.set(k, String(v));
      }
    }
    set(k, v) {
      this._map.set(String(k).toLowerCase(), String(v));
    }
    append(k, v) {
      const key = String(k).toLowerCase();
      const prev = this._map.get(key);
      this._map.set(key, prev ? prev + ", " + String(v) : String(v));
    }
    delete(k) {
      this._map.delete(String(k).toLowerCase());
    }
    get(k) {
      return this._map.get(String(k).toLowerCase()) ?? null;
    }
    has(k) {
      return this._map.has(String(k).toLowerCase());
    }
    forEach(fn) {
      this._map.forEach((v, k) => fn(v, k, this));
    }
    keys() {
      const out = [];
      this._map.forEach((_, k) => out.push(k));
      return out;
    }
    values() {
      const out = [];
      this._map.forEach((v) => out.push(v));
      return out;
    }
    entries() {
      const out = [];
      this._map.forEach((v, k) => out.push([k, v]));
      return out;
    }
    [Symbol.iterator]() {
      return this.entries()[Symbol.iterator]();
    }
  }

  if (typeof globalThis.atob !== "function") {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    globalThis.atob = function (data) {
      let str = String(data).replace(/[=]+$/, "");
      let out = "";
      for (let bc = 0, bs = 0, i = 0; i < str.length; i++) {
        const n = chars.indexOf(str.charAt(i));
        if (n < 0) continue;
        bs = (bs << 6) | n;
        bc += 6;
        if (bc >= 8) {
          bc -= 8;
          out += String.fromCharCode((bs >> bc) & 255);
        }
      }
      return out;
    };
  }
  if (typeof globalThis.TextDecoder !== "function") {
    globalThis.TextDecoder = class {
      decode(buf) {
        const u8 = buf instanceof ArrayBuffer ? new Uint8Array(buf) : buf;
        let s = "";
        for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
        return decodeURIComponent(escape(s));
      }
    };
  }

  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  class ResponsePolyfill {
    constructor(body, init) {
      if (typeof init === "number") {
        this._id = body;
        this.status = init;
        this.headers = new HeadersPolyfill(arguments[2]);
        this.url = "";
      } else {
        init = init || {};
        this._id = init._id;
        this._inline = body;
        this.status = init.status || 200;
        this.headers = new HeadersPolyfill(init.headers);
        this.url = init.url || "";
      }
      this.ok = this.status >= 200 && this.status < 300;
      this.statusText = "";
      const self = this;
      this.body = {
        getReader() {
          return {
            read() {
              const part = host.fetchRead(self._id);
              const decode = (p) => {
                if (!p || p.done) return { done: true, value: undefined };
                return { done: false, value: b64ToBytes(p.b64) };
              };
              if (part && typeof part.then === "function") return part.then(decode);
              return Promise.resolve(decode(part));
            },
            cancel() {
              host.fetchCancel(self._id);
              return Promise.resolve();
            },
            releaseLock() {},
          };
        },
      };
    }
    async arrayBuffer() {
      const chunks = [];
      const reader = this.body.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
      }
      const n = chunks.reduce((a, c) => a + c.length, 0);
      const out = new Uint8Array(n);
      let o = 0;
      for (const c of chunks) {
        out.set(c, o);
        o += c.length;
      }
      return out.buffer;
    }
    async text() {
      return new TextDecoder().decode(await this.arrayBuffer());
    }
    async json() {
      return JSON.parse(await this.text());
    }
    clone() {
      return this;
    }
  }

  // Javet's Android V8 URLSearchParams is not iterable; OpenAI does Object.fromEntries(url.searchParams).
  globalThis.URLSearchParams = class {
    constructor(init) {
      this._pairs = [];
      if (typeof init === "string") {
        const raw = init.startsWith("?") ? init.slice(1) : init;
        for (const part of raw.split("&")) {
          if (!part) continue;
          const i = part.indexOf("=");
          this.append(decodeURIComponent((i < 0 ? part : part.slice(0, i)).replace(/\+/g, " ")), decodeURIComponent((i < 0 ? "" : part.slice(i + 1)).replace(/\+/g, " ")));
        }
      } else if (Array.isArray(init)) {
        for (const row of init) this.append(row[0], row[1]);
      } else if (init && typeof init === "object") {
        if (typeof init.forEach === "function") init.forEach((v, k) => this.append(k, v));
        else for (const [k, v] of Object.entries(init)) this.append(k, v);
      }
    }
    append(k, v) {
      this._pairs.push([String(k), String(v)]);
    }
    set(k, v) {
      this._pairs = this._pairs.filter((p) => p[0] !== String(k));
      this.append(k, v);
    }
    get(k) {
      const found = this._pairs.find((p) => p[0] === String(k));
      return found ? found[1] : null;
    }
    forEach(fn) {
      for (const [k, v] of this._pairs) fn(v, k, this);
    }
    entries() {
      return this._pairs.slice();
    }
    keys() {
      return this._pairs.map((p) => p[0]);
    }
    values() {
      return this._pairs.map((p) => p[1]);
    }
    [Symbol.iterator]() {
      return this._pairs[Symbol.iterator]();
    }
    toString() {
      return this._pairs.map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");
    }
  };
  globalThis.URL = class {
    constructor(input, base) {
      let href = String(input || "");
      if (base && !/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(href)) {
        const b = String(base);
        if (href.startsWith("/")) {
          const origin = b.match(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^/]+/);
          href = (origin ? origin[0] : b.replace(/\/+$/, "")) + href;
        } else {
          href = b.replace(/\/?$/, "/") + href.replace(/^\.\//, "");
        }
      }
      this.href = href;
      const m = href.match(/^([a-zA-Z][a-zA-Z0-9+.-]*:)\/\/([^/?#]*)([^?#]*)(\?[^#]*)?(#.*)?$/);
      this.protocol = m ? m[1] : "";
      this.host = m ? m[2] : "";
      this.hostname = this.host.split(":")[0];
      this.port = this.host.includes(":") ? this.host.split(":").slice(1).join(":") : "";
      this.pathname = m && m[3] ? m[3] : "/";
      this.search = m && m[4] ? m[4] : "";
      this.hash = m && m[5] ? m[5] : "";
      this.origin = this.protocol && this.host ? this.protocol + "//" + this.host : "";
      this.searchParams = new URLSearchParams(this.search);
    }
    toString() {
      return this.href;
    }
  };

  if (typeof globalThis.Headers === "undefined") globalThis.Headers = HeadersPolyfill;
  if (typeof globalThis.FormData !== "function") {
    globalThis.FormData = class FormData {
      constructor() {
        this._pairs = [];
      }
      append(k, v) {
        this._pairs.push([String(k), v]);
      }
      set(k, v) {
        this._pairs = this._pairs.filter((p) => p[0] !== String(k));
        this.append(k, v);
      }
      get(k) {
        const found = this._pairs.find((p) => p[0] === String(k));
        return found ? found[1] : null;
      }
      has(k) {
        return this._pairs.some((p) => p[0] === String(k));
      }
      forEach(fn) {
        for (const [k, v] of this._pairs) fn(v, k, this);
      }
      entries() {
        return this._pairs.slice();
      }
      [Symbol.iterator]() {
        return this._pairs[Symbol.iterator]();
      }
    };
  }
  if (typeof globalThis.Blob !== "function") {
    globalThis.Blob = class Blob {
      constructor(parts, opts) {
        this._parts = parts || [];
        this.type = (opts && opts.type) || "";
        this.size = 0;
      }
    };
  }
  if (typeof globalThis.File !== "function") {
    globalThis.File = class File extends globalThis.Blob {
      constructor(parts, name, opts) {
        super(parts, opts);
        this.name = name || "file";
      }
    };
  }

  function headersToObject(headers) {
    const out = {};
    if (!headers) return out;
    const inner = headers.values && headers.nulls && typeof headers.values.forEach === "function"
      ? headers.values
      : headers;
    if (typeof inner.forEach === "function") {
      inner.forEach((v, k) => {
        if (v != null) out[k] = String(v);
      });
      return out;
    }
    if (typeof inner.entries === "function") {
      for (const [k, v] of inner.entries()) {
        if (v != null) out[k] = String(v);
      }
      return out;
    }
    for (const [k, v] of Object.entries(inner)) {
      if (v == null || typeof v === "object") continue;
      out[k] = String(v);
    }
    return out;
  }

  function bodyToString(body) {
    if (body == null) return null;
    if (typeof body === "string") return body;
    if (body instanceof Uint8Array) return new TextDecoder().decode(body);
    if (body instanceof ArrayBuffer) return new TextDecoder().decode(body);
    if (typeof body === "object" && typeof body.byteLength === "number") {
      return new TextDecoder().decode(body);
    }
    return String(body);
  }

  globalThis.fetch = function (input, init) {
    const url = typeof input === "string" ? input : input && (input.url || input.href);
    const spec = {
      method: (init && init.method) || "GET",
      headers: {},
      body: bodyToString(init && init.body),
    };
    const headers = init && init.headers;
    if (headers) Object.assign(spec.headers, headersToObject(headers));
    host.log("fetch " + spec.method + " " + url);
    const meta = host.fetchStart(url, JSON.stringify(spec));
    return Promise.resolve(new ResponsePolyfill(null, { _id: meta.id, status: meta.status, headers: meta.headers, url }));
  };

  if (typeof globalThis.Response !== "function") globalThis.Response = ResponsePolyfill;
  if (typeof globalThis.Request !== "function") {
    globalThis.Request = class {
      constructor(input, init) {
        init = init || {};
        this.url = typeof input === "string" ? input : input && (input.url || input.href);
        this.method = String((init.method || "GET")).toUpperCase();
        this.headers = new HeadersPolyfill(init.headers);
        this.body = init.body;
        this.signal = init.signal;
      }
    };
  }
  if (typeof globalThis.ReadableStream !== "function") {
    globalThis.ReadableStream = class {
      constructor(source) {
        this._source = source || {};
        this._queue = [];
        this._closed = false;
        this._booted = false;
      }
      getReader() {
        const stream = this;
        const ctrl = {
          enqueue(v) {
            stream._queue.push(v);
          },
          close() {
            stream._closed = true;
          },
          error() {
            stream._closed = true;
          },
        };
        if (!this._booted) {
          this._booted = true;
          try {
            this._source.start && this._source.start(ctrl);
          } catch (_) {}
        }
        return {
          async read() {
            if (stream._source.pull) await stream._source.pull(ctrl);
            if (stream._queue.length) return { done: false, value: stream._queue.shift() };
            return { done: true, value: undefined };
          },
          cancel() {
            return Promise.resolve(stream._source.cancel && stream._source.cancel());
          },
          releaseLock() {},
        };
      }
    };
  }
}
