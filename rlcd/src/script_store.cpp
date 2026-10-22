#include "script_store.h"

#include <string.h>

#include <map>
#include <vector>

extern "C" int crypto_sign_ed25519_tweet_open(unsigned char *m, unsigned long long *mlen,
                                              const unsigned char *sm, unsigned long long n,
                                              const unsigned char *pk);

namespace {

constexpr const char *kIndexPath = "s/index.json";

bool fail(std::string &err, const char *why) {
  err = why;
  return false;
}

bool nameOk(const std::string &name) {
  if (name.empty() || name.size() > kScriptNameLen) return false;
  for (char c : name) {
    const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                    c == '_' || c == '-';
    if (!ok) return false;
  }
  return true;
}

void putLe32(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
  p[2] = (uint8_t)(v >> 16);
  p[3] = (uint8_t)(v >> 24);
}

uint32_t getLe32(const uint8_t *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

struct Sha256 {
  uint32_t s[8];
  uint64_t bits = 0;
  uint8_t buf[64]{};
  size_t n = 0;

  Sha256() {
    s[0] = 0x6a09e667;
    s[1] = 0xbb67ae85;
    s[2] = 0x3c6ef372;
    s[3] = 0xa54ff53a;
    s[4] = 0x510e527f;
    s[5] = 0x9b05688c;
    s[6] = 0x1f83d9ab;
    s[7] = 0x5be0cd19;
  }

  static uint32_t rotr(uint32_t x, uint32_t r) { return (x >> r) | (x << (32 - r)); }

  void block(const uint8_t *p) {
    static const uint32_t K[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2};
    uint32_t w[64];
    for (int i = 0; i < 16; ++i) {
      w[i] = ((uint32_t)p[i * 4] << 24) | ((uint32_t)p[i * 4 + 1] << 16) |
             ((uint32_t)p[i * 4 + 2] << 8) | p[i * 4 + 3];
    }
    for (int i = 16; i < 64; ++i) {
      const uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
      const uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = s[0], b = s[1], c = s[2], d = s[3], e = s[4], f = s[5], g = s[6], h = s[7];
    for (int i = 0; i < 64; ++i) {
      const uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const uint32_t ch = (e & f) ^ ((~e) & g);
      const uint32_t t1 = h + S1 + ch + K[i] + w[i];
      const uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      const uint32_t t2 = S0 + maj;
      h = g;
      g = f;
      f = e;
      e = d + t1;
      d = c;
      c = b;
      b = a;
      a = t1 + t2;
    }
    s[0] += a;
    s[1] += b;
    s[2] += c;
    s[3] += d;
    s[4] += e;
    s[5] += f;
    s[6] += g;
    s[7] += h;
  }

  void update(const uint8_t *data, size_t len) {
    bits += (uint64_t)len * 8;
    while (len) {
      const size_t take = len < (64 - n) ? len : (64 - n);
      memcpy(buf + n, data, take);
      n += take;
      data += take;
      len -= take;
      if (n == 64) {
        block(buf);
        n = 0;
      }
    }
  }

  void final(uint8_t out[32]) {
    uint8_t blockbuf[64];
    memset(blockbuf, 0, sizeof(blockbuf));
    memcpy(blockbuf, buf, n);
    size_t i = n;
    blockbuf[i++] = 0x80;
    if (i > 56) {
      block(blockbuf);
      memset(blockbuf, 0, sizeof(blockbuf));
      i = 0;
    }
    for (int b = 0; b < 8; ++b) blockbuf[63 - b] = (uint8_t)(bits >> (8 * b));
    block(blockbuf);
    for (int w = 0; w < 8; ++w) {
      out[w * 4] = (uint8_t)(s[w] >> 24);
      out[w * 4 + 1] = (uint8_t)(s[w] >> 16);
      out[w * 4 + 2] = (uint8_t)(s[w] >> 8);
      out[w * 4 + 3] = (uint8_t)s[w];
    }
  }
};

bool ed25519Verify(const uint8_t *msg, size_t n, const uint8_t sig[64], const uint8_t pk[32]) {
  std::string sm(64 + n, '\0');
  memcpy(&sm[0], sig, 64);
  if (n) memcpy(&sm[64], msg, n);
  std::string opened(sm.size(), '\0');
  unsigned long long mlen = 0;
  return crypto_sign_ed25519_tweet_open((unsigned char *)&opened[0], &mlen,
                                         (const unsigned char *)sm.data(), sm.size(), pk) == 0;
}

struct Ver {
  uint32_t v = 0;
  bool ok = true;
};

struct Slot {
  std::vector<Ver> versions;
};

struct Index {
  std::string active;
  bool run = false;
  bool safe = false;
  std::map<std::string, Slot> scripts;
};

std::string blobPath(const std::string &name, uint32_t version) {
  return "s/" + name + "." + std::to_string(version);
}

std::string dumpIndex(const Index &idx) {
  std::string o = "{\"active\":\"";
  o += idx.active;
  o += "\",\"run\":";
  o += idx.run ? "true" : "false";
  o += ",\"safe\":";
  o += idx.safe ? "true" : "false";
  o += ",\"scripts\":{";
  bool firstScript = true;
  for (const auto &kv : idx.scripts) {
    if (!firstScript) o += ',';
    firstScript = false;
    o += '"';
    o += kv.first;
    o += "\":{\"versions\":[";
    bool firstVer = true;
    for (const Ver &ver : kv.second.versions) {
      if (!firstVer) o += ',';
      firstVer = false;
      o += "{\"v\":";
      o += std::to_string(ver.v);
      o += ",\"ok\":";
      o += ver.ok ? "true" : "false";
      o += '}';
    }
    o += "]}";
  }
  o += "}}";
  return o;
}

struct Cur {
  const char *p;
  const char *end;
  bool ok = true;

  void skip() {
    while (p < end && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) ++p;
  }
  char peek() {
    skip();
    return p < end ? *p : 0;
  }
  bool eat(char c) {
    skip();
    if (p >= end || *p != c) {
      ok = false;
      return false;
    }
    ++p;
    return true;
  }
  std::string str() {
    if (!eat('"')) return {};
    std::string o;
    while (ok && p < end && *p != '"') {
      if (*p == '\\') {
        ok = false;
        return {};
      }
      o.push_back(*p++);
    }
    if (!eat('"')) return {};
    return o;
  }
  bool key(const char *k) {
    const std::string s = str();
    if (!ok || s != k) {
      ok = false;
      return false;
    }
    return eat(':');
  }
  uint32_t num() {
    skip();
    if (p >= end || *p < '0' || *p > '9') {
      ok = false;
      return 0;
    }
    uint64_t v = 0;
    while (p < end && *p >= '0' && *p <= '9') {
      v = v * 10u + (uint32_t)(*p - '0');
      if (v > 0xffffffffull) {
        ok = false;
        return 0;
      }
      ++p;
    }
    return (uint32_t)v;
  }
  bool boolean() {
    skip();
    if (end - p >= 4 && memcmp(p, "true", 4) == 0) {
      p += 4;
      return true;
    }
    if (end - p >= 5 && memcmp(p, "false", 5) == 0) {
      p += 5;
      return false;
    }
    ok = false;
    return false;
  }
};

bool parseIndex(const std::string &in, Index &idx) {
  idx = Index{};
  Cur c{in.data(), in.data() + in.size(), true};
  if (!c.eat('{') || !c.key("active")) return false;
  idx.active = c.str();
  if (!idx.active.empty() && !nameOk(idx.active)) return false;
  if (!c.eat(',') || !c.key("run")) return false;
  idx.run = c.boolean();
  if (!c.ok || !c.eat(',') || !c.key("safe")) return false;
  idx.safe = c.boolean();
  if (!c.ok || !c.eat(',') || !c.key("scripts") || !c.eat('{')) return false;
  if (c.peek() != '}') {
    for (;;) {
      const std::string name = c.str();
      if (!c.ok || !nameOk(name) || !c.eat(':') || !c.eat('{') || !c.key("versions") || !c.eat('['))
        return false;
      Slot slot;
      if (c.peek() != ']') {
        for (;;) {
          if (!c.eat('{') || !c.key("v")) return false;
          Ver ver;
          ver.v = c.num();
          if (!c.ok || ver.v == 0 || !c.eat(',') || !c.key("ok")) return false;
          ver.ok = c.boolean();
          if (!c.ok || !c.eat('}')) return false;
          if (slot.versions.size() >= 16) return false;
          slot.versions.push_back(ver);
          if (c.peek() == ',') {
            c.eat(',');
            continue;
          }
          break;
        }
      }
      if (!c.eat(']') || !c.eat('}')) return false;
      idx.scripts[name] = slot;
      if (c.peek() == ',') {
        c.eat(',');
        continue;
      }
      break;
    }
  }
  if (!c.ok || !c.eat('}') || !c.eat('}')) return false;
  c.skip();
  return c.ok && c.p == c.end;
}

bool ioRemove(ScriptStoreIo &io, const std::string &path) {
  return io.remove && io.remove(io.ctx, path.c_str());
}

bool ioExists(ScriptStoreIo &io, const std::string &path) {
  return io.exists && io.exists(io.ctx, path.c_str());
}

void recoverIndex(ScriptStoreIo &io) {
  const std::string bak = std::string(kIndexPath) + ".bak";
  const std::string tmp = std::string(kIndexPath) + ".tmp";
  if (!ioExists(io, kIndexPath) && ioExists(io, bak)) {
    if (io.rename) io.rename(io.ctx, bak.c_str(), kIndexPath);
  }
  if (ioExists(io, tmp)) ioRemove(io, tmp);
  if (ioExists(io, kIndexPath) && ioExists(io, bak)) ioRemove(io, bak);
}

// present=false means there is no index. Corrupt JSON is an error.
bool loadIndex(ScriptStoreIo &io, Index &idx, bool &present, std::string &err) {
  present = false;
  idx = Index{};
  recoverIndex(io);
  if (!ioExists(io, kIndexPath)) return true;
  present = true;
  std::string raw;
  if (!io.read || !io.read(io.ctx, kIndexPath, raw)) return fail(err, "index read failed");
  if (raw.size() > 8192 || !parseIndex(raw, idx)) return fail(err, "index corrupt");
  return true;
}

bool writeChecked(ScriptStoreIo &io, const std::string &path, const uint8_t *data, size_t n,
                  std::string &err) {
  if (!io.write || !io.write(io.ctx, path.c_str(), data, n)) return fail(err, "write failed");
  std::string back;
  if (!io.read || !io.read(io.ctx, path.c_str(), back) || back.size() != n ||
      memcmp(back.data(), data, n) != 0) {
    ioRemove(io, path);
    return fail(err, "read-back mismatch");
  }
  return true;
}

bool publishNew(ScriptStoreIo &io, const std::string &path, const uint8_t *data, size_t n,
                std::string &err) {
  if (ioExists(io, path)) {
    std::string cur;
    if (!io.read || !io.read(io.ctx, path.c_str(), cur)) return fail(err, "read existing version");
    if (cur.size() == n && memcmp(cur.data(), data, n) == 0) return true;
    return fail(err, "version already stored");
  }
  const std::string tmp = path + ".tmp";
  if (ioExists(io, tmp)) ioRemove(io, tmp);
  if (!writeChecked(io, tmp, data, n, err)) return false;
  if (!io.rename || !io.rename(io.ctx, tmp.c_str(), path.c_str())) {
    ioRemove(io, tmp);
    return fail(err, "rename failed");
  }
  return true;
}

bool publishReplace(ScriptStoreIo &io, const std::string &path, const std::string &text,
                    std::string &err) {
  const std::string tmp = path + ".tmp";
  const std::string bak = path + ".bak";
  if (!writeChecked(io, tmp, (const uint8_t *)text.data(), text.size(), err)) return false;
  if (ioExists(io, bak) && !ioRemove(io, bak)) {
    ioRemove(io, tmp);
    return fail(err, "bak remove failed");
  }
  if (ioExists(io, path)) {
    if (!io.rename || !io.rename(io.ctx, path.c_str(), bak.c_str())) {
      ioRemove(io, tmp);
      return fail(err, "index backup failed");
    }
  }
  if (!io.rename || !io.rename(io.ctx, tmp.c_str(), path.c_str())) {
    if (!ioExists(io, path) && ioExists(io, bak)) io.rename(io.ctx, bak.c_str(), path.c_str());
    ioRemove(io, tmp);
    return fail(err, "index rename failed");
  }
  if (ioExists(io, bak)) ioRemove(io, bak);
  return true;
}

bool saveIndex(ScriptStoreIo &io, const Index &idx, std::string &err) {
  return publishReplace(io, kIndexPath, dumpIndex(idx), err);
}

void sortDesc(std::vector<Ver> &vs) {
  for (size_t i = 0; i < vs.size(); ++i) {
    for (size_t j = i + 1; j < vs.size(); ++j) {
      if (vs[j].v > vs[i].v) {
        Ver t = vs[i];
        vs[i] = vs[j];
        vs[j] = t;
      }
    }
  }
}

void dropOtherScripts(ScriptStoreIo &io, Index &idx, const std::string &keep) {
  for (auto it = idx.scripts.begin(); it != idx.scripts.end();) {
    if (it->first == keep) {
      ++it;
      continue;
    }
    for (const Ver &ver : it->second.versions) ioRemove(io, blobPath(it->first, ver.v));
    it = idx.scripts.erase(it);
  }
}

void pruneVersions(ScriptStoreIo &io, const std::string &name, Slot &slot) {
  sortDesc(slot.versions);
  while ((int)slot.versions.size() > kScriptKeepVersions) {
    ioRemove(io, blobPath(name, slot.versions.back().v));
    slot.versions.pop_back();
  }
}

uint8_t modeByte(const std::string &mode) {
  if (mode == "once") return 1;
  if (mode == "loop") return 2;
  return 0;
}

const char *modeName(uint8_t b) {
  if (b == 1) return "once";
  if (b == 2) return "loop";
  return nullptr;
}

}  // namespace

void scriptSha256(const uint8_t *data, size_t n, uint8_t out[32]) {
  Sha256 h;
  if (n && data) h.update(data, n);
  h.final(out);
}

bool scriptHexTo32(const char *hex, uint8_t out[32]) {
  if (!hex) return false;
  for (int i = 0; i < 32; ++i) {
    const int hi = hexVal(hex[i * 2]);
    const int lo = hexVal(hex[i * 2 + 1]);
    if (hi < 0 || lo < 0) return false;
    out[i] = (uint8_t)((hi << 4) | lo);
  }
  return hex[64] == 0;
}

void scriptSha256Hex(const uint8_t *data, size_t n, char out[65]) {
  uint8_t dig[32];
  scriptSha256(data, n, dig);
  static const char *hexd = "0123456789abcdef";
  for (int i = 0; i < 32; ++i) {
    out[i * 2] = hexd[dig[i] >> 4];
    out[i * 2 + 1] = hexd[dig[i] & 15];
  }
  out[64] = 0;
}

bool scriptEnvelopePrefix(const ScriptImage &in, std::string &prefix, std::string &err) {
  prefix.clear();
  if (!nameOk(in.name)) return fail(err, "bad script id");
  if (!modeByte(in.mode)) return fail(err, "bad script mode");
  if (in.version == 0) return fail(err, "bad script version");
  if (in.everyMs > 3600000u) return fail(err, "bad every_ms");
  if (in.source.empty() || in.source.size() > kScriptMaxSource) return fail(err, "bad script length");
  prefix.assign(kScriptHeaderLen + in.source.size(), '\0');
  uint8_t *p = (uint8_t *)&prefix[0];
  p[0] = 'L';
  p[1] = 'C';
  p[2] = 'L';
  p[3] = 'W';
  p[4] = kScriptFmtVersion;
  memcpy(p + 5, in.name.data(), in.name.size());
  p[37] = modeByte(in.mode);
  p[38] = 0;
  putLe32(p + 39, in.everyMs);
  putLe32(p + 43, (uint32_t)in.source.size());
  putLe32(p + 47, in.version);
  scriptSha256((const uint8_t *)in.source.data(), in.source.size(), p + 51);
  memcpy(p + kScriptHeaderLen, in.source.data(), in.source.size());
  return true;
}

bool scriptEnvelopeOpen(const uint8_t *blob, size_t n, const uint8_t pubkey[32], ScriptImage &out,
                        std::string &err) {
  out = ScriptImage{};
  if (!blob || !pubkey) return fail(err, "empty envelope");
  if (n < kScriptHeaderLen + 1 + kScriptSigLen) return fail(err, "envelope too small");
  if (memcmp(blob, "LCLW", 4) != 0) return fail(err, "bad envelope magic");
  if (blob[4] != kScriptFmtVersion) return fail(err, "bad envelope version");
  if (blob[38] != 0) return fail(err, "bad envelope flags");
  const char *mode = modeName(blob[37]);
  if (!mode) return fail(err, "bad script mode");
  const uint32_t every = getLe32(blob + 39);
  const uint32_t len = getLe32(blob + 43);
  const uint32_t version = getLe32(blob + 47);
  if (every > 3600000u) return fail(err, "bad every_ms");
  if (version == 0) return fail(err, "bad script version");
  if (len == 0 || len > kScriptMaxSource) return fail(err, "bad script length");
  if (n != kScriptHeaderLen + len + kScriptSigLen) return fail(err, "envelope length mismatch");
  std::string name((const char *)blob + 5, kScriptNameLen);
  while (!name.empty() && name.back() == '\0') name.pop_back();
  if (!nameOk(name)) return fail(err, "bad script id");
  const uint8_t *content = blob + kScriptHeaderLen;
  const uint8_t *sig = content + len;
  uint8_t dig[32];
  scriptSha256(content, len, dig);
  if (memcmp(dig, blob + 51, 32) != 0) return fail(err, "sha256 mismatch");
  if (!ed25519Verify(blob, kScriptHeaderLen + len, sig, pubkey))
    return fail(err, "signature mismatch");
  out.name = name;
  out.version = version;
  out.mode = mode;
  out.everyMs = every;
  out.source.assign((const char *)content, len);
  return true;
}

bool scriptStoreAccept(ScriptStoreIo &io, const uint8_t *blob, size_t n, const uint8_t pubkey[32],
                       std::string &err) {
  ScriptImage img;
  if (!scriptEnvelopeOpen(blob, n, pubkey, img, err)) return false;
  Index idx;
  bool present = false;
  if (!loadIndex(io, idx, present, err)) {
    // A signed deploy replaces a corrupt index. A read error does not.
    if (err == "index read failed") return false;
    idx = Index{};
    err.clear();
  }
  const std::string path = blobPath(img.name, img.version);
  if (!publishNew(io, path, blob, n, err)) return false;
  dropOtherScripts(io, idx, img.name);
  Slot &slot = idx.scripts[img.name];
  bool found = false;
  for (Ver &ver : slot.versions) {
    if (ver.v == img.version) {
      ver.ok = true;
      found = true;
    }
  }
  if (!found) slot.versions.push_back(Ver{img.version, true});
  pruneVersions(io, img.name, slot);
  idx.active = img.name;
  idx.run = true;
  idx.safe = false;
  return saveIndex(io, idx, err);
}

ScriptPick scriptStorePick(ScriptStoreIo &io, const uint8_t pubkey[32], ScriptImage &out,
                           std::string &err) {
  out = ScriptImage{};
  Index idx;
  bool present = false;
  if (!loadIndex(io, idx, present, err)) {
    if (err == "index corrupt") return ScriptPick::SafeMode;
    return ScriptPick::IoError;
  }
  if (!present) return ScriptPick::Empty;
  if (!idx.run) return ScriptPick::Stopped;
  auto it = idx.scripts.find(idx.active);
  if (it == idx.scripts.end()) {
    idx.safe = true;
    if (!saveIndex(io, idx, err)) return ScriptPick::IoError;
    return ScriptPick::SafeMode;
  }
  sortDesc(it->second.versions);
  bool changed = false;
  for (Ver &ver : it->second.versions) {
    if (!ver.ok) continue;
    const std::string path = blobPath(idx.active, ver.v);
    if (!ioExists(io, path)) {
      ver.ok = false;
      changed = true;
      continue;
    }
    std::string raw;
    if (!io.read || !io.read(io.ctx, path.c_str(), raw)) return ScriptPick::IoError;
    ScriptImage img;
    std::string why;
    if (!scriptEnvelopeOpen((const uint8_t *)raw.data(), raw.size(), pubkey, img, why) ||
        img.name != idx.active || img.version != ver.v) {
      ver.ok = false;
      changed = true;
      continue;
    }
    if (changed || idx.safe) {
      idx.safe = false;
      if (!saveIndex(io, idx, err)) return ScriptPick::IoError;
    }
    out = img;
    return ScriptPick::Ready;
  }
  idx.safe = true;
  if (!saveIndex(io, idx, err)) return ScriptPick::IoError;
  err = "no valid script version";
  return ScriptPick::SafeMode;
}

bool scriptStoreMarkBad(ScriptStoreIo &io, const char *name, uint32_t version, std::string &err) {
  if (!name || !nameOk(name) || version == 0) return fail(err, "bad version");
  Index idx;
  bool present = false;
  if (!loadIndex(io, idx, present, err)) return false;
  if (!present) return fail(err, "no index");
  auto it = idx.scripts.find(name);
  if (it == idx.scripts.end()) return fail(err, "script not stored");
  bool found = false;
  for (Ver &ver : it->second.versions) {
    if (ver.v == version) {
      ver.ok = false;
      found = true;
    }
  }
  if (!found) return fail(err, "version not stored");
  return saveIndex(io, idx, err);
}

bool scriptStoreSetRun(ScriptStoreIo &io, bool run, std::string &err) {
  Index idx;
  bool present = false;
  if (!loadIndex(io, idx, present, err)) return false;
  if (!present) return fail(err, "no index");
  idx.run = run;
  if (!run) idx.safe = false;
  return saveIndex(io, idx, err);
}

bool scriptStoreView(ScriptStoreIo &io, ScriptStoreView &out) {
  out = ScriptStoreView{};
  Index idx;
  bool present = false;
  std::string err;
  if (!loadIndex(io, idx, present, err) || !present) return present ? false : true;
  out.run = idx.run;
  out.safeMode = idx.safe;
  out.name = idx.active;
  auto it = idx.scripts.find(idx.active);
  if (it != idx.scripts.end()) {
    for (const Ver &ver : it->second.versions) {
      if (ver.ok && ver.v > out.version) out.version = ver.v;
    }
  }
  return true;
}
