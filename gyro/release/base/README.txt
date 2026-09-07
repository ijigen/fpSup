fpGyroSup Base v1 -- SIGMA fp firmware Ver.5.02 only

Put AutoRun.txt and VSHL.BIN in the root of the SD card the camera boots
from, and make sure there is a folder called

    GYRO

in the root of EVERY volume you record to -- the SD card and, if you record
to one, the USB SSD as well.  The camera writes the log beside the clip, on
the same disk, and it will not create the folder for you: making a directory
writes to the file system, and the only two moments it could do that are
while a take is starting (which froze the camera) or at boot, when it can
only guess which disk you will actually use.  One empty folder, once, is the
honest price.

Then record.  Each take writes

    \GYRO\A001_037.GYR    beside    \CINEMA\A001_037

64 bytes of header and then nothing but 8-byte records, gyro and
accelerometer interleaved in the order they happened.  Convert with

    ./gyro/gyr7.py A001_037.GYR --gcsv A001_037.gcsv

If a take produces no .GYR, the folder is missing on that volume.  Nothing
else is wrong and nothing else needs doing.  Formatting a card removes it,
so put it back after you format.

This card carries the stream and nothing else: no gcsv on the camera, no
lens profile, no USB shell.  If you would rather the camera wrote the .gcsv and
the .json for you and left no .GYR at all, that is the main fpGyroSup release,
in the same folder.

    https://ijigen.github.io/fpSup/gyro/web/     convert in a browser
    ./gyro/gyr7.py                               convert on the command line
