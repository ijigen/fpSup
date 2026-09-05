"""The reader for the ordered IMU stream.

The camera will do this in gcsvgen.S; this is the reference that says what the
bytes mean, and what the tests hold it to.

A record is eight bytes -- x, y, tag, z, four signed halfwords -- and the tag is
the whole protocol:

    tag 0   a gyroscope sample.  It is a row.  Time is position: the row after
            it is 400 us later, because the sensor's 2500 Hz grid is uniform and
            a sample cannot be missing without the index saying so.
    tag 1   an accelerometer sample.  It is not a row.  It belongs to the row
            being built, and time does not advance across it.
    tag 2   a video frame exposure.  Also not a row, also does not advance
            time.  Its position is the answer to "which gyro sample was this
            frame exposed against", which is the anchor, and counting rows
            between two of them is the gyro rate measured against the camera's
            own clock rather than the host's.
    tag 3   the movie recorder committing to start.
    tag 4   the movie recorder stopping.  Neither is a row and neither advances
            time; both are the camera's own record boundaries, put in the
            stream so the gap between "recording started" and "first frame
            exposed" is a count of samples rather than an inference.

Nothing carries a timestamp.  One anchor for the whole run places it on the
clock; everything after that is counting.
"""
import struct

TAG_GYRO, TAG_ACCEL, TAG_FRAME, TAG_START, TAG_STOP = 0, 1, 2, 3, 4
RECORD = 8
GYRO_PERIOD_US = 400.0          # 2500 Hz, the hardware grid


def records(blob):
    """Split a buffer into (x, y, tag, z) tuples."""
    if len(blob) % RECORD:
        raise ValueError(f'{len(blob)} bytes is not a whole number of records')
    return [struct.unpack_from('<hhhh', blob, i) for i in range(0, len(blob), RECORD)]


def rows(recs, t0=0.0, period=GYRO_PERIOD_US):
    """Walk records into rows: (t_us, gyro xyz, accel xyz or None, frame or None).

    A non-gyro record before the first gyro record has no row to attach to; it
    is carried forward onto the first one rather than dropped, which is what
    happens at the start of a buffer whose first gyro batch has not landed yet.
    """
    out = []
    pending_a = None
    pending_f = None
    t = t0
    for x, y, tag, z in recs:
        if tag == TAG_ACCEL:
            pending_a = (x, y, z)
            continue
        if tag == TAG_FRAME:
            pending_f = ('frame', x & 0xFFFF)
            continue
        if tag == TAG_START:
            pending_f = ('start', x & 0xFFFF)
            continue
        if tag == TAG_STOP:
            pending_f = ('stop', x & 0xFFFF)
            continue
        if tag != TAG_GYRO:
            raise ValueError(f'unknown tag {tag}')
        out.append((t, (x, y, z), pending_a, pending_f))
        pending_a = pending_f = None
        t += period
    return out


def frame_spacing(recs):
    """Gyro records between consecutive frame markers.

    This is the number the whole exercise is for: the gyro rate expressed in
    the camera's own frame clock, with no host clock anywhere in it.  29.97 fps
    against a true 2500 Hz would be 83.417 samples a frame.

    Returns (spacings, samples_per_frame) -- the list so an outlier is visible
    rather than averaged away, since a marker lost to a ring wrap looks exactly
    like a doubled interval.
    """
    gaps, n, seen = [], 0, False
    for x, y, tag, z in recs:
        if tag == TAG_GYRO:
            n += 1
        elif tag == TAG_FRAME:
            if seen:
                gaps.append(n)
            seen, n = True, 0
    mean = sum(gaps) / len(gaps) if gaps else None
    return gaps, mean


def summary(recs):
    """What a dump is for: are the producers interleaving as expected."""
    ngyro = sum(1 for r in recs if r[2] == TAG_GYRO)
    naccel = sum(1 for r in recs if r[2] == TAG_ACCEL)
    nframe = sum(1 for r in recs if r[2] == TAG_FRAME)
    known = (TAG_GYRO, TAG_ACCEL, TAG_FRAME, TAG_START, TAG_STOP)
    unknown = sorted({r[2] for r in recs if r[2] not in known})
    _gaps, per_frame = frame_spacing(recs)
    nstart = sum(1 for r in recs if r[2] == TAG_START)
    nstop = sum(1 for r in recs if r[2] == TAG_STOP)
    return {'gyro': ngyro, 'accel': naccel, 'frame': nframe,
            'start': nstart, 'stop': nstop, 'unknown': unknown,
            'per_accel': (ngyro / naccel) if naccel else None,
            'per_frame': per_frame,
            'duration_us': ngyro * GYRO_PERIOD_US}
