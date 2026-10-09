import ctypes
import unittest
from types import SimpleNamespace as S
from support import prop
from BL4ThirdPersonPOC.omni.native_air_input import LiveAirInputTrace


class SourceTests(unittest.TestCase):
    def make_trace(self):
        storage = (ctypes.c_ubyte * 256)()
        address = ctypes.addressof(storage)
        vector = S(_path_name=lambda: '/Script/CoreUObject.Vector',
                   _superfields=lambda: (), _properties=lambda: [
                       prop('X', 'DoubleProperty', 0), prop('Y', 'DoubleProperty', 8),
                       prop('Z', 'DoubleProperty', 16)])
        fields = [prop('ControlInputVector', 'StructProperty', 64, Struct=vector),
                  prop('LastControlInputVector', 'StructProperty', 128, Struct=vector)]
        movement = S()
        pawn = S(Class=S(_superfields=lambda: (), _properties=lambda: fields),
                 _get_address=lambda: address, OakCharacterMovement=movement,
                 GetPendingMovementInputVector=lambda: S(X=0., Y=0., Z=0.),
                 GetLastMovementInputVector=lambda: S(X=0., Y=0., Z=0.))
        mod = S(_native_query=lambda _: S(BaseAddress=address, RegionSize=256,
                                          State=0x1000, Protect=4),
                _native_read=lambda p, n: ctypes.string_at(p, n))
        capture = S(mod=mod, report={'native_reads': 0},
                    bound=lambda: (None, pawn, None, movement))
        trace = LiveAirInputTrace(capture, None)
        return trace, pawn, fields, storage

    def test_sources_use_reflected_offsets_and_sdk_readback(self):
        trace, pawn, fields, storage = self.make_trace()
        trace.bind_input_sources()
        self.assertEqual(trace.control[32], pawn._get_address() + 64)
        self.assertEqual(trace.control[33], pawn._get_address() + 128)
        ctypes.c_double.from_buffer(storage, 64).value = 1
        with self.assertRaisesRegex(RuntimeError, 'readback differs'):
            trace.validate_input_sources()

    def test_wrong_schema_has_no_offset_fallback(self):
        trace, pawn, fields, storage = self.make_trace()
        fields[0].Struct = S(_path_name=lambda: '/Script/Other.Unknown')
        with self.assertRaisesRegex(RuntimeError, 'schema differs'):
            trace.bind_input_sources()
        self.assertEqual(trace.control[32], 0)

    def test_expired_owner_disarms_native_sources(self):
        trace, pawn, fields, storage = self.make_trace()
        trace.bind_input_sources()
        trace.input_pawn_ref = lambda: None
        with self.assertRaisesRegex(RuntimeError, 'owner changed'):
            trace.validate_input_sources()
        self.assertEqual(trace.control[32], 0)
        self.assertEqual(trace.control[33], 0)
