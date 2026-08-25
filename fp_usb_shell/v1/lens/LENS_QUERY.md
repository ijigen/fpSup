# L-mount lens register query over USB

Actively query the attached lens's own register space over the USB vendor shell —
not just what the camera stores, but a direct read of the lens's serial memory. This
reuses the camera's own lens-comm function, so it speaks the real 4-wire L-mount protocol.

## The ABI (reverse-engineered)

```
CmdRead(lens_mgr, lens_addr, len, dest_buf, flag)   @0xC0355BE0  (ARM)
  → reads `len` bytes from the lens's 24-bit register/address space at `lens_addr`
    into dest_buf, chunking at 0xFF bytes/transaction.
```

- **lens_mgr = `0xC347CB14`** (fixed). Its `+0xec` field holds the live serial context
  (`0xC347D1C0` on the test body); that context's command buffer `+0x34` and response
  buffer `+0x143` both carry the `"LDAFR"` header of the L-mount protocol.
- Underneath: `CmdRead → cmdReadMain @0xC0357188 → cmdSend(4)=addr+len, cmdRead(0)=data`,
  packet built by `FUN_c035a030(ctx, cmd_byte, payload)` = `"LDAFR"(5) + 0x00 + cmd + 8B + checksum`,
  sent by `CommPacket @0xC035A1D8` / `commSerial @0xC0359DD0`.

## Usage

`lens_read.S` is a tiny position-independent ARM stub that calls `CmdRead` with args
from a scratch cell; it is injected into the worker cave via `mem set` and invoked with
`call` — no AutoRun reflash. `lens_probe.py` drives it:

```python
from lens_probe import LensProbe
lp = LensProbe()
ret, data = lp.read(0x000000, 16)     # read 16 bytes at lens register 0
```

## Sample dump (test body, registers 0x000–0x0BF0)

See `lens_registers_sample.json`. Highlights:

| register | bytes | note |
|---|---|---|
| `0x0000` | `02 00 02 52 00 00 00 a0 02 05 02 00 00 78` | lens ID / version block |
| `0x0200` | `01 01 01 00 02 00 09 00 01 90 …` | lens parameters (0x190=400, 0x12c=300, …) |
| `0x0400` | `00 00 00 20 0f ff … 0e ca` | 0x0fff=4095 (a max?), 0x0eca=3786 |
| `0x0500` | all-zero block | table area (may need a query cmd to fill) |
| most others | `0xFF` | unused register |

## ⚠️ Hazard — do NOT blind-scan

Reading an address the lens does **not** ACK (e.g. `0x1000`) makes `cmdReadMain` retry
~2500× **and wedges the lens↔body serial bus itself**. Once wedged, every lens read hangs
(even valid ones) and the worker blocks; a USB re-plug does **not** clear it — only a
camera cold-boot does. So read **only known-valid registers** (a whitelist), never a
free sweep. The safe scanner in this folder uses a short per-read timeout and stops on the
first hang, but the right answer is a register whitelist from the L-mount protocol.

Firmware EAs: CmdRead `0xC0355BE0`, cmdReadMain `0xC0357188`, CommPacket `0xC035A1D8`,
commSerial `0xC0359DD0`, packet builder `FUN_c035a030`, lens_mgr `0xC347CB14`,
serial ctx `*(0xC347CB14+0xec)`.
