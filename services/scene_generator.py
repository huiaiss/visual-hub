"""Creative Scene Generator — turns scene descriptions into background images.

Pipeline:
  creative_brief.scenes[] → parse keywords → procedural generation → scene background PNG

Supports:
- 12 scene archetypes with procedural generation strategies
- Custom color palette injection from creative brief
- L1 fallback scene auto-generation
- Scene caching for reuse across batch jobs
- Output: 1080×1920 (portrait) or 1920×1080 (landscape) PNG backgrounds

Technical approach:
  Procedural generation using Pillow — gradients, noise, geometric shapes, textures.
  Designed to run without GPU, no external APIs needed for MVP.
  SeedDream/ChatGPT image generation can be plugged in later as a SceneGenerator backend.
"""

import hashlib
import json
import logging
import os
import random
from dataclasses import dataclass, field
from PIL import Image, ImageDraw, ImageFilter, ImageOps
import numpy as np

from config import Config

logger = logging.getLogger(__name__)

# ============ Scene Archetypes ============

SCENE_ARCHETYPES = {
    "窗边白墙": {
        "keywords": ["窗边", "白墙", "自然光", "窗台", "窗户", "窗"],
        "strategy": "window_wall",
        "palette": {"wall": "#F5F0E8", "light": "#FFF8E7", "shadow": "#E8E0D5", "window": "#B8D4E8"},
    },
    "小区路面": {
        "keywords": ["小区", "路面", "花坛", "户外", "地面", "路", "砖", "步道"],
        "strategy": "outdoor_path",
        "palette": {"ground": "#C4B5A5", "path": "#B8A898", "leaf": "#6B8E5A", "sky": "#D4E4F0"},
    },
    "办公桌旁": {
        "keywords": ["办公桌", "桌子", "茶几", "书桌", "桌面", "木桌"],
        "strategy": "desk_surface",
        "palette": {"surface": "#D4C4A8", "edge": "#B8A080", "bg": "#F0E8D8", "accent": "#8B7355"},
    },
    "对镜自拍": {
        "keywords": ["镜子", "对镜", "穿衣镜", "自拍", "镜面"],
        "strategy": "mirror_frame",
        "palette": {"frame": "#D4C4A8", "glass": "#E8F0F8", "wall": "#F0EBE3", "reflection": "#C8D8E8"},
    },
    "家门口": {
        "keywords": ["家门口", "走廊", "门", "玄关", "走廊"],
        "strategy": "doorway_hall",
        "palette": {"wall": "#F0EBE0", "floor": "#C8B898", "door": "#E8DCC8", "light": "#FFF5E8"},
    },
    "咖啡厅": {
        "keywords": ["咖啡厅", "咖啡", "奶茶店", "角落", "下午茶"],
        "strategy": "cafe_corner",
        "palette": {"table": "#8B6914", "wall": "#F5EDE0", "light": "#FFF0D0", "shadow": "#C8B898"},
    },
    "公园绿道": {
        "keywords": ["公园", "绿道", "树木", "草地", "花园", "植物"],
        "strategy": "park_path",
        "palette": {"ground": "#C8B898", "grass": "#7B9B5A", "trees": "#5A7B3A", "sky": "#C8DCF0"},
    },
    "停车场": {
        "keywords": ["停车场", "车库", "水泥地", "工业", "地下"],
        "strategy": "concrete_floor",
        "palette": {"floor": "#B0A898", "wall": "#C8C0B8", "line": "#E8E0D0", "shadow": "#908878"},
    },
    "商场走廊": {
        "keywords": ["商场", "走廊", "电梯", "室内", "购物中心"],
        "strategy": "mall_corridor",
        "palette": {"floor": "#E0D8C8", "wall": "#F0E8D8", "light": "#FFF8F0", "reflection": "#D8D0C0"},
    },
    "纯色背景": {
        "keywords": ["纯色", "背景布", "纯背景", "单色"],
        "strategy": "solid_backdrop",
        "palette": {"bg": "#F0EBE3", "floor": "#E8E0D5", "gradient": "#F5F2EB"},
    },
    "天台晚霞": {
        "keywords": ["天台", "晚霞", "日落", "天空", "黄昏", "夕阳"],
        "strategy": "sunset_rooftop",
        "palette": {"sky_top": "#4A6FA5", "sky_mid": "#E8945A", "sky_bot": "#F0C878", "ground": "#908878"},
    },
    "旧城区斑马线": {
        "keywords": ["旧城", "斑马线", "街区", "街头", "马路", "街道"],
        "strategy": "street_crosswalk",
        "palette": {"road": "#686868", "stripe": "#F0F0E8", "sidewalk": "#B8B0A0", "building": "#C8C0B0"},
    },
}

FALLBACK_SCENE = "窗边白墙"


# ============ Procedural Generators ============


def _noise_array(w: int, h: int, scale: float = 0.01, octaves: int = 3) -> np.ndarray:
    """Generate smooth Perlin-like noise array using simple frequency stacking."""
    noise = np.zeros((h, w), dtype=np.float32)
    for octave in range(octaves):
        freq = scale * (2 ** octave)
        amp = 1.0 / (2 ** octave)
        # Use a seeded random approach for pseudo-Perlin
        rng = np.random.RandomState(42 + octave)
        small_w = max(2, int(w * freq))
        small_h = max(2, int(h * freq))
        layer = rng.rand(small_h, small_w).astype(np.float32)
        # Upsample to full size
        layer_img = Image.fromarray((layer * 255).astype(np.uint8))
        layer_img = layer_img.resize((w, h), Image.BILINEAR)
        layer = np.array(layer_img, dtype=np.float32) / 255.0
        noise += layer * amp
    return (noise - noise.min()) / (noise.max() - noise.min() + 1e-8)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _interpolate_color(c1: tuple, c2: tuple, t: float) -> tuple:
    """Linear interpolate between two RGB colors."""
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _vertical_gradient(img: ImageDraw.ImageDraw, w: int, h: int, top: tuple, bottom: tuple):
    """Draw a vertical gradient on an image."""
    for y in range(h):
        t = y / h
        color = _interpolate_color(top, bottom, t)
        img.line([(0, y), (w, y)], fill=color)


def _radial_glow(draw: ImageDraw.ImageDraw, w: int, h: int, cx: int, cy: int, radius: int, color: tuple, opacity: float = 0.3):
    """Draw a soft radial glow."""
    for r in range(radius, 0, -5):
        alpha = int(255 * opacity * (r / radius))
        c = (*color, alpha)
        # Circle approximation with filled ellipse
        alpha_normalized = opacity * (r / radius) ** 1.5
        c_faded = _interpolate_color((255, 255, 255), color, alpha_normalized)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c_faded)


# ---- Individual Scene Strategies ----


def _gen_window_wall(w: int, h: int, palette: dict) -> Image.Image:
    """Window + white wall with natural side light."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["wall"]))
    draw = ImageDraw.Draw(img)

    # Wall texture — subtle noise
    noise = _noise_array(w, h, scale=0.005, octaves=2)
    noise_img = Image.fromarray((noise * 20).astype(np.uint8)).convert("L")
    wall_texture = Image.new("RGB", (w, h), _hex_to_rgb(palette["wall"]))
    textured = Image.blend(wall_texture, ImageOps.colorize(noise_img, "#000", "#FFF"), 0.03)
    img.paste(textured)

    # Window frame on the left side
    draw = ImageDraw.Draw(img)
    window_x = int(w * 0.05)
    window_w = int(w * 0.35)
    window_top = int(h * 0.05)
    window_bottom = int(h * 0.7)

    # Window light beam
    light_color = _hex_to_rgb(palette["light"])
    for i in range(window_w * 3):
        alpha = max(0, 1.0 - abs(i - window_w) / window_w)
        x = window_x + i
        if 0 <= x < w:
            c = _interpolate_color(_hex_to_rgb(palette["wall"]), light_color, alpha * 0.3)
            draw.line([(x, window_top), (x, h)], fill=c, width=1)

    # Window frame rect
    draw.rectangle([window_x, window_top, window_x + window_w, window_bottom], outline="#D8D0C0", width=3)
    # Window panes
    pane_mid_y = (window_top + window_bottom) // 2
    pane_mid_x = window_x + window_w // 2
    draw.line([(window_x, pane_mid_y), (window_x + window_w, pane_mid_y)], fill="#D8D0C0", width=2)
    draw.line([(pane_mid_x, window_top), (pane_mid_x, window_bottom)], fill="#D8D0C0", width=2)

    # Floor line
    floor_y = int(h * 0.78)
    draw.rectangle([(0, floor_y), (w, h)], fill=_hex_to_rgb(palette["shadow"]))
    # Floor/wall edge
    draw.line([(0, floor_y), (w, floor_y)], fill="#D0C8B8", width=2)

    # Subtle floor reflection
    for y in range(floor_y, h, 4):
        alpha = (y - floor_y) / (h - floor_y) * 0.15
        c = _interpolate_color(_hex_to_rgb(palette["shadow"]), light_color, alpha)
        draw.line([(0, y), (w, y)], fill=c)

    return img


def _gen_outdoor_path(w: int, h: int, palette: dict) -> Image.Image:
    """Outdoor ground with path and vegetation hints."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["ground"]))
    draw = ImageDraw.Draw(img)

    # Ground texture
    noise = _noise_array(w, h, scale=0.008, octaves=3)
    noise_img = Image.fromarray((noise * 40).astype(np.uint8)).convert("L")
    img = Image.blend(img, ImageOps.colorize(noise_img, "#000", "#FFF"), 0.08)

    draw = ImageDraw.Draw(img)

    # Sky gradient at top
    sky_color = _hex_to_rgb(palette["sky"])
    for y in range(int(h * 0.35)):
        t = y / (h * 0.35)
        c = _interpolate_color(sky_color, _hex_to_rgb(palette["ground"]), t)
        draw.line([(0, y), (w, y)], fill=c)

    # Path surface
    path_y = int(h * 0.45)
    path_color = _hex_to_rgb(palette["path"])
    draw.rectangle([(0, path_y), (w, h)], fill=path_color)

    # Green foliage hints (blurred circles at edges)
    leaf_color = _hex_to_rgb(palette["leaf"])
    for side in ["left", "right"]:
        x_base = 0 if side == "left" else w
        for i in range(3):
            cx = x_base + random.randint(-30, 80) * (1 if side == "left" else -1)
            cy = random.randint(int(h * 0.1), int(h * 0.5))
            r = random.randint(60, 150)
            foliage = Image.new("RGBA", (r * 3, r * 3), (0, 0, 0, 0))
            f_draw = ImageDraw.Draw(foliage)
            f_draw.ellipse([r, r, r * 2, r * 2], fill=(*leaf_color, 60))
            foliage = foliage.filter(ImageFilter.GaussianBlur(30))
            img.paste(foliage, (cx - r * 3 // 2, cy - r * 3 // 2), foliage)

    return img


def _gen_desk_surface(w: int, h: int, palette: dict) -> Image.Image:
    """Wooden desk surface with soft indoor lighting."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["bg"]))
    draw = ImageDraw.Draw(img)

    # Wood grain noise on desk surface
    desk_y = int(h * 0.5)
    noise = _noise_array(w, h - desk_y, scale=0.003, octaves=2)
    # Stretch noise horizontally for wood grain
    noise_stretched = np.zeros_like(noise)
    for y in range(noise.shape[0]):
        noise_stretched[y, :] = noise[y, :]
    noise_img = Image.fromarray((noise_stretched * 50).astype(np.uint8)).convert("L")
    desk_surface = Image.new("RGB", (w, h - desk_y), _hex_to_rgb(palette["surface"]))
    textured_desk = Image.blend(desk_surface, ImageOps.colorize(noise_img, "#000", "#FFF"), 0.05)

    # Desk edge highlight
    draw.rectangle([(0, desk_y), (w, h)], fill=_hex_to_rgb(palette["surface"]))
    img.paste(textured_desk, (0, desk_y))

    # Edge line
    draw.line([(0, desk_y), (w, desk_y)], fill=_hex_to_rgb(palette["edge"]), width=3)

    # Soft top lighting
    light_color = (255, 248, 235)
    for y in range(0, int(h * 0.5), 2):
        alpha = 1.0 - y / (h * 0.5)
        c = _interpolate_color(_hex_to_rgb(palette["bg"]), light_color, alpha * 0.08)
        draw.line([(0, y), (w, y)], fill=c)

    return img


def _gen_mirror_frame(w: int, h: int, palette: dict) -> Image.Image:
    """Full-length mirror on a wall."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["wall"]))
    draw = ImageDraw.Draw(img)

    # Mirror frame
    mirror_x = int(w * 0.15)
    mirror_w = int(w * 0.7)
    mirror_top = int(h * 0.05)
    mirror_bottom = int(h * 0.85)

    # Wooden frame
    frame_thick = 8
    draw.rectangle(
        [mirror_x - frame_thick, mirror_top - frame_thick,
         mirror_x + mirror_w + frame_thick, mirror_bottom + frame_thick],
        fill=_hex_to_rgb(palette["frame"])
    )

    # Glass surface
    draw.rectangle([mirror_x, mirror_top, mirror_x + mirror_w, mirror_bottom],
                   fill=_hex_to_rgb(palette["glass"]))

    # Subtle reflection gradient
    reflection_color = _hex_to_rgb(palette["reflection"])
    for y in range(mirror_top, mirror_bottom, 2):
        alpha = 0.05 + 0.05 * ((y - mirror_top) / (mirror_bottom - mirror_top))
        c = _interpolate_color(_hex_to_rgb(palette["glass"]), reflection_color, alpha)
        draw.line([(mirror_x, y), (mirror_x + mirror_w, y)], fill=c)

    # Floor
    floor_y = int(h * 0.85)
    draw.rectangle([(0, floor_y), (w, h)], fill=_hex_to_rgb(palette["wall"]))
    draw.line([(0, floor_y), (w, floor_y)], fill="#D8D0C0", width=2)

    return img


def _gen_doorway_hall(w: int, h: int, palette: dict) -> Image.Image:
    """Indoor doorway/corridor with perspective."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["wall"]))
    draw = ImageDraw.Draw(img)

    # Floor with perspective lines
    floor_y = int(h * 0.55)
    floor_color = _hex_to_rgb(palette["floor"])
    draw.rectangle([(0, floor_y), (w, h)], fill=floor_color)

    # Perspective lines on floor (vanishing point center-top)
    vp_x, vp_y = w // 2, int(h * -0.2)
    for i in range(8):
        x_offset = (i - 3.5) * w // 6
        start_x = int(vp_x + (x_offset - vp_x) * (floor_y / (floor_y - vp_y)))
        draw.line([(start_x, floor_y), (x_offset + w // 2, h)], fill=_interpolate_color(floor_color, (200, 190, 170), 0.3), width=1)

    # Wall-floor edge
    draw.line([(0, floor_y), (w, floor_y)], fill="#D0C8B8", width=2)

    # Door frame hint
    door_left = int(w * 0.3)
    door_right = int(w * 0.7)
    door_color = _hex_to_rgb(palette["door"])
    draw.rectangle([door_left, int(h * 0.1), door_right, floor_y], fill=door_color, outline="#D0C8B8", width=2)

    return img


def _gen_cafe_corner(w: int, h: int, palette: dict) -> Image.Image:
    """Cozy cafe corner with warm ambient lighting."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["wall"]))
    draw = ImageDraw.Draw(img)

    # Warm ambient glow (center-right)
    light_color = _hex_to_rgb(palette["light"])
    for y in range(h):
        dist_from_center = abs(y - h * 0.4) / (h * 0.6)
        alpha = max(0, 0.15 - dist_from_center * 0.12)
        c = _interpolate_color(_hex_to_rgb(palette["wall"]), light_color, alpha)
        draw.line([(0, y), (w, y)], fill=c)

    # Table surface
    table_y = int(h * 0.6)
    table_color = _hex_to_rgb(palette["table"])
    draw.rectangle([(0, table_y), (w, h)], fill=table_color)

    # Table wood grain
    noise = _noise_array(w, h - table_y, scale=0.004, octaves=2)
    noise_img = Image.fromarray((noise * 30).astype(np.uint8)).convert("L")
    table_texture = Image.blend(
        Image.new("RGB", (w, h - table_y), table_color),
        ImageOps.colorize(noise_img, "#000", "#FFF"), 0.06
    )
    img.paste(table_texture, (0, table_y))

    # Table edge
    draw.line([(0, table_y), (w, table_y)], fill="#7A5C14", width=3)

    return img


def _gen_park_path(w: int, h: int, palette: dict) -> Image.Image:
    """Park path with grass and trees."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["sky"]))
    draw = ImageDraw.Draw(img)

    # Sky
    sky_color = _hex_to_rgb(palette["sky"])
    for y in range(int(h * 0.35)):
        t = 1.0 - y / (h * 0.35)
        c = _interpolate_color((180, 210, 240), sky_color, t)
        draw.line([(0, y), (w, y)], fill=c)

    # Ground
    ground_y = int(h * 0.45)
    draw.rectangle([(0, ground_y), (w, h)], fill=_hex_to_rgb(palette["grass"]))

    # Path
    path_left = int(w * 0.25)
    path_right = int(w * 0.75)
    path_y = int(h * 0.55)
    draw.polygon(
        [(path_left, ground_y), (path_right, ground_y),
         (path_right + int(w * 0.05), h), (path_left - int(w * 0.05), h)],
        fill=_hex_to_rgb(palette["ground"])
    )

    # Tree blobs (blurred green circles)
    tree_color = _hex_to_rgb(palette["trees"])
    for i in range(5):
        cx = int(w * (0.1 + i * 0.2)) + random.randint(-30, 30)
        cy = random.randint(int(h * 0.05), int(h * 0.3))
        r = random.randint(80, 180)
        tree = Image.new("RGBA", (r * 3, r * 3), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(tree)
        t_draw.ellipse([r, r // 2, r * 2, r * 3 // 2], fill=(*tree_color, 50))
        tree = tree.filter(ImageFilter.GaussianBlur(25))
        img.paste(tree, (cx - r * 3 // 2, cy), tree)

    return img


def _gen_concrete_floor(w: int, h: int, palette: dict) -> Image.Image:
    """Concrete/industrial floor with parking lines."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["floor"]))
    draw = ImageDraw.Draw(img)

    # Concrete noise texture
    noise = _noise_array(w, h, scale=0.006, octaves=3)
    noise_img = Image.fromarray((noise * 35).astype(np.uint8)).convert("L")
    img = Image.blend(img, ImageOps.colorize(noise_img, "#000", "#FFF"), 0.06)

    draw = ImageDraw.Draw(img)

    # Wall at top
    wall_y = int(h * 0.2)
    draw.rectangle([(0, 0), (w, wall_y)], fill=_hex_to_rgb(palette["wall"]))
    draw.line([(0, wall_y), (w, wall_y)], fill="#A09888", width=2)

    # Parking line
    line_y = int(h * 0.55)
    line_color = _hex_to_rgb(palette["line"])
    draw.rectangle([(int(w * 0.1), line_y), (int(w * 0.9), line_y + 6)], fill=line_color)

    return img


def _gen_mall_corridor(w: int, h: int, palette: dict) -> Image.Image:
    """Shopping mall corridor with polished floor."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["wall"]))
    draw = ImageDraw.Draw(img)

    # Floor with reflection
    floor_y = int(h * 0.45)
    floor_color = _hex_to_rgb(palette["floor"])
    draw.rectangle([(0, floor_y), (w, h)], fill=floor_color)

    # Floor reflection (mirror gradient)
    for y in range(floor_y, h, 2):
        alpha = 0.03 + 0.07 * (1 - (y - floor_y) / (h - floor_y))
        c = _interpolate_color(floor_color, (255, 255, 250), alpha)
        draw.line([(0, y), (w, y)], fill=c)

    # Wall-floor edge
    draw.line([(0, floor_y), (w, floor_y)], fill="#D8D0C0", width=2)

    # Ceiling lights (soft spots)
    for i in range(3):
        cx = int(w * (0.2 + i * 0.3))
        cy = int(h * 0.08)
        _radial_glow(draw, w, h, cx, cy, 150, (255, 250, 240), opacity=0.15)

    return img


def _gen_solid_backdrop(w: int, h: int, palette: dict) -> Image.Image:
    """Clean solid backdrop with subtle gradient."""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    bg_color = _hex_to_rgb(palette["bg"])
    gradient_color = _hex_to_rgb(palette["gradient"])

    # Subtle top-to-bottom gradient
    for y in range(h):
        t = y / h
        c = _interpolate_color(gradient_color, bg_color, t)
        draw.line([(0, y), (w, y)], fill=c)

    # Floor hint at bottom
    floor_y = int(h * 0.8)
    floor_color = _hex_to_rgb(palette["floor"])
    draw.rectangle([(0, floor_y), (w, h)], fill=floor_color)
    draw.line([(0, floor_y), (w, floor_y)], fill="#D8D0C0", width=1)

    return img


def _gen_sunset_rooftop(w: int, h: int, palette: dict) -> Image.Image:
    """Rooftop at sunset with dramatic sky."""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    # Sunset sky gradient
    sky_top = _hex_to_rgb(palette["sky_top"])
    sky_mid = _hex_to_rgb(palette["sky_mid"])
    sky_bot = _hex_to_rgb(palette["sky_bot"])

    for y in range(int(h * 0.65)):
        if y < h * 0.25:
            t = y / (h * 0.25)
            c = _interpolate_color(sky_top, sky_mid, t)
        else:
            t = (y - h * 0.25) / (h * 0.4)
            c = _interpolate_color(sky_mid, sky_bot, t)
        draw.line([(0, y), (w, y)], fill=c)

    # Ground/rooftop surface
    ground_y = int(h * 0.65)
    ground_color = _hex_to_rgb(palette["ground"])
    draw.rectangle([(0, ground_y), (w, h)], fill=ground_color)

    # Rooftop edge
    draw.line([(0, ground_y), (w, ground_y)], fill="#706858", width=3)

    # Sun glow
    sun_x = int(w * 0.55)
    sun_y = int(h * 0.45)
    sun_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sun_draw = ImageDraw.Draw(sun_img)
    for r in range(120, 10, -3):
        alpha = int(40 * (r / 120))
        sun_draw.ellipse([sun_x - r, sun_y - r, sun_x + r, sun_y + r],
                         fill=(255, 220, 150, alpha))
    sun_img = sun_img.filter(ImageFilter.GaussianBlur(8))
    img.paste(sun_img, (0, 0), sun_img)

    return img


def _gen_street_crosswalk(w: int, h: int, palette: dict) -> Image.Image:
    """Street with crosswalk stripes."""
    img = Image.new("RGB", (w, h), _hex_to_rgb(palette["road"]))
    draw = ImageDraw.Draw(img)

    # Road texture
    noise = _noise_array(w, h, scale=0.007, octaves=2)
    noise_img = Image.fromarray((noise * 25).astype(np.uint8)).convert("L")
    img = Image.blend(img, ImageOps.colorize(noise_img, "#000", "#FFF"), 0.04)

    draw = ImageDraw.Draw(img)

    # Sidewalk
    sidewalk_y = int(h * 0.55)
    draw.rectangle([(0, sidewalk_y), (w, h)], fill=_hex_to_rgb(palette["sidewalk"]))

    # Crosswalk stripes (perspective)
    stripe_color = _hex_to_rgb(palette["stripe"])
    for i in range(6):
        ratio = i / 5
        x1 = int(w * 0.15 + ratio * w * 0.15)
        x2 = int(w * 0.85 - ratio * w * 0.15)
        stripe_top = int(h * 0.4 + ratio * 0.15 * h)
        stripe_h = 8
        draw.rectangle([x1, stripe_top, x2, stripe_top + stripe_h], fill=stripe_color)

    # Buildings hint
    building_color = _hex_to_rgb(palette["building"])
    draw.rectangle([(0, 0), (w, int(h * 0.4))], fill=building_color)

    return img


# Strategy dispatch
STRATEGY_MAP = {
    "window_wall": _gen_window_wall,
    "outdoor_path": _gen_outdoor_path,
    "desk_surface": _gen_desk_surface,
    "mirror_frame": _gen_mirror_frame,
    "doorway_hall": _gen_doorway_hall,
    "cafe_corner": _gen_cafe_corner,
    "park_path": _gen_park_path,
    "concrete_floor": _gen_concrete_floor,
    "mall_corridor": _gen_mall_corridor,
    "solid_backdrop": _gen_solid_backdrop,
    "sunset_rooftop": _gen_sunset_rooftop,
    "street_crosswalk": _gen_street_crosswalk,
}


# ============ Resolution Presets ============

RESOLUTIONS = {
    "portrait": (1080, 1920),   # 抖音/快手/小红书 竖版
    "landscape": (1920, 1080),  # 横版
    "square": (1080, 1080),     # 方版 (快手/视频号)
    "story": (1080, 1440),      # 抖音故事
}


# ============ Main Generator Functions ============


def _match_archetype(scene_name: str, scene_description: str) -> dict | None:
    """Match a scene description to the closest archetype."""
    combined = f"{scene_name} {scene_description}".lower()

    best_match = None
    best_score = 0

    for name, archetype in SCENE_ARCHETYPES.items():
        score = 0
        for kw in archetype["keywords"]:
            if kw.lower() in combined:
                score += 1
        if score > best_score:
            best_score = score
            best_match = archetype

    if best_score == 0:
        return SCENE_ARCHETYPES[FALLBACK_SCENE]
    return best_match


def _apply_custom_palette(archetype: dict, color_palette: dict | None) -> dict:
    """Override archetype palette with custom colors from creative brief."""
    if not color_palette:
        return archetype

    custom_palette = dict(archetype["palette"])

    primary = color_palette.get("primary", "")
    secondary = color_palette.get("secondary", "")
    accent = color_palette.get("accent", "")

    if primary:
        custom_palette["wall"] = primary
        custom_palette["bg"] = primary
    if secondary:
        custom_palette["light"] = secondary
        custom_palette["shadow"] = secondary
    if accent:
        custom_palette["accent"] = accent

    return {**archetype, "palette": custom_palette}


def generate_scene(
    scene_name: str,
    scene_description: str,
    color_palette: dict | None = None,
    resolution: str = "portrait",
) -> str:
    """Generate a single scene background image.

    Args:
        scene_name: Scene name from creative brief (e.g. "窗边白墙")
        scene_description: Scene description from creative brief
        color_palette: Optional color override from creative brief
        resolution: "portrait" | "landscape" | "square"

    Returns:
        Absolute path to generated scene PNG
    """
    w, h = RESOLUTIONS.get(resolution, RESOLUTIONS["portrait"])

    # Match to archetype
    archetype = _match_archetype(scene_name, scene_description)
    archetype = _apply_custom_palette(archetype, color_palette)

    strategy = archetype["strategy"]
    generator = STRATEGY_MAP.get(strategy)
    if not generator:
        logger.warning(f"Unknown strategy '{strategy}', falling back to solid_backdrop")
        generator = _gen_solid_backdrop
        archetype = SCENE_ARCHETYPES["纯色背景"]

    # Generate
    logger.info(f"Generating scene '{scene_name}' with strategy '{strategy}' at {w}×{h}")
    img = generator(w, h, archetype["palette"])

    # Save — descriptive filename for AssetPipeline keyword matching
    # Format: scene_{scene_name}_{strategy}_{short_hash}.png
    # AssetPipeline._match_local() uses keyword overlap on filename stems,
    # so descriptive names enable scene-to-beat matching (MD5-only names match 0%).
    safe_name = scene_name.replace("/", "_").replace(" ", "_")[:20]
    content_fp = f"{safe_name}:{strategy}:{json.dumps(color_palette or {})}:{resolution}"
    short_hash = hashlib.md5(content_fp.encode()).hexdigest()[:6]
    filename = f"scene_{safe_name}_{strategy}_{short_hash}.png"
    output_dir = os.path.join(Config.SCENES_DIR, "custom")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, filename)
    img.save(output_path, "PNG", optimize=True)

    return output_path


def generate_scenes_from_brief(
    creative_brief: dict,
    resolution: str = "portrait",
) -> list[dict]:
    """Generate all scenes from a creative brief.

    Args:
        creative_brief: The creative brief dict from creative_engine
        resolution: Output resolution preset

    Returns:
        List of {scene_name, description, image_path, archetype}
    """
    color_palette = creative_brief.get("color_palette")
    scenes = creative_brief.get("scenes", [])

    results = []
    for scene in scenes:
        name = scene.get("scene_name", "默认场景")
        desc = scene.get("description", scene.get("l1_alternative", "窗边白墙+自然光"))

        path = generate_scene(name, desc, color_palette, resolution)
        archetype = _match_archetype(name, desc)

        results.append({
            "scene_name": name,
            "description": desc,
            "image_path": path,
            "archetype": archetype["strategy"] if archetype else "unknown",
        })

    return results


def generate_scene_set(
    scene_names: list[str],
    color_palette: dict | None = None,
    resolution: str = "portrait",
) -> list[dict]:
    """Generate a set of named scenes with the same color palette.

    Useful for batch generation where you want multiple scene variations.
    """
    results = []
    for name in scene_names:
        # Find the archetype by name
        archetype = SCENE_ARCHETYPES.get(name)
        if archetype:
            desc = archetype["keywords"][0]
        else:
            desc = f"{name}场景"

        path = generate_scene(name, desc, color_palette, resolution)
        results.append({
            "scene_name": name,
            "image_path": path,
        })

    return results


# ============ Scene Caching ============


def list_generated_scenes() -> list[dict]:
    """List all generated scene images in the custom scenes directory."""
    scene_dir = os.path.join(Config.SCENES_DIR, "custom")
    if not os.path.isdir(scene_dir):
        return []

    scenes = []
    for fname in os.listdir(scene_dir):
        if fname.endswith(".png"):
            fpath = os.path.join(scene_dir, fname)
            size_bytes = os.path.getsize(fpath)
            scenes.append({
                "filename": fname,
                "path": fpath,
                "size_kb": round(size_bytes / 1024, 1),
                "url": f"/data/scenes/custom/{fname}",
            })

    scenes.sort(key=lambda s: os.path.getmtime(s["path"]), reverse=True)
    return scenes


def clear_scene_cache(max_age_hours: float = 24):
    """Remove generated scenes older than max_age_hours."""
    scene_dir = os.path.join(Config.SCENES_DIR, "custom")
    if not os.path.isdir(scene_dir):
        return

    import time
    now = time.time()
    cutoff = now - max_age_hours * 3600
    removed = 0

    for fname in os.listdir(scene_dir):
        if fname == ".gitkeep":
            continue
        fpath = os.path.join(scene_dir, fname)
        if os.path.getmtime(fpath) < cutoff:
            os.remove(fpath)
            removed += 1

    if removed:
        logger.info(f"Cleared {removed} cached scene images")
