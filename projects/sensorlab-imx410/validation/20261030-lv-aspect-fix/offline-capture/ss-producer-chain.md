# Native screenshot producer and JPEG layout, offline follow-up

2026-10-30. No USB or camera operations. This is additional evidence for the
**unaccepted** v0.7.3 test; it does not establish that the physical LCD is correct.
The previous live note's C042F990/C04A6B20 candidates are not needed for this chain.

## Confirmed chain from the named screenshot events

All addresses are fp Ver.5.02 RAM addresses. `out/seg0_c0000000.bin` supplies code;
`out/seg1_c2ef6e00.bin` must overlay C2EF6E00 for initialized runtime tables.
Reading MAIN alone at C2F1Fxxx returns inappropriate compressed/uninitialized data.
`trace_ss_producer.py` records the image hashes, exact table words and original
instruction slices in `ss-producer-evidence.json`.

1. C03AD288 indexes the event-name pointer table at **C2F1FA78**. Entries 0x18 and
   0x19 are respectively C0B9FD5A `INTR_REC_SCREENSHOT` and C0B9FD6E
   `INTR_REC_SCREENSHOT_SAVE_FILE`.
2. The CameraFunc dispatch table **C0B9E034**, 16 bytes per entry, maps those
   event IDs to **C03A1F78** and **C03A1FE0**. These functions are absent from the
   exported C decompilation, so the attached evidence uses raw ARM instructions.
   Each constructs a zeroed 0x168-byte worker request, with the event ID at +4.
   C03A1F78 copies CameraFunc payload +10/+11/+14 to request +15C/+15D/+160;
   C03A1FE0 copies +11/+14 to +15D/+160. Both call **C0388990 → C03A9558**.
3. C0388990 returns the XC_MovRecFunc singleton **C358CB80**. C03A9558/C03A9580
   copies and queues the request. Worker **C03889E0** dispatches via **C038ACA8**.
   The initialized table rows **C2F1F724** and **C2F1F734** select **C03AB638**
   and **C03AB670**, forwarding through the current state object's vtable +48
   and +4C. In normal standby states these resolve to **C03ABDD8** and
   **C03ABE08** (StateCommon v16/v17).
4. C03ABDD8 calls **C03833B8** with request +15C/+15D. C03ABE08 calls
   **C03836D0** with request +15D/+160. REC/RECSTART states have different
   screenshot handlers; this follow-up concerns standby.

## Fixed screenshot allocation and the actual producer

**C03833B8** (decomp `out/decomp/full/blk_c03.c:88673`) obtains the screenshot
pair from **C0388668**, which returns **C0B9BA00 = {1024,682}**. It calls:

```
C0046030(rect, C0B9BA00)
    rect = [1024,682, 0,0, 1024,682]
C02E5C10(desc, rect, 0,0,0)
    desc[+00/+04] full W/H = 1024/682
    desc[+08/+0C] origin = 0/0
    desc[+10/+14] active W/H = 1024/682
    desc[+1C] buffer address initially 0
    desc[+24] tiled flag = 0; desc[+28] explicit size = 0
C02DA6E0(desc) = 1024*682*2 = 1,396,736 bytes
```

The descriptor is copied to the StillRecFunc singleton **C3588D74**, at
`+F4 + n*3C`, where count `n` is at +220 and must be below 5. The allocation
record is at descriptor +30. C03833B8 sets descriptor **+1C** from allocation
record +00, then calls **C0383910** to fill that allocation. Thus the pixel
address is a runtime allocation, not a fixed ROM address.

**C0383910** (blk_c03.c:88923) selects the display object through
C02E4128/C02E44B0/C02E44D0 and checks C02E4A50. In the zero branch it calls
**C02E8F20(selected_display, screenshot_desc)** directly. The alternate branch
first captures an intermediate descriptor and then converts it with
C0387C20/C0427540; the active runtime branch was not sampled during the live
trial. C02E8F20 ignores its first argument and dispatches through the singleton
from **C0306C18**, whose stored vtable is **C0B54CD0**; slot +0C is
**C0306B60**, XC_DisplayWriteBackW71C1 v1.

C0306B60 (blk_c03.c:5229) reads the current display output state with
C02E5DE0/C02E9D58 and copies it with C0306C68. It enables writeback with
C02F3BA8, selecting the alternate display ID 1 when C02EA040 says so. The only
geometry-bearing argument sent to **C02F3B80 → C00EAD70** is:

```
{ selected_display_id, screenshot_desc[+1C] }
```

**No screenshot W/H, origin, capacity or row stride is passed to this driver.**
C00EAD70 derives its own W/H through **C00DE5C8/C00DE630**. For the normal
registered output branch the source of those dimensions is:

```
C31D60A0 callback → C00FB090 → registry at C31D718C
  → registered object +14 = output
  → output +48 → object +04 → {W,H}
```

The actual callback is initialized by C00FA778. C00DE630 also permits a
registered height-adjustment callback at C31D2534; the fixture explicitly
declares that callback absent. Fallback size tables are C07C75B8/C07C76AC.

C00EAD70 builds a private 0x70-byte driver request:

| Offset | Value |
| --- | --- |
| +00 | mapped display ID, C00DEA98 |
| +04/+08 | current display W/H, C00DE5C8/C00DE630 |
| +0C | 1 plane |
| +10 | `(destination_address - 0x40000000) >> 2` |

It clears **W*H*2 bytes**, using native **C00E23D0 → C00DB278**. After display
suspension it calls **C00E22A0 → C00EB290**. C00EB290 **re-reads** W/H through
the same native getters, overwrites request +04/+08, and packs:

| Writeback packet field | Actual register | Value |
| --- | --- | --- |
| +04 | 30193010 | height |
| +08 | 30193014 | signed `(width*2)/4`, stride in words |
| +18 | 30193080 | destination address in words |

**C00EAEF8** performs those register writes. C00E22C8 requests the hardware
trigger; no CPU source-pixel pointer is supplied on this path. The source is
the selected display hardware pipeline. This is not proof of LCD scanout.

## JPEG consumer and filename boundary

C03836D0 loops the saved screenshot descriptors through **C0383AA0**
(blk_c03.c:88993). It temporarily installs the screenshot size as image
metadata through **C03884F8**. It obtains an image DB entry with
**C0398860(0xC, ...) → C0374268**, then **C0376B98** reserves names. It attaches
the same saved screenshot pointer to JPEG image 0 using:

```
C0698FF8(DB[+138]) → primary format object
C0699250(format, saved_desc[+1C], 0)
    → format vtable +5C gives descriptor array
    → descriptor0[+1C] = saved screenshot allocation
```

The 160×120 thumbnail conversion is separate. JPEG creation proceeds through
**C0387AD8 → C037D5C8 → worker C0377150 → C037D8F0 → C04247B0 → C04247E8**.
C04247E8 obtains descriptor0 with **C0699288**, then calls **C042E6C8** and
**C042E7E8**. **C042EAD0** copies that descriptor's source address/full W/H and
active rectangle into the compressor request. **C042EC90** passes those fixed
dimensions and the same source address to **C01AA888**, then C01AF740 queues
the JPEG engine operation. JPEG therefore consumes the image descriptor's
W/H; it does not consult C00EB290's possibly different writeback stride.

The exact `SS__` prefix-generation implementation remains unresolved. The
concrete next callsite is **C0376B98 → filename provider virtual +18 → returned
name generator virtual +0C**, called with **C0B9991C = "JPG"**; the returned
0x30-byte filename is copied to DB +1000. C03092F8 selects the provider.
Later C037E0F8 creates/writes that file and calls ImageSave. C069F8D8's
case-insensitive test against C2E399EE `SS__` is only a filename classifier.
There was no additional unbounded string/xref search after this boundary.

The DB/format object plumbing above is a static source trace, not a fully
executed screenshot-to-file fixture. No JPEG bitstream or pixel DMA is emulated.

## Native fixture result and limits

`test_ss_writeback.py --json` passed **6 sensitivity cases plus 5 observed-period
hypotheses**, writing
`ss-writeback-native.json`. The fixed size pair, rectangle/descriptor creation,
allocation-size arithmetic, all driver W/H getters, clear length, writeback
register packet, and JPEG geometry handoff execute actual ROM instructions.
Only **C00E23A8 display suspend** returns declared success; the fixture stops
before **C00E22C8 DMA trigger**, and before **C01AA888 JPEG engine entry**.
There are **no geometry/size/stride arithmetic stubs**. Runtime registry,
display dimensions and descriptor object attachment are explicit fixtures.

| Declared display size | SS allocation bytes | Native clear bytes | Native row stride bytes | JPEG size |
| --- | ---: | ---: | ---: | --- |
| 1024×682 | 1,396,736 | 1,396,736 | 2048 | 1024×682 |
| 1024×642 | 1,396,736 | 1,314,816 | 2048 | 1024×682 |
| 1024×591 | 1,396,736 | 1,210,368 | 2048 | 1024×682 |
| 862×682 | 1,396,736 | 1,175,768 | 1724 | 1024×682 |
| 852×682 | 1,396,736 | 1,162,128 | 1704 | 1024×682 |
| 814×682 | 1,396,736 | 1,110,296 | 1628 | 1024×682 |

**Inference:** when the selected display state really has a changed size,
the direct native screenshot branch can write/clear fewer rows or a different
packed row width than the fixed JPEG descriptor expects. This supplies a
specific screenshot-layout mismatch mechanism for stale bottom rows and
row misinterpretation. It does not establish the live trial's runtime branch,
exact getter values, pixel content, or whether the LCD has a separate defect.
The declared test sizes are sensitivity examples, not hardware measurements.
The additional hypotheses are W860/852/812 at H682 and H643/592 at W1024,
matching observed RGB periods for sensitivity testing; no native getter value
was measured for them. The fixture does not execute pixel DMA or the JPEG
encoder, so it does **not** reproduce RGB wrapping or establish its exact cause.

The native fixture maps a zero-filled C0000000..C3000000 region, copies the
MAIN prefix, then overlays seg1 at C2EF6E00. Its JSON records the SHA-256 of
that **complete mapped byte sequence**, the raw MAIN prefix and seg1. The
static trace script additionally overlays seg0 for table/disassembly evidence;
these two provenance descriptions are intentionally explicit.
