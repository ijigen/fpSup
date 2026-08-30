.syntax unified
.arm
.text
.global gyro_hook

/* SIGMA fp Ver.5.02 Streaming gyro logger.
 * Hook: 0xC00D0794, load: 0xC072DE64.
 * Buffer A/B are 256 KiB each inside the validated 8 MiB USER allocation.
 * The gyro thread only copies. A dedicated firmware thread writes READY blocks.
 */

/* Buffers are sized to the write latency they have to cover, not to the length
 * of the take. A single SD write during recording was measured at 692 ms worst
 * case (notes/SD_WRITE_LATENCY_MEASURED.md); covering that needs about 14 KB at
 * 20 KB/s, so each half is 16 KiB -- 0.82 s of gyro at 2500 Hz x 8 B. The writer
 * thread drains a READY half while the hook fills the other, so the length of a
 * take stops being a memory question at all.
 *
 * That is also what makes the log survive an unexpected power cut. The previous
 * design held the whole take in RAM and wrote at record stop, so a flat battery
 * lost everything. Here each full block is on the card within a second of being
 * filled, carrying a GFB6 magic, a sequence number and a CRC-32 so it can be
 * carved back out even if the directory entry never gets committed. */

/* Addresses live in the bufmem pool, past everything the USB shell owns. The
 * shell's own regions are the frame buffer at +0x0000 and its capture buffer at
 * +0x2000; BUF_A used to sit at +0x1240, right on top of the capture buffer, and
 * before that at the pool base itself, where it read back as ASCII "FPSH".
 *
 *   +0x6000  state, 256 B      +0x6100  path, 256 B
 *   +0x6200  header, 512 B     +0x6400  file object, 3 KiB
 *   +0x7000  BUF_A, 16 KiB     +0xB000  BUF_B, 16 KiB      +0xF000  end
 *
 * The state block and the path used to overlap: S_STOP is at +0x60 and FILE_PATH
 * was STATE+0x60, so writing the path cleared the stop flag and writer_close's
 * final `str r0, [r10, #S_STOP]` zeroed the path's first character. */
/* Offsets from the pool, not addresses.  The pool moved from 0x44F6ADC0 to
 * 0x45026680 the moment the AutoRun asked for 64 KiB instead of 4 -- the
 * allocator simply returns somewhere else -- so every hard-coded address in
 * here was already wrong and would have written into whatever now lives there.
 * The base is read from 0xC3757A7C at run time; everything else is r10 plus a
 * displacement. */
.equ POOL_PTR,        0xC3757A7C
.equ O_STATE,         0x6000      /* r10 points here                        */
.equ O_PATH,          0x0100      /* from r10                               */
.equ O_POST_PATH,     0x0120      /* immutable path of the queued job       */
.equ O_POST_START,    0x0140
.equ O_POST_MODE,     0x0144
.equ O_POST_W,        0x0148
.equ O_POST_H,        0x014C
.equ O_POST_VOLUME,   0x0150      /* immutable volume of the queued job       */
.equ O_LC_STATE,      0x0154      /* PGEN-owned: 0 idle, 1 pending, 3 final,
                                     4 established, 6 publishing              */
.equ O_LC_VOLUME,     0x0158      /* explicit volume: 1 SD, 5 USB SSD         */
.equ O_LC_KIND,       0x015C      /* lifecycle adapter: 1 CDNG, 2 MOV         */
.equ O_LC_GEN,        0x0170      /* PGEN-owned publication generation        */
.equ O_LC_ATTACH,     0x017C      /* callback-owned attached generation       */
.equ O_HEADER,        0x0200
.equ O_FOBJ,          0x0400
.equ O_FOBJ2,         0x0800      /* the gcsv, open while the .GYR is read back */
.equ O_GCSV_PATH,     0x0180      /* its path, beside the .GYR's                */
.equ O_BUF_A,         0x1000
.equ O_BUF_B,         0x5000
.equ BUF_SIZE,        0x00004000
.equ BLOCK_HEADER,    32
.equ PAYLOAD_CAP,     0x00003FE0
.equ F_MGR,           0xC0444658
.equ F_VOL,           0xC0444698
.equ F_CTOR,          0xC0365E90
.equ F_OPEN,          0xC0365FB0
.equ F_READ,          0xC0366060
.equ F_WRITE,         0xC03660E8
.equ F_CLOSE,         0xC0366020
.equ F_DTOR,          0xC0365ED0
.equ ACCEL_CACHE,     0xC377790C  /* i16 X, Y, Z, axis-remapped by the firmware */
.equ ACCEL_REC,       12          /* u32 us, i16 x, i16 y, i16 z, i16 pad       */
.equ ACCEL_ZONE,      0x0400      /* the accel records grow in their own end of  */
.equ ACCEL_BASE,      0x3C00      /* the buffer: BUF_SIZE - ACCEL_ZONE           */
.equ GYRO_CAP,        0x3BE0      /* ACCEL_BASE - BLOCK_HEADER                   */
.equ O_TEXT,          0x1A000     /* pool+0x20000: the gcsv's text, at the stop.
                                     It used to borrow O_BUF_B, which is sixteen
                                     kilobytes, so the text went to the card every
                                     fifteen -- forty writes for one take, landing
                                     while the camera finalises its own clip. The
                                     recording is over by then and the pool has
                                     896 KB nobody uses, verified across a
                                     recording 224 markers out of 224.          */
.equ TEXT_FLUSH,      0x4000      /* 16 KiB. It was 256, to make three writes of
                                     what had been forty -- but each of those
                                     three held the volume for as long as it took
                                     to put a quarter megabyte on the card, and
                                     the camera's own file task cannot preempt a
                                     mutex. Short holds beat few holds when
                                     something at priority 6 is waiting.        */
.equ O_READ,          0x5B000     /* pool+0x61000, past the text buffer         */
.equ READ_SIZE,       0x10000     /* 64 KiB, for the same reason as TEXT_FLUSH   */
.equ O_PROFILE,       0x9000      /* the gap between the block buffers and the
                                   * gcsv's text: 68 KiB, which is where the
                                   * whole \LENS.DAT goes -- one Gyroflow profile
                                   * per sensor mode the camera can record in.
                                   * A single profile would have to be told which
                                   * mode to expect, and would quietly write
                                   * nothing on any other. The table cannot.   */
.equ PROFILE_MAX,     0x10000      /* what tableload.S reads in, so a directory
                                   * entry past it is refused rather than read */
.equ PROFILE_MAGIC,   0x5441444C  /* "LDAT", the same file lensdat.py leaves on
                                   * the card: header, directory, then the text */
.equ PROFILE_DIR,     48          /* the directory follows the header           */
.equ O_END,           0xF000      /* the logger owns r10-0x6000 .. +0xF000 */
.equ HOOK_SITE,       0xC00D0794  /* where the callback branches here from     */
.equ HOOK_ORIG,       0xFA046FD7  /* the instruction it replaced               */
.equ F_CACHE,         0xC000E91C  /* CP15 maintenance after placing code       */
.equ GYRO_DESC_PTR,   0xC31E3FCC
.equ XMP_FOBJ_PTR,    0xC358E140  /* native SPP_metadata.xmp file object    */
.equ MOV_ACTIVE_PTR,  0xC35A952C  /* MOV path valid through ImageSave       */
.equ MOV_BUSY_PTR,    0xC38D2DE8  /* native MOV writer, cleared after commit */

/* The unused tail of the 512-byte header area is a seven-entry post-process
 * queue.  The producer of this queue is the writer itself, after close_file;
 * the callback never touches it.  A new take may therefore replace O_PATH and
 * the live geometry without losing the files still owed to earlier takes. */
.equ O_POST_QUEUE,    0x02A0
.equ Q_HEAD,          0x00
.equ Q_DROPPED,       0x04
.equ Q_OPEN_TRIES,    0x08
.equ Q_OPEN_DELAY,    0x0C
.equ Q_JOBS,          0x10
.equ Q_CAP,           7
.equ Q_JOB_SIZE,      0x30
.equ J_FLAGS,         0x00       /* bit 0 gcsv done, bit 1 json done */
.equ J_ATTEMPTS,      0x04
.equ J_CLOSE_TICK,    0x08
.equ J_START_US,      0x0C
.equ J_MODE,          0x10
.equ J_W,             0x14
.equ J_H,             0x18
.equ J_PATH,          0x1C       /* 20 bytes, including NUL */
.equ POST_RETRIES,    12

/* STATE word offsets. */
.equ S_THREAD,        0x00
.equ S_ACTIVE,        0x04
.equ S_FILE,          0x08  /* 0 closed, 1 open request, 2 open, 3 abort/closing,
                              4 callback is preparing a new take              */
.equ S_INDEX,         0x0C
.equ S_HEAD,          0x10
.equ S_DROPPED,       0x14
.equ S_NEXTSEQ,       0x18
.equ S_ERROR,         0x1C
.equ S_A_STATE,       0x20  /* 0 empty, 1 filling, 2 ready, 3 writing */
.equ S_A_FIRST,       0x28
.equ S_A_LAST,        0x2C
.equ S_A_SEQ,         0x30
.equ S_A_FLAGS,       0x34
.equ S_A_GYRO,        0x38        /* gyro bytes alone; count must not include accel */
.equ S_A_ACC,         0x3C        /* accel record COUNT, in the zone at the end     */
.equ S_B_STATE,       0x40
.equ S_B_FIRST,       0x48
.equ S_B_LAST,        0x4C
.equ S_B_SEQ,         0x50
.equ S_B_FLAGS,       0x54
.equ S_B_GYRO,        0x58
.equ S_B_ACC,         0x5C
.equ S_STOP,          0x60
.equ S_MAGIC,         0x64        /* 'S6G6' once the block has been initialised */
.equ S_LIMIT,         0x68        /* one past the end of the buffer being filled */
.equ S_CLAMPED,       0x6C        /* bytes copy_span refused to write past it   */
.equ S_STOP_T0,       0x70        /* TickTimer when the stop was noticed        */
.equ S_STOP_T1,       0x74        /* TickTimer when the file was closed         */
.equ S_STOP_BLOCKS,   0x78        /* blocks still to write when the stop landed */
.equ S_PARK,          0x7C        /* host asks the writer to step out of the cave */
.equ S_PARKED,        0x80        /* writer confirms it is parked                 */
.equ S_WRITER_PC,     0x84
.equ S_START_US,      0x88        /* the header buffer is reused for the footer */
.equ S_RD_END,        0x90        /* end of the valid data in the read buffer   */
.equ S_RD_EOF,        0x94
.equ S_GEOM_W,        0x98        /* the recording geometry, read at record start */
.equ S_GEOM_H,        0x9C
.equ S_POST_BUSY,     0xA0        /* 0 idle, 1 generator running, 2 cancel it   */
.equ S_MODE_N,        0xA4        /* entries used in the mode history below       */
.equ S_DELAY,         0xF4        /* polls to wait before touching the card   */
.equ S_POOL_TRIED,    0xFC        /* the pool code has been asked for once    */
.equ S_GCSV_FN,       0xF8        /* the gcsv builder, in the pool            */
.equ S_JSON_FN,       0xF0        /* the profile generator, in the pool       */
.equ S_POST_COUNT,    0xAC        /* queued .gcsv/.json jobs                    */
.equ S_MODE_RUN,      0xA8        /* the mode while the file was open and no stop
                                   * pending -- the take's own mode, where the
                                   * last sample of all lands after the stop with
                                   * the camera already back in live view        */
.equ S_MODE_HIST,     0xB0        /* 8 x {TickTimer, mode}; ends at 0xF0, and the
                                   * state block has to stay under O_PATH = 0x100 */
.equ MODE_OBJ,        0xC343B588  /* FUN_c0322e88() returns this; verified live.
                                   * +4 is the mode now, +8 the one before it --
                                   * the pair the firmware's own --mode_change--
                                   * trace prints in ImagerMode.cpp. Reading the
                                   * words directly skips the lazy-singleton
                                   * getter, so this is two loads and safe to do
                                   * on the writer's 5 ms poll. */
.equ F_MODE_NOW,      0xC032C720  /* () -> the current sensor mode enum         */
.equ GEOMETRY,        0xC37CE210  /* {width, height, frame bytes} while recording */        /* the .GYR has nothing more to give          */
.equ S_READ_N,        0x8C        /* where read() drops its byte count          */        /* where to resume once the body is replaced    */
.equ PARK_STUB,       0xC072EFB4  /* as high as it fits: the payload grew into the
                                   * old 0xC072EF00, and code that overwrites the
                                   * stub while the writer is parked in it is a
                                   * freeze. Moving it needs two loads -- one that
                                   * still ends below the old address, then the
                                   * real one. See templates/park.S              */

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm


/* Sits before the entry point rather than with the rest of the data: the hook
 * reaches it with `adr` and the payload outgrew that instruction's range.
 * Nothing executes into it -- the callback branches straight to gyro_hook. */
boot_pool:
    .word   0

/* Load the state block address: the bufmem pool, plus the span the USB shell
 * owns (its frame buffer at +0, its capture buffer at +0x2000). */
.macro pool_state reg
    ldr_addr \reg, POOL_PTR
    ldr     \reg, [\reg]
    add     \reg, \reg, #O_STATE
.endm

gyro_hook:
    push    {r3-r11, lr}

    /* Original instruction replaced at 0xC00D0794. */
    movw    ip, #0xC6F9
    movt    ip, #0xC01E
    blx     ip
    mov     r11, r0

    /* Stand down if this is not the boot that armed us.
     *
     * The shell's loader puts the firmware's own instruction back the moment it
     * has run; this branch stays in place for the life of the session. A soft
     * power-off that does not reload the firmware image therefore comes back up
     * with the callback still pointing here, and the pool pointer belonging to
     * a session that is over -- so the state block would be written over
     * whatever now lives at that address, during the camera's own start-up.
     *
     * The shell alone survives ten power cycles; with the logger the next start
     * fails until the battery comes out, and pulling the card does not help,
     * which puts it in RAM rather than on the card. This is the one thing the
     * logger leaves behind that the shell does not.
     *
     * boot_pool is part of the payload, so the loader rewrites it to zero on
     * every boot that actually runs the AutoRun. First call: remember what the
     * pool was. Later calls: if it moved, the AutoRun did not run, and the only
     * safe thing to do is put the firmware's instruction back and disappear. */
    ldr_addr r10, POOL_PTR
    ldr      r10, [r10]
    adr      r9, boot_pool
    ldr      r8, [r9]
    cmp      r8, #0
    streq    r10, [r9]
    beq      1f
    cmp      r8, r10
    bne      hook_stand_down
1:
    pool_state r10

    /* Initialise the block ourselves, once, rather than trusting the host to
     * have zeroed it.  Pool memory is whatever the last thing there left, so
     * S_THREAD read at boot is a task id only by accident -- and clearing it by
     * hand between reloads created a second writer thread every time, both
     * polling the same buffers.  Two are running on the camera as this is
     * written and there is no way to stop them short of a power cycle: `tkos
     * task` offers chgpri and nothing else. */
    ldr     r0, [r10, #S_MAGIC]
    movw    r1, #0x4736
    movt    r1, #0x4153              /* 'SAG6': single-writer lifecycle revision */
    cmp     r0, r1
    beq     block_ready
    mov     r0, #0
    mov     r2, #0
14: str     r0, [r10, r2]
    add     r2, r2, #4
    cmp     r2, #0x200               @ includes path and lifecycle adapter state
    blo     14b
    str     r1, [r10, #S_MAGIC]
    add     r2, r10, #O_POST_QUEUE
    mov     r0, #0
    str     r0, [r2, #Q_HEAD]
    str     r0, [r2, #Q_DROPPED]
    str     r0, [r2, #Q_OPEN_TRIES]
    str     r0, [r2, #Q_OPEN_DELAY]
block_ready:

    ldr     r0, [r10, #S_THREAD]
    cmp     r0, #0
    bne     thread_ready
    bl      start_writer_thread
thread_ready:
    /* A native file-open event must be able to cancel a slow lens/profile call
     * immediately.  These are RAM-only adapter signals; neither one decides a
     * gyro boundary here.  The low-priority lifecycle watcher publishes that
     * boundary only after it has a stable clip id and explicit volume. */
    ldr_addr r0, XMP_FOBJ_PTR
    ldr     r0, [r0]
    cmp     r0, #0
    bne     native_clip_busy
    ldr_addr r0, MOV_ACTIVE_PTR
    ldrb    r0, [r0]
    cmp     r0, #0
    beq     native_clip_checked
native_clip_busy:
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #0
    movne   r0, #2
    strne   r0, [r10, #S_POST_BUSY]
native_clip_checked:
    /* Native lifecycle owns identity, volume and finalize, but XMP allocation
     * is earlier than actual recording. r5 attached there and moved every GYR
     * media operation into CinemaDNG's most sensitive start-up window. Keep the
     * proven MovieRecording flag as the start gate; once attached, native phase
     * 3 still owns stop so the GYR never closes during native finalization. */
    movw    ip, #0xB2D0
    movt    ip, #0xC035
    blx     ip
    ldrb    r5, [r0, #0x157]
    ldr     r7, [r10, #S_ACTIVE]
    cmp     r7, #1
    bne     recording_not_active
    ldr     r0, [r10, #O_LC_STATE]
    cmp     r0, #3                  @ adapter says native finalize completed
    beq     recording_stopped
    b       drain_ring

recording_not_active:
    /* ACTIVE 2 waits for the old object to close.  A fresh READY generation may
     * then start directly; the core does not care whether it came from the DNG
     * or MOV adapter. */
    /* CDNG/MOV may already have published a descriptor while the camera is
     * still preparing. Do not claim it until recording itself is live. */
    cmp     r5, #0
    beq     return_original
    /* Do not start a new take until the previous writer has closed. */
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     return_original
    /* O_LC_STATE is written only by PGEN.  Claim S_FILE first, then validate
     * the published phase and latch its generation in a callback-owned word.
     * PGEN uses state 6 while publishing and rechecks S_FILE after doing so;
     * the two intent words therefore close the cross-core window without an
     * LDREX/STREX against DMA-backed bufmem (which faults on this camera). */
    ldr     r7, [r10, #O_LC_STATE]
    cmp     r7, #1
    beq     recording_attach_claim
    cmp     r7, #4
    bne     return_original
recording_attach_claim:
    mov     r0, #4                  @ PREPARING: block a new PGEN publication
    str     r0, [r10, #S_FILE]
    dmb     ish
    ldr     r6, [r10, #O_LC_GEN]
    ldr     r0, [r10, #O_LC_STATE]
    cmp     r0, #1                  @ CDNG opening: buffer in RAM only
    beq     recording_attach_valid
    cmp     r0, #4                  @ CDNG established, or native MOV open
    bne     recording_attach_cancel
recording_attach_valid:
    dmb     ish                     @ acquire GEN/path published before phase
    ldr     r0, [r10, #O_LC_GEN]
    cmp     r0, r6                  @ reject a publication completed mid-claim
    bne     recording_attach_cancel
    str     r6, [r10, #O_LC_ATTACH]
    b       recording_started
recording_attach_cancel:
    mov     r0, #0
    str     r0, [r10, #S_FILE]
    b       return_original

recording_started:
    /* Cancel an idle post-process job before it can reuse either file object.
     * FILE=PREPARING closes the check/set window in the writer: after this
     * publication it may finish the current media call, but it cannot begin a
     * new one for the old take. */
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #0
    movne   r0, #2
    strne   r0, [r10, #S_POST_BUSY]
#ifdef FPGYRO_PHASE_PROBE
    /* Initialise every probe word before ACTIVE makes the take visible to the
     * separate CinemaDNG writer task.  Clearing these after ACTIVE would leave
     * a small window in which its first edge could be recorded and erased. */
    mov     r0, #0
    str     r0, [r10, #S_MODE_N]
    str     r0, [r10, #S_STOP_T0]
    str     r0, [r10, #S_STOP_T1]
    str     r0, [r10, #S_STOP_BLOCKS]
#endif
    mov     r0, #1
    str     r0, [r10, #S_ACTIVE]
    mov     r0, #0
    str     r0, [r10, #S_INDEX]
    str     r0, [r10, #S_DROPPED]
    str     r0, [r10, #S_NEXTSEQ]
    str     r0, [r10, #S_ERROR]
#ifndef FPGYRO_PHASE_PROBE
    str     r0, [r10, #S_MODE_N]
#endif
    str     r0, [r10, #S_MODE_RUN]
    str     r0, [r10, #S_STOP]
    str     r0, [r10, #S_A_GYRO]
    str     r0, [r10, #S_A_ACC]
    str     r0, [r10, #S_A_FLAGS]
    str     r0, [r10, #S_B_GYRO]
    str     r0, [r10, #S_B_ACC]
    str     r0, [r10, #S_B_FLAGS]
    add     r2, r10, #O_POST_QUEUE
    str     r0, [r2, #Q_OPEN_TRIES]
    str     r0, [r2, #Q_OPEN_DELAY]
    mov     r1, #1
    str     r1, [r10, #S_A_STATE]
    str     r0, [r10, #S_B_STATE]

    /* Record-start monotonic timestamp. */
    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    mov     r6, r0

    /* O_PATH, adapter kind and volume were assembled and published together by
     * the writer task.  The 2500 Hz callback does not touch a media manager. */

    /* GFS6 64-byte file header. */
    add     r9, r10, #O_HEADER
    movw    r0, #0x4647
    movt    r0, #0x3653              /* GFS6 */
    str     r0, [r9, #0]
    mov     r0, #5                   /* v5: explicit clip id, volume, adapter */
    str     r0, [r9, #4]
    movw    r0, #2500
    str     r0, [r9, #8]             /* sample_rate_hz */
    movw    r0, #400
    str     r0, [r9, #12]            /* sample_period_us */
    str     r6, [r9, #16]
    str     r6, [r10, #S_START_US]   @ the header gets overwritten by the footer

    /* What the camera is actually recording.
     *
     * Reads as zeros when idle, which is why it can only be sampled here. The
     * profile needs the output width, and a DNG frame is the only other place
     * it appears -- so taking it now is what would let the camera write its own
     * lens profile, and lets decode.py stop needing a frame to find the size.
     *
     * Recorded, not used, until it has been seen to hold something. */
    ldr_addr r0, GEOMETRY
    ldr     r1, [r0]
    str     r1, [r10, #S_GEOM_W]
    ldr     r1, [r0, #4]
    str     r1, [r10, #S_GEOM_H]
    add     r0, r10, #O_PATH
    add     r0, r0, #6               @ "A001_037" from "\\GYRO\\..."
    ldr     r1, [r0]
    str     r1, [r9, #20]
    ldr     r1, [r0, #4]
    str     r1, [r9, #24]
    ldr     r0, [r10, #O_LC_VOLUME]
    strb    r0, [r9, #28]
    ldr     r0, [r10, #O_LC_KIND]
    strb    r0, [r9, #29]
    mov     r0, #0
    strh    r0, [r9, #30]
    /* "xyz", all three axes negated -- the chip is mounted 180 degrees to the
     * camera. Verified one column at a time on three single-axis takes; the
     * archived "YxZ" came from absolute correlation coefficients, which fix the
     * axis pairing and say nothing about sign, and it amplifies shake 1.9x. */
    movw    r0, #0x7978
    movt    r0, #0x007A
    str     r0, [r9, #32]
    /* 0.000137923, not the archived 0.000121385. Optical flow measures the
     * product focal_px x gscale, so splitting it needs a focal from somewhere
     * else; the old split used a focal fitted from the same data and let the
     * focal error hide inside gscale. Re-split against the firmware's own mode
     * table it lands 3.5% off the 131 LSB/dps datasheet figure instead of 13.6%. */
    movw    r0, #0x9F6C
    movt    r0, #0x3910
    str     r0, [r9, #36]
    mov     r0, #0
    str     r0, [r9, #40]
    str     r0, [r9, #44]
    str     r0, [r9, #48]
    str     r0, [r9, #52]
    str     r0, [r9, #56]
    str     r0, [r9, #60]

    /* Sensor mode and exposure, so the clip carries what the lens profile needs.
     *
     * 1080p at 29.97 matches two sensor modes -- enum 106 and enum 111, both
     * 3032x1708 full width -- and they differ only in readout: 10557 us against
     * 7828. `imager mode_list` prints both; only the clip itself can say which
     * one it was shot in, and asking the shell during a recording disturbs the
     * recording.
     *
     * FUN_c0322e48(0) is the accessor `imager mode_list` uses. Its object holds
     * the monitor mode at +4 -- which matched mode_now's enum exactly -- and a
     * second mode at +8, which reads 106 while idle. The LiveView object this
     * used to read gave 175, a name the firmware knows (MONIT1_60_FHD_CROP) but
     * which is not in the seventy-row timing table at all, so it was never the
     * sensor mode. The earlier logger called that object the mode table; it
     * isn't, and copying the comment instead of checking cost an afternoon.
     *
     * The exposure is FUN_c030c7f0, a vtable fetch off the sensor-timing object.
     * It is not the readout -- across four takes it returned only 7989 or 16654
     * us, which are 1/125 s and 1/60 s -- but AF consumes it as exposure/2 to
     * find the centre of the exposure, and per-clip exposure is worth having. */
    /* FUN_c032c720() -- no arguments -- returns the current sensor mode enum.
     * It is what `imager mode_now` prints, verified against it live: both said
     * 8 for MONIT1_60.
     *
     * Two wrong sources came before it. The LiveView object at 0xC375D840+8
     * gives 175, a name the firmware knows (MONIT1_60_FHD_CROP) but which is not
     * in the seventy-row timing table at all -- the earlier logger called that
     * object the mode table and it is not one. FUN_c0322e48(0)'s object gives
     * the monitor mode at +4 and, at +8, 106 while idle and 56 while recording;
     * 56 is 2016x1344, and that geometry family has no 29.97 mode at all, so it
     * was the monitor being raised to 120 Hz for the duration, not the sensor.
     *
     * Which matters because 1080p29.97 12-bit has four candidates -- 106 and 111
     * at 3032x1708, 107 and 112 at 2088x1174 -- whose readouts run from 5.4 to
     * 10.6 ms, and the output geometry scales evenly from either family so it
     * cannot tell them apart. Only the clip can. */
    movw    ip, #0xC720
    movt    ip, #0xC032
    blx     ip
    str     r0, [r9, #48]

    movw    ip, #0xC7F0
    movt    ip, #0xC030
    blx     ip
    str     r0, [r9, #56]

    /* The lens's distortion support points, straight after the header.
     *
     * The firmware holds only the interpolation engine -- a 17-point radial map
     * in Q15, piecewise linear -- and the coefficients come from the lens at
     * boot, interpolated for the focus distance and focal length in force at the
     * time. So they belong to the take, like the sensor mode, and reading them
     * afterwards gets whatever the lens was left focused at.
     *
     * Ninety-six bytes of the region rather than a chosen window: two tables sit
     * here, one of them the identity, and picking between them is the decoder's
     * job. Copying blind keeps this end simple and honest. */
    movw    r0, #0xD876
    movt    r0, #0xC2F2
    add     r1, r9, #64
    mov     r2, #0
4:  ldrb    r3, [r0, r2]
    strb    r3, [r1, r2]
    add     r2, r2, #1
    cmp     r2, #96
    blo     4b

    /* Start at current ring head; discard pre-record history. */
    ldr_addr r0, GYRO_DESC_PTR
    ldr     r0, [r0]
    ldr     r0, [r0, #0x60]
    ldr     r1, [r0]
    str     r1, [r10, #S_HEAD]
    str     r1, [r9, #44]            /* initial_head */
    /* Publish OPEN request only after path/header/state are complete. */
    mov     r0, #1
    dmb     ish
    str     r0, [r10, #S_FILE]
    b       return_original

drain_ring:
    ldr_addr r0, GYRO_DESC_PTR
    ldr     r0, [r0]
    ldr     r8, [r0, #0x60]          /* ring base */
    ldr     r5, [r8]                 /* new head */
    ldr     r6, [r10, #S_HEAD]       /* old head */
    cmp     r5, r6
    beq     return_original

    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    mov     r9, r0                   /* batch end timestamp */
    mov     r4, #0                   /* wrap flag */
    cmp     r5, r6
    subhi   r3, r5, r6
    bhi     have_count
    /* 0x12C0, not 0x12C4.  The ring runs [base+4, base+0x12C4), so it holds
     * 0x12C0 bytes -- 600 samples of eight.  Counting the wrap as 0x12C4 took
     * four bytes too many every time it wrapped, which copied four stale bytes
     * and left the payload not a whole number of samples: 16340 bytes claiming
     * 2042 samples, when 2042 samples are 16336.  The decoder caught it; the
     * camera never would have.  the earlier logger has the same constant. */
    movw    r3, #0x12C0
    add     r3, r3, r5
    sub     r3, r3, r6
    mov     r4, #1
have_count:
    mov     r2, r3, lsr #3           /* samples */

    /* Select current buffer and metadata. */
select_buffer:
    ldr     r0, [r10, #S_INDEX]
    cmp     r0, #0
    addeq   r7, r10, #O_BUF_A
    addeq   r1, r10, #S_A_STATE
    addne   r7, r10, #O_BUF_B
    addne   r1, r10, #S_B_STATE
    /* S_INDEX is only a hint.  The producer may append exclusively to a
     * FILLING buffer; READY and WRITING belong to the writer even if a failed
     * swap left the index pointing at them. */
    ldr     ip, [r1]
    cmp     ip, #1
    bne     try_other_buffer
    ldr     r0, [r1, #0x18]          /* gyro bytes so far */
    add     r2, r0, r3
    ldr_addr r12, GYRO_CAP
    cmp     r2, r12
    bls     buffer_has_room

    /* Publish FILLING -> READY only after every byte and metadata word is
     * visible.  The writer pairs this with an acquire barrier. */
    dmb     ish
    mov     ip, #2
    str     ip, [r1]
try_other_buffer:
    ldr     ip, [r10, #S_INDEX]
    eor     ip, ip, #1
    cmp     ip, #0
    addeq   r1, r10, #S_A_STATE
    addne   r1, r10, #S_B_STATE
    ldr     r0, [r1]
    cmp     r0, #0
    bne     drop_batch
    dmb     ish
    str     ip, [r10, #S_INDEX]
    mov     r0, #1
    str     r0, [r1]
    mov     r0, #0
    str     r0, [r1, #0x18]
    str     r0, [r1, #0x1C]
    b       select_buffer

buffer_has_room:
    mov     r2, r3, lsr #3
    cmp     r0, #0
    bne     append_payload
    /* First sample timestamp = batch_end - (samples-1)*400 us. */
    sub     ip, r2, #1
    movw    r0, #400
    mul     ip, ip, r0
    sub     ip, r9, ip
    str     ip, [r1, #8]
    mov     r0, #0
    ldr     ip, [r10, #S_NEXTSEQ]
    str     ip, [r1, #16]
    add     ip, ip, #1
    str     ip, [r10, #S_NEXTSEQ]
    mov     ip, #0
    str     ip, [r1, #20]
append_payload:
    str     r9, [r1, #12]
    ldr     ip, [r1, #20]
    orr     ip, ip, r4
    str     ip, [r1, #20]

    /* Record where this buffer ends before r7 stops being its base.  the earlier logger's
     * copy_span carries USER_END and stops there; this one had no bound at all,
     * so an arithmetic slip anywhere upstream would have it writing through the
     * pool and out the far side -- which is the shape of a fault that comes and
     * goes with whatever happens to be downstream. */
    add     ip, r7, #BUF_SIZE
    str     ip, [r10, #S_LIMIT]

    /* Copy one or two ring spans into buffer+32+payload_count. */
    add     r7, r7, #BLOCK_HEADER
    add     r7, r7, r0
    cmp     r5, r6
    bhi     no_wrap_copy
    add     r0, r6, #4
    movw    r12, #0x12C4
    add     r1, r8, r12
    bl      copy_span
    add     r0, r8, #4
    add     r1, r5, #4
    bl      copy_span
    b       copy_done
no_wrap_copy:
    add     r0, r6, #4
    add     r1, r5, #4
    bl      copy_span
copy_done:
    /* One accelerometer record per batch, straight after the gyro samples.
     *
     * r7 is already pointing at the byte after the copy, and the room check
     * above reserved these twelve.  The timestamp is the same TickTimer read the
     * batch carries, which is the whole point: the two sensors are different
     * chips and only a shared clock makes them comparable.  The cache refreshes
     * at about 47 Hz whatever the sensor is set to -- the firmware polls it --
     * so one per batch is as often as there is anything new to read.
     *
     * The count goes in the top half of the block flags, so the payload stays
     * one array of gyro samples followed by one array of accel records and the
     * header says how many of each.  No second buffer, no second block type. */
    /* One accelerometer record per batch, in a zone of its own at the end of the
     * buffer.  Appending it straight after each batch's gyro samples would
     * interleave the two -- gyro, accel, gyro, accel -- and nothing records the
     * per-batch lengths, so nothing could take them apart again.  Keeping them
     * in separate regions costs one memmove when the block is written and leaves
     * the payload as one array of each.
     *
     * The timestamp is the batch's own TickTimer read: the two sensors are
     * different chips and only a shared clock makes them comparable.  The cache
     * refreshes at about 47 Hz however the sensor is configured -- the firmware
     * polls it -- so one per batch is as often as there is anything new. */
    ldr     r0, [r10, #S_INDEX]
    cmp     r0, #0
    addeq   r2, r10, #S_A_STATE
    addne   r2, r10, #S_B_STATE
    ldr     r0, [r2, #0x1C]          /* accel records so far */
    cmp     r0, #(ACCEL_ZONE / ACCEL_REC) - 1
    bhi     16f                      /* zone full: drop this one, keep the gyro */

    ldr     r7, [r10, #S_INDEX]
    cmp     r7, #0
    addeq   r7, r10, #O_BUF_A
    addne   r7, r10, #O_BUF_B
    movw    r12, #ACCEL_BASE
    add     r7, r7, r12
    add     r12, r0, r0, lsl #1      /* count * 3 */
    add     r7, r7, r12, lsl #2      /* ... * 4 = count * 12, no divide needed */

    str     r9, [r7], #4
    movw    r12, #:lower16:ACCEL_CACHE
    movt    r12, #:upper16:ACCEL_CACHE
    ldrsh   r1, [r12]
    strh    r1, [r7], #2
    ldrsh   r1, [r12, #2]
    strh    r1, [r7], #2
    ldrsh   r1, [r12, #4]
    strh    r1, [r7], #2
    mov     r1, #0
    strh    r1, [r7], #2

    add     r0, r0, #1
    str     r0, [r2, #0x1C]
16:

    /* Re-select metadata and add raw byte count. */
    ldr     r0, [r10, #S_INDEX]
    cmp     r0, #0
    addeq   r1, r10, #S_A_STATE
    addne   r1, r10, #S_B_STATE
    ldr     r0, [r10, #S_INDEX]
    cmp     r0, #0
    addeq   r1, r10, #S_A_STATE
    addne   r1, r10, #S_B_STATE
    ldr     r0, [r1, #0x18]
    add     r0, r0, r3
    str     r0, [r1, #0x18]
    str     r5, [r10, #S_HEAD]
    b       return_original

drop_batch:
    mov     r2, r3, lsr #3
    ldr     r0, [r10, #S_DROPPED]
    add     r0, r0, r2
    str     r0, [r10, #S_DROPPED]
    str     r5, [r10, #S_HEAD]
    b       return_original

recording_stopped:
    cmp     r7, #0
    beq     return_original
    mov     r0, #2                  @ seal old take; wait for next READY generation
    str     r0, [r10, #S_ACTIVE]
    ldr     r0, [r10, #S_INDEX]
    cmp     r0, #0
    addeq   r1, r10, #S_A_STATE
    addne   r1, r10, #S_B_STATE
    /* Gyro bytes, not the old payload count.  That field stopped being updated
     * when the accel records moved to a zone of their own, so this read zero
     * every time and the last buffer of every take was silently dropped -- the
     * footer said seventeen blocks where the file held sixteen. */
    /* Only the producer may publish FILLING -> READY.  In particular, never
     * turn WRITING back into READY if the writer claimed the last half between
     * the active-state load and this callback. */
    ldr     ip, [r1]
    cmp     ip, #1
    bne     stop_buffer_published
    ldr     r0, [r1, #0x18]
    cmp     r0, #0
    beq     stop_buffer_published
    dmb     ish
    mov     r0, #2
    str     r0, [r1]
stop_buffer_published:
    /* Stamp the stop, so "it seemed to hang" becomes a number. The camera
     * finishes its own CinemaDNG the moment recording ends, so anything holding
     * the card after that is ours, and the two stamps say how long for. */
    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    str     r0, [r10, #S_STOP_T0]
    mov     r0, #0
    ldr     ip, [r10, #S_A_STATE]
    cmp     ip, #0
    addne   r0, r0, #1
    ldr     ip, [r10, #S_B_STATE]
    cmp     ip, #0
    addne   r0, r0, #1
    str     r0, [r10, #S_STOP_BLOCKS]

    mov     r0, #1
    dmb     ish
    str     r0, [r10, #S_STOP]
    b       return_original

return_original:
    mov     r0, r11
    pop     {r3-r11, pc}

/* r0=src begin, r1=src end, r7=destination. */
/* Copy [r0,r1) to r7, stopping at S_LIMIT.  Fails closed: what does not fit is
 * counted in S_CLAMPED and dropped, rather than written somewhere else. */
copy_span:
    push    {r2, r3}
    ldr     r2, [r10, #S_LIMIT]
1:
    cmp     r0, r1
    bhs     2f
    cmp     r7, r2
    bhs     3f
    ldrb    r12, [r0], #1
    strb    r12, [r7], #1
    b       1b
3:
    sub     r3, r1, r0               /* what is left over */
    ldr     r2, [r10, #S_CLAMPED]
    add     r2, r2, r3
    str     r2, [r10, #S_CLAMPED]
2:
    pop     {r2, r3}
    bx      lr

/* Create and start a persistent direct-entry writer thread. */
/* Task descriptor is +0 exinf, +4 tskatr, +8 entry, +12 itskpri, +16 stksz,
 * +20 dsname[8]  (notes/TASK_PRIORITY_MAP.md, read from the Cyc wrapper's own
 * descriptor build at 0xC0370838).
 *
 * This routine previously had two independently fatal bugs, both static:
 *
 *  1. It called 0xC01F885C / 0xC01F8D90. Those are the *Cyc-thread* create/start
 *     (service 0x8047/0x8049), whose wrapper always passes a fixed trampoline as
 *     the entry point. Handing them a direct entry corrupts on start -- probe A/A2
 *     froze the camera with no readback. The main task path, the one the shell and
 *     CamMain use, is tk_cre_tsk 0xC0016A58 + tk_sta_tsk 0xC0016BC0.
 *
 *  2. It wrote the ASCII name "S6GF" into descriptor+16, which is stksz, not the
 *     name field. cre_tsk does not bounds-check stksz and still returns a valid
 *     task id, so the fault would only have surfaced at sta_tsk -- on a wildly
 *     out-of-range stack, corrupting the shared stack pool at 0xC301EAE4 and
 *     poisoning every later task creation.
 *
 * itskpri 28 and stksz 0x2000 are the values from probe A5, which is the one that
 * actually ran live (id 119, heartbeat, no freeze). */
start_writer_thread:
    push    {r4, lr}
    sub     sp, sp, #32
    mov     r0, #0
    str     r0, [sp, #0]             /* exinf  */
    mov     r0, #0x41
    str     r0, [sp, #4]             /* tskatr = TA_HLNG | TA_DSNAME */
    adr     r0, writer_thread
    str     r0, [sp, #8]             /* entry  */
    mov     r0, #28
    str     r0, [sp, #12]            /* itskpri */
    movw    r0, #0x2000
    str     r0, [sp, #16]            /* stksz  */
    movw    r0, #0x5947              /* dsname "GYROLOG\0" */
    movt    r0, #0x4F52
    str     r0, [sp, #20]
    movw    r0, #0x4F4C
    movt    r0, #0x0047
    str     r0, [sp, #24]
    mov     r0, #0
    str     r0, [sp, #28]            /* A5 zeroes this; do not hand the OS stack junk */
    mov     r0, sp
    movw    ip, #0x6A58
    movt    ip, #0xC001              /* tk_cre_tsk */
    blx     ip
    pool_state r4
    str     r0, [r4, #S_THREAD]
    cmp     r0, #1
    blt     3f
    mov     r1, #0                   /* stacd */
    movw    ip, #0x6BC0
    movt    ip, #0xC001              /* tk_sta_tsk */
    blx     ip
3:
    add     sp, sp, #32
    pop     {r4, pc}

/* Where park.S sends the thread back to.  The stub knows nothing about this
 * payload's registers -- it leaves its own pointer in r10 -- so the state block
 * is derived again here rather than assumed.  Resuming straight into
 * writer_loop cost one take: every access was off by the distance between the
 * parking words and the block they sit in. */
.global writer_resume
writer_resume:
    pool_state r10
    b       writer_loop

/* Persistent background thread. */
writer_thread:
    push    {r3-r11, lr}
    pool_state r10
writer_loop:
    /* Step out of the cave on request, so the body can be replaced without a
     * power cycle.  The stub lives above everything the loader writes and jumps
     * back through S_WRITER_PC when the host clears S_PARK. */
    ldr     r0, [r10, #S_PARK]
    cmp     r0, #0
    beq     15f
    movw    ip, #:lower16:PARK_STUB
    movt    ip, #:upper16:PARK_STUB
    bx      ip
15:
    bl      mode_watch
    mov     r0, #1                  @ PGEN RAM-only boundary watcher selector
    bl      post_process            @ writer task context, never gyro callback
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #1
    bne     writer_check_blocks
    ldr     r0, [r10, #O_LC_STATE]
    cmp     r0, #4                  @ never create .GYR before native media exists
    bne     writer_check_blocks
    ldr     r0, [r10, #O_LC_GEN]
    ldr     r1, [r10, #O_LC_ATTACH]
    cmp     r0, r1                  @ path/volume belong to the attached generation
    bne     writer_check_blocks
    dmb     ish                     @ acquire path/header published before state 4
    add     r1, r10, #O_POST_QUEUE
    ldr     r0, [r1, #Q_OPEN_DELAY]
    cmp     r0, #0
    subne   r0, r0, #1
    strne   r0, [r1, #Q_OPEN_DELAY]
    bne     writer_check_blocks
    bl      writer_open
writer_check_blocks:
    /* READY buffers are meaningful only while a real file is open.  Without
     * this gate an open failure, or a late stop publication, writes through a
     * constructed-but-unopened object and wedges the media subsystem. */
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #2
    bne     writer_no_blocks
    dmb     ish
    ldr     r0, [r10, #S_A_STATE]
    cmp     r0, #2
    bne     writer_check_b
    ldr     r0, [r10, #S_B_STATE]
    cmp     r0, #2
    bne     writer_choose_a
    ldr     r0, [r10, #S_A_SEQ]
    ldr     r1, [r10, #S_B_SEQ]
    cmp     r0, r1
    bhi     writer_choose_b
writer_choose_a:
    add     r4, r10, #O_BUF_A
    add     r5, r10, #S_A_STATE
    bl      writer_write_block
    b       writer_check_blocks
writer_check_b:
    ldr     r0, [r10, #S_B_STATE]
    cmp     r0, #2
    bne     writer_no_blocks
writer_choose_b:
    add     r4, r10, #O_BUF_B
    add     r5, r10, #S_B_STATE
    bl      writer_write_block
    b       writer_check_blocks

writer_no_blocks:
    /* STOP is published after the callback's final READY publication.  Check
     * it before optional card work, acquire it, and rescan both halves.  This
     * closes the old scan/stop TOCTOU window that could close O_FOBJ and then
     * write the final block through that closed object on the next poll. */
    ldr     r0, [r10, #S_STOP]
    cmp     r0, #1
    bne     writer_idle
    dmb     ish
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #2
    bne     writer_stop_not_open
    ldr     r0, [r10, #S_A_STATE]
    cmp     r0, #2
    beq     writer_check_blocks
    ldr     r0, [r10, #S_B_STATE]
    cmp     r0, #2
    beq     writer_check_blocks
    mov     r0, #3
    dmb     ish
    str     r0, [r10, #S_FILE]
    bl      writer_close
    /* The recording transaction is not complete at GYR close.  Go straight
     * into the same writer task's GCSV->JSON drain: the old 5 ms sleep exposed
     * a window in which record or power-off could arrive between artifacts. */
    b       writer_idle
writer_stop_not_open:
    cmp     r0, #1                  @ pending CDNG ended before first DNG existed
    beq     writer_stop_abort
    cmp     r0, #3
    bne     writer_sleep
writer_stop_abort:
    bl      writer_abort
    b       writer_sleep

writer_idle:
    ldr     r0, [r10, #S_POOL_TRIED]
    cmp     r0, #0
    bne     17f
    mov     r0, #1
    str     r0, [r10, #S_POOL_TRIED]
    bl      pool_load
17:
    ldr     r0, [r10, #S_POST_COUNT]
    cmp     r0, #0
    bne     18f
    /* S_POOL_TRIED=1 means PGEN loaded but has not run its one-shot recovery
     * scan.  Let the same guarded post-process entry do that even with an empty
     * RAM queue; it changes the state to 2 when the scan is complete. */
    ldr     r0, [r10, #S_POOL_TRIED]
    cmp     r0, #1
    bne     writer_sleep
18:
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     writer_sleep

    /* Start immediately after the native adapter's real finalize.  Fixed quiet
     * gaps left the camera briefly unprotected between writes; the native XMP,
     * MOV catalog and lower writer flags give us an exact RAM-only gate. */
    ldr_addr r1, XMP_FOBJ_PTR
    ldr     r1, [r1]
    cmp     r1, #0
    bne     writer_post_busy_native
    ldr_addr r1, MOV_ACTIVE_PTR
    ldrb    r1, [r1]
    cmp     r1, #0
    bne     writer_post_busy_native
    ldr_addr r1, MOV_BUSY_PTR
    ldrb    r1, [r1]
    cmp     r1, #0
    bne     writer_post_busy_native

    mov     r0, #1
    str     r0, [r10, #S_POST_BUSY]
    dmb     ish
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     writer_post_release
    bl      post_process
writer_post_release:
    mov     r0, #0
    dmb     ish
    str     r0, [r10, #S_POST_BUSY]
    b       writer_sleep
writer_post_busy_native:
    b       writer_sleep

/* Every distinct sensor mode the take passes through, with the tick it changed.
 *
 * Two takes shot back to back on the same settings -- A001_016 and A001_017,
 * both FHD 29.97 -- recorded modes 8 and 106 in their headers. The header is
 * sampled the instant ACTIVE goes high, which races the mode change itself, so
 * a single sample cannot say which mode the recording ran in and two samples
 * that disagree cannot either. A history can: it shows when the switch lands
 * and whether anything moves afterwards. Eight slots is more than a take needs;
 * once they are full the watcher stops, so a mode that oscillates cannot push
 * the interesting first entries out.
 *
 * Called from the writer's poll, not the gyro callback -- 5 ms of resolution on
 * a change that takes tens of milliseconds, and nothing added to the 2500 Hz
 * path. */
mode_watch:
    push    {r4, r5, r6, lr}
#ifndef FPGYRO_PHASE_PROBE
    movw    r5, #:lower16:MODE_OBJ
    movt    r5, #:upper16:MODE_OBJ
    ldr     r6, [r5, #4]
    ldr     r4, [r10, #S_MODE_N]
    cmp     r4, #8
    bge     9f
    cmp     r4, #0
    beq     1f
    add     r5, r10, #S_MODE_HIST
    add     r5, r5, r4, lsl #3
    ldr     r5, [r5, #-4]            @ the mode in the last slot used
    cmp     r5, r6
    beq     9f
1:
    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    add     r5, r10, #S_MODE_HIST
    add     r5, r5, r4, lsl #3
    str     r0, [r5]
    str     r6, [r5, #4]
    add     r4, r4, #1
    str     r4, [r10, #S_MODE_N]
9:
#endif
    /* GEOMETRY is often still zero in the callback that first observes record
     * start.  Latch the first valid dimensions while ACTIVE remains true, and
     * never sample it after stop (when it returns to zero).  The queued profile
     * then carries the take's dimensions rather than a start/stop race. */
    ldr     r0, [r10, #S_ACTIVE]
    cmp     r0, #1
    bne     10f
    ldr_addr r0, GEOMETRY
    ldr     r1, [r0]
    ldr     r2, [r0, #4]
    cmp     r1, #0
    beq     10f
    cmp     r2, #0
    beq     10f
    str     r1, [r10, #S_GEOM_W]
    str     r2, [r10, #S_GEOM_H]
10:
    pop     {r4, r5, r6, pc}

/* A subroutine rather than a jump target, so it can be called on its own during
 * bring-up instead of only from the thread's loop. */
writer_write_block:
    push    {r4, r5, r6, r7, r8, lr}
    ldr     r0, [r5]
    cmp     r0, #2
    bne     writer_block_out
    dmb     ish
    mov     r0, #3
    str     r0, [r5]

    /* Bring the two regions together.  The gyro samples start at +32 and the
     * accel records live in their own zone at the end of the buffer; the file
     * wants one payload, so the accel block moves down to sit right after the
     * last gyro sample.  A block holds about forty batches, so this copies a few
     * hundred bytes. */
    ldr     r6, [r5, #0x18]          /* gyro bytes */
    ldr     r8, [r5, #0x1C]          /* accel records */
    cmp     r8, #0
    beq     20f
    add     r8, r8, r8, lsl #1
    mov     r8, r8, lsl #2           /* records * 12 = bytes */
    add     r0, r4, #BLOCK_HEADER
    add     r0, r0, r6               /* destination */
    movw    r1, #ACCEL_BASE
    add     r1, r4, r1               /* source */
    mov     r2, #0
19: ldrb    r7, [r1, r2]
    strb    r7, [r0, r2]
    add     r2, r2, #1
    cmp     r2, r8
    blo     19b
20:
    add     r6, r6, r8               /* payload = gyro + accel bytes */

    add     r0, r4, #BLOCK_HEADER
    mov     r1, r6
    bl      crc32
    mov     r7, r0
    movw    r0, #0x4647
    movt    r0, #0x3642              /* GFB6 */
    str     r0, [r4, #0]
    ldr     r0, [r5, #16]
    str     r0, [r4, #4]
    ldr     r0, [r5, #8]
    str     r0, [r4, #8]
    ldr     r0, [r5, #12]
    str     r0, [r4, #12]
    /* Samples, from the gyro bytes alone. */
    ldr     r0, [r5, #0x18]
    mov     r0, r0, lsr #3
    str     r0, [r4, #16]
    /* Flags: the wrap bit as it stands, with the accel record count above it, so
     * the payload is one array of each and the header says how many. */
    ldr     r0, [r5, #20]
    mov     r0, r0, lsl #16
    mov     r0, r0, lsr #16
    ldr     r1, [r5, #0x1C]          /* records, already a count */
    orr     r0, r0, r1, lsl #16
    str     r0, [r4, #20]
    str     r6, [r4, #24]
    str     r7, [r4, #28]

    add     r0, r10, #O_FOBJ
    mov     r1, r4
    add     r2, r6, #BLOCK_HEADER
    movw    ip, #0x60E8
    movt    ip, #0xC036
    blx     ip
    cmp     r0, #0
    bne     writer_block_written
    /* Stop all further writes through this object.  The callback may continue
     * collecting (and eventually dropping) until recording stops, but it can no
     * longer turn a media error into an invalid-object assertion. */
    mov     r0, #1
    str     r0, [r10, #S_ERROR]
    mov     r0, #3
    dmb     ish
    str     r0, [r10, #S_FILE]
    mov     r0, #O_FOBJ
    bl      close_file
writer_block_written:

    /* The take's own mode, sampled once, at the first block.
     *
     * Both ends of a take give the live-view mode. A001_022's history is 8 at
     * the first poll, 106 at +36 ms, and 8 again seventy milliseconds before the
     * capture ends -- the camera goes home before the logger sees the stop, so
     * "the last sample while recording" is 8 as surely as "the sample at record
     * start" is. A block is 766 ms of samples, which is clear of the switch at
     * one end and of the return at the other, and once set it is not touched
     * again: the final partial block is flushed after the camera has already
     * gone back to live view.
     *
     * Read straight from the mode object rather than through FUN_c032c720,
     * which is that load with a lazy-singleton check in front of it.
     *
     * (What follows was the old re-read, kept for the reasoning:
     *
     * The header's copy is taken the instant ACTIVE goes high, which is the
     * least settled moment there is. This one is taken 766 ms in at the earliest
     * -- a block's worth of samples -- and again every block after, so what
     * reaches the footer is the mode as it was mid-take.
     *
     * It was added believing the header sometimes caught live view: two takes in
     * six recorded mode 8, whose name is MONIT1_60. That reading was wrong.
     * Every mode in this family is named MONIT-something -- 106 is
     * MONIT1_30_HD_LOWP3 and 123 is MONIT1_25_HD_LOWP -- so the name says
     * nothing about recording, and the re-read returns 8 for the whole take
     * rather than disagreeing with the header. The later sample is still the
     * more defensible one; it just does not fix what it was meant to.) */
    ldr     r0, [r10, #S_MODE_RUN]
    cmp     r0, #0
    bne     44f
    movw    r0, #:lower16:MODE_OBJ
    movt    r0, #:upper16:MODE_OBJ
    ldr     r0, [r0, #4]
    str     r0, [r10, #S_MODE_RUN]
44:

    mov     r0, #0
    str     r0, [r5, #0x18]
    str     r0, [r5, #0x1C]
    str     r0, [r5, #20]
    dmb     ish
    str     r0, [r5]
writer_block_out:
    pop     {r4, r5, r6, r7, r8, pc}

writer_sleep:
    mov     r0, #5
    movw    ip, #0x05D8
    movt    ip, #0xC037
    blx     ip
    b       writer_loop

/* Called with bl, and it calls out five times, so lr has to be saved -- the
 * first blx destroyed it and `bx lr` returned into the middle of the media API.
 * An even number of registers keeps the stack eight byte aligned for the
 * callees, which handle doublewords. */
/* ==========================================================================
 * post_process — hand the queue head to the generator in the pool.
 *
 * The profile is built by gyro/profilegen.S, which lives in the bufmem pool
 * rather than here: it reads the lens off the mount, looks the mode up in the
 * firmware's own timing and geometry tables, works out the rolling shutter and
 * the focal length, and formats the text. That is two and a half kilobytes of
 * code and this cave has room for none of it.
 *
 * S_JSON_FN is where the loader left the entry point. Zero means the generator
 * was never placed, and then no profile is written -- which is visible, where
 * branching through a zero would be a freeze.
 * ========================================================================== */
post_process:
    ldr     ip, [r10, #S_JSON_FN]
    cmp     ip, #0
    moveq   r0, #0
    bxeq    lr
    bx      ip                          @ it returns to our caller

/* Close a file and destroy its object: r0 = the object's offset from r10.
 * The other half of open_file, and copied just as often. */
close_file:
    push    {r4, lr}
    mov     r4, r0
    add     r0, r10, r4
    ldr_addr     ip, F_CLOSE
    blx     ip
    add     r0, r10, r4
    mov     r1, #2
    ldr_addr     ip, F_DTOR
    blx     ip
    pop     {r4, pc}

/* Open a file: r0 = object offset, r1 = path, r2 = mode, r3 = explicit volume.
 * Returns what F_OPEN returned -- zero means it did not open.  A take keeps the
 * volume selected at native file-open; an unplugged SSD must fail/retry on 5,
 * never silently spill the matching sidecars onto SD.
 *
 * Three copies of the same six calls, and a fourth wanted for the profile.  The
 * cave is a fixed nine hundred and fifty words and the copies were most of what
 * was left of it; the sequence has never varied, so there was nothing to lose
 * by naming it. */
open_file:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    mov     r7, r3
    add     r0, r10, r4
    mov     r1, r7
    ldr_addr     ip, F_CTOR
    blx     ip
    add     r0, r10, r4
    mov     r1, r5
    mov     r2, r6
    ldr_addr     ip, F_OPEN
    blx     ip
    cmp     r0, #0
    popne   {r4, r5, r6, r7, r8, pc}
    /* It did not open -- but F_CTOR above built the object, and every caller
     * used to branch away and leave it built. A file object that is never
     * destroyed wedges the file system: that is what happened to \LENS.DAT,
     * which could not be opened again by anything until the camera was power
     * cycled, with the card light on. Opens rarely fail, and the damage does
     * not heal, which is exactly the shape of a freeze that only sometimes
     * happens. Destroying it here fixes all four callers at once. */
    add     r0, r10, r4
    mov     r1, #2
    ldr_addr     ip, F_DTOR
    blx     ip
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

writer_open:
    push    {r4, lr}
    mov     r0, #O_FOBJ
    add     r1, r10, #O_PATH
    mov     r2, #7                   /* 7 可覆寫;0x0402 檔案已存在就失敗 */
    ldr     r3, [r10, #O_LC_VOLUME]
    bl      open_file
    /* Zero means it did not open.  Unchecked, the writes that follow go to a
     * file object with nothing behind it and every one of them succeeds. */
    cmp     r0, #0
    bne     13f
writer_open_failed:
    mov     r0, #1
    str     r0, [r10, #S_ERROR]
    add     r4, r10, #O_POST_QUEUE
    ldr     r0, [r4, #Q_OPEN_TRIES]
    add     r0, r0, #1
    str     r0, [r4, #Q_OPEN_TRIES]
    cmp     r0, #5
    blo     16f
    mov     r0, #3                  @ bounded failure: never hammer the volume
    dmb     ish
    str     r0, [r10, #S_FILE]
    ldr     r0, [r10, #S_STOP]
    cmp     r0, #1
    bne     14f
    bl      writer_abort
    b       14f
16:
    mov     r0, #40                  @ retry after 200 ms, never every poll
    str     r0, [r4, #Q_OPEN_DELAY]
    ldr     r0, [r10, #S_STOP]
    cmp     r0, #1
    bne     14f
    mov     r0, #3
    dmb     ish
    str     r0, [r10, #S_FILE]
    bl      writer_abort
14:
    pop     {r4, pc}
13:
    add     r0, r10, #O_FOBJ
    add     r1, r10, #O_HEADER
    mov     r2, #160                 /* 64 of header, then 96 of lens region */
    movw    ip, #0x60E8
    movt    ip, #0xC036
    blx     ip
    cmp     r0, #0
    bne     15f
    mov     r0, #O_FOBJ
    bl      close_file
    b       writer_open_failed
15:
    add     r4, r10, #O_POST_QUEUE
    mov     r0, #0
    str     r0, [r4, #Q_OPEN_TRIES]
    str     r0, [r4, #Q_OPEN_DELAY]
    mov     r0, #2
    dmb     ish
    str     r0, [r10, #S_FILE]
    pop     {r4, pc}

writer_close:
    push    {r4, lr}
    mov     r4, #1                   @ all three final writes must succeed
    /* The mode history first, as its own record, so the fixed 32-byte footer
     * keeps its shape and an older decoder fails loudly on the magic rather
     * than reading the history as a footer. */
    add     r1, r10, #O_HEADER
    movw    r0, #0x4647
#ifdef FPGYRO_PHASE_PROBE
    movt    r0, #0x3654              /* GFT6: media phase trace */
#else
    movt    r0, #0x364D              /* GFM6 */
#endif
    str     r0, [r1, #0]
    ldr     r0, [r10, #S_MODE_N]
    str     r0, [r1, #4]
    add     r0, r10, #O_FOBJ
    mov     r2, #8
    movw    ip, #0x60E8
    movt    ip, #0xC036
    blx     ip
    cmp     r0, #0
    moveq   r4, #0
    add     r0, r10, #O_FOBJ         @ and the history straight out of the state
    add     r1, r10, #S_MODE_HIST    @ block: copying it into the header buffer
    mov     r2, #64                  @ first bought nothing but a loop
    movw    ip, #0x60E8
    movt    ip, #0xC036
    blx     ip
    cmp     r0, #0
    moveq   r4, #0

    /* Append GFE6 footer before closing, preserving loss/error diagnostics. */
    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    mov     r3, r0
    add     r1, r10, #O_HEADER
    movw    r0, #0x4647
    movt    r0, #0x3645              /* GFE6 */
    str     r0, [r1, #0]
    ldr     r0, [r10, #S_NEXTSEQ]
    str     r0, [r1, #4]
    ldr     r0, [r10, #S_DROPPED]
    str     r0, [r1, #8]
    ldr     r0, [r10, #S_ERROR]
    str     r0, [r1, #12]
    str     r3, [r1, #16]
    ldr     r0, [r10, #S_MODE_RUN]      @ sampled at the first block, not at either
    str     r0, [r1, #20]               @ end of the take
    ldr     r0, [r10, #S_GEOM_W]        @ persisted for post-boot recovery
    str     r0, [r1, #24]
    ldr     r0, [r10, #S_GEOM_H]
    str     r0, [r1, #28]
    add     r0, r10, #O_FOBJ
    mov     r2, #32
    movw    ip, #0x60E8
    movt    ip, #0xC036
    blx     ip
    cmp     r0, #0
    moveq   r4, #0
    mov     r0, #O_FOBJ
    bl      close_file
    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    str     r0, [r10, #S_STOP_T1]
    cmp     r4, #0
    beq     writer_close_bad
    bl      post_enqueue
    b       writer_close_queued
writer_close_bad:
    mov     r0, #1
    str     r0, [r10, #S_ERROR]
writer_close_queued:

    mov     r0, #0
    str     r0, [r10, #S_STOP]
    dmb     ish
    str     r0, [r10, #S_FILE]       @ publish CLOSED last
    pop     {r4, pc}

/* A stopped take whose object never opened, or whose block write failed.  No
 * footer can be made trustworthy; release both halves and let the camera keep
 * running instead of calling any more media methods on that object. */
writer_abort:
    push    {r4, lr}
    mov     r0, #0
    str     r0, [r10, #S_A_GYRO]
    str     r0, [r10, #S_A_ACC]
    str     r0, [r10, #S_A_FLAGS]
    str     r0, [r10, #S_B_GYRO]
    str     r0, [r10, #S_B_ACC]
    str     r0, [r10, #S_B_FLAGS]
    dmb     ish
    str     r0, [r10, #S_A_STATE]
    str     r0, [r10, #S_B_STATE]
    str     r0, [r10, #S_STOP]
    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    str     r0, [r10, #S_STOP_T1]
    mov     r0, #0
    dmb     ish
    str     r0, [r10, #S_FILE]
    pop     {r4, pc}

/* Snapshot the take after its .GYR object is closed.  Seven jobs fit exactly in
 * the otherwise unused 0x2A0..0x3FF header tail. */
post_enqueue:
    push    {r4, r5, r6, lr}
    ldr     r6, [r10, #S_POST_COUNT]
    cmp     r6, #Q_CAP
    blo     1f
    add     r4, r10, #O_POST_QUEUE
    ldr     r0, [r4, #Q_DROPPED]
    add     r0, r0, #1
    str     r0, [r4, #Q_DROPPED]
    b       4f
1:
    add     r4, r10, #O_POST_QUEUE
    ldr     r5, [r4, #Q_HEAD]
    add     r5, r5, r6
    cmp     r5, #Q_CAP
    subhs   r5, r5, #Q_CAP
    add     r5, r5, r5, lsl #1      @ index * 3
    add     r5, r4, r5, lsl #4      @ queue + index * 48
    add     r5, r5, #Q_JOBS
    ldr     r0, [r10, #O_LC_VOLUME]
    lsl     r0, r0, #8
    ldr     r1, [r10, #O_LC_KIND]
    orr     r0, r0, r1, lsl #16     @ completion bits remain J_FLAGS[1:0]
    str     r0, [r5, #J_FLAGS]
    mov     r0, #0
    str     r0, [r5, #J_ATTEMPTS]
    ldr     r0, [r10, #S_STOP_T1]
    str     r0, [r5, #J_CLOSE_TICK]
    ldr     r0, [r10, #S_START_US]
    str     r0, [r5, #J_START_US]
    ldr     r0, [r10, #S_MODE_RUN]
    str     r0, [r5, #J_MODE]
    ldr     r0, [r10, #S_GEOM_W]
    str     r0, [r5, #J_W]
    ldr     r0, [r10, #S_GEOM_H]
    str     r0, [r5, #J_H]
    add     r1, r10, #O_PATH
    add     r2, r5, #J_PATH
    mov     r3, #20
2:  ldrb    r0, [r1], #1
    strb    r0, [r2], #1
    subs    r3, r3, #1
    bne     2b
    add     r6, r6, #1
    dmb     ish
    str     r6, [r10, #S_POST_COUNT] @ publish the complete job last
4:
    pop     {r4, r5, r6, pc}

/* Put the firmware's own instruction back and return what it returned.  After
 * this the logger is inert until an AutoRun arms it again. */
hook_stand_down:
    ldr_addr r0, HOOK_SITE
    ldr_addr r1, HOOK_ORIG
    str     r1, [r0]
#ifdef FPGYRO_PHASE_PROBE
    /* A soft restart that did not run AutoRun must not leave the global media
     * writer branching into this session's diagnostic cave. */
    ldr_addr r0, F_WRITE
    ldr_addr r1, 0xE92D40F0          @ original push {r4-r7, lr}
    str     r1, [r0]
    ldr_addr ip, F_CACHE
    blx     ip
#endif
    mov     r0, r11
    pop     {r3-r11, pc}

/* Standard reflected CRC-32 over r1 bytes at r0. */
crc32:
    push    {r4-r6, lr}
    mvn     r2, #0
4:
    cmp     r1, #0
    beq     7f
    ldrb    r3, [r0], #1
    eor     r2, r2, r3
    mov     r4, #8
5:
    and     r5, r2, #1
    mov     r2, r2, lsr #1
    cmp     r5, #0
    beq     6f
    movw    r6, #0x8320
    movt    r6, #0xEDB8
    eor     r2, r2, r6
6:
    subs    r4, r4, #1
    bne     5b
    subs    r1, r1, #1
    bne     4b
7:
    mvn     r0, r2
    pop     {r4-r6, pc}

/* ==========================================================================
 * pool_load — read \PGEN.BIN into the pool and note where the routines landed.
 *
 * "PGEN" | u32 profile entry | u32 gcsv entry | u32 length | the code
 *
 * The AutoRun used to spell this out as ninety-one commands and call it through
 * the borrowed echo handler. It is done here instead: the writer thread runs it
 * on its first idle poll, milliseconds after boot and long before a take, in a
 * normal task context. Ninety-one commands off the boot, and one fewer thing
 * borrowing the shell's command table -- the handler came back from one boot
 * still pointing at our routine, because the single `mem set` that put it back
 * had been dropped.
 *
 * Once, whether or not it works. A missing or unreadable PGEN.BIN leaves both
 * pointers at zero, and then no gcsv and no profile are written, which is
 * visible; retrying every five milliseconds against a card that does not have
 * the file would not be.
 * ========================================================================== */
.equ PGEN_MAGIC,      0x4E454750  /* "PGEN" */
.equ PGEN_HEADER,     16
.equ PG_CODE,         0x71000     /* from r10; 24 KiB past O_READ's end */
.equ PG_MAX,          0x10000     /* bounded 64 KiB code window */

pool_load:
    push    {r4, r5, r6, lr}
    mov     r0, #0
    str     r0, [r10, #S_JSON_FN]       @ never branch through half-placed code
    str     r0, [r10, #S_GCSV_FN]

    mov     r0, #O_FOBJ2
    adr     r1, pgen_path
    mov     r2, #1
    mov     r3, #1                   @ boot asset always lives on AutoRun SD
    bl      open_file
    cmp     r0, #0
    beq     19f

    movw    r4, #:lower16:PG_CODE
    movt    r4, #:upper16:PG_CODE
    add     r4, r10, r4
    mov     r0, #0
    str     r0, [r10, #S_READ_N]
    add     r0, r10, #O_FOBJ2
    mov     r1, r4
    movw    r2, #:lower16:PG_MAX
    movt    r2, #:upper16:PG_MAX
    add     r3, r10, #S_READ_N
    ldr_addr     ip, F_READ
    blx     ip
    ldr     r5, [r10, #S_READ_N]
    mov     r0, #O_FOBJ2
    bl      close_file

    ldr     r0, [r4]
    ldr_addr r1, PGEN_MAGIC
    cmp     r0, r1
    bne     19f
    ldr     r2, [r4, #12]               @ how much code there should be
    add     r2, r2, #PGEN_HEADER
    cmp     r5, r2
    blo     19f                         @ short read: do not run half of it

    ldr_addr ip, F_CACHE                @ or the CPU fetches what the write has
    blx     ip                          @ not put in memory yet

    ldr     r0, [r4, #4]
    add     r0, r0, #PGEN_HEADER
    add     r0, r4, r0
    str     r0, [r10, #S_JSON_FN]
    ldr     r0, [r4, #8]
    add     r0, r0, #PGEN_HEADER
    add     r0, r4, r0
    str     r0, [r10, #S_GCSV_FN]
19:
    pop     {r4, r5, r6, pc}

pgen_path:
    .byte   0x5C                        /* spelled out, so no escaping
                                         * convention can quietly change it */
    .asciz  "PGEN.BIN"
    .align  2

/* ==========================================================================
 * gcsv_build — hand off to the builder in the pool.
 *
 * gyro/gcsvgen.S: the .GYR that was just closed becomes a Gyroflow log. Twelve
 * hundred bytes of reading, formatting and writing, none of it while a take is
 * running, all of it in a cave that had four bytes left.
 *
 * S_GCSV_FN is where the loader left the entry point. Zero means it was never
 * placed and no gcsv is written -- visible, where branching through a zero
 * would be a freeze.
 * ========================================================================== */
gcsv_build:
    ldr     ip, [r10, #S_GCSV_FN]
    cmp     ip, #0
    moveq   r0, #0
    bxeq    lr
    bx      ip                          @ it returns to our caller
