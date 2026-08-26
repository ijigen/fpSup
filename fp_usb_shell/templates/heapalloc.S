.syntax unified
.arm
.text
/* ============================================================================
 * heapalloc — ask the firmware for memory instead of squatting on some.
 * ============================================================================
 *
 * Everything injected here used to live in one megabyte grabbed at boot with
 * `memmgr bufmem get`, carved up by hand: the gyro logger at this offset, the
 * capture buffer at that one, a file staging area after them, and a constant in
 * the host tools saying how big the whole thing was. Nothing checked. A buffer
 * sized to a file could not exceed what was reserved at boot for every purpose
 * at once, and two users of the pool colliding showed up as corrupted data
 * somewhere else entirely.
 *
 * The firmware has a real allocator, and it is what the camera's own code uses.
 * Photo playback asks for ten megabytes to load a still into; the firmware
 * updater asks for thirty-two. Verified here on 2026-08-27 from 64 KiB to
 * 32 MiB: the whole block writes and reads back, and freeing returns the same
 * address next time, so nothing leaks.
 *
 *     heap = FUN_c001cf78(type)                    two-step form, 5 arguments
 *     buf  = FUN_c001d038(heap, size, 0, 0, 0)     -- the fifth goes on the
 *     FUN_c001d2b8(heap, buf)                         stack, so callfn cannot
 *                                                     pass it
 *
 *     FUN_c001d740(desc, type, size, 0)            descriptor form, all four
 *     buf = FUN_c001d7f0(desc)                     in registers -- use this one
 *     FUN_c001d7a0(desc, 2)
 *
 * The descriptor is sixteen bytes of scratch that has to outlive the call: the
 * address is read out of it afterwards, and freeing needs it again. It lives in
 * the parameter block rather than on the stack for that reason.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8. See shellcmd.S.
 *
 * Parameter block, 0xC072F700:
 *      +0x00  operation      host fills: 0 allocate, 1 free
 *      +0x04  heap type      host fills: 10 is what the camera's own code uses
 *      +0x08  size           host fills, bytes
 *      +0x0C  address        written here; zero means the allocator refused
 *      +0xE0  descriptor     sixteen bytes, do not disturb between the two calls
 *
 * High in the block on purpose: getfile puts a NUL-terminated path at +0x24 and
 * a long one would otherwise write straight over it, and a descriptor with
 * somebody's filename in it frees whatever that happens to point at.
 *
 * Refusal is a real answer, not an error: playback wants ten megabytes of its
 * own. Ask for what is needed, hand it back promptly, and check for zero.
 * ========================================================================== */

.equ P,        0xC072F700
.equ P_OP,     0x00
.equ P_TYPE,   0x04
.equ P_SIZE,   0x08
.equ P_ADDR,   0x0C
.equ P_DESC,   0xE0

.equ FMT_S,    0xC0BABB38

.equ H_GET,    0xC001D740     /* (desc, type, size, 0)                        */
.equ H_ADDR,   0xC001D7F0     /* (desc) -> address                            */
.equ H_FREE,   0xC001D7A0     /* (desc, 2)                                    */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, r6, lr}            @ even: AAPCS wants sp 8-byte aligned
    mov     r6, r0                      @ the shell context, for printf
    LDA     r4, P
    add     r5, r4, #P_DESC

    ldr     r0, [r4, #P_OP]
    cmp     r0, #0
    bne     free

    mov     r0, #0                      @ a stale descriptor frees the wrong
    str     r0, [r5]                    @ block, so start from nothing
    str     r0, [r5, #4]
    str     r0, [r5, #8]
    str     r0, [r5, #12]
    str     r0, [r4, #P_ADDR]

    mov     r0, r5
    ldr     r1, [r4, #P_TYPE]
    ldr     r2, [r4, #P_SIZE]
    mov     r3, #0
    LDA     ip, H_GET
    blx     ip

    mov     r0, r5
    LDA     ip, H_ADDR
    blx     ip
    str     r0, [r4, #P_ADDR]

    cmp     r0, #0
    adrne   r1, msg_got
    adreq   r1, msg_none
    b       say

free:
    mov     r0, r5
    mov     r1, #2
    LDA     ip, H_FREE
    blx     ip
    mov     r0, #0
    str     r0, [r4, #P_ADDR]
    adr     r1, msg_freed

say:
    ldr     ip, [r6]
    LDA     r0, FMT_S
    blx     ip

    mov     r0, #0
    pop     {r4, r5, r6, pc}

msg_got:
    .asciz  "heapalloc: address at 0xC072F70C"
    .align  2
msg_none:
    .asciz  "heapalloc: refused"
    .align  2
msg_freed:
    .asciz  "heapalloc: freed"
    .align  2
