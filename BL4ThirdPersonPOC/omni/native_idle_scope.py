"""Exact reflected local IdleTurns scope; original targets and build guards retained."""
import ctypes
import hashlib
import struct
from ..build_gate import REVIEWED_BUILD
from .native_rotation import NativeIdleRoot, NativeIdleUpdate

IDLE_NAMES = frozenset(('GbxAnimGraphNode_IdleTurns', 'GbxAnimGraphNode_IdleTurns_1',
                        'GbxAnimGraphNode_IdleTurns_2', 'GbxAnimGraphNode_IdleTurns_3',
                        'GbxAnimGraphNode_IdleTurns_4'))

class IdleScopeMixin:
    def __init__(self, capture):
        super().__init__(capture)
        self.control = (ctypes.c_uint64 * 9)()
        self.scope_nodes = ()

    def bind_scope(self):
        c = self.capture
        anim = c.anim_ref()
        if anim is None or int(anim._get_address()) != c.anim_address:
            raise RuntimeError('Idle scope animation owner changed')
        found = {}
        owners = (anim.Class, *tuple(anim.Class._superfields()))
        if len(owners) > 64:
            raise RuntimeError('Idle scope inheritance limit')
        for owner in owners:
            for index, prop in enumerate(owner._properties()):
                if index >= 4096:
                    raise RuntimeError('Idle scope property limit')
                if str(prop.Class.Name) != 'StructProperty' or str(prop.Struct.Name) != 'GbxAnimNode_IdleTurns':
                    continue
                name, offset = str(prop.Name), int(prop.Offset_Internal)
                if name not in IDLE_NAMES or not 0 <= offset <= 0x400000:
                    raise RuntimeError('Unreviewed Idle scope layout')
                if name in found and found[name] != offset:
                    raise RuntimeError('Idle scope layouts conflict')
                found[name] = offset
        if set(found) != IDLE_NAMES:
            raise RuntimeError('Idle scope node set differs')
        nodes = tuple((name, c.anim_address + offset) for name, offset in sorted(found.items()))
        for name, address in nodes:
            if c.native.read(address, 8) != struct.pack('<Q', self.table):
                raise RuntimeError('Idle scope vtable differs: ' + name)
        extra = [address for name, address in nodes if name != c.IDLE_NODE_NAME]
        for slot, address in enumerate(extra, 5):
            self.control[slot] = address
        self.scope_nodes = nodes
        c.report.setdefault('idle_scope_bindings', []).append(dict(
            worker=type(self).__name__, nodes=[dict(name=name, address=hex(address)) for name, address in nodes],
            scope='Only five reflected receivers in the bound local animation. Existing free/combat/special-state gates retained.'))
        key = 'idle_root_native_binding' if isinstance(self, NativeIdleRoot) else 'idle_update_native_binding'
        c.report[key]['scope'] = 'Five exact reflected local IdleTurns receivers; original free/combat/special-state enable gates. Scope validated against runtime layouts and reviewed vtable.'

    def validate(self):
        super().validate()
        for name, address in self.scope_nodes:
            if self.capture.native.read(address, 8) != struct.pack('<Q', self.table):
                raise RuntimeError('Idle scope receiver ownership changed: ' + name)

class ScopedIdleRoot(IdleScopeMixin, NativeIdleRoot):
    PREFIX = bytes.fromhex('9c50415249ba1111111111111111493b7208741a493b72287414493b7230740e493b72387408493b72407402eb16f049ff422049833a01750bf049ff4218415a589deb24415a589d80be0c03000001751780be0803000001750eff25000000003333333333333333ff25000000002222222222222222')
    HASH = 'a32a0f080bca52395db5b14b1949d1f69a999ee3b6da09b3469f5577188130f1'

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
        if pe[:4]!=b'PE\0\0' or struct.unpack_from('<H',pe,24)[0]!=0x20b or build!=REVIEWED_BUILD:
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
        if len(self.PROLOGUE)!=18 or len(self.PREFIX)!=118 or hashlib.sha256(self.PREFIX).hexdigest()!=self.HASH:
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
        self.bind_scope()

class ScopedIdleUpdate(IdleScopeMixin, NativeIdleUpdate):
    PREFIX = bytes.fromhex('9c50415249ba1111111111111111493b7a08741a493b7a287414493b7a30740e493b7a387408493b7a407402eb16f049ff422049833a01750bf049ff4218415a589deb24415a589d80b90c03000001751780bf0803000001750eff25000000003333333333333333ff25000000002222222222222222')
    HASH = 'c2a18319bc0f3937e0eef3ab79a8863b5b9876dec99411670021529306b15a44'

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
        if pe[:4]!=b'PE\0\0' or struct.unpack_from('<H',pe,24)[0]!=0x20b or build!=REVIEWED_BUILD:
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
        if len(self.PROLOGUE)!=22 or len(self.PREFIX)!=118 or hashlib.sha256(self.PREFIX).hexdigest()!=self.HASH:
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
        self.bind_scope()

