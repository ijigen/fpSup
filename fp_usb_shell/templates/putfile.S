.syntax unified
.arm
.text
/* ============================================================================
 * putfile — write a host-supplied blob to a file on the card.
 * ============================================================================
 *
 * The native shell reads and writes memory (`mem set`, `mem get`), makes
 * directories and lists them, but nothing in it writes arbitrary content to a
 * file of your choosing.  `dbg write_out_script` writes a fixed sequence to a
 * fixed test.txt, `sdcard test5` writes a test pattern, `analyzer` writes its
 * own log.  So this is the one piece that has to be code.
 *
 * The host does the rest with commands that already exist: it asks the shell
 * for a buffer (`memmgr bufmem get`), stages the bytes into it (`mem set`), and
 * fills in the parameter block below.  Nothing here needs the AutoRun changed,
 * a pool resized, or a second worker.
 *
 * This is a one-shot payload, so it enters from the gyro callback -- where file
 * I/O may not go, because it blocks and takes the media mutex.  The payload
 * therefore only creates a task; the writing happens there.
 *
 * Parameter block, 0xC072F500:
 *      +0x00  'DONE' once the payload has run (one-shot plumbing)
 *      +0x04  payload result: the task id, or <=0 if it could not be created
 *      +0x08  status, see below                       <- poll this
 *      +0x0C  open() return
 *      +0x10  write() return
 *      +0x14  data pointer            host fills
 *      +0x18  data length             host fills
 *      +0x1C  file object scratch     host fills, needs ~1 KiB
 *      +0x20  open mode               host fills, 7 truncates or creates
 *      +0x24  path, NUL-terminated    host fills, e.g. "\AutoRun.txt"
 *
 * Status:
 *      0  not started        3  open returned 0
 *      1  running            4  write returned 0
 *      2  written            5  write returned short
 *
 * Open mode 7 truncates an existing file.  Mode 0x402, which the gyro logger
 * uses, fails when the file is already there -- fine for a logger that always
 * picks a new name, wrong for anything that updates a file in place.
 *
 * Every return value is checked.  These calls report failure by returning 0,
 * and a write that was never attempted looks exactly like one that worked if
 * nobody looks.
 * ========================================================================== */

.equ HOOK_SITE,   0xC00D0794
.equ HOOK_ORIG,   0xFA046FD7
.equ HOOK_TARGET, 0xC01EC6F9
.equ P,           0xC072F500

.equ P_DONE,   0x00
.equ P_RESULT, 0x04
.equ P_STATUS, 0x08
.equ P_OPENR,  0x0C
.equ P_WRITER, 0x10
.equ P_DATA,   0x14
.equ P_LEN,    0x18
.equ P_FOBJ,   0x1C
.equ P_MODE,   0x20
.equ P_PATH,   0x24

/* Media file API, as the gyro logger uses it and the shell's own dumps confirm. */
.equ F_MGR,    0xC0444658      /* () -> manager                                */
.equ F_VOL,    0xC0444698      /* (manager, 0) -> volume                       */
.equ F_CTOR,   0xC0365E90      /* (obj, volume)                                */
.equ F_OPEN,   0xC0365FB0      /* (obj, path, mode) -> 0 on failure            */
.equ F_WRITE,  0xC03660E8      /* (obj, buf, len)   -> bytes, 0 on failure     */
.equ F_CLOSE,  0xC0366020      /* (obj)                                        */
.equ F_DTOR,   0xC0365ED0      /* (obj, 2)                                     */

.equ TK_CRE,   0xC0016A58
.equ TK_STA,   0xC0016BC0

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, lr}
    LDA     r12, HOOK_TARGET
    blx     r12
    mov     r4, r0                  @ the callback's own return value

    LDA     r5, P
    ldr     r0, [r5, #P_DONE]
    LDA     r1, 0x454E4F44          @ 'DONE'
    cmp     r0, r1
    beq     leave                   @ already fired; a restore lost a race

    LDA     r0, HOOK_SITE
    LDA     r1, HOOK_ORIG
    str     r1, [r0]                @ put the site back before doing anything

    bl      payload
    str     r0, [r5, #P_RESULT]
    LDA     r0, 0x454E4F44
    str     r0, [r5, #P_DONE]
leave:
    mov     r0, r4
    pop     {r4, r5, pc}

/* ---------------------------------------------------------------------------
 * Payload: create the writer task.  Nothing that blocks may happen here.
 * Descriptor is +0 exinf, +4 tskatr, +8 entry, +12 itskpri, +16 stksz,
 * +20 dsname[8].  stksz is not bounds-checked by cre_tsk, so a name written
 * into the wrong slot returns a valid task id and corrupts the stack pool at
 * sta_tsk instead of failing.
 * ------------------------------------------------------------------------- */
payload:
    push    {r4, lr}
    sub     sp, sp, #32
    mov     r0, #0
    str     r0, [sp, #0]            @ exinf
    mov     r0, #0x41               @ TA_HLNG | TA_DSNAME
    str     r0, [sp, #4]
    adr     r0, writer
    str     r0, [sp, #8]
    mov     r0, #28                 @ itskpri
    str     r0, [sp, #12]
    movw    r0, #0x2000             @ stksz
    str     r0, [sp, #16]
    movw    r0, #0x5450             @ dsname "PTFILE\0\0"
    movt    r0, #0x4946
    str     r0, [sp, #20]
    movw    r0, #0x454C
    str     r0, [sp, #24]
    mov     r0, #0
    str     r0, [sp, #28]
    mov     r0, sp
    LDA     r12, TK_CRE
    blx     r12
    mov     r4, r0
    cmp     r0, #1
    blt     1f
    mov     r1, #0
    LDA     r12, TK_STA
    blx     r12
1:
    mov     r0, r4
    add     sp, sp, #32
    pop     {r4, pc}

/* ---------------------------------------------------------------------------
 * Writer task.  Task context, so blocking is allowed here.
 * ------------------------------------------------------------------------- */
writer:
    push    {r4-r8, lr}
    LDA     r4, P
    mov     r0, #1
    str     r0, [r4, #P_STATUS]

    LDA     r12, F_MGR
    blx     r12
    mov     r1, #0
    LDA     r12, F_VOL
    blx     r12
    mov     r1, r0
    ldr     r0, [r4, #P_FOBJ]
    LDA     r12, F_CTOR
    blx     r12

    ldr     r0, [r4, #P_FOBJ]
    add     r1, r4, #P_PATH
    ldr     r2, [r4, #P_MODE]
    LDA     r12, F_OPEN
    blx     r12
    str     r0, [r4, #P_OPENR]
    cmp     r0, #0
    moveq   r0, #3
    streq   r0, [r4, #P_STATUS]
    beq     done                    @ nothing to close: the open never took

    ldr     r0, [r4, #P_FOBJ]
    ldr     r1, [r4, #P_DATA]
    ldr     r5, [r4, #P_LEN]
    mov     r2, r5
    LDA     r12, F_WRITE
    blx     r12
    str     r0, [r4, #P_WRITER]
    mov     r6, #2                  @ assume written
    cmp     r0, #0
    moveq   r6, #4
    cmp     r0, r5
    movlo   r6, #5
    str     r6, [r4, #P_STATUS]

    ldr     r0, [r4, #P_FOBJ]
    LDA     r12, F_CLOSE
    blx     r12
done:
    ldr     r0, [r4, #P_FOBJ]
    mov     r1, #2
    LDA     r12, F_DTOR
    blx     r12
    pop     {r4-r8, pc}
