.syntax unified
.arm
.text
.global orient_stub

/* CinemaDNG frames carry no rotation; everything else is untouched.
 *
 * The raw-DNG tag writer asks FUN_c00c9b48 for the EXIF Orientation and stores
 * it as tag 0x112.  Gyroflow takes a DNG sequence's size from the frames but
 * rotates the picture by that tag, so on a portrait take its preview is
 * portrait while its dimensions, lens model and stabilisation maths stay
 * landscape: autosync returns nonsense and no sidecar can reconcile them
 * (gyroflow#1117).  Without the tag every stage agrees and the take stabilises.
 *
 * The call at 0xC00C32C8 comes here instead.  This runs the camera's own getter
 * first and only replaces its answer, so whatever that function does besides
 * returning a number -- it reads the attitude manager, which may be draining
 * something -- still happens on every frame.  The earlier version cleared the
 * manager's support byte so the getter returned early instead; recording then
 * stopped by itself at about twenty seconds, which is the reason this one lets
 * the firmware run to completion.
 *
 * r0-r3 and ip belong to the callee, and r1 is dead at the call site, so only
 * r4 and lr need saving -- an even pair, as the firmware's LDRDs require. */
orient_stub:
    push    {r4, lr}
    movw    ip, #0x9B48
    movt    ip, #0xC00C
    blx     ip                       @ the camera's own answer, side effects and all
    mov     r4, r0
    movw    r0, #0xE08F
    movt    r0, #0xC347              @ MovieRecording, engine selector != 0x21
    ldrb    r0, [r0]
    movw    r1, #0x6609
    movt    r1, #0xC347              @ ...and the other publish target
    ldrb    r1, [r1]
    orrs    r0, r0, r1
    movne   r0, #1                   @ recording: store no rotation
    moveq   r0, r4                   @ idle: leave photographs alone
    pop     {r4, pc}
