.syntax unified
.arm
.text

/* ============================================================================
 * fpGyroSup Base -- the writer puts the block on the card as it stands.
 * ============================================================================
 *
 * Eight-byte records, sixty-four bytes of header, and nothing in between: the
 * payload reaches the card exactly as the producers left it.  Everything else
 * -- the task, the mailbox, the jobs, the take -- is in writer_core.inc.S and
 * is shared with the edition that writes a .gcsv instead.
 * ========================================================================== */

#include "writer_core.inc.S"


/* The ring-walking drain that came before the job queue is gone.  It read the
 * ring's indices and decided what to write; in the audio shape the producer
 * decides that and the writer only carries out what a job says.  Keeping both
 * would have been two owners of the same tail. */

/* writer_put(r4 = the job).  AudioFileWriter::v1's two branches.
 *
 * If the job says it belongs exactly where the file already is, write straight
 * through.  If it does not -- which means a job in between never made it --
 * seek to where it says first, so the gap stays a gap of the right size instead
 * of every later record sliding earlier.
 */
writer_put:
    push    {r4, r5, r6, lr}
    movw    r5, #:lower16:T_POS
    movt    r5, #:upper16:T_POS
    ldr     r6, [r5]
    ldr     r0, [r4, #J_OFF]
    cmp     r6, r0
    beq     2f

#ifndef DRY_RUN
    movw    r1, #:lower16:T_FOBJ
    movt    r1, #:upper16:T_FOBJ
    ldr     r1, [r1]
    mov     r2, r0
    mov     r0, r1
    mov     r1, r2
    mov     r2, #0                      @ from the start of the file
    movw    ip, #:lower16:F_SEEK
    movt    ip, #:upper16:F_SEEK
    blx     ip
#endif
    movw    ip, #:lower16:T_SEEKS
    movt    ip, #:upper16:T_SEEKS
    ldr     r0, [ip]
    add     r0, r0, #1
    str     r0, [ip]                    @ every one of these is a job that was lost
    ldr     r0, [r4, #J_OFF]

2:  ldr     r2, [r4, #J_LEN]
    add     r0, r0, r2
    str     r0, [r5]                    @ where the file is once this lands

#ifndef DRY_RUN
    ldr     r1, [r4, #J_PTR]
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
    movw    ip, #:lower16:T_WRC
    movt    ip, #:upper16:T_WRC
    str     r0, [ip]
#else
    /* Everything except the card.  The path is otherwise identical -- the same
     * post, the same descriptor, the same mailbox, the same wake, the same
     * release -- so a run that survives here and dies without the flag has
     * narrowed the trouble to the card calls and nothing else. */
    movw    ip, #:lower16:T_WRC
    movt    ip, #:upper16:T_WRC
    mov     r0, #1
    str     r0, [ip]
#endif
    ldr     r2, [r4, #J_LEN]
    movw    ip, #:lower16:T_BYTES
    movt    ip, #:upper16:T_BYTES
    ldr     r0, [ip]
    add     r0, r0, r2
    str     r0, [ip]
    movw    ip, #:lower16:T_WRITES
    movt    ip, #:upper16:T_WRITES
    ldr     r0, [ip]
    add     r0, r0, #1
    str     r0, [ip]
    pop     {r4, r5, r6, lr}
    bx      lr



/* ------------------------------------------------------------- the file */

/* Open the file the ring drains into.  The same six calls the logger and the
 * audio writer both make, in the same order:
 *
 *     F_MGR()          the media manager
 *     F_VOL(mgr, 0)    the volume it is currently writing to
 *     F_CTOR(obj, vol) build the file object
 *     F_OPEN(obj, path, mode)
 *
 * Mode 7 overwrites; 0x402 fails when the file already exists, which is a
 * latent bug rather than a safety feature.
 *
 * If the open fails the object is destroyed.  A file object left constructed
 * wedges the file system -- that is what happened to \LENS.DAT, which nothing
 * could open again until the camera was power cycled.
 */
    .global writer_openfile
writer_openfile:
    push    {r4, r5, r6, lr}
#ifdef DRY_RUN
    /* No file object is built and nothing touches the volume.  T_FOPEN is what
     * every other decision reads, so setting it is enough to make the rest of
     * the machinery behave exactly as it would with a real file. */
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    mov     r0, #1
    str     r0, [ip]
    pop     {r4, r5, r6, lr}
    bx      lr
#endif
    movw    r4, #:lower16:T_FOBJ
    movt    r4, #:upper16:T_FOBJ
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f

    movw    ip, #:lower16:F_MGR
    movt    ip, #:upper16:F_MGR
    blx     ip
    mov     r1, #0
    movw    ip, #:lower16:F_VOL
    movt    ip, #:upper16:F_VOL
    blx     ip
    mov     r5, r0                      @ the volume: the ctor's, and the name's
    bl      take_path
    bl      base_path
    mov     r6, r0
    mov     r1, r5
    mov     r0, r4
    movw    ip, #:lower16:F_CTOR
    movt    ip, #:upper16:F_CTOR
    blx     ip

    mov     r0, r4
    mov     r1, r6
    mov     r2, #F_MODE_AUD             @ 6, the mode AudF_W opens with
    movw    ip, #:lower16:F_OPEN
    movt    ip, #:upper16:F_OPEN
    blx     ip
    /* If it did not open, it did not open.  \GYRO has to already exist on
     * whatever volume is being recorded to, and putting it there is the
     * user's business -- makecard.py does it for the SD card and a USB SSD
     * is the same one folder.
     *
     * We tried making it ourselves and it was wrong twice over.  On the
     * record-start path it wrote FAT metadata in SRecFile's thread and froze
     * the camera on every take to the SSD, while the SD card -- which already
     * had the folder, so the mkdir was skipped -- stayed fine all session.
     * Moved to boot it stopped freezing and started guessing: F_VOL returns
     * the volume the camera is routed to AT THAT MOMENT, which is not
     * necessarily the one the user records to an hour later.  A wrong folder
     * on the wrong disk, silently.  Neither is worth a missing folder. */
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    str     r0, [ip]
    cmp     r0, #0
    beq     8f

    /* What AudF_W does next, and we did not: XC_MediaFileSdCard::v13, vtable
     * +0x3C, which takes the card lock and stamps the file.  Copied because the
     * instruction is to copy, and because a file the firmware has stamped is a
     * file the firmware's own bookkeeping has seen. */
    mov     r0, r4
    movw    ip, #:lower16:F_STAMP
    movt    ip, #:upper16:F_STAMP
    blx     ip

    mov     r0, r5                      @ still the volume
    bl      take_header

    /* The tail is NOT touched here.  Whoever asked for the file to be opened
     * decides where the take starts: the record hook latches it at the instant
     * recording begins. */
    b       9f

8:

    mov     r0, r4                      @ it did not open: do not leave it built
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip

9:  pop     {r4, r5, r6, lr}
    bx      lr

/* Take whatever is still in the ring, then close.  Draining first is not a
 * nicety: the last span of a take is the one a stop path most easily loses. */
    .global writer_closefile
writer_closefile:
    push    {r4, r5, r6, lr}
    movw    r6, #:lower16:T_STAGE
    movt    r6, #:upper16:T_STAGE
    mov     r0, #0x21
    str     r0, [r6]                    @ entered

    movw    r4, #:lower16:T_FOPEN
    movt    r4, #:upper16:T_FOPEN
    ldr     r5, [r4]
    cmp     r5, #0
    beq     9f
#ifdef DRY_RUN
    mov     r0, #0
    str     r0, [r4]                    @ nothing was opened; nothing to close
    mov     r0, #0x25
    str     r0, [r6]                    @ the stage the real path ends on
    pop     {r4, r5, r6, lr}
    bx      lr
#endif

    /* No drain here.  Everything of this take was written as jobs, and the
     * stop job came out of the queue behind all of them -- draining again
     * would write the whole ring a second time. */
    mov     r0, #0x23
    str     r0, [r6]                    @ about to close

    /* What the header could not know at open.  The join is done and the mailbox
     * and the thread are gone, so the file is ours again. */
    mov     r0, #G_OFF_HEADER
    bl      blob_at
    movw    r1, #:lower16:B_OFF
    movt    r1, #:upper16:B_OFF
    ldr     r1, [r1]
    sub     r1, r1, #HDR_BYTES
    str     r1, [r0, #H_PAYLOAD]
    movw    r1, #:lower16:B_DROPS
    movt    r1, #:upper16:B_DROPS
    ldr     r1, [r1]
    str     r1, [r0, #H_DROPPED]
    bl      put_header

    /* The destructor and nothing else.  AudioFileWriter::v0 calls
     * XC_MediaFile::v0 and never F_CLOSE, because the destructor closes the
     * file itself -- FUN_c0366020 is its first act.  Calling F_CLOSE first put
     * us through that path twice: once for real, and once as a no-op on an
     * object whose handle we had already nulled.  Audio goes through it once. */
    movw    r6, #:lower16:T_FOBJ
    movt    r6, #:upper16:T_FOBJ
    ldr     r6, [r6]                    @ r6 stops being T_STAGE here
    movw    ip, #:lower16:T_STAGE
    movt    ip, #:upper16:T_STAGE
    mov     r0, #0x24
    str     r0, [ip]                    @ about to destroy
    mov     r0, r6
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip
    movw    ip, #:lower16:T_STAGE
    movt    ip, #:upper16:T_STAGE
    mov     r0, #0x25
    str     r0, [ip]                    @ destroyed, all the way through
    mov     r0, #0
    str     r0, [r4]

9:  pop     {r4, r5, r6, lr}
    bx      lr

/* take_header -- fill in the sixty-four bytes and put them at the front.
 *
 * r0 = the volume.  Called from writer_openfile with the file open and no
 * writer task in existence yet, so the file position is ours alone.
 *
 * Sensor mode, exposure and geometry read as nothing while the camera is idle.
 * Record start is the only moment they can be taken, which is why they are
 * taken here and not by the shell afterwards.
 */
take_header:
    push    {r4, r5, r6, lr}
    mov     r5, r0                      @ the volume, before anything else can
    mov     r0, #G_OFF_HEADER           @ have it -- blob_at returns in r0
    bl      blob_at
    mov     r4, r0

    movw    r0, #0x4647
    movt    r0, #0x3753                 @ "GFS7"
    str     r0, [r4, #H_MAGIC]
    mov     r0, #GYR_VERSION
    str     r0, [r4, #H_VERSION]
    movw    r0, #:lower16:GYR_PERIOD_PS
    movt    r0, #:upper16:GYR_PERIOD_PS
    str     r0, [r4, #H_PERIOD_PS]
    movw    r0, #:lower16:GYR_GSCALE
    movt    r0, #:upper16:GYR_GSCALE
    str     r0, [r4, #H_GSCALE]
    movw    r0, #:lower16:GYR_ORIENT
    movt    r0, #:upper16:GYR_ORIENT
    str     r0, [r4, #H_ORIENT]
    str     r5, [r4, #H_VOLUME]

    /* The clip id, straight out of the name take_path just built: the two are
     * the same eight characters by construction, so there is no second place
     * for them to disagree. */
    mov     r0, #G_OFF_PATH
    bl      blob_at
    ldr     r1, [r0, #6]
    str     r1, [r4, #H_CLIP]
    ldr     r1, [r0, #10]
    str     r1, [r4, #H_CLIP + 4]

    mov     r0, #0
    str     r0, [r4, #H_PAYLOAD]        @ filled in at close
    str     r0, [r4, #H_DROPPED]
    str     r0, [r4, #0x38]
    str     r0, [r4, #0x3C]

    movw    ip, #:lower16:SENSOR_MODE_FN
    movt    ip, #:upper16:SENSOR_MODE_FN
    blx     ip
    str     r0, [r4, #H_MODE]
    movw    ip, #:lower16:EXPOSURE_FN
    movt    ip, #:upper16:EXPOSURE_FN
    blx     ip
    str     r0, [r4, #H_EXPOSURE]
    mov     r0, #0
    str     r0, [r4, #H_WIDTH]
    str     r0, [r4, #H_HEIGHT]
    movw    ip, #:lower16:F_CAMSETTING
    movt    ip, #:upper16:F_CAMSETTING
    blx     ip
    cmp     r0, #0
    beq     1f
    add     r0, r0, #SETTING_DIMS
    ldr     r1, [r0]
    ldr     r2, [r0, #4]
    /* Refuse anything that is not a plausible frame rather than write a
     * number the profile would then be built on. */
    cmp     r1, #640
    blo     1f
    cmp     r2, #360
    blo     1f
    movw    r0, #0x2000
    cmp     r1, r0
    bhi     1f
    cmp     r2, r0
    bhi     1f
    add     r1, r1, #DNG_PAD_W
    add     r2, r2, #DNG_PAD_H
    str     r1, [r4, #H_WIDTH]
    str     r2, [r4, #H_HEIGHT]
1:

    /* The first block belongs after the header.  This lives here, not in
     * take_open, because opening a file is what starts one: --dropfile after a
     * freeze opens nothing and closes what is already there, and with B_OFF
     * owned by the record hook that path stamped the PREVIOUS take's length
     * into the new header.  Whoever opens the file owns where it is. */
    movw    r0, #:lower16:B_OFF
    movt    r0, #:upper16:B_OFF
    mov     r1, #HDR_BYTES
    str     r1, [r0]

    mov     r0, r4
    bl      put_header
    pop     {r4, r5, r6, lr}
    bx      lr

/* put_header -- seek to zero and write the sixty-four bytes.  Nothing else is
 * touching the file when this runs: at open the writer task does not exist yet,
 * at close the join has already collected it. */
put_header:
    push    {r4, r5, r6, lr}
    mov     r5, r0
#ifndef DRY_RUN
    movw    r4, #:lower16:T_FOBJ
    movt    r4, #:upper16:T_FOBJ
    ldr     r4, [r4]
    mov     r0, r4
    mov     r1, #0
    mov     r2, #0
    movw    ip, #:lower16:F_SEEK
    movt    ip, #:upper16:F_SEEK
    blx     ip
    mov     r0, r4
    mov     r1, r5
    mov     r2, #HDR_BYTES
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
#endif
    movw    ip, #:lower16:T_POS
    movt    ip, #:upper16:T_POS
    mov     r0, #HDR_BYTES
    str     r0, [ip]                    @ the file is at the end of the header
    pop     {r4, r5, r6, lr}
    bx      lr

/* The header, rebuilt at every take_open and rewritten at every close. */
writer_header:
    .space  HDR_BYTES
    .align  2

/* base_path -- \GYRO\A001_037.GYR, around the clip name take_path worked out.
 *
 * Where a file goes is the edition's business now: the core knows what the take
 * is called, which is the part that needed the manager arithmetic, and each
 * edition decides the rest.  Base has always put its log here and the folder
 * rule in its README is about this directory.
 */
base_path:
    push    {r4, r5, r6, lr}
    mov     r0, #G_OFF_PATH
    bl      blob_at
    mov     r6, r0
    movw    r0, #0x475C
    movt    r0, #0x5259                 @ "\\GYR"
    str     r0, [r6]
    movw    r0, #0x5C4F                 @ "O\\"
    strh    r0, [r6, #4]
    mov     r0, #G_OFF_CLIP
    bl      blob_at
    mov     r4, r0
    mov     r5, #0
1:  ldrb    r0, [r4, r5]
    cmp     r0, #0
    beq     2f
    add     r1, r6, #6
    strb    r0, [r1, r5]
    add     r5, r5, #1
    b       1b
2:  add     r6, r6, #6
    add     r6, r6, r5                  @ past the name
    mov     r0, #'.'
    strb    r0, [r6], #1
    mov     r0, #'G'
    strb    r0, [r6], #1
    mov     r0, #'Y'
    strb    r0, [r6], #1
    mov     r0, #'R'
    strb    r0, [r6], #1
    mov     r0, #0
    strb    r0, [r6]
    mov     r0, #G_OFF_PATH
    bl      blob_at
    pop     {r4, r5, r6, lr}
    bx      lr
