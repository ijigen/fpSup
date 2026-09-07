.syntax unified
.arm
.text
.global gsup_entry

/* ============================================================================
 * gsup_entry -- forty bytes in the cave, so the boot code can live in the pool.
 * ============================================================================
 *
 * \VSHL.BIN names an entry to branch to once every section is placed, and that
 * has to be an absolute address decided when the card is built.  The code that
 * actually sets the stream up is four kilobytes and lives in the pool, whose
 * address the camera only decides at boot.  This is the one piece that has to
 * be in the cave, and all it does is close that gap.
 *
 * It reads the routine table at the top of the blob -- the same table gsup_boot
 * reads -- so nothing here needs to know how big anything is.
 *
 * stage2 restores lr before it branches here, so returning goes back to the
 * loader and the boot carries on as if nothing happened.  Which is the point:
 * if there is no pool, or the card carries a blob that was never patched, this
 * returns having done nothing and the camera is an ordinary camera.
 * ========================================================================== */

.equ FRAMEBUF,      0xC3757A7C      /* [0] = the camera's DMA pool */
.equ CODE_POOL_OFF, 0x44000         /* where stage2 was told to put the blob */
.equ O_GSUP_BOOT,   0x18            /* the table's seventh word */

gsup_entry:
    push    {r4, lr}
    movw    r0, #:lower16:FRAMEBUF
    movt    r0, #:upper16:FRAMEBUF
    ldr     r0, [r0]
    cmp     r0, #0
    beq     9f                          @ no pool: the blob is not there either
    add     r0, r0, #CODE_POOL_OFF
    ldr     r1, [r0, #O_GSUP_BOOT]
    cmp     r1, #0
    beq     9f                          @ an unpatched table: do nothing at all
    add     r1, r0, r1
    blx     r1
9:  pop     {r4, lr}
    bx      lr
