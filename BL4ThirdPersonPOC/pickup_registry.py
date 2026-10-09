"""Validated pickup discovery, weak references and selection continuity.

The game-thread item-card updater owns this subsystem. No extra SDK callbacks,
timers or global binding replacements are installed. The slot-108 entry records
numeric hints; only SDK-resolved objects are read and retained as WeakPointers.
A bounded MPSC ring claims each free slot before writing; the sole consumer
acknowledges a complete immutable copy. Occupied slots are never overwritten.
Overflow or identity uncertainty disables discovery and uses the original scan.
Native pages/control/ring remain pinned after verified owned-byte restoration.
"""
import ctypes
import struct
from .build_gate import REVIEWED_BUILD
import unrealsdk

from time import monotonic, perf_counter_ns

from unrealsdk.unreal import WeakPointer

EXPECTED = REVIEWED_BUILD

TARGET_RVA = 0xE1621E

VTABLE_RVA = 0xB30FE10

ORIGINAL = bytes.fromhex('415741564154565755534883ec50')

CAPACITY = 4096

STRIDE = 80

class Control(ctypes.Structure):
    _fields_ = [('enabled',ctypes.c_uint64), ('epoch',ctypes.c_uint64), ('overflow',ctypes.c_uint64)]

def image(read, base):
    dos = read(base, 64)
    if dos[:2] != b'MZ':
        raise RuntimeError('DOS header mismatch')
    off = struct.unpack_from('<I', dos, 60)[0]
    if not 64 <= off <= 1048576:
        raise RuntimeError('PE offset outside bounds')
    pe = read(base + off, 24)
    if pe[:4] != b'PE\x00\x00':
        raise RuntimeError('PE signature mismatch')
    machine, sections, timestamp = struct.unpack_from('<HHI', pe, 4)
    optsize = struct.unpack_from('<H', pe, 20)[0]
    if not 1 <= sections <= 96 or not 64 <= optsize <= 4096:
        raise RuntimeError('PE layout outside bounds')
    opt = read(base + off + 24, optsize)
    if struct.unpack_from('<H', opt)[0] != 523:
        raise RuntimeError('PE32+ required')
    size = struct.unpack_from('<I', opt, 56)[0]
    if (timestamp, size, machine) != EXPECTED:
        raise RuntimeError('Game build mismatch; native inventory refused')
    data = read(base + off + 24 + optsize, sections * 40)
    executable = []
    for i in range(sections):
        vsize, rva, raw = struct.unpack_from('<III', data, i * 40 + 8)
        flags = struct.unpack_from('<I', data, i * 40 + 36)[0]
        span = max(vsize, raw)
        if flags & 536870912:
            if not span or rva + span > size:
                raise RuntimeError('Executable section outside image')
            executable.append((base + rva, base + rva + span))
    if not executable:
        raise RuntimeError('No executable image sections')
    return (size, executable)

CHUNKS_RVA = 0xC95C7C8

COUNT_RVA = 0xC95C7DC

ANCHOR_RVA = 0xE1635C

ANCHOR = bytes.fromhex('448b7e0c44393d7564b40b0f8ea7030000410fb7c7488b0d5064b40b4489fac1ea104c8d244041c1e4034c0324d1458b7424104585f60f84000300004885db0f')

class ObjectLifetimeRejected(RuntimeError):
    """Stable table entry for an SDK object carries our rejected lifetime flags.

    This is distinct from an unverified address, changed identity or failed read.
    It only permits retiring the SAME already-validated registry lifetime.
    """
    def __init__(self, address, index, serial, flags):
        self.address=address;self.index=index;self.serial=serial;self.flags=flags
        super().__init__('Stable rejected lifetime: address='+hex(address)+
            ' index='+str(index)+' serial='+str(serial)+' item_flags='+hex(flags))

def native_identity(read, base, addr, expected_index=None):
    count=struct.unpack('<i',read(base+COUNT_RVA,4))[0]
    chunks=struct.unpack('<Q',read(base+CHUNKS_RVA,8))[0]
    if not 0<count<=0x1000000:
        raise RuntimeError('Candidate table count outside bounds')
    header=read(addr,40)
    index=struct.unpack_from('<i',header,12)[0]
    if not 0<=index<count or (expected_index is not None and index!=expected_index):
        raise RuntimeError('Object index mismatch/outside bounds')
    chunk=struct.unpack('<Q',read(chunks+(index>>16)*8,8))[0]
    item_addr=chunk+(index&65535)*24
    item=read(item_addr,24)
    ptr=struct.unpack_from('<Q',item)[0]
    flags=struct.unpack_from('<I',item,8)[0]
    serial=struct.unpack_from('<i',item,16)[0]
    if ptr!=addr or serial<=0:
        raise RuntimeError('Object table identity unavailable/invalid: '
            'address='+hex(addr)+' index='+str(index)+' item_pointer='+hex(ptr)+
            ' serial='+str(serial)+' item_flags='+hex(flags))
    if read(addr,40)!=header or read(item_addr,24)!=item:
        raise RuntimeError('Object identity changed during read')
    if flags&0x10200000:
        raise ObjectLifetimeRejected(addr,index,serial,flags)
    return (index,serial,header)

def candidate_name(raw_index, number, known_index, known_name):
    if raw_index!=known_index:
        raise RuntimeError('Unknown native basename; no name-pool decoder installed')
    return known_name if number==0 else known_name+'_'+str(number-1)

def build_stub(buffer_address, control_address, trampoline, base):
    code=bytes.fromhex('9c50415241534150415149ba444444443333333349833a000f84e000000049bb2222222211111111b801000000f0490fc1035025ff0f0000486bc0504d8d5c030831c049c7c0fffffffff04d0fb1030f85a000000049c743380000000049c743400000000049c743480000000049894b08488b4110498943108b410c49894318498b420849894320488b411849894328488b412049894330448b410c49b98888888877777777453b01734149b9aaaaaaaa999999994d8b094d85c9742f41c1e8104f8b0cc14d85c97422440fb7410c4d6bc0184f8d0c014939097510418b411049894338418b4108498943405848ffc0498703eb095849c742100100000041594158415b415a589dff25000000006666666655555555')
    for marker,address in ((0x1111111122222222,buffer_address),
                           (0x3333333344444444,control_address),
                           (0x5555555566666666,trampoline),
                           (0x7777777788888888,base+COUNT_RVA),
                           (0x99999999AAAAAAAA,base+CHUNKS_RVA)):
        raw=struct.pack('<Q',marker)
        if code.count(raw)!=1:
            raise RuntimeError('Native stub relocation marker mismatch')
        code=code.replace(raw,struct.pack('<Q',address))
    return code

def error(s,phase,exc):
    s['error_count']+=1
    if len(s['errors'])<24:
        s['errors'].append(phase+': '+type(exc).__name__+': '+str(exc))

def actor_key(mod, actor):
    ref=WeakPointer(actor)
    live=ref()
    if live is None:
        raise RuntimeError('Baseline object expired')
    addr=int(live._get_address())
    path=str(live._path_name())
    cls=int(live.Class._get_address())
    index=struct.unpack('<I',mod._native_read(addr+0xC,4))[0]
    hidden=bool(live.bHidden)
    after=ref()
    if after is None or int(after._get_address())!=addr:
        raise RuntimeError('Baseline identity changed')
    return (addr,index,cls),path,hidden

def seed_reference(mod,s,actor):
    ref=WeakPointer(actor); live=ref()
    if live is None:
        raise RuntimeError('Seed pickup expired')
    addr=int(live._get_address())
    token=native_identity(mod._native_read,s['base'],addr,int(live.InternalIndex))
    path=str(live._path_name()); cls=int(live.Class._get_address())
    outer=live.Outer
    if outer is not None:
        outer_ref=WeakPointer(outer); outer_live=outer_ref()
        if outer_live is None:
            raise RuntimeError('Seed Outer expired')
        oa=int(outer_live._get_address())
        ot=native_identity(mod._native_read,s['base'],oa,int(outer_live.InternalIndex))
        s['outer_cache'][oa]={'ref':outer_ref,'path':str(outer_live._path_name()),
                             'index':ot[0],'serial':ot[1]}
    after=ref()
    if after is None or int(after._get_address())!=addr:
        raise RuntimeError('Seed pickup expired during validation')
    if native_identity(mod._native_read,s['base'],addr)!=token:
        raise RuntimeError('Seed pickup identity changed during validation')
    if addr not in s['registry'] and len(s['registry'])>=8192:
        raise RuntimeError('Pickup reference capacity exceeded')
    s['registry'][addr]={'ref':ref,'index':token[0],'serial':token[1],'class':cls,
                         'path':path,'seed':True}

def seed_runtime_outer(mod,s):
    get_runtime=getattr(mod,'_get_runtime',None)
    if not callable(get_runtime):
        return False
    _,pawn,_=get_runtime()
    current=pawn
    seen=set()
    for _ in range(12):
        if current is None:
            return False
        ref=WeakPointer(current); live=ref()
        if live is None:
            return False
        addr=int(live._get_address())
        if addr in seen:
            raise RuntimeError('Player Outer chain contains a cycle')
        seen.add(addr)
        if str(live.Class._path_name())=='/Script/Engine.Level':
            token=native_identity(mod._native_read,s['base'],addr,int(live.InternalIndex))
            path=str(live._path_name())
            after=ref()
            if (after is None or int(after._get_address())!=addr
                    or native_identity(mod._native_read,s['base'],addr)!=token):
                raise RuntimeError('Player Level identity changed during validation')
            s['outer_cache'][addr]={'ref':ref,'path':path,'index':token[0],'serial':token[1]}
            s['runtime_outer_prefixes']=[{'path':path,'index':token[0],'serial':token[1]}]
            return True
        current=live.Outer
    raise RuntimeError('Player Outer chain exceeded bounded depth')

def seed_baseline(mod,s,actors):
    for actor in actors:
        path=None
        try:
            key,path,hidden=actor_key(mod,actor)
            if 'Default__' in path:
                continue
            seed_reference(mod,s,actor)
            s['seed'].add(key)
        except Exception as exc:
            s['seed_rejected_count']+=1
            if len(s['seed_rejections'])<32:
                s['seed_rejections'].append({'path':path,
                    'reason':type(exc).__name__+': '+str(exc)})
    if len(s['registry'])>=8192 or len(s['outer_cache'])>1024:
        raise RuntimeError('Pickup seed capacity exceeded')
    if not s['outer_cache']:
        seed_runtime_outer(mod,s)
    if not s['outer_cache']:
        raise RuntimeError('No valid Level Outer prefix from pickups or player; native hook not installed. '
            'Seed rejections='+str(s['seed_rejected_count'])+
            ' first='+str(s['seed_rejections'][:1]))

def resolve_record(mod,s,r):
    addr=int(r['address'],16); cls=int(r['class_address'],16)
    name_raw=r['name_raw']; name_index=name_raw&0xffffffff; number=name_raw>>32
    if name_index!=s['known_name_index']:
        r['status']='unsupported_basename'; return True
    outer=s['outer_cache'].get(int(r['outer_address'],16))
    if outer is None:
        r['status']='unknown_outer'; return True
    outer_live=outer['ref']()
    if outer_live is None:
        r['status']='expired_outer'; return True
    oa=int(outer_live._get_address())
    ot=native_identity(mod._native_read,s['base'],oa,outer['index'])
    if ot[1]!=outer['serial']:
        r['status']='changed_outer_serial'; return True
    candidate=outer['path']+'.'+candidate_name(name_index,number,s['known_name_index'],s['known_name'])
    r['candidate_path']=candidate
    stamp=perf_counter_ns()
    try:
        found=mod.find_object('InventoryPickup',candidate)
    except ValueError:
        r['status']='lookup_pending'; return False
    finally:
        elapsed=perf_counter_ns()-stamp
        s['lookup_calls']+=1;s['lookup_total_ns']+=elapsed
        s['lookup_max_ns']=max(s['lookup_max_ns'],elapsed)
    if found is None:
        r['status']='lookup_pending'; return False
    ref=WeakPointer(found); live=ref()
    if live is None:
        r['status']='lookup_expired'; return True
    # Only read an SDK-resolved object, never dereference a captured actor pointer.
    if (int(live._get_address())!=addr or int(live.InternalIndex)!=r['object_index']
            or int(live.Class._get_address())!=cls):
        r['status']='lookup_identity_mismatch'; return True
    token=native_identity(mod._native_read,s['base'],addr,r['object_index'])
    if (struct.unpack_from('<Q',token[2],24)[0]!=name_raw
            or struct.unpack_from('<Q',token[2],32)[0]!=oa):
        r['status']='lookup_name_or_outer_mismatch'; return True
    if r['entry_serial'] and token[1]!=r['entry_serial']:
        r['status']='entry_serial_mismatch'; return True
    if str(live._path_name())!=candidate:
        r['status']='lookup_path_mismatch'; return True
    after=ref(); outer_after=outer['ref']()
    if (after is None or outer_after is None or int(after._get_address())!=addr
            or int(outer_after._get_address())!=oa
            or native_identity(mod._native_read,s['base'],addr)!=token
            or native_identity(mod._native_read,s['base'],oa)!=ot):
        r['status']='changed_during_resolution'; return True
    r['status']='resolved';r['resolved_ns']=perf_counter_ns()-s['started_ns']
    r['resolved_epoch']=int(s['hook']['control'].epoch)
    r['resolved_serial']=token[1]
    r['entry_serial_verified']=bool(r['entry_serial'])
    prior=s['registry'].get(addr)
    if prior is not None and prior['serial']!=token[1]:
        s['address_replacements']+=1
    if addr not in s['registry'] and len(s['registry'])>=8192:
        raise RuntimeError('Pickup reference capacity exceeded')
    s['registry'][addr]={'ref':ref,'index':token[0],'serial':token[1],'class':cls,
                         'path':candidate,'seed':False}
    return True

def drain(mod,s):
    hook=s['hook'];buffer=ctypes.addressof(hook['buffer'])
    reserved=struct.unpack('<Q',mod._native_read(buffer,8))[0]
    s['native_reserved']=reserved
    if int(hook['control'].overflow) or reserved-s['read_cursor']>CAPACITY or reserved>=2**63:
        s['overflow']=1
        return
    end=min(reserved,s['read_cursor']+128)
    while s['read_cursor']<end:
        ticket=s['read_cursor'];offset=8+(ticket&(CAPACITY-1))*STRIDE
        raw=mod._native_read(buffer+offset,STRIDE)
        sequence,addr,cls,obj_index,epoch,name_raw,outer,serial,flags,_=struct.unpack('<10Q',raw)
        if sequence!=ticket+1:
            s['unpublished_at_last_drain']=end-ticket
            break
        if struct.unpack('<Q',mod._native_read(buffer+offset,8))[0]!=sequence:
            raise RuntimeError('Claimed ring slot changed during copy')
        # A single aligned uint64 store releases our own allocation's slot.
        # Producers cannot touch a nonzero sequence; copy before acknowledging.
        ctypes.c_uint64.from_buffer(hook['buffer'],offset).value=0
        s['unpublished_at_last_drain']=0;s['read_cursor']+=1
        s['native_records_total']=s.get('native_records_total',0)+1
        r={'sequence':sequence,'address':hex(addr),'object_index':obj_index,
           'class_address':hex(cls),'epoch':epoch,'name_raw':name_raw,
           'outer_address':hex(outer),'entry_serial':serial,'entry_flags':flags,
           'status':'pending','observed_ns':perf_counter_ns()-s['started_ns']}
        if len(s['records'])<128:s['records'].append(r)
        if epoch<s.get('resume_epoch_floor',0):
            r['status']='discarded_old_epoch'
            s['native_discarded_reservations']+=1
            continue
        if len(s['pending'])>=512:
            fallback(s,'pending_resolution_capacity');return
        s['pending'].append(r)


def metric(s,name,elapsed):
    row=s['metrics'].setdefault(name,{'calls':0,'total_ns':0,'max_ns':0})
    row['calls']+=1;row['total_ns']+=elapsed;row['max_ns']=max(row['max_ns'],elapsed)

RECOVERABLE_CONTEXT_REASONS=frozenset(('local_level_unavailable','local_level_expired',
    'local_level_changed','local_level_identity_changed'))

def transition(s,event,**values):
    rows=s.setdefault('context_events',[])
    if len(rows)<128:
        rows.append({'event':event,'elapsed_ns':perf_counter_ns()-s['started_ns'],
            'update':s.get('update_calls',0),**values})
    else:
        s['context_events_dropped']=s.get('context_events_dropped',0)+1

def fallback(s,reason):
    if s.get('fallback_reason') is not None:
        if not s.get('context_paused') or reason in RECOVERABLE_CONTEXT_REASONS:
            return
    s['fallback_reason']=reason
    hook=s.get('hook')
    if hook:
        hook['control'].enabled=0
    recoverable=reason in RECOVERABLE_CONTEXT_REASONS
    s['context_paused']=recoverable
    s['resume_candidate']=None;s['resume_stable_updates']=0
    if len(s['fallback_events'])<32:
        s['fallback_events'].append({'reason':reason,'recoverable':recoverable,
            'update':s.get('update_calls',0),'elapsed_ns':perf_counter_ns()-s['started_ns']})
    continuity=s.get('continuity')
    if isinstance(continuity,dict):
        continuity['active']=False;continuity['pending']=None
    if recoverable:
        dropped=len(s['registry'])
        s['context_discarded_references']=s.get('context_discarded_references',0)+dropped
        s['registry'].clear();s['outer_cache'].clear();s['native_first'].clear()
        for record in s['pending']:
            record['status']='discarded_context_transition'
        s['pending'].clear()
        transition(s,'paused',reason=reason,discarded_references=dropped)
    else:
        transition(s,'fallback_latched',reason=reason)
    unrealsdk.logging.warning('[BL4ThirdPersonPOC.PickupRegistry] '+('PAUSED' if recoverable else 'FALLBACK')+
        ' original discovery: '+reason)

def runtime_context(mod,s):
    pc,pawn,camera=mod._get_runtime()
    if pc is None or pawn is None or camera is None:
        return None
    current=pawn;seen=set()
    for _ in range(12):
        ref=WeakPointer(current);live=ref()
        if live is None:
            return None
        addr=int(live._get_address())
        if addr in seen:
            raise RuntimeError('Player Outer cycle')
        seen.add(addr)
        if str(live.Class._path_name())=='/Script/Engine.Level':
            try:
                token=native_identity(mod._native_read,s['base'],addr,int(live.InternalIndex))
            except ObjectLifetimeRejected:
                return None
            path=str(live._path_name());after=ref()
            if after is None or int(after._get_address())!=addr:
                return None
            try:
                after_token=native_identity(mod._native_read,s['base'],addr,token[0])
            except ObjectLifetimeRejected:
                return None
            if after_token!=token:
                return None
            return {'key':(addr,token[0],token[1],path),
                'row':{'ref':ref,'index':token[0],'serial':token[1],'path':path}}
        current=live.Outer
        if current is None:
            return None
    raise RuntimeError('Player Outer chain exceeded bounded depth')

def check_context(mod,s):
    hook=s['hook']
    if mod._native_read(hook['target'],len(ORIGINAL))!=hook['patch']:
        fallback(s,'native_detour_ownership_changed');return False
    current=runtime_context(mod,s)
    if current is None:
        fallback(s,'local_level_unavailable');return False
    key=current['key']
    if key[0]!=s['level_address']:
        fallback(s,'local_level_changed');return False
    if key[2]!=s['level_serial'] or key[3]!=s['level_path']:
        fallback(s,'local_level_identity_changed');return False
    return True

def resume_ready(mod):
    state=mod._item_card_state
    return (mod._third_person_enabled and not mod._native_fault and isinstance(state,dict)
        and state.get('ready') and state.get('active') and mod._item_card_should_override())

def try_resume(mod,s,current):
    key=current['key']
    if key!=s.get('resume_candidate'):
        s['resume_candidate']=key;s['resume_stable_updates']=1
        transition(s,'candidate',level_address=hex(key[0]),level_serial=key[2],level_path=key[3])
        return
    s['resume_stable_updates']+=1
    if s['resume_stable_updates']<3:
        return
    # Each stable candidate may trigger one bootstrap only; errors latch the
    # original discovery instead of retrying a global scan each update.
    s['resume_attempts']+=1
    stamp=perf_counter_ns()
    try:
        hook=s['hook']
        if mod._native_read(hook['target'],len(ORIGINAL))!=hook['patch']:
            raise RuntimeError('Native detour ownership changed before resume')
        image(mod._native_read,s['base'])
        if mod._native_read(s['base']+ANCHOR_RVA,len(ANCHOR))!=ANCHOR:
            raise RuntimeError('Weak-object anchor changed before resume')
        fresh={'base':s['base'],'registry':{},'outer_cache':{key[0]:current['row']},
            'seed':set(),'seed_rejected_count':0,'seed_rejections':[],'runtime_outer_prefixes':[]}
        # Capture before the bootstrap scan so concurrent new pickups cannot
        # fall into a gap between the scan and enabling discovery. They remain
        # numeric hints until the new SDK context and seed have been validated.
        hook['control'].epoch=s['update_calls'];hook['control'].enabled=1
        s['resume_global_calls']+=1
        actors=tuple(s['binding'][0]('InventoryPickup'))
        seed_baseline(mod,fresh,actors)
        del actors
        after=runtime_context(mod,s)
        if after is None or after['key']!=key or not resume_ready(mod):
            raise RuntimeError('Ready context changed during reseed')
        if mod._native_read(hook['target'],len(ORIGINAL))!=hook['patch']:
            raise RuntimeError('Native detour ownership changed during reseed')
        reserved=struct.unpack('<Q',mod._native_read(ctypes.addressof(hook['buffer']),8))[0]
        if int(hook['control'].overflow) or reserved-s['read_cursor']>CAPACITY:
            raise RuntimeError('Native buffer overflow before resume')
        # Keep the read cursor: outstanding slots must still be acknowledged.
        # The epoch floor discards old-context entries after normal consumption.
        s['native_reserved']=reserved
        s['registry']=fresh['registry'];s['outer_cache']=fresh['outer_cache']
        s['seed']=fresh['seed'];s['pending'].clear();s['native_first'].clear()
        s['level_address']=key[0];s['level_serial']=key[2];s['level_path']=key[3]
        s['context_generation']+=1;s['resume_epoch_floor']=s['update_calls']
        s['fallback_reason']=None;s['context_paused']=False
        # Force the existing production refresh once. It rebuilds geometry and
        # its normal native membership snapshot, including reused addresses.
        # Continuity stays disabled here so pre-load selection cannot carry.
        mod._item_card_refresh_pickups(mod._item_card_state,force=True)
        if s['fallback_reason'] is not None or not resume_ready(mod):
            raise RuntimeError('Production item-card refresh not ready after reseed')
        hook['control'].epoch=s['update_calls'];hook['control'].enabled=1
        s['continuity']['pending']=None;s['continuity']['active']=True
        s['resume_successes']+=1
        transition(s,'resumed',generation=s['context_generation'],seed_count=len(fresh['registry']),
            seed_rejected=fresh['seed_rejected_count'],seed_rejections=fresh['seed_rejections'],
            native_floor=reserved,level_address=hex(key[0]),level_serial=key[2],level_path=key[3],
            global_calls_after_resume=s['fallback_global_calls'])
        unrealsdk.logging.warning('[BL4ThirdPersonPOC.PickupRegistry] RESUMED generation='+str(s['context_generation'])+
            ' seed='+str(len(fresh['registry']))+' bootstrap_searches='+str(s['resume_global_calls']))
    except Exception as exc:
        error(s,'resume',exc)
        s['fallback_reason']=None;s['context_paused']=False
        fallback(s,'resume_failed')
    finally:
        elapsed=perf_counter_ns()-stamp
        metric(s,'resume_bootstrap',elapsed)
        profile_stage(mod,'item.registry_bootstrap',elapsed)

def lifecycle_checkpoint(mod,s):
    if s.get('fallback_reason') is not None and not s.get('context_paused'):
        return
    current=runtime_context(mod,s)
    if s.get('context_paused'):
        if current is None or not resume_ready(mod):
            s['resume_candidate']=None;s['resume_stable_updates']=0
            return
        try_resume(mod,s,current)
        return
    if current is None:
        fallback(s,'local_level_unavailable')
    elif current['key'][0]!=s['level_address']:
        fallback(s,'local_level_changed')
    elif current['key'][2]!=s['level_serial'] or current['key'][3]!=s['level_path']:
        fallback(s,'local_level_identity_changed')

def pump(mod,s):
    if s.get('fallback_reason') is not None:
        return
    drain(mod,s)
    if s['overflow']:
        fallback(s,'native_buffer_overflow');return
    work=s['pending'][:32];del s['pending'][:len(work)]
    for r in work:
        if r['epoch']<s.get('resume_epoch_floor',0):
            r['status']='discarded_old_epoch'
            s['native_discarded_reservations']+=1;continue
        r['resolve_attempts']=r.get('resolve_attempts',0)+1
        try:
            complete=resolve_record(mod,s,r)
        except Exception as exc:
            error(s,'resolve_record',exc);r['status']='resolution_error';complete=True
        if not complete:
            if r['resolve_attempts']<8:
                s['pending'].append(r)
            else:
                r['status']='lookup_retry_limit';complete=True
        if complete and r['status']=='resolved':
            s['resolved_records_total']=s.get('resolved_records_total',0)+1
            s['verified_records_total']=s.get('verified_records_total',0)+int(r.get('entry_serial_verified',False))
        if complete and r['status']!='resolved':
            fallback(s,'native_record:'+r['status']);return
        if s['address_replacements']:
            fallback(s,'address_replacement_requires_geometry_reset');return

def retire(s,addr,reason):
    row=s['registry'].pop(addr,None)
    if row is not None:
        s['retired_references']+=1
        if len(s['retirements'])<256:
            s['retirements'].append({'path':row['path'],'serial':row['serial'],'reason':reason,
                'elapsed_ns':perf_counter_ns()-s['started_ns']})

def checked_registry_token(mod,s,addr,row):
    try:
        return native_identity(mod._native_read,s['base'],addr,row['index'])
    except ObjectLifetimeRejected as exc:
        if (exc.address==addr and exc.index==row['index'] and exc.serial==row['serial']):
            retire(s,addr,'lifetime_flags:'+hex(exc.flags))
            return None
        fallback(s,'rejected_lifetime_identity_mismatch')
        return None

def live_reference(mod,s,addr,row):
    live=row['ref']()
    if live is None:
        retire(s,addr,'weak_expired');return None
    if (int(live._get_address())!=addr or int(live.InternalIndex)!=row['index']
            or int(live.Class._get_address())!=row['class']):
        retire(s,addr,'weak_identity_changed');fallback(s,'registry_identity_changed');return None
    token=checked_registry_token(mod,s,addr,row)
    if token is None:
        return None
    if token[1]!=row['serial'] or str(live._path_name())!=row['path']:
        retire(s,addr,'serial_or_path_changed');fallback(s,'registry_serial_or_path_changed');return None
    if bool(live.bHidden) or live.RootPrimitiveComponent is None:
        return None
    after=row['ref']()
    if after is None or int(after._get_address())!=addr:
        retire(s,addr,'weak_expired_after_read');return None
    after_token=checked_registry_token(mod,s,addr,row)
    if after_token is None:
        return None
    if after_token!=token:
        fallback(s,'registry_changed_during_validation');return None
    return live

def registry_snapshot(mod,s):
    actors=[]
    for addr,row in tuple(s['registry'].items()):
        live=live_reference(mod,s,addr,row)
        if s.get('fallback_reason') is not None:
            return None
        if live is not None:
            actors.append(live)
    return tuple(actors)

def observe_find(mod,s,original):
    def observer(*args,**kwargs):
        if not s['active'] or not args or args[0]!='InventoryPickup':
            return original(*args,**kwargs)
        if len(args)!=1 or kwargs:
            fallback(s,'unsupported_pickup_search_arguments')
        if s.get('fallback_reason') is None:
            stamp=perf_counter_ns()
            try:
                if check_context(mod,s):
                    pump(mod,s)
                    if s.get('fallback_reason') is None:
                        result=registry_snapshot(mod,s)
                        if result is not None:
                            s['registry_calls']+=1
                            if len(s['observations'])<256:
                                s['observations'].append({'update':s['update_calls'],
                                    'elapsed_ns':perf_counter_ns()-s['started_ns'],
                                    'returned':len(result),'registry':len(s['registry']),
                                    'pending':len(s['pending']),'native_cursor':s['read_cursor']})
                            else:
                                s['observations_dropped']+=1
                            return result
            except Exception as exc:
                error(s,'registry_search',exc);fallback(s,'registry_search_error')
            finally:
                metric(s,'registry_find',perf_counter_ns()-stamp)
        s['fallback_global_calls']+=1
        stamp=perf_counter_ns()
        try:
            return original(*args,**kwargs)
        finally:
            metric(s,'fallback_find',perf_counter_ns()-stamp)
    return observer

def observe_use(mod,s,original):
    def observer(*args,**kwargs):
        if not s['active']:
            return original(*args,**kwargs)
        if args or kwargs:
            fallback(s,'unsupported_use_arguments')
        if s.get('fallback_reason') is None:
            stamp=perf_counter_ns();s['use_calls']+=1
            try:
                if check_context(mod,s):
                    pump(mod,s)
                    if s.get('fallback_reason') is None:
                        state=mod._item_card_state
                        if not isinstance(state,dict) or not state.get('ready') or not state.get('active'):
                            s['use_misses']+=1;return None
                        addr=int(state['final_hook']['control'].selected_actor)
                        row=s['registry'].get(addr)
                        actor=live_reference(mod,s,addr,row) if row is not None else None
                        if s.get('fallback_reason') is None:
                            if actor is not None and state['pickups'].get(addr)==row['path']:
                                s['use_hits']+=1;return actor
                            s['use_misses']+=1;return None
            except Exception as exc:
                error(s,'registry_use',exc);fallback(s,'registry_use_error')
            finally:
                metric(s,'registry_use',perf_counter_ns()-stamp)
        s['fallback_use_calls']+=1
        return original(*args,**kwargs)
    return observer

def update_checkpoint(mod,s,phase):
    stamp=perf_counter_ns()
    try:
        if phase=='begin':
            lifecycle_checkpoint(mod,s)
        if s.get('fallback_reason') is None:
            pump(mod,s)
    except Exception as exc:
        error(s,'update_checkpoint:'+phase,exc);fallback(s,'update_checkpoint_error')
    finally:
        elapsed=perf_counter_ns()-stamp
        metric(s,'update_checkpoint',elapsed)
        profile_stage(mod,'item.registry_checkpoint',elapsed)

def record(s, result, **values):
    s['counts'][result] = s['counts'].get(result, 0) + 1
    if len(s['events']) < 256:
        s['events'].append({'elapsed_ns': perf_counter_ns() - s['started_ns'],
                            'result': result, **values})
    else:
        s['events_dropped'] += 1

def identity(actor):
    return int(actor._get_address()), str(actor._path_name())

def observe_continuity_refresh(mod, s, original):
    def observer(state, *, force=False):
        s['pending'] = None
        saved = None
        old_hook = state.get('final_hook')
        old_rebuilds = int(state.get('snapshot_rebuilds', 0))
        old_count = len(state.get('pickups', {}))
        if s['active'] and not force and state.get('ready') and state.get('active') and isinstance(old_hook, dict):
            try:
                due = monotonic() - float(state['last_pickup_refresh']) >= mod.ITEM_CARD_PICKUP_REFRESH_INTERVAL
                control = old_hook['control']
                addr = int(control.selected_actor)
                path = state['pickups'].get(addr)
                samples = int(state['pending_samples'])
                if due and int(control.enabled) and addr and path and state['pending_actor'] == addr and samples >= mod.ITEM_CARD_STABLE_SELECTION_SAMPLES:
                    t = perf_counter_ns()
                    actor = mod.find_object('InventoryPickup', path)
                    s['path_resolve_calls'] += 1
                    s['path_resolve_ns'] += perf_counter_ns() - t
                    if actor is not None and identity(actor) == (addr, path) and not bool(actor.bHidden):
                        saved = {'ref': WeakPointer(actor), 'address': addr, 'path': path,
                                 'samples': samples, 'state': state}
            except Exception as exc:
                error(s, 'save_selection', exc)
        result = original(state, force=force)
        if s['active'] and state.get('final_hook') is not old_hook and int(state.get('snapshot_rebuilds', 0)) > old_rebuilds:
            record(s, 'rebuild', old_count=old_count, new_count=len(state['pickups']),
                   previous_selection=saved['address'] if saved else 0)
            if saved is not None:
                saved['hook'] = state.get('final_hook')
                s['pending'] = saved
        return result
    return observer

def observe_continuity_publish(mod, s, original):
    def observer(state, actor, actor_object, geometry, raw_count, eligible_count):
        saved = s['pending']
        s['pending'] = None
        if s['active'] and saved is not None:
            try:
                addr, path = saved['address'], saved['path']
                same = (saved['state'] is state and saved['hook'] is state.get('final_hook')
                        and state.get('ready') and state.get('active')
                        and mod._item_card_state is state and mod._item_card_should_override()
                        and actor == addr and eligible_count > 0
                        and geometry is not None and int(geometry['address']) == addr
                        and state['pickups'].get(addr) == path)
                live = saved['ref']() if same else None
                same = same and live is not None and identity(live) == (addr, path) and not bool(live.bHidden)
                if same:
                    control = state['final_hook']['control']
                    # Keep disabled until the normal publisher enables the new
                    # control. Its candidate was freshly checked in this update.
                    control.selected_actor = addr
                    state['pending_actor'] = addr
                    state['pending_samples'] = saved['samples']
                    record(s, 'preserved', address=addr, path=path, new_count=len(state['pickups']))
                else:
                    record(s, 'rejected', previous=addr, fresh=actor)
            except Exception as exc:
                error(s, 'preserve_selection', exc)
        return original(state, actor, actor_object, geometry, raw_count, eligible_count)
    return observer

def install(mod):
    base=int(mod._kernel32.GetModuleHandleW(None) or 0)
    if not base:
        raise RuntimeError('Main module unavailable')
    size,ranges=image(mod._native_read,base)
    if not any(a<=base+TARGET_RVA and base+TARGET_RVA+len(ORIGINAL)<=b for a,b in ranges):
        raise RuntimeError('Candidate outside executable image')
    cls=unrealsdk.find_class('InventoryPickup');ref=WeakPointer(cls.ClassDefaultObject)
    cdo=ref()
    if cdo is None:
        raise RuntimeError('Pickup CDO unavailable')
    addr=int(cdo._get_address())
    vt=struct.unpack('<Q',mod._native_read(addr,8))[0]
    if vt!=base+VTABLE_RVA or struct.unpack('<Q',mod._native_read(vt+108*8,8))[0]!=base+TARGET_RVA:
        raise RuntimeError('Pickup slot-108 binding changed')
    if ref() is None or mod._native_read(base+TARGET_RVA,len(ORIGINAL))!=ORIGINAL:
        raise RuntimeError('Pickup entry changed or already owned')
    if mod._native_read(base+ANCHOR_RVA,len(ANCHOR))!=ANCHOR:
        raise RuntimeError('Reviewed weak-object lookup anchor changed')
    cls_ref=WeakPointer(cls); cls_live=cls_ref()
    if cls_live is None:
        raise RuntimeError('Pickup class lifetime unavailable')
    class_token=native_identity(mod._native_read,base,int(cls_live._get_address()),int(cls_live.InternalIndex))
    known_index,known_number=struct.unpack_from('<II',class_token[2],24)
    if known_number!=0 or str(cls_live.Name)!='InventoryPickup':
        raise RuntimeError('Pickup basename anchor differs')

    for name in ('find_all','_update_item_card_fusion','_get_item_card_selected_pickup',
                 '_item_card_refresh_pickups','_item_card_publish_selection','_item_card_should_override'):
        if not callable(getattr(mod,name,None)):
            raise RuntimeError('Production interface missing: '+name)
    s={'registry_revision':2,'base':base,'registry':{},'outer_cache':{},'pending':[],
       'runtime_outer_prefixes':[],'seed_rejected_count':0,'seed_rejections':[],
       'known_name_index':known_index,'known_name':'InventoryPickup',
       'retired_references':0,'retirements':[],'address_replacements':0,
       'lookup_calls':0,'lookup_total_ns':0,'lookup_max_ns':0,
       'version':mod.MOD_VERSION,'active':True,'started_ns':perf_counter_ns(),'hook':None,'binding':None,
       'seed':set(),'native_first':{},'records':[],'read_cursor':0,
       'errors':[],'error_count':0,'native_reserved':0,'overflow':0,'unpublished_at_last_drain':0,
       'native_restored':False,'fallback_reason':None,'fallback_events':[],
       'metrics':{},'registry_calls':0,'use_calls':0,'use_hits':0,'use_misses':0,
       'fallback_global_calls':0,'fallback_use_calls':0,'update_calls':0,
       'observations':[],'observations_dropped':0,'context_paused':False,'context_generation':0,
       'resume_candidate':None,'resume_stable_updates':0,'resume_attempts':0,'resume_successes':0,
       'resume_global_calls':0,'native_discarded_reservations':0,'resume_epoch_floor':0,'context_discarded_references':0,
       'context_events':[],'context_events_dropped':0,
       'build':{'base':hex(base),'timestamp':hex(EXPECTED[0]),'image_size':hex(size)},
       'native_target_rva':hex(TARGET_RVA),'native_patches_added':1,'sdk_hooks_added':0,
       'limits':{'native_records':CAPACITY,'drain_per_checkpoint':128,'resolve_per_checkpoint':32},
       'native_records_total':0,'resolved_records_total':0,'verified_records_total':0}
    # Capture the local Level even when pickups already supplied Outer prefixes.
    if not seed_runtime_outer(mod,s):
        raise RuntimeError('Local Level unavailable; native hook not installed')
    local=s['runtime_outer_prefixes'][0]
    s['level_path']=local['path'];s['level_serial']=local['serial']
    s['level_address']=next(a for a,r in s['outer_cache'].items() if r['path']==local['path'] and r['serial']==local['serial'])
    initial=runtime_context(mod,s)
    if initial is None or initial['key']!=(s['level_address'],local['index'],s['level_serial'],s['level_path']):
        raise RuntimeError('Local context changed before initial seed')
    s['seed_count']=0;s['seed_global_calls']=0
    s['continuity']={'active':True,'pending':None,'started_ns':s['started_ns'],
        'bindings':[],'counts':{},'events':[],'events_dropped':0,'errors':[],'error_count':0,
        'path_resolve_calls':0,'path_resolve_ns':0}
    s['binding']=(mod.find_all,None)
    mod._pickup_registry_state=s
    mod._active_native_state['pickup_registry']=s
    try:
        def builder(stub,trampoline):
            buffer=ctypes.create_string_buffer(8+CAPACITY*STRIDE)
            control=Control(0,0,0)
            return buffer,control,build_stub(ctypes.addressof(buffer),ctypes.addressof(control),trampoline,base)
        if mod._native_read(base+TARGET_RVA,len(ORIGINAL))!=ORIGINAL:
            raise RuntimeError('Pickup entry changed before install')
        s['hook']=mod._native_allocate_hook(base+TARGET_RVA,ORIGINAL,len(ORIGINAL),builder,'pickup registry')
        if mod._native_read(s['hook']['target'],len(ORIGINAL))!=s['hook']['patch']:
            raise RuntimeError('Pickup registry native readback mismatch')
        s['hook']['control'].enabled=1
        stamp=perf_counter_ns()
        seed_baseline(mod,s,mod.find_all('InventoryPickup'))
        after=runtime_context(mod,s)
        if after is None or after['key']!=initial['key'] or not resume_ready(mod):
            raise RuntimeError('Ready context changed during initial seed')
        s['seed_search_and_validation_ns']=perf_counter_ns()-stamp;s['seed_global_calls']=1
        s['seed_count']=len(s['seed'])
    except Exception:
        stop(mod,'install_failed')
        raise
    unrealsdk.logging.info('[BL4ThirdPersonPOC.PickupRegistry] READY seed='+str(s['seed_count'])+' ring_capacity='+str(CAPACITY))
    return s


def prepare(mod):
    """Permit a fresh enable only after the previous owner was fully restored."""
    if any(e.get('kind')=='pickup_registry' for e in getattr(mod,'_native_patch_quarantine',())):
        return
    s=getattr(mod,'_pickup_registry_state',None)
    if isinstance(s,dict) and not s.get('active') and not mod._active_native_state.get('pickup_registry'):
        mod._pickup_registry_state=None


def ensure_started(mod):
    s=getattr(mod,'_pickup_registry_state',None)
    if isinstance(s,dict):return s
    if not resume_ready(mod):return None
    try:
        if any(e.get('kind')=='pickup_registry' for e in getattr(mod,'_native_patch_quarantine',())):
            raise RuntimeError('An older pickup registry patch remains quarantined')
        return install(mod)
    except Exception as exc:
        # A failed install is attempted once per enable, never once per frame.
        s=getattr(mod,'_pickup_registry_state',None)
        if not isinstance(s,dict):
            s={'active':False,'fallback_reason':'install_failed','hook':None,
               'errors':[type(exc).__name__+': '+str(exc)],'error_count':1}
            mod._pickup_registry_state=s
        else:
            s['active']=False
            s['fallback_reason']='install_failed'
            s['continuity']['active']=False
        unrealsdk.logging.warning('[BL4ThirdPersonPOC.PickupRegistry] INSTALL_FAILED '+type(exc).__name__+': '+str(exc))
        return s


def checkpoint(mod,phase):
    s=ensure_started(mod) if phase=='begin' else getattr(mod,'_pickup_registry_state',None)
    if not isinstance(s,dict) or not s.get('active'):return
    if phase=='begin':
        s['update_calls']+=1
        s['hook']['control'].epoch=s['update_calls']
    update_checkpoint(mod,s,phase)


def collect(mod):
    s=getattr(mod,'_pickup_registry_state',None)
    if not isinstance(s,dict) or not s.get('active'):
        return mod.find_all('InventoryPickup')
    return observe_find(mod,s,mod.find_all)('InventoryPickup')


def selected(mod,original):
    s=getattr(mod,'_pickup_registry_state',None)
    if not isinstance(s,dict) or not s.get('active'):return original()
    return observe_use(mod,s,original)()


def refresh(mod,state,force,original):
    s=getattr(mod,'_pickup_registry_state',None)
    c=s.get('continuity') if isinstance(s,dict) and s.get('active') else None
    if not isinstance(c,dict):return original(state,force=force)
    return observe_continuity_refresh(mod,c,original)(state,force=force)


def publish(mod,state,actor,actor_object,geometry,raw_count,eligible_count,original):
    s=getattr(mod,'_pickup_registry_state',None)
    c=s.get('continuity') if isinstance(s,dict) and s.get('active') else None
    if not isinstance(c,dict):return original(state,actor,actor_object,geometry,raw_count,eligible_count)
    return observe_continuity_publish(mod,c,original)(state,actor,actor_object,geometry,raw_count,eligible_count)


def stop(mod,reason):
    """Restore only owned bytes; pin published storage even after restoration.

    Failure retains the disabled owner and delegates retries to quarantine.
    Native producers may already be in flight: never free pages/control/ring.
    """
    s=getattr(mod,'_pickup_registry_state',None)
    if not isinstance(s,dict):return True
    s['active']=False;s['stop_reason']=reason
    c=s.get('continuity')
    if isinstance(c,dict):c['active']=False;c['pending']=None
    hook=s.get('hook')
    if isinstance(hook,dict):
        hook['control'].enabled=0
        try:
            mod._native_restore_hook(hook)
            if mod._native_read(hook['target'],len(ORIGINAL))!=ORIGINAL:
                raise RuntimeError('Pickup registry restoration readback mismatch')
            if hook.get('stub'):
                mod._retired_native_stubs.append(('pickup_registry',hook['stub'],hook['buffer'],hook['control']))
                hook['stub']=0
            s['native_restored']=True
        except Exception as exc:
            error(s,'native_cleanup',exc)
            mod._quarantine_native_patch('pickup_registry',s,'restore_incomplete')
            unrealsdk.logging.error('[BL4ThirdPersonPOC.PickupRegistry] STOP_FAILED '+str(exc))
            return False
    if mod._active_native_state.get('pickup_registry') is s:
        mod._active_native_state.pop('pickup_registry',None)
    # Bounded diagnostics are retained; SDK weak references are no longer needed.
    for name in ('registry','outer_cache','native_first'):
        if name in s:s[name].clear()
    if 'pending' in s:s['pending'].clear()
    unrealsdk.logging.info('[BL4ThirdPersonPOC.PickupRegistry] STOP reason='+reason+
        ' records='+str(s.get('native_records_total',0))+' resolved='+str(s.get('resolved_records_total',0))+
        ' resumes='+str(s.get('resume_successes',0))+' fallback='+str(s.get('fallback_reason')))
    return True


def emit_summary(mod):
    """Small read-only diagnostic when the existing performance command stops.

    Registry counters cover its entire current owner lifetime; profiler stage
    timings cover only the selected performance window.
    """
    s=getattr(mod,'_pickup_registry_state',None)
    if not isinstance(s,dict):
        unrealsdk.logging.info('[BL4ThirdPersonPOC] PERF_PICKUP_REGISTRY state=not_started')
        return
    c=s.get('continuity',{})
    unrealsdk.logging.info('[BL4ThirdPersonPOC] PERF_PICKUP_REGISTRY scope=registry_lifetime '+
        'active='+str(s.get('active',False))+' fallback='+str(s.get('fallback_reason'))+
        ' searches='+str(s.get('registry_calls',0))+' fallback_global='+str(s.get('fallback_global_calls',0))+
        ' bootstrap_global='+str(s.get('seed_global_calls',0)+s.get('resume_global_calls',0))+
        ' native_records='+str(s.get('native_records_total',0))+' resolved='+str(s.get('resolved_records_total',0))+
        ' pending='+str(len(s.get('pending',())))+' references='+str(len(s.get('registry',{})))+
        ' resumes='+str(s.get('resume_successes',0))+' overflow='+str(s.get('overflow',0))+
        ' errors='+str(s.get('error_count',0))+' continuity_preserved='+str(c.get('counts',{}).get('preserved',0))+
        ' continuity_errors='+str(c.get('error_count',0)))


def profile_stage(mod,name,elapsed):
    probe=getattr(mod,'_perf_probe',None)
    if isinstance(probe,dict) and probe.get('armed'):
        mod._perf_record_metric(name,elapsed)
