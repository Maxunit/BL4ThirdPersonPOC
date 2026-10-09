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

CAPACITY = 1024

RECORD_SIZE = 128

TARGET_RVA = 0x493D8EA

PROLOGUE = bytes.fromhex('5657534881eca0000000660f29bc2490000000660f29b42480000000')

TRACE_PREFIX = bytes.fromhex('9c50415241535249ba111111111111111149833a01753f493b4a08753965488b042548000000493b4210752a4c8b99100100004d3b5a18751d49837a38017516488b442428493b4240750b4d8d834002000049ff42485a415b415a589d')

SLIDE_RECORD_PREFIX = bytes.fromhex('9c50415241535249ba111111111111111149833a010f85d3000000493b4a080f85c900000065488b042548000000493b42100f85b60000004c8b99100100004d3b5a180f85a5000000498b4228483d000400000f83950000004889c248c1e20749035220488b442428488942084c895a104c894a18498b0048894220498b400848894228498b401048894230498b401848894238498b834002000048894240498b834802000048894248498b835002000048894250498b8358020000488942584c8b1c24498b0348894260498b430848894268498b431048894270498b42304889427848c7020100000049ff42285a415b415a589d')

SLIDE_RECORD_HASH = '9739330907f06c1ec57ad178d71b65b0f776c88520137cd3dd41005cff7ff374'

TRACE_HASH = '79cd2c76a368f08b8000004670068127de8eb8c7fd0bdb6b978925dc1d3fc293'

class NativeTrace:
    def __init__(self, capture):
        self.capture = capture
        self.mod = capture.mod
        self.hook = None
        self.control = (ctypes.c_uint64 * 10)()
        self.buffer = (ctypes.c_ubyte * (CAPACITY * RECORD_SIZE))()
        self.consumed = 0
        self.slide_control = (ctypes.c_uint64 * 7)()
        self.slide_buffer = (ctypes.c_ubyte * (CAPACITY * RECORD_SIZE))()
        self.slide_consumed = 0
        capture.report['slide_rotation_arguments'] = []

    def read(self, address, size):
        if not 0x10000 <= address < 0x800000000000 or not 0 < size <= 4096 or address+size >= 0x800000000000:
            raise RuntimeError('Native read outside bounds')
        self.capture.report['native_reads'] += 1
        data = self.mod._native_read(address,size)
        if len(data) != size:
            raise RuntimeError('Short native read')
        return data

    def u64(self, address):
        return struct.unpack('<Q',self.read(address,8))[0]

    def install(self):
        if not self.capture.updates.is_game_thread():
            raise RuntimeError('Native installation requires owned game thread')
        if len(PROLOGUE) != 28 or len(TRACE_PREFIX) != 93 or hashlib.sha256(TRACE_PREFIX).hexdigest() != TRACE_HASH:
            raise RuntimeError('Audited instruction template differs')
        if TRACE_PREFIX.count(b'\x11'*8) != 1:
            raise RuntimeError('Native control marker differs')
        pc,pawn,camera,movement = self.capture.bound()
        self.movement = int(movement._get_address())
        self.base = int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        dos = self.read(self.base,64)
        if dos[:2] != b'MZ':raise RuntimeError('DOS signature differs')
        offset = struct.unpack_from('<I',dos,60)[0]
        if not 64 <= offset <= 0x100000:raise RuntimeError('PE offset outside bounds')
        pe = self.read(self.base+offset,0x108)
        build = (struct.unpack_from('<I',pe,8)[0],struct.unpack_from('<I',pe,80)[0],struct.unpack_from('<H',pe,4)[0])
        if pe[:4] != b'PE\0\0' or struct.unpack_from('<H',pe,24)[0] != 0x20b or build != (0x6AA81051,0x31B8C000,0x8664):
            raise RuntimeError('Unreviewed game build')
        self.capture.report['build'] = [hex(v) for v in build]
        self.vtable = self.u64(self.movement)
        if self.vtable != self.base+0xB709670 or self.u64(self.vtable+157*8) != self.base+TARGET_RVA:
            raise RuntimeError('Reviewed movement dispatch differs')
        self.component = self.u64(self.movement+0x110)
        if not self.component or self.u64(self.component) != self.base+0xA824FC0:
            raise RuntimeError('Reviewed UpdatedComponent differs')
        if self.u64(self.base+0xA824FC0+162*8) != self.base+0x28BA36:
            raise RuntimeError('Reviewed component dispatch differs')
        if self.read(self.base+0x2E2E11,6) != bytes.fromhex('ff90e8040000'):
            raise RuntimeError('TurnState caller instruction differs')
        if hashlib.sha256(self.read(self.base+0x56EF1A4,1355)).hexdigest()!='4e81eb7ca362027ab28ac5c04d520e5a8c328e7d07be6328a47b166207a37f3e':
            raise RuntimeError('Reviewed Slide rotation caller differs')
        target = self.base+TARGET_RVA
        if self.read(target,len(PROLOGUE)) != PROLOGUE:
            raise RuntimeError('Native entry is already patched or differs')
        # Check the complete entry window is committed executable image memory.
        info = self.mod._native_query(target)
        region_base = int(info.BaseAddress or 0)
        if (int(info.State) != 0x1000 or int(info.Type) != 0x1000000
                or int(info.Protect)&0x100 or int(info.Protect)&0xff not in (0x20,0x40,0x80)
                or not region_base <= target < target+len(PROLOGUE) <= region_base+int(info.RegionSize)):
            raise RuntimeError('Native code page identity/protection differs')
        self.control[8] = self.base+0x2E2E17
        self.control[1] = self.movement
        self.control[2] = threading.get_native_id()
        self.control[3] = self.component
        self.control[4] = ctypes.addressof(self.buffer)
        stub = int(self.mod._kernel32.VirtualAlloc(None,0x2000,0x3000,0x40) or 0)
        if not stub:raise RuntimeError('Native trace allocation failed')
        trampoline = stub+0x1800
        self.hook = {'target':target,'original':PROLOGUE,
            'patch':self.mod._native_absolute_jump(stub)+b'\x90'*(len(PROLOGUE)-14),
            'stub':stub,'trampoline':trampoline,'buffer':self.buffer,'control':self.control,
            'restored':False,'patch_attempted':False,'label':'player TurnState trace'}
        if len(SLIDE_RECORD_PREFIX)!=245 or hashlib.sha256(SLIDE_RECORD_PREFIX).hexdigest()!=SLIDE_RECORD_HASH:
            raise RuntimeError('Reviewed Slide recording template differs')
        for slot in (1,2,3):self.slide_control[slot]=self.control[slot]
        self.slide_control[4]=ctypes.addressof(self.slide_buffer)
        recording=SLIDE_RECORD_PREFIX.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(self.slide_control)))
        code = recording+TRACE_PREFIX.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(self.control)))+self.mod._native_absolute_jump(trampoline)
        original = self.mod._native_build_trampoline(PROLOGUE,target+len(PROLOGUE))
        ctypes.memmove(stub,code,len(code));ctypes.memmove(trampoline,original,len(original))
        process = self.mod._kernel32.GetCurrentProcess()
        for address,data in ((stub,code),(trampoline,original)):
            if not self.mod._kernel32.FlushInstructionCache(process,ctypes.c_void_p(address),len(data)):
                raise RuntimeError('Native instruction-cache flush failed')
        self.capture.bound()
        self.validate()
        if self.read(target,len(PROLOGUE)) != PROLOGUE:raise RuntimeError('Entry changed before publication')
        self.hook['patch_attempted'] = True
        self.mod._native_write_code(target,self.hook['patch'])
        if self.read(target,len(PROLOGUE)) != self.hook['patch']:
            raise RuntimeError('Native patch publication readback differs')
        self.capture.report.update(native_patches=4,native_patches_peak=4,
            native_patch_installations=4,trace_capacity=0,native_per_call_recording=False)
        self.capture.report['native_binding'] = {'target_rva':hex(TARGET_RVA),
            'turn_state_return_rva':'0x2e2e17','native_thread_id':int(self.control[2]),
            'note':'Local movement and current UpdatedComponent filter; rotation argument replacement is enabled only for the local TurnState caller during the manually stopped follow test.'}
        self.control[0] = 1
        logging.warning(TAG+' TRACE_INSTALLED native_patches=4 game_writes=0')

    def validate(self):
        movement = self.capture.bound()[3]
        if (int(movement._get_address()) != self.movement or self.u64(self.movement) != self.vtable
                or self.u64(self.movement+0x110) != self.component):
            raise RuntimeError('Bound native movement/component changed')

    def consume(self):
        count = int(self.control[5])
        if not self.consumed <= count <= CAPACITY:raise RuntimeError('Native record count outside bounds')
        for index in range(self.consumed,count):
            raw = bytes(self.buffer[index*RECORD_SIZE:(index+1)*RECORD_SIZE])
            committed,caller,component,flags = struct.unpack_from('<4Q',raw)
            if committed not in (1,2):raise RuntimeError('Uncommitted native record')
            if committed == 2 and caller-self.base != 0x2E2E17:
                raise RuntimeError('Replacement record has unexpected caller')
            relative = caller-self.base
            delta = struct.unpack_from('<3d',raw,96)
            target,root = quat(raw[32:64]),quat(raw[64:96])
            row = {'index':index,'caller_return_rva':hex(relative),
                'from_turn_state':relative == 0x2E2E17,'component_address':hex(component),
                'sweep_argument_low_byte':flags & 0xff,'r9_raw':hex(flags),'requested_quaternion':target,'root_quaternion_before_call':root,
                'rotation_argument_replaced':committed == 2,
                'forwarded_quaternion':root if committed == 2 else target,
                'delta_xyz':list(delta) if all(math.isfinite(v) for v in delta) else None,
                'last_widget_update_index':struct.unpack_from('<Q',raw,120)[0]}
            if 'yaw' in target and 'yaw' in root:
                row['target_minus_root_before'] = angle(target['yaw'],root['yaw'])
            self.capture.report['native_records'].append(row)
        self.consumed = count

    def consume_slide(self):
        count=int(self.slide_control[5])
        if not self.slide_consumed<=count<=CAPACITY:raise RuntimeError('Slide trace count outside bounds')
        for index in range(self.slide_consumed,count):
            raw=bytes(self.slide_buffer[index*RECORD_SIZE:(index+1)*RECORD_SIZE])
            committed,caller,component,flags=struct.unpack_from('<4Q',raw)
            if committed!=1 or component!=self.component:raise RuntimeError('Slide trace record identity differs')
            requested=quat(raw[32:64]);root=quat(raw[64:96])
            delta=struct.unpack_from('<3d',raw,96)
            row=dict(index=index,caller_return_rva=hex(caller-self.base),
                requested_quaternion=requested,root_quaternion_before_call=root,
                r9_raw=hex(flags),last_widget_update_index=struct.unpack_from('<Q',raw,120)[0],
                delta_xyz=list(delta) if all(math.isfinite(v) for v in delta) else None)
            if 'yaw' in requested and 'yaw' in root:row['requested_minus_root']=angle(requested['yaw'],root['yaw'])
            self.capture.report['slide_rotation_arguments'].append(row)
        self.slide_consumed=count
        self.capture.report['slide_rotation_argument_count']=count
        self.capture.report['slide_rotation_argument_capacity_reached']=count==CAPACITY

    def stop(self):
        self.slide_control[0]=0
        self.control[0] = 0
        if self.hook is not None:
            if not self.capture.updates.is_game_thread():
                raise RuntimeError('Native cleanup requires owned game thread; rerun in console')
            if self.hook['patch_attempted']:
                self.mod._native_restore_hook(self.hook)
                self.capture.report['native_restoration_verified'] = True
            self.mod._native_release_hook(self.hook)
            self.hook = None
        self.capture.report['native_patches'] = 0
        self.capture.report['native_rotation_argument_overrides'] = int(self.control[9])
        self.consume()
        self.consume_slide()

class NativeAimYaw:
    TARGET = 0x15D688
    PROLOGUE = bytes.fromhex('4157415641545657534883ec384889d64889cf')
    PREFIX = bytes.fromhex('9c50415249ba1111111111111111493b4a087527488b442418493b4210751c4885d27417f049ff422049833a01750c48c70200000000f049ff4218415a589d')
    HASH = '24561c0e3c7f65744351e0a4b2732fcdb9d00ac234da7452e6ec23bb315a6b60'
    PREFIX_SIZE = 63

    def prefix_code(self):
        return self.PREFIX.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(self.control)))

    def __init__(self,capture):
        self.capture=capture
        self.mod=capture.mod
        self.control=(ctypes.c_uint64*5)()
        self.hook=None

    def install(self):
        c=self.capture
        if not c.updates.is_game_thread():raise RuntimeError('Aim hook installation requires owned game thread')
        read=c.native.read
        base=int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        dos=read(base,64)
        if dos[:2]!=b'MZ':raise RuntimeError('Aim DOS signature differs')
        offset=struct.unpack_from('<I',dos,60)[0]
        if not 64<=offset<=0x100000:raise RuntimeError('Aim PE offset outside bounds')
        pe=read(base+offset,0x108)
        build=(struct.unpack_from('<I',pe,8)[0],struct.unpack_from('<I',pe,80)[0],struct.unpack_from('<H',pe,4)[0])
        if pe[:4]!=b'PE\0\0' or struct.unpack_from('<H',pe,24)[0]!=0x20b or build!=(0x6AA81051,0x31B8C000,0x8664):
            raise RuntimeError('Unreviewed Aim hook game build')
        anim=c.anim_ref()
        # SDK property enumeration may include inherited properties again.
        # Require one distinct reflected layout, rather than one enumeration occurrence.
        candidate_map={}
        for owner in (anim.Class,*tuple(anim.Class._superfields())):
            for prop in owner._properties():
                if str(prop.Name)!=c.NODE_NAME or str(prop.Class.Name)!='StructProperty':continue
                key=(int(prop.Offset_Internal),str(prop.Struct.Name))
                candidate_map.setdefault(key,prop)
        candidates=list(candidate_map.values())
        if len(candidates)!=1 or str(candidates[0].Struct.Name)!='GbxAnimNode_Rotation_AimOffset':
            raise RuntimeError('Aim node reflection binding differs: distinct layouts='+repr(list(candidate_map)))
        node_offset=int(candidates[0].Offset_Internal)
        if not 0<=node_offset<=0x400000:raise RuntimeError('Aim node offset outside bounds')
        self.node=c.anim_address+node_offset
        self.table=struct.unpack('<Q',read(self.node,8))[0]
        if self.table!=base+0xB0A4B90 or struct.unpack('<Q',read(self.table+61*8,8))[0]!=base+self.TARGET:
            raise RuntimeError('Reviewed normal Aim input dispatch differs')
        node=getattr(anim,c.NODE_NAME)
        if int(node.YawAxis)!=1 or int(node.PitchAxis)!=2:raise RuntimeError('Reviewed Aim axes differ')
        for rva,expected in {0x15D5EF:'ff90e8010000',0x15D59E:'f30f5a8640010000',0x15D5C5:'f30f5a8644010000'}.items():
            if read(base+rva,len(bytes.fromhex(expected)))!=bytes.fromhex(expected):
                raise RuntimeError('Reviewed Aim axis/callsite differs: '+hex(rva))
        target=base+self.TARGET
        if read(target,len(self.PROLOGUE))!=self.PROLOGUE:raise RuntimeError('Aim entry patched or differs')
        info=self.mod._native_query(target);region=int(info.BaseAddress or 0)
        if (int(info.State)!=0x1000 or int(info.Type)!=0x1000000 or int(info.Protect)&0x100
                or int(info.Protect)&0xff not in (0x20,0x40,0x80)
                or not region<=target<target+len(self.PROLOGUE)<=region+int(info.RegionSize)):
            raise RuntimeError('Aim native code page differs')
        if len(self.PROLOGUE)!=19 or len(self.PREFIX)!=self.PREFIX_SIZE or hashlib.sha256(self.PREFIX).hexdigest()!=self.HASH:
            raise RuntimeError('Audited Aim instruction template differs')
        self.control[1]=self.node;self.control[2]=base+0x15D5F5
        stub=int(self.mod._kernel32.VirtualAlloc(None,0x2000,0x3000,0x40) or 0)
        if not stub:raise RuntimeError('Aim stub allocation failed')
        trampoline=stub+0x1800
        self.hook={'target':target,'original':self.PROLOGUE,
            'patch':self.mod._native_absolute_jump(stub)+b'\x90'*(len(self.PROLOGUE)-14),
            'stub':stub,'trampoline':trampoline,'control':self.control,'buffer':self.control,
            'restored':False,'patch_attempted':False,'label':'normal AimOffset stack yaw AB'}
        code=self.prefix_code()+self.mod._native_absolute_jump(trampoline)
        original=self.mod._native_build_trampoline(self.PROLOGUE,target+len(self.PROLOGUE))
        ctypes.memmove(stub,code,len(code));ctypes.memmove(trampoline,original,len(original))
        for address,data in ((stub,code),(trampoline,original)):
            if not self.mod._kernel32.FlushInstructionCache(self.mod._kernel32.GetCurrentProcess(),ctypes.c_void_p(address),len(data)):
                raise RuntimeError('Aim instruction-cache flush failed')
        c.bound()
        if read(self.node,8)!=struct.pack('<Q',self.table) or read(target,len(self.PROLOGUE))!=self.PROLOGUE:
            raise RuntimeError('Aim binding changed before publication')
        self.hook['patch_attempted']=True
        self.mod._native_write_code(target,self.hook['patch'])
        if read(target,len(self.PROLOGUE))!=self.hook['patch']:raise RuntimeError('Aim patch readback differs')
        c.report['aim_native_binding']={'target_rva':hex(self.TARGET),'caller_return_rva':'0x15d5f5',
            'node_name':c.NODE_NAME,'node_offset':node_offset,
            'scope':'Exact normal node address and captured caller only. Zero first double in caller-owned temporary input vector; preserve pitch and all other arguments. Runs inline on the animation caller thread, without Python callbacks. Counters use atomic increments; published stubs and controls remain pinned after restoration.'}

    def validate(self):
        c=self.capture
        anim=c.anim_ref()
        if anim is None or int(anim._get_address())!=c.anim_address:raise RuntimeError('Aim animation identity changed')
        if self.hook is not None:
            if c.native.read(self.node,8)!=struct.pack('<Q',self.table):raise RuntimeError('Aim node vtable changed')
            if c.native.read(self.hook['target'],len(self.PROLOGUE))!=self.hook['patch']:
                raise RuntimeError('Aim code ownership changed')

    def stop(self):
        self.control[0]=0
        if self.hook is not None:
            if not self.capture.updates.is_game_thread():raise RuntimeError('Aim cleanup requires owned game thread')
            if self.hook['patch_attempted']:
                self.mod._native_restore_hook(self.hook)
                self.capture.report['aim_native_restoration_verified']=True
            self.mod._native_release_hook(self.hook)
            self.hook=None
        self.capture.report['aim_yaw_neutralizations']=int(self.control[3])
        self.capture.report['native_data_writes']=int(self.control[3])
        self.capture.report['aim_input_dispatch_calls']=int(self.control[4])

class NativeIdleRoot:
    TARGET = 0x186EC4A
    POSE_TARGET = 0x186EC26
    PROLOGUE = bytes.fromhex('80be0c03000001750980be08030000017417')
    PREFIX = bytes.fromhex('9c50415249ba1111111111111111493b72087516f049ff422049833a01750bf049ff4218415a589deb24415a589d80be0c03000001751780be0803000001750eff25000000003333333333333333ff25000000002222222222222222')
    HASH = '096df20006ecce7b527a6e272e11e111ab68ac5910b9f5713d2b5c199d34e327'

    def __init__(self,capture):
        self.capture=capture
        self.mod=capture.mod
        self.control=(ctypes.c_uint64*5)()
        self.hook=None

    def install(self):
        c=self.capture
        if not c.updates.is_game_thread():raise RuntimeError('IdleRoot hook installation requires owned game thread')
        read=c.native.read
        base=int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        dos=read(base,64)
        if dos[:2]!=b'MZ':raise RuntimeError('IdleRoot DOS signature differs')
        offset=struct.unpack_from('<I',dos,60)[0]
        if not 64<=offset<=0x100000:raise RuntimeError('IdleRoot PE offset outside bounds')
        pe=read(base+offset,0x108)
        build=(struct.unpack_from('<I',pe,8)[0],struct.unpack_from('<I',pe,80)[0],struct.unpack_from('<H',pe,4)[0])
        if pe[:4]!=b'PE\0\0' or struct.unpack_from('<H',pe,24)[0]!=0x20b or build!=(0x6AA81051,0x31B8C000,0x8664):
            raise RuntimeError('Unreviewed IdleRoot hook game build')
        anim=c.anim_ref()
        # SDK property enumeration may include inherited properties again.
        # Require one distinct reflected layout, rather than one enumeration occurrence.
        candidate_map={}
        for owner in (anim.Class,*tuple(anim.Class._superfields())):
            for prop in owner._properties():
                if str(prop.Name)!=c.IDLE_NODE_NAME or str(prop.Class.Name)!='StructProperty':continue
                key=(int(prop.Offset_Internal),str(prop.Struct.Name))
                candidate_map.setdefault(key,prop)
        candidates=list(candidate_map.values())
        if len(candidates)!=1 or str(candidates[0].Struct.Name)!='GbxAnimNode_IdleTurns':
            raise RuntimeError('IdleRoot node reflection binding differs: distinct layouts='+repr(list(candidate_map)))
        node_offset=int(candidates[0].Offset_Internal)
        if not 0<=node_offset<=0x400000:raise RuntimeError('IdleRoot node offset outside bounds')
        self.node=c.anim_address+node_offset
        self.table=struct.unpack('<Q',read(self.node,8))[0]
        if self.table!=base+0xB09AF80 or struct.unpack('<Q',read(self.table+5*8,8))[0]!=base+self.POSE_TARGET:
            raise RuntimeError('Reviewed normal IdleRoot input dispatch differs')
        node=getattr(anim,c.IDLE_NODE_NAME)
        if read(base+0x186EC45,5)!=bytes.fromhex('e8b25df602'):
            raise RuntimeError('Reviewed base pose call before Root correction differs')
        if read(base+0x186EC5C,23)!=bytes.fromhex('0f287424200f287c2430440f284424404883c4585f5ec3'):
            raise RuntimeError('Reviewed pose epilogue differs')
        target=base+self.TARGET
        if read(target,len(self.PROLOGUE))!=self.PROLOGUE:raise RuntimeError('IdleRoot entry patched or differs')
        info=self.mod._native_query(target);region=int(info.BaseAddress or 0)
        if (int(info.State)!=0x1000 or int(info.Type)!=0x1000000 or int(info.Protect)&0x100
                or int(info.Protect)&0xff not in (0x20,0x40,0x80)
                or not region<=target<target+len(self.PROLOGUE)<=region+int(info.RegionSize)):
            raise RuntimeError('IdleRoot native code page differs')
        if len(self.PROLOGUE)!=18 or len(self.PREFIX)!=92 or hashlib.sha256(self.PREFIX).hexdigest()!=self.HASH:
            raise RuntimeError('Audited IdleRoot instruction template differs')
        self.control[1]=self.node
        stub=int(self.mod._kernel32.VirtualAlloc(None,0x2000,0x3000,0x40) or 0)
        if not stub:raise RuntimeError('IdleRoot stub allocation failed')
        trampoline=stub+0x1800
        self.hook={'target':target,'original':self.PROLOGUE,
            'patch':self.mod._native_absolute_jump(stub)+b'\x90'*(len(self.PROLOGUE)-14),
            'stub':stub,'trampoline':trampoline,'control':self.control,'buffer':self.control,
            'restored':False,'patch_attempted':False,'label':'trace-confirmed IdleTurns_2 extra Root correction AB'}
        code=(self.PREFIX.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(self.control)))
            .replace(b'\x22'*8,struct.pack('<Q',base+0x186EC5C))
            .replace(b'\x33'*8,struct.pack('<Q',base+0x186EC73)))
        ctypes.memmove(stub,code,len(code))
        if not self.mod._kernel32.FlushInstructionCache(self.mod._kernel32.GetCurrentProcess(),ctypes.c_void_p(stub),len(code)):
            raise RuntimeError('IdleRoot instruction-cache flush failed')
        c.bound()
        if read(self.node,8)!=struct.pack('<Q',self.table) or read(target,len(self.PROLOGUE))!=self.PROLOGUE:
            raise RuntimeError('IdleRoot binding changed before publication')
        self.hook['patch_attempted']=True
        self.mod._native_write_code(target,self.hook['patch'])
        if read(target,len(self.PROLOGUE))!=self.hook['patch']:raise RuntimeError('IdleRoot patch readback differs')
        c.report['idle_root_native_binding']={'target_rva':hex(self.TARGET),'pose_entry_rva':hex(self.POSE_TARGET),
            'node_name':c.IDLE_NODE_NAME,'node_offset':node_offset,
            'scope':'After original base-pose evaluation: exact trace-confirmed IdleTurns_2 node RSI only. When enabled skip only the additional Root quaternion multiplication; other nodes preserve both original guard tests and destinations. No node field writes or Python animation-thread callbacks. Published stubs/controls remain pinned after restoration.'}

    def validate(self):
        c=self.capture
        anim=c.anim_ref()
        if anim is None or int(anim._get_address())!=c.anim_address:raise RuntimeError('IdleRoot animation identity changed')
        if self.hook is not None:
            if c.native.read(self.node,8)!=struct.pack('<Q',self.table):raise RuntimeError('IdleRoot node vtable changed')
            if c.native.read(self.hook['target'],len(self.PROLOGUE))!=self.hook['patch']:
                raise RuntimeError('IdleRoot code ownership changed')

    def stop(self):
        self.control[0]=0
        if self.hook is not None:
            if not self.capture.updates.is_game_thread():raise RuntimeError('IdleRoot cleanup requires owned game thread')
            if self.hook['patch_attempted']:
                self.mod._native_restore_hook(self.hook)
                self.capture.report['idle_root_native_restoration_verified']=True
            self.mod._native_release_hook(self.hook)
            self.hook=None
        self.capture.report['idle_root_correction_bypasses']=int(self.control[3])
        self.capture.report['idle_root_guard_dispatches']=int(self.control[4])

class NativeIdleUpdate:
    TARGET = 0x186E883
    POSE_TARGET = 0x186E850
    PROLOGUE = bytes.fromhex('80b90c03000001750d80bf08030000010f84b1000000')
    PREFIX = bytes.fromhex('9c50415249ba1111111111111111493b7a087516f049ff422049833a01750bf049ff4218415a589deb24415a589d80b90c03000001751780bf0803000001750eff25000000003333333333333333ff25000000002222222222222222')
    HASH = '9ad9792881baa6f48307606933037b85bb66909318da9a2a5cc183449333fb87'

    def __init__(self,capture):
        self.capture=capture
        self.mod=capture.mod
        self.control=(ctypes.c_uint64*5)()
        self.hook=None

    def install(self):
        c=self.capture
        if not c.updates.is_game_thread():raise RuntimeError('IdleUpdate hook installation requires owned game thread')
        read=c.native.read
        base=int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        dos=read(base,64)
        if dos[:2]!=b'MZ':raise RuntimeError('IdleUpdate DOS signature differs')
        offset=struct.unpack_from('<I',dos,60)[0]
        if not 64<=offset<=0x100000:raise RuntimeError('IdleUpdate PE offset outside bounds')
        pe=read(base+offset,0x108)
        build=(struct.unpack_from('<I',pe,8)[0],struct.unpack_from('<I',pe,80)[0],struct.unpack_from('<H',pe,4)[0])
        if pe[:4]!=b'PE\0\0' or struct.unpack_from('<H',pe,24)[0]!=0x20b or build!=(0x6AA81051,0x31B8C000,0x8664):
            raise RuntimeError('Unreviewed IdleUpdate hook game build')
        anim=c.anim_ref()
        # SDK property enumeration may include inherited properties again.
        # Require one distinct reflected layout, rather than one enumeration occurrence.
        candidate_map={}
        for owner in (anim.Class,*tuple(anim.Class._superfields())):
            for prop in owner._properties():
                if str(prop.Name)!=c.IDLE_NODE_NAME or str(prop.Class.Name)!='StructProperty':continue
                key=(int(prop.Offset_Internal),str(prop.Struct.Name))
                candidate_map.setdefault(key,prop)
        candidates=list(candidate_map.values())
        if len(candidates)!=1 or str(candidates[0].Struct.Name)!='GbxAnimNode_IdleTurns':
            raise RuntimeError('IdleUpdate node reflection binding differs: distinct layouts='+repr(list(candidate_map)))
        node_offset=int(candidates[0].Offset_Internal)
        if not 0<=node_offset<=0x400000:raise RuntimeError('IdleUpdate node offset outside bounds')
        self.node=c.anim_address+node_offset
        self.table=struct.unpack('<Q',read(self.node,8))[0]
        if self.table!=base+0xB09AF80 or struct.unpack('<Q',read(self.table+4*8,8))[0]!=base+self.POSE_TARGET:
            raise RuntimeError('Reviewed normal IdleUpdate input dispatch differs')
        node=getattr(anim,c.IDLE_NODE_NAME)
        if read(base+0x186E850,51)!=bytes.fromhex('41565657534881ec8800000066440f29442470660f297c24600f297424504889d64889cf488b05c510e90a4831e04889442448'):
            raise RuntimeError('Reviewed IdleTurns update prefix differs')
        target=base+self.TARGET
        if read(target,len(self.PROLOGUE))!=self.PROLOGUE:raise RuntimeError('IdleUpdate entry patched or differs')
        info=self.mod._native_query(target);region=int(info.BaseAddress or 0)
        if (int(info.State)!=0x1000 or int(info.Type)!=0x1000000 or int(info.Protect)&0x100
                or int(info.Protect)&0xff not in (0x20,0x40,0x80)
                or not region<=target<target+len(self.PROLOGUE)<=region+int(info.RegionSize)):
            raise RuntimeError('IdleUpdate native code page differs')
        if len(self.PROLOGUE)!=22 or len(self.PREFIX)!=92 or hashlib.sha256(self.PREFIX).hexdigest()!=self.HASH:
            raise RuntimeError('Audited IdleUpdate instruction template differs')
        self.control[1]=self.node
        stub=int(self.mod._kernel32.VirtualAlloc(None,0x2000,0x3000,0x40) or 0)
        if not stub:raise RuntimeError('IdleUpdate stub allocation failed')
        trampoline=stub+0x1800
        self.hook={'target':target,'original':self.PROLOGUE,
            'patch':self.mod._native_absolute_jump(stub)+b'\x90'*(len(self.PROLOGUE)-14),
            'stub':stub,'trampoline':trampoline,'control':self.control,'buffer':self.control,
            'restored':False,'patch_attempted':False,'label':'trace-confirmed IdleTurns_2 update idle branch AB'}
        code=(self.PREFIX.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(self.control)))
            .replace(b'\x22'*8,struct.pack('<Q',base+0x186E899))
            .replace(b'\x33'*8,struct.pack('<Q',base+0x186E94A)))
        ctypes.memmove(stub,code,len(code))
        if not self.mod._kernel32.FlushInstructionCache(self.mod._kernel32.GetCurrentProcess(),ctypes.c_void_p(stub),len(code)):
            raise RuntimeError('IdleUpdate instruction-cache flush failed')
        c.bound()
        if read(self.node,8)!=struct.pack('<Q',self.table) or read(target,len(self.PROLOGUE))!=self.PROLOGUE:
            raise RuntimeError('IdleUpdate binding changed before publication')
        self.hook['patch_attempted']=True
        self.mod._native_write_code(target,self.hook['patch'])
        if read(target,len(self.PROLOGUE))!=self.hook['patch']:raise RuntimeError('IdleUpdate patch readback differs')
        c.report['idle_update_native_binding']={'target_rva':hex(self.TARGET),'pose_entry_rva':hex(self.POSE_TARGET),
            'node_name':c.IDLE_NODE_NAME,'node_offset':node_offset,
            'scope':'Exact bound IdleTurns_2 RDI at reviewed update branch. When enabled route to original fallback that selects input zero (Idle) and runs the original generic update. Preserve original branch guards/destinations for all other nodes or disabled gate. No node field writes from Python; worker caller runs inline with no Python callback. Counters atomic and stubs pinned after restoration.'}


    def validate(self):
        c=self.capture
        anim=c.anim_ref()
        if anim is None or int(anim._get_address())!=c.anim_address:raise RuntimeError('IdleUpdate animation identity changed')
        if self.hook is not None:
            if c.native.read(self.node,8)!=struct.pack('<Q',self.table):raise RuntimeError('IdleUpdate node vtable changed')
            if c.native.read(self.hook['target'],len(self.PROLOGUE))!=self.hook['patch']:
                raise RuntimeError('IdleUpdate code ownership changed')

    def stop(self):
        self.control[0]=0
        if self.hook is not None:
            if not self.capture.updates.is_game_thread():raise RuntimeError('IdleUpdate cleanup requires owned game thread')
            if self.hook['patch_attempted']:
                self.mod._native_restore_hook(self.hook)
                self.capture.report['idle_update_native_restoration_verified']=True
            self.mod._native_release_hook(self.hook)
            self.hook=None
        self.capture.report['idle_update_idle_branch_overrides']=int(self.control[3])
        self.capture.report['idle_update_guard_dispatches']=int(self.control[4])

class NativeSlideCrouchAimYaw(NativeAimYaw):
    # Two sequential copies of the tested 63-byte receiver/caller filter.
    # Each restores registers/flags before the next; no new code patch site.
    PREFIX=NativeAimYaw.PREFIX*2
    PREFIX_SIZE=126
    HASH='f1de20b2c866a0eb8893e25c5cf8d15531569aee37597d7771eaa7d47f20db8c'
    CROUCH_NAME='GbxAnimGraphNode_Rotation_AimOffset_2'

    def __init__(self,capture):
        super().__init__(capture)
        self.crouch_control=(ctypes.c_uint64*5)()
        # The primary published control also pins the second control lifetime.
        self.control._slide_crouch_control=self.crouch_control
        self.crouch_node=None

    def prefix_code(self):
        original=NativeAimYaw.PREFIX
        if len(original)!=63 or hashlib.sha256(original).hexdigest()!=NativeAimYaw.HASH:
            raise RuntimeError('Original Aim prefix audit differs')
        return (original.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(self.control)))+
                original.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(self.crouch_control))))

    def install(self):
        c=self.capture
        if not c.updates.is_game_thread():raise RuntimeError('Crouch Aim binding requires owned game thread')
        anim=c.anim_ref();read=c.native.read
        if anim is None or int(anim._get_address())!=c.anim_address:raise RuntimeError('Crouch Aim animation identity differs')
        layouts={}
        for owner in (anim.Class,*tuple(anim.Class._superfields())):
            for prop in owner._properties():
                if str(prop.Name)==self.CROUCH_NAME and str(prop.Class.Name)=='StructProperty':
                    layouts[(int(prop.Offset_Internal),str(prop.Struct.Name))]=prop
        if len(layouts)!=1:raise RuntimeError('Crouch Aim reflected layouts differ')
        offset,kind=next(iter(layouts))
        if kind!='GbxAnimNode_Rotation_AimOffset' or not 0<=offset<=0x400000:
            raise RuntimeError('Crouch Aim reflected struct differs')
        node=getattr(anim,self.CROUCH_NAME)
        if (str(node.RotationChannelName.TagName)!='RotationChannel.Aim' or
            str(node.BlendSpaceKey.TagName)!='AnimSet.Player.3rd.AimO_3rd_Crouch' or
            int(node.YawAxis)!=1 or int(node.PitchAxis)!=2):
            raise RuntimeError('Crouch Aim channel/key/axes differ')
        base=int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        address=c.anim_address+offset
        table=struct.unpack('<Q',read(address,8))[0]
        if table!=base+0xB0A4B90 or struct.unpack('<Q',read(table+61*8,8))[0]!=base+self.TARGET:
            raise RuntimeError('Crouch Aim native dispatch differs')
        self.crouch_node=address;self.crouch_table=table
        self.crouch_control[1]=address;self.crouch_control[2]=base+0x15D5F5
        # Parent performs the existing exact Steam fingerprint/code/caller checks.
        super().install()
        self.validate()
        c.report['crouch_aim_native_binding']=dict(node_name=self.CROUCH_NAME,node_offset=offset,
            target_rva=hex(self.TARGET),caller_return_rva='0x15d5f5',additional_native_patches=0,
            scope='Second exact-node/caller copy of the tested Aim prefix, enabled only in B free Slide. Zero yaw in caller temporary, preserve pitch. Worker counters atomic, no strict pose-order inference.')

    def validate(self):
        super().validate()
        if self.crouch_node is not None and self.capture.native.read(self.crouch_node,8)!=struct.pack('<Q',self.crouch_table):
            raise RuntimeError('Crouch Aim node ownership changed')

    def stop(self):
        self.crouch_control[0]=0
        super().stop()
        r=self.capture.report
        r['crouch_aim_yaw_neutralizations']=int(self.crouch_control[3])
        r['crouch_aim_input_dispatch_calls']=int(self.crouch_control[4])
        r['native_data_writes']=int(r.get('native_data_writes',0))+int(self.crouch_control[3])

