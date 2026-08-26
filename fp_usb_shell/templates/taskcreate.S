.syntax unified
.arm
.text
/* ============================================================================
 * taskcreate — start a background thread, with the ABI that actually works.
 * ============================================================================
 *
 * Two independently fatal mistakes live here, and both were made before:
 *
 *  1. There are two create/start pairs in the firmware. 0xC01F885C and
 *     0xC01F8D90 are the *Cyc-thread* ones, services 0x8047 and 0x8049, whose
 *     wrapper always passes a fixed trampoline as the entry point. Handing them
 *     a direct entry corrupts on start and freezes the camera with nothing
 *     readable back. The pair below is the one CamMain and the shell use.
 *
 *  2. The descriptor is +0 exinf, +4 tskatr, +8 entry, +12 itskpri, +16 stksz,
 *     +20 dsname[8]. Writing the name one slot early puts ASCII into stksz.
 *     cre_tsk does not bounds-check it and still returns a valid id, so the
 *     fault surfaces at sta_tsk instead -- on a wildly out-of-range stack,
 *     corrupting the shared stack pool at 0xC301EAE4 and poisoning every task
 *     created afterwards.
 *
 * itskpri 1..32, lower is more urgent; 28 is a background writer that yields to
 * everything that matters. stksz must not exceed 0x2000.
 *
 * There is no way to stop one of these afterwards. `tkos task` offers chgpri
 * and nothing else, and tk_ext_tsk's stub is not linked into this firmware --
 * of the sixteen syscall stubs sharing its template the service ids are 0x8001,
 * 0x8003, 0x801B-0x8024 and 0x8037-0x8044, and no 0x8004 constant exists
 * anywhere in 0xC0010000-0xC0040000. So a task started from the injection
 * region pins the code underneath it until the battery comes out, unless it can
 * be parked: see park.S.
 *
 * Call it from task context (shellcmd.S), not from a callback.
 * ========================================================================== */

.equ TK_CRE,   0xC0016A58      /* tk_cre_tsk(descriptor) -> id, or <=0        */
.equ TK_STA,   0xC0016BC0      /* tk_sta_tsk(id, stacd)                       */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* r0 = entry point, r1 = itskpri.  Returns the task id, or <=0.
 * Change the two dsname words to name your own; it shows in `tkos tsklist`. */
.global task_start
task_start:
    push    {r4, r5, lr}
    sub     sp, sp, #32                 @ 32 + 12 pushed keeps sp 8-byte aligned
    mov     r4, r0
    mov     r5, r1

    mov     r0, #0
    str     r0, [sp, #0]                @ exinf
    mov     r0, #0x41                   @ tskatr = TA_HLNG | TA_DSNAME
    str     r0, [sp, #4]
    str     r4, [sp, #8]                @ entry
    str     r5, [sp, #12]               @ itskpri
    movw    r0, #0x2000                 @ stksz -- never more than this
    str     r0, [sp, #16]
    movw    r0, #0x5355                 @ dsname "USTMPL\0\0"
    movt    r0, #0x4D54
    str     r0, [sp, #20]
    movw    r0, #0x4C50
    str     r0, [sp, #24]
    mov     r0, #0
    str     r0, [sp, #28]               @ the OS does not clear this; do not
                                        @ hand it stack junk

    mov     r0, sp
    LDA     ip, TK_CRE
    blx     ip
    mov     r4, r0
    cmp     r0, #1
    blt     1f
    mov     r1, #0                      @ stacd
    LDA     ip, TK_STA
    blx     ip
1:
    mov     r0, r4
    add     sp, sp, #32
    pop     {r4, r5, pc}
