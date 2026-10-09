"""Render the Camera Console on the existing game menu lifecycle.

An open-menu state owns widgets, imported fonts/textures and input latches.
Allowlisted packaged assets can be materialized for Unreal runtime import.
Commit sanitized camera/motion choices through injected callbacks. Dispatch runs
only from the existing menu animation callback; closing releases this window's
references. Menu behavior is preserved and remains a separate gameplay task.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Callable

from .vehicle_camera import DEFAULTS as VEHICLE_DEFAULTS, RANGES as VEHICLE_RANGES, PRESETS as VEHICLE_PRESETS

import unrealsdk as sdk
from unrealsdk import logging

WIDTH = 1180
HEIGHT = 680
INK = "100F0D"
PANEL = "24211D"
HEADER = "1B1916"
ROW = "2D2923"
GOLD = "EFB82D"
ORANGE = "E67E32"
CREAM = "F2E6CE"
DIM = "B6A58B"
TRACK = "48443E"
PURPLE = "9E62C8"
DEFAULTS = (0, 75, 10)
RANGES = ((-75, 75), (0, 150), (-65, 85))
PRESETS = {"STANDARD": DEFAULTS, "CLOSE": (45, 55, 10), "WIDE": (-50, 90, 15)}
ERRORS = (AttributeError, TypeError, ValueError, KeyError, RuntimeError)
_reported: set[str] = set()


def cosmetic(key: str, action: Callable[[], Any]) -> bool:
    try:
        action()
        return True
    except ERRORS as error:
        if key not in _reported:
            _reported.add(key)
            logging.warning(
                f"[BL4ThirdPersonPOC] CONSOLE_STYLE_FALLBACK {key}: {error}"
            )
        return False


def new(kind: str, owner: Any) -> Any:
    return sdk.construct_object(kind, owner)


def enum(kind: str, member: str) -> Any:
    return getattr(sdk.find_enum(kind), member)


def vector(x: float, y: float) -> Any:
    return sdk.make_struct("Vector2D", X=float(x), Y=float(y))


def linear(color: str, alpha: float = 1.0) -> Any:
    # Hex palette values are sRGB; Slate's LinearColor requires linear channels.
    def channel(offset: int) -> float:
        value = int(color[offset : offset + 2], 16) / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return sdk.make_struct(
        "LinearColor", R=channel(0), G=channel(2), B=channel(4), A=alpha
    )


def slate(color: str, alpha: float = 1.0) -> Any:
    return sdk.make_struct("SlateColor", SpecifiedColor=linear(color, alpha))


def margin(left: float = 0, top: float = 0, right: float = 0, bottom: float = 0) -> Any:
    return sdk.make_struct("Margin", Left=left, Top=top, Right=right, Bottom=bottom)


def sized(owner: Any, child: Any, width: float = 0, height: float = 0) -> Any:
    box = new("SizeBox", owner)
    if width:
        box.SetWidthOverride(float(width))
    if height:
        box.SetHeightOverride(float(height))
    box.SetContent(child)
    return box


def border(owner: Any, color: str, padding: Any = None) -> Any:
    box = new("Border", owner)
    box.SetBrushColor(linear(color))
    box.SetPadding(padding if padding is not None else margin())
    return box


def place(
    slot: Any, *, fill: bool = False, padding: Any = None, center: bool = False
) -> Any:
    if padding is not None:
        slot.SetPadding(padding)
    if fill:
        slot.SetSize(
            sdk.make_struct(
                "SlateChildSize", Value=1.0, SizeRule=enum("ESlateSizeRule", "Fill")
            )
        )
    if center:
        slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Center"))
    return slot


def row(owner: Any, child: Any, **kwargs: Any) -> Any:
    return place(owner.AddChildToHorizontalBox(child), **kwargs)


def column(owner: Any, child: Any, **kwargs: Any) -> Any:
    return place(owner.AddChildToVerticalBox(child), **kwargs)


def gap(owner: Any, height: int) -> None:
    column(owner, sized(owner, new("Spacer", owner), height=height))


def asset_path(filename: str) -> str | None:
    """Materialize allowlisted fonts/PNGs for Unreal's runtime file import."""
    allowed = {
        "Anton-Regular.ttf",
        "BarlowCondensed-Medium.ttf",
        "shoulder_hunter.png",
        "console_frame.png",
        "console_backdrop.png",
        "button_normal.png",
        "button_active.png",
        "icon_camera.png",
        "icon_aiming.png",
        "icon_motion.png",
    }
    if filename not in allowed:
        raise ValueError("Unknown menu asset")
    try:
        from mods_base import SETTINGS_DIR, open_in_mod_dir

        with open_in_mod_dir(
            Path(__file__).with_name("assets") / filename, binary=True
        ) as source:
            data = source.read(8_000_001)
        signature = (
            b"\x89PNG\r\n\x1a\n" if filename.endswith(".png") else b"\x00\x01\x00\x00"
        )
        if len(data) > 8_000_000 or not data.startswith(signature):
            raise ValueError("Invalid menu asset")
        target = Path(SETTINGS_DIR) / "bl4tps_camera_console" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != data:
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, target)
        return str(target)
    except (OSError, ValueError, ImportError) as error:
        key = f"asset:{filename}"
        if key not in _reported:
            _reported.add(key)
            logging.warning(
                f"[BL4ThirdPersonPOC] CONSOLE_STYLE_FALLBACK {key}: {error}"
            )
        return None


def configure_texture_filter(texture, filename):
    """Configure only this window's imported texture; report native readback."""
    before = str(texture.Filter)
    filters = sdk.find_enum("TextureFilter")
    bilinear = None
    for name in ("TF_Bilinear", "Bilinear", "TF_BILINEAR"):
        try:
            bilinear = getattr(filters, name)
            break
        except AttributeError:
            continue
    if bilinear is None:
        raise RuntimeError("TextureFilter exposes no bilinear member")
    texture.Filter = bilinear
    refresh = getattr(texture, "UpdateResource", None)
    refresh_status = "not_exposed"
    if callable(refresh):
        refresh()
        refresh_status = "called"
    logging.info(f"[BL4ThirdPersonPOC] MENU_TEXTURE_FILTER asset={filename} before={before} after={texture.Filter} refresh={refresh_status}")


def picture(
    owner: Any, state: dict[str, Any], filename: str, color: str = "FFFFFF"
) -> Any | None:
    """Optional, noninteractive art. Never hold textures beyond this window."""
    result: list[Any] = []

    def load() -> None:
        texture = state["textures"].get(filename)
        if texture is None:
            path = asset_path(filename)
            if path is None:
                return
            pc = state.get("pc")
            library_class = sdk.find_class("KismetRenderingLibrary")
            if pc is None or library_class is None:
                raise RuntimeError("Image import context unavailable")
            library = library_class.ClassDefaultObject
            if library is None:
                raise RuntimeError("Image importer unavailable")
            texture = library.ImportFileAsTexture2D(pc, path)
            if texture is None:
                raise RuntimeError("Image import returned no texture")
            cosmetic(f"texture_filter:{filename}", lambda: configure_texture_filter(texture, filename))
            state["textures"][filename] = texture
        image = new("Image", owner)
        image.SetBrushFromTexture(texture, False)
        image.SetColorAndOpacity(linear(color))
        image.SetVisibility(enum("ESlateVisibility", "HitTestInvisible"))
        result.append(image)

    cosmetic(f"image:{filename}", load)
    return result[0] if result else None


def fonts(owner: Any) -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for family, filename in (
        ("title", "Anton-Regular.ttf"),
        ("body", "BarlowCondensed-Medium.ttf"),
    ):
        path = asset_path(filename)
        if path is None:
            continue

        def load(family: str = family, path: str = path) -> None:
            font = new("Font", owner)
            font.FontCacheType = enum("EFontCacheType", "Runtime")
            composite = font.CompositeFont
            composite.DefaultTypeface.Fonts = [
                sdk.make_struct(
                    "TypefaceEntry",
                    Name="Regular",
                    Font=sdk.make_struct(
                        "FontData",
                        FontFilename=path,
                        Hinting=enum("EFontHinting", "Default"),
                        LoadingPolicy=enum("EFontLoadingPolicy", "LazyLoad"),
                        SubFaceIndex=0,
                    ),
                )
            ]
            font.CompositeFont = composite
            loaded[family] = font

        cosmetic(f"font:{family}", load)
    return loaded


def text(
    owner: Any,
    value: str,
    state: dict[str, Any],
    size: int = 20,
    color: str = CREAM,
    title: bool = False,
) -> Any:
    label = new("TextBlock", owner)
    label.SetText(value)

    def style() -> None:
        font = label.Font
        font.Size = size
        family = "title" if title else "body"
        if family in state["fonts"]:
            font.FontObject = state["fonts"][family]
            font.TypefaceFontName = "Regular"
        label.SetFont(font)
        label.SetColorAndOpacity(slate(color))

    cosmetic("text", style)
    return label


def paint_brush(brush: Any, template: Any, color: str, alpha: float = 1.0) -> Any:
    # Assigning a brush into a struct field must precede this operation.
    brush.DrawAs = enum("ESlateBrushDrawType", "Image")
    brush.TintColor = slate(color, alpha)
    return brush


def button(
    owner: Any,
    caption: str,
    state: dict[str, Any],
    key: str,
    width: int,
    height: int = 48,
    accent: str = DIM,
    icon: str | None = None,
    label_size: int = 17,
) -> Any:
    """Latched ToggleButton records even short clicks between existing GG callbacks."""
    frame = border(owner, INK, margin(3, 3, 3, 3))
    fill = border(frame, HEADER, margin(8, 4, 8, 4))
    frame.SetContent(fill)
    check = new("CheckBox", fill)
    style = check.WidgetStyle
    # ESlateCheckBoxType::ToggleButton; APEX uses this value because Slate enums
    # need not be exposed through Unreal reflection in a packaged game.
    style.CheckBoxType = 1
    style.Padding = margin()
    for field in (
        "UncheckedImage",
        "UncheckedHoveredImage",
        "UncheckedPressedImage",
        "CheckedImage",
        "CheckedHoveredImage",
        "CheckedPressedImage",
    ):
        setattr(style, field, state["template"])
        hovered = "Hovered" in field
        pressed = "Pressed" in field
        color = "FFFFFF" if hovered else INK
        alpha = 0.24 if hovered else 0.28 if pressed else 0.0
        brush = paint_brush(getattr(style, field), state["template"], color, alpha)
        brush.ImageSize.X = brush.ImageSize.Y = 1.0
        if hovered:

            def hover_outline(brush: Any = brush) -> None:
                brush.DrawAs = enum("ESlateBrushDrawType", "RoundedBox")
                brush.OutlineSettings.Width = 2.0
                brush.OutlineSettings.Color = slate(CREAM, 0.85)
                radii = brush.OutlineSettings.CornerRadii
                radii.X = radii.Y = radii.Z = radii.W = 0.0
                brush.OutlineSettings.RoundingType = enum(
                    "ESlateBrushRoundingType", "FixedRadius"
                )

            cosmetic("button_hover_outline", hover_outline)
    check.WidgetStyle = style
    check.SetIsChecked(False)
    line = new("HorizontalBox", check)
    if icon is not None:
        image = picture(line, state, icon, accent)
        if image is not None:
            row(
                line,
                sized(line, image, 30, 30),
                center=True,
                padding=margin(0, 0, 12, 0),
            )
            state["button_icons"][key] = image
    label = text(line, caption, state, label_size, accent, title=True)
    row(line, label, center=True)
    check.SetContent(sized(check, line, height=height - 14))
    fill.SetContent(check)
    cosmetic(
        "button_align",
        lambda: setattr(
            check, "HorizontalAlignment", enum("EHorizontalAlignment", "HAlign_Center")
        ),
    )
    # UMG shear values are degrees. The old fraction produced an almost flat tab.
    cosmetic("slant", lambda: frame.SetRenderShear(vector(-7.0, 0)))
    cosmetic("label_unslant", lambda: line.SetRenderShear(vector(7.0, 0)))
    layers = new("Overlay", owner)
    shade = border(layers, INK)
    shade.SetVisibility(enum("ESlateVisibility", "HitTestInvisible"))
    cosmetic("shadow_slant", lambda: shade.SetRenderShear(vector(-7.0, 0)))
    shadow_slot = layers.AddChildToOverlay(shade)
    shadow_slot.SetPadding(margin(5, 5, 0, 0))
    shadow_slot.SetHorizontalAlignment(enum("EHorizontalAlignment", "HAlign_Fill"))
    shadow_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Fill"))
    normal_art = picture(layers, state, "button_normal.png")
    selected_art = picture(layers, state, "button_active.png")
    if normal_art is not None and selected_art is not None:
        # The PNG already includes its shadow. Keep the native shade only
        # for the fallback without art, avoiding mismatched double shadows.
        shade.SetBrushColor(linear(INK, 0.0))
        for art in (normal_art, selected_art):
            art_slot = layers.AddChildToOverlay(art)
            art_slot.SetPadding(margin(0, 0, 5, 5))
            art_slot.SetHorizontalAlignment(enum("EHorizontalAlignment", "HAlign_Fill"))
            art_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Fill"))
        selected_art.SetColorAndOpacity(linear("FFFFFF", 0.0))
        frame.SetBrushColor(linear(INK, 0.0))
        fill.SetBrushColor(linear(HEADER, 0.0))
        state["button_art"][key] = (normal_art, selected_art)
    face_slot = layers.AddChildToOverlay(frame)
    face_slot.SetPadding(margin(0, 0, 5, 5))
    face_slot.SetHorizontalAlignment(enum("EHorizontalAlignment", "HAlign_Fill"))
    face_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Fill"))
    state["buttons"][key] = (check, fill, label, accent)
    return sized(owner, layers, width + 5, height + 5)


def paint_button(state: dict[str, Any], key: str, selected: bool) -> None:
    _check, fill, label, accent = state["buttons"][key]
    art = state.get("button_art", {}).get(key)
    if art is not None:
        normal_art, selected_art = art
        normal_art.SetColorAndOpacity(linear("FFFFFF", 0.0 if selected else 1.0))
        selected_art.SetColorAndOpacity(linear("FFFFFF", 1.0 if selected else 0.0))
    else:
        fill.SetBrushColor(linear(GOLD if selected else HEADER))
    label.SetColorAndOpacity(slate(INK if selected else accent))
    image = state["button_icons"].get(key)
    if image is not None:
        image.SetColorAndOpacity(linear(INK if selected else accent))


def clicked(state: dict[str, Any], key: str) -> bool:
    check = state["buttons"][key][0]
    if check.IsChecked():
        check.SetIsChecked(False)
        return True
    return False


def style_numeric_background(number, state):
    style = number.WidgetStyle
    style.Padding = margin(6, 3, 6, 3)
    style.BackgroundColor = slate("FFFFFF")
    style.ForegroundColor = slate(CREAM)
    style.FocusedForegroundColor = slate(CREAM)
    style.ReadOnlyForegroundColor = slate(CREAM)
    for field in ("BackgroundImageNormal", "BackgroundImageHovered",
                  "BackgroundImageFocused", "BackgroundImageReadOnly"):
        setattr(style, field, state["template"])
        brush = paint_brush(getattr(style, field), state["template"], INK)
        brush.ImageSize.X = brush.ImageSize.Y = 1.0
    number.WidgetStyle = style


def style_numeric_font(number, state, compact):
    style = number.WidgetStyle
    text_style = style.TextStyle
    font = text_style.Font
    font.Size = 15 if compact else 17
    if "title" in state["fonts"]:
        font.FontObject = state["fonts"]["title"]
        font.TypefaceFontName = "Regular"
    text_style.Font = font
    text_style.ColorAndOpacity = slate(CREAM)
    style.TextStyle = text_style
    number.WidgetStyle = style


def slider_row(
    owner: Any,
    state: dict[str, Any],
    index: int,
    caption: str,
    description: str,
    option: Any,
    limits: tuple[float, float] | None = None,
    step: float = 1.0,
    compact: bool = False,
    numeric: tuple[str, dict[str, Any]] | None = None,
) -> None:
    frame = border(owner, INK, margin(2, 2, 2, 2))
    panel = border(frame, ROW, margin(14, 5, 14, 5))
    frame.SetContent(panel)
    frame.SetBrushColor(linear(INK, 0.0))
    panel.SetBrushColor(linear(ROW, 0.0))
    line = new("HorizontalBox", panel)
    panel.SetContent(line)
    words = new("VerticalBox", line)
    column(words, text(words, caption, state, 16 if compact else 18, title=True))
    column(words, text(words, description, state, 12, DIM))
    row(line, sized(line, words, 325), center=True)
    stack = new("Overlay", line)
    progress = new("ProgressBar", stack)
    style = progress.WidgetStyle
    for field, color in (
        ("BackgroundImage", TRACK),
        ("FillImage", GOLD),
        ("MarqueeImage", GOLD),
    ):
        setattr(style, field, state["template"])
        paint_brush(getattr(style, field), state["template"], color)
    progress.WidgetStyle = style
    cosmetic("progress_tint", lambda: progress.SetFillColorAndOpacity(linear("FFFFFF")))
    bar_slot = stack.AddChildToOverlay(sized(stack, progress, height=12))
    bar_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Center"))
    bar_slot.SetHorizontalAlignment(enum("EHorizontalAlignment", "HAlign_Fill"))
    bar_slot.SetPadding(margin(12, 0, 12, 0))
    slider = new("Slider", stack)
    lo, hi = limits if limits is not None else RANGES[index]
    initial = quantized(float(option.value), lo, hi, step)
    if initial != float(option.value):
        option.value = initial
        state["dirty"] = True
    slider.SetMinValue(float(lo))
    slider.SetMaxValue(float(hi))
    slider.SetStepSize(float(step))
    slider.SetValue(float(initial))

    def handle_style() -> None:
        style = slider.WidgetStyle
        for field in ("NormalBarImage", "HoveredBarImage", "DisabledBarImage"):
            setattr(style, field, state["template"])
            paint_brush(getattr(style, field), state["template"], INK, 0.0)
        for field, color in (
            ("NormalThumbImage", GOLD),
            ("HoveredThumbImage", "FFD15A"),
            ("DisabledThumbImage", DIM),
        ):
            setattr(style, field, state["template"])
            brush = paint_brush(getattr(style, field), state["template"], color)
            # FSlateBrush.ImageSize may use a float-vector type distinct from
            # reflected Vector2D. Mutate components, as APEX does, rather than
            # assigning a potentially incompatible struct and aborting at Normal.
            brush.ImageSize.X = 24.0
            brush.ImageSize.Y = 30.0

            def thumb_outline(brush: Any = brush) -> None:
                brush.DrawAs = enum("ESlateBrushDrawType", "RoundedBox")
                brush.OutlineSettings.Width = 2.0
                brush.OutlineSettings.Color = slate(INK)
                radii = brush.OutlineSettings.CornerRadii
                radii.X = radii.Y = radii.Z = radii.W = 0.0
                brush.OutlineSettings.RoundingType = enum(
                    "ESlateBrushRoundingType", "FixedRadius"
                )

            cosmetic("thumb_outline", thumb_outline)
        style.BarThickness = 12.0
        slider.WidgetStyle = style
        slider.SetSliderHandleColor(linear("FFFFFF"))

    cosmetic("slider", handle_style)
    knob_slot = stack.AddChildToOverlay(slider)
    knob_slot.SetHorizontalAlignment(enum("EHorizontalAlignment", "HAlign_Fill"))
    knob_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Fill"))
    row(line, sized(line, stack, height=42), fill=True, center=True)
    number_box = border(line, "715139", margin(1, 1, 1, 1))
    if numeric is not None:
        number = new("EditableTextBox", number_box)
        number.SetText(format(initial, "g"))
        number.SelectAllTextWhenFocused = True
        number.ClearKeyboardFocusOnCommit = True
        number.SetIsReadOnly(False)
        number.SetForegroundColor(linear(CREAM))
        cosmetic("numeric_center", lambda: number.SetJustification(enum("ETextJustify", "Center")))

        # Background and font are separate so a font-schema mismatch cannot
        # leave the native light-grey background unchanged.
        cosmetic("numeric_background", lambda: style_numeric_background(number, state))
        cosmetic("numeric_font", lambda: style_numeric_font(number, state, compact))
        scope, main_state = numeric
        key = f"input:{scope}:{index}"
        main_state.setdefault("numeric_inputs", {})[key] = (scope, index, number, state)
    else:
        number = text(number_box, format(initial, "g"), state, 21, title=True)
    number_box.SetContent(number)
    if numeric is not None:
        row(line, button(line, "-", main_state, f"step:{scope}:{index}:minus",
                         36, 40, GOLD, label_size=12),
            padding=margin(8, 0, 0, 0), center=True)
    row(line, sized(line, number_box, 76, 40 if compact else 44), padding=margin(6 if numeric is not None else 14, 0, 0, 0), center=True)
    if numeric is not None:
        row(line, button(line, "+", main_state, f"step:{scope}:{index}:plus",
                         36, 40, GOLD, label_size=12),
            padding=margin(6, 0, 0, 0), center=True)
    column(owner, sized(owner, frame, height=68 if compact else 76),
           padding=margin(0, 0, 0, 6 if compact else 8))
    column(owner, sized(owner, border(owner, "59422D"), height=1))
    state["sliders"].append(slider)
    state["labels"].append(number)
    state["progress"].append(progress)
    state["ranges"].append((lo, hi))
    state.setdefault("increments", []).append(step)
    state["values"].append(initial)
    progress.SetPercent((initial - lo) / (hi - lo))


def heading(
    owner: Any,
    caption: str,
    description: str,
    state: dict[str, Any],
    title_size: int = 26,
    description_size: int = 13,
) -> None:
    column(owner, text(owner, caption, state, title_size, title=True))
    column(owner, text(owner, description, state, description_size, DIM))
    gap(owner, 8)


def build(
    root: Any,
    tree: Any,
    state: dict[str, Any],
    options: tuple[Any, ...],
    dynamic_motion_enabled: bool,
    motion_parameters=None,
    save_motion: Callable[[], Any] | None = None,
    reset_motion: Callable[[], Any] | None = None,
    get_sniper_mode: Callable[[], bool] | None = None,
    set_sniper_mode: Callable[[bool], Any] | None = None,
    get_ffyl_mode: Callable[[], bool] | None = None,
    set_ffyl_mode: Callable[[bool], Any] | None = None,
    get_ground_slam_mode: Callable[[], bool] | None = None,
    set_ground_slam_mode: Callable[[bool], Any] | None = None,
    vehicle_options: tuple[Any, ...] = (),
    get_vehicle_control: Callable[[], bool] | None = None,
    set_vehicle_control: Callable[[bool], Any] | None = None,
    get_omni_movement: Callable[[], bool] | None = None,
    set_omni_movement: Callable[[bool], Any] | None = None,
    omni_movement_caption: Callable[[], str] | None = None,
    get_hybrid_ads: Callable[[], bool] | None = None,
    set_hybrid_ads: Callable[[bool], Any] | None = None,
    debug_actions: dict[str, Callable[[], Any]] | None = None,
    debug_status: Callable[[], dict[str, str]] | None = None,
    camera_features=None,
) -> Any:
    """Build a fully owned view; state is already registered for partial-failure cleanup."""
    state.update(
        console=True,
        buttons={},
        button_icons={},
        button_art={},
        textures={},
        progress=[],
        page=0,
        fonts=fonts(root),
    )
    scale = new("ScaleBox", root)
    scale.SetStretch(enum("EStretch", "ScaleToFit"))
    tree.RootWidget = scale
    layers = new("Overlay", scale)
    scale.SetContent(sized(scale, layers, WIDTH, HEIGHT))
    background = picture(layers, state, "console_backdrop.png")
    if background is not None:
        background_slot = layers.AddChildToOverlay(background)
        background_slot.SetHorizontalAlignment(
            enum("EHorizontalAlignment", "HAlign_Fill")
        )
        background_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Fill"))
    rim = border(layers, INK, margin(14, 14, 14, 14))
    if background is not None:
        # Only the contour-matched image paints the outermost silhouette.
        rim.SetBrushColor(linear(INK, 0.0))
    content_slot = layers.AddChildToOverlay(rim)
    content_slot.SetHorizontalAlignment(enum("EHorizontalAlignment", "HAlign_Fill"))
    content_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Fill"))
    panel = border(rim, PANEL)
    panel.SetBrushColor(linear(PANEL, 0.0))
    rim.SetContent(panel)
    state["template"] = new("InputKeySelector", root).WidgetStyle.Normal
    layout = new("VerticalBox", panel)
    panel.SetContent(layout)
    header = border(layout, HEADER, margin(18, 8, 18, 8))
    header.SetBrushColor(linear(HEADER, 0.0))
    head = new("HorizontalBox", header)
    header.SetContent(head)
    portrait = picture(head, state, "shoulder_hunter.png")
    if portrait is not None:
        row(
            head,
            sized(head, portrait, 88, 96),
            center=True,
            padding=margin(0, 0, 14, 0),
        )
    else:
        icon = border(head, GOLD, margin(5, 5, 5, 5))
        icon.SetContent(border(icon, INK))
        row(head, sized(head, icon, 48, 36), center=True, padding=margin(0, 0, 16, 0))
    title_stack = new("VerticalBox", head)
    column(title_stack, text(title_stack, "BL4 THIRD PERSON", state, 39, GOLD, title=True))
    column(title_stack, text(title_stack, "CAMERA SETTINGS", state, 14, CREAM, title=True))
    row(head, title_stack, fill=True, center=True)
    column(layout, sized(layout, header, height=128))
    column(layout, sized(layout, border(layout, INK), height=4))
    middle = new("HorizontalBox", layout)
    column(layout, middle, fill=True)
    nav_panel = border(middle, HEADER, margin(14, 12, 14, 12))
    nav_layout = new("VerticalBox", nav_panel)
    nav_panel.SetContent(nav_layout)
    nav_scroll = new("ScrollBox", nav_layout)
    column(nav_layout, nav_scroll, fill=True)
    state["nav_scroll"] = nav_scroll
    nav = new("VerticalBox", nav_scroll)
    nav_scroll.AddChild(nav)
    for index, (caption, icon) in enumerate(
        (
            ("CAMERA", "icon_camera.png"),
            ("CAMERA MODES", "icon_aiming.png"),
            ("CAMERA MOTION", "icon_motion.png"),
            ("VEHICLE CAMERA", "icon_camera.png"),
            ("ADS ZOOM", "icon_aiming.png"),
            ("DEBUG", None),
        )
    ):
        column(
            nav,
            button(nav, caption, state, f"nav:{index}", 218, 62, CREAM, label_size=22),
            padding=margin(0, 0, 0, 10),
        )
    column(nav_layout, text(nav_layout, "CAMERA SETTINGS", state, 13, DIM),
           padding=margin(0, 6, 0, 0))
    row(middle, sized(middle, nav_panel, 270))
    row(middle, sized(middle, border(middle, INK), 4))
    switcher = new("WidgetSwitcher", middle)
    state["switcher"] = switcher
    row(middle, switcher, fill=True)
    pages: list[Any] = []
    for _index in range(6):
        page = border(switcher, PANEL, margin(18, 12, 18, 12))
        scroll = new("ScrollBox", page)
        page.SetContent(scroll)
        contents = new("VerticalBox", scroll)
        scroll.AddChild(contents)
        switcher.AddChild(page)
        pages.append(contents)
    camera, aiming, motion, vehicle, ads, debug = pages
    heading(camera, "HIPFIRE CAMERA", "Choose your view. Make it yours.", state)
    preset_row = new("HorizontalBox", camera)
    row(
        preset_row,
        text(preset_row, "Camera Preset", state, 18, title=True),
        fill=True,
        center=True,
    )
    for name in PRESETS:
        row(
            preset_row,
            button(preset_row, name, state, f"preset:{name}", 120, 46, CREAM, label_size=15),
            padding=margin(6, 0, 0, 0),
        )
    column(camera, preset_row)
    gap(camera, 8)
    for index, (caption, description) in enumerate(
        (
            ("Camera Distance", "Offset: negative = farther, positive = closer."),
            ("Shoulder Offset", "Horizontal distance from your character."),
            ("Camera Height", "Vertical offset from the normal camera."),
        )
    ):
        slider_row(camera, state, index, caption, description, options[index], numeric=("player", state))
    column(
        camera,
        text(camera, "F6  SWITCH SHOULDER    /    CHANGES APPLY LIVE", state, 13, DIM),
    )
    heading(vehicle, 'VEHICLE CAMERA', 'Position your vehicle camera independently of your character.', state, 24, 12)
    vehicle_state = dict(fonts=state['fonts'], template=state['template'],
                         sliders=[], labels=[], progress=[], ranges=[], values=[], dirty=False)
    state['vehicle_view'] = vehicle_state
    state['vehicle_options'] = vehicle_options
    preset_row = new('HorizontalBox', vehicle)
    row(preset_row, text(preset_row, 'Vehicle Preset', state, 18, title=True), fill=True, center=True)
    for name in VEHICLE_PRESETS:
        row(preset_row, button(preset_row, name, state, 'vehicle:'+name, 120, 46, CREAM, label_size=15), padding=margin(6,0,0,0))
    column(vehicle, preset_row)
    gap(vehicle, 10)
    for index, (caption, description, option) in enumerate(zip(
            ('Distance (X)', 'Side (Y)', 'Height (Z)'),
            ('Positive = closer; negative = farther.',
             'Positive = right; negative = left; zero = centered.',
             'Positive = higher; negative = lower.'), vehicle_options)):
        slider_row(vehicle, vehicle_state, index, caption, description, option, VEHICLE_RANGES[index], compact=True, numeric=("vehicle", state))
    column(vehicle, text(vehicle, 'Saved separately / changes apply live in your vehicle.', state, 13, DIM))
    state['vehicle_finalize'] = lambda read_widgets: commit_vehicle(state, read_widgets=read_widgets)
    state['get_vehicle_control'] = get_vehicle_control or (lambda: False)
    state['set_vehicle_control'] = set_vehicle_control or (lambda value: None)
    controls = new('HorizontalBox', vehicle)
    state['vehicle_control_label'] = text(controls, vehicle_control_caption(state), state, 17, title=True)
    row(controls, state['vehicle_control_label'], fill=True, center=True)
    row(controls, button(controls, 'SWITCH', state, 'vehicle:control_mode', 110, 46, GOLD, label_size=15))
    column(vehicle, controls, padding=margin(0, 10, 0, 0))
    column(vehicle, text(vehicle, 'Camera-relative: WASD / left stick drive; mouse / right stick look.', state, 12, DIM))

    heading(
        aiming,
        "CAMERA MODES",
        "Choose the view for special gameplay situations.",
        state,
    )
    state["get_sniper_mode"] = get_sniper_mode or (lambda: False)
    state["set_sniper_mode"] = set_sniper_mode or (lambda value: None)
    sniper_row = new("HorizontalBox", aiming)
    state["sniper_label"] = text(
        sniper_row,
        "Sniper ADS: " + ("TPS" if state["get_sniper_mode"]() else "FPS"),
        state,
        22,
        title=True,
    )
    row(sniper_row, state["sniper_label"], fill=True, center=True)
    row(
        sniper_row,
        button(sniper_row, "SWITCH VIEW", state, "modes:sniper", 230, 50, GOLD),
    )
    column(aiming, sniper_row)
    gap(aiming, 10)
    column(
        aiming,
        text(
            aiming,
            "Applies on the next ADS entry or observed weapon change.",
            state,
            14,
            DIM,
        ),
    )
    gap(aiming, 24)
    state["get_ffyl_mode"] = get_ffyl_mode or (lambda: False)
    state["set_ffyl_mode"] = set_ffyl_mode or (lambda value: None)
    ffyl_row = new("HorizontalBox", aiming)
    state["ffyl_label"] = text(
        ffyl_row,
        "TPS-FFYL (Beta): " + ("ON" if state["get_ffyl_mode"]() else "OFF"),
        state,
        22,
        title=True,
    )
    row(ffyl_row, state["ffyl_label"], fill=True, center=True)
    row(ffyl_row, button(ffyl_row, "TOGGLE", state, "modes:ffyl", 230, 50, GOLD))
    column(aiming, ffyl_row)
    gap(aiming, 10)
    column(
        aiming,
        text(
            aiming,
            "Beta: third-person FFYL with camera collision. OFF uses FPS.",
            state,
            14,
            DIM,
        ),
    )
    gap(aiming, 20)
    state["get_ground_slam_mode"] = get_ground_slam_mode or (lambda: True)
    state["set_ground_slam_mode"] = set_ground_slam_mode or (lambda value: None)
    slam_row = new("HorizontalBox", aiming)
    state["ground_slam_label"] = text(
        slam_row,
        "TPS Ground Slam (Beta): "
        + ("ON" if state["get_ground_slam_mode"]() else "OFF"),
        state,
        22,
        title=True,
    )
    row(slam_row, state["ground_slam_label"], fill=True, center=True)
    row(slam_row, button(slam_row, "TOGGLE", state, "modes:ground_slam", 230, 50, GOLD))
    column(aiming, slam_row)
    gap(aiming, 10)
    column(
        aiming,
        text(
            aiming,
            "Beta: preserves your aim during TPS Ground Slam. OFF uses FPS.",
            state,
            14,
            DIM,
        ),
    )
    gap(aiming, 24)
    heading(
        aiming,
        "MOVEMENT (EXPERIMENTAL)",
        "Your character turns toward the direction you move in third person.",
        state,
        24,
        12,
    )
    state["get_omni_movement"] = get_omni_movement or (lambda: False)
    state["set_omni_movement"] = set_omni_movement or (lambda value: None)
    state["omni_movement_caption"] = omni_movement_caption or (
        lambda: "ON" if state["get_omni_movement"]() else "OFF"
    )
    omni_row = new("HorizontalBox", aiming)
    state["omni_label"] = text(omni_row, omni_caption(state), state, 22, title=True)
    row(omni_row, state["omni_label"], fill=True, center=True)
    row(omni_row, button(omni_row, "TOGGLE", state, "modes:omni", 230, 50, GOLD))
    column(aiming, omni_row)
    gap(aiming, 10)
    column(
        aiming,
        text(
            aiming,
            "Manual Sprint; Sprint again while sprinting dashes. Uses your game key mappings.",
            state,
            14,
            DIM,
        ),
    )
    gap(aiming, 16)
    state["get_hybrid_ads"] = get_hybrid_ads or (lambda: False)
    state["set_hybrid_ads"] = set_hybrid_ads or (lambda value: None)
    hybrid_row = new("HorizontalBox", aiming)
    state["hybrid_ads_label"] = text(hybrid_row, hybrid_caption(state), state, 22, title=True)
    row(hybrid_row, state["hybrid_ads_label"], fill=True, center=True)
    row(hybrid_row, button(hybrid_row, "TOGGLE", state, "modes:hybrid_ads", 230, 50, GOLD))
    column(aiming, hybrid_row)
    gap(aiming, 10)
    column(
        aiming,
        text(
            aiming,
            "Omni only: hold ADS to aim over the shoulder; Sprint while aiming toggles the scope.",
            state,
            14,
            DIM,
        ),
    )
    from .motion_settings import GROUPS, DEFAULTS as MOTION_DEFAULTS, MotionOption

    parameters = (
        motion_parameters if motion_parameters is not None else dict(MOTION_DEFAULTS)
    )
    state["motion_parameters"] = parameters
    state["motion_defaults"] = MOTION_DEFAULTS
    state["motion_reset"] = reset_motion
    state["motion_save"] = save_motion
    state["motion_page"] = 0
    state["motion_views"] = []
    heading(
        motion,
        "CAMERA MOTION",
        "Changes apply live / saved when you close.",
        state,
        24,
        12,
    )
    status_row = new("HorizontalBox", motion)
    state["dynamic_motion_label"] = text(
        status_row,
        "Dynamic Camera Motion: " + ("ON" if dynamic_motion_enabled else "OFF"),
        state,
        20,
        title=True,
    )
    row(status_row, state["dynamic_motion_label"], fill=True, center=True)
    row(
        status_row,
        button(
            status_row, "TOGGLE CAMERA MOTION", state, "dynamic_motion", 270, 50, GOLD
        ),
    )
    column(motion, status_row)
    gap(motion, 4)
    navigation = new("HorizontalBox", motion)
    row(navigation, button(navigation, "PREV", state, "motion:prev", 85, 50))
    state["motion_heading"] = text(navigation, "1 / 6  MOVEMENT", state, 18, title=True)
    row(
        navigation,
        state["motion_heading"],
        fill=True,
        center=True,
        padding=margin(12, 0, 12, 0),
    )
    row(navigation, button(navigation, "NEXT", state, "motion:next", 85, 50))
    column(motion, navigation)
    gap(motion, 4)
    motion_switcher = new("WidgetSwitcher", motion)
    state["motion_switcher"] = motion_switcher
    column(motion, motion_switcher)
    for title, specs in GROUPS:
        page = new("VerticalBox", motion_switcher)
        motion_switcher.AddChild(page)
        substate = dict(
            fonts=state["fonts"],
            template=state["template"],
            sliders=[],
            labels=[],
            progress=[],
            ranges=[],
            values=[],
            dirty=False,
        )
        options_for_page = []
        for index, (key, caption, description, default, lo, hi) in enumerate(specs):
            option = MotionOption(parameters, key)
            options_for_page.append(option)
            slider_row(
                page,
                substate,
                index,
                caption,
                description,
                option,
                (lo, hi),
                0.5 if key == "baseline" else 1.0,
                compact=True,
                numeric=(f"motion:{len(state['motion_views'])}", state),
            )
        state["motion_views"].append((title, substate, tuple(options_for_page)))
    motion_switcher.SetActiveWidgetIndex(0)
    state["buttons"]["motion:prev"][0].SetIsEnabled(False)
    state["motion_finalize"] = lambda read_widgets: finalize_motion(state, read_widgets)
    if camera_features is not None:
        from . import menu_camera_features
        menu_camera_features.build(camera, ads, state, camera_features)
    state["debug_actions"] = debug_actions or {}
    state["debug_status"] = debug_status or (lambda: {})
    state["debug_action_labels"] = {}
    heading(debug, "DEBUG & DIAGNOSTICS", "Actions close this menu. Results appear in the SDK log.", state, 26, 13)
    for key, caption, description in (
        ("perf", "PERFORMANCE", "Start a bounded capture; reopen this tab to stop and print the report."),
        ("slide_perf", "SLIDE TIMING", "Capture one bounded slide timing window; repeat to print its report."),
        ("camera", "CAMERA STATE", "Print the current camera and offset data."),
        ("slide", "SLIDE STATE", "Print the current slide state and camera data."),
        ("gameplay", "GAMEPLAY STATE", "Print the current gameplay and native-owner diagnostics."),
        ("repair", "REPAIR CAMERA", "Use the existing TPS repair; native camera routes may refuse repair."),
    ):
        action_row = new("HorizontalBox", debug)
        words = new("VerticalBox", action_row)
        column(words, text(words, caption, state, 18, title=True))
        column(words, text(words, description, state, 12, DIM))
        row(action_row, words, fill=True, center=True)
        row(action_row, button(action_row, "RUN", state, "debug:" + key, 125, 42, GOLD, label_size=13))
        state["debug_action_labels"][key] = state["buttons"]["debug:" + key][2]
        state["buttons"]["debug:" + key][0].SetIsEnabled(key in state["debug_actions"])
        column(debug, action_row, padding=margin(0, 0, 0, 12))
    state["numeric_finalize"] = lambda: apply_numeric_inputs(state, options, force=True)
    refresh_debug_status(state)
    column(layout, sized(layout, border(layout, INK), height=4))
    footer = border(layout, HEADER, margin(16, 8, 16, 8))
    footer.SetBrushColor(linear(HEADER, 0.0))
    footer_row = new("HorizontalBox", footer)
    footer.SetContent(footer_row)
    state["notice"] = text(footer_row, "BUILD 0.3.8.14 / QA", state, 12, DIM)
    row(footer_row, state["notice"], fill=True, center=True)
    for key, caption, width, color in (
        ("reset", "RESET THIS CATEGORY", 220, CREAM),
        ("defaults", "RESTORE ALL DEFAULTS", 250, ORANGE),
    ):
        row(
            footer_row,
            button(footer_row, caption, state, key, width, accent=color),
            padding=margin(10, 0, 0, 0),
            center=True,
        )
    column(layout, sized(layout, footer, height=70))
    frame_art = picture(layers, state, "console_frame.png")
    if frame_art is not None:
        art_slot = layers.AddChildToOverlay(frame_art)
        art_slot.SetHorizontalAlignment(enum("EHorizontalAlignment", "HAlign_Fill"))
        art_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Fill"))
    close_widget = button(layers, "CLOSE  X", state, "close", 140, 52, ORANGE, label_size=18)
    close_slot = layers.AddChildToOverlay(close_widget)
    close_slot.SetHorizontalAlignment(enum("EHorizontalAlignment", "HAlign_Right"))
    close_slot.SetVerticalAlignment(enum("EVerticalAlignment", "VAlign_Top"))
    close_slot.SetPadding(margin(0, 48, 18, 0))
    state["close"] = state["buttons"]["close"][0]
    switcher.SetActiveWidgetIndex(0)
    paint_button(state, "nav:0", True)
    paint_button(state, "close", False)
    show_presets(state)
    commit_vehicle(state, read_widgets=False)
    logging.info(
        "[BL4ThirdPersonPOC] CONSOLE_VIEW fonts="
        + "+".join(state["fonts"])
        + f" images={len(state['textures'])}"
    )
    return sdk.make_struct(
        "GameViewportWidgetSlot",
        ZOrder=1000,
        bAutoRemoveOnWorldRemoved=True,
        Anchors=sdk.make_struct(
            "Anchors", Minimum=vector(0.06, 0.08), Maximum=vector(0.94, 0.92)
        ),
        Alignment=vector(0, 0),
        Offsets=margin(),
    )


def quantized(value: float, lo: float, hi: float, step: float = 1.0) -> float:
    if not math.isfinite(value):
        raise ValueError("Non-finite camera setting")
    rounded_value = math.copysign(math.floor(abs(value) / step + 0.5), value) * step
    return max(lo, min(hi, rounded_value))


def commit_motion(state: dict[str, Any], read_widgets: bool = True) -> None:
    changed = False
    for _title, view, options in state.get("motion_views", []):
        for index, option in enumerate(options):
            lo, hi = view["ranges"][index]
            raw = view["sliders"][index].GetValue() if read_widgets else option.value
            value = quantized(float(raw), lo, hi, view["increments"][index])
            if value != view["values"][index] or value != option.value:
                option.value = value
                view["values"][index] = value
                view["sliders"][index].SetValue(float(value))
                set_numeric_label(view, index, value)
                view["progress"][index].SetPercent((value - lo) / (hi - lo))
                changed = True
    if changed:
        state["motion_dirty"] = True
        if state.get("motion_reset"):
            state["motion_reset"]()


def finalize_motion(state: dict[str, Any], read_widgets: bool) -> None:
    if read_widgets:
        commit_motion(state)
    if state.get("motion_dirty") and state.get("motion_save"):
        state["motion_save"]()
        state["motion_dirty"] = False


def reset_motion_controls(state: dict[str, Any]) -> None:
    state["motion_parameters"].update(state["motion_defaults"])
    commit_motion(state, False)
    state["motion_dirty"] = True


def rounded(value: float, lo: int, hi: int) -> int:
    if not math.isfinite(value):
        raise ValueError("Non-finite camera setting")
    return max(lo, min(hi, int(math.copysign(math.floor(abs(value) + 0.5), value))))


def show_presets(state: dict[str, Any]) -> None:
    current = tuple(state["values"])
    for name, values in PRESETS.items():
        paint_button(state, f"preset:{name}", current == values)


def commit(
    state: dict[str, Any], options: tuple[Any, ...], values: tuple[int, ...]
) -> None:
    for index, (option, raw) in enumerate(zip(options, values)):
        lo, hi = RANGES[index]
        value = rounded(float(raw), lo, hi)
        if value != state["values"][index] or float(option.value) != value:
            option.value = value
            state["dirty"] = True
        state["values"][index] = value
        state["sliders"][index].SetValue(float(value))
        set_numeric_label(state, index, value)
        state["progress"][index].SetPercent((value - lo) / (hi - lo))
    show_presets(state)


def commit_vehicle(state, values=None, *, read_widgets=True):
    view = state.get('vehicle_view')
    options = state.get('vehicle_options', ())
    if view is None or len(options) != 3:
        return
    polling = values is None and read_widgets
    if values is None:
        values = tuple(slider.GetValue() for slider in view['sliders']) if read_widgets else tuple(view['values'])
    checked = tuple(rounded(float(raw), *limits) for raw, limits in zip(values, VEHICLE_RANGES))
    if polling and checked == tuple(view['values']):
        return
    if len(checked) != 3:
        raise ValueError('Three vehicle settings required')
    for i, (option, value, (lo, hi)) in enumerate(zip(options, checked, VEHICLE_RANGES)):
        if float(option.value) != value or view['values'][i] != value:
            state['dirty'] = True
        option.value = value
        view['values'][i] = value
        view['sliders'][i].SetValue(float(value))
        set_numeric_label(view, i, value)
        view['progress'][i].SetPercent((value-lo)/(hi-lo))
    if view.get('dirty'):
        state['dirty'] = True
        view['dirty'] = False
    for name, preset in VEHICLE_PRESETS.items():
        paint_button(state, 'vehicle:'+name, checked == preset)


def vehicle_control_caption(state):
    return "Driving: " + ("CAMERA-RELATIVE" if state['get_vehicle_control']() else "ORIGINAL")


def numeric_has_focus(field):
    # EditableTextBox can delegate Slate focus to its inner editable widget.
    # Probe both direct focus and descendant focus without assuming one path.
    supported = False
    for name in ("HasKeyboardFocus", "HasAnyUserFocus", "HasFocusedDescendants"):
        try:
            method = getattr(field, name)
        except AttributeError:
            continue
        supported = True
        if method():
            return True
    if not supported:
        raise RuntimeError("EditableTextBox exposes no supported focus query")
    return False


def set_numeric_label(view, index, value):
    if index not in view.get("editing", set()):
        view["labels"][index].SetText(format(value, "g"))


def apply_numeric_inputs(state, options, *, force=False):
    history = state.setdefault("numeric_focus", {})
    actions = []
    # Read drafts before committing any one view, so a commit cannot alter them.
    for key, (scope, index, field, view) in state.get("numeric_inputs", {}).items():
        focused = numeric_has_focus(field) if not force else False
        previous = history.get(key, False)
        history[key] = focused
        editing = view.setdefault("editing", set())
        if focused:
            editing.add(index)
        else:
            editing.discard(index)
        raw = str(field.GetText()).strip().replace(",", ".")
        if (previous and not focused) or (force and raw != format(view["values"][index], "g")):
            actions.append((scope, index, field, view, raw))
    for scope, index, field, view, raw in actions:
        try:
            limits = view["ranges"][index]
            value = (quantized(float(raw), *limits, view["increments"][index])
                     if scope not in ("player", "vehicle") else rounded(float(raw), *limits))
        except (ValueError, OverflowError):
            field.SetText(format(view["values"][index], "g"))
            logging.warning(f"[BL4ThirdPersonPOC] MENU_INPUT_REJECTED scope={scope} axis={index}")
            continue
        values = list(view["values"])
        values[index] = value
        commit_numeric_view(state, options, scope, view, values)


def commit_numeric_view(state, options, scope, view, values):
    if scope == "player":
        commit(state, options, tuple(values))
    elif scope == "vehicle":
        commit_vehicle(state, tuple(values))
    elif scope.startswith('feature:'):
        entry = next(item for item in state['feature_views'] if item[0] == scope)
        commit_feature_values(state, view, entry[2], values)
    else:
        motion_index = int(scope.split(":")[1])
        _title, motion_view, motion_options = state["motion_views"][motion_index]
        commit_motion_values(state, motion_view, motion_options, values)


def apply_step_buttons(state, options):
    """Use the same validated commit route as sliders and numeric fields."""
    for scope, index, field, view in state.get("numeric_inputs", {}).values():
        for name, direction in (("minus", -1), ("plus", 1)):
            if clicked(state, f"step:{scope}:{index}:{name}"):
                values = list(view["values"])
                step = view["increments"][index]
                values[index] = quantized(values[index] + direction * step,
                                          *view["ranges"][index], step)
                # Explicit stepping replaces this field's draft; other drafts stay.
                view.setdefault("editing", set()).discard(index)
                commit_numeric_view(state, options, scope, view, values)


def read_slider_changes(state):
    changes = []
    views = [("player", state)]
    if state.get("vehicle_view") is not None:
        views.append(("vehicle", state["vehicle_view"]))
    views.extend((scope, view) for scope, view, _options in state.get('feature_views', []))
    views.extend((f"motion:{index}", view)
                 for index, (_title, view, _options) in enumerate(state.get("motion_views", [])))
    for scope, view in views:
        values = tuple(quantized(float(slider.GetValue()), *view["ranges"][index],
                                 view["increments"][index])
                       for index, slider in enumerate(view["sliders"]))
        if values != tuple(view["values"]):
            changes.append((scope, view, values))
    return changes


def commit_motion_values(state, view, options, values):
    changed = False
    for index, (option, raw) in enumerate(zip(options, values)):
        lo, hi = view["ranges"][index]
        value = quantized(float(raw), lo, hi, view["increments"][index])
        if value != view["values"][index] or value != option.value:
            changed = True
        option.value = value
        view["values"][index] = value
        view["sliders"][index].SetValue(float(value))
        set_numeric_label(view, index, value)
        view["progress"][index].SetPercent((value - lo) / (hi - lo))
    if changed:
        state["motion_dirty"] = True
        if state.get("motion_reset"):
            state["motion_reset"]()



def commit_feature_values(state, view, options, values):
    for index, (option, raw) in enumerate(zip(options, values)):
        value = quantized(float(raw), *view['ranges'][index], view['increments'][index])
        if value != option.value or value != view['values'][index]:
            state['dirty'] = True
        option.value = value
        view['values'][index] = value
        view['sliders'][index].SetValue(float(value))
        set_numeric_label(view, index, value)
        lo, hi = view['ranges'][index]
        view['progress'][index].SetPercent((value-lo)/(hi-lo))


def refresh_debug_status(state):
    statuses = state["debug_status"]()
    for key in ("perf", "slide_perf"):
        label = state["debug_action_labels"].get(key)
        if label is not None:
            label.SetText(statuses.get(key, "START"))


def dispatch_debug(state, close):
    for key, callback in state.get("debug_actions", {}).items():
        if clicked(state, "debug:" + key):
            close("button")
            try:
                result = callback()
                logging.info(f"[BL4ThirdPersonPOC] MENU_DEBUG_ACTION action={key} result={result}")
            except Exception as error:
                logging.error(f"[BL4ThirdPersonPOC] MENU_DEBUG_FAILED action={key}: {error}")
            return True
    return False


def reset_vehicle_control(state):
    state['set_vehicle_control'](False)
    state['vehicle_control_label'].SetText(vehicle_control_caption(state))


def omni_caption(state):
    return "Omni Movement: " + state["omni_movement_caption"]()


def hybrid_caption(state):
    return "Hybrid ADS Mode: " + ("ON" if state["get_hybrid_ads"]() else "OFF")


def set_hybrid(state, value):
    state["set_hybrid_ads"](value)
    state["hybrid_ads_label"].SetText(hybrid_caption(state))


def set_omni(state, value):
    # The setter only persists a choice that took effect; the label shows the result.
    state["set_omni_movement"](value)
    state["omni_label"].SetText(omni_caption(state))


def dispatch(
    state: dict[str, Any],
    options: tuple[Any, ...],
    close: Callable[..., Any],
    get_dynamic_motion: Callable[[], bool],
    set_dynamic_motion: Callable[[bool], Any],
) -> None:
    """Called solely by GG's existing animation event while this menu is open."""
    # Preserve actual slider movement across a simultaneous text focus loss.
    slider_changes = read_slider_changes(state)
    apply_numeric_inputs(state, options)
    for scope, view, values in slider_changes:
        commit_numeric_view(state, options, scope, view, values)
    apply_step_buttons(state, options)
    if state.get('feature_dispatch'):
        state['feature_dispatch']()
    if state["page"] == 5:
        refresh_debug_status(state)
        if dispatch_debug(state, close):
            return
    if clicked(state, 'vehicle:control_mode'):
        state['set_vehicle_control'](not state['get_vehicle_control']())
        state['vehicle_control_label'].SetText(vehicle_control_caption(state))
    if clicked(state, "close"):
        finalize_motion(state, True)
        close("button")
        return
    for index in range(6):
        if clicked(state, f"nav:{index}"):
            state["page"] = index
            state["switcher"].SetActiveWidgetIndex(index)
            for other in range(6):
                paint_button(state, f"nav:{other}", other == index)
            state["buttons"]["reset"][0].SetIsEnabled(index != 5)
    for direction, delta in (("prev", -1), ("next", 1)):
        if clicked(state, "motion:" + direction):
            index = max(
                0, min(len(state["motion_views"]) - 1, state["motion_page"] + delta)
            )
            state["motion_page"] = index
            state["motion_switcher"].SetActiveWidgetIndex(index)
            state["motion_heading"].SetText(
                f"{index + 1} / {len(state['motion_views'])}  {state['motion_views'][index][0]}"
            )
            state["buttons"]["motion:prev"][0].SetIsEnabled(index > 0)
            state["buttons"]["motion:next"][0].SetIsEnabled(
                index < len(state["motion_views"]) - 1
            )
    for name, values in PRESETS.items():
        if clicked(state, f"preset:{name}"):
            commit(state, options, values)
    for name, preset in VEHICLE_PRESETS.items():
        if clicked(state, 'vehicle:'+name):
            commit_vehicle(state, preset)
    if clicked(state, "modes:sniper"):
        state["set_sniper_mode"](not state["get_sniper_mode"]())
        state["sniper_label"].SetText(
            "Sniper ADS: " + ("TPS" if state["get_sniper_mode"]() else "FPS")
        )
    if clicked(state, "modes:ffyl"):
        state["set_ffyl_mode"](not state["get_ffyl_mode"]())
        state["ffyl_label"].SetText(
            "TPS-FFYL (Beta): " + ("ON" if state["get_ffyl_mode"]() else "OFF")
        )
    if clicked(state, "modes:omni"):
        set_omni(state, not state["get_omni_movement"]())
    if clicked(state, "modes:hybrid_ads"):
        set_hybrid(state, not state["get_hybrid_ads"]())
    if clicked(state, "modes:ground_slam"):
        state["set_ground_slam_mode"](not state["get_ground_slam_mode"]())
        state["ground_slam_label"].SetText(
            "TPS Ground Slam (Beta): "
            + ("ON" if state["get_ground_slam_mode"]() else "OFF")
        )
    if clicked(state, "dynamic_motion"):
        set_dynamic_motion(not get_dynamic_motion())
        state["dynamic_motion_label"].SetText(
            "Dynamic Camera Motion: " + ("ON" if get_dynamic_motion() else "OFF")
        )
    if clicked(state, "reset"):
        if state["page"] == 0:
            commit(state, options, DEFAULTS)
            if state.get('feature_reset'):
                state['feature_reset']('shoulder')
        elif state["page"] == 1:
            state["set_sniper_mode"](False)
            state["sniper_label"].SetText("Sniper ADS: FPS")
            state["set_ffyl_mode"](True)
            state["set_ground_slam_mode"](True)
            state["ground_slam_label"].SetText(
                "TPS Ground Slam (Beta): "
                + ("ON" if state["get_ground_slam_mode"]() else "OFF")
            )
            state["ffyl_label"].SetText(
                "TPS-FFYL (Beta): " + ("ON" if state["get_ffyl_mode"]() else "OFF")
            )
            if state["get_omni_movement"]():
                set_omni(state, False)
            if state.get("get_hybrid_ads", lambda: False)():
                set_hybrid(state, False)
        elif state["page"] == 2:
            reset_motion_controls(state)
            set_dynamic_motion(False)
            state["dynamic_motion_label"].SetText("Dynamic Camera Motion: OFF")
        elif state['page'] == 3:
            commit_vehicle(state, VEHICLE_DEFAULTS)
            reset_vehicle_control(state)
        elif state['page'] == 4 and state.get('feature_reset'):
            state['feature_reset']('ads')
    if clicked(state, "defaults"):
        state["set_sniper_mode"](False)
        state["sniper_label"].SetText("Sniper ADS: FPS")
        state["set_ffyl_mode"](True)
        state["set_ground_slam_mode"](True)
        state["ground_slam_label"].SetText(
            "TPS Ground Slam (Beta): "
            + ("ON" if state["get_ground_slam_mode"]() else "OFF")
        )
        state["ffyl_label"].SetText(
            "TPS-FFYL (Beta): " + ("ON" if state["get_ffyl_mode"]() else "OFF")
        )
        reset_motion_controls(state)
        commit(state, options, DEFAULTS)
        commit_vehicle(state, VEHICLE_DEFAULTS)
        reset_vehicle_control(state)
        if state["get_omni_movement"]():
            set_omni(state, False)
        if state.get("get_hybrid_ads", lambda: False)():
            set_hybrid(state, False)
        set_dynamic_motion(False)
        state["dynamic_motion_label"].SetText("Dynamic Camera Motion: OFF")
        if state.get('feature_reset'):
            state['feature_reset']()
        state["notice"].SetText("Camera + vehicle + modes + motion + ADS defaults restored")
