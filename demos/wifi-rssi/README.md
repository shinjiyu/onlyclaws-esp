# Demo：本地 Wi‑Fi 质量曲线

只读板载 `net.rssi()`，**不发起 HTTP / emit**，避免拖垮已经很差的办公网。

- 4 秒采一个点，环形缓冲约 6 分钟
- RLCD 约 12 秒刷一帧；ePaper 约 30 秒（局刷）
- 大字当前 dBm + GOOD/OK/WEAK/BAD，下面一条 RSSI 历史折线（-35 ~ -90）
