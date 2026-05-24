"""Plan generation service — vision analysis, plan generation, persistence."""
import json
import logging
import os
import random
import uuid
from concurrent.futures import ThreadPoolExecutor

from config import Config
from services.ai_client import _get_doubao_client, _get_client, _image_to_data_url
from services.prompt_engine import (
    CATEGORY_CONFIGS,
    DEFAULT_CATEGORY_CONFIG,
    SCRIPT_TYPES,
    build_vision_prompt,
    build_plan_prompt,
)
from services.json_repair import repair_truncated_json
from services.gatekeeper import review_all, QAReport

logger = logging.getLogger(__name__)


def analyze_product_images(image_paths: list[str], industry: str) -> str:
    """Run vision analysis on product images, returns description string."""
    cat_cfg = CATEGORY_CONFIGS.get(industry, DEFAULT_CATEGORY_CONFIG)
    vision_client = _get_doubao_client()
    if not vision_client:
        raise RuntimeError("豆包 Vision 未配置")

    vision_dims = cat_cfg["vision_dims"]
    if len(image_paths) == 1:
        vision_content = [
            {"type": "image_url", "image_url": {"url": _image_to_data_url(image_paths[0])}},
            {"type": "text", "text": f"你是{industry}产品鉴定专家。请仔细观察图片，按以下维度精准描述（80-120字）：\n\n{vision_dims}\n\n用简洁中文，严格基于图片内容，不要编造不存在的特征。注意：图片可能是纯背景的产品白底图，请根据实际可见内容描述。"},
        ]
    else:
        vision_content = [{"type": "text", "text": f"你是{industry}产品鉴定专家。以下是同一产品的{len(image_paths)}张多角度实拍图，请综合分析所有图片，按以下维度精准描述（100-150字）：\n\n{vision_dims}\n\n用简洁中文，综合所有图片信息，严格基于图片内容，不要编造不存在的特征。"}]
        for p in image_paths:
            vision_content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(p)}})

    resp = vision_client.chat.completions.create(
        model=Config.DOUBAO_VISION_MODEL,
        messages=[{"role": "user", "content": vision_content}],
    )
    return resp.choices[0].message.content.strip()


def _ensure_required_fields(plan: dict) -> dict:
    """Post-process a generated plan to guarantee shooting_tier, shooting_template_card,
    storyboard[].how_to_shoot, and storyboard[].tier are present.
    If the AI model omitted them, derive sensible defaults from existing fields."""
    # 1. Ensure top-level shooting_tier
    if "shooting_tier" not in plan or not plan["shooting_tier"]:
        plan["shooting_tier"] = "L1"

    # 2. Ensure shooting_template_card
    if "shooting_template_card" not in plan or not plan.get("shooting_template_card"):
        tier = plan.get("shooting_tier", "L1")
        if tier == "L1":
            plan["shooting_template_card"] = {
                "tier_label": "📱 手机随手出片",
                "equipment_needed": "一部手机，自然光，无需其他设备",
                "best_scene": "窗边白墙前，光线最好的位置",
                "time_needed": "拍摄5分钟 + 剪辑3分钟 = 共8分钟",
                "pitfall_alert": "不要逆光拍，产品会漆黑一片。面对窗户让光从侧面来。",
                "editing_recipe": "① 剪映导入素材 → ② 选「一键成片」模板 → ③ 导出1080p",
                "bgm_pick": "剪映热门BGM「轻快时尚」或搜索「穿搭卡点」",
            }
        else:
            plan["shooting_template_card"] = {
                "tier_label": "📱+💡 手机+简单道具",
                "equipment_needed": "手机 + 三脚架/自拍杆 + 环形补光灯（可选）",
                "best_scene": "家里腾出2平米空地，靠窗位置",
                "time_needed": "拍摄10分钟 + 剪辑5分钟 = 共15分钟",
                "pitfall_alert": "手持拍摄容易抖，用支架固定或双手握紧夹住身体。",
                "editing_recipe": "① 剪映导入素材 → ② 卡点剪辑+滤镜「复古棕」 → ③ 添加字幕导出1080p",
                "bgm_pick": "剪映音频搜「潮流穿搭」或「复古街拍BGM」",
            }

    # 3. Ensure storyboard shots have tier, how_to_shoot, audio_l1, audio_l2
    storyboard = plan.get("script", {}).get("storyboard", [])
    default_howto = {
        1: "手机横握平拍，与被摄物同高，保持稳定",
        2: "手机靠近产品30cm，点击屏幕对焦，拍特写",
        3: "手机倒扣放地上，镜头朝上仰拍鞋底",
        4: "手机侧拍，利用窗边自然光从侧面打过来",
        5: "手机手持俯拍，自然站立向下拍",
        6: "手机固定在三脚架上，正面平拍全身或半身",
        7: "手机手持慢动作跟拍，保持画面平稳",
    }
    for shot in storyboard:
        sn = shot.get("shot", 0)
        if "tier" not in shot or not shot["tier"]:
            shot["tier"] = plan.get("shooting_tier", "L1")
        if "how_to_shoot" not in shot or not shot["how_to_shoot"]:
            shot["how_to_shoot"] = default_howto.get(sn, "手机平拍，利用自然光，保持画面稳定")

        # Migrate old "audio" field if present, then ensure audio_l1/audio_l2 exist
        old_audio = shot.pop("audio", None)
        if "audio_l1" not in shot or not shot.get("audio_l1"):
            shot["audio_l1"] = old_audio if old_audio else shot.get("visual", "产品展示")
        if "audio_l2" not in shot or not shot.get("audio_l2"):
            shot["audio_l2"] = old_audio if old_audio else shot.get("visual", "产品展示")

    return plan


def generate_single_plan(deepseek, prompt: str, variant_index: int) -> tuple:
    """Generate a single plan with retry logic. Returns (plan_dict, None) or (None, error_text)."""
    last_error_text = ""
    for attempt in range(3):
        resp = deepseek.chat.completions.create(
            model=Config.DEEPSEEK_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt + (f"\n\n(第{attempt + 1}次尝试，必须输出完整JSON)" if attempt > 0 else ""),
                }
            ],
            temperature=0.88 + attempt * 0.02,
            max_tokens=8000,
            timeout=180,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.startswith("```"))

        try:
            plan = json.loads(text)
            return (_ensure_required_fields(plan), None)
        except json.JSONDecodeError as e:
            logger.warning(f"Variant {variant_index} JSON attempt {attempt + 1} failed: {e}")
            repaired = repair_truncated_json(text)
            try:
                plan = json.loads(repaired)
                return (_ensure_required_fields(plan), None)
            except json.JSONDecodeError:
                last_error_text = text
                continue

    return (None, last_error_text)


def generate_plans(
    product_desc: str,
    extra_info: str,
    industry: str,
    script_type: str,
    variant_count: int,
    reference_top_plan: dict | None = None,
) -> dict:
    """Generate 1-5 shooting plan variants. Returns result dict with plans, errors, etc."""
    st = SCRIPT_TYPES[script_type]
    deepseek = _get_client()
    base_seed = random.randint(1000, 9999)

    plans = []
    errors = []

    def gen_variant(i):
        seed = base_seed + i * 777
        prompt = build_plan_prompt(product_desc, extra_info, industry, st, seed, i, variant_count, reference_top_plan)
        return generate_single_plan(deepseek, prompt, i)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(gen_variant, i) for i in range(1, variant_count + 1)]
        for i, future in enumerate(futures):
            plan, error = future.result()
            if plan is not None:
                plans.append(plan)
            else:
                errors.append(f"方案{i + 1}")
                if error:
                    debug_path = os.path.join(Config.UPLOADS_DIR, f"debug_variant_{uuid.uuid4().hex[:8]}.txt")
                    with open(debug_path, "w", encoding="utf-8") as df:
                        df.write(error)
                    logger.error(f"Variant {i + 1} failed, saved to {debug_path}")

    if not plans:
        raise RuntimeError(f"所有方案生成失败（{', '.join(errors)}），请重试")

    # Gatekeeper QA: review all plans, sort by quality score
    qa_reports = review_all(plans, industry, deep_check=False)
    qa_map = {r.plan_index: r for r in qa_reports}

    for i, plan in enumerate(plans):
        plan_index = i + 1
        report = qa_map.get(plan_index)
        if report:
            plan["_qa"] = {
                "score": report.score,
                "pass": report.pass_,
                "dimensions": report.dimensions,
                "issues_count": len(report.issues),
                "summary": report.summary,
            }

    plans.sort(key=lambda p: p.get("_qa", {}).get("score", 0), reverse=True)

    return {
        "plans": plans,
        "errors": errors if errors else None,
        "variant_count": len(plans),
        "qa_reports": [
            {
                "plan_index": r.plan_index,
                "score": r.score,
                "pass": r.pass_,
                "dimensions": r.dimensions,
                "summary": r.summary,
                "issues": [{"dimension": i.dimension, "severity": i.severity, "field": i.field, "message": i.message, "fix": i.fix_suggestion} for i in r.issues],
            }
            for r in qa_reports
        ],
    }


def generate_plans_with_progress(
    product_desc: str,
    extra_info: str,
    industry: str,
    script_type: str,
    variant_count: int,
    on_progress,
    reference_top_plan: dict | None = None,
) -> dict:
    """Generate plans with per-variant progress callbacks.

    on_progress(event: dict) is called from worker threads.
    Events: {"type": "variant_started", "variant": N, "total": M}
            {"type": "variant_complete", "variant": N, "plan": {...}}
    """
    st = SCRIPT_TYPES[script_type]
    deepseek = _get_client()
    base_seed = random.randint(1000, 9999)

    plans = []
    errors = []

    def gen_variant(i):
        on_progress({"type": "variant_started", "variant": i, "total": variant_count})
        seed = base_seed + i * 777
        prompt = build_plan_prompt(product_desc, extra_info, industry, st, seed, i, variant_count, reference_top_plan)
        plan, error = generate_single_plan(deepseek, prompt, i)
        if plan is not None:
            on_progress({"type": "variant_complete", "variant": i, "plan": plan})
        return (plan, error)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(gen_variant, i) for i in range(1, variant_count + 1)]
        for i, future in enumerate(futures):
            plan, error = future.result()
            if plan is not None:
                plans.append(plan)
            else:
                errors.append(f"方案{i + 1}")
                if error:
                    debug_path = os.path.join(Config.UPLOADS_DIR, f"debug_variant_{uuid.uuid4().hex[:8]}.txt")
                    with open(debug_path, "w", encoding="utf-8") as df:
                        df.write(error)
                    logger.error(f"Variant {i + 1} failed, saved to {debug_path}")

    if not plans:
        raise RuntimeError(f"所有方案生成失败（{', '.join(errors)}），请重试")

    # Gatekeeper QA
    on_progress({"type": "qa_started", "plan_count": len(plans)})
    qa_reports = review_all(plans, industry, deep_check=False)
    qa_map = {r.plan_index: r for r in qa_reports}

    for i, plan in enumerate(plans):
        plan_index = i + 1
        report = qa_map.get(plan_index)
        if report:
            plan["_qa"] = {
                "score": report.score,
                "pass": report.pass_,
                "dimensions": report.dimensions,
                "issues_count": len(report.issues),
                "summary": report.summary,
            }

    plans.sort(key=lambda p: p.get("_qa", {}).get("score", 0), reverse=True)
    on_progress({"type": "qa_complete", "reports": [{"plan_index": r.plan_index, "score": r.score, "pass": r.pass_} for r in qa_reports]})

    return {
        "plans": plans,
        "errors": errors if errors else None,
        "variant_count": len(plans),
        "qa_reports": [
            {
                "plan_index": r.plan_index,
                "score": r.score,
                "pass": r.pass_,
                "dimensions": r.dimensions,
                "summary": r.summary,
                "issues": [{"dimension": i.dimension, "severity": i.severity, "field": i.field, "message": i.message, "fix": i.fix_suggestion} for i in r.issues],
            }
            for r in qa_reports
        ],
    }

def auto_describe(image_paths: list[str], industry: str, extra_info: str = "") -> str:
    """AI-assisted product description generation."""
    cat_cfg = CATEGORY_CONFIGS.get(industry, DEFAULT_CATEGORY_CONFIG)

    # Vision analysis
    vision_client = _get_doubao_client()
    if not vision_client:
        raise RuntimeError("豆包 Vision 未配置")

    vision_dims = cat_cfg["vision_dims"]
    if len(image_paths) == 1:
        vision_content = [
            {"type": "image_url", "image_url": {"url": _image_to_data_url(image_paths[0])}},
            {"type": "text", "text": f"你是{industry}产品专家。请仔细观察图片，按以下维度精准描述（80-120字）：\n\n{vision_dims}\n\n用简洁中文，严格基于图片内容，不要编造不存在的特征。"},
        ]
    else:
        vision_content = [{"type": "text", "text": f"你是{industry}产品专家。以下是同一产品的{len(image_paths)}张多角度实拍图，请综合分析（100-150字）：\n\n{vision_dims}\n\n用简洁中文，综合所有图片信息，严格基于图片内容。"}]
        for p in image_paths:
            vision_content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(p)}})

    resp = vision_client.chat.completions.create(
        model=Config.DOUBAO_VISION_MODEL,
        messages=[{"role": "user", "content": vision_content}],
    )
    vision_desc = resp.choices[0].message.content.strip()

    deepseek = _get_client()
    if not deepseek:
        return vision_desc

    user_hint = f"\n\n用户额外补充：{extra_info}" if extra_info.strip() else ""
    craft_prompt = f"你是{industry}电商文案专家。根据以下产品视觉分析结果，写一段\"产品补充说明\"（50-120字），方便后续AI生成拍摄方案时参考。\n\n产品视觉分析：{vision_desc}{user_hint}\n\n要求：用口语化中文，突出核心卖点（材质/设计/价格/受众），像卖家在跟拍摄团队交流一样写。直接输出文案，不加引号或标记。"

    craft_resp = deepseek.chat.completions.create(
        model=Config.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": craft_prompt}],
        max_tokens=400,
    )
    return craft_resp.choices[0].message.content.strip()
