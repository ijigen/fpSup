.syntax unified
.arm
.text

/* C03660E8 -> C072F000.  build/test_phase_probe.py recomputes this word from
 * the two addresses so a moved probe cannot silently leave a stale branch. */
.word   0xEA0F23C4
