"""Game-thread updates owned by an invisible, non-interactive viewport widget.

The widget survives normal gameplay, auto-removes with its world, and is rebuilt
from weakly validated current runtime objects. Animation events only bootstrap
or recover the widget; subscribers run only on its own widget tick.
"""
import unrealsdk as sdk
from unrealsdk import hooks
from unrealsdk.unreal import WeakPointer

WIDGET_TICK = '/Script/UMG.UserWidget:Tick'
KEY = 'bl4tps.runtime_updates'
_owner = None

class Owner:
    def __init__(self, mod):
        self.mod = mod
        # Loader enable runs on the SDK initialization thread, not GameThread.
        self.thread = None
        self.widget_ref = self.pc_ref = None
        self.widget_address = self.pc_address = None
        self.baseline = None
        self.registered = []
        self.routes = {}
        self.busy = False
        self.active = True

    def on_thread(self):
        return self.thread is not None and int(self.mod._kernel32.GetCurrentThreadId()) == self.thread

    def live_widget(self):
        live = None if self.widget_ref is None else self.widget_ref()
        return live if live is not None and live.Class is not None else None

    def refresh(self):
        pc, pawn, manager = self.mod._get_runtime()
        if any(o is None for o in (pc, pawn, manager)):
            return
        for o in (pc, pawn, manager):
            live = WeakPointer(o)()
            if live is None or live.Class is None:
                return
        address = int(pc._get_address())
        old = self.live_widget()
        old_pc = None if self.pc_ref is None else self.pc_ref()
        if old is not None and old_pc is not None and address == self.pc_address:
            return
        from . import menu_console as ui
        viewport = next((o for o in sdk.find_all(sdk.find_class('GameViewportSubsystem'))
                         if not str(o.Name).startswith('Default__')), None)
        if viewport is None:
            return
        widget = sdk.construct_object('UserWidget', pc)
        baseline = bool(widget.bHasScriptImplementedTick)
        widget.bHasScriptImplementedTick = True
        tree = sdk.construct_object('WidgetTree', widget)
        widget.WidgetTree = tree
        tree.RootWidget = sdk.construct_object('CanvasPanel', tree)
        widget.SetVisibility(ui.enum('ESlateVisibility', 'HitTestInvisible'))
        widget.SetRenderOpacity(0.)
        slot = sdk.make_struct('GameViewportWidgetSlot', ZOrder=-100,
            bAutoRemoveOnWorldRemoved=True,
            Anchors=sdk.make_struct('Anchors', Minimum=ui.vector(0,0), Maximum=ui.vector(1,1)),
            Alignment=ui.vector(0,0), Offsets=ui.margin())
        if not viewport.AddWidget(widget, slot):
            widget.bHasScriptImplementedTick = baseline
            raise RuntimeError('Update widget viewport attachment failed')
        old_baseline = self.baseline
        self.widget_ref, self.pc_ref = WeakPointer(widget), WeakPointer(pc)
        self.widget_address, self.pc_address = int(widget._get_address()), address
        self.baseline = baseline
        if old is not None:
            old.RemoveFromParent()
            if old_baseline is not None:
                old.bHasScriptImplementedTick = old_baseline
        self.mod.logging.info('[BL4ThirdPersonPOC.Updates] WIDGET_RESUMED controller=' + hex(address))

    def widget_recover(self, obj, args, ret, func):
        # UMG script Tick is the measured game-thread source. Animation callbacks
        # can run on workers and must never establish this identity.
        if not self.active:
            return
        if self.thread is None:
            self.thread = int(self.mod._kernel32.GetCurrentThreadId())
            self.mod.logging.info('[BL4ThirdPersonPOC.Updates] GAME_THREAD_BOUND id=' + hex(self.thread))
        return self.recover(obj, args, ret, func)

    def restart_recover(self, obj, args, ret, func):
        # ClientRestart is a game-thread RPC already used by camera lifecycle.
        # It bootstraps cold starts even when no script widget is ticking yet.
        if not self.active:
            return
        if self.thread is None:
            self.thread = int(self.mod._kernel32.GetCurrentThreadId())
            self.mod.logging.info('[BL4ThirdPersonPOC.Updates] GAME_THREAD_BOUND id='
                + hex(self.thread) + ' source=ClientRestart')
        return self.recover(obj, args, ret, func)

    def recover(self, obj, args, ret, func):
        # Check thread before any SDK object or reflected field access.
        if not self.active or self.busy or not self.on_thread():
            return
        self.busy = True
        try:
            self.refresh()
        except Exception as exc:
            self.mod.logging.error('[BL4ThirdPersonPOC.Updates] RECOVERY_FAILED ' + repr(exc))
        finally:
            self.busy = False

    def install(self):
        for path, suffix in ((self.mod.FIRST_PERSON_ANIM_HOOK, '.first'),
                             (self.mod.THIRD_PERSON_ANIM_HOOK, '.third'),
                             (WIDGET_TICK, '.recover'),
                             (self.mod.CLIENT_RESTART_FUNCTION, '.restart')):
            spec = (path, hooks.Type.POST_UNCONDITIONAL, KEY + suffix)
            if hooks.has_hook(*spec):
                raise RuntimeError('Update recovery hook already owned')
            self.registered.append(spec)
            callback = (self.widget_recover if path == WIDGET_TICK else
                        self.restart_recover if path == self.mod.CLIENT_RESTART_FUNCTION else
                        self.recover)
            hooks.add_hook(*spec, callback)
            if not hooks.has_hook(*spec):
                raise RuntimeError('Update recovery registration unverified')
        # No UI construction on loader enable: wait for game-thread RPC or UMG Tick.

    def filtered(self, callback):
        def routed(obj, args, ret, func):
            if not self.active or not self.on_thread():
                return
            if self.live_widget() is None or int(obj._get_address()) != self.widget_address:
                return
            return callback(obj, args, ret, func)
        return routed

    def close(self):
        # Keep the producer alive until all dependent subscriptions have gone.
        if self.routes:
            return False
        self.active = False
        for spec in list(self.registered):
            if hooks.has_hook(*spec):
                hooks.remove_hook(*spec)
            if hooks.has_hook(*spec):
                return False
            self.registered.remove(spec)
        widget = self.live_widget()
        if widget is not None:
            widget.RemoveFromParent()
            if self.baseline is not None:
                widget.bHasScriptImplementedTick = self.baseline
        self.widget_ref = self.pc_ref = None
        return True


def start(mod):
    global _owner
    if not shutdown():
        raise RuntimeError('Update owner cleanup incomplete')
    _owner = Owner(mod)
    try:
        _owner.install()
    except Exception:
        shutdown()
        raise


def shutdown():
    global _owner
    if _owner is None:
        return True
    if not _owner.close():
        return False
    _owner = None
    return True


def _mapped(path, kind, name):
    if _owner is None:
        raise RuntimeError('Owned update producer not started')
    if path == _owner.mod.FIRST_PERSON_ANIM_HOOK:
        return (WIDGET_TICK, kind, name)
    return (path, kind, name)


def add_hook(path, kind, name, callback):
    spec = _mapped(path, kind, name)
    if spec[0] != WIDGET_TICK:
        return hooks.add_hook(*spec, callback)
    if hooks.has_hook(*spec):
        raise RuntimeError('Owned update subscription already registered')
    wrapped = _owner.filtered(callback)
    _owner.routes[spec] = wrapped
    return hooks.add_hook(*spec, wrapped)


def has_hook(path, kind, name):
    return hooks.has_hook(*_mapped(path, kind, name))


def remove_hook(path, kind, name):
    spec = _mapped(path, kind, name)
    result = hooks.remove_hook(*spec)
    if not hooks.has_hook(*spec):
        _owner.routes.pop(spec, None)
    return result


def is_game_thread():
    return _owner is not None and _owner.on_thread()
