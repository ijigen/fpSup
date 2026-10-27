#!/bin/sh
set -eu
cd "$(dirname "$0")"
clang++ -std=c++17 -O3 -fobjc-arc -dynamiclib -framework Foundation -framework Metal \
  cdng_image/native/metal_backend.mm -o cdng_image/native/libcdng_metal.dylib
echo 'Metal backend built.'
