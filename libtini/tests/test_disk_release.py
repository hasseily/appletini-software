"""Release-volume limits beyond the small foundation boot disk."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_disk',ROOT/'tools/disk.py')
disk=importlib.util.module_from_spec(spec);spec.loader.exec_module(disk)

class ReleaseDisk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.template=(ROOT/'build-inputs/prodos/ProDOS_2_4_3.po').read_bytes()
    def test_large_directory_empty_save_and_repeatability(self):
        files=[('FILE'+str(i),bytes([i])*((i%3)*512),6,0) for i in range(30)]
        a=disk.build_image(self.template,b'PROGRAM',files=files,total=1600)
        disk.validate_image(a)
        extracted=disk.read_root_files(a)
        self.assertEqual(len(extracted),32)
        for name,data,_,_ in files:self.assertEqual(extracted[name],data)
        self.assertEqual(a,disk.build_image(self.template,b'PROGRAM',files=files,total=1600))
    def test_multiple_bitmap_blocks_and_index_high_bytes(self):
        payload=bytes(range(256))*512
        files=[('LARGE'+str(i),payload,6,0) for i in range(18)]
        image=disk.build_image(self.template,b'PROGRAM',files=files,total=8192)
        disk.validate_image(image)
        self.assertEqual(len(image),8192*512)
        self.assertEqual(disk.read_root_files(image)['LARGE17'],payload)
        broken=bytearray(image);broken[(disk.BITMAP+1)*512]^=0x80
        with self.assertRaises(ValueError):disk.validate_image(broken)
    def test_root_directory_and_capacity_rejection(self):
        with self.assertRaises(ValueError):disk.build_image(self.template,b'P',files=[('F'+str(i),b'x',6,0) for i in range(50)])
        with self.assertRaises(ValueError):disk.build_image(self.template,b'P',files=[('BIG'+str(i),bytes(131072),6,0) for i in range(2)])
        with self.assertRaises(ValueError):disk.build_image(self.template,b'P',files=[('PRODOS',b'x',6,0)])
        with self.assertRaises(ValueError):disk.build_image(self.template,b'P',total=65536)

if __name__=='__main__':unittest.main()
