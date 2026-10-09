import struct
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch
import support
from BL4ThirdPersonPOC.omni import native_fire_activity as native


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x140000000
        self.wa, self.pa, self.data, self.fire, self.aux, self.entries = (
            0x200000000 + i * 0x10000 for i in range(6))
        self.memory = {}
        def read(a, n):
            return bytes(self.memory[a+i] for i in range(n))
        self.read = read
        for rva, b in native.GUARDS.items():
            self.put(self.base+rva, b)
        self.pack(self.wa+0xBE8, '<Qii', self.data, 1, 1)
        self.put(self.wa+0xBD8, b'\0')
        self.pack(self.data+8, '<Q', self.fire)
        ft, at = self.base+0xB9474F0, self.base+0xB946C90
        self.pack(self.fire, '<Q', ft)
        self.pack(ft+0x2B8, '<Q', self.base+0x6F35FA)
        self.pack(ft+0x398, '<Q', self.base+0xB81A94)
        self.pack(self.fire+0xB0, '<Q', self.aux)
        self.put(self.fire+0x2D0, b'\xd0')
        self.pack(self.aux, '<Q', at)
        self.pack(at+0x2B8, '<Q', self.base+0x107A06E)
        self.put(self.aux+0xC0, b'\0')
        self.pack(self.aux+0x100, '<Q', 0)
        user = self.pa+0x60E8
        self.pack(user+0x150, '<Q', self.pa)
        self.pack(user+0xA0, '<Qii', self.entries, 1, 1)
        self.pack(self.entries+0x20, '<Q', self.wa)
        self.pack(self.entries+0x58, '<Q', 0)
        self.put(self.entries+0x68, b'\x01')
        self.weapon = S(_get_address=lambda: self.wa)
        self.pawn = S(Class=S(Name='OakCharacter'), _get_address=lambda: self.pa)
        self.mod = S(_native_read=read, _kernel32=S(GetModuleHandleW=lambda _: self.base))
        image = S(in_image=lambda a: self.base <= a < self.base+0x31B8C000,
                  code_rva=lambda a: a-self.base if self.base <= a < self.base+0x31B8C000 else None)
        with patch.object(native, 'parse_pe_identity', return_value=native.REVIEWED_BUILD), \
                patch.object(native, 'Image', return_value=image):
            self.reader = native.NativeFireActivity(self.mod)

    def put(self, a, b):
        self.memory.update({a+i:v for i,v in enumerate(b)})

    def pack(self, a, fmt, *v):
        self.put(a, struct.pack(fmt, *v))

    def test_exact_primary_and_auxiliary_getter_truth_table(self):
        for flags in (0, 0xd0, 0xc0, 1, 2, 3):
            for state in (0, 1, 2, 3, 255):
                for handle in (0, 0x12345678):
                    self.put(self.fire+0x2D0, bytes([flags]))
                    self.put(self.aux+0xC0, bytes([state]))
                    self.pack(self.aux+0x100, '<Q', handle)
                    row = self.reader.sample(self.pawn, self.weapon)
                    self.assertEqual(row['active'], bool(flags & 3 or state > 1 or handle))

    def test_native_pending_both_sources_and_closure(self):
        for handle, flags in ((0,1), (0,3), (123,1), (123,3)):
            self.pack(self.entries+0x58, '<Q', handle)
            self.put(self.entries+0x68, bytes([flags]))
            self.assertEqual(self.reader.sample(self.pawn,self.weapon)['pending'], bool(handle or flags & 2))

    def test_unknown_auxiliary_does_not_guess_activity(self):
        self.pack(self.base+0xB946C90+0x2B8, '<Q', self.base+0x9999)
        self.assertFalse(self.reader.sample(self.pawn,self.weapon)['supported'])

    def test_no_auxiliary_is_supported(self):
        self.pack(self.fire+0xB0, '<Q', 0)
        self.assertTrue(self.reader.sample(self.pawn,self.weapon)['supported'])

    def test_binding_change_is_refused(self):
        original = self.reader.read
        reads = []
        def unstable(a,n):
            if a == self.fire+0xB0:
                reads.append(1)
                if len(reads)>1: return bytes(n)
            return original(a,n)
        self.reader.read = unstable
        with self.assertRaisesRegex(RuntimeError, 'binding changed'):
            self.reader.sample(self.pawn,self.weapon)

    def test_changed_native_code_refuses_before_sampling(self):
        self.put(self.base+0x107A06E,b'\0')
        with patch.object(native, 'parse_pe_identity', return_value=native.REVIEWED_BUILD):
            with self.assertRaisesRegex(RuntimeError, 'measured code differs'):
                native.NativeFireActivity(self.mod)
