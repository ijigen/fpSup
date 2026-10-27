"""GPU-assisted predictor search; entropy coding stays in native libjpeg.

Metal and CUDA execute the same integer predictor/category calculation. GPU
results select predictors only, so every output is still decoded and checked.
"""
import ctypes
import heapq
import os
from pathlib import Path
import sys
import threading

import numpy as np

NATIVE=Path(__file__).parent/'native'
_backends={}
_lock=threading.Lock()


def cpu_histogram(pixels,stride,bits,predictors):
    """Integer reference for kernel conformance; not used to fake GPU execution."""
    a=np.asarray(pixels,dtype=np.uint16).reshape(-1,stride//2,2).astype(np.int32)
    result=np.zeros((7,2,17),np.uint32)
    for p in predictors:
        pred=np.empty_like(a)
        pred[0,0]=1<<(bits-1);pred[0,1:]=a[0,:-1];pred[1:,0]=a[:-1,0]
        left=a[1:,:-1];up=a[:-1,1:];corner=a[:-1,:-1]
        pred[1:,1:]={1:left,2:up,3:corner,4:left+up-corner,
                     5:left+((up-corner)>>1),6:up+((left-corner)>>1),7:(left+up)>>1}[p]
        diff=(a-pred).astype(np.int16).astype(np.int32)
        magnitude=np.abs(diff)
        category=np.zeros_like(magnitude)
        nonzero=magnitude!=0
        category[nonzero]=np.floor(np.log2(magnitude[nonzero])).astype(np.int32)+1
        for c in range(2):result[p-1,c]=np.bincount(category[:,:,c].ravel(),minlength=17)
    return result


def estimated_bits(hist):
    # Huffman merge cost equals sum(frequency * code length); a dummy symbol
    # reserves the all-ones code. Category 16 has no appended magnitude bits.
    total=0
    for counts in (hist.sum(axis=0),):
        heap=[int(v) for v in counts if v];heap.append(1);heapq.heapify(heap)
        while len(heap)>1:
            n=heapq.heappop(heap)+heapq.heappop(heap);total+=n;heapq.heappush(heap,n)
        total+=sum(int(counts[c])*c for c in range(1,16))
    return total


class GPU:
    def __init__(self,backend):
        if backend not in ('metal','cuda'):raise ValueError('Unknown GPU backend')
        if backend=='metal' and sys.platform!='darwin':raise RuntimeError('Metal requires macOS')
        library=NATIVE/('libcdng_metal.dylib' if backend=='metal' else ('cdng_cuda.dll' if os.name=='nt' else 'libcdng_cuda.so'))
        if not library.exists():raise RuntimeError(f'{backend.upper()} backend has not been built: {library.name}')
        self.library=ctypes.CDLL(str(library));self.backend=backend
        self.library.cdng_gpu_hist.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,
                                           ctypes.c_uint32,ctypes.c_void_p,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_uint32]
        self.library.cdng_gpu_hist.restype=ctypes.c_int
        self.library.cdng_gpu_name.argtypes=[];self.library.cdng_gpu_name.restype=ctypes.c_char_p
        self.name=self.library.cdng_gpu_name().decode('utf-8',errors='replace')
        self._self_test()

    def histogram(self,pixels,stride,bits,predictors):
        pixels=np.ascontiguousarray(pixels,dtype=np.uint16)
        if pixels.size>=2**32:raise ValueError('GPU tile is too large')
        result=np.zeros((7,2,17),np.uint32);error=ctypes.create_string_buffer(2048)
        code=self.library.cdng_gpu_hist(pixels.ctypes.data,pixels.size,stride,bits,
            sum(1<<(p-1) for p in predictors),result.ctypes.data,
            os.fsencode(NATIVE/'predict.metal'),error,len(error))
        if code:raise RuntimeError(f'{self.backend.upper()}: {error.value.decode(errors="replace")}')
        return result

    def _self_test(self):
        for bits in (8,12,16):
            pixels=np.random.default_rng(bits).integers(0,2**bits,size=(8,64),dtype=np.uint16)
            actual=self.histogram(pixels,64,bits,range(1,8))
            if not np.array_equal(actual,cpu_histogram(pixels,64,bits,range(1,8))):
                raise RuntimeError(f'{self.backend.upper()} integer predictor self-test failed')

    def rank(self,pixels,stride,bits,predictors):
        hist=self.histogram(pixels,stride,bits,predictors)
        return sorted(predictors,key=lambda p:estimated_bits(hist[p-1]))


def get_gpu(backend):
    with _lock:
        if backend not in _backends:_backends[backend]=GPU(backend)
        return _backends[backend]
