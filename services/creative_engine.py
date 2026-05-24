"""Creative engine: structured product analysis → creative brief → feeds plan generation.

Replaces the old "one big prompt" approach with a three-stage pipeline:
  1. analyze_product()     → Doubao Vision → structured JSON (not free text)
  2. generate_creative_brief() → DeepSeek  → concept name, mood, scenes, model, composition
  3. The existing plan_service generates full plans with this richer context
"""
import json
import logging

from config import Config
from services.ai_client import _get_doubao_client, _get_dashscope_client, _get_client, _image_to_data_url
from services.prompt_engine import CATEGORY_CONFIGS, DEFAULT_CATEGORY_CONFIG
from services.script_knowledge import BGM_KNOWLEDGE, HOOK_BLUEPRINTS, EMOTIONAL_ARC, SHOOTING_TIERS, SCENE_REPLACEMENTS

logger = logging.getLogger(__name__)

# ============ STAGE 1: Structured Product Analysis ============

_ANALYSIS_SCHEMA = """{
  "category": "具体品类（如：老爹鞋/厚底鞋）",
  "sub_category": "细分（如：复古厚底运动鞋）",
  "style_keywords": ["风格标签1", "风格标签2", "风格标签3"],
  "materials": ["材质1", "材质2"],
  "colors": [{"name": "米白", "hex_guess": "#F5F0E8"}, {"name": "灰蓝", "hex_guess": "#7B8FA1"}],
  "target_audience": {"gender": "女", "age_range": "18-28", "scenarios": ["日常通勤", "校园", "逛街"]},
  "key_features": ["卖点1", "卖点2", "卖点3"],
  "price_perception": "平价/中端/高端",
  "texture_notes": "材质质感描述（如：PU皮哑光质感，网面透气纹理）",
  "design_highlights": "设计亮点（如：圆头厚底，侧面弧线流畅，鞋舌logo刺绣）"
}"""


def _build_analysis_prompt(industry: str, image_count: int) -> str:
    cat_cfg = CATEGORY_CONFIGS.get(industry, DEFAULT_CATEGORY_CONFIG)
    return f"""你是{industry}产品鉴定专家。以下是同一产品的{image_count}张多角度实拍图。

请综合分析所有图片，严格基于图片可见内容，输出以下JSON（不要markdown代码块，直接输出JSON）：

{_ANALYSIS_SCHEMA}

规则：
- 只描述图片中实际可见的特征，不编造
- colors数组的hex_guess根据图片实际颜色推测
- target_audience根据产品风格推断
- 所有中文输出"""


def analyze_product(image_paths: list[str], industry: str) -> dict:
    """Stage 1: Vision analysis → structured JSON product profile."""
    vision_client = _get_doubao_client()
    if not vision_client:
        raise RuntimeError("豆包 Vision 未配置")

    vision_prompt = _build_analysis_prompt(industry, len(image_paths))

    if len(image_paths) == 1:
        content = [
            {"type": "image_url", "image_url": {"url": _image_to_data_url(image_paths[0])}},
            {"type": "text", "text": vision_prompt},
        ]
    else:
        content = [{"type": "text", "text": vision_prompt}]
        for p in image_paths:
            content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(p)}})

    resp = vision_client.chat.completions.create(
        model=Config.DOUBAO_VISION_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=1500,
    )
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Vision analysis JSON parse failed, returning raw text")
        return {"raw_analysis": text, "parse_error": True}


def analyze_product_qwen(image_paths: list[str], industry: str) -> dict:
    """Stage 1b: Qwen-VL-Max vision analysis → structured JSON (domestic最强VLM)."""
    client = _get_dashscope_client()
    if not client:
        raise RuntimeError("DashScope (Qwen-VL) 未配置，请在 .env 中设置 DASHSCOPE_API_KEY")

    vision_prompt = _build_analysis_prompt(industry, len(image_paths))

    if len(image_paths) == 1:
        content = [
            {"type": "image_url", "image_url": {"url": _image_to_data_url(image_paths[0])}},
            {"type": "text", "text": vision_prompt},
        ]
    else:
        content = [{"type": "text", "text": vision_prompt}]
        for p in image_paths:
            content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(p)}})

    resp = client.chat.completions.create(
        model=Config.QWEN_VL_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=1500,
    )
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Qwen-VL analysis JSON parse failed, returning raw text")
        return {"raw_analysis": text, "parse_error": True}


def _merge_analyses(doubao: dict, qwen: dict) -> dict:
    """Merge two vision analyses, preferring non-empty fields and filling gaps."""
    if doubao.get("parse_error") and qwen.get("parse_error"):
        return doubao  # both failed, return whatever we have
    if doubao.get("parse_error"):
        return qwen
    if qwen.get("parse_error"):
        return doubao

    merged = {}
    # For each key, prefer the longer/more detailed value
    for key in set(list(doubao.keys()) + list(qwen.keys())):
        dv = doubao.get(key)
        qv = qwen.get(key)
        if isinstance(dv, list) and isinstance(qv, list):
            # Merge lists, deduplicate
            seen = set()
            merged_list = []
            for item in dv + qv:
                if isinstance(item, dict):
                    item_str = json.dumps(item, ensure_ascii=False, sort_keys=True)
                else:
                    item_str = str(item)
                if item_str not in seen:
                    seen.add(item_str)
                    merged_list.append(item)
            merged[key] = merged_list
        elif isinstance(dv, dict) and isinstance(qv, dict):
            merged[key] = {**dv, **qv}  # merge dicts, qwen overrides
        elif dv and qv:
            merged[key] = dv if len(str(dv)) >= len(str(qv)) else qv
        else:
            merged[key] = dv or qv
    return merged


def analyze_product_ensemble(image_paths: list[str], industry: str) -> dict:
    """Run both Doubao and Qwen vision analysis, merge for best accuracy."""
    import concurrent.futures

    doubao_result = None
    qwen_result = None
    doubao_error = None
    qwen_error = None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        doubao_future = executor.submit(analyze_product, image_paths, industry)
        qwen_future = None
        if Config.DASHSCOPE_API_KEY:
            qwen_future = executor.submit(analyze_product_qwen, image_paths, industry)

        try:
            doubao_result = doubao_future.result(timeout=90)
        except Exception as e:
            doubao_error = str(e)
            logger.warning(f"Doubao analysis failed: {e}")

        if qwen_future:
            try:
                qwen_result = qwen_future.result(timeout=90)
            except Exception as e:
                qwen_error = str(e)
                logger.warning(f"Qwen-VL analysis failed: {e}")

    if doubao_error and qwen_error:
        raise RuntimeError(f"Both vision models failed. Doubao: {doubao_error}; Qwen: {qwen_error}")
    if doubao_error and not qwen_result:
        raise RuntimeError(f"Doubao failed and Qwen unavailable: {doubao_error}")

    if qwen_result:
        return _merge_analyses(doubao_result or {}, qwen_result)
    return doubao_result or {}


# ============ STAGE 2: Creative Brief Generation ============

_CREATIVE_BRIEF_SCHEMA = """{
  "concept_name": "创意概念名（如：城市漫游者、午后慢时光）",
  "concept_story": "一句话解释这个概念（如：在旧城区的斑马线和灰砖墙之间，用脚步丈量城市）",
  "mood_keywords": ["情绪词1", "情绪词2", "情绪词3"],
  "visual_tone": "整体视觉调性描述（50字内）",
  "scenes": [
    {
      "scene_name": "场景1名称",
      "description": "场景详细描述（光线/背景/道具/氛围）",
      "why_it_fits": "为什么这个场景适合这个产品",
      "camera_suggestion": "拍摄建议（手机具体怎么摆，不要专业术语）",
      "l1_alternative": "如果找不到这个场景，可以用什么L1场景平替（如：窗边白墙+自然光）"
    }
  ],
  "color_palette": {
    "primary": "#HEX主色",
    "secondary": "#HEX辅色",
    "accent": "#HEX点缀色",
    "rationale": "配色理由"
  },
  "model_direction": {
    "look": "模特穿搭建议",
    "pose_style": "姿态风格（优先不露脸方案）",
    "casting_notes": "选角建议（标注：可不露脸局部拍，同事即可）"
  },
  "composition_style": "整体构图风格（用手机拍法描述，如：手机倒扣地上仰拍鞋底）",
  "differentiation": "与同类产品视频的差异化方向",
  "bgm_suggestion": {"bpm_range": "推荐BPM", "genre": "推荐曲风", "mood": "音乐情绪"},
  "top_hook_types": ["最适合该产品的2-3种钩子类型（从视觉冲击/悬念好奇/身份认同/反差对比/价格锚点/场景痛点中选择）"]
}"""


def generate_creative_brief(product_analysis: dict, industry: str, extra_info: str = "") -> dict:
    """Stage 2: Structured product analysis → creative brief with concept + scenes + model + BGM."""
    client = _get_client()
    if not client:
        raise RuntimeError("DeepSeek 未配置")

    analysis_text = json.dumps(product_analysis, ensure_ascii=False, indent=2)
    user_hint = f"\n\n用户补充信息：{extra_info}" if extra_info.strip() else ""

    # Build BGM tempo reference
    bgm_lines = []
    for product, info in BGM_KNOWLEDGE["tempo_by_product"].items():
        bgm_lines.append(f"  {product}: {info['bpm']}BPM {info['genre']}")

    # Build hook blueprint reference
    hook_lines = []
    for name, details in HOOK_BLUEPRINTS.items():
        hook_lines.append(f"  {name}: {details['structure']} | 最佳: {details['best_for']}")

    # Build L1 scene reference
    l1_scenes = []
    for s in SHOOTING_TIERS["L1_极简"]["scenes"][:4]:
        l1_scenes.append(f"  · {s}")

    # Build scene replacement reference
    scene_rep = []
    for pro, sub in list(SCENE_REPLACEMENTS.items())[:4]:
        scene_rep.append(f"  · {pro} → {sub}")

    prompt = f"""你是{industry}行业创意总监，专为素人手机拍摄制定创意方案。你的受众是工厂老板/员工，只有一部手机，没有摄影基础。

根据以下产品结构化分析，为这款产品设计一个可执行的创意拍摄概念。

产品分析：
{analysis_text}{user_hint}

# BGM参考（根据产品品类匹配BPM/曲风）:
{chr(10).join(bgm_lines)}

# 钩子类型参考:
{chr(10).join(hook_lines)}

# L1极简场景库（优先使用，任何人都能拍）:
{chr(10).join(l1_scenes)}

# 场景平替表（不要写专业场景，或必须附带L1平替）:
{chr(10).join(scene_rep)}

要求：
1. concept_name独特有记忆点，不要用泛词
2. 场景必须优先选L1极简场景（窗边白墙/小区路面/对镜自拍/办公桌旁）。如果创意需要特殊场景，必须在l1_alternative字段给出平替方案
3. camera_suggestion用"手机怎么摆"描述，不要用焦段/光圈等专业术语。如"手机倒扣放地上仰拍"而非"35mm低角度仰拍"
4. model_direction优先不露脸方案——只拍脚和腿，标注"同事即可，不需要模特"
5. 配色方案给出具体hex值
6. bgm_suggestion参考上述BPM映射表
7. top_hook_types从钩子参考中选择适合品类的

请严格输出JSON（不要markdown代码块）：
{_CREATIVE_BRIEF_SCHEMA}"""

    resp = client.chat.completions.create(
        model=Config.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=3000,
        response_format={"type": "json_object"},
        timeout=120,
    )
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Creative brief JSON parse failed: {e}")
        return {"raw_brief": text, "parse_error": True}


# ============ STAGE 3: Build enriched plan prompt context ============

def build_creative_context(analysis: dict, brief: dict) -> str:
    """Build a rich context string from analysis + brief to inject into plan prompt."""
    parts = []

    if not analysis.get("parse_error"):
        parts.append(f"""【产品画像】
- 品类：{analysis.get('category', '')} / {analysis.get('sub_category', '')}
- 风格：{', '.join(analysis.get('style_keywords', []))}
- 材质：{', '.join(analysis.get('materials', []))}
- 颜色：{', '.join(c.get('name', '') for c in analysis.get('colors', []))}
- 受众：{analysis.get('target_audience', {}).get('gender', '')} {analysis.get('target_audience', {}).get('age_range', '')} · {', '.join(analysis.get('target_audience', {}).get('scenarios', []))}
- 卖点：{', '.join(analysis.get('key_features', []))}
- 质感：{analysis.get('texture_notes', '')}
- 设计亮点：{analysis.get('design_highlights', '')}""")

    if not brief.get("parse_error"):
        scenes_text = "\n".join(
            f"  · {s.get('scene_name', '')}：{s.get('description', '')}（拍摄：{s.get('camera_suggestion', '')}）（L1平替：{s.get('l1_alternative', '窗边白墙+自然光')}）"
            for s in brief.get("scenes", [])
        )
        bgm = brief.get("bgm_suggestion", {})
        bgm_text = f"  BPM {bgm.get('bpm_range', '')} / {bgm.get('genre', '')} / {bgm.get('mood', '')}" if bgm else ""
        top_hooks = brief.get("top_hook_types", [])
        hooks_text = f"  推荐钩子: {', '.join(top_hooks)}" if top_hooks else ""
        parts.append(f"""【创意大纲】
- 概念：{brief.get('concept_name', '')} — {brief.get('concept_story', '')}
- 情绪：{', '.join(brief.get('mood_keywords', []))}
- 视觉调性：{brief.get('visual_tone', '')}
- 场景方案：
{scenes_text}
- 配色方案：主色{brief.get('color_palette', {}).get('primary', '')} / 辅色{brief.get('color_palette', {}).get('secondary', '')} / 点缀{brief.get('color_palette', {}).get('accent', '')}
- 模特方向：{brief.get('model_direction', {}).get('look', '')} · {brief.get('model_direction', {}).get('pose_style', '')}
- 构图风格：{brief.get('composition_style', '')}
- 差异化：{brief.get('differentiation', '')}
- 音乐建议：{bgm_text}
-{hooks_text}""")

    return "\n".join(parts)
