fpGyroSup v1.14.0 -- SIGMA fp firmware Ver.5.02 only

Put AutoRun.txt and fpSup.BIN in the root of the SD card the camera boots
from, and record CinemaDNG.  Nothing else: no folder to make, no file to
convert, no step after the take.

WHAT CHANGED SINCE v1.13.1

  The payload is unchanged.  The loader and its second stage are new
  (2026-09-25), and they change what happens when the camera is
  switched off.

  - Every firmware word this card changes is recorded when it loads
    and written back when the camera powers off.  Turning the camera
    off with the power switch keeps the firmware in memory -- it is a
    warm restart, not a cold one -- and until now the changes stayed
    in it, into the next boot and whatever card was in the slot then.
    Now the camera powers off stock.

    The gyro no longer registers a power-off routine of its own.  Its
    four hook sites are part of the loader's write-back, the same one
    that covers every other card.

  - This card still starts the ordinary way on every boot: the
    AutoRun runs and the progress bar shows.  The instant start (the
    card loaded about 1.4 s after power-on, no AutoRun) and the short
    cold start are packaging, not part of this card: build the card on
    the fpSup-Merge page and tick Fast Start 2.

  NOTE  The write-back runs as part of a normal power-off.  If the
        camera loses power without one -- a frozen camera with the
        battery pulled -- it does not run, and the changed words can
        stay in memory until the camera next starts cold.

Each take writes both of the files Gyroflow wants, inside the clip's own
folder, while it is being recorded:

    \CINEMA\A001_037\A001_037.gcsv    the IMU log
    \CINEMA\A001_037\A001_037.json    the lens profile

Load the frames and both files into Gyroflow and run its synchronisation as
usual.  There is nothing to convert, but the offset still has to be found:
CinemaDNG carries no timecode, and the log starts about half a second after
the first frame -- measured between 470 and 570 ms, and different every take --
so it is not a number you can fill in once and reuse.

The log is every sample the gyro produced -- 2499.466 Hz, nothing averaged and
nothing dropped -- with each accelerometer reading placed on the row of the
sample it followed.  The profile carries the lens's own distortion, read out
of the camera's calibration data for whatever is mounted, so it is the same
curve the camera puts in a DNG's WarpRectilinear opcode.

Portrait takes need nothing done to them.  In CINE the camera records every
frame landscape upright, so Gyroflow reads a portrait take exactly as it
reads a landscape one: load the frames and the two sidecars, sync, stabilise,
and turn the picture at the end of the edit.  Leave horizon lock off.
Photographs are untouched and still rotate by themselves.

CinemaDNG only.  A MOV take gets no sidecars: MOV records through a different
path this build does not hook.  Use fpGyroSup Base for MOV -- it writes a .GYR
beside any take -- or v1.1 of this line.

This card carries no USB shell.  Nothing is flashed: take the two files off
the card, or pull the battery, and the camera is exactly as it was.
