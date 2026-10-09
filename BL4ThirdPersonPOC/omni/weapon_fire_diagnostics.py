"""Bounded read-only reflected weapon state discovery; no guessed getters."""
import math
import re
from unrealsdk.unreal import WeakPointer

MATCH = re.compile(r'ammo|fir(e|ing)|pending|queued|use|shot|state|reload|clip|magazine|heat|charge|trigger', re.I)
SCALARS = frozenset(('BoolProperty', 'IntProperty', 'Int64Property', 'UInt32Property',
                     'ByteProperty', 'EnumProperty', 'FloatProperty', 'DoubleProperty'))


class WeaponFireDiagnostics:
    def __init__(self, report):
        self.report = report
        self.weapon_ref = None
        self.fields = []
        self.previous = None
        report['weapon_fire_diagnostic'] = dict(
            note='Read-only named reflected candidates. Names alone do not prove fire admission or ammunition semantics.',
            layouts=[], observations=[], errors=[])

    def sample(self, weapon, *, update, phase, fire, firing):
        diag = self.report['weapon_fire_diagnostic']
        if weapon is None:
            self.weapon_ref = None
            self.fields = []
            self.previous = None
            return
        try:
            if self.weapon_ref is None or self.weapon_ref() != weapon:
                self.weapon_ref = WeakPointer(weapon)
                self.fields = []
                self.previous = None
                self.discover(weapon, (), 0, set())
                layout = dict(weapon=str(weapon._path_name()),
                              fields=[dict(path='.'.join(path), kind=kind) for path, kind in self.fields])
                diag['layouts'].append(layout)
                del diag['layouts'][:-16]
            values = {}
            for path, kind in self.fields:
                obj = weapon
                for name in path:
                    if obj is None:
                        break
                    obj = getattr(obj, name)
                if obj is None:
                    value = None
                elif kind == 'BoolProperty':
                    value = bool(obj)
                elif kind in ('EnumProperty', 'ByteProperty'):
                    value = str(obj)[:160]
                elif kind in ('FloatProperty', 'DoubleProperty'):
                    value = float(obj)
                    if not math.isfinite(value):
                        value = 'NONFINITE'
                else:
                    value = int(obj)
                values['.'.join(path)] = value
            state = dict(phase=phase, fire=fire, firing=firing, values=values)
            if state != self.previous:
                diag['observations'].append(dict(update=update, **state))
                del diag['observations'][:-256]
                self.previous = state
        except Exception as exc:
            message = repr(exc)[:400]
            if message not in diag['errors']:
                diag['errors'].append(message)
                del diag['errors'][:-16]

    def discover(self, obj, path, depth, seen, schema=None):
        if obj is None or depth > 2 or len(self.fields) >= 96:
            return
        if not path:
            key = str(obj._path_name())
        else:
            key = '.'.join(path)
        if key in seen:
            return
        seen.add(key)
        cls = obj.Class if schema is None else schema
        owners = (cls, *tuple(cls._superfields()))
        if len(owners) > 64:
            raise RuntimeError('Weapon diagnostic inheritance limit')
        names = set()
        for owner in owners:
            for index, prop in enumerate(owner._properties()):
                if index >= 4096:
                    raise RuntimeError('Weapon diagnostic property limit')
                name, kind = str(prop.Name), str(prop.Class.Name)
                if name in names or not MATCH.search(name):
                    continue
                names.add(name)
                field_path = (*path, name)
                if kind in SCALARS:
                    self.fields.append((field_path, kind))
                elif kind == 'ObjectProperty' and depth < 2:
                    child = getattr(obj, name)
                    if child is not None:
                        self.discover(child, field_path, depth + 1, seen)
                elif kind == 'StructProperty' and depth < 2:
                    self.discover(getattr(obj, name), field_path, depth + 1, seen, prop.Struct)
                if len(self.fields) >= 96:
                    return
