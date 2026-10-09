import ctypes as C, mmap, struct, math
from pathlib import Path
lib=C.CDLL(str(Path(__file__).with_name('native_fixture.so').resolve()))
lib.run_stub.argtypes=[C.c_void_p,C.c_void_p,C.c_void_p]
libc=C.CDLL(None);teb=(C.c_ubyte*128)();C.c_uint64.from_buffer(teb,0x48).value=42
old=C.c_ulong();assert libc.syscall(158,0x1004,C.byref(old))==0
assert libc.syscall(158,0x1001,C.c_ulong(C.addressof(teb)))==0
try:
 template=(Path(__file__).parent.parent / 'live_input_extension.bin').read_bytes()
 control=(C.c_uint64*64)();movement=(C.c_ubyte*0x5000)();cfg=(C.c_ubyte*256)();records=(C.c_ubyte*(1024*128))()
 pending=(C.c_double*3)();last=(C.c_double*3)();vector=(C.c_double*3)(7,8,9)
 control[0]=1;control[1]=C.addressof(movement);control[2]=42;control[4]=C.addressof(records);control[7]=1;control[12]=4;control[14]=C.addressof(cfg)
 control[32]=C.addressof(pending);control[33]=C.addressof(last);control[34]=struct.unpack('<Q',struct.pack('<d',.04))[0]
 C.c_uint64.from_buffer(movement,0x4430).value=C.addressof(cfg);movement[0x1100]=3;movement[0x4458]=1
 angles=(0,-90,180,90)
 for i,a in enumerate(angles):
  raw=struct.unpack('<I',struct.pack('<f',a))[0];C.c_uint32.from_buffer(cfg,144+i*4).value=raw;control[40+i*4]=raw
  control[41+i*4]=struct.unpack('<Q',struct.pack('<d',math.cos(math.radians(a))))[0]
  control[42+i*4]=struct.unpack('<Q',struct.pack('<d',math.sin(math.radians(a))))[0]
 page=mmap.mmap(-1,8192,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC);addr=C.addressof(C.c_char.from_buffer(page));page[6000]=0xc3
 code=template.replace(b'\x11'*8,struct.pack('<Q',C.addressof(control))).replace(b'\x22'*8,struct.pack('<Q',addr+6000)).replace(b'\x33'*8,struct.pack('<Q',C.cast(lib.fixture_return,C.c_void_p).value));page[:len(code)]=code
 total=0
 for yaw in range(-180,180,15):
  for enum,a in enumerate(angles):
   for source in ('pending','last'):
    pending[:]=[0,0,0];last[:]=[0,0,0];target=[math.cos(math.radians(yaw)),math.sin(math.radians(yaw)),0];(pending if source=='pending' else last)[:]=target
    vector[:]=[7,8,9];control[3]=0;control[8]=0;movement[0x4448]=enum
    lib.run_stub(addr,C.addressof(movement),C.addressof(vector))
    assert control[8]==1,(yaw,enum,source,list(vector))
    actual=[math.cos(math.radians(a))*vector[0]-math.sin(math.radians(a))*vector[1],math.sin(math.radians(a))*vector[0]+math.cos(math.radians(a))*vector[1]]
    assert max(abs(x-y) for x,y in zip(actual,target))<1e-12
    assert control[39]==(1 if source=='pending' else 2)
    assert struct.unpack_from('<Q',records,88)[0]==1
    pending[:]=[1,0,0];vector[:]=[7,8,9]
    lib.run_stub(addr,C.addressof(movement),C.addressof(vector));assert list(vector)==[7,8,9] and control[8]==1
    total+=1
 for bad in (0,float('nan'),float('inf'),1000):
  pending[:]=[bad,bad,0];last[:]=[0,0,0];control[3]=control[8]=0;vector[:]=[7,8,9]
  lib.run_stub(addr,C.addressof(movement),C.addressof(vector));assert list(vector)==[7,8,9] and control[8]==0
 for gate in ('mode','wish','owner','thread','config','phase','capacity'):
  pending[:]=[1,1,0];vector[:]=[7,8,9];control[3]=control[8]=0;movement[0x1100]=3;movement[0x4458]=1;control[1]=C.addressof(movement);control[2]=42;control[14]=C.addressof(cfg);control[12]=4
  if gate=='mode':movement[0x1100]=1
  if gate=='wish':movement[0x4458]=0
  if gate=='owner':control[1]+=8
  if gate=='thread':control[2]=43
  if gate=='config':control[14]+=8
  if gate=='phase':control[12]=0
  if gate=='capacity':control[3]=1024
  lib.run_stub(addr,C.addressof(movement),C.addressof(vector));assert list(vector)==[7,8,9] and control[8]==0,gate
 print(total,'native direction/enum/source cases passed; one-shot, zero/nonfinite inputs and 7 gates passed')
finally:
 assert libc.syscall(158,0x1001,old)==0
