"""Pipeline Bridge — connects visual-hub creative plans to auto-video-platform.

Converts FrameCraft shooting plans into auto-video-platform's Beat-level Script
objects, feeds scene images as assets, and orchestrates end-to-end video production.

Data flow:
  visual-hub Plan JSON → Script (Beat-level) → AssetPipeline → Assembly → MP4

Usage:
    from services.pipeline_bridge import plan_to_video

    result = plan_to_video(
        plan=plan_dict,
        scene_images=["/data/scenes/window.png", ...],
        output_dir="output/my_video",
        video_type="product_promo",
    )
    # result.html_path, result.mp4_path, result.audio_path
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Add auto-video-platform to sys.path (robust multi-drive resolution)
_AUTO_VIDEO_ROOT = os.environ.get(
    "AUTO_VIDEO_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "auto-video-platform"),
)
_AUTO_VIDEO_ROOT = os.path.abspath(_AUTO_VIDEO_ROOT)
# Fallback: try d:\auto-video-platform if relative path doesn't exist
if not os.path.isdir(_AUTO_VIDEO_ROOT):
    _ALT = r"d:\auto-video-platform"
    if os.path.isdir(_ALT):
        _AUTO_VIDEO_ROOT = _ALT
if _AUTO_VIDEO_ROOT not in sys.path:
    sys.path.insert(0, _AUTO_VIDEO_ROOT)


# ─── Data Types — canonical source from auto-video-platform ───

# Import canonical Beat/Script from auto-video-platform (single source of truth)
try:
    from generators.script_engine import Beat, Script
except ImportError:
    # Fallback: keep local copies if auto-video-platform unavailable
    @dataclass
    class Beat:
        index: int
        text: str
        visual: str
        animation: str = "fade"
        emotion: str = "trust"
        duration_s: float = 4.0
        is_save_trigger: bool = False
        is_share_trigger: bool = False
        is_comment_trigger: bool = False
        # Extended FrameCraft dimensions
        caption: str = ""          # On-screen subtitle text
        how_to_shoot: str = ""     # Shooting instruction for production
        tier: str = "L1"           # Shooting tier: L1/L2/L3
        audio_l2_text: str = ""    # Alternate narration (B-roll voice)

    @dataclass
    class Script:
        title: str
        hook_type: str
        beats: list[Beat]
        outro: Beat
        tags: list[str] = field(default_factory=list)
        bgm_style: str = ""
        checklist: str = ""
        total_duration_s: float = 0.0
        # Extended FrameCraft dimensions
        bgm_search_keywords: list[str] = field(default_factory=list)
        bgm_tempo_bpm: str = ""
        bgm_usage_tips: str = ""
        composition_style: str = ""
        model_direction: str = ""
        differentiation: str = ""
        key_features: list[str] = field(default_factory=list)
        top_hook_types: list[str] = field(default_factory=list)


# ─── Emotion & Animation Mapping ──────────────────────────────

# Map storyboard shot positions to psychological functions
_POSITION_EMOTION = {
    1: "hook",        # Opening — grab attention
    2: "curiosity",   # Product reveal
    3: "trust",       # Detail showcase
    4: "desire",      # Feature highlight
    5: "trust",       # Social proof
    6: "desire",      # Scenario
    7: "action",      # CTA
}

# Map shot tier to animation style
_TIER_ANIMATION = {
    "L1": "pop",       # Phone-shot — simple pop
    "L2": "zoom",      # Pro — zoom detail
    "L3": "slide",     # Studio — smooth slides
}

# Convert visual-hub script_type to auto-video-platform video_type
_SCRIPT_TYPE_TO_VIDEO_TYPE = {
    "with_cart": "product_promo",
    "no_cart": "product_promo",
    "live": "vlog",
}

# Map video_type to component_set (which component library to use)
_VIDEO_TYPE_TO_COMPONENT_SET = {
    "ai_flaw_detect": "ai_flaw_detect",
    # All e-commerce / product promo types use the ecommerce component library
    "product_promo": "ecommerce",
    "factory_promo": "ecommerce",
    "tutorial": "ecommerce",
    "vlog": "ecommerce",
}

# Default tags by industry
_INDUSTRY_TAGS = {
    "鞋类": ["鞋类测评", "好鞋推荐", "穿搭", "平价款", "国货鞋"],
    "服装": ["穿搭", "好物推荐", "服装测评", "显瘦穿搭", "平价穿搭"],
    "美妆": ["美妆测评", "平价好物", "妆容教程", "护肤", "好物推荐"],
    "食品": ["零食测评", "美食推荐", "好吃不贵", "追剧零食", "吃货"],
    "3C数码": ["数码测评", "数码好物", "科技", "好物推荐", "测评"],
    "家居": ["家居好物", "居家好物", "收纳", "平价家居", "好物推荐"],
}

# Platform → (width, height) for HTML rendering + MP4 export
_PLATFORM_DIMENSIONS = {
    "douyin": (1080, 1920),       # 抖音 9:16
    "kuaishou": (1080, 1920),     # 快手 9:16
    "xiaohongshu": (1080, 1440),  # 小红书 3:4
    "shipinhao": (1080, 1920),    # 视频号 9:16
    "taobao": (800, 800),         # 淘宝 1:1
    "jingdong": (800, 800),       # 京东 1:1
    "pdd": (1080, 1440),          # 拼多多 3:4
    "default": (1080, 1920),
}


# ─── Core Conversion ──────────────────────────────────────────

def plan_to_script(
    plan: dict,
    industry: str = "鞋类",
    script_type: str = "with_cart",
    extra_context: str = "",
    creative_brief: dict = None,
    product_analysis: dict = None,
) -> Script:
    """Convert a visual-hub shooting plan into a Beat-level Script.

    Args:
        plan: A single plan dict from generate_plans() output. Must have:
              - titles (or title)
              - hook_type (optional)
              - script.storyboard[] with visual, audio_l1, audio_l2, tier, duration
              - shooting_template_card.bgm_pick (optional)
              - shooting_template_card.tier_label (optional)
        industry: Product category for default tags.
        script_type: with_cart / no_cart / live
        extra_context: Additional context string for style hints.

    Returns:
        Script ready for auto-video-platform consumption.
    """
    storyboard = plan.get("script", {}).get("storyboard", [])
    if not storyboard:
        raise ValueError("Plan has no storyboard — cannot convert to video script")

    raw_titles = plan.get("titles", plan.get("title", f"{industry}产品展示"))
    # Handle new v4 format: titles is a list of {text, type, scenario} dicts
    if isinstance(raw_titles, list) and len(raw_titles) > 0:
        if isinstance(raw_titles[0], dict):
            title = raw_titles[0].get("text", f"{industry}产品展示")
        else:
            title = str(raw_titles[0])
    elif isinstance(raw_titles, str):
        title = raw_titles
    else:
        title = f"{industry}产品展示"

    # Hook type: extract from new format or use direct string
    hook_type = plan.get("hook_type", "身份认同型")
    if not hook_type or hook_type == "身份认同型":
        if isinstance(raw_titles, list) and len(raw_titles) > 0 and isinstance(raw_titles[0], dict):
            hook_type = raw_titles[0].get("type", "身份认同型")

    # Top hook types — all candidate hook types from the plan
    top_hook_types = plan.get("top_hook_types", [])
    if not top_hook_types and isinstance(raw_titles, list):
        top_hook_types = [t.get("type", "") for t in raw_titles if isinstance(t, dict) and t.get("type")]
    if hook_type and hook_type not in top_hook_types:
        top_hook_types.insert(0, hook_type)

    # Build beats from storyboard
    beats = []
    for i, shot in enumerate(storyboard):
        sn = shot.get("shot", i + 1)
        text = shot.get("audio_l1", shot.get("audio", shot.get("visual", "")))
        visual = shot.get("visual", "")
        tier = shot.get("tier", "L1")

        # Duration: use plan's specified duration or sensible default
        raw_dur = shot.get("duration", 0)
        try:
            dur = float(str(raw_dur).replace("s", "").strip())
        except (ValueError, TypeError):
            dur = 3.5 if sn == 1 else 4.0  # Hook is shorter

        emotion = _POSITION_EMOTION.get(sn, "trust")
        animation = _TIER_ANIMATION.get(tier, "fade")

        # FrameCraft extended dimensions per shot
        caption = shot.get("caption", "")
        how_to_shoot = shot.get("how_to_shoot", "")

        # Algorithm triggers — mark specific positions
        is_save = (sn == len(storyboard))  # Last shot = save trigger
        is_share = (sn == max(1, len(storyboard) - 1))  # Second-to-last = share
        is_comment = (sn == len(storyboard))  # Last shot also = comment trigger

        beat = Beat(
            index=sn,
            text=text or "",
            visual=visual or "",
            animation=animation,
            emotion=emotion,
            duration_s=max(dur, 2.0),
            is_save_trigger=is_save,
            is_share_trigger=is_share,
            is_comment_trigger=is_comment,
            caption=caption,
            how_to_shoot=how_to_shoot,
            tier=tier,
            audio_l2_text=shot.get("audio_l2", ""),
        )
        beats.append(beat)

    # Outro — from plan's CTA / brand close
    template_card = plan.get("shooting_template_card", {})
    outro_text = f"截图保存拍摄方案，下次直接对照拍。关注我，每天一个电商拍摄技巧。"
    outro_visual = "品牌logo + 关注引导 + 拍摄方案清单"

    outro = Beat(
        index=len(beats) + 1,
        text=outro_text,
        visual=outro_visual,
        animation="pop",
        emotion="action",
        duration_s=5.0,
        is_save_trigger=True,
        is_share_trigger=True,
        is_comment_trigger=True,
    )

    # BGM style — from params (preferred) or plan template card
    if creative_brief is None:
        creative_brief = plan.get("creative_brief", {})
    if isinstance(creative_brief, str):
        try:
            creative_brief = json.loads(creative_brief)
        except (json.JSONDecodeError, TypeError):
            creative_brief = {}

    bgm_info = creative_brief.get("bgm_suggestion", {})
    if isinstance(bgm_info, str):
        try:
            bgm_info = json.loads(bgm_info)
        except (json.JSONDecodeError, TypeError):
            bgm_info = {}

    bgm_style = template_card.get("bgm_pick", bgm_info.get("style", "轻快时尚"))
    if isinstance(bgm_style, str) and "剪映" in bgm_style:
        bgm_style = bgm_style.replace("剪映热门BGM「", "").replace("」", "").replace("剪映音频搜「", "").replace("」", "")

    bgm_search_keywords = bgm_info.get("search_keywords", bgm_info.get("recommendations", []))
    if isinstance(bgm_search_keywords, str):
        bgm_search_keywords = [bgm_search_keywords]
    bgm_tempo_bpm = bgm_info.get("tempo_bpm", "")
    bgm_usage_tips = bgm_info.get("usage_tips", "")

    # FrameCraft creative dimensions
    composition_style = creative_brief.get("composition_style", "")
    model_direction = creative_brief.get("model_direction", "")
    if isinstance(model_direction, dict):
        model_direction = json.dumps(model_direction, ensure_ascii=False)
    differentiation = creative_brief.get("differentiation", "")

    # Product key features for tagging — from params (preferred) or plan dict
    if product_analysis is None:
        product_analysis = plan.get("product_analysis", {})
    if isinstance(product_analysis, str):
        try:
            product_analysis = json.loads(product_analysis)
        except (json.JSONDecodeError, TypeError):
            product_analysis = {}
    key_features = product_analysis.get("key_features", [])

    # Checklist — combine equipment, pitfalls, and how_to_shoot tips
    checklist_lines = []
    if template_card.get("equipment_needed"):
        checklist_lines.append(template_card["equipment_needed"][:40])
    if template_card.get("pitfall_alert"):
        checklist_lines.append(template_card["pitfall_alert"][:40])
    checklist = " | ".join(checklist_lines) if checklist_lines else "手机拍摄秘籍"

    # Tags — combine industry defaults + key features + differentiation
    tags = list(_INDUSTRY_TAGS.get(industry, _INDUSTRY_TAGS["鞋类"]))
    if key_features:
        tags = key_features[:3] + tags
    if differentiation and len(differentiation) < 20:
        tags.insert(0, differentiation)

    total = sum(b.duration_s for b in beats) + outro.duration_s

    return Script(
        title=title[:15] if title else f"{industry}拍摄",
        hook_type=hook_type,
        beats=beats,
        outro=outro,
        tags=tags,
        bgm_style=bgm_style,
        checklist=checklist,
        total_duration_s=total,
        bgm_search_keywords=bgm_search_keywords,
        bgm_tempo_bpm=bgm_tempo_bpm,
        bgm_usage_tips=bgm_usage_tips,
        composition_style=composition_style,
        model_direction=model_direction,
        differentiation=differentiation,
        key_features=key_features,
        top_hook_types=top_hook_types,
    )


def plans_to_scripts(
    plans: list[dict],
    industry: str = "鞋类",
    script_type: str = "with_cart",
    creative_brief: dict = None,
    product_analysis: dict = None,
) -> list[tuple[int, Script]]:
    """Convert all plans in a result set. Returns [(plan_index, Script), ...]."""
    results = []
    for i, plan in enumerate(plans):
        try:
            script = plan_to_script(plan, industry, script_type,
                                    creative_brief=creative_brief,
                                    product_analysis=product_analysis)
            results.append((i + 1, script))
        except ValueError as e:
            logger.warning(f"Plan {i + 1} conversion skipped: {e}")
    return results


# ─── Pipeline Runner ──────────────────────────────────────────

class VideoExportResult:
    """Result from plan_to_video()."""

    def __init__(self, plan_index: int, script: Script, output_dir: str,
                 html_path: str = "", mp4_path: str = "", audio_path: str = "",
                 srt_path: str = "", duration_s: float = 0.0, error: str = ""):
        self.plan_index = plan_index
        self.script = script
        self.output_dir = output_dir
        self.html_path = html_path
        self.mp4_path = mp4_path
        self.audio_path = audio_path
        self.srt_path = srt_path
        self.duration_s = duration_s
        self.error = error
        self.ok = not error


def plan_to_video(
    plan: dict,
    scene_images: list[str] = None,
    output_dir: str = None,
    video_type: str = "product_promo",
    platform: str = "douyin",
    industry: str = "鞋类",
    script_type: str = "with_cart",
    tts_voice: str = "zh-CN-YunxiNeural",
    tts_speed: float = 1.15,
    skip_tts: bool = False,
    skip_mp4: bool = False,
    bgm: bool = False,
    creative_brief: dict = None,
    product_analysis: dict = None,
) -> VideoExportResult:
    """Convert a single plan into a finished MP4 video.

    This is the main entry point — takes a visual-hub plan + scene images
    and runs the full auto-video-platform pipeline.

    Args:
        plan: visual-hub plan dict (with storyboard, shooting_template_card, etc.)
        scene_images: List of scene background image file paths (generated by scene_generator)
        output_dir: Output directory for video assets (auto-generated if None)
        video_type: product_promo | factory_promo | tutorial | vlog | ai_flaw_detect
        platform: Target platform — "douyin" | "kuaishou" | "xiaohongshu" | "shipinhao" | "taobao"
                  Determines output dimensions (e.g. douyin=1080x1920, xiaohongshu=1080x1440)
        industry: Product category
        script_type: with_cart | no_cart | live
        tts_voice: edge-tts voice name
        tts_speed: TTS speed multiplier
        skip_tts: Skip audio generation
        skip_mp4: Skip Chromium MP4 rendering
        bgm: Download/generate background music

    Returns:
        VideoExportResult with paths to all output files.
    """
    import time
    import uuid

    t0 = time.time()
    scene_images = scene_images or []

    # 1. Convert plan → Script
    script = plan_to_script(plan, industry, script_type,
                            creative_brief=creative_brief,
                            product_analysis=product_analysis)
    logger.info(f"Converted plan to Script: {script.title}, {len(script.beats)} beats, {script.total_duration_s:.1f}s")

    # 1.5 QA Gate — reject plans that don't pass gatekeeper (threshold: 70/100)
    try:
        from services.gatekeeper import review
        qa_report = review(plan, industry)
        if not qa_report.pass_ or qa_report.score < 70:
            return VideoExportResult(
                plan_index=0, script=script, output_dir=output_dir or "",
                error=f"QA rejected (score={qa_report.score}/100): {qa_report.summary}",
            )
        logger.info(f"QA passed: score={qa_report.score}/100, {qa_report.summary}")
    except ImportError:
        pass  # gatekeeper not available, proceed without gating

    # 2. Determine output directory
    if not output_dir:
        plan_id = uuid.uuid4().hex[:8]
        from config import Config
        output_dir = os.path.join(Config.DATA_DIR, "videos", f"plan_{plan_id}")

    os.makedirs(output_dir, exist_ok=True)

    # 3. Build ref_analysis dict (scene images + product context + brand colors)
    ref_analysis = _build_ref_analysis(plan, scene_images, creative_brief)

    # 4. Resolve assets — feed scene images as user assets
    from builders.asset_pipeline import AssetPipeline
    assets_dir = os.path.join(output_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    asset_pipeline = AssetPipeline(assets_dir=assets_dir)

    # Index scene images and any image_paths from plan
    user_assets = list(scene_images)
    image_paths_json = plan.get("image_paths", "[]")
    if isinstance(image_paths_json, str):
        try:
            image_paths_json = json.loads(image_paths_json)
        except json.JSONDecodeError:
            image_paths_json = []
    for p in image_paths_json:
        if os.path.exists(p) and p not in user_assets:
            user_assets.append(p)

    asset_plan = asset_pipeline.resolve(script, ref_analysis, user_assets)
    summary = asset_pipeline.summary(asset_plan)
    logger.info(f"Assets: {summary['total_beats']} beats, {summary['local_assets']} local, "
                f"{summary['generation_needed']} need generation")

    # Generate missing assets (uses Pollinations.ai or Pillow fallback)
    if summary['generation_needed'] > 0:
        logger.info(f"Generating {summary['generation_needed']} missing assets...")
        asset_plan = asset_pipeline.generate_missing(asset_plan)

    # 5. Assemble HTML + Audio + SRT
    from builders.assembly_engine import AssemblyEngine
    width, height = _PLATFORM_DIMENSIONS.get(platform, _PLATFORM_DIMENSIONS["default"])
    component_set = _VIDEO_TYPE_TO_COMPONENT_SET.get(video_type, "ai_flaw_detect")
    assembler = AssemblyEngine(
        output_dir=output_dir,
        tts_voice=tts_voice,
        tts_speed=tts_speed,
        canvas_width=width,
        canvas_height=height,
        component_set=component_set,
    )

    bgm_path = ""
    if bgm:
        from pipeline import VideoPipeline
        bgm_path = VideoPipeline.download_bgm(output_dir, script.total_duration_s)

    try:
        result = assembler.assemble(script, asset_plan, bgm_path, ref_analysis)
    except Exception as e:
        logger.exception("Assembly failed")
        return VideoExportResult(
            plan_index=0, script=script, output_dir=output_dir,
            error=f"Assembly failed: {e}",
        )

    # 6. Render MP4 (optional)
    mp4_path = ""
    if not skip_mp4:
        try:
            from builders.chromium_renderer import ChromiumRenderer
            renderer = ChromiumRenderer()
            mp4_path = renderer.render(
                html_dir=output_dir,
                audio_path=result.audio_path if os.path.exists(result.audio_path) else "",
                duration_s=result.total_duration_s,
                output_path=os.path.join(output_dir, "output.mp4"),
            )
            logger.info(f"MP4 rendered: {mp4_path}")
        except FileNotFoundError:
            logger.warning("Chromium not found — skipping MP4 render")
        except Exception as e:
            logger.warning(f"MP4 render failed (non-blocking): {e}")

    elapsed = time.time() - t0
    logger.info(f"Video export complete in {elapsed:.1f}s → {output_dir}")

    return VideoExportResult(
        plan_index=0,
        script=script,
        output_dir=output_dir,
        html_path=result.html_path,
        mp4_path=mp4_path,
        audio_path=result.audio_path,
        srt_path=result.srt_path,
        duration_s=result.total_duration_s,
    )


def batch_plans_to_videos(
    plans: list[dict],
    scene_images: list[str] = None,
    base_output_dir: str = None,
    video_type: str = "product_promo",
    industry: str = "鞋类",
    script_type: str = "with_cart",
    max_workers: int = 2,
    **kwargs,
) -> list[VideoExportResult]:
    """Convert multiple plans to videos in parallel.

    Args:
        plans: List of plan dicts
        scene_images: Shared scene images for all plans
        base_output_dir: Base directory (plan_N/ subdirs created automatically)
        max_workers: Max parallel video exports
        **kwargs: Passed to plan_to_video()

    Returns:
        List of VideoExportResult, one per plan.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not base_output_dir:
        from config import Config
        base_output_dir = os.path.join(Config.DATA_DIR, "videos")

    results = []

    def export_one(i, plan):
        plan_dir = os.path.join(base_output_dir, f"plan_{i + 1}")
        return plan_to_video(
            plan=plan,
            scene_images=scene_images,
            output_dir=plan_dir,
            video_type=video_type,
            industry=industry,
            script_type=script_type,
            **kwargs,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(export_one, i, plan): i for i, plan in enumerate(plans)}
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                i = futures[future]
                logger.exception(f"Plan {i + 1} video export failed")
                results.append(VideoExportResult(
                    plan_index=i + 1,
                    script=Script(title="", hook_type="", beats=[], outro=Beat(
                        index=0, text="", visual="", duration_s=0)),
                    output_dir="",
                    error=str(e),
                ))

    results.sort(key=lambda r: r.plan_index)
    return results


# ─── Helpers ──────────────────────────────────────────────────

def _build_ref_analysis(plan: dict, scene_images: list[str], creative_brief: dict = None) -> dict:
    """Build a ref_analysis dict from plan data for the asset pipeline.

    Carries brand identity (color_palette, mood) through to CompositionBuilder
    so the rendered HTML reflects the creative brief's aesthetic instead of
    hardcoded cyberpunk green.

    Priority: creative_brief.color_palette > plan-level color_palette > defaults.
    """
    analysis = {
        "description": "",
        "image_path": scene_images[0] if scene_images else "",
        "results": [],
        "brand_style": {},  # color_palette + mood for CompositionBuilder
    }

    # Product description from plan context
    template_card = plan.get("shooting_template_card", {})
    if template_card.get("best_scene"):
        analysis["description"] += f"推荐场景: {template_card['best_scene']}. "
    if template_card.get("tier_label"):
        analysis["description"] += f"拍摄级别: {template_card['tier_label']}. "

    titles = plan.get("titles", "")
    if titles:
        analysis["description"] += f"视频主题: {titles}. "

    # ── Brand colors: creative_brief takes priority ──
    if creative_brief:
        cp = creative_brief.get("color_palette", {})
        if cp:
            analysis["brand_style"]["colors"] = {
                "primary": cp.get("primary", ""),
                "secondary": cp.get("secondary", ""),
                "accent": cp.get("accent", ""),
            }
        if creative_brief.get("concept_name"):
            analysis["brand_style"]["concept_name"] = creative_brief["concept_name"]
        if creative_brief.get("mood_keywords"):
            analysis["brand_style"]["mood_tags"] = creative_brief["mood_keywords"]
        # Extended FrameCraft dimensions for HTML template styling
        if creative_brief.get("model_direction"):
            md = creative_brief["model_direction"]
            analysis["brand_style"]["model_direction"] = json.dumps(md, ensure_ascii=False) if isinstance(md, dict) else str(md)
        if creative_brief.get("composition_style"):
            analysis["brand_style"]["composition_style"] = creative_brief["composition_style"]
        if creative_brief.get("differentiation"):
            analysis["brand_style"]["differentiation"] = creative_brief["differentiation"]
        # BGM info for audio-driven visual sync
        bgm = creative_brief.get("bgm_suggestion", {})
        if isinstance(bgm, dict):
            if bgm.get("tempo_bpm"):
                analysis["brand_style"]["bgm_tempo_bpm"] = bgm["tempo_bpm"]
            if bgm.get("style"):
                analysis["brand_style"]["bgm_style"] = bgm["style"]
            if bgm.get("search_keywords"):
                analysis["brand_style"]["bgm_search_keywords"] = bgm["search_keywords"]

    # Fall back to plan-level color_palette (backward compat)
    if not analysis["brand_style"].get("colors"):
        color_palette = (
            template_card.get("color_palette")
            or plan.get("color_palette")
            or {}
        )
        if color_palette:
            analysis["brand_style"]["colors"] = color_palette

    # Mood/concept from plan if not already set from creative_brief
    if not analysis["brand_style"].get("mood_tags") and template_card.get("mood_tags"):
        analysis["brand_style"]["mood_tags"] = template_card["mood_tags"]
    if not analysis["brand_style"].get("concept_name") and plan.get("concept_name"):
        analysis["brand_style"]["concept_name"] = plan["concept_name"]

    # Product key_features and design_highlights for copy/visual emphasis
    product_analysis = plan.get("product_analysis", {})
    if isinstance(product_analysis, str):
        try:
            product_analysis = json.loads(product_analysis)
        except (json.JSONDecodeError, TypeError):
            product_analysis = {}
    if product_analysis.get("key_features"):
        analysis["brand_style"]["key_features"] = product_analysis["key_features"]
    if product_analysis.get("design_highlights"):
        analysis["brand_style"]["design_highlights"] = product_analysis["design_highlights"]

    # Add each scene image as a result entry
    for img in scene_images:
        if os.path.exists(img):
            analysis["results"].append({
                "image_path": img,
                "description": os.path.splitext(os.path.basename(img))[0],
            })

    return analysis


def check_auto_video_available() -> bool:
    """Check if auto-video-platform is importable and has required dependencies."""
    try:
        from builders.asset_pipeline import AssetPipeline
        from builders.assembly_engine import AssemblyEngine
        return True
    except ImportError as e:
        logger.warning(f"auto-video-platform not fully available: {e}")
        return False


# ─── C1 Pipeline Integration ────────────────────────────────────


def plan_to_images(
    product_images: list[str],
    industry: str = "鞋类",
    platforms: list[str] = None,
    creative_brief: dict = None,
    product_analysis: dict = None,
    output_dir: str = None,
    skip_analysis: bool = False,
) -> dict:
    """Run the C1 image generation pipeline.

    Product photos → Product Analysis → Creative Brief → Scene Generation
    → Product-on-Scene Compositing → Multi-Platform Adaptation.

    Args:
        product_images: List of product photo file paths (3-10 recommended)
        industry: Product category for AI analysis
        platforms: Target platforms (default: douyin + xiaohongshu + taobao)
        creative_brief: Pre-computed brief dict (skips AI if provided)
        product_analysis: Pre-computed analysis dict (skips AI if provided)
        output_dir: Output directory for composited images
        skip_analysis: Skip AI entirely, use provided or cached data

    Returns:
        dict with keys: output_dir, scene_paths, composite_paths, total_images,
                        product_analysis, creative_brief, ok
    """
    from builders.c1_pipeline import C1Pipeline

    if output_dir is None:
        from config import Config
        output_dir = os.path.join(Config.DATA_DIR, "c1_output", f"run_{int(time.time())}")

    pipeline = C1Pipeline(output_dir=output_dir)
    result = pipeline.run(
        product_images=product_images,
        industry=industry,
        platforms=platforms or ["douyin", "xiaohongshu", "taobao"],
        creative_brief=creative_brief,
        product_analysis=product_analysis,
        skip_analysis=skip_analysis,
    )

    return {
        "output_dir": result.output_dir,
        "scene_paths": result.scene_paths,
        "composite_paths": result.composite_paths,
        "total_images": result.total_images,
        "product_analysis": result.product_analysis,
        "creative_brief": result.creative_brief,
        "ok": result.ok,
    }
