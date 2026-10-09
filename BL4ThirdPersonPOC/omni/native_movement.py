"""Audited native workers. Templates, fingerprints and owner/thread guards unchanged from V3."""
import ctypes
import struct
import hashlib
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, perf_counter_ns
import json
import sys
from unrealsdk import hooks, make_struct, find_enum, find_object
from .common import log as logging
from unrealsdk.unreal import WeakPointer
from .common import KEY, TAG, angle, parts, describe, quat

DASH_TRACE_TEMPLATE = bytes.fromhex('4881ec9800000048894c24204889542428ff157a01000048894424309c8f4424384c8b156101000049833a010f85440100004c8b5c24204d3b5a080f853501000065488b042548000000493b42100f8522010000488b842498000000488b15360100004885d274094839d00f8505010000498b4a184881f9000400000f83ec00000048c1e10749034a2048c7010000000048894108488b44243048894110488b44242848894118498b422848894120410fb6830011000048894128410fb6835844000048894130410fb6836846000048894138418b832c36000048894140418b833036000048894148410fb6833836000048894150410fb6836036000048894158410fb683b505000048894160410fb683a836000048894168498b83780100004889417048c741780000000048c7010100000049ff421849837a38017538807c24300175314180bb0011000001752741f683a836000001741d49817a4000020000731349ff4240c644243000eb0849c7423001000000488b442430ff7424389d488da42498000000c3111111111111111122222222222222223333333333333333')

DASH_TRACE_HASH = 'e35edb39e4f25fe677c4e54a5f78e7d2943900eefb8ab03a64b68049cb9f258f'

DASH_CAPACITY = 1024

DASH_RECORD_SIZE = 128

class DashReturnTrace:
    template = DASH_TRACE_TEMPLATE
    template_hash = DASH_TRACE_HASH

    def continuation(self, trampoline, target, prologue):
        return trampoline

    def build_original(self,prologue,target):
        return self.mod._native_build_trampoline(prologue,target+len(prologue))

    def __init__(self,capture,spec):
        self.capture=capture; self.mod=capture.mod; self.spec=spec
        self.control=(ctypes.c_uint64*9)()
        self.buffer=(ctypes.c_ubyte*(DASH_CAPACITY*DASH_RECORD_SIZE))()
        self.hook=None; self.consumed=0

    def read(self,address,size):
        if not 0x10000<=address<0x800000000000 or not 0<size<=4096 or address+size>=0x800000000000:
            raise RuntimeError('Native diagnostic read bounds')
        self.capture.report['native_reads']+=1
        data=self.mod._native_read(address,size)
        if len(data)!=size: raise RuntimeError('Short native read')
        return data

    def install(self):
        if not self.capture.updates.is_game_thread(): raise RuntimeError('Installation requires owned game thread')
        if hashlib.sha256(self.template).hexdigest()!=self.template_hash: raise RuntimeError('Trace template differs')
        for marker in (b'\x11'*8,b'\x22'*8,b'\x33'*8):
            if self.template.count(marker)!=1: raise RuntimeError('Trace marker count differs')
        self.movement=int(self.capture.bound()[3]._get_address())
        self.base=int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        dos=self.read(self.base,64)
        if dos[:2]!=b'MZ':raise RuntimeError('DOS header differs')
        off=struct.unpack_from('<I',dos,60)[0]
        if not 64<=off<=0x100000:raise RuntimeError('PE bounds')
        pe=self.read(self.base+off,0x108)
        build=(struct.unpack_from('<I',pe,8)[0],struct.unpack_from('<I',pe,80)[0],struct.unpack_from('<H',pe,4)[0])
        if pe[:4]!=b'PE\0\0' or struct.unpack_from('<H',pe,24)[0]!=0x20B or build!=(0x6AA81051,0x31B8C000,0x8664):
            raise RuntimeError('Unreviewed game build')
        self.capture.report['build']=[hex(v) for v in build]
        if struct.unpack('<Q',self.read(self.movement,8))[0]!=self.base+0xB709670:
            raise RuntimeError('Local movement vtable differs')
        rva,hexprologue,length,digest,caller,label=self.spec
        prologue=bytes.fromhex(hexprologue); target=self.base+rva
        if hashlib.sha256(self.read(target,length)).hexdigest()!=digest:
            raise RuntimeError('Reviewed full function differs: '+label)
        info=self.mod._native_query(target); region=int(info.BaseAddress or 0)
        if (int(info.State)!=0x1000 or int(info.Type)!=0x1000000 or int(info.Protect)&0x100
                or int(info.Protect)&0xff not in (0x20,0x40,0x80)
                or not region<=target<target+len(prologue)<=region+int(info.RegionSize)):
            raise RuntimeError('Native image page protection differs')
        self.control[1]=self.movement;self.control[2]=threading.get_native_id()
        self.control[4]=ctypes.addressof(self.buffer)
        stub=int(self.mod._kernel32.VirtualAlloc(None,0x2000,0x3000,0x40) or 0)
        if not stub:raise RuntimeError('Trace allocation failed')
        trampoline=stub+0x1800
        self.hook={'target':target,'original':prologue,
            'patch':self.mod._native_absolute_jump(stub)+b'\x90'*(len(prologue)-14),
            'stub':stub,'trampoline':trampoline,'buffer':self.buffer,'control':self.control,
            'restored':False,'patch_attempted':False,'label':'Dash gate trace '+label}
        code=self.template.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(self.control)))
        code=code.replace(b'\x22'*8,struct.pack('<Q',self.continuation(trampoline,target,prologue))).replace(b'\x33'*8,struct.pack('<Q',self.base+caller))
        # Reviewed copied entry window contains whole instructions, no RIP operands or relative branches.
        original=self.build_original(prologue,target)
        ctypes.memmove(stub,code,len(code));ctypes.memmove(trampoline,original,len(original))
        process=self.mod._kernel32.GetCurrentProcess()
        for address,data in ((stub,code),(trampoline,original)):
            if not self.mod._kernel32.FlushInstructionCache(process,ctypes.c_void_p(address),len(data)):
                raise RuntimeError('Instruction cache flush failed')
        self.capture.bound()
        if self.read(target,len(prologue))!=prologue:raise RuntimeError('Entry changed before publication')
        self.hook['patch_attempted']=True
        self.mod._native_write_code(target,self.hook['patch'])
        if self.read(target,len(prologue))!=self.hook['patch']:raise RuntimeError('Patch readback differs')
        self.control[0]=1
        self.capture.report['native_patches']+=1
        self.capture.report['native_patches_peak']=max(self.capture.report.get('native_patches_peak',0),self.capture.report['native_patches'])

    def validate(self):
        if int(self.capture.bound()[3]._get_address())!=self.movement:raise RuntimeError('Movement identity changed')
        if self.hook is not None and self.read(self.hook['target'],len(self.hook['patch']))!=self.hook['patch']:
            raise RuntimeError('Owned trace bytes changed')

    def consume(self):
        count=int(self.control[3])
        if not self.consumed<=count<=DASH_CAPACITY:raise RuntimeError('Record count outside bounds')
        for index in range(self.consumed,count):
            values=struct.unpack('<16Q',bytes(self.buffer[index*128:(index+1)*128]))
            committed,caller,result,arg,update,mode,wish,unknown,g1,g2,b3638,b3660,b5b5,flags,interface,reserved=values
            if committed!=1:raise RuntimeError('Uncommitted trace record')
            self.capture.report['dash_native_records'].append({'gate':self.spec[5],'index':index,
                'caller_return_rva':hex(caller-self.base),'return_rax_hex':hex(result),'original_return_al_raw':result&255,
                'argument_rdx_hex':hex(arg),'last_widget_update_index':update,
                'native_mode_1100_raw':mode,'dash_wish_byte_raw':wish,'unknown_4668_raw':unknown,
                'grant_362c_raw':g1,'grant_3630_raw':g2,'combined_grant_bit2':bool((g1|g2)&2),
                'gate_3638_raw':b3638,'gate_3660_raw':b3660,'flags_5b5_raw':b5b5,
                'flags_5b5_bit20':bool(b5b5&0x20),'sprint_flags_36a8_raw':flags,
                'movement_interface_178_hex':hex(interface)})
        self.consumed=count

    def stop(self):
        self.control[0]=0
        if self.hook is not None:
            if not self.capture.updates.is_game_thread():raise RuntimeError('Cleanup requires owned game thread; rerun')
            if self.hook['patch_attempted']:self.mod._native_restore_hook(self.hook)
            self.mod._native_release_hook(self.hook)
            self.hook=None
        self.consume()

SPRINT_DIRECTION_SPEC = (5194783, '0f57c0f30f5ac6660f2ec20f96c0', 14, '6ff9532a4ea1b2a5322078d7a906bad2f034466c3f221b5a5875d394f9b01649', 5194393, 'sprint_direction_comparison')

class DirectionCompareTrace(DashReturnTrace):
    # Interior instruction window: execute its exact original comparison once,
    # preserve all registers/flags except scoped B result AL, then resume after the 14 copied bytes.
    template=bytes.fromhex('0f57c0f30f5ac6660f2ec20f96c09c50515241504151415241534c8b158101000049833a010f8565010000493b72080f855b01000065488b042548000000493b42100f8548010000488b842418010000483b055b0100000f8533010000498b4a184881f9000400000f831a01000048c1e10749034a2048c7010000000048894108488b44243048894110498b42284889411848897120660fd64128660fd65130488b868803000048894138488b869003000048894140488b869803000048894148488b0748894150488b470848894158488b4710488941608b86300400008941680fb686a836000089416c488b96f01c00008b82440200008941708b82480200008941740fb6442430894178c7417c000000003c00756449837a3801755d83be00110000017554f686a836000001744b49817a4000020000734166480f7ed048c1e83425ff0700003dff070000742c66480f7ec048c1e83425ff0700003dff0700007417c644243001c7417801000000c7417c0100000049ff424048c7010100000049ff4218eb0849c7423001000000415b415a415941585a59589dff2508000000111111111111111122222222222222223333333333333333')
    template_hash='464b16c65902a76dab211986cc05f9e736555cf16c98fe18c66588577e9ed52f'

    def continuation(self,trampoline,target,prologue):
        return target+len(prologue)

    def install(self):
        base=int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        if hashlib.sha256(self.read(base+0x4F4310,385)).hexdigest()!='3c310c22ac5544b8bff9be5cfd7f9ca7aeced71bffb5253330d1c5437fff0128':
            raise RuntimeError('Reviewed full movement predicate differs')
        super().install()
        self.capture.report['direction_native_binding']={'predicate_rva':'0x4f4310',
            'comparison_rva':'0x4f441f','exact_caller_return_rva':'0x4f4299',
            'comparison_result_modified_in_scoped_B':True,'earlier_checks_preserved':True}

    def consume(self):
        count=int(self.control[3])
        if not self.consumed<=count<=DASH_CAPACITY:raise RuntimeError('Direction record count outside bounds')
        for index in range(self.consumed,count):
            data=bytes(self.buffer[index*128:(index+1)*128])
            committed,caller,result,update,movement=struct.unpack_from('<5Q',data)
            if committed!=1:raise RuntimeError('Uncommitted direction record')
            threshold,dot,*vectors=struct.unpack_from('<8d',data,40)
            analog,flags,configured_angle,minimum_analog=struct.unpack_from('<fIff',data,104)
            self.capture.report['direction_native_records'].append({'index':index,
                'caller_return_rva':hex(caller-self.base),'last_widget_update_index':update,
                'comparison_al_raw':result&255,'threshold':threshold,'dot_product':dot,
                'acceleration':vectors[:3],'reference_vector':vectors[3:],
                'analog_input_modifier':analog,'sprint_flags_36a8_raw':flags,
                'configuration_244_raw':configured_angle,'minimum_analog_248':minimum_analog,
                'effective_comparison_al':struct.unpack_from('<I',data,120)[0],
                'direction_override_applied':bool(struct.unpack_from('<I',data,124)[0])})
        self.consumed=count

class SprintIndexTrace(DashReturnTrace):
    template=bytes.fromhex('9c50515241504151415241534c8b152f01000049833a010f8513010000488b4c2428493b4a080f8504010000488b442440483b051a0100000f85f2000000837928020f85e80000008b44242083f8010f87db0000004d8b4a484183b900110000010f85c900000041f681a8360000040f84bb00000049817a18000400000f83a500000048c7c001000000f0490fc14218483d000400000f838c00000048c1e0074903422048c700000000004c8b5c24404c8958084c8b5c24204c8958104c895818488948204d8b5a284c895828450fb699a83600004c8958304d8b5a384c89583848c740400000000049837a3801752f837c242001752849817a4000020000731e48c74424200000000048c740180000000048c7404001000000f049ff424048c70001000000eb0849c7423001000000415b415a415941585a59589dff2508000000111111111111111122222222222222223333333333333333')
    template_hash='01cbb072c8e8f79d97f19adb7276d753b910fce2f98dfd59be0fa1fcc9444d3e'
    def __init__(self,capture):
        super().__init__(capture,(3281836, '415741565657534883ec2085d2780a', 218, '7bb3cfdb9abcf15562104f70bacfc2640cf18a310706570c941cf6230f607f29', 25601371, 'sprint_locomotion_selected_index'))
        self.control=(ctypes.c_uint64*10)()

    def build_original(self,prologue,target):
        # First 13 bytes contain whole pushes/sub/test. Relocate the following
        # short JS explicitly: nonnegative falls through at +15, negative +25.
        if prologue.hex()!='415741565657534883ec2085d2780a':
            raise RuntimeError('Reviewed index-selector entry window differs')
        return (prologue[:13]+bytes.fromhex('0f890e000000')
            +self.mod._native_absolute_jump(target+25)
            +self.mod._native_absolute_jump(target+15))

    def install(self):
        c=self.capture
        anim=c.anim_ref()
        if anim is None:raise RuntimeError('Index-selector animation owner expired')
        self.node=c.selection_addresses['GbxAnimGraphNode_Locomotion_2']
        self.control[9]=int(c.bound()[3]._get_address())
        super().install()
        self.control[1]=self.node
        c.report['sprint_index_binding']={'node':'GbxAnimGraphNode_Locomotion_2',
            'offset':38928,'selector_rva':'0x3213ac','caller_return_rva':'0x186a55b',
            'scope':'Only native grounded sprint, exact live node and exact caller; index 1 to 0 in animation B. Native animation update threads allowed; no Python callback on them.'}

    def validate(self):
        super().validate()
        c=self.capture
        anim=c.anim_ref()
        if anim is None or int(anim._get_address())+38928!=self.node:
            raise RuntimeError('Index-selector animation identity changed')
        if self.read(self.node,8)!=struct.pack('<Q',self.base+0xB09B440):
            raise RuntimeError('Index-selector node vtable changed')

    def consume(self):
        count=int(self.control[3])
        if not self.consumed<=count<=DASH_CAPACITY:raise RuntimeError('Index trace record bound exceeded')
        for index in range(self.consumed,count):
            values=struct.unpack('<16Q',bytes(self.buffer[index*128:(index+1)*128]))
            if values[0]!=1:break  # Worker reservation may still be in flight.
            _,caller,original,effective,node,update,flags,enabled,applied,*_=values
            self.capture.report['sprint_index_native_records'].append({'index':index,
                'caller_return_rva':hex(caller-self.base),'original_index':original&0xffffffff,
                'effective_index':effective&0xffffffff,'node_address':hex(node),
                'last_widget_update_index':update,'native_sprint_flags':flags,
                'animation_B_enabled':bool(enabled),'override_applied':bool(applied)})
            self.consumed=index+1

class LiveDirectionTrace(DirectionCompareTrace):
    template=bytes.fromhex('0f57c0f30f5ac6660f2ec20f96c09c50515241504151415241534c8b159200000049833a01757a493b7208757465488b042548000000493b42107565488b842418010000483b05780000007554f049ff421849837a38017548807c243000754183be00110000017538f686a836000001742f66480f7ed048c1e83425ff0700003dff070000741a660f7ef0250000807f3d0000807f740ac644243001f049ff4240415b415a415941585a59589dff2508000000111111111111111122222222222222223333333333333333')
    template_hash='a57af2e7afee94fa78158efae04faa608e8cf146ab96d150f50badeb59b20c45'
    def consume(self):
        self.capture.report['live_direction_calls']=int(self.control[3])
        self.capture.report['live_direction_overrides']=int(self.control[8])

class LiveIndexTrace(SprintIndexTrace):
    template=bytes.fromhex('9c50515241504151415241534c8b157000000049833a017558488b4c2428493b4a08754d488b442440483b0563000000753f837928027539f049ff421849837a3801752d837c24200175264d8b4a484183b90011000001751841f681a836000004740e48c744242000000000f049ff4240415b415a415941585a59589dff2508000000111111111111111122222222222222223333333333333333')
    template_hash='c164eb5be66273865374604f48029c710346cf46c6702d3166e03d4e7ac2bbac'
    def consume(self):
        self.capture.report['live_index_calls']=int(self.control[3])
        self.capture.report['live_index_overrides']=int(self.control[8])

DASH_INLINE_TEMPLATE = bytes.fromhex('89c3488b064889f1ff90880e00009c50515241504151415241534c8b150301000049833a010f85e7000000493b72080f85dd00000065488b042548000000493b42100f85ca000000498b4a184881f9000400000f83b100000048c1e10649034a2048c70100000000488b8424e800000048894108488b442430488941100fb6c348894118498b4228488941200fb68600110000488941280fb68658440000488941300fb686684600004889413848c7010100000049ff421849837a3801755380fb01754e807c243000754780be0011000001753e498b42484883f8037734388648440000752cf686a8360000047423f6865844000001741a49817a4000010000731049ff424031dbeb0849c7423001000000415b415a415941585a59589dff2508000000111111111111111122222222222222223333333333333333')

DASH_INLINE_HASH = 'fe0fd4d4264fdf3584c04e5e1eef6d1fb00a42113443db90e53cbd84b40756e0'

DASH_INLINE_SPEC = (0x153950, '89c3488b064889f1ff90880e0000', 14, 'cca20cc4f2658557c38e94598b3f49b9babd90c3529846d37e5b2ef7c14d91eb', 0, 'paired_branch_inputs')

class DashBranchTrace(DashReturnTrace):
    template = DASH_INLINE_TEMPLATE
    template_hash = DASH_INLINE_HASH

    def __init__(self,capture,spec):
        super().__init__(capture,spec)
        self.control=(ctypes.c_uint64*10)()

    def continuation(self, trampoline, target, prologue):
        return target + len(prologue)

    def install(self):
        base=int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        # No RIP-relative operands or direct relative calls/branches in the copied 14 bytes.
        # Keep the original indirect call. Only explicit B may neutralize the proven BL=1/AL=0 reject.
        if self.read(base+0x15395e, 35) != bytes.fromhex('84db743b3c010f859f000000488dbe78010000488b86780100004889f9ff90d0000000'):
            raise RuntimeError('Reviewed branch context differs')
        super().install()

    def consume(self):
        count=int(self.control[3])
        if not self.consumed<=count<=DASH_CAPACITY:raise RuntimeError('Branch count outside bounds')
        for index in range(self.consumed,count):
            committed,caller,result,first,update,mode,wish,unknown=struct.unpack('<8Q',bytes(self.buffer[index*64:(index+1)*64]))
            if committed!=1:raise RuntimeError('Uncommitted branch record')
            phase='MOVEMENT_DIRECTION'
            if phase=='MOVEMENT_DIRECTION' and wish&1 and mode==1:
                pair=str(first)+'/'+str(result&255)
                counts=self.capture.report['gate_pair_counts'][phase]
                counts[pair]=counts.get(pair,0)+1
            self.capture.report['dash_native_records'].append({
                'ab_gate_phase':phase,
                'gate':self.spec[5], 'index':index,
                'helper_4f4310_bl_raw':first, 'virtual_e88_al_raw':result&255,
                'virtual_e88_full_rax_hex':hex(result),
                'containing_function_return_address_hex':hex(caller),
                'last_widget_update_index':update, 'native_mode_1100_raw':mode,
                'dash_wish_byte_raw':wish,'unknown_4668_raw':unknown,
                'original_inputs_would_reject_at_153a10':bool(first and (result&255)==0)})
        self.consumed=count

DASH_TEMPLATE = bytes.fromhex('9c50515241504151415241534c8b154101000049833a010f85180100004c8b5c24284d3b5a080f850901000065488b042548000000493b42100f85f60000004d8b4a184981f9000200000f83dd0000004d89c849c1e0074d03422049c700000000004d89480849c7401000000000488b44244049894018498b4228498940204d8b5a38418b83a836000049894028410fb6835844000049894030410fb6834844000049894038410fb68300110000498940684d8b5a084d895870410fb6434849894040410fb6434949894048488b5424204989507849c740500000000049c740580000000049c740600000000049837a400175254983784801751e4983786801751749c740100100000041f6402804740849c740100200000049c7000100000049ff42184983781000751ceb0849c7423001000000415b415a415941585a59589dff2515000000415b415a415941585a59589dc311111111111111112222222222222222')

DASH_TEMPLATE_HASH = '9618e4af09099c36eb1b231d3a24a31a17aab24901de298889d7c568bfe75561'

ROUTE_CAPACITY = 512

ROUTE_RECORD_SIZE = 128

SPRINT_TEMPLATE = bytes.fromhex('9c50515241504151415241534c8b153001000049833a010f85140100004c8b5c24284d3b5a080f850501000065488b042548000000493b42100f85f20000004d8b4a184981f9000200000f83d90000004d89c849c1e0074d03422049c700000000004d89480849c7401001000000488b44244049894018498b4228498940204d8b5a38418b83a836000049894028410fb6835844000049894030410fb6834844000049894038410fb68300110000498940684d8b5a084d895870410fb6434849894040410fb6434949894048488b5424204989507849c740500000000049c740580000000049c74060000000004881fa00000100722648b8e8ffffffff7f00004839c27317488b0249894050488b420849894058488b42104989406049c7000100000049ff4218eb0849c7423001000000415b415a415941585a59589dff250800000011111111111111112222222222222222')

SPRINT_TEMPLATE_HASH = '3f8a75462dc335efccbf96d019e8575895af57cc282aff9dcdbaa5244c4aa6b8'

class EntryTrace:
    def __init__(self, capture, spec):
        self.capture, self.mod, self.spec = capture, capture.mod, spec
        self.hook = None

    def read(self, address, size):
        if not 0x10000 <= address < 0x800000000000 or not 0 < size <= 4096 or address+size >= 0x800000000000:
            raise RuntimeError('Native read outside diagnostic bounds')
        self.capture.report['native_reads'] += 1
        data = self.mod._native_read(address, size)
        if len(data) != size: raise RuntimeError('Short diagnostic read')
        return data

    def install(self):
        if not self.capture.updates.is_game_thread(): raise RuntimeError('Install outside owned game thread')
        rva, prefix, length, digest, kind, label = self.spec
        original = bytes.fromhex(prefix)
        if len(original) != 15: raise RuntimeError('Unexpected audited instruction window')
        template = SPRINT_TEMPLATE if kind == 1 else DASH_TEMPLATE
        expected_hash = SPRINT_TEMPLATE_HASH if kind == 1 else DASH_TEMPLATE_HASH
        if hashlib.sha256(template).hexdigest() != expected_hash: raise RuntimeError('Trace template mismatch')
        for marker in (b'\x11'*8, b'\x22'*8):
            if template.count(marker) != 1: raise RuntimeError('Trace marker mismatch')
        base = self.capture.base
        target = base+rva
        if hashlib.sha256(self.read(target, length)).hexdigest() != digest:
            raise RuntimeError('Reviewed callback differs: '+label)
        if self.read(target, len(original)) != original: raise RuntimeError('Callback prologue mismatch')
        info = self.mod._native_query(target)
        region = int(info.BaseAddress or 0)
        if (int(info.State) != 0x1000 or int(info.Type) != 0x1000000 or int(info.Protect)&0x100
                or int(info.Protect)&255 not in (0x20, 0x40, 0x80)
                or not region <= target < target+len(original) <= region+int(info.RegionSize)):
            raise RuntimeError('Callback image page protection differs')
        stub = int(self.mod._kernel32.VirtualAlloc(None, 0x2000, 0x3000, 0x40) or 0)
        if not stub: raise RuntimeError('Trace allocation failed')
        trampoline = stub+0x1800
        self.hook = {'target': target, 'original': original,
            'patch': self.mod._native_absolute_jump(stub)+b'\x90',
            'stub': stub, 'trampoline': trampoline, 'buffer': self.capture.buffer,
            'control': self.capture.control, 'restored': False, 'patch_attempted': False,
            'label': 'Sprint/Dash entry order '+label}
        code = template.replace(b'\x11'*8, struct.pack('<Q', ctypes.addressof(self.capture.control)))
        code = code.replace(b'\x22'*8, struct.pack('<Q', trampoline))
        if kind == 1:
            # Whole pushes/sub/movapd window, no relative operand.
            replay = self.mod._native_build_trampoline(original, target+15)
        else:
            # Original cmp + JNE must reach its original reject destination.
            displacement = struct.unpack_from('<i', original, 11)[0]
            reject = target+15+displacement
            if reject != base+0xFB7598: raise RuntimeError('Audited Dash branch differs')
            replay = (original[:9]+b'\x74\x0e'+self.mod._native_absolute_jump(reject)
                      +self.mod._native_absolute_jump(target+15))
        ctypes.memmove(stub, code, len(code))
        ctypes.memmove(trampoline, replay, len(replay))
        process = self.mod._kernel32.GetCurrentProcess()
        for address, data in ((stub, code), (trampoline, replay)):
            if not self.mod._kernel32.FlushInstructionCache(process, ctypes.c_void_p(address), len(data)):
                raise RuntimeError('Trace instruction cache flush failed')
        self.capture.bound(); self.capture.validate_handler()
        if self.read(target, len(original)) != original: raise RuntimeError('Entry changed before publication')
        self.hook['patch_attempted'] = True
        self.mod._native_write_code(target, self.hook['patch'])
        if self.read(target, len(original)) != self.hook['patch']: raise RuntimeError('Trace publication readback differs')
        self.capture.report['native_patches'] += 1
        self.capture.report['native_patches_peak'] = max(self.capture.report.get('native_patches_peak', 0), self.capture.report['native_patches'])

    def validate(self):
        if self.hook is not None and self.read(self.hook['target'], len(self.hook['patch'])) != self.hook['patch']:
            raise RuntimeError('Owned entry trace bytes changed')

    def stop(self):
        if self.hook is None: return
        if not self.capture.updates.is_game_thread(): raise RuntimeError('Cleanup requires owned game thread; rerun')
        if self.hook['patch_attempted']: self.mod._native_restore_hook(self.hook)
        self.mod._native_release_hook(self.hook)
        self.hook = None

TRACE_SPECS = (
    (0x115182C, '41565657534883ec38660f29742420', 622,
     '1238223716544ec7ddbff3756171cacdd9e10c3c76c0b5f4df04496a779c316f', 1, 'sprint_entry'),
    (0xFB7448, '564883ec20807949010f8541010000', 360,
     'c10e0a7258861bdd0daa7b078145683d202550c21c2ff738fa21024d444ea326', 2, 'dash_entry'))

class VectorEntryTrace(DashReturnTrace):
    template = bytes.fromhex('9c50515241504151415241534c8b15d401000049833a010f85b8010000493b4a080f85ae01000065488b042548000000493b42100f859b01000049837a38010f8590010000488b442440483b05a60100000f857e0100004d8b4a184981f9000400000f83650100004d89c849c1e0074d03422049c700000000004d894808498b422849894010488b4424404989401849895020488b0249894028488b420849894030488b42104989403849c740580000000049837a40000f85c300000049837a6001742149837a6003741a49837a60020f85aa00000080b900110000030f859d000000eb0d80b900110000010f858e000000f68158440000010f84810000000fb6814844000083f80377754c8b99304400004d3b5a7075684d85db746349837a6001751a493b42687556418b848390000000413b427875484d8d5a48eb204989c149c1e1054f8d8c0a80000000418b848390000000413b0175264d8d5908498b03488902498b430848894208498b43104889421049ff424049c74058010000000fb68148440000498940680fb6810011000049894070488b813044000049894078488b0249894040488b420849894048488b421049894050498b42604989406049c7000100000049ff4218eb0849c7423001000000415b415a415941585a59589dff2508000000111111111111111122222222222222223333333333333333')
    template_hash = '3b073d83c57de38d336ba327f127f8ce112f085c3d867ee5a96f976088a814ae'

    def __init__(self, capture, spec):
        super().__init__(capture,spec)
        self.control = (ctypes.c_uint64*32)()

    def consume(self):
        count = int(self.control[3])
        if not self.consumed <= count <= DASH_CAPACITY: raise RuntimeError('Vector entry count outside bounds')
        for i in range(self.consumed,count):
            data = bytes(self.buffer[i*128:(i+1)*128])
            commit,seq,update,caller,pointer = struct.unpack_from('<5Q',data)
            if commit != 1 or seq != i: raise RuntimeError('Vector entry record invalid')
            original = struct.unpack_from('<3d',data,40)
            supplied = struct.unpack_from('<3d',data,64)
            changed,phase = struct.unpack_from('<2Q',data,88)
            if not all(math.isfinite(v) for v in (*original,*supplied)):
                raise RuntimeError('Nonfinite vector record')
            self.capture.report['vector_entry_records'].append({'update_index':update,
                'phase':('AIR_MOVEMENT_VECTOR' if phase==2 else 'GROUND_CIRCLE_ACTUAL_ENUM' if phase==3 else 'MOVEMENT_VECTOR') if phase else 'ORIGINAL_VECTOR',
                'caller_return_rva':hex(caller-self.base),'original_vector':list(original),
                'supplied_vector':list(supplied),'overridden':bool(changed),
                'native_direction_at_entry':struct.unpack_from('<Q',data,104)[0],
                'native_mode_at_entry':struct.unpack_from('<Q',data,112)[0],
                'native_config_at_entry':hex(struct.unpack_from('<Q',data,120)[0])})
            self.capture.report['native_input_vector_overrides_total'] += int(bool(changed))
            self.consumed = i+1
        self.consumed = count

    def stop(self):
        self.control[0] = 0
        if self.hook is not None:
            if not self.capture.updates.is_game_thread():
                raise RuntimeError('Cleanup requires owned game thread; rerun')
            if self.hook['patch_attempted']:
                self.mod._native_restore_hook(self.hook)
            self.mod._native_release_hook(self.hook)
            self.hook = None
        # Native restoration is mandatory; final diagnostic decoding is best effort.
        try:
            self.consume()
        except Exception as exc:
            detail = 'Vector final diagnostic decode failed: '+repr(exc)
            errors = self.capture.report['errors']
            if detail not in errors:
                errors.append(detail)
            self.capture.report['vector_final_decode_error'] = repr(exc)

CircleEntry_SPRINT_TEMPLATE = bytes.fromhex('9c50515241504151415241534c8b153001000049833a010f85140100004c8b5c24284d3b5a080f850501000065488b042548000000493b42100f85f20000004d8b4a184981f9000200000f83d90000004d89c849c1e0074d03422049c700000000004d89480849c7401001000000488b44244049894018498b4228498940204d8b5a38418b83a836000049894028410fb6835844000049894030410fb6834844000049894038410fb68300110000498940684d8b5a084d895870410fb6434849894040410fb6434949894048488b5424204989507849c740500000000049c740580000000049c74060000000004881fa00000100722648b8e8ffffffff7f00004839c27317488b0249894050488b420849894058488b42104989406049c7000100000049ff4218eb0849c7423001000000415b415a415941585a59589dff250800000011111111111111112222222222222222')

CircleEntry_SPRINT_TEMPLATE_HASH = '3f8a75462dc335efccbf96d019e8575895af57cc282aff9dcdbaa5244c4aa6b8'

CircleEntry_DASH_TEMPLATE = bytes.fromhex('9c50515241504151415241534c8b151201000049833a010f85fa000000493b4a080f85f000000065488b042548000000493b42100f85dd0000004d8b82800000004983f8010f82cc0000004983f8020f87c20000004d8b5a384180bb00110000010f85b000000041f68358440000010f85a2000000807949010f85980000000fb6414883f8030f878b0000004d8b8a88000000493b4168757e498b8330440000493b41707571488b0248d1e04c8b5a0849d1e34c09d84c8b5a1049d1e34c09d8745549c78280000000000000004d8982a8000000498b4228498982a00000000fb64148498982b0000000f049ff82900000004983f802751f49c7010100000049c741380100000049c7416003000000f049ff8298000000415b415a415941585a59589deb0844444444444444449c50515241504151415241534c8b1553000000f049ff42404c8b5c24284d895a6065488b04254800000049894268488b5424404989527049833a01751bf049ff42484d3b5a087510f049ff4250493b42107505f049ff4258415b415a415941585a59589deb0833333333333333339c50515241504151415241534c8b150101000049833a010f85e50000004c8b5c24284d3b5a080f85d600000065488b042548000000493b42100f85c30000004d8b4a184981f9000200000f83aa0000004d89c849c1e0074d03422049c700000000004d89480849c7401002000000488b44244049894018498b4228498940204d8b5a38418b83a836000049894028410fb6835844000049894030410fb6834844000049894038410fb68300110000498940684d8b5a084d895870410fb6434849894040410fb6434949894048488b5424204989507849c740500000000049c740580000000049c740600000000049c7000100000049ff4218eb0849c7423001000000415b415a415941585a59589dff250800000011111111111111112222222222222222')

CircleEntry_DASH_TEMPLATE_HASH = 'bb334fb717b43859dd7adda4f1870a8c06cdc5f6955846e04cabf15e762df0e3'

CircleEntry_CAPACITY = 512

CircleEntry_RECORD_SIZE = 128

class CircleEntry_EntryTrace:
    def __init__(self, capture, spec):
        self.capture, self.mod, self.spec = capture, capture.mod, spec
        self.hook = None

    def read(self, address, size):
        if not 0x10000 <= address < 0x800000000000 or not 0 < size <= 4096 or address+size >= 0x800000000000:
            raise RuntimeError('Native read outside diagnostic bounds')
        self.capture.report['native_reads'] += 1
        data = self.mod._native_read(address, size)
        if len(data) != size: raise RuntimeError('Short diagnostic read')
        return data

    def install(self):
        if not self.capture.updates.is_game_thread(): raise RuntimeError('Install outside owned game thread')
        rva, prefix, length, digest, kind, label = self.spec
        original = bytes.fromhex(prefix)
        if (label, len(original)) not in (('circle_hold_entry',16),('circle_crouch_entry',19)): raise RuntimeError('Unexpected audited Circle Hold instruction window')
        template = CircleEntry_SPRINT_TEMPLATE if kind == 1 else CircleEntry_DASH_TEMPLATE
        expected_hash = CircleEntry_SPRINT_TEMPLATE_HASH if kind == 1 else CircleEntry_DASH_TEMPLATE_HASH
        if hashlib.sha256(template).hexdigest() != expected_hash: raise RuntimeError('Trace template mismatch')
        for marker in (b'\x11'*8, b'\x22'*8, b'\x33'*8, b'\x44'*8):
            if template.count(marker) != 1: raise RuntimeError('Trace marker mismatch')
        base = self.capture.base
        target = base+rva
        if hashlib.sha256(self.read(target, length)).hexdigest() != digest:
            raise RuntimeError('Reviewed callback differs: '+label)
        if self.read(target, len(original)) != original: raise RuntimeError('Callback prologue mismatch')
        info = self.mod._native_query(target)
        region = int(info.BaseAddress or 0)
        if (int(info.State) != 0x1000 or int(info.Type) != 0x1000000 or int(info.Protect)&0x100
                or int(info.Protect)&255 not in (0x20, 0x40, 0x80)
                or not region <= target < target+len(original) <= region+int(info.RegionSize)):
            raise RuntimeError('Callback image page protection differs')
        stub = int(self.mod._kernel32.VirtualAlloc(None, 0x2000, 0x3000, 0x40) or 0)
        if not stub: raise RuntimeError('Trace allocation failed')
        trampoline = stub+0x1800
        self.hook = {'target': target, 'original': original,
            'patch': self.mod._native_absolute_jump(stub)+b'\x90'*(len(original)-14),
            'stub': stub, 'trampoline': trampoline, 'buffer': self.capture.buffer,
            'control': self.capture.control, 'restored': False, 'patch_attempted': False,
            'label': 'Sprint/Dash entry order '+label}
        code = template.replace(b'\x11'*8, struct.pack('<Q', ctypes.addressof(self.capture.control)))
        code = code.replace(b'\x22'*8, struct.pack('<Q', trampoline))
        code = code.replace(b'\x33'*8, struct.pack('<Q', ctypes.addressof(self.capture.control)))
        code = code.replace(b'\x44'*8, struct.pack('<Q', ctypes.addressof(self.capture.control)))
        # Complete instructions; no relative operand in either reviewed entry prologue.
        replay = self.mod._native_build_trampoline(original, target+len(original))
        ctypes.memmove(stub, code, len(code))
        ctypes.memmove(trampoline, replay, len(replay))
        process = self.mod._kernel32.GetCurrentProcess()
        for address, data in ((stub, code), (trampoline, replay)):
            if not self.mod._kernel32.FlushInstructionCache(process, ctypes.c_void_p(address), len(data)):
                raise RuntimeError('Trace instruction cache flush failed')
        self.capture.bound(); self.capture.validate_handler()
        if self.read(target, len(original)) != original: raise RuntimeError('Entry changed before publication')
        self.hook['patch_attempted'] = True
        self.mod._native_write_code(target, self.hook['patch'])
        if self.read(target, len(original)) != self.hook['patch']: raise RuntimeError('Trace publication readback differs')
        self.capture.report['native_patches'] += 1
        self.capture.report['native_patches_peak'] = max(self.capture.report.get('native_patches_peak', 0), self.capture.report['native_patches'])

    def validate(self):
        if self.hook is not None and self.read(self.hook['target'], len(self.hook['patch'])) != self.hook['patch']:
            raise RuntimeError('Owned entry trace bytes changed')

    def stop(self):
        if self.hook is None: return
        if not self.capture.updates.is_game_thread(): raise RuntimeError('Cleanup requires owned game thread; rerun')
        if self.hook['patch_attempted']: self.mod._native_restore_hook(self.hook)
        self.mod._native_release_hook(self.hook)
        self.hook = None

class NativeEntryOwner:
    def __init__(self,parent):
        self.parent=parent;self.mod=parent.mod;self.updates=parent.updates;self.report=parent.report
        self.control=(ctypes.c_uint64*24)();self.buffer=(ctypes.c_ubyte*(CircleEntry_CAPACITY*CircleEntry_RECORD_SIZE))()
        self.consumed=0;self.base=0
    def bound(self):return self.parent.bound()
    def validate_handler(self):return self.parent.validate_handler()

ENTRY_SPECS = [('Action_Crouch', 21414478, '5657534883ec40660f297c2430660f29742420', 775, '9b81d5df010ca0b396611807c9d6597cb59c537940ae960f70b38acd48cc5d9a', 'circle_crouch_entry')]

