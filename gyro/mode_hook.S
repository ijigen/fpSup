.syntax unified
.arm

#include "ring_task.inc.S"

.text
.global mode_hook

/* The STILL/CINE mode being set -- the only moment early enough to decide what
 * a take's frames will say about which way up they are.
 *
 * A CinemaDNG frame's EXIF Orientation comes from FUN_c00c9b48, and its first
 * line is `if (the Level object's +0x30 byte is 0) return 1`, which is
 * landscape upright.  So clearing that byte makes every frame of every take
 * landscape upright without a patch anywhere in the recording path.
 *
 * WHY NOT AT RECORD START.  That was tried, on this camera, and it does not
 * work: a portrait take's first frame still read Orientation 8 with the hook
 * demonstrably run -- fourteen blocks handed over, the .json written, the byte
 * saved and restored.  Whatever consumes it has consumed it before our record
 * hook at 0xC03790B8 runs.  Setting the mode is minutes earlier and nothing
 * happens between it and the take.
 *
 * The other thing that was tried is worse, and is why this is a hook at a
 * moment rather than a byte held down: a version that cleared the byte and
 * left it cleared made recording stop by itself at about twenty seconds (see
 * orient_stub.S).  Here the camera is not recording when the byte changes, and
 * it changes once.
 *
 * WHY NOT DelayableStillCineSwitch::v1.  That was tried too, and never fired.
 * The delayable is the DEFERRED path: an event handler asks FUN_c0499e20
 * whether the switch is blocked and only queues a delayable when it is --
 * StandbyEventHandler_w71c1::v5 does the switch itself in the other branch,
 * which is the branch a person flipping the switch takes.  G_MODE_N was 0
 * after a flip each way, which is exactly the reading that separates "the
 * encoding is the other way round" from "this code never ran".
 *
 * FUN_c0058308 is where every one of those paths ends up: it is the setter
 * paired with FUN_c0058340, the getter the whole firmware asks for the mode --
 * both reach the same sub-object through vtable slot +0x10.  r1 is the value
 * being set, in that same encoding.
 *
 * Which of 0 and 1 is CINE is not decidable from the decompilation: all
 * sixty-seven uses of that value are symmetric.  So the hook records what it
 * saw and how many times, and MODE_CINE is filled in from one flip of the
 * switch.  Left negative it only watches.
 *
 * The site is 0xC0058310, `mov r5, r1` = 0xE1A05001, one instruction past a
 * prologue that has already pushed lr -- so lr is free, and the displaced
 * instruction runs on the way out. */
mode_hook:
    push    {r0, r1, r2, r3, r12, lr}   @ six registers: the stack stays 8-aligned
    movw    r2, #:lower16:G_MODE
    movt    r2, #:upper16:G_MODE
    str     r1, [r2]                    @ the last mode we saw set
    ldr     r3, [r2, #4]
    add     r3, r3, #1
    str     r3, [r2, #4]                @ and how many there have been

.if MODE_CINE >= 0
    cmp     r1, #MODE_CINE
    moveq   r3, #0                      @ into cine: nothing rotates
    movne   r3, #1                      @ back to stills: the camera's own answer
    movw    r2, #:lower16:LEVEL_GATE
    movt    r2, #:upper16:LEVEL_GATE
    strb    r3, [r2]
.endif

    pop     {r0, r1, r2, r3, r12, lr}
    mov     r5, r1                      @ the instruction ARM_MODE replaced
    bx      lr
