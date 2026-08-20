# FPSH protocol v1

All integer fields are little-endian. The logical frame is exactly 64 bytes.
For the current v29 transport it occupies bytes 0–63 of a zero-padded
1024-byte EP05 OUT transfer; EP84 IN returns the 64-byte frame.

| Offset | Size | Field | Meaning |
|---:|---:|---|---|
| 0 | 4 | magic | ASCII `FPSH` |
| 4 | 1 | version | `1` |
| 5 | 1 | command | `1` PING, `2` ECHO |
| 6 | 2 | flags | reserved, zero |
| 8 | 4 | sequence | daemon-assigned monotonic request number |
| 12 | 2 | payload_length | 0–44 bytes |
| 14 | 2 | status | zero for success |
| 16 | 4 | checksum | IEEE CRC32 of all 64 bytes with this field zeroed |
| 20 | 44 | payload | command data; unused bytes are zero |

The receiver must reject an invalid magic, version, length, CRC, command, or
sequence. A nonzero response status is a camera-side error. Sequence numbers
are allocated only to USB requests; `STATUS` and `INFO` are daemon-local.

The Unix socket protocol is deliberately separate and line-based:
`STATUS`, `INFO`, `PING`, `ECHO text`, and `QUIT`. Each connection carries one
request and one newline-terminated response. `fpshelld` serializes clients and
is the only process permitted to own interface 1.

At present the camera AutoRun echoes bytes and does not independently parse
FPSH. Host validation already establishes the envelope needed for a future
camera dispatcher without changing agent-facing clients.
