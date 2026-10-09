"""Weapon-relative TPS ADS options; saved by the SDK outside the .sdkmod."""
import math

CATEGORIES = (
    ('pistol', 'PISTOL'), ('smg', 'SMG'), ('assault_rifle', 'ASSAULT RIFLE'),
    ('shotgun', 'SHOTGUN'), ('sniper_rifle', 'SNIPER'), ('heavy_weapon', 'HEAVY WEAPON'),
)
ZOOM_RANGE = (0.5, 3.0)


def create_options(SliderOption, BoolOption):
    global_zoom = SliderOption('tps_ads_zoom_global', 1.0, *ZOOM_RANGE,
                              step=0.05, is_integer=False, is_hidden=True,
                              display_name='TPS ADS Zoom: Global',
                              description='Multiplier of each weapon optical zoom; 1 uses existing zoom.')
    categories = {}
    for key, label in CATEGORIES:
        categories[key] = (
            BoolOption('tps_ads_zoom_'+key+'_custom', False, is_hidden=True,
                       display_name=label+' Custom TPS ADS Zoom'),
            SliderOption('tps_ads_zoom_'+key, 1.0, *ZOOM_RANGE,
                         step=0.05, is_integer=False, is_hidden=True,
                         display_name=label+' TPS ADS Zoom'),
        )
    shoulder = SliderOption('shoulder_swap_duration', 0.2, 0.0, 1.0,
                            step=0.01, is_integer=False, is_hidden=True,
                            display_name='Shoulder Swap Blend Duration',
                            description='Seconds; 0 switches instantly.')
    return {'global': global_zoom, 'categories': categories, 'shoulder': shoulder}


def multiplier(owner, category):
    settings = getattr(owner, '_camera_feature_options', None)
    if settings is None:
        return 1.0
    option = settings['global']
    custom = settings['categories'].get(category)
    if custom is not None and custom[0].value is True:
        option = custom[1]
    try:
        value = float(option.value)
        if not math.isfinite(value):
            return 1.0
        return max(ZOOM_RANGE[0], min(ZOOM_RANGE[1], value))
    except (TypeError, ValueError, OverflowError):
        return 1.0


def adjust(owner, category, base_fov, derived):
    factor = multiplier(owner, category)
    if factor == 1.0:
        return derived
    base_tangent = math.tan(math.radians(float(base_fov))/2.0)
    desired = float(derived[2])*factor
    target = math.degrees(2.0*math.atan(base_tangent/desired))
    target = max(owner.ADS_MIN_SAFE_FOV,
                 min(float(base_fov), owner.ADS_MAX_SAFE_FOV, target))
    effective = base_tangent/math.tan(math.radians(target)/2.0)
    return target, derived[1], effective
