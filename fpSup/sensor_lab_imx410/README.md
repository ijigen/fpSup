# SensorLab-IMX410 web page

One static page: the Quick Set simulator, which is also where the camera's QR code lands
(`https://ijigen.github.io/fpSup/sensor_lab_imx410/#<code>`). A code in the address is decoded and
loaded into the simulator, with the full mode details (sensor crop, binning, ISP scale, recorded
bit depth, sizes, rolling shutter, data rates). Anything the simulator cannot show exactly is listed
on the page. Every change in the simulator rewrites the address to the camera's own payload format.
English by default, with Simplified and Traditional Chinese. `simulator/` redirects here.

The simulator uses the SensorLab **0.0.6test** C calculation core and QR encoder compiled
to WebAssembly. Everything runs in the browser; no camera, local server, account or remote
calculation service is needed. Image quality, recording, playback and physical camera stability are
not simulated.

These static files are generated from the maintained workspace sources with
`python3 -B projects/sensorlab-imx410/site/build_site.py`. `wasm_info.json` records the version,
source fingerprints and binary checksum. The camera QR payload and its URL are unchanged.
