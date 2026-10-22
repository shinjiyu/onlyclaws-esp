# TweetNaCl

Public-domain NaCl implementation by Daniel J. Bernstein, Bernard van Gastel,
Wesley Janssen, Tanja Lange, Peter Schwabe, and Sjaak Smetsers.

Source: https://tweetnacl.cr.yp.to/20140427/tweetnacl.c and `tweetnacl.h`
(2014-04-27). The firmware uses `crypto_sign_ed25519_tweet_open` to check
script envelopes.

`u32` is `uint32_t` instead of `unsigned long`. TweetNaCl's field arithmetic
needs a 32-bit `u32`, and `unsigned long` is 64 bits on LP64 hosts. `u64`
stays `unsigned long long` so it still matches `tweetnacl.h`.
