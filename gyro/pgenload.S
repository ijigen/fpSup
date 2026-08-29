/* Read \PGEN.BIN off the card into the pool and point the logger at it.
 *
 * The profile generator is two and a half kilobytes and the injection cave has
 * under a hundred bytes left, so it runs from the bufmem pool.  The pool's
 * address is only known at run time, which is why this exists: the AutoRun
 * cannot place code at an address it will not learn until boot, but it can
 * spell out something small that asks on its behalf.  The same shape as
 * tableload.S, which has been doing this for the lens table.
 *
 * \PGEN.BIN:  "PGEN" | u32 profile entry | u32 gcsv entry | u32 length | code
 *
 * The code is position independent -- internal calls are `bl`, everything else
 * is an absolute firmware address or an offset from r10 -- so it runs from
 * wherever it lands.
 *
 * Called with no arguments.  Returns the entry point, or zero.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.equ POOL_PTR,   0xC3757A7C   /* where the AutoRun left `memmgr bufmem get`   */
.equ O_STATE,    0x6000       /* the logger's r10, from the pool base         */
.equ PG_CODE,    0xF7000      /* from r10; must match putprofile.py           */
.equ PG_MAX,     0x1800       /* up to PG_TEXT at 0xF8800                     */
.equ S_JSON_FN,  0x00F0       /* from r10; must match logger.S                */
.equ S_GCSV_FN,  0x00F8
.equ HEADER,     16           /* "PGEN", two entry offsets, length            */
.equ MAGIC,      0x4E454750   /* "PGEN" */
.equ O_FOBJ,     0x19000      /* from r10: clear of the code and its buffers  */
.equ O_COUNT,    0x19800

.equ F_MGR,      0xC0444658
.equ F_VOL,      0xC0444698
.equ F_CTOR,     0xC0365E90
.equ F_OPEN,     0xC0365FB0
.equ F_READ,     0xC0366060
.equ F_CLOSE,    0xC0366020
.equ F_DTOR,     0xC0365ED0
.equ F_CACHE,    0xC000E91C   /* without it the CPU can fetch instructions the
                               * write has not reached memory with yet        */

    .global pgen_load
pgen_load:
    push    {r4, r5, r6, lr}
    ldr_addr r4, POOL_PTR
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f
    movw    r5, #:lower16:O_STATE
    movt    r5, #:upper16:O_STATE
    add     r4, r4, r5                  /* r4 = the logger's r10 */

    mov     r0, #0                      /* clear both first: half placed code
                                         * must never be branched to */
    movw    r5, #:lower16:S_JSON_FN
    str     r0, [r4, r5]
    movw    r5, #:lower16:S_GCSV_FN
    str     r0, [r4, r5]

    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    mov     r1, r0
    movw    r5, #:lower16:O_FOBJ
    movt    r5, #:upper16:O_FOBJ
    add     r5, r4, r5
    mov     r0, r5
    ldr_addr ip, F_CTOR
    blx     ip
    mov     r0, r5
    adr     r1, pgen_path
    mov     r2, #1
    ldr_addr ip, F_OPEN
    blx     ip
    cmp     r0, #0
    beq     8f

    movw    r6, #:lower16:O_COUNT
    movt    r6, #:upper16:O_COUNT
    add     r6, r4, r6
    mov     r0, #0
    str     r0, [r6]
    mov     r0, r5
    movw    r1, #:lower16:PG_CODE
    movt    r1, #:upper16:PG_CODE
    add     r1, r4, r1
    movw    r2, #:lower16:PG_MAX
    movt    r2, #:upper16:PG_MAX
    mov     r3, r6
    ldr_addr ip, F_READ
    blx     ip
    mov     r0, r5
    ldr_addr ip, F_CLOSE
    blx     ip
8:  mov     r0, r5
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip

    movw    r5, #:lower16:PG_CODE
    movt    r5, #:upper16:PG_CODE
    add     r5, r4, r5
    ldr     r0, [r5]
    ldr_addr r1, MAGIC
    cmp     r0, r1
    bne     9f
    ldr     r2, [r5, #12]               /* length */
    cmp     r2, #0
    beq     9f
    ldr     r0, [r6]                    /* what actually came off the card */
    add     r1, r2, #HEADER
    cmp     r0, r1
    blo     9f                          /* short read: do not run half of it */

    ldr_addr ip, F_CACHE
    blx     ip

    ldr     r0, [r5, #4]                /* the profile generator */
    add     r0, r0, #HEADER
    add     r0, r5, r0
    movw    r1, #:lower16:S_JSON_FN
    str     r0, [r4, r1]
    ldr     r0, [r5, #8]                /* the gcsv builder */
    add     r0, r0, #HEADER
    add     r0, r5, r0
    movw    r1, #:lower16:S_GCSV_FN
    str     r0, [r4, r1]
    pop     {r4, r5, r6, pc}
9:
    mov     r0, #0
    pop     {r4, r5, r6, pc}

pgen_path:
    .byte   0x5C                        /* a backslash, spelled out so no
                                         * escaping convention can change it */
    .asciz  "PGEN.BIN"
    .align  2
