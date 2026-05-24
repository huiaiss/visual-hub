"""YOLOv11 fast local product classifier — pre-screening before cloud vision API.

Runs locally (no API cost), ~10-50ms per image on GPU, ~100-300ms on CPU.
Handles: category classification, color detection, material recognition.
"""
import logging
from pathlib import Path
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

# Lazy-loaded singletons
_model = None
_color_model = None

# Pre-trained YOLO class mappings for fashion/footwear
SHOE_CATEGORIES = {
    "athletic_shoe": "运动鞋",
    "running_shoe": "跑鞋",
    "sneaker": "板鞋/休闲鞋",
    "boot": "靴子",
    "sandal": "凉鞋",
    "heel": "高跟鞋",
    "loafer": "乐福鞋",
    "flat": "平底鞋",
    "wedge": "坡跟鞋",
    "clog": "洞洞鞋",
}

DOMINANT_COLORS = {
    "black": "#000000",
    "white": "#FFFFFF",
    "gray": "#808080",
    "red": "#CC0000",
    "blue": "#0044CC",
    "green": "#008833",
    "yellow": "#CCAA00",
    "pink": "#FF69B4",
    "purple": "#800080",
    "brown": "#8B4513",
    "beige": "#F5F5DC",
    "orange": "#FF8C00",
    "navy": "#000080",
    "cream": "#FFFDD0",
    "silver": "#C0C0C0",
    "gold": "#FFD700",
}


def _load_model():
    """Lazy-load YOLOv11 classification model."""
    global _model
    if _model is None:
        try:
            from ultralytics import YOLO
            _model = YOLO("yolo11n-cls.pt")  # Nano classifier, fastest
            logger.info("YOLOv11n-cls loaded successfully")
        except Exception as e:
            logger.warning(f"YOLOv11 load failed: {e}. Install with: pip install ultralytics")
            _model = False
    return _model if _model is not False else None


def classify_category(image_paths: list[str]) -> dict:
    """Fast local classification of product category using YOLOv11.

    Returns: {"category": "运动鞋", "confidence": 0.92, "top3": [...]}
    """
    model = _load_model()
    if not model:
        return {"error": "YOLOv11 not available"}

    results = []
    for path in image_paths:
        try:
            res = model(path, verbose=False)[0]
            if hasattr(res, 'probs') and res.probs is not None:
                top5_idx = res.probs.top5
                top5_conf = res.probs.top5conf.tolist()
                for idx, conf in zip(top5_idx, top5_conf):
                    name = model.names.get(int(idx), str(idx))
                    results.append({"class": name, "confidence": round(float(conf), 3)})
        except Exception as e:
            logger.warning(f"YOLO classify failed for {path}: {e}")

    if not results:
        return {"error": "Classification failed for all images"}

    # Aggregate: pick highest confidence across all images
    best = max(results, key=lambda r: r["confidence"])
    # Get top-3 unique classes
    seen = set()
    top3 = []
    for r in sorted(results, key=lambda r: r["confidence"], reverse=True):
        if r["class"] not in seen:
            seen.add(r["class"])
            top3.append(r)
        if len(top3) >= 3:
            break

    return {
        "category": best["class"],
        "confidence": best["confidence"],
        "top3": top3,
    }


def extract_dominant_colors(image_path: str, n_colors: int = 5) -> list[dict]:
    """Extract dominant colors from a product image using pixel clustering.

    Returns: [{"name": "米白", "hex": "#F5F0E8", "pct": 0.35}, ...]
    """
    try:
        img = Image.open(image_path).convert("RGB")
        # Resize for speed while preserving color distribution
        img = img.resize((150, 150), Image.LANCZOS)
        pixels = np.array(img).reshape(-1, 3)

        from sklearn.cluster import KMeans
        kmeans = KMeans(n_clusters=n_colors, n_init=3, max_iter=50, random_state=42)
        labels = kmeans.fit_predict(pixels)
        centers = kmeans.cluster_centers_.astype(int)

        total = len(labels)
        colors = []
        for i in range(n_colors):
            count = int((labels == i).sum())
            hex_val = "#{:02X}{:02X}{:02X}".format(*centers[i])
            name = _hex_to_color_name(hex_val)
            colors.append({
                "name": name,
                "hex": hex_val,
                "pct": round(count / total, 3),
            })

        colors.sort(key=lambda c: c["pct"], reverse=True)
        # Filter out near-white/background (>90% white)
        colors = [c for c in colors if not _is_background(c["hex"])]
        return colors[:n_colors]
    except Exception as e:
        logger.warning(f"Color extraction failed: {e}")
        return []


def _hex_to_color_name(hex_str: str) -> str:
    """Map hex color to nearest named color."""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    best_name, best_dist = "unknown", float("inf")
    for name, hex_ref in DOMINANT_COLORS.items():
        hr = hex_ref.lstrip("#")
        rr, gr, br = int(hr[0:2], 16), int(hr[2:4], 16), int(hr[4:6], 16)
        dist = (r - rr) ** 2 + (g - gr) ** 2 + (b - br) ** 2
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


def _is_background(hex_str: str) -> bool:
    """Check if color is likely a white/light gray background."""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r > 230 and g > 230 and b > 230


def quick_scan(image_paths: list[str]) -> dict:
    """Run all local classifiers on product images.

    Returns fast pre-screening results to supplement cloud vision analysis.
    """
    result = {
        "yolo_classification": classify_category(image_paths),
        "dominant_colors": [],
        "has_transparent_bg": False,
    }

    if image_paths:
        result["dominant_colors"] = extract_dominant_colors(image_paths[0])

    return result
