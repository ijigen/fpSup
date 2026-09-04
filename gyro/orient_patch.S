.syntax unified
.arm
.text
/* One word over the `bl FUN_c00c9b48` in the raw-DNG tag writer, so the
 * Orientation it stores comes from orient_stub (0xC072EF00) instead. */
    .word   0xEB19AF0C
