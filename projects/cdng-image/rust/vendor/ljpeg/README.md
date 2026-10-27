Fast, no dependency decoder and encoder of the original [lossless JPEG](https://en.wikipedia.org/wiki/Lossless_JPEG) format.
A lot of the code is used from [dnglab](https://github.com/dnglab/dnglab), with modifications
for use as a standalone library and some improvements.

Based on the limited testing on the author's machine, the decoder is about 2.5x faster
than [lj92.c](https://github.com/martinhering/liblj92), which is faster than
[Adobe DNG SDK](https://www.fastcinemadng.com/info/jpeg/lossless-jpeg-decoder.html).
This difference is not very important for decoding a single frame, but for real time
video playback, it is crucial. It's worth noting that no vectorization or multithreading
is used, since the decoding algorithm is very sequencial.

# `no_std` support
Everything in this crate is `no_std`. The `alloc` crate is required for the encoder
and for the decoder to store the Huffman table, but this could potentially be worked around.
