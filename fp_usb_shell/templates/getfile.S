.syntax unified
.arm
.text
/* ============================================================================
 * getfile — read a file from the card into memory, where the host can see it.
 * ============================================================================
 *
 * The other half of putfile.S, and what makes writing a file safe to do: a
 * write can be read back and compared before anything acts on it.  The AutoRun
 * is the case that matters -- it is only executed at boot, so a bad write is
 * harmless as long as it is caught before the next one.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8.  See shellcmd.S.
 *
 * Parameter block, 0xC072F700:
 *      +0x04  bytes actually read                     <- filled by read()
 *      +0x08  status                                  <- read this
 *      +0x0C  open() return
 *      +0x10  read() return
 *      +0x14  buffer                  host fills
 *      +0x18  bytes to read           host fills
 *      +0x1C  file object scratch     host fills, ~1 KiB
 *      +0x20  open mode               host fills
 *      +0x24  path, NUL-terminated    host fills
 *
 * Status:  1 running   2 read   3 open returned 0   4 read returned 0
 *
 * read() is 0xC0366060, four arguments, forwarding to vtable slot +0x10 --
 * against write()'s three at +0x18.  The fourth is where the count goes, which
 * is why write() can answer a bare flag: it has nowhere to report a partial.
 * ========================================================================== */

.equ P,        0xC072F700
.equ P_ACTUAL, 0x04
.equ P_STATUS, 0x08
.equ P_OPENR,  0x0C
.equ P_READR,  0x10
.equ P_BUF,    0x14
.equ P_LEN,    0x18
.equ P_FOBJ,   0x1C
.equ P_MODE,   0x20
.equ P_PATH,   0x24

.equ FMT_S,    0xC0BABB38

.equ F_MGR,    0xC0444658
.equ F_VOL,    0xC0444698
.equ F_CTOR,   0xC0365E90
.equ F_OPEN,   0xC0365FB0
.equ F_READ,   0xC0366060     /* (obj, buf, len, *actual) */
.equ F_CLOSE,  0xC0366020
.equ F_DTOR,   0xC0365ED0

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
    mov     r8, r0
    LDA     r4, P
    mov     r0, #1
    str     r0, [r4, #P_STATUS]
    mov     r0, #0
    str     r0, [r4, #P_ACTUAL]

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
    beq     destroy

    ldr     r0, [r4, #P_FOBJ]
    ldr     r1, [r4, #P_BUF]
    ldr     r2, [r4, #P_LEN]
    add     r3, r4, #P_ACTUAL
    LDA     ip, F_READ
    blx     ip
    str     r0, [r4, #P_READR]
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
    .asciz  "getfile: read"
    .align  2
msg_bad:
    .asciz  "getfile: FAILED, read status at 0xC072F708"
    .align  2
