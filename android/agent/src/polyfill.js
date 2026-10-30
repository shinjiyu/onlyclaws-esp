/** Enough of the web platform for pi-ai + the OpenAI SDK inside V8. */

export function installPolyfill(host) {
  if (typeof globalThis.process === "undefined") {
    globalThis.process = { env: {}, versions: {} };
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

  class AbortControllerPolyfill {
    constructor() {
      this.signal = new AbortSignalPolyfill();
    }
    abort(reason) {
      if (this.signal.aborted) return;
      this.signal.aborted = true;
      this.signal.reason = reason || new Error("aborted");
      for (const fn of this.signal._listeners) fn({ type: "abort" });
    }
  }

  if (typeof globalThis.AbortController === "undefined") {
    globalThis.AbortController = AbortControllerPolyfill;
    globalThis.AbortSignal = AbortSignalPolyfill;
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
    get(k) {
      return this._map.get(String(k).toLowerCase()) ?? null;
    }
    has(k) {
      return this._map.has(String(k).toLowerCase());
    }
    forEach(fn) {
      for (const [k, v] of this._map) fn(v, k, this);
    }
    entries() {
      return this._map.entries();
    }
    [Symbol.iterator]() {
      return this._map.entries();
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
    constructor(id, status, headers) {
      this._id = id;
      this.status = status;
      this.ok = status >= 200 && status < 300;
      this.statusText = "";
      this.headers = new HeadersPolyfill(headers);
      const self = this;
      this.body = {
        getReader() {
          return {
            read() {
              return host.fetchRead(self._id).then((part) => {
                if (part.done) return { done: true, value: undefined };
                return { done: false, value: b64ToBytes(part.b64) };
              });
            },
            cancel() {
              host.fetchCancel(self._id);
              return Promise.resolve();
            },
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

  if (typeof globalThis.Headers === "undefined") globalThis.Headers = HeadersPolyfill;

  globalThis.fetch = function (input, init) {
    const url = typeof input === "string" ? input : input && input.url;
    const spec = {
      method: (init && init.method) || "GET",
      headers: {},
      body: init && init.body != null ? String(init.body) : null,
    };
    const headers = init && init.headers;
    if (headers) {
      if (typeof headers.forEach === "function") headers.forEach((v, k) => (spec.headers[k] = v));
      else Object.assign(spec.headers, headers);
    }
    return host.fetchStart(url, JSON.stringify(spec)).then((meta) => {
      return new ResponsePolyfill(meta.id, meta.status, meta.headers);
    });
  };
}
