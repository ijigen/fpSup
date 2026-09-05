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
 */

/* Provisional home: the logger's own injection cave, with no logger loaded.
 * When the two producers are assembled into the real thing, these move to the
 * buffer declared out of the pool the way the audio writer declares its own. */
.equ STREAM_GHEAD,   0xC072E1F0     /* u32, gyro ring head we have consumed    */
.equ STREAM_PADBAD,  0xC072E1F4     /* u32, gyro samples whose pad was not 0   */
.equ STREAM_INDEX,   0xC072E1F8     /* u32, monotonic; both producers claim it */
                                    /* 0xC072E1FC spare                        */
.equ STREAM_BASE,    0xC072E200
.equ STREAM_COUNT,   256            /* 2 KiB, about 100 ms of gyro             */
.equ STREAM_MASK,    (STREAM_COUNT - 1)

.equ TAG_GYRO,       0
.equ TAG_ACCEL,      1

.equ HEAD_UNARMED,   0xFFFFFFFF
