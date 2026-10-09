"""Scoped respawn TPS handoff and offset compensation, derived from QA probes.
No new hooks or native writes. Native reads require the reviewed game build,
serial-bound local objects and coherent live stack membership. Other restarts
keep the existing repair. The optional cleanup handoff remains a QA candidate.
"""
import math
import struct
from time import perf_counter_ns
from .ffyl_entry_blend import NativeBlendReader

ATTR = '_respawn_camera_state'


def reset(mod):
    # SDK TPS entries are owned by the ordinary camera stack owner, not here.
    setattr(mod, ATTR, None)


def error(state, phase, exc):
    state['error_count'] += 1
    state['mod'].logging.warning('[BL4ThirdPersonPOC.Respawn] DECLINED '
        + phase + ': ' + type(exc).__name__ + ': ' + str(exc))


def safe_snapshot(*args):
    return None


def append_event(state,event):
    # Only state changes are logged; no per-frame diagnostic recording.
    state['mod'].logging.info('[BL4ThirdPersonPOC.Respawn] '
        + event['method'] + ' ' + str(event['parameters']))


def update(mod):
    lifecycle=mod._camera_lifecycle
    if lifecycle.get('reason')!='client_restart' or not mod._third_person_enabled:
        reset(mod)
        return False
    state=getattr(mod,ATTR,None)
    if state is None:
        if not lifecycle.get('pending'):
            return False
        _,pawn,manager=mod._get_runtime()
        if pawn is None or manager is None:
            return False
        if str(manager.GetActorCameraMode(pawn))!='RespawnCamera':
            return False
        state={'mod':mod,'active':True,'window':True,'callback_calls':0,
               'error_count':0,'native_accesses_added':0,'game_writes_added':0,
               'tps_fname_hex':''}
        setattr(mod,ATTR,state)  # A refusal is retained for this restart.
        try:
            from unrealsdk.unreal import WeakPointer
            state['native_reader']=NativeBlendReader(mod,state,WeakPointer)
        except Exception as exc:
            error(state,'reader_preflight',exc)
            state['handoff_aborted']=True
            return False
    if state.get('handoff_aborted') or state.get('handoff_finished'):
        return False
    state['callback_calls']+=1
    # Controller returns None only when it owns this callback's transition;
    # otherwise the existing lifecycle routine remains responsible.
    return control_lifecycle(mod,state,lambda:False)() is None


def compensate_offset(mod,values):
    state=getattr(mod,ATTR,None)
    if not (state and state.get('active') and state.get('offset_blend_stage')
            and not state.get('offset_blend_complete')
            and not state.get('handoff_aborted') and mod._third_person_enabled
            and mod._camera_lifecycle.get('reason')=='client_restart'):
        return values
    if not any(abs(v)>1e-6 for v in values):
        return values
    if any(bool(getattr(mod,k,False)) for k in
           ('_ads_active','_slide_active','_ladder_active','_vehicle_camera_active','_shop_camera_active')):
        return values
    try:
        reader=state['native_reader'];reader.validate_lifetimes()
        _,pawn,manager=mod._get_runtime()
        if str(manager.GetActorCameraMode(pawn))!='ThirdPerson':
            return values
        tps_stack_proof(mod,state)
        now=perf_counter_ns()
        if state.get('offset_blend_start_ns') is None:
            state['offset_blend_start_ns']=now
        elapsed=(now-state['offset_blend_start_ns'])/1e9
        if state['offset_blend_stage']=='early':
            native=reader.snapshot()
            if native.get('status')!='ok' or native['mode_fname_hex']!=state['tps_fname_hex']:
                raise RuntimeError('Early offset progress has no validated TPS runtime')
            duration=native['blend_duration'];remaining=native['blend_remaining']
            if not (3.5<=duration<=4.0 and 0<=remaining<=duration):
                raise RuntimeError('Early offset progress outside validated blend bounds')
            factor=offset_blend_factor(duration-remaining,duration)
        else:
            start=state.get('offset_blend_from_factor',0.0)
            factor=start+(1.0-start)*offset_blend_factor(elapsed)
        state['offset_blend_last_factor']=factor
        if factor>=1:
            state['offset_blend_complete']=True
        return tuple(v*factor for v in values)
    except Exception as exc:
        error(state,'offset_blend',exc)
        state['offset_blend_complete']=True
        return values


def runtime_stack(mod,state):
    reader=state['native_reader']
    reader.validate_lifetimes()
    manager=reader.addresses[2]
    header=reader.read(manager+0x39a8,0xb0)
    array,count,capacity=struct.unpack_from('<Qii',header,0x18)
    if not 0 <= count <= min(capacity,64) or not 0 <= capacity <= 256:
        raise RuntimeError('Camera stack bounds changed')
    data=reader.read(array,count*40) if count else b''
    if reader.read(manager+0x39a8,0xb0)!=header:
        raise RuntimeError('Camera stack header changed during validation')
    if count and reader.read(array,len(data))!=data:
        raise RuntimeError('Camera stack changed during validation')
    reader.validate_lifetimes()
    entries=[data[i:i+40] for i in range(0,len(data),40)]
    return header,entries

def tps_stack_proof(mod,state):
    header,entries=runtime_stack(mod,state)
    expected=state['tps_fname_hex']
    matches=[i for i,e in enumerate(entries) if e[:8].hex()==expected and struct.unpack_from('<I',e,8)[0]==0x7201]
    if matches != [len(entries)-1] or not entries:
        raise RuntimeError('Expected unique top ThirdPerson entry missing')
    if header[0x88:0x90].hex()!=expected or entries[-1][24:40]!=header[0xa0:0xb0]:
        raise RuntimeError('Current ThirdPerson runtime/stack membership differs')
    return {'stack_count':len(entries),'top_fname_hex':expected,'unique_top_tps':True}

def valid_source_stack(entries,default_fname_hex,respawn_fname_hex):
    # The game may pop RespawnCamera in the same native handoff before the
    # first Python callback. Both coherent observed layouts are legitimate.
    if len(entries) not in (1,2) or not respawn_fname_hex or respawn_fname_hex==default_fname_hex:
        return False
    if any(len(e)!=40 or struct.unpack_from('<I',e,8)[0]!=0x7201 for e in entries):
        return False
    names=[e[:8].hex() for e in entries]
    return names==[default_fname_hex] or names==[respawn_fname_hex,default_fname_hex]

def cleanup_remaining(sample,age_seconds):
    if not sample or sample.get('status')!='ok':
        raise RuntimeError('No validated Default blend sample before stack cleanup')
    duration=sample['blend_duration'];remaining=sample['blend_remaining']
    if not (3.5<=duration<=4.0 and 0.1<=remaining<=1.0 and 0<=age_seconds<=0.1):
        raise RuntimeError('Last live blend sample outside cleanup handoff bounds')
    estimate=remaining-age_seconds
    if estimate<=0.05:
        raise RuntimeError('Too little validated blend time left for cleanup handoff')
    return estimate

def offset_blend_factor(elapsed_seconds, duration=0.16):
    if not math.isfinite(duration) or duration<=0:
        raise RuntimeError('Offset blend duration is invalid')
    t=max(0.0,min(1.0,elapsed_seconds/duration))
    return t*t*(3.0-2.0*t)

def push_target(mod,state,pawn,manager,duration,stage):
    if mod._camera_stack_owner.get('pending_pop'):
        raise RuntimeError('Pending owner pop blocks respawn target')
    before=safe_snapshot(mod,state,stage+'_before')
    if mod._third_person_pushed or mod._camera_stack_owner.get('owned'):
        mod._retire_camera_stack_owner('respawn_verified_tps_absent')
    state[stage+'_push_attempted']=True
    manager.PushActorCameraMode(pawn,'ThirdPerson','',duration,False)
    mod._record_camera_stack_owner(pawn,manager)
    state['handoff_started']=True
    state['game_writes_added']+=1
    state[stage+'_started']=True
    # Bind the TPS name from the SDK-confirmed target, not a numeric constant.
    if str(manager.GetActorCameraMode(pawn))!='ThirdPerson':
        raise RuntimeError('SDK TPS push did not select ThirdPerson')
    header,_=runtime_stack(mod,state)
    if not state['tps_fname_hex']:
        state['tps_fname_hex']=header[0x88:0x90].hex()
    proof=tps_stack_proof(mod,state)
    mod._camera_lifecycle.update(pending=True,repair_done=False,suppress_offsets=False,
                                phase='respawn_'+stage+'_blend')
    state['offset_blend_from_factor']=(state.get('offset_blend_last_factor',0.0) if stage=='cleanup' else 0.0)
    state['offset_blend_stage']=stage
    state['offset_blend_start_ns']=None
    state['offset_blend_complete']=False
    mod._apply_camera_offset()
    state[stage+'_requested_duration']=duration
    state[stage+'_push_proof']=proof
    append_event(state,{'method':stage+'_tps_push','callback':state['callback_calls'],
        'parameters':{'duration':duration,'proof':proof,'native_transition_name_reused':False},
        'before':before,'after':safe_snapshot(mod,state,stage+'_after')})

def control_lifecycle(mod,state,original):
    def observer(*args,**kwargs):
        lifecycle=mod._camera_lifecycle
        if not (state['active'] and state['window'] is not None
                and lifecycle.get('reason')=='client_restart' and not state.get('handoff_aborted')):
            return original(*args,**kwargs)
        try:
            reader=state['native_reader'];reader.validate_lifetimes()
            _,pawn,manager=mod._get_runtime()
            mode=str(manager.GetActorCameraMode(pawn))
            transitioning=bool(manager.CameraModeState.bIsTransitioning)
            if not mod._third_person_enabled or any(bool(getattr(mod,k,False)) for k in
                    ('_ads_active','_slide_active','_ladder_active','_vehicle_camera_active','_shop_camera_active')):
                state['handoff_aborted']=True
                return original(*args,**kwargs)
            if state.get('early_started'):
                if mode=='ThirdPerson':
                    proof=tps_stack_proof(mod,state)
                    native=reader.snapshot()
                    if native.get('status')=='ok' and transitioning and not state.get('cleanup_started'):
                        if native['mode_fname_hex']!=state['tps_fname_hex']:
                            raise RuntimeError('Early target native identity differs')
                        state['last_live_target_sample']=native
                        state['last_live_target_sample_ns']=perf_counter_ns()
                    lifecycle['suppress_offsets']=False
                    if transitioning:
                        lifecycle.update(pending=True,repair_done=False,phase='respawn_target_blend')
                        return None
                    lifecycle.update(pending=False,repair_done=True,phase='respawn_target_resumed')
                    if not state.get('handoff_finished'):
                        state['handoff_finished']=True
                        state['handoff_settle_proof']=proof
                        append_event(state,{'method':'target_settled','callback':state['callback_calls'],
                            'parameters':proof,'before':None,'after':safe_snapshot(mod,state,'target_settled')})
                    return original(*args,**kwargs)
                header,entries=runtime_stack(mod,state)
                if mode=='Default' and not entries and transitioning and not state.get('cleanup_attempted'):
                    state['cleanup_attempted']=True
                    sample=state.get('last_live_target_sample')
                    age=(perf_counter_ns()-state.get('last_live_target_sample_ns',0))/1e9
                    remaining=cleanup_remaining(sample,age)
                    if header[0x88:0x90].hex()!=state['default_fname_hex']:
                        raise RuntimeError('Cleanup Default identity differs')
                    state['cleanup_native_source']=sample
                    state['cleanup_last_sample_age_seconds']=age
                    state['cleanup_remaining_is_estimate']=True
                    push_target(mod,state,pawn,manager,remaining,'cleanup')
                    return None
                state['handoff_superseded_mode']=mode
                state['handoff_aborted']=True
                if mode=='Default' and not entries:
                    mod._retire_camera_stack_owner('respawn_target_lost_empty_stack')
                    lifecycle.update(pending=True,repair_done=False,suppress_offsets=True,
                                     settled_since=None,phase='respawn_target_lost')
                    state['fallback_repair_rearmed']=True
                return original(*args,**kwargs)
            if not lifecycle.get('pending') or state.get('early_attempted'):
                return original(*args,**kwargs)
            if mode=='RespawnCamera':
                header,_=runtime_stack(mod,state)
                state['respawn_camera_fname_hex']=header[0x88:0x90].hex()
                state['respawn_camera_seen']=True
                return original(*args,**kwargs)
            if mode!='Default' or not transitioning or not state.get('respawn_camera_seen'):
                return original(*args,**kwargs)
            state['early_attempted']=True
            native=reader.snapshot()
            if native.get('status')!='ok':
                raise RuntimeError('Early Default source runtime unavailable')
            duration=native['blend_duration'];remaining=native['blend_remaining']
            if not (3.5<=duration<=4.0 and 0<=duration-remaining<=0.15 and remaining>0):
                raise RuntimeError('Early Default first-callback duration outside validated bounds')
            header,entries=runtime_stack(mod,state)
            if not valid_source_stack(entries,native['mode_fname_hex'],state.get('respawn_camera_fname_hex')):
                raise RuntimeError('Early Default source stack differs')
            if any(e[:8].hex()==state['tps_fname_hex'] for e in entries):
                raise RuntimeError('TPS already present in source stack')
            state['default_fname_hex']=native['mode_fname_hex']
            state['early_native_source']=native
            state['early_stack_evidence']=[e.hex() for e in entries]
            push_target(mod,state,pawn,manager,remaining,'early')
            return None
        except Exception as exc:
            error(state,'respawn_path_handoff',exc)
            state['handoff_declined_or_failed']=str(exc)
            state['handoff_aborted']=True
            if state.get('handoff_started'):
                lifecycle.update(pending=True,repair_done=False,settled_since=None)
                # A failed cleanup attempt must also retire stale ownership so
                # the normal repair can actually push again rather than skip.
                try:
                    _,entries=runtime_stack(mod,state)
                    if mode=='Default' and not entries:
                        mod._retire_camera_stack_owner('respawn_failed_empty_stack')
                        lifecycle['suppress_offsets']=True
                        state['fallback_repair_rearmed']=True
                except Exception as cleanup_exc:
                    error(state,'fallback_owner_validation',cleanup_exc)
            return original(*args,**kwargs)
    return observer
