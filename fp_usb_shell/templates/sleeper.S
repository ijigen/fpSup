/* Where the loader's task goes when there is no shell to become.
 *
 * The loader ends by branching to the entry the binary names, because a task
 * cannot return here -- tk_ext_tsk is not in the syscall table. In the build
 * that carries the USB shell that entry is the shell's serve loop. In the
 * shipping build there is no shell, and a task that spins would burn a core at
 * priority 28 for the life of the camera, so it sleeps instead: a second at a
 * time, forever, costing nothing.
 */
    .syntax unified
    .arm

    .global sleep_forever
sleep_forever:
1:  mov     r0, #1000
    movw    ip, #0x05D8
    movt    ip, #0xC037                 /* dly_tsk */
    blx     ip
    b       1b
