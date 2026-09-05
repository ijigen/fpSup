.syntax unified
.arm
.text
/* NOT USED BY THE BUILD -- build_card.py generates .orient_patch.S with the
 * displacement worked out from wherever it is placing orient_stub.
 *
 * This file held 0xEB19AF0C, a `bl 0xC072EF00` written out by hand.  When the
 * stub moved to 0xC072EF40 the word stayed behind, and 0xC072EF00 was by then
 * inside the logger; the raw-DNG tag writer calls it once per frame, so the
 * camera froze the moment a take started.  Kept only so the address that was
 * shipped can be recognised. */
    .word   0xEB19AF0C
