#!/bin/sh
set -eu
cd "$(dirname "$0")/rust"
cargo build --release --locked
echo 'Built rust/target/release/cdng-image (Metal included).'
