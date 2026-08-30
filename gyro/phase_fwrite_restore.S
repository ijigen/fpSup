.syntax unified
.arm
.text

/* Restore the original C03660E8 prologue after any earlier phase-probe boot. */
.word   0xE92D40F0                  /* push {r4, r5, r6, r7, lr} */
