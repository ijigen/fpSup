.syntax unified
.arm
.text
/* ============================================================================
 * shellcmd — run code in task context by borrowing a shell command.
 * ============================================================================
 *
 * The other way to get code running, and the better one whenever the code has
 * to block.  `oneshot.S` borrows the gyro callback, which runs interrupt-ish:
 * no blocking, no mutexes, so anything real has to start a task -- and a task
 * that finishes has nowhere to go, because ext_tsk's stub is not in the
 * firmware's syscall table and returning from a task entry is undefined.
 *
 * A shell command handler has neither problem.  The shell's own `dir`, `mkdir`
 * and `sdcard` commands do file I/O, so the dispatcher's task may block; and a
 * handler is an ordinary function that returns.
 *
 * The command table is 77 entries of {char name[0x14]; void *handler} at
 * 0xC0BAC14C, stride 0x18, so the handler pointer for entry n is at
 * 0xC0BAC14C + n*0x18 + 0x14.  `echo` is entry 17, pointer 0xC0BAC2F8,
 * currently 0xC03D99A0 -- borrowed here because nothing depends on it.
 *
 *     ./fpsh mem set 0xC0BAC2F8 0xC072F600     point it at this code
 *     ./fpsh echo                              run it, synchronously
 *     ./fpsh mem set 0xC0BAC2F8 0xC03D99A0     put it back
 *
 * Handler signature, from disassembling echo's own body:
 *
 *     r0  context; [r0] is printf(fmt, ...) so output goes back to the host
 *     r1  argument count
 *     r2  argument vector, r2[i] is a NUL-terminated string
 *
 * Restore the pointer when finished.  A handler left pointing into the cave is
 * a command that jumps into whatever gets injected there next.
 * ========================================================================== */

.equ FMT_S,   0xC0BABB38          /* "%s " — the format echo itself uses */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    /* An even number of registers, deliberately.  AAPCS wants the stack eight
     * byte aligned at a call, and pushing an odd count leaves it four -- which
     * costs nothing until the callee reaches an LDRD, and then it is a data
     * abort with the shell task holding the dispatcher. */
    push    {r4, r5, r6, lr}
    mov     r4, r0                  @ context
    mov     r5, r2                  @ argv

    /* Print one line back to the host, so the command shows it ran. */
    ldr     ip, [r4]
    LDA     r0, FMT_S
    adr     r1, message
    blx     ip

    mov     r0, #0
    pop     {r4, r5, r6, pc}

message:
    .asciz  "shellcmd template ran"
    .align  2
