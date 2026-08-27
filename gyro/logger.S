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
.equ TEXT_FLUSH,      0x40000     /* 256 KiB: three writes instead of forty     */
.equ O_READ,          0x5B000     /* pool+0x61000, past the text buffer         */
.equ READ_SIZE,       0x9C000     /* 624 KiB, ending 12 KiB short of the pool   */
.equ O_END,           0xF000      /* the logger owns r10-0x6000 .. +0xF000 */
.equ PATH_MGR_SD,     0xC3438400
.equ GYRO_DESC_PTR,   0xC31E3FCC

/* STATE word offsets. */
.equ S_THREAD,        0x00
.equ S_ACTIVE,        0x04
.equ S_FILE,          0x08  /* 0 closed, 1 open request, 2 open, 3 close request */
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
.equ S_MODE_LATE,     0xA0        /* the mode, re-read once recording is going  */
.equ F_MODE_NOW,      0xC032C720  /* () -> the current sensor mode enum         */
.equ GEOMETRY,        0xC37CE210  /* {width, height, frame bytes} while recording */        /* the .GYR has nothing more to give          */
.equ S_READ_N,        0x8C        /* where read() drops its byte count          */        /* where to resume once the body is replaced    */
.equ PARK_STUB,       0xC072EF00  /* never rewritten; see templates/park.S        */

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

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
    movt    r1, #0x3653              /* 'S6G6' */
    cmp     r0, r1
    beq     block_ready
    mov     r0, #0
    mov     r2, #0
14: str     r0, [r10, r2]
    add     r2, r2, #4
    cmp     r2, #0x100
    blo     14b
    str     r1, [r10, #S_MAGIC]
block_ready:

    ldr     r0, [r10, #S_THREAD]
    cmp     r0, #0
    bne     thread_ready
    bl      start_writer_thread
thread_ready:
    /* Real MovieRecording state. */
    movw    ip, #0xB2D0
    movt    ip, #0xC035
    blx     ip
    ldrb    r5, [r0, #0x157]
    ldr     r7, [r10, #S_ACTIVE]
    cmp     r5, #0
    beq     recording_stopped
    cmp     r7, #0
    bne     drain_ring

recording_started:
    /* Do not start a new take until the previous writer has closed. */
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     return_original
    mov     r0, #1
    str     r0, [r10, #S_ACTIVE]
    mov     r0, #0
    str     r0, [r10, #S_INDEX]
    str     r0, [r10, #S_DROPPED]
    str     r0, [r10, #S_NEXTSEQ]
    str     r0, [r10, #S_ERROR]
    str     r0, [r10, #S_STOP]
    str     r0, [r10, #S_A_GYRO]
    str     r0, [r10, #S_B_GYRO]
    mov     r1, #1
    str     r1, [r10, #S_A_STATE]
    str     r0, [r10, #S_B_STATE]

    /* Record-start monotonic timestamp. */
    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    mov     r6, r0

    /* Build \A001_003.GYR; manager contains previous clip number.
     *
     * Seed the template first.  the earlier logger kept FILE_PATH inside its own image, so
     * the backslash, the underscore and the extension arrived with the code and
     * only the digits were ever written.  Moving the path into the pool left
     * those bytes zero, and the first recording opened "" -- sixteen blocks
     * written to a file object that was never opened, and nothing noticed. */
    ldr_addr r8, PATH_MGR_SD
    add     r9, r10, #O_PATH
    mov     r0, #0x5C                @ '\\'
    strb    r0, [r9, #0]
    mov     r0, #0x5F                @ '_'
    strb    r0, [r9, #5]
    mov     r0, #0x2E                @ '.'
    strb    r0, [r9, #9]
    mov     r0, #0x47                @ 'G'
    strb    r0, [r9, #10]
    mov     r0, #0x59                @ 'Y'
    strb    r0, [r9, #11]
    mov     r0, #0x52                @ 'R'
    strb    r0, [r9, #12]
    mov     r0, #0
    strb    r0, [r9, #13]
    ldrb    r0, [r8, #8]
    strb    r0, [r9, #1]
    add     r0, r9, #2
    ldr     r1, [r8, #0x0C]
    bl      put_decimal_3
    add     r0, r9, #6
    ldr     r1, [r8, #0x10]
    add     r1, r1, #1
    bl      put_decimal_3

    /* GFS6 64-byte file header. */
    add     r9, r10, #O_HEADER
    movw    r0, #0x4647
    movt    r0, #0x3653              /* GFS6 */
    str     r0, [r9, #0]
    mov     r0, #4                   /* v4: header carries the lens region */
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
    ldrb    r0, [r8, #8]
    str     r0, [r9, #20]
    ldr     r0, [r8, #0x0C]
    str     r0, [r9, #24]
    ldr     r0, [r8, #0x10]
    add     r0, r0, #1
    str     r0, [r9, #28]
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
    ldr     r0, [r1, #0x18]          /* gyro bytes so far */
    add     r2, r0, r3
    ldr_addr r12, GYRO_CAP
    cmp     r2, r12
    bls     buffer_has_room

    /* Publish full current buffer, then swap only if the other is EMPTY.
     * Publish only from a state the writer does not own. A buffer can be READY
     * with S_INDEX still pointing at it -- that is what happens when the other
     * half was busy and the batch was dropped -- and by the next batch the writer
     * may have taken it to WRITING. Storing 2 unconditionally put it back to
     * READY underneath the writer, advertising a buffer that was mid-write. */
    ldr     ip, [r1, #0]
    cmp     ip, #3
    movne   ip, #2
    strne   ip, [r1, #0]
    ldr     ip, [r10, #S_INDEX]
    eor     ip, ip, #1
    cmp     ip, #0
    addeq   r1, r10, #S_A_STATE
    addne   r1, r10, #S_B_STATE
    ldr     r0, [r1]
    cmp     r0, #0
    bne     drop_batch
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
    mov     r0, #0
    str     r0, [r10, #S_ACTIVE]
    ldr     r0, [r10, #S_INDEX]
    cmp     r0, #0
    addeq   r1, r10, #S_A_STATE
    addne   r1, r10, #S_B_STATE
    /* Gyro bytes, not the old payload count.  That field stopped being updated
     * when the accel records moved to a zone of their own, so this read zero
     * every time and the last buffer of every take was silently dropped -- the
     * footer said seventeen blocks where the file held sixteen. */
    ldr     r0, [r1, #0x18]
    cmp     r0, #0
    movne   r0, #2
    strne   r0, [r1]
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
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #1
    bne     writer_check_blocks
    bl      writer_open
writer_check_blocks:
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
    ldr     r0, [r10, #S_STOP]
    cmp     r0, #1
    bne     writer_sleep
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #2
    bne     writer_sleep
    bl      writer_close
    b       writer_sleep

/* A subroutine rather than a jump target, so it can be called on its own during
 * bring-up instead of only from the thread's loop. */
writer_write_block:
    push    {r4, r5, r6, r7, r8, lr}
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

    /* Re-read the sensor mode, once recording is under way.
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
     * more defensible one; it just does not fix what it was meant to. */
    movw    ip, #:lower16:F_MODE_NOW
    movt    ip, #:upper16:F_MODE_NOW
    blx     ip
    str     r0, [r10, #S_MODE_LATE]

    mov     r0, #0
    str     r0, [r5, #0x18]
    str     r0, [r5, #0x1C]
    str     r0, [r5, #20]
    str     r0, [r5]
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
writer_open:
    push    {r4, lr}
    movw    ip, #0x4658
    movt    ip, #0xC044
    blx     ip
    mov     r1, #0
    movw    ip, #0x4698
    movt    ip, #0xC044
    blx     ip
    mov     r1, r0
    add     r0, r10, #O_FOBJ
    movw    ip, #0x5E90
    movt    ip, #0xC036
    blx     ip
    add     r0, r10, #O_FOBJ
    add     r1, r10, #O_PATH
    mov     r2, #7                   /* 7 可覆寫;0x0402 檔案已存在就失敗 */
    movw    ip, #0x5FB0
    movt    ip, #0xC036
    blx     ip
    /* Zero means it did not open.  Unchecked, the writes that follow go to a
     * file object with nothing behind it and every one of them succeeds. */
    cmp     r0, #0
    bne     13f
    mov     r0, #1
    str     r0, [r10, #S_ERROR]
    pop     {r4, pc}
13:
    add     r0, r10, #O_FOBJ
    add     r1, r10, #O_HEADER
    mov     r2, #160                 /* 64 of header, then 96 of lens region */
    movw    ip, #0x60E8
    movt    ip, #0xC036
    blx     ip
    mov     r0, #2
    str     r0, [r10, #S_FILE]
    pop     {r4, pc}

writer_close:
    push    {r4, lr}
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
    ldr     r0, [r10, #S_MODE_LATE]     @ the mode as it was mid-take, not at the
    str     r0, [r1, #20]               @ instant the flag went up
    mov     r0, #0
    str     r0, [r1, #24]
    str     r0, [r1, #28]
    add     r0, r10, #O_FOBJ
    mov     r2, #32
    movw    ip, #0x60E8
    movt    ip, #0xC036
    blx     ip
    add     r0, r10, #O_FOBJ
    movw    ip, #0x6020
    movt    ip, #0xC036
    blx     ip
    add     r0, r10, #O_FOBJ
    mov     r1, #2
    movw    ip, #0x5ED0
    movt    ip, #0xC036
    blx     ip
    /* The .GYR is closed and both halves are free: turn it into a .CSV.
     * Here rather than on the callback, and after the close rather than
     * alongside it, so the file on the card is complete before anything reads
     * it back. Takes a few hundred milliseconds on a long take -- which costs
     * nothing, because the card is busy anyway and the callback is not waiting. */
    bl      gcsv_build

    movw    ip, #0xB6E0
    movt    ip, #0xC002
    blx     ip
    str     r0, [r10, #S_STOP_T1]

    mov     r0, #0
    str     r0, [r10, #S_FILE]
    str     r0, [r10, #S_STOP]
    pop     {r4, pc}

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

put_decimal_3:
    mov     r2, #'0'
8:
    cmp     r1, #100
    blo     9f
    sub     r1, r1, #100
    add     r2, r2, #1
    b       8b
9:
    strb    r2, [r0], #1
    mov     r2, #'0'
10:
    cmp     r1, #10
    blo     11f
    sub     r1, r1, #10
    add     r2, r2, #1
    b       10b
11:
    strb    r2, [r0], #1
    add     r1, r1, #'0'
    strb    r1, [r0]
    bx      lr

/* ==========================================================================
 * put_int — r0 signed value, r1 destination.  Returns the destination advanced.
 *
 * No hardware divide on this core, and repeated subtraction on a fifteen-million
 * microsecond timestamp is not a plan, so the divide by ten is the usual
 * reciprocal multiply: n/10 = (n * 0xCCCCCCCD) >> 35.
 * ========================================================================== */
put_int:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r1
    mov     r5, r0
    cmp     r5, #0
    bge     30f
    mov     r6, #'-'
    strb    r6, [r4], #1
    rsb     r5, r5, #0
30:
    sub     sp, sp, #16
    mov     r8, sp
    mov     r6, #0
31:
    movw    r0, #0xCCCD
    movt    r0, #0xCCCC
    umull   r1, r0, r5, r0
    lsr     r0, r0, #3                  @ r0 = r5 / 10
    add     r1, r0, r0, lsl #2
    sub     r1, r5, r1, lsl #1          @ r5 - 10*(r5/10)
    add     r1, r1, #'0'
    strb    r1, [r8, r6]
    add     r6, r6, #1
    mov     r5, r0
    cmp     r5, #0
    bne     31b
32:
    subs    r6, r6, #1
    blt     33f
    ldrb    r1, [r8, r6]
    strb    r1, [r4], #1
    b       32b
33:
    add     sp, sp, #16
    mov     r0, r4
    pop     {r4, r5, r6, r7, r8, pc}

/* r0 = source (NUL-terminated), r1 = destination.  Returns it advanced. */
put_str:
    push    {r4, lr}
34: ldrb    r4, [r0], #1
    cmp     r4, #0
    beq     35f
    strb    r4, [r1], #1
    b       34b
35: mov     r0, r1
    pop     {r4, pc}

/* ==========================================================================
 * gcsv_build — turn the .GYR just written into a Gyroflow .GCSV beside it.
 *
 * Runs in the writer thread, after the .GYR is closed, with both halves free.
 * The samples are long gone from memory by then -- that is what streaming means
 * -- so the file is read back a block at a time rather than held.
 *
 * This is deliberately not on the gyro callback. The earlier logger built its
 * text there and blocked it for the better part of a second, which is how it
 * missed the next take's start: the callback cannot see ACTIVE go 0 to 1 while
 * it is inside itself. Here the callback sets a flag and returns in microseconds.
 *
 * gscale and the orientation are literals rather than formatted: they are
 * compile-time constants, and formatting a float in ARM to match what the host
 * decoder writes is a lot of code for a string that never changes.
 * ========================================================================== */
gcsv_build:
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}

    /* \A001_018.GYR -> \A001_018.CSV, beside it. */
    add     r0, r10, #O_PATH
    add     r1, r10, #O_GCSV_PATH
    mov     r2, #0
40: ldrb    r3, [r0, r2]
    strb    r3, [r1, r2]
    add     r2, r2, #1
    cmp     r2, #16
    blo     40b
    mov     r3, #'C'
    strb    r3, [r1, #10]
    mov     r3, #'S'
    strb    r3, [r1, #11]
    mov     r3, #'V'
    strb    r3, [r1, #12]

    /* The .GYR, for reading. */
    ldr_addr     ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr     ip, F_VOL
    blx     ip
    mov     r1, r0
    add     r0, r10, #O_FOBJ
    ldr_addr     ip, F_CTOR
    blx     ip
    add     r0, r10, #O_FOBJ
    add     r1, r10, #O_PATH
    mov     r2, #1
    ldr_addr     ip, F_OPEN
    blx     ip
    cmp     r0, #0
    beq     gcsv_out

    /* The .CSV, for writing. */
    ldr_addr     ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr     ip, F_VOL
    blx     ip
    mov     r1, r0
    add     r0, r10, #O_FOBJ2
    ldr_addr     ip, F_CTOR
    blx     ip
    add     r0, r10, #O_FOBJ2
    add     r1, r10, #O_GCSV_PATH
    mov     r2, #7
    ldr_addr     ip, F_OPEN
    blx     ip
    cmp     r0, #0
    beq     gcsv_close_gyr

    /* Header, with the clip name lifted out of the path. */
    movw    r6, #:lower16:O_TEXT
    movt    r6, #:upper16:O_TEXT
    add     r6, r10, r6
    mov     r5, r6
    adr     r0, gcsv_head1
    mov     r1, r5
    bl      put_str
    mov     r5, r0
    add     r0, r10, #O_PATH
    add     r0, r0, #1                  @ past the backslash
    mov     r1, r5
41: ldrb    r2, [r0], #1
    cmp     r2, #'.'
    beq     42f
    cmp     r2, #0
    beq     42f
    strb    r2, [r1], #1
    b       41b
42: mov     r5, r1
    adr     r0, gcsv_head2
    mov     r1, r5
    bl      put_str
    mov     r5, r0

    /* Skip the file header. */
    add     r0, r10, #O_FOBJ
    add     r1, r10, #O_BUF_A
    mov     r2, #160
    add     r3, r10, #S_READ_N
    ldr_addr     ip, F_READ
    blx     ip

    ldr     r11, [r10, #S_START_US]     @ not the header: writer_close put the
                                        @ GFE6 footer there before this ran, and
                                        @ every timestamp came out negative

    add     r0, r10, #O_READ
    mov     r4, r0
    str     r0, [r10, #S_RD_END]        @ nothing buffered yet
    mov     r0, #0
    str     r0, [r10, #S_RD_EOF]
    b       gcsv_refill

/* --- slide the partial block to the front, top the buffer up -------------- */
gcsv_refill:
    /* The old path read a 32-byte header and then the payload, per block: two
     * card operations for every 766 ms of take. Measured at 29 ms each -- one
     * second of stop path for a 26 s clip, and twenty-three seconds for ten
     * minutes. The card is not the reason: the camera loads a 31 MB DNG into
     * memory in 0.17 s, at 183 MB/s. It was being asked for sixteen kilobytes
     * at a time.
     *
     * 624 KiB a go instead. A block can straddle the end of a read, so whatever
     * is left over slides to the front and the next read lands behind it --
     * which is how this avoids needing seek, whose semantics here are unknown. */
    add     r7, r10, #O_READ
    ldr     r8, [r10, #S_RD_END]
    subs    r8, r8, r4                  @ leftover bytes
    movlo   r8, #0
    cmp     r4, r7
    beq     41f                         @ already at the front
    mov     r9, #0
40: cmp     r9, r8
    bhs     41f
    ldrb    r0, [r4, r9]
    strb    r0, [r7, r9]
    add     r9, r9, #1
    b       40b
41:
    ldr     r0, [r10, #S_RD_EOF]
    cmp     r0, #0
    bne     42f
    mov     r0, #0                      @ a failed read may leave this stale, and
    str     r0, [r10, #S_READ_N]        @ a stale count is a buffer of old bytes
    add     r0, r10, #O_FOBJ
    add     r1, r7, r8
    movw    r2, #:lower16:READ_SIZE
    movt    r2, #:upper16:READ_SIZE
    sub     r2, r2, r8                  @ room behind the leftover
    add     r3, r10, #S_READ_N
    ldr_addr     ip, F_READ
    blx     ip
    ldr     r0, [r10, #S_READ_N]
    cmp     r0, #0
    moveq   r1, #1
    streq   r1, [r10, #S_RD_EOF]        @ short read: that was the last of it
    add     r8, r8, r0
42:
    mov     r4, r7
    add     r0, r7, r8
    str     r0, [r10, #S_RD_END]

gcsv_block:
    ldr     r0, [r10, #S_RD_END]
    sub     r0, r0, r4                  @ bytes available at r4
    cmp     r0, #BLOCK_HEADER
    blo     43f
    ldr     r1, [r4]
    movw    r2, #0x4647
    movt    r2, #0x3642                 @ GFB6
    cmp     r1, r2
    bne     gcsv_flush_last             @ not a block: stop here
    ldr     r2, [r4, #24]               @ payload bytes
    add     r2, r2, #BLOCK_HEADER
    cmp     r0, r2
    bhs     44f                         @ the whole block is in the buffer
43: ldr     r0, [r10, #S_RD_EOF]
    cmp     r0, #0
    bne     gcsv_flush_last             @ a truncated tail, and no more file
    b       gcsv_refill
44:
    ldr     r8, [r4, #16]               @ gyro samples
    ldr     r9, [r4, #8]                @ first timestamp
    sub     r9, r9, r11                 @ relative to record start
    add     r7, r4, #BLOCK_HEADER       @ the samples themselves
    add     r4, r4, r2                  @ and the next block

gcsv_sample:
    cmp     r8, #0
    beq     gcsv_block

    mov     r0, r9
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7]
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7, #2]
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7, #6]                @ z sits past the pad
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #10
    strb    r0, [r5], #1

    add     r7, r7, #8
    sub     r8, r8, #1
    movw    r0, #400
    add     r9, r9, r0

    /* Flush well before the end: one line is at most about forty bytes. */
    sub     r0, r5, r6
    movw    r1, #:lower16:TEXT_FLUSH
    movt    r1, #:upper16:TEXT_FLUSH
    cmp     r0, r1
    blo     gcsv_sample
    bl      gcsv_flush
    b       gcsv_sample

gcsv_flush_last:
    bl      gcsv_flush
    add     r0, r10, #O_FOBJ2
    ldr_addr     ip, F_CLOSE
    blx     ip
    add     r0, r10, #O_FOBJ2
    mov     r1, #2
    ldr_addr     ip, F_DTOR
    blx     ip
gcsv_close_gyr:
    add     r0, r10, #O_FOBJ
    ldr_addr     ip, F_CLOSE
    blx     ip
    add     r0, r10, #O_FOBJ
    mov     r1, #2
    ldr_addr     ip, F_DTOR
    blx     ip
gcsv_out:
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}

/* Write out whatever is in the text buffer and rewind it. */
gcsv_flush:
    push    {r0, r1, r2, lr}
    sub     r2, r5, r6
    cmp     r2, #0
    beq     43f
    add     r0, r10, #O_FOBJ2
    mov     r1, r6
    ldr_addr     ip, F_WRITE
    blx     ip
    mov     r5, r6
43: pop     {r0, r1, r2, pc}

gcsv_head1:
    .asciz  "GYROFLOW IMU LOG\nversion,1.3\nid,sigma_fp_v502_internal_icm20321\norientation,xyz\nfwversion,SIGMA fp 5.02\nvideofilename,"
    .align  2
gcsv_head2:
    .asciz  "\ntscale,0.000001\ngscale,0.000137923\nt,gx,gy,gz\n"
    .align  2
