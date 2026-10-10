"""Owned rebind metadata and guarded image queries; no profiling hooks.

Animation views expire at the outer bind's return. The one cooked class entry
retains primitive metadata and weak UStruct identities only; each reuse scans
fresh ordered FFields. Bone names cross only one session's head/visual bind.
Image query results expire at that same callback. Every reused write must pass
fresh first-page protection admission before copying, inside the writer's
original restoration finally. Original build/byte/lifetime checks still run.
"""
import ctypes
import threading
from contextlib import contextmanager
from unrealsdk.unreal import WeakPointer
class MetadataView:
    """Lazy read-only metadata; never substitute gameplay objects or node values."""
    __slots__ = ('source', 'values', 'stats', 'property_view')

    def __init__(self, source, stats, property_view=True):
        self.source, self.stats = source, stats
        self.values = {}
        self.property_view = property_view

    def __getattr__(self, name):
        allowed = ('Name', 'Class', 'Struct', 'Offset_Internal') if self.property_view else ('Name',)
        if name not in allowed:
            return getattr(self.source, name)
        if name in self.values:
            self.stats['metadata_hits'] += 1
            return self.values[name]
        value = getattr(self.source, name)
        if name == 'Name':
            value = str(value)
        elif name in ('Class', 'Struct') and value is not None:
            value = MetadataView(value, self.stats, False)
        self.values[name] = value
        self.stats['metadata_reads'] += 1
        return value

class BoundLayout:
    """Owned animation metadata retained only until the outer profiled call exits."""
    def __init__(self, session, anim, stats):
        from unrealsdk.unreal import WeakPointer
        self.session, self.stats = session, stats
        pawn = session.bound()[1]
        mesh = session.mesh_ref() if session.mesh_ref else None
        cls = anim.Class
        self.refs = tuple(WeakPointer(o) for o in (pawn, mesh, anim, cls))
        self.addresses = tuple(int(o._get_address()) for o in (pawn, mesh, anim, cls))
        self.owner_list = None
        self.tables, self.views = {}, {}
        self.name_tables, self.selection_tables = {}, {}
        self.validate(session, anim)

    def validate(self, session, anim):
        self.stats['identity_checks'] += 1
        live = tuple(ref() for ref in self.refs)
        if session is not self.session or any(o is None for o in live):
            raise RuntimeError('Shared layout owner expired')
        pawn, mesh, bound_anim, cls = live
        if (session.bound()[1] != pawn or session.mesh_ref() != mesh
                or session.anim_ref() != bound_anim or anim != bound_anim
                or pawn.Mesh != mesh or mesh.AnimScriptInstance != bound_anim
                or bound_anim.Class != cls or int(anim._get_address()) != session.anim_address
                or tuple(int(o._get_address()) for o in live) != self.addresses):
            raise RuntimeError('Shared layout live identity changed')

    def owners(self):
        if self.owner_list is None:
            cls = self.refs[3]()
            owners = [cls]
            for parent in cls._superfields():
                if len(owners) >= 64:
                    raise RuntimeError('Shared layout inheritance limit')
                owners.append(parent)
            self.owner_list = tuple(owners)
            self.stats['inheritance_scans'] += 1
        else:
            self.stats['inheritance_hits'] += 1
        return self.owner_list

    def properties(self, owner):
        owners = self.owners()
        if not any(owner == entry for entry in owners):
            raise RuntimeError('Shared layout property owner outside bound inheritance')
        key = int(owner._get_address())
        if key in self.tables:
            self.stats['property_hits'] += 1
            return self.tables[key]
        result = []
        # Publish only a completely consumed scan. Duplicate order stays intact.
        for index, prop in enumerate(owner._properties()):
            if index >= 4096:
                raise RuntimeError('Shared layout property limit')
            address = int(prop._get_address())
            prior = self.views.get(address)
            if prior is None:
                if len(self.views) >= 32768:
                    raise RuntimeError('Shared layout total property limit')
                prior = self.views[address] = MetadataView(prop, self.stats)
            result.append(prior)
        self.tables[key] = tuple(result)
        self.stats['property_scans'] += 1
        self.stats['property_rows'] += len(result)
        return self.tables[key]

    def selected_properties(self, owner, selector):
        props=self.properties(owner)
        if selector is None:return props
        mode, values=selector
        key=int(owner._get_address())
        if mode=='names':
            # Index ALL names, retaining every duplicate and original row order.
            if key not in self.name_tables:
                table={}
                for index,prop in enumerate(props):
                    table.setdefault(str(prop.Name),[]).append((index,prop))
                self.name_tables[key]=table
                self.stats['name_index_builds']+=1
            else:self.stats['name_index_hits']+=1
            rows=[]
            for name in set(values):rows.extend(self.name_tables[key].get(name,()))
            result=tuple(prop for index,prop in sorted(rows,key=lambda row:row[0]))
        elif mode=='idle_struct':
            selection_key=(key,mode)
            if selection_key not in self.selection_tables:
                # Do not filter by reviewed node names: unknown idle nodes must
                # reach the original fail-closed validation in bind_scope.
                result=tuple(prop for prop in props
                    if str(prop.Class.Name)=='StructProperty'
                    and str(prop.Struct.Name)=='GbxAnimNode_IdleTurns')
                self.selection_tables[selection_key]=result
                self.stats['struct_index_builds']+=1
            else:
                result=self.selection_tables[selection_key]
                self.stats['struct_index_hits']+=1
        else:raise RuntimeError('Unknown shared property selection')
        self.stats['selected_property_rows']+=len(result)
        return result

    def fields(self):
        result = {}
        for owner in self.owners():
            for prop in self.properties(owner):
                result.setdefault(str(prop.Name), prop)
        return result

class FrozenClassName:
    """Property-kind metadata only; no retained SDK FFieldClass wrapper."""
    __slots__=('Name',)
    def __init__(self,name):self.Name=name

class FrozenStruct:
    """Serial-bound weak UStruct; live access for fields beyond its name."""
    __slots__=('ref','address','_name')
    def __init__(self,source,name):
        from unrealsdk.unreal import WeakPointer
        self.ref=WeakPointer(source)
        self.address=int(source._get_address())
        self._name=name
    @property
    def Name(self):
        self.resolve()
        return self._name
    def resolve(self):
        obj=self.ref()
        if obj is None or int(obj._get_address())!=self.address:
            raise RuntimeError('Cached reflection Struct expired')
        return obj
    def __getattr__(self,name):return getattr(self.resolve(),name)

class ClassEntry:
    """One cooked class schema; primitive values and weak UObject references."""
    def __init__(self,layout):
        from unrealsdk.unreal import WeakPointer
        owners=layout.owners()
        self.refs=tuple(WeakPointer(owner) for owner in owners)
        self.addresses=tuple(int(owner._get_address()) for owner in owners)
        self.rows={}
        self.values={}
        self.structs=[]
        for key,props in layout.tables.items():
            rows=[]
            for prop in props:
                address=int(prop.source._get_address())
                rows.append(address)
                if address in self.values:continue
                frozen={}
                for name,value in prop.values.items():
                    if name=='Name':frozen[name]=str(value)
                    elif name=='Offset_Internal':frozen[name]=int(value)
                    elif name=='Class':
                        if value is None:frozen[name]=None
                        elif 'Name' in value.values:
                            frozen[name]=FrozenClassName(str(value.values['Name']))
                    elif name=='Struct':
                        if value is None:frozen[name]=None
                        elif 'Name' in value.values:
                            struct=FrozenStruct(value.source,str(value.values['Name']))
                            struct.resolve()
                            frozen[name]=struct
                            self.structs.append(struct)
                self.values[address]=frozen
            self.rows[key]=tuple(rows)
        if len(self.values)>32768:raise RuntimeError('Cached class property bound')

    def reuse(self,layout):
        # Discover fresh SDK FFields for this bind. Nothing from a previous
        # session's FField/mesh/pawn/animation wrappers is retained or reused.
        current=layout.owners()
        old=tuple(ref() for ref in self.refs)
        if (any(owner is None for owner in old) or len(current)!=len(old)
                or any(a!=b for a,b in zip(current,old))
                or tuple(int(owner._get_address()) for owner in current)!=self.addresses):
            return False,'class_or_inheritance_changed'
        for struct in self.structs:
            try:struct.resolve()
            except RuntimeError:return False,'struct_expired'
        # Validate every retained property's ordered identity before importing
        # ANY cached metadata into the new live views.
        for owner in current:
            key=int(owner._get_address())
            props=layout.properties(owner)
            rows=tuple(int(prop.source._get_address()) for prop in props)
            if rows!=self.rows.get(key):return False,'property_rows_changed'
        for address,prop in layout.views.items():
            prop.values.update(self.values.get(address,{}))
        return True,'reused'

STATS = ('identity_checks inheritance_scans inheritance_hits property_scans property_hits property_rows '
         'metadata_reads metadata_hits name_index_builds name_index_hits struct_index_builds '
         'struct_index_hits selected_property_rows').split()
REGION_FIELDS = ('BaseAddress', 'AllocationBase', 'AllocationProtect', 'RegionSize', 'State', 'Protect', 'Type')
REGION_RVAS = frozenset((0x120a80a, 0x15d688, 0x186ec4a, 0x186e883, 0x4f441f,
                       0x3213ac, 0x115182c, 0x153950, 0x493d8ea, 0x146c24e))

class SystemInfo(ctypes.Structure):
    _fields_ = [('dwOemId', ctypes.c_uint32), ('dwPageSize', ctypes.c_uint32),
        ('minimum', ctypes.c_void_p), ('maximum', ctypes.c_void_p), ('mask', ctypes.c_size_t),
        ('processors', ctypes.c_uint32), ('processor_type', ctypes.c_uint32),
        ('granularity', ctypes.c_uint32), ('level', ctypes.c_uint16), ('revision', ctypes.c_uint16)]

def live_page_size():
    if ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(SystemInfo) != 48:
        raise RuntimeError('Win64 SYSTEM_INFO required')
    api = ctypes.WinDLL('kernel32', use_last_error=True).GetSystemInfo
    api.argtypes = [ctypes.POINTER(SystemInfo)]
    api.restype = None
    info = SystemInfo()
    api(ctypes.byref(info))
    size = int(info.dwPageSize)
    if info.dwOemId & 0xffff != 9 or not 0x1000 <= size <= 0x10000 or size & (size-1):
        raise RuntimeError('Live x64 page size unavailable')
    return size

class RebindCache:
    def __init__(self, supervisor):
        self.sup, self.mod, self.updates = supervisor, supervisor.mod, supervisor.updates
        self.entry = self.layout = self.capture = self.region = self.bones = None
        self.thread = None
        self.page_size = None
        self.stats = dict.fromkeys(STATS, 0)
        self.totals = dict(transactions=0, class_hits=0, class_misses=0,
                           reused_queries=0, guarded_writes=0, region_fallbacks=0, bone_hits=0)

    def owned(self):
        c = self.capture
        return (c is not None and c is self.sup.child and c.active and self.sup.active
                and c.mod is self.mod and c.updates is self.updates
                and getattr(self.mod, '_player_omnidirectional_gameplay', None) is self.sup
                and threading.get_ident() == self.thread and self.updates.is_game_thread())

    @contextmanager
    def transaction(self, capture):
        if self.capture is not None:
            if capture is not self.capture or not self.owned():
                raise RuntimeError('Nested rebind ownership differs')
            yield
            return
        if capture is not self.sup.child or not capture.active or not self.updates.is_game_thread():
            raise RuntimeError('Rebind outside owned game thread')
        if self.page_size is None:
            self.page_size = live_page_size()
        self.capture, self.thread = capture, threading.get_ident()
        self.region = dict(candidate=None, base=None, seeded=False, pending={}, authorizing=None)
        previous = getattr(self.mod, '_omni_rebind_memory', None)
        if previous is not None:
            self.capture = self.region = None
            raise RuntimeError('Rebind memory owner occupied')
        self.mod._omni_rebind_memory = self
        failed = True
        try:
            yield
            failed = False
        finally:
            layout = self.layout
            self.layout = self.region = self.capture = self.thread = None
            if getattr(self.mod, '_omni_rebind_memory', None) is self:
                del self.mod._omni_rebind_memory
            if failed:
                self.entry = self.bones = None
            elif layout is not None and self.entry is None:
                # Optional cache publication may never replace a successful bind.
                try:
                    layout.validate(layout.session, layout.refs[2]())
                    entry = ClassEntry(layout)
                    layout.validate(layout.session, layout.refs[2]())
                    self.entry = entry
                except Exception:
                    self.entry = None
            self.totals['transactions'] += int(layout is not None)

    def query_layout(self, op, capture, anim, owner=None, selector=None):
        if capture is not self.capture or not self.owned():
            raise RuntimeError('Layout outside owned bind')
        if self.layout is None:
            layout = BoundLayout(capture, anim, self.stats)
            self.layout = layout
            hit = False
            if self.entry is not None:
                try:
                    hit, reason = self.entry.reuse(layout)
                except BaseException:
                    self.entry = None
                    raise
                if not hit:
                    self.entry = None
            self.totals['class_hits' if hit else 'class_misses'] += 1
        layout = self.layout
        layout.validate(capture, anim)
        if op == 'owners': result = layout.owners()
        elif op == 'props': result = layout.selected_properties(owner, selector)
        elif op == 'fields': result = layout.fields()
        else: raise RuntimeError('Unknown layout operation')
        layout.validate(capture, anim)
        return result

    def bone_identity(self, capture, mesh, count):
        pc, pawn, camera = self.mod._get_runtime()
        getter = getattr(mesh, 'GetSkeletalMeshAsset', None)
        if pawn is None or pawn.Mesh != mesh or not callable(getter) or int(mesh.GetNumBones()) != count:
            return None
        objects = (pc, pawn, camera, mesh, mesh.AnimScriptInstance, getter())
        if any(obj is None for obj in objects): return None
        refs = tuple(WeakPointer(obj) for obj in objects)
        if any(ref() is None for ref in refs): return None
        return refs, tuple(int(obj._get_address()) for obj in objects), count

    @staticmethod
    def same_bones(left, right):
        if left is None or right is None: return False
        old = tuple(ref() for ref in left[0])
        new = tuple(ref() for ref in right[0])
        return (left[1:] == right[1:] and len(old) == len(new)
                and all(a is not None and a == b for a, b in zip(old, new))
                and tuple(int(obj._get_address()) for obj in old) == left[1])

    def bone_names(self, phase, capture, mesh, count):
        if capture is not self.sup.child or not self.updates.is_game_thread():
            return tuple(str(mesh.GetBoneName(i)) for i in range(count))
        try: identity = self.bone_identity(capture, mesh, count)
        except Exception: identity = None
        saved, self.bones = self.bones, None
        if phase == 'visual' and saved is not None and saved[0] is capture:
            if self.same_bones(saved[1], identity):
                self.totals['bone_hits'] += 1
                return saved[2]
        names = tuple(str(mesh.GetBoneName(i)) for i in range(count))
        if phase == 'head' and identity is not None:
            try: after = self.bone_identity(capture, mesh, count)
            except Exception: after = None
            if self.same_bones(identity, after): self.bones = (capture, after, names)
        return names

    def single_page(self, address, size):
        return (type(address) is int and 0 < size <= 64 and self.page_size is not None
                and address // self.page_size == (address+size-1) // self.page_size)

    def admitted(self, region, address, base):
        start, size = region['BaseAddress'], region['RegionSize']
        return (0x10000 <= address < address+64 < 1<<47 and 0 < size < 1<<47
                and start <= address and address+64 <= start+size < 1<<47
                and region['AllocationBase'] == base and region['State'] == 0x1000
                and region['Type'] == 0x1000000 and not region['Protect'] & 0x100
                and region['Protect'] & 0xff in (0x20, 0x40, 0x80))

    def query_region(self, address, fresh):
        if not self.owned(): return fresh(address)
        c = self.region
        candidate, base = c['candidate'], c['base']
        if (candidate is not None and address-base in REGION_RVAS
                and self.single_page(address, 64) and self.admitted(candidate, address, base)):
            info = self.mod._MEMORY_BASIC_INFORMATION()
            for name, value in candidate.items(): setattr(info, name, value)
            c['pending'][address] = candidate['Protect']
            self.totals['reused_queries'] += 1
            return info
        info = fresh(address)
        fields = {k: int(getattr(info, k) or 0) for k in REGION_FIELDS}
        base = fields['AllocationBase']
        if fields['Type'] != 0x1000000 or address-base not in REGION_RVAS or c['seeded']: return info
        c['seeded'], c['base'] = True, base
        try:
            seed_address = base+min(REGION_RVAS)
            if not 0x10000 <= seed_address < seed_address+64 < 1<<47:
                raise RuntimeError('Image seed outside bounds')
            seed = fresh(seed_address)
            candidate = {k: int(getattr(seed, k) or 0) for k in REGION_FIELDS}
            if hasattr(seed, 'PartitionId'): candidate['PartitionId'] = int(seed.PartitionId)
            signature = ('AllocationBase', 'AllocationProtect', 'State', 'Protect', 'Type')
            if (not self.admitted(candidate, seed_address, base) or not self.admitted(fields, address, base)
                    or any(candidate[k] != fields[k] for k in signature)):
                raise RuntimeError('Fresh image/seed guards differ')
            c['candidate'] = candidate
        except Exception:
            c['candidate'] = None
            self.totals['region_fallbacks'] += 1
        return info

    def write_admission(self, address, data):
        c = self.region
        if c is None: return None
        expected = c['pending'].get(address)
        if expected is None:
            if c['candidate'] is not None and (type(address) is not int or address-c['base'] not in REGION_RVAS
                    or type(data) is not bytes or not self.single_page(address, len(data))):
                c['candidate'] = None
            return None
        if not self.owned() or type(data) is not bytes or not self.single_page(address, len(data)):
            c['candidate'] = None
            raise RuntimeError('Reused code write outside owner/page; no bytes copied')
        def admit(old_protect):
            if not self.owned() or self.region is not c or c['pending'].get(address) != expected:
                raise RuntimeError('Reused code authorization changed; no bytes copied')
            if int(old_protect) != expected:
                c['candidate'] = None
                raise RuntimeError('Live code-page protection changed; no bytes copied')
            c['pending'].pop(address, None)
            self.totals['guarded_writes'] += 1
        return admit

    def clear(self):
        self.entry = self.bones = self.layout = self.region = self.capture = self.thread = None
        if getattr(self.mod, '_omni_rebind_memory', None) is self: del self.mod._omni_rebind_memory

def layout_query(op, capture, anim, owner=None, selector=None):
    supervisor = getattr(capture, 'lifecycle_supervisor', None)
    cache = getattr(supervisor, 'rebind_cache', None)
    if cache is not None and cache.capture is not None:
        return cache.query_layout(op, capture, anim, owner, selector)
    if op == 'owners': return (anim.Class, *tuple(anim.Class._superfields()))
    if op == 'props': return owner._properties()
    if op == 'fields':
        from .common import reflected_fields
        return reflected_fields(anim.Class)
    raise RuntimeError('Unknown layout operation')

def bone_names(phase, capture, mesh, count):
    cache = getattr(getattr(capture, 'lifecycle_supervisor', None), 'rebind_cache', None)
    if cache is None: return tuple(str(mesh.GetBoneName(i)) for i in range(count))
    return cache.bone_names(phase, capture, mesh, count)
