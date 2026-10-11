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
    if settings.get('slam_distance') is not None:
        view(camera, 'feature:slam_distance', settings['slam_distance'],
             'Ground Slam Extra Distance', 'Centimeters / 0 = off / default 150',
             (0., 250.), 5.)
    if settings.get('root_height') is not None:
        ui.gap(camera, 8)
        line = ui.new('HorizontalBox', camera)
        state['root_height_label'] = ui.text(line, '', state, 16)
        ui.row(line, state['root_height_label'], fill=True, center=True)
        ui.row(line, ui.button(line, 'TOGGLE', state, 'feature:root_height', 180, 44, ui.GOLD))
        ui.column(camera, line)
        ui.column(camera, ui.text(camera, 'Keep framing when the standing body lowers on terrain.', state, 12, ui.DIM))
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
    if state.get('root_height_label') is not None:
        state['root_height_label'].SetText('Grounded Body Height (QA): ' + ('ON' if settings['root_height'].value is True else 'OFF'))
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
    settings = state['camera_features']
    if settings.get('root_height') is not None and clicked(state, 'feature:root_height'):
        settings['set_root_height'](not (settings['root_height'].value is True))
        state['dirty'] = True
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
    if scope in (None, 'shoulder') and settings.get('root_height') is not None:
        settings['set_root_height'](True)
    for key, pair in settings['categories'].items():
        if scope in (None, 'ads'):
            pair[0].value = False
    for name, view, options in state['feature_views']:
        camera = name in ('feature:shoulder', 'feature:slam_distance')
        default = .2 if name == 'feature:shoulder' else 150. if name == 'feature:slam_distance' else 1.
        if scope is None or (scope == 'shoulder' and camera) or (scope == 'ads' and not camera):
            commit_feature_values(state, view, options, [default])
    state['dirty'] = True
    refresh(state)
