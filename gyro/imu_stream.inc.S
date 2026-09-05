/* One ordered stream, one record shape.
 *
 *      0   i16  x
 *      2   i16  y
 *      4   i16  tag     0 = gyroscope, 1 = accelerometer
 *      6   i16  z
 *
 * Eight bytes either way, and the tag is the only thing that separates them.
 *
 * There is no per-record timestamp, and that is the point.  The gyro runs on a
 * strictly uniform 2500 Hz hardware grid, so a gyro record's position in the
 * stream already says when it happened: one step back is 400 us earlier.  The
 * clock reads that used to stand in for this come from a TickTimer call made
 * inside the callback, which lags the last sample by however long the callback
 * took to arrive -- nought to a millisecond of jitter, which the old seam
 * arithmetic then had to spend code undoing.  A per-record timestamp would have
 * sprayed that jitter across every row instead of the block boundary.  So the
 * grid is the time base and one anchor per block places the whole run.
 *
 * The accelerometer has no grid of its own -- the firmware publishes it at
 * about 47 Hz, unevenly -- so it does not get a time of its own either.  It is
 * appended where it happens, between two gyro records, and it belongs to the
 * row it lands next to.  The reader advances 400 us on tag 0 and does not
 * advance on tag 1.
 *
 * The one honest cost: the gyro producer runs in the firmware's GyroData
 * callback, measured at 50.0 Hz -- 1170 drains in 23.378 s -- so it appends a
 * whole 20 ms batch at once, at the end of the 20 ms it covers.  An
 * accelerometer record that arrives between two callbacks is appended at its own
 * true instant, but the gyro record it lands against is the last one of the
 * batch that has already been drained.  So the reader dates it to the start of
 * the interval it actually arrived in: nought to twenty milliseconds EARLY, ten
 * on average.  Early, not late -- the gyro records are what run behind, and the
 * accelerometer inherits their lag.
 *
 * The accelerometer only ever feeds a gravity vector at 47 Hz, which does not
 * move in 20 ms, so this is left as it is rather than paid for.  It is written
 * down because "position implies time" is a claim and this is the size of the
 * claim's error.  It is also fixable for free if it ever matters: the hook could
 * latch the firmware ring's head along with the sample, and the gyro producer
 * splice the record in at that position inside the batch instead of after it.
 *
 * tag 2 is a video frame exposure.  Not a row either, and it carries no time of
 * its own -- it IS a time, the one the clip is cut on.  Its position says which
 * gyro sample the frame was exposed against, so both of the questions that
 * matter -- how many samples per frame, and which sample is frame zero -- are
 * read straight out of the stream rather than computed from a clock.
 *
 * Note what this does NOT claim.  Audio is in sync with video without knowing
 * an accurate start time at all: both begin filling at the same event, so any
 * common offset is invisible inside the clip.  By the same argument, a gyro
 * stream that begins at that event needs no timestamp either.  So the 470-570
 * ms our anchor is out by is not evidence that the factory's start point is
 * late -- it has never been established which side is late, and the marker is
 * here to settle that by measurement rather than to assume it.
 */

/* Provisional home: the logger's own injection cave, with no logger loaded.
 * When the two producers are assembled into the real thing, these move to the
 * buffer declared out of the pool the way the audio writer declares its own. */
.equ STREAM_FCOUNT,  0xC072E1E0     /* u32, frame markers appended             */
.equ STREAM_F0_GC,   0xC072E1E4     /* u32, STREAM_GCOUNT at the FIRST marker.
                                     * The ring holds only 100 ms, so frame
                                     * zero is long gone by the end of a take.
                                     * This keeps the one number that cannot be
                                     * recovered afterwards: which gyro sample
                                     * the take's first exposure landed on.
                                     * With it, (gcount - f0_gc) / (fcount - 1)
                                     * is the samples-per-frame over the whole
                                     * take, measured against the camera's own
                                     * frame clock and nothing else.          */
.equ STREAM_V0_GC,   0xC072E1C0     /* u32, STREAM_GCOUNT at the first sensor
                                     * Vd after recording began.  THE anchor:
                                     * the gyro sample the take's first frame
                                     * was read out against.  Vd is the
                                     * exposure side of the pipeline -- a frame
                                     * reaches the card hundreds of buffered
                                     * milliseconds later, so the file write is
                                     * the wrong end to measure from.        */
.equ STREAM_VCOUNT,  0xC072E1C4     /* u32, Vd since the start re-armed it.
                                     * Vd free-runs in liveview, so the count
                                     * is meaningless unless something resets
                                     * it -- the record-start hook does.     */
.equ STREAM_R1_GC,   0xC072E1D0     /* u32, STREAM_GCOUNT when recording ended */
.equ STREAM_R1_N,    0xC072E1D4     /* u32, times that has happened            */
.equ STREAM_R0_GC,   0xC072E1E8     /* u32, STREAM_GCOUNT when the audio file
                                     * writer was constructed.  Beside F0_GC
                                     * this is the whole experiment: the gap
                                     * between them is how far our start point
                                     * sits from the take's first exposure,
                                     * measured in gyro samples of 400 us --
                                     * a number, where the 470-570 ms has only
                                     * ever been an inference from Gyroflow's
                                     * auto-sync.
                                     *
                                     * MEASURED 2026-09-06, two takes: the gap
                                     * between R0 and R1 tracked the take -- an
                                     * 11 s take gave 11.38 s, a 3 s take gave
                                     * 4.40 s -- and 0xC01FBA28 fired first
                                     * both times.  So that one is the start
                                     * and 0xC01FB880 is the end, which is the
                                     * opposite of what the call sites read
                                     * like.  movRec tears the running monitor
                                     * audio down when recording begins; the
                                     * state machine's case 1 builds it back up
                                     * when recording ends.                   */
.equ STREAM_R0_N,    0xC072E1EC     /* u32, times that has happened            */
.equ STREAM_GHEAD,   0xC072E1F0     /* u32, gyro ring head we have consumed    */
.equ STREAM_PADBAD,  0xC072E1F4     /* u32, gyro samples whose pad was not 0   */
.equ STREAM_INDEX,   0xC072E1F8     /* u32, monotonic; both producers claim it */
.equ STREAM_GCOUNT,  0xC072E1FC     /* u32, gyro records only -- the rate ruler */
.equ STREAM_BASE,    0xC072E200
.equ STREAM_COUNT,   256            /* 2 KiB, about 100 ms of gyro             */
.equ STREAM_MASK,    (STREAM_COUNT - 1)

.equ TAG_GYRO,       0
.equ TAG_ACCEL,      1
.equ TAG_FRAME,      2
.equ TAG_START,      3
.equ TAG_STOP,       4
.equ TAG_VD,         5

.equ HEAD_UNARMED,   0xFFFFFFFF
