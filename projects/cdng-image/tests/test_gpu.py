import concurrent.futures
import os
import unittest
import numpy as np
from cdng_image.gpu import GPU,cpu_histogram


class KernelTests(unittest.TestCase):
    def test_reference_boundaries(self):
        a=np.array([[0,0,65535,32768],[1,65534,32768,0]],np.uint16)
        h=cpu_histogram(a,4,16,range(1,8))
        self.assertTrue(np.all(h.sum(axis=2)==4))
        self.assertGreater(h[0,:,16].sum(),0)

    @unittest.skipUnless(os.environ.get('CDNG_TEST_GPU'),'Set CDNG_TEST_GPU=metal or cuda for hardware conformance')
    def test_hardware_matches_integer_reference(self):
        gpu=GPU(os.environ['CDNG_TEST_GPU'])
        cases=[]
        for bits in (8,10,12,14,16):
            for width in (8,32,512,1024):
                a=np.random.default_rng(bits+width).integers(0,2**bits,(10,width),dtype=np.uint16)
                cases.append((a,width,bits))
        cases.extend([(np.zeros((4,512),np.uint16),512,12),
                      (np.full((4,512),65535,np.uint16),512,16)])
        def check(case):
            a,stride,bits=case
            actual=gpu.histogram(a,stride,bits,range(1,8))
            self.assertTrue(np.array_equal(actual,cpu_histogram(a,stride,bits,range(1,8))))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(check,cases))

if __name__=='__main__':unittest.main()
