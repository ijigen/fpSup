fp 5.02 main OSD software front descriptor, offline proof 2026-10-30

The last committed main-layer descriptor is W(0xC3824FF0), and its frame
base is W(descriptor+4). This is the software presentation selection, not
a proven hardware LCD scanout latch. No camera operation was performed.

Main layer: 0xC3824FA8, vtable 0xC2EF6280.
  +0x3c/+0x40/+0x44: descriptor table (three entries)
  +0x48, address C3824FF0: last committed/front descriptor
  +0x4c, address C3824FF4: next/back drawing descriptor
  +0x50, address C3824FF8: current table index (0..2)
Known descriptor addresses: C38D6DB0/C38D6DCC/C38D6DE8.
Observed frame bases: C6200180/C6355180/C64AA180 (do not hard-code their
current order). Descriptor+8 points to width/height; current size 1024x682.

Primary native evidence is saved with instruction bytes in
native-disassembly.txt, from out/MAIN_c0000000.bin SHA256
92a8ee993f6c3d66c251e88d45a2ccd5135c6cf7342717784321c2ed506e2fb4.
  vtable+0x0c C07212E0 -> C0721CB8(layer+0x24) reads layer+0x48.
  vtable+0x10 C0721328 -> C0721CC8(layer+0x24) reads layer+0x4c.
  vtable+0x14 C0721370 locks layer+0x20 then C0721CD8 advances the ring:
    index=(index+1)%3; front=table[index]; back=table[(index+1)%3].
  C0528A18 commits through vtable+0x14, then C0528A38 presents.
  C0528650 calls vtable+0x0c; the selected descriptor reaches C02E5550.
  C02E8AD0 reads descriptor+4, converts the address via C001D978, and
    writes the output request. C02E8C5C submits via C02E6250.
  C0528BA0 separately uses +0x0c as copy source and +0x10 as destination.

prove_front.py executes the original ARM getters, readiness leaf and
rotation, with only synthetic layer/table/stack RAM. It does not stub
those functions. Three initial indices times nine rotations: 81 native
calls and 27 commits passed; getter results, preserved stack and exact
three-word rotation writes are checked. proof.json preserves the result.
Run with an existing Python environment containing unicorn and capstone:
  python3 -B projects/sensorlab-imx410/tools/osd-front/prove_front.py
The macOS sandbox may require the established offline Unicorn exception.

For a read-only capture, read the three table pointers plus front/back/
index together and require front==table[index] and back==table[(index+1)%3].
Read the front pointer again after copying pixels and report changes.
This detects many races, not three-swap ABA or hardware presentation lag;
prefer a settled screen. Reading all three buffers and choosing the most
plausible image can select a stale page. No live helper is added here.
