.syntax unified
.arm
.text
/* ============================================================================
 * putfile — write a host-supplied blob to a file on the card.
 * ============================================================================
 *
 * A worked example of shellcmd.S, and the reason it exists.  The native shell
 * reads and writes memory, makes directories and lists them, but nothing in it
 * writes arbitrary content to a path of your choosing: `dbg write_out_script`
 * writes a fixed sequence to a fixed name, `sdcard test5` writes a test
 * pattern, `analyzer` writes its own log.
 *
 * The host does everything else with commands that already exist -- `mem set`
 * stages the bytes, `dir` confirms the result -- so this is only the write.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8.  Run through a command
 * rather than the gyro callback because file I/O blocks and takes the media
 * mutex, and because a handler is a function that may simply return.
 *
 * Parameter block, 0xC072F700:
 *      +0x08  status                                  <- read this
 *      +0x0C  open() return
 *      +0x10  write() return
 *      +0x14  data pointer            host fills
 *      +0x18  data length             host fills
 *      +0x1C  file object scratch     host fills, ~1 KiB
 *      +0x20  open mode               host fills, 7 truncates or creates
 *      +0x24  path, NUL-terminated    host fills, e.g. "\AutoRun.txt"
 *
 * Status:  1 running   2 written   3 open returned 0   4 write returned 0
 *
 * write() answers 1 for success, not a byte count -- it returned 1 for a 25
 * byte file that `dir` then showed as 25 bytes.  So the length is confirmed on
 * the host, from the directory, not from this return.
 *
 * Mode 7 truncates an existing file.  Mode 0x402, which the gyro logger uses,
 * fails when the file is already there -- fine for a logger that always picks a
 * new name, wrong for anything that updates a file in place.
 *
 * Every return is checked.  These calls report failure by returning zero, and a
 * write that never happened is indistinguishable from one that worked unless
 * somebody looks.
 * ========================================================================== */

.equ P,        0xC072F700
.equ P_STATUS, 0x08
.equ P_OPENR,  0x0C
.equ P_WRITER, 0x10
.equ P_DATA,   0x14
.equ P_LEN,    0x18
.equ P_FOBJ,   0x1C
.equ P_MODE,   0x20
.equ P_PATH,   0x24

.equ FMT_S,    0xC0BABB38     /* "%s " */

.equ F_MGR,    0xC0444658     /* () -> manager                            */
.equ F_VOL,    0xC0444698     /* (manager, 0) -> volume                   */
.equ F_CTOR,   0xC0365E90     /* (obj, volume)                            */
.equ F_OPEN,   0xC0365FB0     /* (obj, path, mode) -> 0 on failure        */
.equ F_WRITE,  0xC03660E8     /* (obj, buf, len)   -> 1 ok, 0 on failure   */
.equ F_CLOSE,  0xC0366020     /* (obj)                                    */
.equ F_DTOR,   0xC0365ED0     /* (obj, 2)                                 */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    /* An even number of registers, deliberately.  AAPCS wants the stack eight
     * byte aligned at a call, and pushing an odd count leaves it four -- which
     * costs nothing until the callee reaches an LDRD, and then it is a data
     * abort with the shell task holding the dispatcher. */
    push    {r4, r5, r6, r7, r8, lr}
    mov     r8, r0                  @ shell context, for the reply
    LDA     r4, P
    mov     r0, #1
    str     r0, [r4, #P_STATUS]

    LDA     ip, F_MGR
    blx     ip
    mov     r1, #0
    LDA     ip, F_VOL
    blx     ip
    mov     r1, r0
    ldr     r0, [r4, #P_FOBJ]
    LDA     ip, F_CTOR
    blx     ip

    ldr     r0, [r4, #P_FOBJ]
    add     r1, r4, #P_PATH
    ldr     r2, [r4, #P_MODE]
    LDA     ip, F_OPEN
    blx     ip
    str     r0, [r4, #P_OPENR]
    cmp     r0, #0
    moveq   r0, #3
    streq   r0, [r4, #P_STATUS]
    beq     destroy                 @ nothing to close: the open never took

    ldr     r0, [r4, #P_FOBJ]
    ldr     r1, [r4, #P_DATA]
    ldr     r5, [r4, #P_LEN]
    mov     r2, r5
    LDA     ip, F_WRITE
    blx     ip
    str     r0, [r4, #P_WRITER]
    cmp     r0, #0
    moveq   r6, #4
    movne   r6, #2
    str     r6, [r4, #P_STATUS]

    ldr     r0, [r4, #P_FOBJ]
    LDA     ip, F_CLOSE
    blx     ip

destroy:
    ldr     r0, [r4, #P_FOBJ]
    mov     r1, #2
    LDA     ip, F_DTOR
    blx     ip

    ldr     r0, [r4, #P_STATUS]
    cmp     r0, #2
    adreq   r1, msg_ok
    adrne   r1, msg_bad
    ldr     ip, [r8]
    LDA     r0, FMT_S
    blx     ip

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

msg_ok:
    .asciz  "putfile: written"
    .align  2
msg_bad:
    .asciz  "putfile: FAILED, read status at 0xC072F708"
    .align  2
