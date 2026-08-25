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
 *     0xC072F050..0xC072F500   this worker's code
 *     0xC072F500..0xC072F700   the one-shot template's scratch and code
 *     pool +0x0000             FPSH frame buffer, 4 KiB
 *     pool +0x2000             shell capture buffer, 16 KiB (derived from the
 *                              pool pointer, never hard-coded)
 *     pool +0x6000             free, for the logger's own buffers
 *
 * STATE.  Sixteen words at 0xC072F000, readable with
 *     shl mem save \VSHL.BIN 0xC072F000,,0x40
 *
 *     +00 'VSHL'      +04 task id      +08 start result  +0C rounds
 *     +10 OUT arm     +14 OUT wait     +18 IN arm        +1C IN wait
 *     +20 served      +24 faults       +28 gate holds    +2C last USB_STATE
 *     +30 last DALEPENA
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
.equ TIMEOUT,     50000

/* --- our memory ----------------------------------------------------------- */
.equ STATE,       0xC072F000      /* 16 words                                 */
.equ CAP_LEN,     0xC072F040      /* bytes captured from the shell            */
/* The capture buffer lives in the DMA pool, not the code cave.  In the cave it
 * could only be about 1.4 KiB before running into the injection ceiling, and a
 * kilobyte truncates the longer shell commands — `imager mode_list` stopped
 * after seven of seventy sensor modes.  The pool has room to spare and the CPU
 * copies out of it, so no coherency handling is needed. */
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
    LDA     r0, FRAMEBUF
    ldr     r8, [r0]
    add     r8, r8, #CAP_OFF
    b       reply

reply_nothing:
    mov     r9, #0
    LDA     r0, FRAMEBUF
    ldr     r8, [r0]
    add     r8, r8, #CAP_OFF

/* ==========================================================================
 * reply — send r9 bytes from r8, 44 to a frame, at least one frame.  Every
 * frame but the last sets flags bit 0.  The received header is reused so the
 * daemon's magic and sequence checks still pass.
 * ========================================================================== */
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

    mvn     r3, #0
    mov     r0, #0
crc_next_byte:
    ldrb    r1, [r6, r0]
    eor     r3, r3, r1
    mov     r2, #8
crc_next_bit:
    tst     r3, #1
    lsr     r3, r3, #1
    beq     crc_no_xor
    LDA     r1, 0xEDB88320
    eor     r3, r3, r1
crc_no_xor:
    subs    r2, r2, #1
    bne     crc_next_bit
    add     r0, r0, #1
    cmp     r0, #FRAME
    blo     crc_next_byte
    mvn     r3, r3
    str     r3, [r6, #16]

    bl      arm_in
    str     r0, [r4, #0x18]
    cmp     r0, #0
    bne     fault
    mov     r0, #LOG_IN
    movw    r1, #TIMEOUT
    LDA     r12, FN_WAIT
    blx     r12
    str     r0, [r4, #0x1C]
    cmp     r0, #0
    bne     fault

    cmp     r9, #0
    bgt     reply

    ldr     r0, [r4, #0x20]
    add     r0, r0, #1
    str     r0, [r4, #0x20]
    b       next_round

fault:
    ldr     r0, [r4, #0x24]
    add     r0, r0, #1
    str     r0, [r4, #0x24]
    mov     r0, #20
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
    mov     r0, #LOG_OUT
    LDA     r12, FN_ENDX
    blx     r12                         @ drop a TRB left by a timed-out round
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
