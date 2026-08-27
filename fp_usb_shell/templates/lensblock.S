.syntax unified
.arm
.text
/* ============================================================================
 * lensblock — read one data block out of the mounted lens.
 * ============================================================================
 *
 * The L-mount bus is shared with the camera's own periodic lens polling, and
 * reading it out of band returns all-0xFF and trips the "鏡頭異常" warning on
 * screen. What is missing is not an unlock command but a mutex, and the
 * firmware's own accessor takes it: FUN_c03554a0() hands back the context and
 * FUN_c0355de0(ctx, id, dst) does the locked read.
 *
 * Blocks are addressed by id, not by address. FUN_c0355e10 indexes a ROM table
 * at 0xC0B94364, stride 0x0C, {addr, len, flag}; ids run 0x00-0x51. A flag of 1
 * means the firmware will refuse. The length is read from that table here so the
 * host knows how much came back without having to keep its own copy.
 *
 * `ok` means the transaction completed, not that there is data: CmdRead clears
 * the destination first, so an all-zero block is a lens that genuinely has
 * nothing at that id.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8. See shellcmd.S.
 *
 * Parameter block, 0xC072F700:
 *      +0x00  block id          host fills
 *      +0x04  destination       host fills -- blocks reach 2101 bytes, which is
 *                               not going to fit beside the parameters
 *      +0x08  ok                written here
 *      +0x0C  length            written here, from the ROM table
 *
 * Read with the camera idle. The mutex is held for the length of the read, and
 * the camera wants it back for its own polling.
 * ========================================================================== */

.equ P,        0xC072F700
.equ TABLE,    0xC0B94364     /* {addr, len, flag} per id, stride 0x0C        */
.equ F_CTX,    0xC03554A0     /* () -> the lens comms context                 */
.equ F_READ,   0xC0355DE0     /* (ctx, id, dst) -> ok; takes the bus mutex    */
.equ FMT_S,    0xC0BABB38

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r8, r0                      @ shell context, for printf
    LDA     r4, P
    ldr     r5, [r4]                    @ block id
    ldr     r6, [r4, #4]                @ destination

    LDA     r0, TABLE
    add     r0, r0, #4                  @ the len field of entry zero
    mov     r1, #0xC
    mla     r0, r5, r1, r0
    ldr     r7, [r0]                    @ its length
    mov     r0, #0
    str     r0, [r4, #8]                @ ok, until it is
    str     r7, [r4, #0xC]

    LDA     r12, F_CTX
    blx     r12
    mov     r1, r5
    mov     r2, r6
    LDA     r12, F_READ
    blx     r12
    str     r0, [r4, #8]

    ldr     ip, [r8]
    LDA     r0, FMT_S
    adr     r1, msg
    blx     ip
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

msg:
    .asciz  "lensblock: ok and length at 0xC072F708"
    .align  2
