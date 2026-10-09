/* OnlyClaws shared helpers: base path, i18n, fetch wrapper. */
(function () {
  const BASE = location.pathname.replace(/\/(console|apply)(\/.*)?$/, "").replace(/\/$/, "");
  const LANG_KEY = "oc_lang";
  const dict = { zh: {}, en: {} };

  function detectLang() {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === "zh" || saved === "en") return saved;
    return /^zh/i.test(navigator.language || "") ? "zh" : "en";
  }
  let lang = detectLang();

  function t(key, vars) {
    let s = (dict[lang] && dict[lang][key]) ?? (dict.zh[key] ?? key);
    if (vars) for (const k in vars) s = s.replaceAll("{" + k + "}", vars[k]);
    return s;
  }

  function apply(root) {
    const scope = root || document;
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    scope.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    scope.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    scope.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
    scope.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    scope.querySelectorAll("[data-lang-toggle]").forEach((el) => { el.textContent = lang === "zh" ? "EN" : "中文"; });
    const titleKey = document.body && document.body.dataset.titleKey;
    if (titleKey) document.title = t(titleKey);
  }

  function setLang(next) {
    lang = next === "en" ? "en" : "zh";
    localStorage.setItem(LANG_KEY, lang);
    apply();
    document.dispatchEvent(new CustomEvent("oc:lang", { detail: lang }));
  }

  function addStrings(table) {
    for (const l of ["zh", "en"]) Object.assign(dict[l], table[l] || {});
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  async function api(path, opts = {}) {
    const { timeoutMs = 30000, ...rest } = opts;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const isForm = rest.body instanceof FormData;
    let body = rest.body;
    if (body && !isForm && typeof body !== "string") body = JSON.stringify(body);
    try {
      const r = await fetch(BASE + path, {
        credentials: "same-origin",
        ...rest,
        body,
        headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...(rest.headers || {}) },
        signal: controller.signal,
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        let msg = data.message || data.detail || r.statusText;
        if (Array.isArray(msg)) msg = msg.map((x) => x.msg || JSON.stringify(x)).join("; ");
        const err = new Error(msg || "HTTP " + r.status);
        err.status = r.status;
        err.code = msg;
        throw err;
      }
      return data;
    } catch (ex) {
      if (ex && ex.name === "AbortError") {
        const err = new Error(t("err.timeout"));
        err.status = 0;
        throw err;
      }
      if (ex && !ex.status && /Failed to fetch|NetworkError|Load failed|network connection/i.test(ex.message || "")) {
        const err = new Error(t("err.network"));
        err.status = 0;
        throw err;
      }
      throw ex;
    } finally {
      clearTimeout(timer);
    }
  }

  async function copy(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    if (btn) {
      const prev = btn.textContent;
      btn.textContent = t("common.copied");
      setTimeout(() => { btn.textContent = prev; }, 1200);
    }
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return t("time.just");
    if (diff < 3600) return t("time.min", { n: Math.floor(diff / 60) });
    if (diff < 86400) return t("time.hour", { n: Math.floor(diff / 3600) });
    return d.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  addStrings({
    zh: {
      "common.copy": "复制",
      "common.copied": "已复制",
      "err.timeout": "请求超时，请稍后重试",
      "err.network": "网络连接中断，请检查网络后重试",
      "time.just": "刚刚",
      "time.min": "{n} 分钟前",
      "time.hour": "{n} 小时前",
    },
    en: {
      "common.copy": "Copy",
      "common.copied": "Copied",
      "err.timeout": "Request timed out. Try again.",
      "err.network": "Connection dropped. Check your network and retry.",
      "time.just": "just now",
      "time.min": "{n} min ago",
      "time.hour": "{n} h ago",
    },
  });

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-lang-toggle]");
    if (el) setLang(lang === "zh" ? "en" : "zh");
  });

  window.OC = {
    BASE,
    t,
    apply,
    addStrings,
    setLang,
    get lang() { return lang; },
    api,
    copy,
    escapeHtml,
    fmtTime,
    $: (sel, root) => (root || document).querySelector(sel),
    $$: (sel, root) => Array.from((root || document).querySelectorAll(sel)),
  };
})();
