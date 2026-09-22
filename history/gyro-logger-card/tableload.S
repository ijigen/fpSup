/* Read \LENS.DAT off the card into the pool, where the logger looks for it.
 *
 * The lens-profile table is sixty kilobytes.  Sending that over USB takes half a
 * minute and eight thousand repaired words, because `mem set` moves four bytes a
 * round trip and drops some of them; the camera reads the same file off its own
 * card in a moment.  So the host places this, calls it once, and the table is
 * there -- and the AutoRun can call exactly the same code at boot, which is what
 * makes the logger work from a cold start with nothing plugged in.
 *
 * Called with no arguments.  Returns the byte count, or zero if the file was not
 * there or did not open.  Nothing here is reached from the recording path.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.equ POOL_PTR,   0xC3757A7C   /* where the AutoRun left `memmgr bufmem get`   */
.equ O_STATE,    0x6000       /* the logger's r10, from the pool base         */
/* The gap between the logger's block buffers and its gcsv text buffer is
 * r10+0x9000 .. r10+0x1A000, and everything here has to fit inside it without
 * overlapping anything else here.
 *
 * TABLE_MAX is the pad lensdat.py writes, not the space that is left: reading
 * "as much as will fit" put the tail of the file on top of the file object,
 * mid-read.  It survived the read and then closed a corrupted object, and the
 * next open failed -- nothing crashed, the damage just waited. An older, longer
 * \LENS.DAT can leave a tail past the pad, and this stops short of it; the
 * directory never points there. */
.equ O_TABLE,    0x9000       /* from r10; must match logger.S's O_PROFILE    */
.equ TABLE_MAX,  0x10000      /* exactly lensdat.py's pad: 0x9000..0x19000    */
.equ O_FOBJ,     0x19000      /* clear of the table, clear of O_TEXT          */
.equ O_COUNT,    0x19800      /* where read() drops its byte count            */

.equ F_MGR,      0xC0444658
.equ F_VOL,      0xC0444698
.equ F_CTOR,     0xC0365E90
.equ F_OPEN,     0xC0365FB0
.equ F_READ,     0xC0366060
.equ F_CLOSE,    0xC0366020
.equ F_DTOR,     0xC0365ED0

    .global table_load
table_load:
    push    {r4, r5, r6, lr}
    ldr_addr r4, POOL_PTR
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f                       /* no pool: the AutoRun has not run */
    movw    r5, #:lower16:O_STATE
    movt    r5, #:upper16:O_STATE
    add     r4, r4, r5               /* r4 = the logger's r10 */

    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    mov     r1, r0
    movw    r5, #:lower16:O_FOBJ
    movt    r5, #:upper16:O_FOBJ
    add     r5, r4, r5               /* r5 = the file object */
    mov     r0, r5
    ldr_addr ip, F_CTOR
    blx     ip
    mov     r0, r5
    adr     r1, lensdat_path
    mov     r2, #1                   /* read */
    ldr_addr ip, F_OPEN
    blx     ip
    cmp     r0, #0
    beq     9f

    movw    r6, #:lower16:O_COUNT
    movt    r6, #:upper16:O_COUNT
    add     r6, r4, r6
    mov     r0, #0
    str     r0, [r6]                 /* a stale count would read as a success */
    mov     r0, r5
    movw    r1, #:lower16:O_TABLE
    movt    r1, #:upper16:O_TABLE
    add     r1, r4, r1
    movw    r2, #:lower16:TABLE_MAX
    movt    r2, #:upper16:TABLE_MAX
    mov     r3, r6
    ldr_addr ip, F_READ
    blx     ip

    mov     r0, r5
    ldr_addr ip, F_CLOSE
    blx     ip
    mov     r0, r5
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    ldr     r0, [r6]
    pop     {r4, r5, r6, pc}
9:
    mov     r0, #0
    pop     {r4, r5, r6, pc}

lensdat_path:
    .byte   0x5C                     /* a backslash, spelled out so no escaping
                                      * convention can quietly change it */
    .asciz  "LENS.DAT"
    .align  2
