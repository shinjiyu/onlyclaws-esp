/* TweetNaCl for the firmware link. randombytes is only used by keypair,
   which the device never calls; signing keys live on the control plane. */
#include <string.h>

void randombytes(unsigned char *x, unsigned long long xlen) {
  memset(x, 0, (size_t)xlen);
}

#include "../third_party/tweetnacl/tweetnacl.c"
