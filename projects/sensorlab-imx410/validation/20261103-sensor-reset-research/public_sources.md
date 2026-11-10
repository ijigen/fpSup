# Public-source check: sensor reset versus link synchronization

Checked 2026-11-03. This is offline research, not a camera measurement.

## Sony IMX410CQK product information

Source: https://www.sony-semicon.com/files/62/pdf/p-13_IMX410CQK_Flyer.pdf

The two-page Sony document identifies the IMX410CQK's 72 MHz input and eight-lane
SLVS-EC output, but does not give a register map, a FIFO-clear command, or a
startup/standby sequence. It cannot establish the meaning of `0011`, `0002`, or
`00D1–00D3`. No IMX410-specific documented FIFO-clear setting was located in this
search. This is a search result, not proof that such an internal function cannot exist.

## Direct IMX410 link measurements

Source: https://landingfield.wordpress.com/2021/05/10/decoding-the-slvs-ec-protocol-from-imx410bqt/

The author's IMX410BQT experiment decoded frame/line-valid flags and a line index
from SLVS-EC packet headers; the index restarts with XVS/XHS. The author also
reported that A7 III initialization activated the transmitter on the Nikon part
but did not produce valid image data; Nikon initialization did. This is primary
experimental evidence for that device, not a register specification for the fp's
variant.

Implications for this investigation:

- A truncated sensor line and a receiver's incorrect line-start handling require
  different fixes. DNG pixels alone do not expose the original packet flags.
- Reusing another IMX410 camera's startup bytes is not justified simply by the
  shared model family. Compare the role and ordering, then use fp-native controls.

## Receiver vendor documentation

Source: https://www.microchip.com/content/dam/mchp/documents/FPGA/ProductDocuments/UserGuides/polarfire_fpga_slvs_ec_user_guide.pdf

Microchip's SLVS-EC receiver guide describes separate byte alignment, PHY packet
decoding, and payload/line/frame-valid decoding stages (sections 3.1–3.4). It also
distinguishes sensor standby/sync codes from reset of the receiver itself.

This supports investigating boundary synchronization as a class of mechanism.
It does **not** describe the fp SoC and cannot decode any undocumented fp MMIO
bit, identify the fp's FIFO depth, or establish that a receiver reset fixes the
recorded first-frame defect.

## Excluded shortcuts

- Do not transplant `SW_RESET`, `REGHOLD`, or corrupted-frame masking addresses
  from IMX219/415/455/571/678 datasheets or drivers into the IMX410.
- Do not equate a CPU D-cache clean, clearing DRAM, sensor standby, SLVS link
  training, and a sensor FIFO flush. They act at different boundaries.
- Packet-header observation would be decisive, but the current fp research has
  not identified a validated software accessor for these flags. A future test
  must not label ordinary TG counters as raw sensor packet headers.
