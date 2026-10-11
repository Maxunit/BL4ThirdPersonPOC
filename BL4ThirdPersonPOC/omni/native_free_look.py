"""QA extension of the reviewed Aim hook; original workers remain audited."""
import ctypes
import hashlib
import struct
from .native_rotation import NativeSlideCrouchAimYaw

# Assembled from docs/omni/native_validation/free_look_prefix.s, without
# relocations. Both copies retain the exact receiver/caller filters and the
# existing yaw-only mode. Only mode 2 changes the caller's yaw/pitch temporary.
FREE_LOOK_PREFIX = bytes.fromhex(
    '9c50415249ba1111111111111111493b4a080f8502010000488b442418493b42100f85f30000004885d20f84ea000000f049ff422049833a010f84cf00000049833a020f85d10000004883ec40f30f7f0424f30f7f4c2410f30f7f5424200fae5c24308b4424300d801f0000894424340fae542434498b4228660f6ec0f30f5ac048c1e820660f6ec8f30f5ac9660f2ec07a5f660f2e05850000007755660f2e0583000000724b660f2ec97a45660f2e0d7b000000773b660f2e0d790000007231f20f105208660f2ed27a26660f2e156c000000771c660f2e156a0000007212f20f59d1f20f1102f20f115208f049ff42180fae542430f30f6f0424f30f6f4c2410f30f6f5424204883c440eb0c48c70200000000f049ff4218415a589deb30000000000080414000000000008041c0000000000000f03f0000000000000000000000000080664000000000008066c0')
FREE_LOOK_HASH = '5b7ede243c2774c4fbe365bfbc231e72cc70bd3a02e1304decd7a151f6648163'


class NativeFreeLookAim(NativeSlideCrouchAimYaw):
    PREFIX = FREE_LOOK_PREFIX * 2
    PREFIX_SIZE = 672
    HASH = 'a91817d3c27fe26e589a954b067726d7bfaabc6dea12064876681bb097cdca55'

    def __init__(self, capture):
        super().__init__(capture)
        self.control = (ctypes.c_uint64 * 6)()
        self.crouch_control = (ctypes.c_uint64 * 6)()
        self.control._slide_crouch_control = self.crouch_control

    def prefix_code(self):
        if (len(FREE_LOOK_PREFIX) != 336
                or hashlib.sha256(FREE_LOOK_PREFIX).hexdigest() != FREE_LOOK_HASH
                or FREE_LOOK_PREFIX.count(b'\x11' * 8) != 1):
            raise RuntimeError('Free-look instruction template audit differs')
        return b''.join(FREE_LOOK_PREFIX.replace(
            b'\x11' * 8, struct.pack('<Q', ctypes.addressof(control)))
            for control in (self.control, self.crouch_control))

    def install(self):
        # Retain all existing Steam fingerprint, reflection, axes, exact caller,
        # vtable, code-page, installation readback and restoration checks.
        super().install()
        scope = ('Exact owned normal/crouch node and reviewed caller only. '
                 'Mode 1: zero yaw, preserve pitch (.32 special movement). '
                 'Mode 2: single packed yaw/alpha publication; replace temporary '
                 'yaw and multiply original pitch. Preserve roll, arguments, '
                 'GPRs, XMM0-2, MXCSR and flags. No Python on animation workers.')
        self.capture.report['aim_native_binding']['scope'] = scope
        self.capture.report['crouch_aim_native_binding']['scope'] = scope
        self.capture.report['free_look_settings'] = dict(
            yaw_input_limit_degrees=35, fade_start_degrees=60,
            neutral_from_degrees=90, additional_native_patches=0,
            source='current callback camera and post-follow actor sample',
            scope='free grounded Omni, standing/crouched; angular smoothstep')
