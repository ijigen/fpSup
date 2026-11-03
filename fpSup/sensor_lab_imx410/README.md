# SensorLab-IMX410 web tools

- [Simulator](simulator/): English Quick Set simulator with custom DC/RES,
  recipe selection, frame-rate limits, crop/aspect illustration and QR codes.
- [Mode viewer](./): decodes the existing camera QR URL; English by default,
  with optional Simplified and Traditional Chinese.

The simulator uses the SensorLab **0.7.26test** C calculation core and QR
encoder compiled to WebAssembly. Everything runs in the browser; no camera,
local server, account or remote calculation service is needed. Image quality,
recording, playback and physical camera stability are not simulated.

These static files are generated from the maintained workspace sources with
`python3 -B projects/sensorlab-imx410/site/build_site.py --simulator`.
`simulator/wasm_info.json` records the version, source fingerprints and binary
checksum. The camera QR payload and its existing directory URL are unchanged.
