"""Observed colors and safe options for the three built-in color effects."""

COLOR_EFFECT_IDS = {(5, 0), (34, 0), (39, 0)}
SOLID_COLOR_EFFECT = "Solid color"


def is_color_effect(state: dict) -> bool:
    """Animation colors are distinct from the uniform HSV mode."""
    return (
        not state["music"].get("on")
        and state.get("color_mode") == 14
        and tuple(state["effect"][:2]) in COLOR_EFFECT_IDS
    )


def effect_colors(state: dict) -> list[tuple[int, int, int]] | None:
    """Decode signed/unsigned ARGB readback, ignoring zero padding slots."""
    if not is_color_effect(state) or len(state["effect"]) < 3:
        return None
    options = state["effect"][2]
    colors = options.get("color") if isinstance(options, dict) else None
    if (
        not isinstance(colors, list)
        or not 1 <= len(colors) <= 4
        or any(type(value) is not int or not -(2**31) <= value < 2**32 for value in colors)
    ):
        return None
    return [((value >> 16) & 255, (value >> 8) & 255, value & 255) for value in colors if value != 0] or None


def color_options(state: dict, preset: dict, rgb: tuple[int, int, int]) -> dict:
    """Keep a confirmed speed; never replay normalized renderer fields."""
    options = {key: value for key, value in preset["options"].items() if key == "rate"}
    if (
        is_color_effect(state)
        and state["effect"][:2] == [preset["effect_id"], preset["custom_id"]]
        and len(state["effect"]) > 2
        and isinstance(observed := state["effect"][2], dict)
        and type(rate := observed.get("rate")) is int
        and 0 <= rate <= 255
    ):
        options["rate"] = rate
    red, green, blue = rgb
    options["color"] = [0xFF000000 | red << 16 | green << 8 | blue]
    return options
