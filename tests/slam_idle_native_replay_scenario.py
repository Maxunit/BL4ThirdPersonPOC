"""Execute reviewed captured Update and unchanged IdleUpdate prefix on synthetic nodes.

Linux x64 offline only; ms_abi C helpers record selection/update/seek calls.
This verifies native dispatch semantics, not Unreal graph output or animation.
"""
import ctypes as C
import hashlib
import json
import mmap
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import tempfile
import support
from BL4ThirdPersonPOC.omni.native_idle_scope import ScopedIdleUpdate

EXPECTED='6d23c416af99cb4bfda63f2f3f9e96a5f023ef2551412399dda8ecc141ca8dfd'
ROOT=Path(__file__).resolve().parents[1]
CSOURCE=r'''
#include <stdint.h>
#include <string.h>
#define MS __attribute__((ms_abi))
typedef void (MS *Update)(void*,void*);
static unsigned selection, selections, updates, seeks;
static float time_position;
static uintptr_t selected_node;
static void MS select_input(void *node,unsigned input,void *descriptor) {
    selection=input; selections++; selected_node=(uintptr_t)node;
}
static void MS generic_update(void *node,void *context) { updates++; }
static float MS duration(void *node) { return 1.0f; }
static void MS seek(void *node,float position) { seeks++; time_position=position; }
static void MS unexpected(void) { }
static float MS angle(void *value) { return 0.0f; }
uintptr_t address(unsigned index) {
    switch(index) {
      case 0:return (uintptr_t)select_input;
      case 1:return (uintptr_t)generic_update;
      case 2:return (uintptr_t)duration;
      case 3:return (uintptr_t)seek;
      case 4:return (uintptr_t)angle;
      default:return (uintptr_t)unexpected;
    }
}
void run(uintptr_t entry,void *node,void *context) {
    selection=99; selections=updates=seeks=0; time_position=0; selected_node=0;
    ((Update)entry)(node,context);
}
unsigned stat(unsigned index) {
    switch(index) { case 0:return selection; case 1:return selections;
      case 2:return updates; case 3:return seeks; default:return 0; }
}
float seek_position(void) { return time_position; }
uintptr_t last_node(void) { return selected_node; }
'''


def main():
    if platform.system()!='Linux' or platform.machine() not in ('x86_64','AMD64'):
        print(json.dumps(dict(skipped='Linux x64 replay host required')));return
    cc,dis=shutil.which('gcc'),shutil.which('objdump')
    if not cc or not dis:
        print(json.dumps(dict(skipped='gcc and objdump required')));return
    fixture=json.loads((ROOT/'tests/fixtures/slam_idle_update_1.10.2.json').read_text())
    original=bytes.fromhex(fixture['original_code_hex'])
    assert len(original)==982 and hashlib.sha256(original).hexdigest()==EXPECTED
    with tempfile.TemporaryDirectory() as directory:
        directory=Path(directory);src=directory/'helpers.c';so=directory/'helpers.so'
        src.write_text(CSOURCE)
        subprocess.run([cc,'-shared','-fPIC','-O2','-o',str(so),str(src)],check=True,capture_output=True)
        lib=C.CDLL(str(so));lib.address.argtypes=[C.c_uint];lib.address.restype=C.c_size_t
        lib.run.argtypes=[C.c_size_t,C.c_void_p,C.c_void_p];lib.stat.argtypes=[C.c_uint]
        lib.stat.restype=C.c_uint;lib.seek_position.restype=C.c_float;lib.last_node.restype=C.c_size_t
        raw=directory/'original.bin';raw.write_bytes(original)
        out=subprocess.run([dis,'-D','-b','binary','-m','i386:x86-64','-M','intel',
                            '--insn-width=16','--adjust-vma='+fixture['entry_rva'],str(raw)],
                           check=True,capture_output=True,text=True).stdout
        image=mmap.mmap(-1,0x8000,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
        base=C.addressof(C.c_ubyte.from_buffer(image));entry=int(fixture['entry_rva'],16)
        image[:len(original)]=original
        globals={0xc6ff940:struct.pack('<Q',0),0xc948c29:b'\0',
                 0x9976e78:struct.pack('<f',180.),0x9c24624:struct.pack('<f',-180.),
                 0x9c1f31c:struct.pack('<f',360.),0x9e17c9c:struct.pack('<f',-360.),
                 0x9c1f318:struct.pack('<f',90.),0x992a9a0:struct.pack('<4I',*[0x7fffffff]*4),
                 0x992a170:struct.pack('<2d',-1.,1.),0x992a160:struct.pack('<2d',1.,-1.)}
        global_addresses={}
        for index,(address,data) in enumerate(globals.items()):
            offset=0x3000+index*32;image[offset:offset+len(data)]=data;global_addresses[address]=base+offset
        external_indices={0x3213ac:0,0x4907242:1,0x47bf7fa:4,0x56c405c:5,0x4d837c0:5}
        external_addresses={}
        for index,(address,helper) in enumerate(external_indices.items()):
            offset=0x1800+index*32
            image[offset:offset+14]=bytes.fromhex('ff2500000000')+struct.pack('<Q',lib.address(helper))
            external_addresses[address]=base+offset
        relocations=0
        for line in out.splitlines():
            match=re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)',line)
            if not match:continue
            address=int(match[1],16);data=bytes.fromhex(match[2]);text=match[3]
            offset=address-entry
            if '[rip+' in text or '[rip-' in text:
                target=int(re.search(r'#\s*0x([0-9a-f]+)',text)[1],16)
                new=global_addresses[target]
                image[offset+len(data)-4:offset+len(data)]=struct.pack('<i',new-(base+offset+len(data)))
                relocations+=1
            elif data[0]==0xe8:
                target=int(re.search(r'call\s+0x([0-9a-f]+)',text)[1],16)
                if not entry<=target<entry+len(original):
                    new=external_addresses[target]
                    image[offset+1:offset+5]=struct.pack('<i',new-(base+offset+5));relocations+=1
        assert relocations==32,relocations
        node=C.create_string_buffer(0x400);other=C.create_string_buffer(0x400);context=C.create_string_buffer(0x80)
        owned=C.addressof(node);foreign=C.addressof(other)
        control=(C.c_uint64*9)();control[1]=owned
        table=(C.c_size_t*64)();table[0x108//8]=lib.address(2);table[0x1a8//8]=lib.address(3)
        for memory in (node,other):
            memory[0x308]=1;memory[0x30c]=1;memory[0x314]=1
            for offset in (0x130,0x1b8):struct.pack_into('<Q',memory,offset,C.addressof(table))
        prefix=ScopedIdleUpdate.PREFIX
        assert hashlib.sha256(prefix).hexdigest()==ScopedIdleUpdate.HASH
        prefix=(prefix.replace(b'\x11'*8,struct.pack('<Q',C.addressof(control)))
            .replace(b'\x22'*8,struct.pack('<Q',base+0x186e899-entry))
            .replace(b'\x33'*8,struct.pack('<Q',base+0x186e94a-entry)))
        image[0x1000:0x1000+len(prefix)]=prefix
        offset=0x186e883-entry
        patch=bytes.fromhex('ff2500000000')+struct.pack('<Q',base+0x1000)
        image[offset:offset+len(ScopedIdleUpdate.PROLOGUE)]=patch+b'\x90'*(len(ScopedIdleUpdate.PROLOGUE)-len(patch))
        rows=[]
        cases=[(0,owned,177.,2),(0,owned,-177.,1),(1,owned,177.,0),(1,owned,-177.,0),
               (1,foreign,177.,2),(1,foreign,-177.,1)]
        for gate,address,yaw,wanted in cases:
            control[0]=gate
            memory=node if address==owned else other
            struct.pack_into('<2f',memory,0x300,0.,yaw)
            struct.pack_into('<f',memory,0x310,yaw)
            lib.run(base,address,C.addressof(context))
            result=dict(gate=gate,owned=address==owned,yaw=yaw,input=lib.stat(0),
                        selections=lib.stat(1),generic_updates=lib.stat(2),seeks=lib.stat(3))
            assert result['input']==wanted,result
            assert result['selections']==result['generic_updates']==1,result
            assert result['seeks']==(0 if wanted==0 else 1),result
            assert lib.last_node()==address,result
            rows.append(result)
        # Ordinary disabled/inactive native node chooses its original Idle fallback.
        control[0]=0;node[0x308]=0;lib.run(base,owned,C.addressof(context))
        assert lib.stat(0)==0 and lib.stat(2)==1
        print(json.dumps(dict(cases=rows,inactive_idle=True,owned_bypasses=int(control[3]),
                              dispatches=int(control[4]),relocations=relocations,
                              note='Synthetic private fields/constants and helper implementations; no rendered-pose proof.')))

if __name__=='__main__':main()
