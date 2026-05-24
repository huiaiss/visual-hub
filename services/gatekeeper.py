"""Gatekeeper Agent (质检师) — Comprehensive plan/script quality assurance.

Validates shooting plans across 7 dimensions before they reach the user.
Rule-based checks for mechanical issues + LLM-based checks for semantic quality.

Architecture:
  gatekeeper.review(plan, industry) → QAReport {pass, score, issues[], suggestions[]}
"""

import json
import logging
import re
from dataclasses import dataclass, field

from services.ai_client import _get_client
from config import Config
from services.script_knowledge import (
    CUSTOMER_PERSPECTIVE_RULES,
    SCRIPT_TIERS,
    PAIN_POINTS_BY_INDUSTRY,
    LIVE_STREAM_PATTERNS,
)

logger = logging.getLogger(__name__)

# ============ Data Classes ============


@dataclass
class QAIssue:
    dimension: str  # STRUCTURE | L1_SCRIPT | L2_SCRIPT | SCENE_TIER | PERSPECTIVE | COMPLIANCE | HOOK
    severity: str  # error | warning | suggestion
    field: str  # e.g. "storyboard[2].audio_l1"
    message: str  # Human-readable issue description
    fix_suggestion: str  # How to fix it


@dataclass
class QAReport:
    plan_index: int  # Which plan variant (1-based)
    pass_: bool  # True = ready for user, False = needs fix
    score: int  # 0-100
    dimensions: dict  # {dimension_name: score}
    issues: list[QAIssue] = field(default_factory=list)
    summary: str = ""


# ============ DIMENSION 1: Structure — Required Fields ============

REQUIRED_TOP_FIELDS = [
    "shooting_tier",
    "shooting_template_card",
    "titles",
    "hook",
    "script.storyboard",
]

REQUIRED_SHOT_FIELDS = [
    "shot",
    "tier",
    "visual",
    "audio_l1",
    "audio_l2",
    "how_to_shoot",
]

# Fields where short values are valid (IDs, tiers, etc.)
SHORT_VALUE_FIELDS = {"shot", "tier"}

SHOOTING_TEMPLATE_REQUIRED = [
    "tier_label",
    "equipment_needed",
    "best_scene",
    "time_needed",
    "pitfall_alert",
    "editing_recipe",
    "bgm_pick",
]


def _check_structure(plan: dict) -> tuple[int, list[QAIssue]]:
    """Check all required fields exist and are non-empty."""
    issues = []
    total_checks = 0
    passed_checks = 0

    # Top-level fields
    for field in REQUIRED_TOP_FIELDS:
        total_checks += 1
        parts = field.split(".")
        val = plan
        for p in parts:
            val = val.get(p, {}) if isinstance(val, dict) else {}
        if not val or (isinstance(val, str) and not val.strip()):
            issues.append(QAIssue(
                dimension="STRUCTURE", severity="error", field=field,
                message=f"缺少必填字段: {field}",
                fix_suggestion=f"在方案中补充 {field} 字段",
            ))
        else:
            passed_checks += 1

    # shooting_template_card sub-fields
    card = plan.get("shooting_template_card", {})
    for field in SHOOTING_TEMPLATE_REQUIRED:
        total_checks += 1
        if not card.get(field):
            issues.append(QAIssue(
                dimension="STRUCTURE", severity="warning", field=f"shooting_template_card.{field}",
                message=f"拍摄模板卡缺少: {field}",
                fix_suggestion=f"补充拍摄模板卡中的 {field} 信息",
            ))
        else:
            passed_checks += 1

    # Storyboard shots
    storyboard = plan.get("script", {}).get("storyboard", [])
    if not storyboard:
        issues.append(QAIssue(
            dimension="STRUCTURE", severity="error", field="script.storyboard",
            message="分镜表为空，至少需要7个镜头",
            fix_suggestion="生成7镜分镜表（参考 SHOT_STRUCTURE）",
        ))
        return (0, issues)

    for shot in storyboard:
        sn = shot.get("shot", "?")
        for field in REQUIRED_SHOT_FIELDS:
            total_checks += 1
            val = shot.get(field)
            # Short-value fields just need to exist (not empty/None)
            if field in SHORT_VALUE_FIELDS:
                if val is None or (isinstance(val, str) and not val.strip()):
                    issues.append(QAIssue(
                        dimension="STRUCTURE", severity="error", field=f"storyboard[{sn}].{field}",
                        message=f"第{sn}镜缺少必填字段: {field}",
                        fix_suggestion=f"为第{sn}镜补充 {field}",
                    ))
                else:
                    passed_checks += 1
                continue
            # Text fields need minimum content
            if not val or (isinstance(val, str) and len(val.strip()) < 5):
                issues.append(QAIssue(
                    dimension="STRUCTURE", severity="error", field=f"storyboard[{sn}].{field}",
                    message=f"第{sn}镜缺少必填字段: {field}",
                    fix_suggestion=f"为第{sn}镜补充 {field}",
                ))
            else:
                passed_checks += 1

    score = round(passed_checks / max(total_checks, 1) * 100)
    return (score, issues)


# ============ DIMENSION 2: L1 Script Quality ============

L1_FORBIDDEN_WORDS = [
    "家人们", "宝宝们", "姐妹们冲", "手慢无", "库存不多",
    "最后", "赶快", "赶紧抢", "拼手速",
]
L1_FORBIDDEN_PATTERNS = [
    r"(EVA|PU|TPU|飞织|人体工[学程]|包裹性|支撑性|减震|回弹率)",
    r"(最\S{1,3}[的了])",
    r"(全网\S{1,3})",
]


def _check_l1_scripts(plan: dict) -> tuple[int, list[QAIssue]]:
    """Check L1 scripts follow beginner-friendly rules."""
    issues = []
    storyboard = plan.get("script", {}).get("storyboard", [])
    if not storyboard:
        return (0, issues)

    total_checks = len(storyboard) * 5  # 5 checks per shot
    passed_checks = 0

    for shot in storyboard:
        sn = shot.get("shot", "?")
        l1 = shot.get("audio_l1", "")

        if not l1 or len(l1.strip()) < 15:
            issues.append(QAIssue(
                dimension="L1_SCRIPT", severity="error", field=f"storyboard[{sn}].audio_l1",
                message=f"第{sn}镜 L1话术太短（需≥15字），当前: {len(l1)}字",
                fix_suggestion="L1话术至少15字，包含痛点+解法+感受",
            ))
            continue

        passed_checks += 1

        # Check sentence count (should be 1-4 short sentences)
        sentences = re.split(r"[。！？\.\!\?，,]", l1)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) > 5:
            issues.append(QAIssue(
                dimension="L1_SCRIPT", severity="warning", field=f"storyboard[{sn}].audio_l1",
                message=f"第{sn}镜 L1话术句子偏多（{len(sentences)}句），建议≤4句",
                fix_suggestion="拆分为更短的句子，或精简内容",
            ))
        else:
            passed_checks += 1

        # Check sentence length (max 35 chars)
        long_sentences = [s for s in sentences if len(s) > 35]
        if long_sentences:
            issues.append(QAIssue(
                dimension="L1_SCRIPT", severity="warning", field=f"storyboard[{sn}].audio_l1",
                message=f"第{sn}镜 L1话术有{len(long_sentences)}句超过35字: {long_sentences[0][:30]}...",
                fix_suggestion="拆分长句，每句控制在35字以内",
            ))
        else:
            passed_checks += 1

        # Check forbidden words
        for word in L1_FORBIDDEN_WORDS:
            if word in l1:
                issues.append(QAIssue(
                    dimension="L1_SCRIPT", severity="error", field=f"storyboard[{sn}].audio_l1",
                    message=f"第{sn}镜 L1话术含禁止词: '{word}'（L1是朋友推荐口吻，不能用营销腔）",
                    fix_suggestion=f"将'{word}'改为更自然的日常表达",
                ))

        # Check forbidden patterns (technical jargon)
        for pattern in L1_FORBIDDEN_PATTERNS:
            match = re.search(pattern, l1)
            if match:
                issues.append(QAIssue(
                    dimension="L1_SCRIPT", severity="warning", field=f"storyboard[{sn}].audio_l1",
                    message=f"第{sn}镜 L1话术含专业术语: '{match.group(1)}'（L1不能有术语）",
                    fix_suggestion=f"将'{match.group(1)}'翻译成日常说法",
                ))

        # Check if it sounds like friend recommendation (positive check)
        friend_markers = ["我跟你说", "真的", "我觉得", "我自己", "你们看", "要不要", "可以"]
        has_friend_tone = any(m in l1 for m in friend_markers)
        if not has_friend_tone:
            issues.append(QAIssue(
                dimension="L1_SCRIPT", severity="suggestion", field=f"storyboard[{sn}].audio_l1",
                message=f"第{sn}镜 L1话术缺少朋友推荐口吻标记",
                fix_suggestion="加入'我跟你说'/'真的'/'我自己也在用'等自然表达",
            ))
        else:
            passed_checks += 1

    score = round(passed_checks / max(total_checks, 1) * 100)
    return (score, issues)


# ============ DIMENSION 3: L2 Script Quality ============

L2_REQUIRED_ELEMENTS = {
    "痛点放大": [r"(是不是|有没有|每次|受够|忍|烦|怕|担心|焦虑)"],
    "FABE产品力": [r"(材质|面料|鞋底|鞋面|设计|工艺|做工|细节|品质|质量)"],
    "信任构建": [r"(运费险|退货|质保|穿了|用了|自己|实拍|实测)"],
    "行动推动": [r"(点击|下单|链接|购物车|[1一]键|入手|带走|冲)"],
}

L2_COMPLIANCE_FORBIDDEN = list(
    LIVE_STREAM_PATTERNS.get("compliance_replacements", {}).keys()
)


def _check_l2_scripts(plan: dict) -> tuple[int, list[QAIssue]]:
    """Check L2 scripts have proper professional anchor structure."""
    issues = []
    storyboard = plan.get("script", {}).get("storyboard", [])
    if not storyboard:
        return (0, issues)

    total_checks = len(storyboard) * 3
    passed_checks = 0

    for shot in storyboard:
        sn = shot.get("shot", "?")
        l2 = shot.get("audio_l2", "")

        if not l2 or len(l2.strip()) < 15:
            issues.append(QAIssue(
                dimension="L2_SCRIPT", severity="error", field=f"storyboard[{sn}].audio_l2",
                message=f"第{sn}镜 L2话术太短（需≥15字）",
                fix_suggestion="L2话术≥30字，含FABE结构",
            ))
            continue
        passed_checks += 1

        # Check compliance: no forbidden marketing terms
        for forbidden in L2_COMPLIANCE_FORBIDDEN:
            if forbidden in l2:
                replacement = LIVE_STREAM_PATTERNS["compliance_replacements"].get(forbidden, "")
                issues.append(QAIssue(
                    dimension="L2_SCRIPT", severity="error", field=f"storyboard[{sn}].audio_l2",
                    message=f"第{sn}镜 L2话术含违规词: '{forbidden}' → 应替换为: {replacement}",
                    fix_suggestion=f"将'{forbidden}'改为'{replacement}'",
                ))

        # Check minimum length (L2 should be longer than L1)
        l1 = shot.get("audio_l1", "")
        if len(l2) < len(l1):
            issues.append(QAIssue(
                dimension="L2_SCRIPT", severity="warning", field=f"storyboard[{sn}].audio_l2",
                message=f"第{sn}镜 L2话术({len(l2)}字)比L1({len(l1)}字)还短，应该更长更详细",
                fix_suggestion="L2应比L1长，需要展开FABE+痛点放大+信任构建",
            ))
        else:
            passed_checks += 1

        # Check L2 vs L1 are actually different (not just copy)
        if l2.strip() == l1.strip():
            issues.append(QAIssue(
                dimension="L2_SCRIPT", severity="error", field=f"storyboard[{sn}].audio_l2",
                message=f"第{sn}镜 L2话术与L1完全相同，必须区分！",
                fix_suggestion="L2应有不同的口吻、更长的句子、更专业的话术结构",
            ))
        else:
            passed_checks += 1

    score = round(passed_checks / max(total_checks, 1) * 100)
    return (score, issues)


# ============ DIMENSION 4: Scene Tier — L1 Fallback ============

PROFESSIONAL_SCENE_KEYWORDS = [
    "影棚", "摄影棚", "专业灯光", "滑轨", "稳定器", "摇臂",
    "RAW", "达芬奇", "多机位", "租用", "专业模特",
]

L1_FALLBACK_SCENES = [
    "窗边白墙+自然光",
    "小区路面/花坛边",
    "办公桌/茶几旁",
    "对镜自拍",
    "家门口/走廊",
]


def _check_scene_tier(plan: dict) -> tuple[int, list[QAIssue]]:
    """Check every scene has L1 fallback and camera instructions are phone-based."""
    issues = []
    storyboard = plan.get("script", {}).get("storyboard", [])
    if not storyboard:
        return (0, issues)

    total_checks = len(storyboard) * 2
    passed_checks = 0

    for shot in storyboard:
        sn = shot.get("shot", "?")
        how_to = shot.get("how_to_shoot", "")

        # Check camera instructions contain phone-specific language
        phone_markers = ["手机", "手持", "自拍", "靠墙", "倒扣", "放地上", "三脚架", "自拍杆"]
        has_phone_instruction = any(m in how_to for m in phone_markers)
        if not has_phone_instruction:
            issues.append(QAIssue(
                dimension="SCENE_TIER", severity="warning", field=f"storyboard[{sn}].how_to_shoot",
                message=f"第{sn}镜拍摄说明缺少手机拍法描述: '{how_to[:40]}...'",
                fix_suggestion="用'手机怎么摆'描述，如'手机倒扣放地上仰拍'",
            ))
        else:
            passed_checks += 1

        # Check for professional-only scenes without L1 alternative
        has_pro_scene = any(kw in how_to for kw in PROFESSIONAL_SCENE_KEYWORDS)
        has_l1_fallback = any(kw in how_to for kw in ["窗边", "白墙", "小区", "办公桌", "对镜", "走廊", "阳台"])
        if has_pro_scene and not has_l1_fallback:
            issues.append(QAIssue(
                dimension="SCENE_TIER", severity="error", field=f"storyboard[{sn}].how_to_shoot",
                message=f"第{sn}镜含专业场景但没有L1平替方案",
                fix_suggestion="添加L1平替建议，如：'如果没这个场景，窗边白墙+自然光也能拍'",
            ))
        else:
            passed_checks += 1

    score = round(passed_checks / max(total_checks, 1) * 100)
    return (score, issues)


# ============ DIMENSION 5: Customer Perspective Rules ============

PERSPECTIVE_CHECKS = [
    {
        "rule": "先痛后解",
        "pattern": r"(是不是|有没有|受够|忍|每次|怕|担心|烦恼|困扰|焦虑)",
        "anti_pattern": r"^(这款|这双|这个产品|我们)",
        "message": "话术开头直接介绍产品，应该先从客户痛点出发",
        "fix": "先用痛点开头，如'你是不是也受够了...' 再给解法",
    },
    {
        "rule": "场景代入",
        "pattern": r"(上班|通勤|逛街|约会|面试|聚会|出门|回家|拍照|雨天|夏天|冬天)",
        "message": "话术缺少具体场景，观众无法代入",
        "fix": "加入具体场景，如'早上通勤路上'/'周末逛街穿它'",
    },
    {
        "rule": "身份喊话",
        "pattern": r"(小个子|脚宽|学生党|上班族|宝妈|通勤族|女生|男生)",
        "message": "话术缺少目标人群喊话",
        "fix": "直接喊出目标人群，如'小个子女生看过来'",
    },
    {
        "rule": "利益翻译",
        "pattern": r"(踩.*软|走.*不累|不.*脚|显.*高|显.*瘦|好.*搭)",
        "anti_pattern": r"(EVA|PU|TPU|飞织|人体工[学程]|包裹性|支撑性|减震)",
        "message": "话术用了专业术语而不是生活化利益",
        "fix": "把参数翻译成好处，'EVA发泡底'→'踩着像踩棉花'",
    },
    {
        "rule": "结果可视化",
        "pattern": r"(\d+[厘米米]|\d+[步公里]|\d+[天年月周]|\d+[块元])",
        "message": "话术缺少具体数字，建议用数据加强说服力",
        "fix": "加入具体数字，如'走2万步脚不累'/'高5厘米'",
    },
    {
        "rule": "降低防御",
        "pattern": r"(不合适.*退|运费险|试试|可以.*看|自己.*看)",
        "message": "话术缺少降低防御的表达",
        "fix": "加入'不合适随时退'/'有运费险'/'试试又不亏'等",
    },
]


def _check_perspective(plan: dict) -> tuple[int, list[QAIssue]]:
    """Check adherence to 8 customer perspective rules across all scripts."""
    issues = []
    storyboard = plan.get("script", {}).get("storyboard", [])
    if not storyboard:
        return (0, issues)

    # Combine all L1 and L2 text
    all_text = " ".join(
        s.get("audio_l1", "") + " " + s.get("audio_l2", "")
        for s in storyboard
    )

    total_checks = len(PERSPECTIVE_CHECKS)
    passed_checks = 0

    for check in PERSPECTIVE_CHECKS:
        # Check positive pattern
        if check.get("pattern"):
            if re.search(check["pattern"], all_text):
                passed_checks += 1
            else:
                issues.append(QAIssue(
                    dimension="PERSPECTIVE", severity="warning", field="all_scripts",
                    message=f"客户视角规则【{check['rule']}】: {check['message']}",
                    fix_suggestion=check["fix"],
                ))
            continue

        passed_checks += 1  # No pattern check needed

    score = round(passed_checks / max(total_checks, 1) * 100)
    return (score, issues)


# ============ DIMENSION 6: Compliance — Sensitive Words ============

COMPLIANCE_BLACKLIST = [
    # 绝对化用语
    (r"最\S{1,3}[的了]", "绝对化用语违规，改为'很'/'非常'"),
    (r"全网\S{1,4}", "全网xx违规，改为'很划算'"),
    (r"第一\S{0,2}", "含'第一'，电商法禁止"),
    (r"100%", "100%承诺违规，改为'基本都'"),
    (r"绝对\S{0,2}", "绝对化用语，删除或替换"),
    (r"保证\S{0,2}", "保证承诺违规，改用真实体验"),
    (r"肯定\S{0,2}", "肯定承诺违规，改为'我觉得'"),
    # 虚假紧迫
    (r"最后\s*\d+\s*[分钟天件双]", "虚假紧迫感违规，用真实库存/活动周期"),
    (r"马上涨价", "虚假涨价，改为'现在买最合适'"),
    (r"不买就亏", "制造焦虑违规，改为'有需要的可以考虑'"),
    (r"马上就?没[了有]", "虚假紧迫违规"),
    # 其他
    (r"包治\S{0,2}", "医疗承诺违规"),
    (r"百分百", "绝对承诺违规，改为'基本'"),
]


def _check_compliance(plan: dict) -> tuple[int, list[QAIssue]]:
    """Scan all text for prohibited words."""
    issues = []
    storyboard = plan.get("script", {}).get("storyboard", [])

    all_fields = []
    for shot in storyboard:
        sn = shot.get("shot", "?")
        for field in ["audio_l1", "audio_l2", "visual", "caption"]:
            text = shot.get(field, "")
            if text:
                all_fields.append((f"storyboard[{sn}].{field}", text))

    # Also check title
    title = plan.get("script", {}).get("title", "")
    if title:
        all_fields.append(("script.title", title))

    total_checks = len(all_fields)
    passed_checks = total_checks

    for field_name, text in all_fields:
        for pattern, warning in COMPLIANCE_BLACKLIST:
            match = re.search(pattern, text)
            if match:
                issues.append(QAIssue(
                    dimension="COMPLIANCE", severity="error", field=field_name,
                    message=f"违规词检测: '{match.group(0)}' — {warning}",
                    fix_suggestion=warning,
                ))
                passed_checks -= 1

    score = round(passed_checks / max(total_checks, 1) * 100)
    return (score, issues)


# ============ DIMENSION 7: Hook Quality ============

HOOK_TYPES = ["视觉冲击", "悬念好奇", "身份认同", "反差对比", "价格锚点", "场景痛点"]


def _check_hook(plan: dict) -> tuple[int, list[QAIssue]]:
    """Check the opening hook (shots 1-2) are engaging."""
    issues = []
    storyboard = plan.get("script", {}).get("storyboard", [])
    if len(storyboard) < 2:
        return (0, issues)

    # Check shot 1 has hook characteristics
    shot1 = storyboard[0]
    l1_1 = shot1.get("audio_l1", "")
    l2_1 = shot1.get("audio_l2", "")

    total_checks = 3
    passed_checks = 0

    # Check hook uses at least one hook type pattern
    hook_patterns = {
        "身份认同": r"(小个子|脚宽|学生党|上班族|宝妈|通勤族|女生|男生)",
        "悬念好奇": r"(为什么|到底|到底有多|你看|你能|猜到|原来)",
        "场景痛点": r"(是不是|有没有|受够|每次|忍不了|怕|担心)",
        "反差对比": r"(左边|右边|以前|现在|普通|vs|对比|差距)",
        "价格锚点": r"(\d+[块元]|\d+[块钱元]|原价|券后|只要|才\d+)",
    }

    combined_hook = l1_1 + " " + l2_1
    found_hook_type = None
    for hook_type, pattern in hook_patterns.items():
        if re.search(pattern, combined_hook):
            found_hook_type = hook_type
            break

    if found_hook_type:
        passed_checks += 1
    else:
        issues.append(QAIssue(
            dimension="HOOK", severity="warning", field="storyboard[1]",
            message="第1镜开场没有钩子！缺少身份喊话/悬念/痛点/反差元素",
            fix_suggestion=f"加入钩子元素，如: {', '.join(HOOK_TYPES[:3])}等",
        ))

    # Check hook timing (visual should match hook intensity)
    visual1 = shot1.get("visual", "")
    if len(visual1) < 10:
        issues.append(QAIssue(
            dimension="HOOK", severity="warning", field="storyboard[1].visual",
            message="第1镜画面描述太短，钩子镜需要视觉冲击",
            fix_suggestion="描述具体视觉冲击效果，如'左右分屏对比'/'低角度仰拍冲击'",
        ))
    else:
        passed_checks += 1

    passed_checks += 1  # Basic structure check passed

    score = round(passed_checks / max(total_checks, 1) * 100)
    return (score, issues)


# ============ LLM-BASED DEEP CHECK ============

_DEEP_CHECK_PROMPT = """你是短视频内容质检专家。请审查以下{industry}产品拍摄方案的第{shot_num}镜脚本，从3个维度打分并给出修改建议。

话术内容:
L1（小白版）: {audio_l1}
L2（专业主播版）: {audio_l2}
画面: {visual}

## 评分维度（每项0-100分，60以下不合格）

1. **痛点击穿力**: 话术是否戳到目标客户的真实痛点？客户会不会觉得"这就是在说我"？
2. **口吻匹配度**: L1是否真像朋友推荐？L2是否有专业主播的控场力？两者区分度够吗？
3. **转化诱导力**: 听完这段话，客户会不会产生点击购物车的冲动？

## 输出JSON（无markdown）
{{"pain_hit": 分数, "tone_match": 分数, "conversion_power": 分数, "overall": 平均分, "verdict": "pass"或"fail", "red_flags": ["问题1", "问题2"], "rewrite_suggestion": "如果不合格，给一句改写建议"}}"""


def _llm_deep_check(plan: dict, industry: str) -> tuple[int, list[QAIssue]]:
    """Use LLM to do semantic quality check on key shots (1, 4, 7)."""
    client = _get_client()
    if not client:
        return (80, [])  # Skip LLM check if no client

    issues = []
    storyboard = plan.get("script", {}).get("storyboard", [])
    key_shots = [s for s in storyboard if s.get("shot") in [1, 4, 7]]
    if not key_shots:
        key_shots = storyboard[:3]

    scores = []
    for shot in key_shots:
        sn = shot.get("shot", "?")
        prompt = _DEEP_CHECK_PROMPT.format(
            industry=industry,
            shot_num=sn,
            audio_l1=shot.get("audio_l1", ""),
            audio_l2=shot.get("audio_l2", ""),
            visual=shot.get("visual", ""),
        )

        try:
            resp = client.chat.completions.create(
                model=Config.DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"},
                timeout=60,
            )
            text = resp.choices[0].message.content.strip()
            result = json.loads(text)
            scores.append(result.get("overall", 70))

            if result.get("verdict") == "fail":
                for flag in result.get("red_flags", []):
                    issues.append(QAIssue(
                        dimension="PERSPECTIVE", severity="warning",
                        field=f"storyboard[{sn}]",
                        message=f"第{sn}镜LLM质检: {flag}",
                        fix_suggestion=result.get("rewrite_suggestion", "需要人工审核"),
                    ))
        except Exception as e:
            logger.warning(f"LLM deep check failed for shot {sn}: {e}")
            scores.append(70)

    avg_score = round(sum(scores) / max(len(scores), 1))
    return (avg_score, issues)


# ============ MAIN REVIEW FUNCTION ============

DIMENSION_WEIGHTS = {
    "STRUCTURE": 0.25,
    "L1_SCRIPT": 0.15,
    "L2_SCRIPT": 0.15,
    "SCENE_TIER": 0.10,
    "PERSPECTIVE": 0.15,
    "COMPLIANCE": 0.10,
    "HOOK": 0.10,
}

DIMENSION_LABELS = {
    "STRUCTURE": "必填字段完整性",
    "L1_SCRIPT": "L1小白话术质量",
    "L2_SCRIPT": "L2专业主播话术质量",
    "SCENE_TIER": "场景分层合理性",
    "PERSPECTIVE": "客户视角规则",
    "COMPLIANCE": "合规检查",
    "HOOK": "开场钩子质量",
}


def review(plan: dict, industry: str = "鞋类", plan_index: int = 1, deep_check: bool = True) -> QAReport:
    """Run all 7 QA dimensions on a plan. Returns QAReport.

    Args:
        plan: The shooting plan dict from plan_service
        industry: Industry category for context
        plan_index: Which variant (1-based), for reporting
        deep_check: Whether to run LLM semantic check (slower but more thorough)
    """
    all_issues = []
    dimension_scores = {}

    checks = [
        ("STRUCTURE", _check_structure),
        ("L1_SCRIPT", _check_l1_scripts),
        ("L2_SCRIPT", _check_l2_scripts),
        ("SCENE_TIER", _check_scene_tier),
        ("PERSPECTIVE", _check_perspective),
        ("COMPLIANCE", _check_compliance),
        ("HOOK", _check_hook),
    ]

    for dim_name, check_func in checks:
        score, issues = check_func(plan)
        dimension_scores[dim_name] = score
        all_issues.extend(issues)

    # LLM deep check (optional, slower)
    if deep_check:
        llm_score, llm_issues = _llm_deep_check(plan, industry)
        dimension_scores["LLM_DEEP"] = llm_score
        all_issues.extend(llm_issues)

    # Calculate weighted total
    weighted_total = 0
    total_weight = 0
    for dim_name, weight in DIMENSION_WEIGHTS.items():
        if dim_name in dimension_scores:
            weighted_total += dimension_scores[dim_name] * weight
            total_weight += weight

    # Blend in LLM score if available
    if deep_check and "LLM_DEEP" in dimension_scores:
        # LLM score gets 10% weight blended into the total
        rule_score = weighted_total / max(total_weight, 0.01)
        llm_score = dimension_scores["LLM_DEEP"]
        final_score = round(rule_score * 0.85 + llm_score * 0.15)
    else:
        final_score = round(weighted_total / max(total_weight, 0.01))

    # Determine pass/fail
    errors = [i for i in all_issues if i.severity == "error"]
    pass_ = len(errors) == 0 and final_score >= 60

    # Build dimension labels
    dim_labels = {}
    for dim_name, score in dimension_scores.items():
        label = DIMENSION_LABELS.get(dim_name, dim_name)
        dim_labels[label] = score

    # Build summary
    error_count = len([i for i in all_issues if i.severity == "error"])
    warn_count = len([i for i in all_issues if i.severity == "warning"])
    sug_count = len([i for i in all_issues if i.severity == "suggestion"])

    if pass_:
        summary = f"✅ PASS | 评分: {final_score}/100 | "
        if warn_count:
            summary += f"{warn_count}个优化建议"
        else:
            summary += "所有维度合格"
    else:
        summary = f"❌ FAIL | 评分: {final_score}/100 | {error_count}个错误, {warn_count}个警告"

    return QAReport(
        plan_index=plan_index,
        pass_=pass_,
        score=final_score,
        dimensions=dim_labels,
        issues=all_issues,
        summary=summary,
    )


def review_all(plans: list[dict], industry: str = "鞋类", deep_check: bool = False) -> list[QAReport]:
    """Run QA on all plan variants. Returns list of QAReport sorted by score desc."""
    reports = []
    for i, plan in enumerate(plans):
        report = review(plan, industry, plan_index=i + 1, deep_check=deep_check)
        reports.append(report)
    reports.sort(key=lambda r: r.score, reverse=True)
    return reports


def format_report(report: QAReport, verbose: bool = False) -> str:
    """Format a QAReport as human-readable text."""
    lines = [
        f"{'='*50}",
        f"  方案{report.plan_index} 质检报告",
        f"  {report.summary}",
        f"{'='*50}",
        f"",
        f"各维度得分:",
    ]
    for dim, score in report.dimensions.items():
        bar = "█" * (score // 10) + "░" * (10 - score // 10)
        lines.append(f"  {dim:12s} [{bar}] {score}/100")

    lines.append("")

    if verbose and report.issues:
        lines.append(f"详细问题 ({len(report.issues)}个):")
        lines.append("-" * 50)
        for issue in report.issues:
            icon = {"error": "🔴", "warning": "🟡", "suggestion": "🔵"}.get(issue.severity, "⚪")
            lines.append(f"  {icon} [{issue.dimension}] {issue.field}")
            lines.append(f"     {issue.message}")
            lines.append(f"     → {issue.fix_suggestion}")
            lines.append("")

    return "\n".join(lines)
