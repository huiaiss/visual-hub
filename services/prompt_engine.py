"""Prompt building and category configurations for FrameCraft shooting plan generation.

Knowledge injection from script_knowledge.py (GitHub-sourced best practices):
- Streamer-Sales (3.7k stars): live streaming personas, compliance, customer psychology
- MoneyPrinterTurbo (39.9k stars): hook frameworks, shot structure, title formulas
- OpenReels + VideoProduction: BGM mixing, editing transitions, color grading

Shooting tier system: L1=手机随手拍 L2=手机+简单道具 L3=专业团队

Data loaded from config/prompts/*.yaml — edit YAML to tune prompts without touching code.
"""
import time
import json
import yaml
from pathlib import Path

from services.script_knowledge import (
    HOOK_BLUEPRINTS,
    SHOT_STRUCTURE,
    EMOTIONAL_ARC,
    BGM_KNOWLEDGE,
    LIVE_STREAM_PATTERNS,
    ANCHOR_PERSONAS,
    EDITING_KNOWLEDGE,
    TITLE_FORMULAS,
    SHOOTING_TIERS,
    SHOOTING_PITFALLS,
    SCENE_REPLACEMENTS,
    PAIN_POINTS_BY_INDUSTRY,
    CUSTOMER_PERSPECTIVE_RULES,
    SCRIPT_TIERS,
)

_PROMPTS_DIR = Path(__file__).parent.parent / "config" / "prompts"


def _load_yaml(filename: str) -> dict:
    with open(_PROMPTS_DIR / filename, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Load data from YAML ──
_vision = _load_yaml("vision_prompts.yaml")
CATEGORY_CONFIGS = _vision["category_configs"]
DEFAULT_CATEGORY_CONFIG = _vision["default_category_config"]
_VISION_PROMPT_SINGLE = _vision["vision_prompt_single"]
_VISION_PROMPT_MULTI = _vision["vision_prompt_multi"]

_plan = _load_yaml("plan_prompts.yaml")
SCRIPT_TYPES = _plan["script_types"]
VARIATION_INSTRUCTIONS = _plan["variation_instructions"]
_PLAN_PROMPT_TEMPLATE = _plan["plan_prompt_template"]


# ── Knowledge injection builder ──

def _build_knowledge_injection(industry: str, script_type: str, var_info: dict) -> str:
    """Build a condensed knowledge injection with proven patterns and tier guidance."""
    st_label = script_type
    shot_key = "7_shot_cart" if "挂车" in script_type else "7_shot_no_cart"
    shots = SHOT_STRUCTURE.get(shot_key, [])
    arc = EMOTIONAL_ARC.get(st_label, {})

    # Shot structure reference
    shot_lines = []
    for s in shots:
        shot_lines.append(f"    镜{s['shot']} [{s['purpose']}] {s['timing']}: {s['notes']}")

    # Select anchor persona
    persona_map = {"鞋类": "甜美可爱型", "服装": "甜美可爱型", "美妆": "甜美可爱型",
                   "3C数码": "专业测评型", "家居": "生活分享型", "食品": "生活分享型"}
    persona_name = persona_map.get(industry, "生活分享型")
    persona = ANCHOR_PERSONAS.get(persona_name, ANCHOR_PERSONAS["生活分享型"])

    # BGM tempo mapping
    bgm_tempo_lines = []
    for product, info in BGM_KNOWLEDGE["tempo_by_product"].items():
        bgm_tempo_lines.append(f"    {product}: {info['bpm']}BPM {info['genre']}")

    # Hook type info
    hook_type = var_info.get("type", "")
    hook_text_examples = var_info.get("text_examples", [])
    hook_visual = var_info.get("visual", "")

    # Title formula examples
    title_examples = []
    for formula_type, examples in TITLE_FORMULAS.items():
        title_examples.append(f"    {formula_type}: {' | '.join(examples[:2])}")

    # Pain point psychology for this industry
    industry_pain = PAIN_POINTS_BY_INDUSTRY.get(industry, PAIN_POINTS_BY_INDUSTRY.get("鞋类", {}))
    pain_lines = []
    for p in industry_pain.get("primary_pains", [])[:4]:
        pain_lines.append(f"    痛点「{p['pain']}」→ 客户心里话：「{p['inner_voice']}」→ 解法：{p['solution_angle']}")
    customer_mindset = industry_pain.get("customer_mindset", "")

    # Customer perspective rules (top 5)
    perspective_lines = []
    for r in CUSTOMER_PERSPECTIVE_RULES[:5]:
        perspective_lines.append(f"    {r}")

    # Script tier guidance
    l1_script = SCRIPT_TIERS["L1_小白版"]
    l2_script = SCRIPT_TIERS["L2_专业主播版"]

    # Compliance dict
    compliance_items = []
    for bad, good in list(LIVE_STREAM_PATTERNS["compliance_replacements"].items())[:5]:
        compliance_items.append(f"    「{bad}」→「{good}」")

    # L1 shooting guidance (DEFAULT - most important for accessibility)
    l1 = SHOOTING_TIERS["L1_极简"]
    l1_scenes = "\n".join(f"    · {s}" for s in l1["scenes"])
    l1_howto = "\n".join(f"    · {h}" for h in l1["camera_howto"])

    # L2 shooting guidance (fallback for better quality)
    l2 = SHOOTING_TIERS["L2_标准"]
    l2_scenes = "\n".join(f"    · {s}" for s in l2["scenes"])
    l2_howto = "\n".join(f"    · {h}" for h in l2["camera_howto"])

    # Pitfalls
    pitfalls_text = "\n".join(f"    {p}" for p in SHOOTING_PITFALLS[:5])

    # Scene replacements (professional → real-world substitute)
    scene_rep_lines = []
    for pro, sub in list(SCENE_REPLACEMENTS.items())[:5]:
        scene_rep_lines.append(f"    「{pro}」→ 「{sub}」")

    return f"""
# 拍摄门槛分级（默认L1极简方案，人人都能拍）

## L1 极简（手机随手出片）
  设备: {l1['equipment']}
  操作: {l1['operator']}
  场景:
{l1_scenes}
  拍法（手机怎么摆就怎么拍）:
{l1_howto}
  剪辑: {l1['editing']}
  时长: {l1['duration']}

## L2 标准（手机+简单道具）
  设备: {l2['equipment']}
  场景:
{l2_scenes}
  拍法:
{l2_howto}
  剪辑: {l2['editing']}

## 场景平替表（专业场景→素人能拍）
{chr(10).join(scene_rep_lines)}

## 素人拍鞋必看避坑指南
{pitfalls_text}

## 本方案钩子模板：{hook_type}
  文字模板: {' | '.join(hook_text_examples[:2])}
  画面模式: {hook_visual}

## {industry}客户痛点心理学（站在客户角度想问题！）
  核心洞察: {customer_mindset}
{chr(10).join(pain_lines)}

## 客户视角写作铁律（每条都必须遵守）
{chr(10).join(perspective_lines)}

## 话术分层标准（每镜必须产出两版）
  【L1 小白版】{l1_script['persona']}
    语调: {l1_script['tone']}
    用词: {l1_script['vocabulary']}
    句式: {l1_script['sentence_length']}
    结构: {l1_script['structure']}
    禁忌: {'; '.join(l1_script['taboo'][:3])}
    开场示范: {l1_script['opening_examples'][0]}
    收尾示范: {l1_script['closing_examples'][0]}

  【L2 专业主播版】{l2_script['persona']}
    语调: {l2_script['tone']}
    结构: {l2_script['structure']}
    技法: {'; '.join(l2_script['techniques'][:3])}
    开场示范: {l2_script['opening_examples'][0]}
    收尾示范: {l2_script['closing_examples'][0]}
    合规底线: {l2_script['compliance']}

## 7镜故事板情绪递进（{st_label}标准框架）
  情绪弧线: {arc.get('arc', '')}
  BGM配合: {arc.get('music_mapping', '')}
{chr(10).join(shot_lines)}

## BGM 品类→节奏映射
{chr(10).join(bgm_tempo_lines)}
  混音规则: 人声100%, BGM 25-30%, 音效10%
  找爆款BGM: {BGM_KNOWLEDGE['how_to_find_trending'][0]} / {BGM_KNOWLEDGE['how_to_find_trending'][2]}

## 标题公式
{chr(10).join(title_examples)}

## 剪辑规范
  黄金法则: {EDITING_KNOWLEDGE['golden_rules'][0]}; {EDITING_KNOWLEDGE['golden_rules'][1]}; {EDITING_KNOWLEDGE['golden_rules'][4]}
  转场: 冲击→闪白 | 细节→叠化 | 场景切换→缩放滑动 | 情绪转折→变速闪黑

## 四平台调色参数
  抖音: {EDITING_KNOWLEDGE['color_grading_by_platform']['抖音']}
  小红书: {EDITING_KNOWLEDGE['color_grading_by_platform']['小红书']}

## 主播人设: {persona_name}
  语调: {persona['tone']} | 语速: {persona['speed']}
  开场: 「{persona['opening']}」
  收尾: 「{persona['closing']}」

## 合规替换词典
{chr(10).join(compliance_items)}
"""


# ── Vision prompt builder ──

def build_vision_prompt(industry: str, image_count: int, vision_dims: str) -> list[dict]:
    """Build the vision analysis prompt content array."""
    if image_count == 1:
        text = _VISION_PROMPT_SINGLE.format(industry=industry, vision_dims=vision_dims)
        return [
            {"type": "image_url", "image_url": {"url": "{data_url}"}},
            {"type": "text", "text": text},
        ]
    else:
        text = _VISION_PROMPT_MULTI.format(industry=industry, image_count=image_count, vision_dims=vision_dims)
        return [{"type": "text", "text": text}]


# ── Plan prompt builder ──

def build_plan_prompt(
    product_desc: str,
    extra_info: str,
    industry: str,
    st: dict,
    variation_seed: int,
    variant_index: int,
    total_variants: int,
    reference_top_plan: dict | None = None,
) -> str:
    """Build the full plan generation prompt for a single variant.

    Key design principle: output schemes that ANYONE can shoot with a phone.
    Default target is L1 (phone + natural light, no model needed).
    L2 is bonus for users with tripod/ring light.
    Professional L3 is mentioned only as optional upgrade path.
    """
    st_label = st["label"]
    st_goal = st["goal"]

    var_info = VARIATION_INSTRUCTIONS.get(variant_index, VARIATION_INSTRUCTIONS[1])
    var_note = f"这是第{variant_index}/{total_variants}套方案，{var_info['instruction']}"
    if variant_index > 1:
        var_note += f"\n务必与前{variant_index - 1}套方案有明显差异：不同钩子、不同场景（都必须是素人可拍的）、不同情绪线。"

    ref_block = ""
    if reference_top_plan:
        ref_product = reference_top_plan.get("product_analysis", "")[:120]
        ref_hook = reference_top_plan.get("top_plan", {}).get("hook", {})
        ref_hook_type = ref_hook.get("type", "")
        ref_hook_desc = ref_hook.get("description", "")
        ref_titles = reference_top_plan.get("top_plan", {}).get("titles", [])
        ref_title_texts = [t.get("text", "") if isinstance(t, dict) else str(t) for t in ref_titles[:2]]
        ref_block = f"""
参考案例（同品类历史高分方案）：
- 同类产品：{ref_product}
- 高分钩子方向：{ref_hook_type} — {ref_hook_desc}
- 高分标题方向：{', '.join(ref_title_texts)}
请借鉴高分方案策略，但针对当前新品差异化调整。
"""

    knowledge = _build_knowledge_injection(industry, st["label"], var_info)

    extra = extra_info or "无额外信息，请基于视觉分析发挥"

    # Merge variant_index into format params for template
    prompt = _PLAN_PROMPT_TEMPLATE.format(
        variation_seed=variation_seed,
        variant_index=variant_index,
        total_variants=total_variants,
        st_label=st_label,
        st_goal=st_goal,
        var_note=var_note,
        ref_block=ref_block,
        product_desc=product_desc,
        extra_info=extra,
        knowledge=knowledge,
    )
    return prompt
