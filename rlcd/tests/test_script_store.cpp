// Host checks for the signed LittleFS script store: envelope layout, Ed25519
// reject-before-write, .tmp + rename, power loss, and rollback. argv:
//   (none)            run the cases below
//   <pubkey> <blob>   verify one envelope and print "ok <id> <version>"

#include <stdio.h>
#include <string.h>

#include <map>
#include <string>
#include <vector>

#include "script_store.h"

extern "C" {
int crypto_sign_ed25519_tweet(unsigned char *sm, unsigned long long *smlen, const unsigned char *m,
                              unsigned long long n, const unsigned char *sk);
int crypto_sign_ed25519_tweet_keypair(unsigned char *pk, unsigned char *sk);
void randombytes(unsigned char *x, unsigned long long xlen) {
  for (unsigned long long i = 0; i < xlen; ++i) x[i] = (unsigned char)(0xA5 ^ (i * 17u));
}
}

static int gFailures = 0;
static unsigned char gPk[32];
static unsigned char gSk[64];

#define CHECK(cond)                                                                 \
  do {                                                                              \
    if (!(cond)) {                                                                  \
      fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);             \
      ++gFailures;                                                                  \
    }                                                                               \
  } while (0)

static void initKey() {
  static bool ready = false;
  if (ready) return;
  CHECK(crypto_sign_ed25519_tweet_keypair(gPk, gSk) == 0);
  ready = true;
}

struct Mem {
  std::map<std::string, std::string> files;
  int failRenames = 0;
  std::string failRenameIf;
  bool corruptTmpRead = false;

  static Mem *self(void *ctx) { return (Mem *)ctx; }

  static bool exists(void *ctx, const char *path) { return self(ctx)->files.count(path) != 0; }

  static bool read(void *ctx, const char *path, std::string &out) {
    Mem *m = self(ctx);
    auto it = m->files.find(path);
    if (it == m->files.end()) return false;
    out = it->second;
    if (m->corruptTmpRead && std::string(path).size() >= 4 &&
        std::string(path).rfind(".tmp") == std::string(path).size() - 4 && !out.empty()) {
      out.back() = (char)(out.back() ^ 0x01);
      m->corruptTmpRead = false;
    }
    return true;
  }

  static bool write(void *ctx, const char *path, const uint8_t *data, size_t n) {
    self(ctx)->files[path].assign((const char *)data, n);
    return true;
  }

  static bool rename(void *ctx, const char *from, const char *to) {
    Mem *m = self(ctx);
    if (m->failRenames > 0 && (m->failRenameIf.empty() || std::string(from).find(m->failRenameIf) != std::string::npos)) {
      --m->failRenames;
      return false;
    }
    auto it = m->files.find(from);
    if (it == m->files.end()) return false;
    m->files[to] = it->second;
    m->files.erase(it);
    return true;
  }

  static bool remove(void *ctx, const char *path) {
    self(ctx)->files.erase(path);
    return true;
  }

  ScriptStoreIo io() {
    return ScriptStoreIo{&exists, &read, &write, &rename, &remove, this};
  }
};

static std::string blobFor(const char *id, uint32_t version, const char *mode, uint32_t every,
                           const char *source) {
  initKey();
  ScriptImage in;
  in.name = id;
  in.version = version;
  in.mode = mode;
  in.everyMs = every;
  in.source = source;
  std::string prefix;
  std::string err;
  CHECK(scriptEnvelopePrefix(in, prefix, err));
  std::string sm(prefix.size() + 64, '\0');
  unsigned long long slen = 0;
  CHECK(crypto_sign_ed25519_tweet((unsigned char *)&sm[0], &slen, (const unsigned char *)prefix.data(),
                                  prefix.size(), gSk) == 0);
  CHECK(slen == prefix.size() + 64);
  return prefix + sm.substr(0, 64);
}

static bool fileHas(const Mem &m, const std::string &path) { return m.files.count(path) != 0; }

static void testSha256() {
  uint8_t d[32];
  scriptSha256((const uint8_t *)"", 0, d);
  static const uint8_t empty[32] = {0xe3, 0xb0, 0xc4, 0x42, 0x98, 0xfc, 0x1c, 0x14, 0x9a, 0xfb, 0xf4,
                                     0xc8, 0x99, 0x6f, 0xb9, 0x24, 0x27, 0xae, 0x41, 0xe4, 0x64, 0x9b,
                                     0x93, 0x4c, 0xa4, 0x95, 0x99, 0x1b, 0x78, 0x52, 0xb8, 0x55};
  CHECK(memcmp(d, empty, 32) == 0);
  const char *abc = "abc";
  scriptSha256((const uint8_t *)abc, 3, d);
  static const uint8_t abcDig[32] = {0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40,
                                      0xde, 0x5d, 0xae, 0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17,
                                      0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad};
  CHECK(memcmp(d, abcDig, 32) == 0);
}

static void testRejectBeforeWrite() {
  initKey();
  Mem mem;
  ScriptStoreIo io = mem.io();
  std::string blob = blobFor("abc", 1, "loop", 1000, "print(1)\n");
  blob[80] ^= 0x01;
  std::string err;
  CHECK(!scriptStoreAccept(io, (const uint8_t *)blob.data(), blob.size(), gPk, err));
  CHECK(err == "signature mismatch" || err == "sha256 mismatch");
  CHECK(mem.files.empty());

  blob = blobFor("abc", 1, "loop", 1000, "print(1)\n");
  unsigned char other[32];
  memset(other, 0x11, sizeof(other));
  CHECK(!scriptStoreAccept(io, (const uint8_t *)blob.data(), blob.size(), other, err));
  CHECK(mem.files.empty());

  ScriptImage bad;
  CHECK(!scriptEnvelopeOpen((const uint8_t *)blob.data(), 10, gPk, bad, err));
}

static void testAcceptPickAndStop() {
  Mem mem;
  ScriptStoreIo io = mem.io();
  std::string err;
  const std::string blob = blobFor("abcd", 1, "once", 250, "function on_start() end\n");
  CHECK(scriptStoreAccept(io, (const uint8_t *)blob.data(), blob.size(), gPk, err));
  CHECK(fileHas(mem, "s/abcd.1"));
  CHECK(fileHas(mem, "s/index.json"));
  CHECK(!fileHas(mem, "s/abcd.1.tmp"));

  ScriptImage img;
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
  CHECK(img.name == "abcd" && img.version == 1 && img.mode == "once" && img.everyMs == 250);
  CHECK(img.source == "function on_start() end\n");

  CHECK(scriptStoreSetRun(io, false, err));
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Stopped);
  CHECK(fileHas(mem, "s/abcd.1"));
  CHECK(scriptStoreSetRun(io, true, err));
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
}

static void testPowerLossAndReadback() {
  Mem mem;
  ScriptStoreIo io = mem.io();
  std::string err;
  const std::string v1 = blobFor("abcd", 1, "loop", 1000, "v1");
  CHECK(scriptStoreAccept(io, (const uint8_t *)v1.data(), v1.size(), gPk, err));

  mem.failRenames = 1;
  const std::string v2 = blobFor("abcd", 2, "loop", 1000, "v2");
  CHECK(!scriptStoreAccept(io, (const uint8_t *)v2.data(), v2.size(), gPk, err));
  CHECK(!fileHas(mem, "s/abcd.2"));
  CHECK(!fileHas(mem, "s/abcd.2.tmp"));
  ScriptImage img;
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
  CHECK(img.version == 1 && img.source == "v1");

  // Version file landed, index rename did not. The next accept of the same
  // bytes adopts it.
  mem.failRenames = 1;
  mem.failRenameIf = "index.json.tmp";
  CHECK(!scriptStoreAccept(io, (const uint8_t *)v2.data(), v2.size(), gPk, err));
  CHECK(fileHas(mem, "s/abcd.2"));
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
  CHECK(img.version == 1);
  mem.failRenameIf.clear();
  CHECK(scriptStoreAccept(io, (const uint8_t *)v2.data(), v2.size(), gPk, err));
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
  CHECK(img.version == 2 && img.source == "v2");

  mem.corruptTmpRead = true;
  const std::string v3 = blobFor("abcd", 3, "loop", 1000, "v3");
  CHECK(!scriptStoreAccept(io, (const uint8_t *)v3.data(), v3.size(), gPk, err));
  CHECK(err == "read-back mismatch");
  CHECK(!fileHas(mem, "s/abcd.3"));
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
  CHECK(img.version == 2);
}

static void testRollbackAndKeepThree() {
  Mem mem;
  ScriptStoreIo io = mem.io();
  std::string err;
  for (uint32_t v = 1; v <= 4; ++v) {
    const std::string src = "v" + std::to_string(v);
    const std::string blob = blobFor("abcd", v, "loop", 1000, src.c_str());
    CHECK(scriptStoreAccept(io, (const uint8_t *)blob.data(), blob.size(), gPk, err));
  }
  CHECK(!fileHas(mem, "s/abcd.1"));
  CHECK(fileHas(mem, "s/abcd.2") && fileHas(mem, "s/abcd.4"));

  // Switching script id drops the previous script's files.
  const std::string other = blobFor("ef01", 1, "loop", 1000, "other");
  CHECK(scriptStoreAccept(io, (const uint8_t *)other.data(), other.size(), gPk, err));
  CHECK(!fileHas(mem, "s/abcd.4"));
  CHECK(fileHas(mem, "s/ef01.1"));
  for (uint32_t v = 2; v <= 3; ++v) {
    const std::string src = "o" + std::to_string(v);
    const std::string blob = blobFor("ef01", v, "loop", 50, src.c_str());
    CHECK(scriptStoreAccept(io, (const uint8_t *)blob.data(), blob.size(), gPk, err));
  }

  mem.files["s/ef01.3"] = "garbage";
  ScriptImage img;
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
  CHECK(img.version == 2 && img.source == "o2");

  CHECK(scriptStoreMarkBad(io, "ef01", 2, err));
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
  CHECK(img.version == 1 && img.source == "other");
  CHECK(scriptStoreMarkBad(io, "ef01", 1, err));
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::SafeMode);

  ScriptStoreView view;
  CHECK(scriptStoreView(io, view));
  CHECK(view.safeMode && view.name == "ef01");
}

static void testIndexBackup() {
  Mem mem;
  ScriptStoreIo io = mem.io();
  std::string err;
  const std::string blob = blobFor("abcd", 1, "loop", 1000, "stay");
  CHECK(scriptStoreAccept(io, (const uint8_t *)blob.data(), blob.size(), gPk, err));
  mem.files["s/index.json.bak"] = mem.files["s/index.json"];
  mem.files.erase("s/index.json");
  ScriptImage img;
  CHECK(scriptStorePick(io, gPk, img, err) == ScriptPick::Ready);
  CHECK(img.source == "stay");
  CHECK(fileHas(mem, "s/index.json"));
  CHECK(!fileHas(mem, "s/index.json.bak"));
}

static int verifyFiles(const char *pubPath, const char *blobPath) {
  FILE *pf = fopen(pubPath, "rb");
  FILE *bf = fopen(blobPath, "rb");
  if (!pf || !bf) {
    fprintf(stderr, "open failed\n");
    if (pf) fclose(pf);
    if (bf) fclose(bf);
    return 2;
  }
  std::string pub(32, '\0');
  std::string blob;
  if (fread(&pub[0], 1, 32, pf) != 32) {
    fprintf(stderr, "pubkey\n");
    fclose(pf);
    fclose(bf);
    return 2;
  }
  char buf[1024];
  size_t n = 0;
  while ((n = fread(buf, 1, sizeof(buf), bf)) > 0) blob.append(buf, n);
  fclose(pf);
  fclose(bf);
  ScriptImage img;
  std::string err;
  if (!scriptEnvelopeOpen((const uint8_t *)blob.data(), blob.size(), (const uint8_t *)pub.data(), img,
                          err)) {
    fprintf(stderr, "%s\n", err.c_str());
    return 1;
  }
  printf("ok %s %u\n", img.name.c_str(), (unsigned)img.version);
  return 0;
}

int main(int argc, char **argv) {
  if (argc == 3) return verifyFiles(argv[1], argv[2]);
  testSha256();
  testRejectBeforeWrite();
  testAcceptPickAndStop();
  testPowerLossAndReadback();
  testRollbackAndKeepThree();
  testIndexBackup();
  if (gFailures) {
    fprintf(stderr, "%d failure(s)\n", gFailures);
    return 1;
  }
  printf("ok\n");
  return 0;
}
