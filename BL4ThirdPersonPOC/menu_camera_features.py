"""ADS category controls and shoulder duration using the existing numeric widgets."""
from .ads_zoom_settings import CATEGORIES, ZOOM_RANGE


def build(camera, ads, state, settings):
    from . import menu_console as ui
    state['camera_features'] = settings
    state['feature_views'] = []

    def view(owner, scope, option, caption, description, limits, increment):
        values = dict(fonts=state['fonts'], template=state['template'], sliders=[],
                      labels=[], progress=[], ranges=[], values=[], dirty=False)
        ui.slider_row(owner, values, 0, caption, description, option, limits, increment,
                      compact=True, numeric=(scope, state))
        state['feature_views'].append((scope, values, (option,)))
        return values

    ui.gap(camera, 12)
    view(camera, 'feature:shoulder', settings['shoulder'], 'Shoulder Swap Blend',
         'Seconds / 0 = instant / default 0.20', (0., 1.), .01)
    ui.heading(ads, 'TPS ADS ZOOM', 'Weapon-relative zoom / 1.00x keeps existing zoom.', state, 26, 13)
    view(ads, 'feature:global', settings['global'], 'Global Zoom Multiplier',
         'Applies to every category using GLOBAL', ZOOM_RANGE, .05)
    ui.gap(ads, 10)
    navigation = ui.new('HorizontalBox', ads)
    ui.row(navigation, ui.button(navigation, 'PREV', state, 'ads:prev', 85, 50))
    state['ads_heading'] = ui.text(navigation, '', state, 19, title=True)
    ui.row(navigation, state['ads_heading'], fill=True, center=True,
           padding=ui.margin(14, 0, 0, 0))
    ui.row(navigation, ui.button(navigation, 'NEXT', state, 'ads:next', 85, 50))
    ui.column(ads, navigation)
    switcher = ui.new('WidgetSwitcher', ads)
    ui.column(ads, switcher)
    state['ads_switcher'] = switcher
    state['ads_page'] = 0
    state['ads_labels'] = {}
    for key, caption in CATEGORIES:
        page = ui.new('VerticalBox', switcher)
        switcher.AddChild(page)
        ui.gap(page, 8)
        line = ui.new('HorizontalBox', page)
        label = ui.text(line, '', state, 16)
        state['ads_labels'][key] = label
        ui.row(line, label, fill=True, center=True)
        ui.row(line, ui.button(line, 'GLOBAL / CUSTOM', state, 'ads:mode:'+key,
                              230, 50, ui.GOLD, label_size=17))
        ui.column(page, line)
        custom, option = settings['categories'][key]
        subview = view(page, 'feature:'+key, option, caption+' Zoom Multiplier',
                       'CUSTOM keeps this category separate', ZOOM_RANGE, .05)
        subview['custom_flag'] = custom
    ui.gap(ads, 8)
    ui.column(ads, ui.text(ads, 'Only TPS ADS is changed. FPS scopes keep their weapon zoom.', state, 13, ui.DIM))
    switcher.SetActiveWidgetIndex(0)
    state['feature_refresh'] = lambda: refresh(state)
    state['feature_dispatch'] = lambda: dispatch(state)
    state['feature_reset'] = lambda scope=None: reset(state, scope)
    refresh(state)


def refresh(state):
    settings = state['camera_features']
    for scope, view, options in state['feature_views']:
        if 'custom_flag' not in view:
            continue
        key = scope.split(':', 1)[1]
        enabled = view['custom_flag'].value is True
        factor = float(options[0].value if enabled else settings['global'].value)
        state['ads_labels'][key].SetText(('CUSTOM' if enabled else 'GLOBAL')+f' / {factor:g}x')
        view['sliders'][0].SetIsEnabled(enabled)
        view['labels'][0].SetIsEnabled(enabled)
        for direction in ('minus', 'plus'):
            state['buttons'][f'step:{scope}:0:{direction}'][0].SetIsEnabled(enabled)
    index = state['ads_page']
    state['ads_heading'].SetText(f'{index+1} / {len(CATEGORIES)}  {CATEGORIES[index][1]}')
    state['buttons']['ads:prev'][0].SetIsEnabled(index > 0)
    state['buttons']['ads:next'][0].SetIsEnabled(index < len(CATEGORIES)-1)


def dispatch(state):
    from .menu_console import clicked
    for direction, delta in (('prev', -1), ('next', 1)):
        if clicked(state, 'ads:'+direction):
            index = max(0, min(len(CATEGORIES)-1, state['ads_page']+delta))
            state['ads_page'] = index
            state['ads_switcher'].SetActiveWidgetIndex(index)
    for key, _label in CATEGORIES:
        if clicked(state, 'ads:mode:'+key):
            flag, _option = state['camera_features']['categories'][key]
            flag.value = not (flag.value is True)
            state['dirty'] = True
    refresh(state)


def reset(state, scope=None):
    from .menu_console import commit_feature_values
    settings = state['camera_features']
    for key, pair in settings['categories'].items():
        if scope in (None, 'ads'):
            pair[0].value = False
    for name, view, options in state['feature_views']:
        shoulder = name == 'feature:shoulder'
        if scope is None or (scope == 'shoulder' and shoulder) or (scope == 'ads' and not shoulder):
            commit_feature_values(state, view, options, [.2 if shoulder else 1.])
    state['dirty'] = True
    refresh(state)
