"""Video Renderer — FrameCraft's native video export pipeline.

Encapsulates: plan → Script → TTS → Assets → HTML → MP4
Fully independent — zero code dependency on auto-video-platform.

Usage:
    from services.video_renderer import render_video

    result = render_video(plan=plan_dict, scene_images=["..."], platform="douyin")
    # result.html_path, result.mp4_path, result.audio_path
"""

import json
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

from services.script_models import Beat, Script


# ── Constants ─────────────────────────────────────────────────

_SCRIPT_TYPE_TO_VIDEO_TYPE = {
    "with_cart": "product_promo",
    "no_cart": "product_promo",
    "live": "vlog",
}

_VIDEO_TYPE_TO_COMPONENT_SET = {
    "ai_flaw_detect": "ai_flaw_detect",
    "product_promo": "ecommerce",
    "factory_promo": "ecommerce",
    "tutorial": "ecommerce",
    "vlog": "ecommerce",
}

_INDUSTRY_TAGS = {
    "鞋类": ["鞋类测评", "好鞋推荐", "穿搭", "平价款", "国货鞋"],
    "服装": ["穿搭", "好物推荐", "服装测评", "显瘦穿搭", "平价穿搭"],
    "美妆": ["美妆测评", "平价好物", "妆容教程", "护肤", "好物推荐"],
    "食品": ["零食测评", "美食推荐", "好吃不贵", "追剧零食", "吃货"],
    "3C数码": ["数码测评", "数码好物", "科技", "好物推荐", "测评"],
    "家居": ["家居好物", "居家好物", "收纳", "平价家居", "好物推荐"],
}

_PLATFORM_DIMENSIONS = {
    "douyin": (1080, 1920),
    "kuaishou": (1080, 1920),
    "xiaohongshu": (1080, 1440),
    "shipinhao": (1080, 1920),
    "taobao": (800, 800),
    "jingdong": (800, 800),
    "pdd": (1080, 1440),
    "default": (1080, 1920),
}

_POSITION_EMOTION = {
    1: "hook",
    2: "curiosity",
    3: "trust",
    4: "desire",
    5: "trust",
    6: "desire",
    7: "action",
}

_TIER_ANIMATION = {
    "L1": "pop",
    "L2": "zoom",
    "L3": "slide",
}


# ── Public API ────────────────────────────────────────────────


class VideoRenderResult:
    """Result from render_video()."""

    def __init__(self, plan_index: int = 0, script: Script = None,
                 output_dir: str = "", html_path: str = "", mp4_path: str = "",
                 audio_path: str = "", srt_path: str = "",
                 duration_s: float = 0.0, error: str = ""):
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


def plan_to_script(
    plan: dict,
    industry: str = "鞋类",
    script_type: str = "with_cart",
    creative_brief: dict = None,
    product_analysis: dict = None,
) -> Script:
    """Convert a FrameCraft shooting plan into a Beat-level Script."""
    storyboard = plan.get("script", {}).get("storyboard", [])
    if not storyboard:
        raise ValueError("Plan has no storyboard")

    # Title
    raw_titles = plan.get("titles", plan.get("title", f"{industry}产品展示"))
    if isinstance(raw_titles, list) and len(raw_titles) > 0:
        title = raw_titles[0].get("text", f"{industry}产品展示") if isinstance(raw_titles[0], dict) else str(raw_titles[0])
    elif isinstance(raw_titles, str):
        title = raw_titles
    else:
        title = f"{industry}产品展示"

    # Hook type
    hook_type = plan.get("hook_type", "身份认同型")
    if isinstance(raw_titles, list) and len(raw_titles) > 0 and isinstance(raw_titles[0], dict):
        hook_type = raw_titles[0].get("type", hook_type)

    top_hook_types = plan.get("top_hook_types", [])
    if not top_hook_types and isinstance(raw_titles, list):
        top_hook_types = [t.get("type", "") for t in raw_titles if isinstance(t, dict) and t.get("type")]
    if hook_type and hook_type not in top_hook_types:
        top_hook_types.insert(0, hook_type)

    # Beats
    beats = []
    for i, shot in enumerate(storyboard):
        sn = shot.get("shot", i + 1)
        text = shot.get("audio_l1", shot.get("audio", shot.get("visual", "")))
        visual = shot.get("visual", "")
        tier = shot.get("tier", "L1")
        raw_dur = shot.get("duration", 0)
        try:
            dur = float(str(raw_dur).replace("s", "").strip())
        except (ValueError, TypeError):
            dur = 3.5 if sn == 1 else 4.0

        emotion = _POSITION_EMOTION.get(sn, "trust")
        animation = _TIER_ANIMATION.get(tier, "fade")

        beat = Beat(
            index=sn, text=text or "", visual=visual or "",
            animation=animation, emotion=emotion, duration_s=max(dur, 2.0),
            is_save_trigger=(sn == len(storyboard)),
            is_share_trigger=(sn == max(1, len(storyboard) - 1)),
            is_comment_trigger=(sn == len(storyboard)),
            caption=shot.get("caption", ""),
            how_to_shoot=shot.get("how_to_shoot", ""),
            tier=tier,
            audio_l2_text=shot.get("audio_l2", ""),
        )
        beats.append(beat)

    # Outro
    outro = Beat(
        index=len(beats) + 1,
        text="截图保存拍摄方案，下次直接对照拍。关注我，每天一个电商拍摄技巧。",
        visual="品牌logo + 关注引导 + 拍摄方案清单",
        animation="pop", emotion="action", duration_s=5.0,
        is_save_trigger=True, is_share_trigger=True, is_comment_trigger=True,
    )

    # Creative brief extraction
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

    template_card = plan.get("shooting_template_card", {})
    bgm_style = template_card.get("bgm_pick", bgm_info.get("style", "轻快时尚"))
    if isinstance(bgm_style, str) and "剪映" in bgm_style:
        bgm_style = bgm_style.replace("剪映热门BGM「", "").replace("」", "")

    bgm_search_keywords = bgm_info.get("search_keywords", bgm_info.get("recommendations", []))
    if isinstance(bgm_search_keywords, str):
        bgm_search_keywords = [bgm_search_keywords]

    composition_style = creative_brief.get("composition_style", "")
    model_direction = creative_brief.get("model_direction", "")
    if isinstance(model_direction, dict):
        model_direction = json.dumps(model_direction, ensure_ascii=False)
    differentiation = creative_brief.get("differentiation", "")

    # Product analysis extraction
    if product_analysis is None:
        product_analysis = plan.get("product_analysis", {})
    if isinstance(product_analysis, str):
        try:
            product_analysis = json.loads(product_analysis)
        except (json.JSONDecodeError, TypeError):
            product_analysis = {}
    key_features = product_analysis.get("key_features", [])

    # Checklist
    checklist_lines = []
    if template_card.get("equipment_needed"):
        checklist_lines.append(template_card["equipment_needed"][:40])
    if template_card.get("pitfall_alert"):
        checklist_lines.append(template_card["pitfall_alert"][:40])
    checklist = " | ".join(checklist_lines) if checklist_lines else "手机拍摄秘籍"

    # Tags
    tags = list(_INDUSTRY_TAGS.get(industry, _INDUSTRY_TAGS["鞋类"]))
    if key_features:
        tags = key_features[:3] + tags
    if differentiation and len(differentiation) < 20:
        tags.insert(0, differentiation)

    total = sum(b.duration_s for b in beats) + outro.duration_s

    return Script(
        title=title[:15] if title else f"{industry}拍摄",
        hook_type=hook_type, beats=beats, outro=outro,
        tags=tags, bgm_style=bgm_style, checklist=checklist,
        total_duration_s=total,
        bgm_search_keywords=bgm_search_keywords,
        bgm_tempo_bpm=bgm_info.get("tempo_bpm", ""),
        bgm_usage_tips=bgm_info.get("usage_tips", ""),
        composition_style=composition_style,
        model_direction=model_direction,
        differentiation=differentiation,
        key_features=key_features,
        top_hook_types=top_hook_types,
    )


def render_video(
    plan: dict,
    scene_images: list[str] = None,
    output_dir: str = None,
    video_type: str = "product_promo",
    platform: str = "douyin",
    industry: str = "鞋类",
    script_type: str = "with_cart",
    tts_voice: str = "zh-CN-YunxiNeural",
    tts_speed: float = 1.15,
    skip_mp4: bool = False,
    bgm: bool = False,
    creative_brief: dict = None,
    product_analysis: dict = None,
) -> VideoRenderResult:
    """Render a FrameCraft plan to finished MP4 video.

    Returns VideoRenderResult with html_path, mp4_path, audio_path, srt_path.
    """
    t0 = time.time()
    scene_images = scene_images or []

    # 1. Plan → Script
    script = plan_to_script(plan, industry, script_type,
                            creative_brief=creative_brief,
                            product_analysis=product_analysis)
    logger.info(f"Script: {script.title}, {len(script.beats)} beats, {script.total_duration_s:.1f}s")

    # 2. QA Gate
    try:
        from services.gatekeeper import review
        qa_report = review(plan, industry)
        if not qa_report.pass_ or qa_report.score < 70:
            return VideoRenderResult(
                script=script, output_dir=output_dir or "",
                error=f"QA rejected (score={qa_report.score}/100): {qa_report.summary}",
            )
        logger.info(f"QA passed: {qa_report.score}/100")
    except ImportError:
        pass

    # 3. Output directory
    if not output_dir:
        from config import Config
        output_dir = os.path.join(Config.DATA_DIR, "videos", f"render_{uuid.uuid4().hex[:8]}")
    os.makedirs(output_dir, exist_ok=True)

    # 4. Build ref_analysis
    ref_analysis = _build_ref_analysis(plan, scene_images, creative_brief)

    # 5. Asset pipeline
    from services.rendering.asset_pipeline import AssetPipeline
    assets_dir = os.path.join(output_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    asset_pipeline = AssetPipeline(assets_dir=assets_dir)

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
    logger.info(f"Assets: {summary['total_beats']} beats, {summary['local_assets']} local")

    if summary['generation_needed'] > 0:
        logger.info(f"Generating {summary['generation_needed']} missing assets...")
        asset_plan = asset_pipeline.generate_missing(asset_plan)

    # 6. Assembly
    from services.rendering.assembler import FrameAssembler
    width, height = _PLATFORM_DIMENSIONS.get(platform, _PLATFORM_DIMENSIONS["default"])
    component_set = _VIDEO_TYPE_TO_COMPONENT_SET.get(video_type, "ecommerce")
    assembler = FrameAssembler(
        output_dir=output_dir, tts_voice=tts_voice, tts_speed=tts_speed,
        canvas_width=width, canvas_height=height, component_set=component_set,
    )

    if bgm:
        logger.info("BGM download requested but not yet implemented in FrameCraft")
    bgm_path = ""

    try:
        result = assembler.assemble(script, asset_plan, bgm_path, ref_analysis)
    except Exception as e:
        logger.exception("Assembly failed")
        return VideoRenderResult(script=script, output_dir=output_dir, error=f"Assembly failed: {e}")

    # 7. MP4 render
    mp4_path = ""
    if not skip_mp4:
        try:
            from services.rendering.chromium_renderer import ChromiumRenderer
            renderer = ChromiumRenderer()
            mp4_path = renderer.render(
                html_dir=output_dir,
                audio_path=result.audio_path if os.path.exists(result.audio_path) else "",
                duration_s=result.total_duration_s,
                output_path=os.path.join(output_dir, "output.mp4"),
            )
        except FileNotFoundError:
            logger.warning("Chromium not found — skipping MP4 render")
        except Exception as e:
            logger.warning(f"MP4 render failed (non-blocking): {e}")

    elapsed = time.time() - t0
    logger.info(f"Video render complete in {elapsed:.1f}s → {output_dir}")

    return VideoRenderResult(
        script=script, output_dir=output_dir,
        html_path=result.html_path, mp4_path=mp4_path,
        audio_path=result.audio_path, srt_path=result.srt_path,
        duration_s=result.total_duration_s,
    )


def check_renderer_available() -> bool:
    """Check if rendering engine dependencies are importable."""
    try:
        from services.rendering.asset_pipeline import AssetPipeline
        from services.rendering.assembler import FrameAssembler
        return True
    except ImportError as e:
        logger.warning(f"Renderer not available: {e}")
        return False


# ── Helpers ────────────────────────────────────────────────────

def _build_ref_analysis(plan: dict, scene_images: list[str], creative_brief: dict = None) -> dict:
    """Build ref_analysis dict from plan data for the asset pipeline."""
    analysis = {
        "description": "",
        "image_path": scene_images[0] if scene_images else "",
        "results": [],
        "brand_style": {},
    }

    template_card = plan.get("shooting_template_card", {})
    if template_card.get("best_scene"):
        analysis["description"] += f"推荐场景: {template_card['best_scene']}. "
    if template_card.get("tier_label"):
        analysis["description"] += f"拍摄级别: {template_card['tier_label']}. "

    titles = plan.get("titles", "")
    if titles:
        analysis["description"] += f"视频主题: {titles}. "

    # Brand colors from creative_brief
    if creative_brief:
        cp = creative_brief.get("color_palette", {})
        if cp:
            analysis["brand_style"]["colors"] = {
                "primary": cp.get("primary", ""),
                "secondary": cp.get("secondary", ""),
                "accent": cp.get("accent", ""),
            }
        for key in ("concept_name", "composition_style", "differentiation"):
            if creative_brief.get(key):
                analysis["brand_style"][key] = creative_brief[key]
        if creative_brief.get("mood_keywords"):
            analysis["brand_style"]["mood_tags"] = creative_brief["mood_keywords"]
        md = creative_brief.get("model_direction")
        if md:
            analysis["brand_style"]["model_direction"] = json.dumps(md, ensure_ascii=False) if isinstance(md, dict) else str(md)
        bgm = creative_brief.get("bgm_suggestion", {})
        if isinstance(bgm, dict):
            for key in ("tempo_bpm", "style", "search_keywords"):
                if bgm.get(key):
                    analysis["brand_style"][f"bgm_{key}"] = bgm[key]

    if not analysis["brand_style"].get("colors"):
        color_palette = template_card.get("color_palette") or plan.get("color_palette") or {}
        if color_palette:
            analysis["brand_style"]["colors"] = color_palette

    # Product features
    product_analysis = plan.get("product_analysis", {})
    if isinstance(product_analysis, str):
        try:
            product_analysis = json.loads(product_analysis)
        except (json.JSONDecodeError, TypeError):
            product_analysis = {}
    for key in ("key_features", "design_highlights"):
        if product_analysis.get(key):
            analysis["brand_style"][key] = product_analysis[key]

    # Scene image entries
    for img in scene_images:
        if os.path.exists(img):
            analysis["results"].append({
                "image_path": img,
                "description": os.path.splitext(os.path.basename(img))[0],
            })

    return analysis
