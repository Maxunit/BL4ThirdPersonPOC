"""Isolated Linux x64 executable-template check; no game process access."""
import ctypes, mmap, struct
from pathlib import Path
root=Path(__file__).resolve().parent
count=0
for kind in ('root','update'):
 template=(root/f'idle_scope_{kind}.bin').read_bytes()
 for enabled in (0,1):
  for receiver in range(6):
   for first,second in ((0,0),(0,1),(1,0),(1,1)):
    nodes=[ctypes.create_string_buffer(0x320) for _ in range(6)]
    addresses=[ctypes.addressof(n) for n in nodes]
    ctl=(ctypes.c_uint64*9)();ctl[0]=enabled;ctl[1]=addresses[0]
    for i,a in enumerate(addresses[1:5],5):ctl[i]=a
    memory=mmap.mmap(-1,4096,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
    buf=(ctypes.c_char*4096).from_buffer(memory);base=ctypes.addressof(buf)
    # Jump destinations identify which original branch was selected.
    memory[512:518]=bytes.fromhex('b802000000c3');memory[528:534]=bytes.fromhex('b803000000c3')
    code=template.replace(b'\x11'*8,struct.pack('<Q',ctypes.addressof(ctl))).replace(b'\x22'*8,struct.pack('<Q',base+512)).replace(b'\x33'*8,struct.pack('<Q',base+528))
    memory[:len(code)]=code
    wrapper=(b'\x56\x48\x89\xfe' if kind=='root' else b'')+b'\x48\x89\xf9\x48\xb8'+struct.pack('<Q',base)+b'\xff\xd0'+(b'\x5e' if kind=='root' else b'')+b'\xc3'
    memory[640:640+len(wrapper)]=wrapper
    n=nodes[receiver];n[0x30c]=bytes([first]);n[0x308]=bytes([second])
    value=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p)(base+640)(addresses[receiver])
    matched=receiver<5
    expected=2 if enabled and matched else (3 if (first==1 and second==1) else 2)
    assert value==expected,(kind,enabled,receiver,first,second,value,expected)
    assert ctl[3]==int(bool(enabled and matched))
    assert ctl[4]==int(matched)
    del buf;memory.close();count+=1
print(f'{count} native cases passed: both templates, five exact receivers, unowned receiver, enabled/disabled gates and all original branch flags.')
