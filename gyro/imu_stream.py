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

Nothing carries a timestamp.  One anchor for the whole run places it on the
clock; everything after that is counting.
"""
import struct

TAG_GYRO, TAG_ACCEL = 0, 1
RECORD = 8
GYRO_PERIOD_US = 400.0          # 2500 Hz, the hardware grid


def records(blob):
    """Split a buffer into (x, y, tag, z) tuples."""
    if len(blob) % RECORD:
        raise ValueError(f'{len(blob)} bytes is not a whole number of records')
    return [struct.unpack_from('<hhhh', blob, i) for i in range(0, len(blob), RECORD)]


def rows(recs, t0=0.0, period=GYRO_PERIOD_US):
    """Walk records into rows: (t_us, gyro xyz, accel xyz or None).

    An accelerometer record before the first gyro record has no row to attach
    to; it is carried forward onto the first one rather than dropped, which is
    what happens at the very start of a buffer whose first gyro batch has not
    landed yet.
    """
    out = []
    pending = None
    t = t0
    for x, y, tag, z in recs:
        if tag == TAG_ACCEL:
            pending = (x, y, z)
            continue
        if tag != TAG_GYRO:
            raise ValueError(f'unknown tag {tag}')
        out.append((t, (x, y, z), pending))
        pending = None
        t += period
    return out


def summary(recs):
    """What a dump is for: are the two producers interleaving as expected."""
    ngyro = sum(1 for r in recs if r[2] == TAG_GYRO)
    naccel = sum(1 for r in recs if r[2] == TAG_ACCEL)
    unknown = sorted({r[2] for r in recs if r[2] not in (TAG_GYRO, TAG_ACCEL)})
    return {'gyro': ngyro, 'accel': naccel, 'unknown': unknown,
            'per_accel': (ngyro / naccel) if naccel else None,
            'duration_us': ngyro * GYRO_PERIOD_US}
