# stage5-era tools — superseded

> Kept as history. These cannot run in this tree: what they import or read
> lives outside it, or was retired with the generation they belonged to.
>
> 保留作為歷史。這些在這棵樹裡跑不起來:它們 import 或讀取的東西已經不在,
> 或隨著它們所屬的世代一起退役了。

## `build_imu_snapshot.py`

Assembled a position-independent IMU snapshot blob for the stage5 AutoRun. It
imports `build_stage5_autorun`, which is in the research tree at
`projects/gyro-sup/`, not here, and reads `camera/imu_snapshot.S`, a path that
does not exist in `gyro/`. Both have been true for long enough that the tool
could not have been run from this repository.

It named `0xC072F200` and `0xC072F300` for its code and result, which
`console/fpstate.py` also names for its own snapshot -- two tools, two
meanings, one pair of addresses. Retiring it is half of what ends that; the
other half is fpstate asking `cave.claim`.

The source it assembled, `gyro/imu_snapshot.S`, stays where it is: it is the
readable original of the routine `fpstate.py` carries as a word list, and its
result address is a `#ifndef` default now rather than a claim.
