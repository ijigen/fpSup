.syntax unified
.arm
.text
/* Persistent base-shell worker for the SHARED USB test interface.
 *
 * A standing service: created at boot via the gyro one-shot hook, blocks on GO (set by AutoRun after
 * `echo`), then LOOPS FOREVER serving one FPSH command per round over EP05 OUT / EP84 IN. Multiple
 * agents share it through fpshelld (which owns interface 1 and enforces the session lease); the camera
 * side stays simple and just executes the serialized commands it receives.
 *
 * Commands (shell syntax; worker parses — does NOT call the firmware shell dispatcher):
 *   mem set  <hexaddr> <hexval>   write, addr word-aligned + in tight scratch [WR_LO,WR_HI]; ack=echo
 *   mem read <hexaddr> <declen>   len 1..44, addr..addr+len in mapped [RD_LO,RD_HI); reply=data+CRC32
 * Hardened: each numeric token needs >=1 digit and a space/NUL terminator; else it is rejected (no
 * write/read). Bounded ranges cap blast radius. On any OUT/IN arm/wait error or OUT-wait timeout the
 * worker just re-arms and keeps serving (never permanently parks) — it is a standing service.
 *
 * Coherency: received command read via UNCACHED raw_buf+0x40000000; reply built there too, with a DSB
 * before EP84 IN StartTransfer; TRB stays raw_buf+0xC0000000. Never call FUN_c000ea54.
 *
 * State 0xC072F000 (readback 0x80):
 *   [0]0x42 [4]id [8]start [12]'WORK' [16]GO
 *   [20]last OUT arm [24]last OUT wait [28]last IN arm [32]last IN wait [36]last marker
 *   [40]pre-GO hb [44]stage
 *   [48]last result(1 badcmd/2 range/3 set-ok/4 read-ok/5 malformed) [52]addr [56]val/len
 *   [0x58]fault count [0x5C]command-id (commands served) [0x60..0x7C]write scratch
 */

.equ STATE,     0xC072F000
.equ HOOK,      0xC00D0794
.equ HOOK_ORIG, 0xFA046FD7
.equ ACCESSOR,  0xC01EC6F9
.equ FN_CRETSK, 0xC0016A58
.equ FN_STATSK, 0xC0016BC0
.equ FN_DLY,    0xC01F89C4
.equ FN_ENDX,   0xC01E6D49
.equ FN_STARTX, 0xC01E6B81
.equ FN_WAIT,   0xC01E4E81
.equ BUF_PTR,   0xC3757A7C
.equ CTX5_TBL,  0xC31E3278
.equ CTX4_TBL,  0xC31E3274
/* idle-gate: re-arm EPs only when the USB gadget is configured & idle (survives record-start).
 * HW-validated in normal serving: USB_STATE==2, USB_EPMASK==0, USB_LINK==1. FUN_c01e40d0 accepts state>=2. */
.equ USB_STATE, 0xC31E3748
.equ USB_EPMASK,0xC31E3900
.equ USB_LINK,  0xC31E396C
/* USB-connect admission gate: movie-recording flag = FUN_c035b2d0()+0x157. !=0 => recording in progress;
 * defer USB init until clear (mirrors firmware DelayableUsbConnectingObserver @0xC0498F40). Replaces the
 * fixed 30s formerly in AutoRun. */
.equ REC_FLAG,  0xC347E08F
/* Record-safe bootstrap (SysNoRemain observer): register an observer on the firmware's USB-connect
 * permission mask so it sets GO at the NATIVE release (recording exclusive lock clears), replacing the
 * AutoRun fixed 30s + unconditional endpoint-enable. */
.equ FN_SYSNOREMAIN, 0xC0017920   /* SysNoRemain(statusObj, mask, observerPtr) */
.equ FN_STATUSOBJ,   0xC00178D8   /* returns system-status object handle (0xC3033834) */
.equ FN_EPENABLE,    0xC01E62A9   /* FUN_c01e62a9(ep): endpoint-context enable (thumb) */
.equ USB_ADMIT_MASK, 0x00100080   /* firmware's own USB-connect-permission status mask */
.equ DALEPENA,       0x2100C720
.equ DALEPENA_SH,    0xC31E398C
.equ CTX4_MODE,      0xC31E38C8   /* ctx4 endpoint mode: registration forces it to 3; restore Bulk-IN 2
                                     before FUN_c01e62a9(4) (what the c32 echo-init did) */   /* DALEPENA shadow — set 0x600 here too so config-gated resync
                                     (HW=shadow) preserves our vendor endpoints across benign transitions */
.equ TRB_ARMED, 0x813
.equ WORKER_PRI, 0x1C
.equ TMO,       50000
.equ UNCACHED,  0x40000000
.equ CACHED,    0xC0000000
.equ WR_LO,     0xC072F060
.equ WR_HI,     0xC072F07C     /* inclusive last word start */
.equ RD_LO,     0xC0000000
.equ RD_HI,     0xC1000000     /* exclusive */
/* raw-push: arm EP84 with a big TRB from a DRAM address (for grabbing raw frames). */
.equ RAW_LO,    0x40000000     /* DRAM + aliases (raw buffers live in 0x4x/0x5x) */
.equ RAW_HI,    0x60000000
.equ RAW_CHUNK, 0x00FF0000     /* <= 24-bit TRB size max (~16MB) */
/* Code INJECTION cave: agents `mem set` code here then `call` it — so new dev never needs a new
   AutoRun. Isolated RAM above the worker/state; not firmware code. */
.equ INJ_LO,    0xC072F100
.equ INJ_HI,    0xC0730000
/* Full-shell-over-USB: forward received "shl <cmd>" to the firmware shell command executor with a
   capture sink, return captured output. Any of the 77 top commands + sub-commands run over USB. */
.equ FN_SHEXEC,   0xC03D9C20   /* FUN_c03d9c20(ctx, char* line): tokenize+dispatch+run */
.equ FN_SHPUSH,   0xC03D9AC0   /* FUN_c03d9ac0(ctx, sink): push output callback */
.equ FN_SHPOP,    0xC03D9B20   /* FUN_c03d9b20(ctx): pop output callback */
.equ FN_SHINIT,   0xC03D9A10   /* FUN_c03d9a10(ctx): one-time ctx init */
.equ SHELL_CTX,   0xC3756904   /* global shell context singleton (ctx[0]=output cb) */
.equ FN_VSNPRINTF,0xC0013F48   /* FUN_c0013f48(buf,size,fmt,va_list) */
.equ CAP_OFF,     0xC072F1F8   /* capture write offset (INJ cave word) */
.equ CAP_BUF,     0xC072F200   /* capture buffer (INJ cave) */
.equ CAP_SZ,      0x00000100   /* 256 bytes */

.global cave_entry
cave_entry:
    push    {r4, r5, r6, lr}
    movw    r12, #:lower16:ACCESSOR
    movt    r12, #:upper16:ACCESSOR
    blx     r12
    mov     r4, r0
    movw    r0, #:lower16:STATE
    movt    r0, #:upper16:STATE
    ldr     r1, [r0]
    cmp     r1, #0x42
    beq     cave_done
    mov     r1, #0x42
    str     r1, [r0]
    movw    r0, #:lower16:HOOK
    movt    r0, #:upper16:HOOK
    movw    r1, #:lower16:HOOK_ORIG
    movt    r1, #:upper16:HOOK_ORIG
    str     r1, [r0]
    sub     sp, sp, #32
    mov     r0, #0
    str     r0, [sp, #0]
    mov     r0, #0x41
    str     r0, [sp, #4]
    adr     r0, worker_entry
    str     r0, [sp, #8]
    mov     r0, #WORKER_PRI
    str     r0, [sp, #12]
    movw    r0, #0x2000
    str     r0, [sp, #16]
    movw    r0, #0x5250
    movt    r0, #0x424f
    str     r0, [sp, #20]
    movw    r0, #0x0045
    str     r0, [sp, #24]
    mov     r0, #0
    str     r0, [sp, #28]
    mov     r0, sp
    movw    r12, #:lower16:FN_CRETSK
    movt    r12, #:upper16:FN_CRETSK
    blx     r12
    add     sp, sp, #32
    movw    r5, #:lower16:STATE
    movt    r5, #:upper16:STATE
    str     r0, [r5, #4]
    cmp     r0, #0
    ble     cave_done
    mov     r1, #0
    movw    r12, #:lower16:FN_STATSK
    movt    r12, #:upper16:FN_STATSK
    blx     r12
    str     r0, [r5, #8]
    /* SysNoRemain observer registration DISABLED for first-bring-up isolation — the round_loop already
     * handles recording via the DALEPENA-0x600 + REC_FLAG gate; the observer was only an event-driven
     * wake for record-then-boot. Re-enable once the core (gate + shell-forward) is proven on hardware. */
    /* idle boot: set GO now if not recording (round_loop then gates on enumeration before enabling). */
    movw    r0, #:lower16:REC_FLAG
    movt    r0, #:upper16:REC_FLAG
    ldrb    r1, [r0]
    cmp     r1, #0
    bne     cave_done
    mov     r1, #1
    str     r1, [r5, #16]           @ GO = 1
cave_done:
    mov     r0, r4
    pop     {r4, r5, r6, pc}

/* --- SysNoRemain observer: object + vtable + notify (firmware invokes vtable[+0xc] only) --- */
.align 2
obs_notify:                         @ (r0=this, r1=changed_mask, r2=statusptr) -> latch GO, return
    movw    r0, #:lower16:STATE
    movt    r0, #:upper16:STATE
    mov     r1, #1
    str     r1, [r0, #16]           @ GO = 1 (worker's admission_gate is the REC_FLAG debounce)
    bx      lr
.align 2
obs_vtable:
    .word   0                       @ +0x00
    .word   0                       @ +0x04
    .word   0                       @ +0x08
    .word   0                       @ +0x0c -> patched to &obs_notify at register time
obs_object:
    .word   0                       @ +0x00 -> patched to &obs_vtable
    .word   0                       @ +0x04 unused by our notify

/* ================= persistent worker ================= */
worker_entry:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}
    movw    r4, #:lower16:STATE
    movt    r4, #:upper16:STATE
    movw    r0, #0x524b
    movt    r0, #0x574f
    str     r0, [r4, #12]            @ 'WORK'
wait_go:
    ldr     r0, [r4, #16]
    cmp     r0, #0
    bne     admission_gate
    ldr     r0, [r4, #40]
    add     r0, r0, #1
    str     r0, [r4, #40]
    mov     r0, #20
    movw    r12, #:lower16:FN_DLY
    movt    r12, #:upper16:FN_DLY
    blx     r12
    b       wait_go

/* USB-connect admission gate (runs ONCE after GO, before the first EP arm).
 * Defer while movie recording is active (REC_FLAG != 0) — this is the exact state the firmware's native
 * DelayableUsbConnectingObserver defers USB connect on. Require 3 consecutive clear reads (~200ms apart) to
 * skip the sub-second RECSTART->REC transient. FN_DLY yields the CPU; if recording never ends we keep
 * deferring (matching native admission), recoverable by reboot. Replaces the removed AutoRun 30s. */
admission_gate:
    mov     r7, #0                  @ consecutive-clear counter
ag_poll:
    movw    r0, #:lower16:REC_FLAG
    movt    r0, #:upper16:REC_FLAG
    ldrb    r1, [r0]
    str     r1, [r4, #36]           @ marker: last recording-flag read (host-visible)
    cmp     r1, #0
    bne     ag_busy
    add     r7, r7, #1
    cmp     r7, #3
    bge     round_loop              @ 3 clears -> round_loop; endpoint-enable happens THERE after the
                                    @ USB_STATE>=2 (enumerated) gate, so we never enable pre-enumeration
    b       ag_delay
ag_busy:
    mov     r7, #0                  @ recording -> reset consecutive counter
ag_delay:
    ldr     r0, [r4, #40]
    add     r0, r0, #1
    str     r0, [r4, #40]           @ heartbeat while deferring
    mov     r0, #200                @ ~200ms between polls
    movw    r12, #:lower16:FN_DLY
    movt    r12, #:upper16:FN_DLY
    blx     r12
    b       ag_poll

/* One-time endpoint bring-up (what AutoRun's `echo`/FUN_c01e62a9 used to do, now behind the admission
 * gate): enable EP84-IN(4) + EP05-OUT(5) + DALEPENA |= 0x600. One-shot via STATE+0x3C. */
ag_admitted:
    ldr     r0, [r4, #0x3C]
    cmp     r0, #0
    bne     round_loop              @ already brought up
    mov     r0, #1
    str     r0, [r4, #0x3C]
    movw    r0, #:lower16:CTX4_MODE
    movt    r0, #:upper16:CTX4_MODE
    mov     r1, #2
    str     r1, [r0]                @ restore ctx4 Bulk-IN mode 2 (registration forces mode 3)
    mov     r0, #4
    movw    r12, #:lower16:FN_EPENABLE
    movt    r12, #:upper16:FN_EPENABLE
    blx     r12                     @ FUN_c01e62a9(4)  EP84 IN
    mov     r0, #5
    movw    r12, #:lower16:FN_EPENABLE
    movt    r12, #:upper16:FN_EPENABLE
    blx     r12                     @ FUN_c01e62a9(5)  EP05 OUT
    movw    r0, #:lower16:DALEPENA
    movt    r0, #:upper16:DALEPENA
    ldr     r1, [r0]
    orr     r1, r1, #0x600
    str     r1, [r0]                 @ HW DALEPENA |= 0x600 (enable EP84/EP05)
    movw    r0, #:lower16:DALEPENA_SH
    movt    r0, #:upper16:DALEPENA_SH
    ldr     r1, [r0]
    orr     r1, r1, #0x600
    str     r1, [r0]                 @ shadow |= 0x600 (survive config-gated resync)
    /* fall through */

round_loop:
    /* idle-gate: hold (don't arm EPs) unless USB gadget configured & idle */
    movw    r0, #:lower16:USB_STATE
    movt    r0, #:upper16:USB_STATE
    ldr     r1, [r0]
    cmp     r1, #2
    blt     gate_hold               @ state < 2 -> link not configured
    movw    r0, #:lower16:USB_LINK
    movt    r0, #:upper16:USB_LINK
    ldr     r1, [r0]
    cmp     r1, #0
    beq     gate_hold               @ link byte 0 -> not ready
    movw    r0, #:lower16:USB_EPMASK
    movt    r0, #:upper16:USB_EPMASK
    ldr     r1, [r0]
    cmp     r1, #0
    bne     gate_hold               @ an EP event pending -> not idle
    /* record-safe gate: are OUR vendor endpoints still enabled in DALEPENA?
     * record-mode reconfig (FUN_c01e62a8(0)) hard-resets DALEPENA to 0x3, disabling EP84/EP05.
     * Arming into disabled endpoints is the freeze (DEPCMD busy-spin -> IRQ0x34 livelock). */
    movw    r0, #:lower16:DALEPENA
    movt    r0, #:upper16:DALEPENA
    ldr     r1, [r0]
    and     r1, r1, #0x600
    cmp     r1, #0x600
    beq     arm_serve               @ our eps enabled -> serve
    /* 0x600 lost = recording reconfig disabled us. Do NOT arm. */
    movw    r0, #:lower16:REC_FLAG
    movt    r0, #:upper16:REC_FLAG
    ldrb    r1, [r0]
    cmp     r1, #0
    bne     gate_hold               @ still recording -> hold (never arm a disabled EP)
    /* recording cleared + link configured -> re-enable our endpoints, then re-arm.
     * (the record reconfig's cleanup already quiesced our stale arm; just re-enable + loop) */
    mov     r0, #0
    str     r0, [r4, #0x3C]         @ clear the endpoint-enable one-shot
    b       ag_admitted             @ re-run FUN_c01e62a9(4/5) + set DALEPENA 0x600, falls to round_loop
arm_serve:
    bl      arm_out
    ldr     r0, [r4, #20]
    cmp     r0, #0
    bne     fault_retry             @ OUT arm error
    mov     r0, #3
    str     r0, [r4, #44]
    mov     r0, #5
    movw    r1, #TMO
    movw    r12, #:lower16:FN_WAIT
    movt    r12, #:upper16:FN_WAIT
    blx     r12
    str     r0, [r4, #24]           @ OUT wait
    cmp     r0, #0
    bne     fault_retry             @ timeout waiting for a command -> just re-arm & wait

    /* r6 = uncached buf base; r10 = command string (payload @+20) */
    movw    r0, #:lower16:BUF_PTR
    movt    r0, #:upper16:BUF_PTR
    ldr     r6, [r0]
    mov     r0, #UNCACHED
    add     r6, r6, r0
    add     r10, r6, #20
    /* dispatch by 4-char prefix: "raw " -> raw-push, "mem " -> mem set/read */
    ldr     r0, [r10]
    movw    r1, #0x6172
    movt    r1, #0x2077            @ "raw " = 0x20776172
    cmp     r0, r1
    beq     do_rawpush
    movw    r1, #0x6163
    movt    r1, #0x6c6c            @ "call" = 0x6C6C6163
    cmp     r0, r1
    beq     do_call
    movw    r1, #0x6873
    movt    r1, #0x206c            @ "shl " = 0x206C6873 -> forward to firmware shell
    cmp     r0, r1
    beq     do_shell
    movw    r1, #0x656d
    movt    r1, #0x206d            @ "mem " = 0x206D656D
    cmp     r0, r1
    bne     bad_cmd
    add     r10, r10, #4
    /* dispatch: "set " (0x20746573) or "read" (0x64616572) */
    ldr     r0, [r10]
    movw    r1, #0x6573
    movt    r1, #0x2074
    cmp     r0, r1
    beq     do_set
    movw    r1, #0x6572
    movt    r1, #0x6461            @ "read" = 0x64616572
    cmp     r0, r1
    beq     do_read
    b       bad_cmd

do_set:
    add     r0, r10, #4            @ past "set "
    bl      parse_hex             @ r2=addr, r3=digits, r0=ptr
    cmp     r3, #0
    beq     malformed
    mov     r8, r2
    ldrb    r1, [r0]
    cmp     r1, #0x20             @ require a space between the two tokens
    bne     malformed
    add     r0, r0, #1
    bl      parse_hex             @ r2=val, r3=digits
    cmp     r3, #0
    beq     malformed
    mov     r9, r2
    ldrb    r1, [r0]              @ exact end: after value must be NUL or space
    cmp     r1, #0
    beq     set_ok_bounds
    cmp     r1, #0x20
    bne     malformed
set_ok_bounds:
    str     r8, [r4, #52]
    str     r9, [r4, #56]
    tst     r8, #3
    bne     out_range             @ word-aligned only
    movw    r0, #:lower16:WR_LO
    movt    r0, #:upper16:WR_LO
    cmp     r8, r0
    blo     ds_chk_inj
    movw    r0, #:lower16:WR_HI
    movt    r0, #:upper16:WR_HI
    cmp     r8, r0
    bls     ds_write              @ in tight scratch
ds_chk_inj:
    movw    r0, #:lower16:INJ_LO
    movt    r0, #:upper16:INJ_LO
    cmp     r8, r0
    blo     out_range
    movw    r0, #:lower16:INJ_HI
    movt    r0, #:upper16:INJ_HI
    cmp     r8, r0
    bhs     out_range
ds_write:
    str     r9, [r8]              @ WRITE (scratch or injection cave)
    mov     r0, #3
    str     r0, [r4, #48]
    b       arm_in                @ ack = unchanged echo frame

do_read:
    add     r0, r10, #4            @ past "read"
    ldrb    r1, [r0]
    cmp     r1, #0x20             @ require a space after "read"
    bne     malformed
    add     r0, r0, #1
    bl      parse_hex             @ r2=addr, r3=digits
    cmp     r3, #0
    beq     malformed
    mov     r8, r2
    ldrb    r1, [r0]
    cmp     r1, #0x20             @ space between addr and len
    bne     malformed
    add     r0, r0, #1
    bl      parse_dec             @ r2=len, r3=digits
    cmp     r3, #0
    beq     malformed
    mov     r9, r2
    ldrb    r1, [r0]              @ exact end
    cmp     r1, #0
    beq     read_bounds
    cmp     r1, #0x20
    bne     malformed
read_bounds:
    str     r8, [r4, #52]
    str     r9, [r4, #56]
    cmp     r9, #1
    blo     out_range
    cmp     r9, #44
    bhi     out_range
    adds    r0, r8, r9            @ end = addr+len; detect 32-bit overflow
    bcs     out_range
    /* the whole [addr, end) must lie inside ONE named read interval (rd_table).
       Position-independent address of rd_table via a PC-relative offset word (adr is out of range). */
    ldr     r1, .Loff_rdtab
.Ladd_rdtab:
    add     r1, pc, r1            @ pc = .Ladd_rdtab+8; r1 = rd_table
    b       .Lrdt_go
.Loff_rdtab:
    .word   rd_table - (.Ladd_rdtab + 8)
.Lrdt_go:
rdt_loop:
    ldr     r2, [r1]              @ lo
    ldr     r3, [r1, #4]          @ hi (exclusive)
    orrs    r12, r2, r3
    beq     out_range             @ (0,0) terminator -> not in any interval
    cmp     r8, r2
    blo     rdt_next
    cmp     r0, r3
    bls     rdt_ok
rdt_next:
    add     r1, r1, #8
    b       rdt_loop
rdt_ok:
    /* build reply frame in uncached buffer r6: copy r9 bytes @r8 -> payload r6+20, pad, CRC, arm_in.
     * Reusable: enter at build_reply with r6=uncached buf, r8=src, r9=len(<=44). */
build_reply:
    add     r7, r6, #20
    mov     r5, #0
rd_copy:
    ldrb    r0, [r8, r5]
    strb    r0, [r7, r5]
    add     r5, r5, #1
    cmp     r5, r9
    blo     rd_copy
rd_zero:
    cmp     r5, #44
    bhs     rd_hdr
    mov     r0, #0
    strb    r0, [r7, r5]
    add     r5, r5, #1
    b       rd_zero
rd_hdr:
    strh    r9, [r6, #12]         @ payload_length = len
    mov     r0, #0
    strh    r0, [r6, #14]         @ status = 0
    str     r0, [r6, #16]         @ checksum = 0
    mvn     r3, #0                @ crc = 0xFFFFFFFF
    mov     r5, #0
crc_byte:
    ldrb    r0, [r6, r5]
    eor     r3, r3, r0
    mov     r1, #8
crc_bit:
    ands    r0, r3, #1
    lsr     r3, r3, #1
    beq     crc_nobit
    movw    r2, #0x8320
    movt    r2, #0xedb8
    eor     r3, r3, r2
crc_nobit:
    subs    r1, r1, #1
    bne     crc_bit
    add     r5, r5, #1
    cmp     r5, #64
    blo     crc_byte
    mvn     r3, r3
    str     r3, [r6, #16]         @ checksum
    mov     r0, #4
    str     r0, [r4, #48]         @ read-ok
    b       arm_in

do_rawpush:
    add     r0, r10, #4            @ past "raw "
    bl      parse_hex             @ r2=addr, r3=digits
    cmp     r3, #0
    beq     malformed
    mov     r8, r2
    ldrb    r1, [r0]
    cmp     r1, #0x20
    bne     malformed
    add     r0, r0, #1
    bl      parse_hex             @ r2=len, r3=digits
    cmp     r3, #0
    beq     malformed
    mov     r9, r2
    movw    r1, #:lower16:RAW_CHUNK
    movt    r1, #:upper16:RAW_CHUNK
    cmp     r9, r1
    movhi   r9, r1                @ len = min(len, ~16MB)
    str     r8, [r4, #52]
    str     r9, [r4, #56]
    movw    r0, #:lower16:RAW_LO
    movt    r0, #:upper16:RAW_LO
    cmp     r8, r0
    blo     out_range
    adds    r0, r8, r9
    bcs     out_range
    movw    r1, #:lower16:RAW_HI
    movt    r1, #:upper16:RAW_HI
    cmp     r0, r1
    bhi     out_range
    /* arm EP84 IN with a big TRB straight from the DRAM address (copy-free raw DMA) */
    movw    r0, #:lower16:CTX4_TBL
    movt    r0, #:upper16:CTX4_TBL
    ldr     r7, [r0]
    str     r8, [r7]              @ bufptr = addr
    mov     r0, #0
    str     r0, [r7, #4]
    str     r9, [r7, #8]          @ size = len
    movw    r0, #TRB_ARMED
    str     r0, [r7, #12]
    dsb
    mov     r0, #9
    movw    r12, #:lower16:FN_STARTX
    movt    r12, #:upper16:FN_STARTX
    blx     r12                    @ StartTransfer(9)
    str     r0, [r4, #28]         @ raw arm ret
    mov     r0, #4
    movw    r1, #TMO
    movw    r12, #:lower16:FN_WAIT
    movt    r12, #:upper16:FN_WAIT
    blx     r12                    @ wait (host RAWREADs the raw chunk)
    str     r0, [r4, #32]         @ raw wait ret
    mov     r0, #6
    str     r0, [r4, #48]         @ result = 6 (rawpush done)
    b       loop_yield            @ NO 64-byte reply; loop for next command

do_call:
    add     r0, r10, #4            @ past "call"
    ldrb    r1, [r0]
    cmp     r1, #0x20
    bne     malformed
    add     r0, r0, #1
    bl      parse_hex             @ r2=addr
    cmp     r3, #0
    beq     malformed
    mov     r8, r2
    str     r8, [r4, #52]
    tst     r8, #3
    bne     out_range             @ word-aligned ARM entry
    movw    r0, #:lower16:INJ_LO
    movt    r0, #:upper16:INJ_LO
    cmp     r8, r0
    blo     out_range
    movw    r0, #:lower16:INJ_HI
    movt    r0, #:upper16:INJ_HI
    cmp     r8, r0
    bhs     out_range             @ only call code in the injection cave
    mov     r0, r4                @ arg0 = STATE ptr (injected code's I/O scratchpad)
    blx     r8                    @ run injected code
    str     r0, [r4, #56]         @ injected return value
    mov     r0, #7
    str     r0, [r4, #48]         @ result = 7 (call done)
    b       arm_in                @ ack

/* "shl <cmd>": forward <cmd> to the firmware shell command executor (FUN_c03d9c20) with a capture
 * sink; return the captured console output as the reply payload. Any of the 77 shell commands + subs. */
do_shell:
    add     r8, r10, #4           @ r8 = shell command line (after "shl "); UNCACHED+writable for strtok
    /* one-time global shell ctx init */
    movw    r0, #:lower16:SHELL_CTX
    movt    r0, #:upper16:SHELL_CTX
    ldr     r1, [r0]
    cmp     r1, #0
    bne     sh_ctx_ok
    movw    r0, #:lower16:SHELL_CTX
    movt    r0, #:upper16:SHELL_CTX
    movw    r12, #:lower16:FN_SHINIT
    movt    r12, #:upper16:FN_SHINIT
    blx     r12                   @ FUN_c03d9a10(ctx)
sh_ctx_ok:
    movw    r0, #:lower16:CAP_OFF
    movt    r0, #:upper16:CAP_OFF
    mov     r1, #0
    str     r1, [r0]              @ reset capture offset
    movw    r0, #:lower16:SHELL_CTX
    movt    r0, #:upper16:SHELL_CTX
    adr     r1, my_sink
    movw    r12, #:lower16:FN_SHPUSH
    movt    r12, #:upper16:FN_SHPUSH
    blx     r12                   @ push capture sink
    movw    r0, #:lower16:SHELL_CTX
    movt    r0, #:upper16:SHELL_CTX
    mov     r1, r8
    movw    r12, #:lower16:FN_SHEXEC
    movt    r12, #:upper16:FN_SHEXEC
    blx     r12                   @ FUN_c03d9c20(ctx, line)
    movw    r0, #:lower16:SHELL_CTX
    movt    r0, #:upper16:SHELL_CTX
    movw    r12, #:lower16:FN_SHPOP
    movt    r12, #:upper16:FN_SHPOP
    blx     r12                   @ pop sink -> restore UART
    movw    r0, #:lower16:CAP_OFF
    movt    r0, #:upper16:CAP_OFF
    ldr     r9, [r0]              @ captured length
    cmp     r9, #44
    movhi   r9, #44               @ clamp to 44 (single 64B frame; multi-frame is a later extension)
    movw    r8, #:lower16:CAP_BUF
    movt    r8, #:upper16:CAP_BUF
    mov     r0, #8
    str     r0, [r4, #48]         @ result = 8 (shell-ok)
    b       build_reply           @ copy r9 bytes @r8 -> reply payload, CRC, arm_in

/* capture sink (mirrors FUN_c000ee60): (r0=fmt, r1=a1, r2=a2, r3=a3) -> vsnprintf into CAP_BUF+off */
my_sink:
    push    {r1, r2, r3}          @ va_list: &a1 = sp, contiguous with any incoming stack varargs
    push    {r4, r5, lr}
    mov     r2, r0                @ arg3 = fmt
    add     r3, sp, #12           @ arg4 = &a1 (past r4,r5,lr)
    movw    r4, #:lower16:CAP_OFF
    movt    r4, #:upper16:CAP_OFF
    ldr     r5, [r4]
    movw    r0, #:lower16:CAP_BUF
    movt    r0, #:upper16:CAP_BUF
    add     r0, r0, r5            @ arg1 = buf+off
    movw    r1, #CAP_SZ
    subs    r1, r1, r5            @ arg2 = size-off
    ble     ms_pop
    sub     r1, r1, #1            @ leave room for NUL
    movw    r12, #:lower16:FN_VSNPRINTF
    movt    r12, #:upper16:FN_VSNPRINTF
    blx     r12                   @ FUN_c0013f48(buf,size,fmt,&a1) -> chars written
    cmp     r0, #0
    ble     ms_pop
    ldr     r5, [r4]
    add     r5, r5, r0
    str     r5, [r4]              @ off += n
ms_pop:
    pop     {r4, r5, lr}
    add     sp, sp, #12           @ pop va_list
    bx      lr

bad_cmd:
    mov     r0, #1
    str     r0, [r4, #48]
    b       arm_in
malformed:
    mov     r0, #5
    str     r0, [r4, #48]
    b       arm_in
out_range:
    mov     r0, #2
    str     r0, [r4, #48]

arm_in:
    movw    r0, #:lower16:BUF_PTR
    movt    r0, #:upper16:BUF_PTR
    ldr     r6, [r0]
    mov     r0, #CACHED
    add     r5, r6, r0
    movw    r0, #:lower16:CTX4_TBL
    movt    r0, #:upper16:CTX4_TBL
    ldr     r7, [r0]
    str     r5, [r7]
    mov     r0, #0
    str     r0, [r7, #4]
    mov     r0, #64
    str     r0, [r7, #8]
    movw    r0, #TRB_ARMED
    str     r0, [r7, #12]
    mov     r0, #4
    str     r0, [r4, #44]
    dsb                           @ reply payload/header/CRC + TRB visible before IN starts
    mov     r0, #9
    movw    r12, #:lower16:FN_STARTX
    movt    r12, #:upper16:FN_STARTX
    blx     r12
    str     r0, [r4, #28]         @ IN arm
    cmp     r0, #0
    bne     fault_retry
    mov     r0, #5
    str     r0, [r4, #44]
    mov     r0, #4
    movw    r1, #TMO
    movw    r12, #:lower16:FN_WAIT
    movt    r12, #:upper16:FN_WAIT
    blx     r12
    str     r0, [r4, #32]         @ IN wait
    cmp     r0, #0
    bne     fault_retry
    mov     r0, #6
    str     r0, [r4, #44]
    movw    r0, #0x4f44
    movt    r0, #0x454e
    str     r0, [r4, #36]         @ 'DONE' (per-command marker)
    ldr     r0, [r4, #0x5c]
    add     r0, r0, #1
    str     r0, [r4, #0x5c]       @ command-id (commands served)
    b       loop_yield

fault_retry:
    ldr     r0, [r4, #0x58]
    add     r0, r0, #1
    str     r0, [r4, #0x58]       @ fault count (timeouts + errors)
loop_yield:
    mov     r0, #20
    movw    r12, #:lower16:FN_DLY
    movt    r12, #:upper16:FN_DLY
    blx     r12
    b       round_loop

gate_hold:
    /* USB not ready to arm (e.g. record-start perturbation): short-delay and re-check, DO NOT arm a disabled EP */
    ldr     r0, [r4, #0x54]
    add     r0, r0, #1
    str     r0, [r4, #0x54]         @ gate-hold counter (diagnostic)
    mov     r0, #10
    movw    r12, #:lower16:FN_DLY
    movt    r12, #:upper16:FN_DLY
    blx     r12
    b       round_loop

/* arm EP05 OUT (r4=STATE). clobbers r0,r1,r5,r6,r7,r12. */
arm_out:
    push    {lr}
    movw    r0, #:lower16:BUF_PTR
    movt    r0, #:upper16:BUF_PTR
    ldr     r6, [r0]
    mov     r0, #CACHED
    add     r5, r6, r0
    mov     r0, #1
    str     r0, [r4, #44]
    mov     r0, #5
    movw    r12, #:lower16:FN_ENDX
    movt    r12, #:upper16:FN_ENDX
    blx     r12
    movw    r0, #:lower16:CTX5_TBL
    movt    r0, #:upper16:CTX5_TBL
    ldr     r7, [r0]
    str     r5, [r7]
    mov     r0, #0
    str     r0, [r7, #4]
    mov     r0, #1024
    str     r0, [r7, #8]
    movw    r0, #TRB_ARMED
    str     r0, [r7, #12]
    mov     r0, #2
    str     r0, [r4, #44]
    mov     r0, #10
    movw    r12, #:lower16:FN_STARTX
    movt    r12, #:upper16:FN_STARTX
    blx     r12
    str     r0, [r4, #20]
    pop     {pc}

/* parse_hex: r0=ptr -> r2=value, r3=digit count, r0=ptr after. skips optional 0x. uses r1,r12. */
parse_hex:
    mov     r2, #0
    mov     r3, #0
    ldrb    r1, [r0]
    cmp     r1, #0x30
    bne     phx_loop
    ldrb    r1, [r0, #1]
    cmp     r1, #0x78
    cmpne   r1, #0x58
    addeq   r0, r0, #2
phx_loop:
    ldrb    r1, [r0]
    sub     r12, r1, #0x30
    cmp     r12, #9
    bls     phx_acc
    sub     r12, r1, #0x61
    cmp     r12, #5
    bhi     phx_up
    add     r12, r12, #10
    b       phx_acc
phx_up:
    sub     r12, r1, #0x41
    cmp     r12, #5
    bhi     phx_done
    add     r12, r12, #10
phx_acc:
    lsl     r2, r2, #4
    orr     r2, r2, r12
    add     r3, r3, #1
    add     r0, r0, #1
    b       phx_loop
phx_done:
    bx      lr

/* parse_dec: r0=ptr -> r2=value, r3=digit count, r0=ptr after. uses r1,r12. */
parse_dec:
    mov     r2, #0
    mov     r3, #0
pd_loop:
    ldrb    r1, [r0]
    sub     r12, r1, #0x30
    cmp     r12, #9
    bhi     pd_done
    mov     r1, #10
    mul     r2, r2, r1
    add     r2, r2, r12
    add     r3, r3, #1
    add     r0, r0, #1
    b       pd_loop
pd_done:
    bx      lr

/* ---- named read-interval table: [lo, hi) pairs, (0,0)-terminated ----
   Narrow windows around the monitoring-console state sources (read-only observation). */
.align 2
rd_table:
    .word 0xC0000000, 0xC1000000   @ firmware code/strings/data
    .word 0xC31E3FC0, 0xC31E4000   @ gyro mailbox ptr 0xC31E3FCC (narrow; avoids USB TRB/flag)
    .word 0x2E006000, 0x2E008000   @ gyro ring (sub-ARM shared RAM) 0x2E006004/0x2E00644C
    .word 0xC343A000, 0xC343B000   @ ISO/gain controller G 0xC343A6A0
    .word 0xC3033000, 0xC3034000   @ AAT tracking box 0xC3033E00 + conf 0xC3033E26
    .word 0xC37CC000, 0xC37CE000   @ faces 0xC37CCA9C + FD_WORK 0xC37CD754 + AAT-model ptr 0xC37CDFA8
    .word 0xC3204000, 0xC3207000   @ AfMgr ctx 0xC32044D8 + area-mode 0xC32046A4 + drive-mode 0xC32065A0
    .word 0xC3202000, 0xC3203000   @ AF waypoints 0xC32020E4/E8
    .word 0xC3298000, 0xC3299000   @ AF contrast arrays 0xC32985E8/0xC32986B4
    .word 0xC3291000, 0xC3292000   @ AF peak/target/step 0xC32914E0/0xC32915B0/0xC32915C4
    .word 0xC3404000, 0xC3405000   @ AF-model singleton 0xC3404678 (+4 body-motion)
    .word 0xC33D0000, 0xC33D6000   @ drift 0xC33D1958 + peak-ring 0xC33D0384 + dir-vote 0xC33D5144
    .word 0x50000000, 0x50100000   @ raw LV/Bayer ring (probe window)
    .word 0x00000000, 0x00000000   @ terminator
