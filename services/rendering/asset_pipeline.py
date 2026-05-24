"""Asset Pipeline — 多源素材匹配与生成引擎.

三源策略（按优先级）：
  1. 用户自有素材 → 直接匹配使用
  2. AI生成（Seedream图片 / Seedance视频）→ 按需生成
  3. 免费图库（Unsplash/Pexels）→ 兜底

核心设计：每个Beat的visual描述 → 匹配/生成 → AssetRef（带文件路径和裁剪参数）

Usage:
    from services.rendering.asset_pipeline import AssetPipeline
    pipeline = AssetPipeline(assets_dir="assets/ep1")
    resolved = pipeline.resolve(script, ref_analysis={...})
    # resolved = {beat_index: AssetRef, ...}
"""

import os, json, hashlib, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Data Types ─────────────────────────────────────────────

@dataclass
class AssetRef:
    """一个已解析的素材引用."""
    beat_index: int
    file_path: str                  # 本地文件路径（相对或绝对）
    asset_type: str                 # "image" | "video"
    source: str                     # "local" | "ai_generated" | "stock"
    crop: Optional[dict] = None     # 裁剪参数 {x, y, w, h}（用于放大到特定区域）
    scale: float = 1.0              # 缩放比例（用于放大效果）
    fallback: Optional[str] = None  # 备用文件路径


@dataclass
class AssetPlan:
    """素材方案 — 每个Beat用什么素材."""
    beat_index: int
    visual_desc: str                # 原始画面描述
    matched_asset: AssetRef
    needs_generation: bool = False
    generation_prompt: str = ""     # AI生图提示词
    generation_size: str = "1080x1920"


# ─── Asset Pipeline ────────────────────────────────────────

class AssetPipeline:
    """多源素材匹配与生成."""

    def __init__(self, assets_dir: str = "assets", cache_dir: str = None,
                 brand_name: str = None):
        self.assets_dir = Path(assets_dir)
        self.cache_dir = Path(cache_dir or os.path.join(assets_dir, ".cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.brand_name = brand_name or "AI电商"

        # 初始化各源
        self._local_index: dict[str, list[Path]] = {}
        self._index_local_assets()

    # ─── Public API ─────────────────────────────────────

    def resolve(self, script, ref_analysis: dict = None,
                user_assets: list[str] = None) -> dict[int, AssetPlan]:
        """为Script的每个Beat解析素材.

        Args:
            script: Script对象（含beats列表）
            ref_analysis: 参考图分析结果（用于AI生成prompt增强）
            user_assets: 用户额外指定的素材文件路径列表

        Returns:
            {beat_index: AssetPlan} 每个beat的素材方案
        """
        # 刷新本地索引（包含用户额外素材）
        if user_assets:
            self._index_user_assets(user_assets)

        ref = ref_analysis or {}
        # Collect scene images from ref_analysis for index-based fallback matching
        scene_pool = self._collect_scene_images(ref)
        plan: dict[int, AssetPlan] = {}

        for beat in script.beats:
            asset_plan = self._resolve_beat(beat, ref, scene_pool, beat.index)
            plan[beat.index] = asset_plan

        # 处理outro
        outro_plan = self._resolve_outro(script)
        plan[script.outro.index] = outro_plan

        return plan

    @staticmethod
    def _collect_scene_images(ref: dict) -> list[str]:
        """Extract scene image paths from ref_analysis results for fallback matching."""
        images = []
        for r in ref.get("results", []):
            img = r.get("image_path", "") or r.get("image", "")
            if img and os.path.exists(img):
                images.append(img)
        # Also include top-level image_path
        top = ref.get("image_path", "")
        if top and os.path.exists(top) and top not in images:
            images.append(top)
        return images

    def generate_missing(self, plan: dict[int, AssetPlan],
                         api_key: str = None) -> dict[int, AssetPlan]:
        """对标记needs_generation的beat调用AI生成.

        三源策略: Seedream (豆包) → 免费图库 → Pillow占位图
        """
        import urllib.request
        import urllib.parse
        import urllib.error
        import base64

        SEEDREAM_MODELS = [
            "doubao-seedream-4-5-251128",
            "doubao-seedream-4-0-250828",
        ]
        seedream_key = os.environ.get("SEEDREAM_API_KEY", "")
        seedream_url = os.environ.get("SEEDREAM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")

        _seedream_client = None
        if seedream_key:
            try:
                from openai import OpenAI
                _seedream_client = OpenAI(base_url=seedream_url, api_key=seedream_key)
            except Exception as e:
                print(f"  [asset] Seedream client init failed: {e}")

        for beat_idx, asset_plan in plan.items():
            if not asset_plan.needs_generation:
                continue

            prompt = asset_plan.generation_prompt
            cache_key = hashlib.md5(prompt.encode()).hexdigest()[:12]
            cache_path = self.cache_dir / f"gen_{cache_key}.png"

            if cache_path.exists() and cache_path.stat().st_size > 100:
                asset_plan.matched_asset.file_path = str(cache_path)
                asset_plan.matched_asset.source = "ai_generated"
                asset_plan.needs_generation = False
                continue

            generated = False
            want_real = asset_plan.matched_asset.source == "stock"

            # 0) REAL PHOTO route — download from Unsplash (keyword-matched)
            if want_real:
                try:
                    self._download_stock_photo(cache_path, prompt)
                    if cache_path.stat().st_size > 500:
                        generated = True
                        asset_plan.matched_asset.source = "stock"
                        print(f"  [asset] Beat {beat_idx}: real photo (Unsplash)")
                except Exception as e:
                    print(f"  [asset] Beat {beat_idx}: real photo failed ({e}), falling back to AI")

            # 1) Seedream (豆包) — primary AI generation
            if not generated and _seedream_client:
                for model in SEEDREAM_MODELS:
                    try:
                        actual_size = "1440x2560" if "4-5" in model else "1080x1920"
                        resp = _seedream_client.images.generate(
                            model=model, prompt=prompt, size=actual_size,
                            n=1, response_format="b64_json",
                            extra_body={"watermark": False}
                        )
                        img_data = base64.b64decode(resp.data[0].b64_json)
                        cache_path.write_bytes(img_data)
                        if cache_path.stat().st_size > 500:
                            generated = True
                            print(f"  [asset] Beat {beat_idx}: Seedream ({model})")
                            break
                    except Exception as e:
                        print(f"  [asset] Beat {beat_idx}: Seedream {model} failed ({e})")

            # 2) Pollinations.ai (free, no API key) — secondary fallback
            if not generated:
                try:
                    encoded = urllib.parse.quote(prompt)
                    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&nologo=true"
                    req = urllib.request.Request(url, headers={"User-Agent": "auto-video-platform/1.0"})
                    with urllib.request.urlopen(req, timeout=45) as resp:
                        cache_path.write_bytes(resp.read())
                    if cache_path.stat().st_size > 500:
                        generated = True
                        print(f"  [asset] Beat {beat_idx}: Pollinations.ai")
                except Exception as e:
                    print(f"  [asset] Beat {beat_idx}: Pollinations.ai failed ({e})")

            # 3) Fallback: Pillow placeholder
            if not generated:
                try:
                    self._make_placeholder(cache_path, prompt, beat_idx)
                    print(f"  [asset] Beat {beat_idx}: Pillow placeholder")
                except Exception as e:
                    print(f"  [asset] Beat {beat_idx}: placeholder also failed ({e})")
                    continue

            asset_plan.matched_asset.file_path = str(cache_path)
            asset_plan.matched_asset.source = "ai_generated"
            asset_plan.needs_generation = False

        return plan

    def _make_placeholder(self, path: Path, prompt: str, beat_idx: int):
        """Pillow fallback: 赛博朋克风格鉴定界面，模拟Douyin视频帧."""
        from PIL import Image, ImageDraw, ImageFont

        W, H = 1080, 1920
        img = Image.new("RGB", (W, H), color=(8, 10, 18))
        draw = ImageDraw.Draw(img)

        # Load fonts
        try:
            font_lg = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 56)
            font_md = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 40)
            font_sm = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 28)
        except OSError:
            font_lg = font_md = font_sm = ImageFont.load_default()

        # ── Scan line effect ──
        for y in range(0, H, 6):
            draw.line([(0, y), (W, y)], fill=(12, 15, 25))

        # ── Top header bar ──
        draw.rectangle([(0, 0), (W, 130)], fill=(0, 200, 100))
        tag = {1: "HOOK", 2: "展示", 3: "破绽①", 4: "破绽②", 5: "破绽③",
               6: "原理", 7: "清单", 8: "转发", 9: "评论", 10: "OUTRO"}.get(beat_idx, f"BEAT{beat_idx}")
        draw.text((40, 30), f"{self.brand_name} · {tag}", fill=(8, 10, 18), font=font_lg)

        # ── Center: visual placeholder area ──
        # AI detection interface mockup
        cx, cy = W // 2, H // 2
        # Simulated "magnifying glass" frame
        r_frame = 320
        draw.ellipse([(cx-r_frame, cy-60-r_frame), (cx+r_frame, cy-60+r_frame)],
                     outline=(0, 200, 100), width=6)
        # Crosshair
        draw.line([(cx, cy-60-r_frame), (cx, cy-60+r_frame)], fill=(0, 180, 90), width=2)
        draw.line([(cx-r_frame, cy-60), (cx+r_frame, cy-60)], fill=(0, 180, 90), width=2)
        draw.text((cx-80, cy-60-30), "🔍 放大检测", fill=(0, 200, 100), font=font_md)

        # ── Red circle annotation on the right side ──
        rx, ry, rr = W - 120, cy - 100, 140
        draw.ellipse([(rx-rr, ry-rr), (rx+rr, ry+rr)], outline=(255, 23, 68), width=7)
        draw.text((rx-45, ry-30), "!", fill=(255, 23, 68), font=font_lg)

        # ── Bottom: prompt description ──
        desc_text = self._wrap_text(prompt[:100], 24)
        y_text = H - 300
        draw.text((60, y_text), "AI生成素材提示词:", fill=(0, 200, 100), font=font_md)
        y_text += 60
        for line in desc_text:
            draw.text((60, y_text), line, fill=(180, 190, 210), font=font_sm)
            y_text += 36

        # ── Corner decorations ──
        for (x, y) in [(20, H-80), (W-20, 150)]:
            # Green corner brackets
            pass
        draw.rectangle([(0, H-3), (W, H)], fill=(0, 200, 100))  # bottom edge

        img.save(str(path), "PNG")

    @staticmethod
    def _download_stock_photo(dest: Path, hint: str):
        """Download free stock photo from Unsplash (no API key needed)."""
        import urllib.request
        import urllib.parse

        # Extract searchable keywords from the hint
        keywords = AssetPipeline._extract_search_keywords(hint)
        query = ",".join(keywords[:4]) if keywords else "portrait"

        sources = [
            # Unsplash source API — keyword-matched, free, no API key
            f"https://source.unsplash.com/1080x1920/?{urllib.parse.quote(query)}",
            # Lorem Picsum as fallback
            "https://picsum.photos/1080/1920?random",
        ]
        for url in sources:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "auto-video-platform/1.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    dest.write_bytes(resp.read())
                if dest.stat().st_size > 500:
                    return
            except Exception:
                continue
        raise RuntimeError("All stock photo sources exhausted")

    @staticmethod
    def _extract_search_keywords(hint: str) -> list[str]:
        """Extract English search keywords from a mixed CN/EN prompt."""
        # Map common Chinese visual keywords to English search terms
        CN_EN_MAP = {
            "人像": "portrait", "皮肤": "skin", "毛孔": "texture",
            "手": "hands", "手指": "fingers", "眼睛": "eyes",
            "脸": "face", "头发": "hair", "衣服": "clothing",
            "光影": "lighting", "阴影": "shadows", "招牌": "sign",
            "文字": "typography", "背景": "background",
            "真实": "real", "照片": "photo", "真人": "person",
            "建筑": "architecture", "风景": "landscape",
            "室内": "indoor", "室外": "outdoor",
            "食物": "food", "产品": "product", "工厂": "factory",
            "机器": "machine", "设备": "equipment",
        }
        words = []
        # Check for English words
        eng_words = [w for w in hint.split() if w.isascii() and len(w) > 2]
        words.extend([w.strip('.,;:!?()[]') for w in eng_words[:3]])

        # Check for Chinese keywords
        for cn, en in CN_EN_MAP.items():
            if cn in hint and en not in words:
                words.append(en)
        return words if words else ["portrait", "face"]

    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> list[str]:
        """Simple text wrapping by character count."""
        lines = []
        while len(text) > max_chars:
            # Find a good break point
            break_at = max_chars
            for sep in ['，', ',', '、', ' ', '。']:
                pos = text[:break_at].rfind(sep)
                if pos > max_chars // 2:
                    break_at = pos + 1
                    break
            lines.append(text[:break_at])
            text = text[break_at:].lstrip('，,、 ')
        if text:
            lines.append(text)
        return lines

    def summary(self, plan: dict[int, AssetPlan]) -> dict:
        """返回素材方案摘要."""
        total = len(plan)
        local = sum(1 for p in plan.values() if p.matched_asset.source == "local")
        ai_gen = sum(1 for p in plan.values() if p.matched_asset.source == "ai_generated")
        stock = sum(1 for p in plan.values() if p.matched_asset.source == "stock")

        return {
            "total_beats": total,
            "local_assets": local,
            "ai_generated": ai_gen,
            "stock_fallback": stock,
            "generation_needed": sum(1 for p in plan.values() if p.needs_generation),
        }

    # ─── Beat Resolution ─────────────────────────────────

    def _resolve_beat(self, beat, ref: dict, scene_pool: list[str] = None, beat_idx: int = 0) -> AssetPlan:
        """为单个Beat匹配素材."""
        visual = beat.visual

        # 1. 先尝试本地匹配（关键词重叠度）
        local_match = self._match_local(visual)
        if local_match:
            return AssetPlan(
                beat_index=beat.index,
                visual_desc=visual,
                matched_asset=AssetRef(
                    beat_index=beat.index,
                    file_path=str(local_match),
                    asset_type=self._guess_type(local_match),
                    source="local",
                ),
            )

        # 2. 索引兜底匹配：scene_pool[beat_idx % len(scene_pool)]
        if scene_pool:
            fallback_path = scene_pool[beat_idx % len(scene_pool)]
            return AssetPlan(
                beat_index=beat.index,
                visual_desc=visual,
                matched_asset=AssetRef(
                    beat_index=beat.index,
                    file_path=fallback_path,
                    asset_type=self._guess_type(Path(fallback_path)),
                    source="local",
                ),
            )

        # 3. 检查参考图中是否有可用区域（裁剪参考图的一部分）
        crop_match = self._match_crop_from_ref(visual, ref)
        if crop_match:
            return AssetPlan(
                beat_index=beat.index,
                visual_desc=visual,
                matched_asset=crop_match,
            )

        # 3. 判断素材类型：需要"真实照片"还是"AI生成假图"
        needs_real_photo = self._is_real_photo_need(visual)
        source_type = "stock" if needs_real_photo else "ai_generated"

        gen_prompt = self._build_generation_prompt(visual, ref)
        return AssetPlan(
            beat_index=beat.index,
            visual_desc=visual,
            matched_asset=AssetRef(
                beat_index=beat.index,
                file_path="",  # 待生成
                asset_type="image",
                source=source_type,
            ),
            needs_generation=True,
            generation_prompt=gen_prompt,
        )

    @staticmethod
    def _is_real_photo_need(visual_desc: str) -> bool:
        """Check if a beat needs a REAL photo (not AI-generated).

        AI照妖镜核心逻辑: "破绽展示"用AI图, "真实对比"用真人照片.
        """
        REAL_KEYWORDS = [
            "真人", "真实", "对比", "正常", "真实照片",
            "真人照片", "真人皮肤", "真人毛孔", "真人手指",
            "真实光线", "真实阴影", "真实衣服", "真实纹理",
            "正常人", "正常手指", "正常皮肤", "正常眼睛",
            "compare", "real", "authentic", "genuine",
        ]
        return any(kw in visual_desc for kw in REAL_KEYWORDS)

    def _resolve_outro(self, script) -> AssetPlan:
        """Outro使用品牌logo/关注引导画面."""
        # 检查本地有无logo文件
        logo_paths = list(self.assets_dir.glob("logo*")) + list(self.assets_dir.glob("brand*"))
        logo_path = str(logo_paths[0]) if logo_paths else ""

        return AssetPlan(
            beat_index=script.outro.index,
            visual_desc=script.outro.visual,
            matched_asset=AssetRef(
                beat_index=script.outro.index,
                file_path=logo_path,
                asset_type="image",
                source="local" if logo_path else "ai_generated",
            ),
            needs_generation=not bool(logo_path),
            generation_prompt="brand logo with scan line effect, cyberpunk style, dark background, 1080x1920",
        )

    # ─── Local Asset Matching ─────────────────────────────

    def _index_local_assets(self):
        """扫描assets_dir下所有媒体文件并建立索引."""
        extensions = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".gif"}
        self._local_index = {}

        if not self.assets_dir.exists():
            return

        for f in self.assets_dir.iterdir():
            if f.is_file() and f.suffix.lower() in extensions:
                # 用文件名（去扩展名）做索引key
                key = f.stem.lower().replace('_', ' ').replace('-', ' ')
                if key not in self._local_index:
                    self._local_index[key] = []
                self._local_index[key].append(f)

    def _index_user_assets(self, paths: list[str]):
        """索引用户额外指定的素材."""
        for p in paths:
            fp = Path(p)
            if fp.exists() and fp.is_file():
                key = fp.stem.lower().replace('_', ' ').replace('-', ' ')
                if key not in self._local_index:
                    self._local_index[key] = []
                if fp not in self._local_index[key]:
                    self._local_index[key].append(fp)

    def _match_local(self, visual_desc: str) -> Optional[Path]:
        """在本地素材库中匹配画面描述.

        策略：关键词重叠度匹配（简单高效，不需要embedding）.
        """
        desc_lower = visual_desc.lower()
        desc_words = set(desc_lower.replace('，', ' ').replace(',', ' ').split())

        best_score = 0
        best_file = None

        for filename_key, files in self._local_index.items():
            fn_words = set(filename_key.split())
            overlap = desc_words & fn_words
            # 加权：完全匹配的关键词越长越好
            score = sum(len(w) for w in overlap)

            if score > best_score and score >= 3:  # 至少3个字符匹配
                best_score = score
                best_file = files[0]

        return best_file

    def _match_crop_from_ref(self, visual_desc: str, ref: dict) -> Optional[AssetRef]:
        """检查是否可以从参考图中裁剪一个区域来用.

        适用场景：参考图分析结果中包含具体坐标区域（如标注的破绽位置）.
        """
        ref_image = ref.get("image_path", "")
        if not ref_image or not Path(ref_image).exists():
            return None

        # 检查visual描述中是否有具体坐标/区域
        import re
        coords = re.findall(r'\((\d+),\s*(\d+)\)', visual_desc)
        regions = ref.get("regions", []) or ref.get("annotations", [])

        if coords or regions:
            # 用参考图本身作为素材，配合裁剪参数
            crop = None
            if coords:
                # 取第一个坐标做中心点，裁剪周围区域
                x, y = int(coords[0][0]), int(coords[0][1])
                crop = {"x": max(0, x - 200), "y": max(0, y - 200), "w": 400, "h": 400}

            return AssetRef(
                beat_index=0,
                file_path=ref_image,
                asset_type="image",
                source="local",
                crop=crop,
                scale=2.5,  # 默认放大2.5倍展示破绽
            )

        return None

    # ─── AI Generation Prompts ────────────────────────────

    def _build_generation_prompt(self, visual_desc: str, ref: dict) -> str:
        """将画面描述转化为AI生图提示词.

        针对不同场景优化prompt风格：
        - AI鉴定视频 → 需要AI生成"有破绽的假图"作为素材
        - 带货视频 → 需要产品展示图
        - 工厂视频 → 需要工业场景图
        """
        ref_desc = ref.get("description", "") or ref.get("summary", "")

        base = visual_desc

        # 注入参考图上下文
        if ref_desc:
            base = f"{base}（参考场景：{ref_desc[:200]}）"

        # 通用优化：强调竖屏、高清、适合短视频
        enhancements = "竖屏9:16构图，高清细节，适合抖音短视频，画面主体居中"

        return f"{base}，{enhancements}"

    def _guess_type(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in (".mp4", ".mov", ".webm"):
            return "video"
        return "image"

    # ─── Stock Fallback ───────────────────────────────────

    def search_stock(self, query: str, count: int = 5) -> list[dict]:
        """搜索免费图库（Unsplash API）.

        用于AI生成失败或成本过高时的兜底策略。
        """
        # Unsplash 免费API（无需认证的demo级访问有限制）
        # 生产环境应注册API key
        access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
        if not access_key:
            return self._pexels_fallback(query, count)

        import urllib.request, urllib.parse
        params = urllib.parse.urlencode({
            "query": query,
            "per_page": count,
            "orientation": "portrait",
        })
        url = f"https://api.unsplash.com/search/photos?{params}"
        req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {access_key}"})

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return [
                    {"url": r["urls"]["regular"], "thumb": r["urls"]["thumb"],
                     "author": r["user"]["name"], "source": "unsplash"}
                    for r in data.get("results", [])
                ]
        except Exception:
            return self._pexels_fallback(query, count)

    def _pexels_fallback(self, query: str, count: int = 5) -> list[dict]:
        """Pexels API兜底."""
        api_key = os.environ.get("PEXELS_API_KEY", "")
        if not api_key:
            return []

        import urllib.request, urllib.parse
        params = urllib.parse.urlencode({
            "query": query, "per_page": count, "orientation": "portrait",
        })
        url = f"https://api.pexels.com/v1/search?{params}"
        req = urllib.request.Request(url, headers={"Authorization": api_key})

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return [
                    {"url": p["src"]["large"], "thumb": p["src"]["medium"],
                     "author": p["photographer"], "source": "pexels"}
                    for p in data.get("photos", [])
                ]
        except Exception:
            return []


# ─── Convenience ────────────────────────────────────────────

def plan_to_storyboard(asset_plan: dict[int, AssetPlan],
                       script) -> list[dict]:
    """将AssetPlan + Script合并为storyboard（供composition_builder使用）."""
    shots = []

    for beat in script.beats:
        ap = asset_plan.get(beat.index)
        asset = ap.matched_asset if ap else None

        shots.append({
            "shot": beat.index,
            "duration": f"{beat.duration_s}s",
            "visual": beat.visual,
            "audio": beat.text,
            "caption": beat.text,
            "animation": beat.animation,
            "emotion": beat.emotion,
            "asset_path": asset.file_path if asset else "",
            "asset_type": asset.asset_type if asset else "image",
            "crop": asset.crop if asset else None,
            "scale": asset.scale if asset else 1.0,
        })

    # Outro
    ap = asset_plan.get(script.outro.index)
    shots.append({
        "shot": script.outro.index,
        "duration": f"{script.outro.duration_s}s",
        "visual": script.outro.visual,
        "audio": script.outro.text,
        "caption": script.outro.text,
        "animation": "pop",
        "emotion": "action",
        "asset_path": ap.matched_asset.file_path if ap else "",
        "asset_type": "image",
        "crop": None,
        "scale": 1.0,
    })

    return shots
