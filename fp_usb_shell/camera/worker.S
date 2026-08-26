.syntax unified
.arm
.text
/* ============================================================================
 * USB shell worker — runs on the camera, serves the PTP gadget's bulk pipes.
 * ============================================================================
 *
 * The gadget is the firmware's own PTP gadget, left exactly as the firmware
 * builds it.  The firmware therefore owns the descriptors, creates and enables
 * the endpoints, and re-creates them after a record-mode reconfiguration.  This
 * worker only moves bytes through pipes that already exist.
 *
 * AutoRun changes one word:
 *   0xC0CF3740  interface class 06/01/01 -> ff/ff/ff, so the host's PTP stack
 *               does not claim interface 0 before the shell daemon can.
 *
 * The gadget's class handler is deliberately left alone.  Removing it looks
 * harmless — FUN_c04dbc10 only answers the PTP class control requests 0x64 /
 * 0x66 / 0x67 and never touches a bulk endpoint — but registration stores it at
 * 0xC30257C0 and the control path at 0xC01E8268 stalls when it is NULL, so the
 * device never gets an address.  Two boots confirmed that.
 *
 * ENDPOINTS.  Taken from the PTP gadget, and matched against the firmware's own
 * bulk transfer routine at 0xC01E5BC0, which arms them exactly this way:
 *
 *     EP 0x01 OUT bulk   logical 1   physical 2   TRB ptr @ 0xC31E3268
 *     EP 0x82 IN  bulk   logical 2   physical 5   TRB ptr @ 0xC31E326C
 *     EP 0x83 IN  bulk       logical 3   physical 7   TRB ptr @ 0xC31E3270
 *                 AutoRun turns PTP's unused interrupt endpoint into this so a
 *                 hook has a pipe of its own.  The worker never touches it.
 *
 *   physical      = (logical << 1) | (direction == IN)
 *   StartTransfer takes the physical number, EndTransfer and Wait the logical
 *   TRB buffer     = CPU address - 0x40000000
 *   TRB control    = 0x813
 *
 * PROTOCOL.  FPSH v1, 64-byte frames, little-endian:
 *
 *     +00 magic "FPSH"   +04 version  +05 command  +06 flags
 *     +08 sequence       +0C payload_length        +0E status
 *     +10 crc32 (whole frame with this field zeroed)
 *     +14 payload, 44 bytes
 *
 *   A reply may span several frames: flags bit 0 means another frame follows.
 *   A command may be longer than the payload field — the worker reads it as a
 *   NUL-terminated string, and the OUT TRB is 1 KiB, so the text may run past
 *   byte 64 of the same transfer.  The CRC still covers only the first 64.
 *
 * COMMANDS.  One: `shl <line>`, which hands <line> to the firmware's own shell
 * dispatcher and returns whatever it printed.  That already includes `mem set`
 * and `mem save`, so the worker needs no memory commands of its own.
 *
 * MEMORY.  The worker sits high in the cave so that 0xC072DE64 through
 * 0xC072F000 stays clear for a gyro logger loaded alongside it — the two share
 * one card, and the shell is how the logger gets developed.
 *
 *     0xC072DE64..0xC072F000   free, for the gyro logger
 *     0xC072F000..0xC072F040   this worker's state
 *     0xC072F050..0xC072F700   this worker's code
 *     0xC072F700..0xC072F700   the one-shot template's scratch and code
 *     pool +0x0000             FPSH frame buffer, 4 KiB
 *     pool +0x2000             shell capture buffer, 16 KiB (derived from the
 *                              pool pointer, never hard-coded)
 *     pool +0x6000             free, for the logger's own buffers
 *
 * STATE.  Sixteen words at 0xC072F000, readable with
 *     shl mem save \VSHL.BIN 0xC072F000,,0x40
 *
 *     +00 'VSHL'      +04 task id      +08 last round faulted   +0C rounds
 *     +10 OUT arm     +14 OUT wait     +18 IN arm        +1C IN wait
 *     +20 served      +24 faults       +28 gate holds    +2C last USB_STATE
 *     +30 last DALEPENA  +34 first fault: which call  +38 what it returned
 *     +3C first gate reason (0x80000000 | DALEPENA<<8 | state)
 * ========================================================================== */

/* --- firmware entry points ------------------------------------------------ */
.equ FN_CRETSK,   0xC0016A58      /* tk_cre_tsk(descriptor) -> id             */
.equ FN_STATSK,   0xC0016BC0      /* tk_sta_tsk(id, code)                     */
.equ FN_DELAY,    0xC01F89C4      /* delay(ms), yields the CPU                */
.equ FN_ENDX,     0xC01E6D49      /* EndTransfer(logical ep)         [thumb]  */
.equ FN_STARTX,   0xC01E6B81      /* StartTransfer(physical ep)      [thumb]  */
.equ FN_WAIT,     0xC01E4E81      /* Wait(logical ep, timeout)       [thumb]  */
.equ FN_SHINIT,   0xC03D9A10      /* shell context one-time init              */
.equ FN_SHPUSH,   0xC03D9AC0      /* push an output sink                      */
.equ FN_SHPOP,    0xC03D9B20      /* pop the output sink                      */
.equ FN_SHRUN,    0xC03D9C20      /* tokenise, dispatch and run one line      */
.equ FN_VSNPRINT, 0xC0013F48      /* vsnprintf(buf, size, fmt, va)            */

/* --- firmware data -------------------------------------------------------- */
.equ FRAMEBUF,    0xC3757A7C      /* `memmgr bufmem get` result: [0] = address */
.equ TRB_OUT,     0xC31E3268      /* endpoint TRB table [1]: EP 0x01 OUT      */
.equ TRB_IN,      0xC31E326C      /* endpoint TRB table [2]: EP 0x82 IN       */
.equ USB_STATE,   0xC31E3748      /* 4 means the link is suspended            */
.equ DALEPENA,    0x2100C720      /* DWC3: bit N = physical endpoint N enabled */
.equ EP_MASK,     0x24            /* physical 2 (EP 0x01 OUT) | 5 (EP 0x82 IN) */
.equ SHELL_CTX,   0xC3756904      /* firmware shell context singleton         */

.equ PHYS_OUT,    2
.equ PHYS_IN,     5
.equ LOG_OUT,     1
.equ LOG_IN,      2
.equ TRB_ARMED,   0x813
.equ TIMEOUT,     50000         /* waiting for a command: no hurry            */
/* Waiting for the host to collect a reply is a different question, and fifty
 * seconds is the wrong answer to it. The host gives up after two hundred
 * milliseconds; everything after that is the camera holding a transfer nobody
 * is coming for, deaf to commands the whole time. That is what looked like the
 * worker dying: rounds crawling one every ten seconds, endpoints healthy, the
 * gate never once closed. Replugging the cable "fixed" it because
 * re-enumeration aborts the wait.
 *
 * Long enough that a host which is still there will be served; short enough
 * that one which has walked away costs a round, not a minute. */
.equ TIMEOUT_IN,  300

/* --- our memory ----------------------------------------------------------- */
.equ STATE,       0xC072F000      /* 16 words                                 */
.equ CAP_LEN,     0xC072F040      /* bytes captured from the shell            */
.equ SWAP_MAGIC,  0xC072F044      /* "SWAP" here and an address below means go */
.equ SWAP_ADDR,   0xC072F048
.equ CAP_PTR,     0xC072F04C      /* where the reply's bytes are, if not the
                                     capture buffer                           */
.equ SWAP_WORD,   0x50415753      /* "SWAP" */
/* The capture buffer lives in the DMA pool, not the code cave.  In the cave it
 * could only be about 1.4 KiB before running into the injection ceiling, and a
 * kilobyte truncates the longer shell commands — `imager mode_list` stopped
 * after seven of seventy sensor modes.  The pool has room to spare and the CPU
 * copies out of it, so no coherency handling is needed. */
.equ POOL_FAULTS, 0x6800        /* ten fault counters, past the buffers */
.equ CAP_OFF,     0x2000          /* capture buffer sits this far past the frame */
.equ CAP_MAX,     0x4000          /* 16 KiB                                   */

/* --- bootstrap ------------------------------------------------------------ */
.equ HOOK_SITE,   0xC00D0794      /* gyro callback, borrowed once             */
.equ HOOK_ORIG,   0xFA046FD7      /* the BLX this site normally holds         */
.equ HOOK_TARGET, 0xC01EC6F9      /* what that BLX called (thumb)             */

.equ TASK_PRIO,   28              /* verified safe                            */
.equ TASK_STACK,  0x2000          /* 8 KiB; the stack pool is shared - do not
                                     raise this, it corrupts other tasks      */
.equ FRAME,       64
.equ CHUNK,       44
.equ BULK_MIN,    128             /* replies at least this big go in one transfer */
.equ UNCACHED,    0x40000000
.equ TO_BUS,      0xC0000000      /* +0xC0000000 mod 2^32 == -0x40000000      */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* ==========================================================================
 * bootstrap — entered once from the gyro callback site.  Calls the routine it
 * displaced, creates the worker task, then puts the original word back.
 * ========================================================================== */
/* Not used by the loader build, and not dead either.
 *
 * `build_autorun.py --loader` puts the worker in VSHL.BIN and hooks loader.S
 * instead, which places this code and branches straight to `serve` -- so on a
 * card built that way nothing here ever runs, and STATE+0x00 stays zero rather
 * than reading "VSHL".
 *
 * Without --loader the AutoRun spells the whole worker out and hooks this, and
 * that build is the way back: it is one file, it depends on nothing written
 * recently, and it is what to fall back to when the binary or the loader is the
 * suspect. The loader has been wrong twice already -- once living at the
 * address it was copying to, once guarding itself with a word the worker
 * clears -- and both times this was what a card reader could put back.
 *
 * Its two hundred bytes used to cost fifty `mem set` commands. They now arrive
 * in a file, so keeping it costs nothing worth counting.
 */
.global bootstrap
bootstrap:
    push    {r4, r5, lr}
    LDA     r12, HOOK_TARGET
    blx     r12
    mov     r4, r0                      @ the displaced call's return value

    LDA     r5, STATE
    ldr     r0, [r5]
    LDA     r1, 0x4C485356              @ 'VSHL'
    cmp     r0, r1
    beq     bootstrap_done
    str     r1, [r5]                    @ claim before anything can re-enter

    LDA     r0, HOOK_SITE
    LDA     r1, HOOK_ORIG
    str     r1, [r0]

    sub     sp, sp, #32
    mov     r0, #0
    str     r0, [sp, #0]                @ exinf
    mov     r0, #0x41
    str     r0, [sp, #4]                @ tskatr
    adr     r0, serve
    str     r0, [sp, #8]                @ entry
    mov     r0, #TASK_PRIO
    str     r0, [sp, #12]
    movw    r0, #TASK_STACK
    str     r0, [sp, #16]
    LDA     r0, 0x4853565F              @ dsname "_VSH"
    str     r0, [sp, #20]
    movw    r0, #0x004C                 @ "L"
    str     r0, [sp, #24]
    mov     r0, #0
    str     r0, [sp, #28]
    mov     r0, sp
    LDA     r12, FN_CRETSK
    blx     r12
    add     sp, sp, #32
    str     r0, [r5, #4]
    cmp     r0, #0
    ble     bootstrap_done
    mov     r1, #0
    LDA     r12, FN_STATSK
    blx     r12
    str     r0, [r5, #8]
bootstrap_done:
    mov     r0, r4
    pop     {r4, r5, pc}

/* Ahead of `serve`, not after it.
 *
 * `serve` reaches this with `adr`, which is pc-relative and has a small range,
 * and every line added to `serve` pushed it further away until the assembler
 * refused -- twice in one evening, for changes that had nothing to do with it.
 * Sitting before its only caller, the distance shrinks as the code above it
 * grows instead of stretching.
 */
/* ==========================================================================
 * capture — the shell calls its sink as printf(fmt, a1, a2, a3), with any
 * further arguments already on the stack, so &a1 has to sit next to them.
 * ========================================================================== */
capture:
    push    {r1, r2, r3}                @ makes a contiguous va_list
    push    {r4, r5, lr}
    mov     r2, r0                      @ fmt
    add     r3, sp, #12                 @ &a1
    LDA     r4, CAP_LEN
    ldr     r5, [r4]
    LDA     r0, FRAMEBUF
    ldr     r0, [r0]
    add     r0, r0, #CAP_OFF
    add     r0, r0, r5
    movw    r1, #CAP_MAX
    subs    r1, r1, r5
    ble     capture_done
    sub     r1, r1, #1                  @ leave room for the NUL
    LDA     r12, FN_VSNPRINT
    blx     r12
    cmp     r0, #0
    ble     capture_done
    ldr     r5, [r4]
    add     r5, r5, r0
    str     r5, [r4]
capture_done:
    pop     {r4, r5, lr}
    add     sp, sp, #12
    bx      lr

/* ==========================================================================
 * serve — the worker task.  r4 holds STATE for its whole life.
 * ========================================================================== */
serve:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}   @ 8 words keeps sp 8-byte aligned
    LDA     r4, STATE

next_round:
    ldr     r0, [r4, #0x0C]
    add     r0, r0, #1
    str     r0, [r4, #0x0C]

    /* Somewhere to go, if the host has somewhere for this task to be.
     *
     * Every change to this file has cost a power cycle, because the code is
     * placed at boot and this task is running inside it -- overwriting it from
     * a borrowed shell command means overwriting the instructions doing the
     * overwriting. Eight reboots in one evening.
     *
     * The way out is not to do the copying here. loader.S sits at the bottom of
     * the cave, well clear of this code, and its `load` entry already reads
     * VSHL.BIN, places what it says and branches to the entry named in it. This
     * task jumping there replaces the worker with itself, from outside itself.
     *
     * Two words rather than one: an address alone is a jump to whatever
     * happened to be written, and this runs every round. The magic is cleared
     * before the branch so a half-written pair cannot fire twice. */
    LDA     r0, SWAP_MAGIC
    ldr     r1, [r0]
    LDA     r2, SWAP_WORD
    cmp     r1, r2
    bne     no_swap
    mov     r1, #0
    str     r1, [r0]
    LDA     r0, SWAP_ADDR
    ldr     r0, [r0]
    cmp     r0, #0
    bxne    r0
no_swap:

    /* Do not touch an endpoint the firmware has not configured yet.  DALEPENA is
     * the controller's own record of which physical endpoints exist, so it is
     * the only honest test: it stays 0x003 (EP0 only) until the host completes
     * SET_CONFIGURATION.  Issuing DEPCMDs before that competes with the driver
     * while it is trying to enumerate, and the enumeration is what loses.
     * USB_STATE is not a substitute — it reads 2 long before the endpoints
     * exist.  It is still worth checking for suspend, where arming makes the
     * controller busy-spin. */
    LDA     r0, DALEPENA
    ldr     r1, [r0]
    str     r1, [r4, #0x30]
    and     r1, r1, #EP_MASK
    cmp     r1, #EP_MASK
    bne     hold

    LDA     r0, USB_STATE
    ldr     r1, [r0]
    str     r1, [r4, #0x2C]
    cmp     r1, #4
    beq     hold

    bl      arm_out
    str     r0, [r4, #0x10]
    cmp     r0, #0
    bne     fault

    mov     r0, #LOG_OUT
    movw    r1, #TIMEOUT
    LDA     r12, FN_WAIT
    blx     r12
    str     r0, [r4, #0x14]
    cmp     r0, #0
    bne     fault                       @ idle timeout: just arm again

    LDA     r0, FRAMEBUF
    ldr     r6, [r0]
    mov     r0, #UNCACHED
    add     r6, r6, r0                  @ r6 = uncached view of the frame
    add     r10, r6, #20                @ payload

    ldr     r0, [r10]
    LDA     r1, 0x206C6873              @ "shl "
    cmp     r0, r1
    bne     reply_nothing

/* --- run one firmware shell line, capturing what it prints ---------------- */
    add     r7, r10, #4                 @ the line; writable, so strtok is fine
    LDA     r0, SHELL_CTX
    ldr     r1, [r0]
    cmp     r1, #0
    bne     shell_ready
    LDA     r0, SHELL_CTX
    LDA     r12, FN_SHINIT
    blx     r12
shell_ready:
    LDA     r0, CAP_LEN
    mov     r1, #0
    str     r1, [r0]

    LDA     r0, SHELL_CTX
    adr     r1, capture
    LDA     r12, FN_SHPUSH
    blx     r12

    LDA     r0, SHELL_CTX
    mov     r1, r7
    LDA     r12, FN_SHRUN
    blx     r12

    LDA     r0, SHELL_CTX
    LDA     r12, FN_SHPOP
    blx     r12                         @ hand the console back to the UART

    LDA     r0, CAP_LEN
    ldr     r9, [r0]

    /* Send from wherever the answer already is.
     *
     * Everything used to be copied into the capture buffer first, and that
     * buffer is sixteen kilobytes -- so a thirty-one megabyte file came back in
     * nineteen hundred and ninety-five round trips, each one a request the host
     * had to make and the camera had to be ready for. The limit was never the
     * link or the card (the card reads that file into memory in 0.17 s, at 183
     * MB/s); it was a staging buffer we were copying through for no reason.
     *
     * A TRB carries a 24-bit length, so one transfer can be sixteen megabytes.
     * A payload that already knows where its bytes are puts the address here
     * and the DMA reads them where they lie. The capture buffer stays for what
     * it is actually for: catching what the firmware's printf writes. */
    LDA     r0, CAP_PTR
    ldr     r8, [r0]
    cmp     r8, #0
    bne     reply_entry
    LDA     r0, FRAMEBUF
    ldr     r8, [r0]
    add     r8, r8, #CAP_OFF
    b       reply_entry

reply_nothing:
    mov     r9, #0
    LDA     r0, FRAMEBUF
    ldr     r8, [r0]
    add     r8, r8, #CAP_OFF

/* ==========================================================================
 * reply — send r9 bytes from r8.
 *
 * Small replies go 44 to a frame, every frame but the last setting flags bit 0.
 * The received header is reused so the daemon's magic and sequence checks still
 * pass.
 *
 * Large ones do not.  Forty-four bytes per 64-byte frame, one armed transfer and
 * one blocking wait apiece, is 1.1% of what the endpoint can carry -- it is bulk,
 * 1024-byte packets, burst 3, so 4096 bytes fit in a single transfer.  Reading a
 * 250 KB file that way took eighty thousand round trips at 160 microseconds each,
 * and the slowness had nothing to do with the card or the link.
 *
 * So: one header frame saying how many bytes follow and carrying their CRC-32,
 * then the block itself in a single transfer, straight out of the capture buffer
 * with no copy.  Three thousand bytes go from 137 transfers to two.
 * ========================================================================== */
reply_entry:
    /* The host can say in the command frame that it already knows how many bytes
     * are coming and wants only those. That removes the header frame, and with
     * it a race: the block's TRB is armed after the header transfer completes,
     * so a host that reads the header and immediately asks for the block can
     * arrive before there is anywhere to put it. Nine percent of large replies
     * failed that way, and a failure costs a 200 ms timeout -- which was the
     * whole difference between 4 ms and 22 ms an exchange. */

    /* Read here and not at the loop head below.  fill_header writes this same
     * field to say another frame follows, so a reply of more than 44 bytes came
     * back round, read its own 1, and dived into the raw path -- which broke
     * every reply longer than one frame, `version` included. */
    ldrh    r0, [r6, #6]
    tst     r0, #1
    bne     reply_raw

    cmp     r9, #BULK_MIN
    bhs     reply_bulk

reply:
    mov     r5, r9
    cmp     r5, #CHUNK
    movhi   r5, #CHUNK
    sub     r9, r9, r5

    add     r7, r6, #20
    mov     r0, #0
copy_payload:
    cmp     r0, r5
    bhs     pad_payload
    ldrb    r1, [r8, r0]
    strb    r1, [r7, r0]
    add     r0, r0, #1
    b       copy_payload
pad_payload:
    cmp     r0, #CHUNK
    bhs     fill_header
    mov     r1, #0
    strb    r1, [r7, r0]
    add     r0, r0, #1
    b       pad_payload

fill_header:
    add     r8, r8, r5                  @ advance for the next frame
    cmp     r9, #0
    movne   r0, #1
    moveq   r0, #0
    strh    r0, [r6, #6]                @ flags: more to come
    strh    r5, [r6, #12]               @ payload_length
    mov     r0, #0
    strh    r0, [r6, #14]               @ status
    str     r0, [r6, #16]               @ crc field zeroed for the calculation

    mov     r0, r6
    mov     r1, #FRAME
    bl      crc_block
    str     r3, [r6, #16]

    bl      arm_in
    str     r0, [r4, #0x18]
    cmp     r0, #0
    bne     fault
    mov     r0, #LOG_IN
    movw    r1, #TIMEOUT_IN
    LDA     r12, FN_WAIT
    blx     r12
    str     r0, [r4, #0x1C]
    cmp     r0, #0
    bne     fault

    cmp     r9, #0
    bgt     reply

reply_done:
    mov     r0, #0
    LDA     r1, CAP_PTR                 @ one command's answer, not the next one's
    str     r0, [r1]
    str     r0, [r4, #0x08]             @ clean round: nothing to end next time
    ldr     r0, [r4, #0x20]
    add     r0, r0, #1
    str     r0, [r4, #0x20]
    b       next_round

fault:
    mov     r0, #1
    str     r0, [r4, #0x08]             @ next arm_out has something to clean up
    ldr     r0, [r4, #0x24]
    add     r0, r0, #1
    str     r0, [r4, #0x24]
    mov     r0, #1
    LDA     r12, FN_DELAY
    blx     r12
    b       next_round

hold:
    ldr     r0, [r4, #0x28]
    add     r0, r0, #1
    str     r0, [r4, #0x28]
    mov     r0, #50
    LDA     r12, FN_DELAY
    blx     r12
    b       next_round

/* --- arm EP 0x01 OUT for one command; returns the StartTransfer status ----- */
arm_out:
    push    {r4, r5, r6, r7, lr}

    /* Only after a round that went wrong.
     *
     * This used to end the transfer before every arm, tens of thousands of
     * times, to drop a TRB a timed-out round might have left. The controller
     * then rejected one Start Transfer in four -- a hundred and seventy-seven
     * faults out of a hundred and seventy-nine, all of them here, all of them
     * DEPCMD answering with a non-zero status, which on this controller means
     * it had no transfer resource to give. Ending and starting a transfer every
     * round is what spends them.
     *
     * A round that ended cleanly has nothing to drop. STATE+0x08 says whether
     * the last one did: `fault` sets it, `reply_done` clears it. */
    ldr     r0, [r4, #0x08]
    cmp     r0, #0
    beq     arm_out_go
    mov     r0, #LOG_OUT
    LDA     r12, FN_ENDX
    blx     r12                         @ drop the TRB the bad round left
arm_out_go:
    LDA     r0, FRAMEBUF
    ldr     r6, [r0]
    mov     r0, #TO_BUS
    add     r5, r6, r0
    LDA     r0, TRB_OUT
    ldr     r7, [r0]
    str     r5, [r7]
    mov     r0, #0
    str     r0, [r7, #4]
    mov     r0, #1024
    str     r0, [r7, #8]
    movw    r0, #TRB_ARMED
    str     r0, [r7, #12]
    dsb
    mov     r0, #PHYS_OUT
    LDA     r12, FN_STARTX
    blx     r12
    pop     {r4, r5, r6, r7, pc}

/* --- the block alone, because the host said it knows the length ----------- */
reply_raw:
    /* Never answer with nothing.
     *
     * The host asked for a block of a length it already knows, and is sitting
     * in a bulk IN waiting for exactly that many bytes. Sending none used to
     * count the command as served and move on, which leaves the host with
     * nothing to do but time out -- and a timeout is a cancelled transfer, and
     * enough cancelled transfers and the firmware's own wait returns the error
     * that takes it to FUN_c01e6ef8, which ends every endpoint and drops the
     * device off the bus. The camera stays perfectly happy; only the USB side
     * of it disappears, and it does not come back on its own.
     *
     * One byte is not the answer the host wanted, but it ends the transfer.
     * A short read is an error it can see and retry in microseconds, instead
     * of a silence it can only wait out. */
    cmp     r9, #0
    moveq   r9, #1
    bl      arm_in_block
    cmp     r0, #0
    bne     fault
    mov     r0, #LOG_IN
    movw    r1, #TIMEOUT_IN
    LDA     r12, FN_WAIT
    blx     r12
    str     r0, [r4, #0x1C]
    cmp     r0, #0
    bne     fault
    b       reply_done

/* --- one header frame, then the block in a single transfer ---------------- */
reply_bulk:
    mov     r0, r8
    mov     r1, r9
    bl      crc_block                   @ r3 = CRC-32 of the block

    add     r7, r6, #20
    str     r3, [r7]                    @ payload[0..3] = the block's CRC
    mov     r0, #2
    strh    r0, [r6, #6]                @ flags: a raw block follows
    strh    r9, [r6, #12]               @ payload_length = its length
    mov     r0, #0
    strh    r0, [r6, #14]
    str     r0, [r6, #16]

    mov     r0, r6
    mov     r1, #FRAME
    bl      crc_block
    str     r3, [r6, #16]

    bl      arm_in
    str     r0, [r4, #0x18]
    cmp     r0, #0
    bne     fault
    mov     r0, #LOG_IN
    movw    r1, #TIMEOUT_IN
    LDA     r12, FN_WAIT
    blx     r12
    cmp     r0, #0
    bne     fault

    bl      arm_in_block
    cmp     r0, #0
    bne     fault
    mov     r0, #LOG_IN
    movw    r1, #TIMEOUT_IN
    LDA     r12, FN_WAIT
    blx     r12
    str     r0, [r4, #0x1C]
    cmp     r0, #0
    bne     fault
    b       reply_done

/* r0 = start, r1 = length -> r3 = CRC-32 */
crc_block:
    push    {r4, r5, r6, lr}
    mvn     r3, #0
    mov     r4, #0
1:  cmp     r4, r1
    bhs     3f
    ldrb    r5, [r0, r4]
    eor     r3, r3, r5
    mov     r2, #8
2:  tst     r3, #1
    lsr     r3, r3, #1
    beq     4f
    LDA     r5, 0xEDB88320
    eor     r3, r3, r5
4:  subs    r2, r2, #1
    bne     2b
    add     r4, r4, #1
    b       1b
3:  mvn     r3, r3
    pop     {r4, r5, r6, pc}

/* --- arm EP 0x82 IN with r9 bytes at r8, no copy -------------------------- */
arm_in_block:
    push    {r4, r5, r6, r7, lr}
    mov     r0, #TO_BUS
    add     r5, r8, r0
    LDA     r0, TRB_IN
    ldr     r7, [r0]
    str     r5, [r7]
    mov     r0, #0
    str     r0, [r7, #4]
    str     r9, [r7, #8]
    movw    r0, #TRB_ARMED
    str     r0, [r7, #12]
    dsb
    mov     r0, #PHYS_IN
    LDA     r12, FN_STARTX
    blx     r12
    pop     {r4, r5, r6, r7, pc}

/* --- arm EP 0x82 IN with the 64-byte reply frame -------------------------- */
arm_in:
    push    {r4, r5, r6, r7, lr}
    LDA     r0, FRAMEBUF
    ldr     r6, [r0]
    mov     r0, #TO_BUS
    add     r5, r6, r0
    LDA     r0, TRB_IN
    ldr     r7, [r0]
    str     r5, [r7]
    mov     r0, #0
    str     r0, [r7, #4]
    mov     r0, #FRAME
    str     r0, [r7, #8]
    movw    r0, #TRB_ARMED
    str     r0, [r7, #12]
    dsb                                 @ frame and TRB visible before the DMA
    mov     r0, #PHYS_IN
    LDA     r12, FN_STARTX
    blx     r12
    pop     {r4, r5, r6, r7, pc}


