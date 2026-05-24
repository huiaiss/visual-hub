"""Prompt building and category configurations for FrameCraft shooting plan generation.

Knowledge injection from script_knowledge.py (GitHub-sourced best practices):
- Streamer-Sales (3.7k stars): live streaming personas, compliance, customer psychology
- MoneyPrinterTurbo (39.9k stars): hook frameworks, shot structure, title formulas
- OpenReels + VideoProduction: BGM mixing, editing transitions, color grading

Shooting tier system: L1=手机随手拍 L2=手机+简单道具 L3=专业团队
"""
import time
import json

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

# ============ CATEGORY CONFIGS ============
CATEGORY_CONFIGS = {
    "鞋类": {
        "vision_dims": """1. 品类：具体鞋型（老爹鞋/运动鞋/帆布鞋/乐福鞋/高跟鞋/凉鞋/拖鞋/靴子/童鞋/商务皮鞋等）及性别（男/女/童/中性）
2. 鞋底：厚底/松糕底/平底/橡胶底/牛筋底？厚度多少cm？（目测）
3. 鞋面：材质（PU/真皮/帆布/网面/绒面/飞织/超纤等）、鞋头形状（圆头/方头/尖头/露趾）
4. 颜色：列举所有颜色，多色产品逐个列出
5. 风格：整体风格关键词（运动/通勤/休闲/街头/甜美/商务/户外等）
6. 适合人群：性别+年龄段+穿搭场景""",
        "hook_types": ["视觉冲击", "反差对比", "身份认同", "价格锚点", "场景痛点"],
        "bgm_with_cart": "快节奏卡点/电子鼓点/变装BGM，120-130BPM",
        "bgm_without_cart": "轻快吉他/钢琴/氛围感，80-90BPM",
        "typical_scenes": ["街头/斑马线", "咖啡厅/商场", "运动场/户外", "对镜自拍/衣帽间", "居家/窗台"],
        "required_angles": [
        {"slot": 1, "name": "正面平拍", "desc": "产品正面完整展示，鞋头/鞋面/闭合方式清晰", "required": True},
        {"slot": 2, "name": "鞋底特写", "desc": "鞋底纹路/厚度/品牌标识清晰可见", "required": True},
        {"slot": 3, "name": "侧面", "desc": "展示鞋底厚度/跟高/鞋型弧线", "required": True},
        {"slot": 4, "name": "细节特写", "desc": "材质纹理/缝线/装饰/logo近拍", "required": False},
        {"slot": 5, "name": "上脚效果", "desc": "真人穿着展示比例和搭配效果", "required": False},
    ],
    },
    "服装": {
        "vision_dims": """1. 品类：具体单品类型（连衣裙/T恤/衬衫/裤装/外套/套装等）及版型（修身/宽松/oversize）
2. 面料：材质（棉/麻/丝/雪纺/针织/牛仔/西装料等）、厚薄、垂感
3. 颜色/图案：主色+辅色，是否有印花/条纹/格纹/纯色
4. 领型/袖型/长度：具体款式细节
5. 风格：整体风格关键词（通勤/休闲/街头/法式/新中式/辣妹/甜美等）
6. 适合人群：年龄段+身材类型+穿搭场景""",
        "hook_types": ["视觉冲击", "反差对比", "身份认同", "身材痛点", "场景痛点", "价格锚点"],
        "bgm_with_cart": "快节奏卡点/变装BGM/强鼓点，120-135BPM",
        "bgm_without_cart": "轻快流行/法式慵懒/氛围钢琴，75-90BPM",
        "typical_scenes": ["街拍/咖啡厅", "对镜自拍/试衣间", "户外/公园", "商场/买手店", "居家/卧室"],
        "required_angles": [
        {"slot": 1, "name": "正面平铺", "desc": "服装正面完整平铺或挂拍，展示整体版型", "required": True},
        {"slot": 2, "name": "背面平铺", "desc": "服装背面完整展示，领标/洗标可见", "required": True},
        {"slot": 3, "name": "侧面版型", "desc": "侧面展示廓形/下摆/袖型弧线", "required": True},
        {"slot": 4, "name": "细节特写", "desc": "领口/袖口/纽扣/面料纹理近拍", "required": False},
        {"slot": 5, "name": "上身效果", "desc": "真人穿着展示比例和搭配", "required": False},
    ],
    },
    "美妆": {
        "vision_dims": """1. 品类：口红/眼影/粉底/腮红/眉笔/护肤品等
2. 包装：外观设计、便携性、质感
3. 质地：哑光/滋润/水光/雾面/闪粉
4. 色号：具体颜色+适用肤色
5. 适用人群：年龄段+肤质+妆容风格""",
        "hook_types": ["视觉冲击", "反差对比", "成分党", "妆效展示", "痛点解决"],
        "bgm_with_cart": "轻快电子/时尚节拍，110-125BPM",
        "bgm_without_cart": "舒缓氛围/纯净钢琴，70-85BPM",
        "required_angles": [
        {"slot": 1, "name": "产品正面", "desc": "产品正面完整展示，品牌/品名/外观清晰", "required": True},
        {"slot": 2, "name": "背面成分", "desc": "背面标签/成分表/备案号清晰可见", "required": True},
        {"slot": 3, "name": "质地/颜色", "desc": "展示质地（膏体/粉质/液体）和真实颜色", "required": True},
        {"slot": 4, "name": "使用效果", "desc": "手臂试色或上脸效果对比展示", "required": False},
        {"slot": 5, "name": "包装盒/赠品", "desc": "完整包装/配件/赠品展示", "required": False},
    ],
    },
    "食品": {
        "vision_dims": """1. 品类：零食/饮品/速食/调味品/生鲜等
2. 包装：袋装/罐装/盒装、设计风格
3. 卖点：口味/配料/产地/工艺
4. 规格：净含量、份量
5. 适合场景：追剧/办公/聚会/送礼/健身""",
        "hook_types": ["食欲刺激", "价格锚点", "场景痛点", "健康焦虑", "好奇心"],
        "bgm_with_cart": "快节奏/食欲感BGM/ASMR，100-120BPM",
        "bgm_without_cart": "温馨/治愈/生活感，70-85BPM",
        "required_angles": [
        {"slot": 1, "name": "包装正面", "desc": "产品正面完整展示，品牌/品名/外观清晰", "required": True},
        {"slot": 2, "name": "配料表/背面", "desc": "配料表/营养成分表/生产信息清晰", "required": True},
        {"slot": 3, "name": "内容物实拍", "desc": "打开包装展示真实内容物状态", "required": True},
        {"slot": 4, "name": "食用场景", "desc": "展示食用/使用场景（摆盘/冲泡/试吃）", "required": False},
        {"slot": 5, "name": "保质期/规格", "desc": "保质期标签/净含量/规格对比", "required": False},
    ],
    },
    "3C数码": {
        "vision_dims": """1. 品类：手机配件/耳机/充电器/智能穿戴/电脑周边等
2. 外观：颜色/材质/尺寸/工业设计
3. 核心功能：主要卖点和技术参数
4. 接口/兼容性：适用设备
5. 适用人群：游戏/办公/学生/通勤""",
        "hook_types": ["功能震撼", "价格锚点", "痛点解决", "对比测评", "科技感"],
        "bgm_with_cart": "科技感电子/快节奏，110-130BPM",
        "bgm_without_cart": "极简电子/氛围科技，75-90BPM",
        "required_angles": [
        {"slot": 1, "name": "产品正面", "desc": "产品正面完整展示，品牌/型号/外观清晰", "required": True},
        {"slot": 2, "name": "背面/接口", "desc": "背面接口/参数标签/认证标识清晰", "required": True},
        {"slot": 3, "name": "侧面厚度", "desc": "侧面展示产品厚度/比例/工业设计", "required": True},
        {"slot": 4, "name": "接口/细节", "desc": "接口/按键/镜头/屏幕细节近拍", "required": False},
        {"slot": 5, "name": "配件全家福", "desc": "所有配件/包装/说明书完整展示", "required": False},
    ],
    },
    "家居": {
        "vision_dims": """1. 品类：收纳/装饰/清洁/家纺/厨具等
2. 材质：木质/塑料/金属/布艺/陶瓷
3. 尺寸/颜色/风格
4. 使用场景：客厅/卧室/厨房/卫生间
5. 目标人群：租房党/新家装修/宝妈/收纳控""",
        "hook_types": ["场景痛点", "视觉冲击", "价格锚点", "收纳魔法", "对比展示"],
        "bgm_with_cart": "轻快活泼/家居感，95-110BPM",
        "bgm_without_cart": "温暖治愈/慢生活，65-80BPM",
        "required_angles": [
        {"slot": 1, "name": "产品正面", "desc": "产品正面完整展示，款式/颜色/设计清晰", "required": True},
        {"slot": 2, "name": "背面/底部", "desc": "背面或底部结构/支撑方式/标签", "required": True},
        {"slot": 3, "name": "侧面整体", "desc": "侧面展示比例/尺寸/厚度/轮廓", "required": True},
        {"slot": 4, "name": "材质细节", "desc": "材质纹理/接缝/做工/logo近拍", "required": False},
        {"slot": 5, "name": "场景/参照", "desc": "实际使用场景或尺寸参照物对比", "required": False},
    ],
    },
}

DEFAULT_CATEGORY_CONFIG = {
    "vision_dims": """1. 品类：具体产品类型
2. 外观特征：颜色/材质/尺寸/设计
3. 核心卖点：主要功能和差异化特点
4. 目标人群：年龄段+使用场景
5. 风格：整体视觉风格关键词""",
    "hook_types": ["视觉冲击", "价格锚点", "痛点解决", "身份认同", "反差对比"],
    "bgm_with_cart": "快节奏/强节奏感，110-130BPM",
    "bgm_without_cart": "轻松氛围/自然感，75-90BPM",
}

SCRIPT_TYPES = {
    "with_cart": {
        "label": "挂车版",
        "goal": "转化率优先，卖点密集，价格锚点+紧迫感，强引导购物车",
        "default_bpm": "120-130",
        "default_voice": "剪映AI语音-解说男声，语速快有说服力",
    },
    "without_cart": {
        "label": "不挂车版",
        "goal": "完播率优先，强视觉冲击，隐藏式种草，引导关注",
        "default_bpm": "80-90",
        "default_voice": "剪映AI语音-情感女声，温柔舒缓",
    },
}

VARIATION_INSTRUCTIONS = {
    1: {
        "type": "反差对比",
        "instruction": "使用「反差对比」型钩子——用对比制造视觉冲击",
        "text_examples": ["左边：你的旧XX 右边：我的新XX", "穿前155 vs 穿后165", "普通款vs这款，差距也太大了吧"],
        "visual": "左右分屏/上下分屏，同一人物同一角度，只换产品",
    },
    2: {
        "type": "身份认同",
        "instruction": "使用「身份认同」或「场景痛点」型钩子——直接喊出目标人群的痛点",
        "text_examples": ["小个子女生必看！这双鞋自带增高Buff", "脚宽星人集合！终于找到不挤脚的鞋了", "学生党福音，百元出头穿出千元质感"],
        "visual": "人物出镜+产品特写交替，建立身份关联",
    },
    3: {
        "type": "价格锚点",
        "instruction": "使用「价格锚点」或「反常识」型钩子——强调性价比或打破认知",
        "text_examples": ["商场同款399，今天直接169", "不是贵的买不起，而是这款更有性价比", "工厂直发，省掉中间商差价"],
        "visual": "价格对比字幕+产品细节轮播+限时优惠倒计时",
    },
    4: {
        "type": "视觉冲击",
        "instruction": "使用「视觉冲击」型钩子——纯靠画面吸引，前3秒强视觉刺激",
        "text_examples": ["慢动作+特写+光影变化", "BGM卡点+画面快速切换", "变速+特写+色彩冲击"],
        "visual": "慢动作/特写/光影/快速卡点切换",
    },
    5: {
        "type": "悬念好奇",
        "instruction": "使用「悬念好奇」型钩子——前3秒抛出问题或悬念，揭晓式展开",
        "text_examples": ["这双鞋到底有多软？看完你就知道了", "为什么这双鞋卖了10万双？3个原因", "拆开给你看，里面长这样"],
        "visual": "前2秒特写遮挡/模糊→第3秒揭晓，配合音效卡点",
    },
}


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


def build_vision_prompt(industry: str, image_count: int, vision_dims: str) -> list[dict]:
    """Build the vision analysis prompt content array."""
    if image_count == 1:
        return [
            {"type": "image_url", "image_url": {"url": "{data_url}"}},
            {"type": "text", "text": f"你是{industry}产品鉴定专家。请仔细观察图片，按以下维度精准描述（80-120字）：\n\n{vision_dims}\n\n用简洁中文，严格基于图片内容，不要编造不存在的特征。注意：图片可能是纯背景的产品白底图，请根据实际可见内容描述。"},
        ]
    else:
        return [{"type": "text", "text": f"你是{industry}产品鉴定专家。以下是同一产品的{image_count}张多角度实拍图，请综合分析所有图片，按以下维度精准描述（100-150字）：\n\n{vision_dims}\n\n用简洁中文，综合所有图片信息，严格基于图片内容，不要编造不存在的特征。"}]


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

    return f"""你是素人手机拍摄教练——帮普通人用一部手机拍出能卖货的好视频。

核心原则：方案生成后任何人拿到就能拍，不需要摄影基础，不需要专业设备，不需要请模特。默认L1极简方案（手机+自然光），L2作为进阶选项。

全局随机种子：{variation_seed}　|　方案编号：{variant_index}/{total_variants}
脚本类型：{st_label}（{st_goal}）
{var_note}
{ref_block}
产品创意分析（含产品画像+创意大纲）：
{product_desc}

用户补充信息：
{extra_info or "无额外信息，请基于视觉分析发挥"}

{knowledge}

核心要求（每条都必须遵守，违反的JSON会被拒绝）：
1. 默认产出L1极简方案。场景优先选「窗边白墙/小区路面/对镜自拍/办公桌旁」等素人5分钟内能到达的场地。如果创意需要的场景偏专业（如咖啡厅/街拍），必须同时给出L1平替方案
2. 【MANDATORY】每个 storyboard 镜号必须包含 "how_to_shoot" 字段——用手机拍法描述（如"手机倒扣放地上，镜头朝上拍鞋底"），禁止写专业术语。同时必须包含 "tier" 字段标注 L1 或 L2
3. 【MANDATORY】顶层必须包含 "shooting_tier" 字段（"L1" 或 "L2"）和 "shooting_template_card" 对象（6个字段：tier_label, equipment_needed, best_scene, time_needed, pitfall_alert, editing_recipe, bgm_pick）
4. 【MANDATORY·话术分层】每个 storyboard 镜号必须包含 "audio_l1"（小白版）和 "audio_l2"（专业主播版）两个版本的口播文案，各≥30字。L1像朋友聊天推荐，L2像专业带货主播。两者都必须站在客户角度想问题——先讲痛点再给解法，不能上来就夸产品
5. 【话术核心铁律】站在客户的角度想问题！每句话先问自己：客户听了会觉得"这说的就是我"吗？禁止写"这款鞋有5cm厚底"这种产品视角文案，必须写成"你是不是也受够了平底鞋显矮？"这种客户视角文案
6. 真人展示优先「不露脸局部拍」——只拍脚和腿，任何人都能出镜，不需要模特
7. 标题套用标题公式，3个标题分属不同公式类型
8. 四平台发布策略各自独立，调色参数按上述四平台值
9. BGM必须标注具体BPM范围和搜索关键词
10. 直播话术生成微憋单+平播两套，融入主播人设开场/收尾句式，所有话术经过合规替换词典检查
11. 付费投流策略（四平台独立，标注推荐/可选）
12. 全方案100%合规：绝对不出现「最/第一/全网最低/100%/最后3分钟/马上涨价/保证/肯定/不买就亏」，违者用合规词典替换。话术中标注🚨红线

⚠️ CRITICAL: 以下字段绝对不能省略 —— shooting_tier, shooting_template_card, storyboard[].how_to_shoot, storyboard[].tier, storyboard[].audio_l1, storyboard[].audio_l2

请严格输出JSON（不要markdown代码块）：
{{
  "product_summary": "产品一句话（15字内）",
  "shooting_tier": "L1 或 L2（必填！不要省略）",
  "shooting_template_card": {{
    "tier_label": "📱 手机随手出片 或 📱+💡 手机+简单道具（必填）",
    "equipment_needed": "具体需要什么设备（必填）",
    "best_scene": "具体去哪里拍（必填）",
    "time_needed": "拍摄+剪辑总时长（必填）",
    "pitfall_alert": "最容易踩的坑（必填）",
    "editing_recipe": "剪映3步操作（必填）",
    "bgm_pick": "推荐BGM+搜索关键词（必填）"
  }},
  "titles": [
    {{"text": "标题1", "type": "痛点型", "scenario": "{st_label}适用"}},
    {{"text": "标题2", "type": "反常识型", "scenario": "{st_label}适用"}},
    {{"text": "标题3", "type": "身份快照型", "scenario": "{st_label}适用"}}
  ],
  "hook": {{
    "description": "前3秒钩子核心思路",
    "visual": "具体画面描述（素人可实现的）",
    "text": "叠加文字内容",
    "type": "钩子类型（视觉冲击/悬念好奇/身份认同/反差对比/价格锚点/场景痛点）"
  }},
  "script": {{
    "goal": "{st_goal}",
    "storyboard": [
      {{"shot": 1, "duration": "0-3s", "tier": "L1或L2（必填！）", "visual": "画面描述", "audio_l1": "【小白版·必填】朋友推荐口吻，≥30字。先讲痛点再给解法，用日常聊天语言。例：'你是不是也受够了...？'", "audio_l2": "【专业主播版·必填】带货主播口吻，≥30字。痛点放大+FABE+行动推动。例：'停！所有XX的姐妹听好了...'", "caption": "字幕", "how_to_shoot": "手机怎么摆/光线在哪/注意什么（必填！禁止写焦段光圈等专业术语）"}}
    ]
  }},
  "bgm": {{
    "style": "BGM风格",
    "recommendations": ["具体曲目1", "具体曲目2", "具体曲目3"],
    "search_keywords": ["搜索关键词1", "搜索关键词2"],
    "how_to_find_trending": "在抖音/小红书找当下爆款BGM的具体方法",
    "tempo_bpm": "推荐BPM范围",
    "usage_tips": "卡点技巧/音量比例"
  }},
  "post_production": {{
    "editing": {{
      "pace": "剪辑节奏",
      "transitions": "转场建议",
      "effects": "特效建议",
      "key_moments": "关键节奏点"
    }},
    "color_grading": {{
      "style": "调色风格",
      "filter_lut": "推荐剪映滤镜名称（不要达芬奇/专业调色软件）",
      "parameters": "亮度/对比度/饱和度/色温参数"
    }},
    "captions": {{
      "font": "剪映可用的字体",
      "size_position": "字号和位置",
      "animation": "动画效果",
      "color_palette": "配色方案",
      "highlight_rules": "重点标注规则"
    }},
    "sound_design": {{
      "sfx": "音效建议",
      "audio_mixing": "人声/BGM/音效分贝比例"
    }}
  }},
  "voiceover": {{
    "method": "推荐AI语音工具（必须是剪映/度加等免费工具）",
    "recommended_voice": "具体AI音色名称",
    "speed": "语速建议",
    "how_to_clone": "剪映操作步骤：打开剪映→文本→朗读→选音色→调语速→导出",
    "tips": "AI语音使用技巧"
  }},
  "platforms": {{
    "douyin": {{
      "video": {{"adaptation": "抖音版本调整", "aspect_ratio": "9:16", "duration": "建议时长（秒）", "cart_hook": "购物车引导话术", "coupon_strategy": "优惠券策略"}},
      "publish_strategy": {{"best_times": ["时段1", "时段2"], "best_days": ["周X"], "frequency": "发布频率", "first_comment": "首发自评", "interaction_guide": "评论区互动策略", "hashtag_tips": "标签技巧"}}
    }},
    "kuaishou": {{
      "video": {{"adaptation": "快手版本调整（老铁文化）", "aspect_ratio": "9:16", "duration": "建议时长", "cart_hook": "小黄车话术", "coupon_strategy": "快手券策略"}},
      "publish_strategy": {{"best_times": ["时段1", "时段2"], "best_days": ["周X"], "frequency": "发布频率", "first_comment": "首发自评", "interaction_guide": "互动策略", "hashtag_tips": "标签技巧"}}
    }},
    "xiaohongshu": {{
      "video": {{"adaptation": "小红书视频调整", "aspect_ratio": "3:4或9:16", "duration": "建议时长"}},
      "image_post": {{"cover_design": "封面设计（配色/标题/字体）", "image_sequence": ["图1内容", "图2内容", "图3内容", "图4内容", "图5内容"], "title": "图文笔记标题", "copywriting": "正文文案（开头痛点+中间卖点+结尾CTA）", "hashtag_strategy": "标签策略", "publish_note": "发布注意事项"}},
      "publish_strategy": {{"best_times": ["时段1", "时段2"], "best_days": ["周X"], "frequency": "发布频率", "first_comment": "首条评论", "interaction_guide": "互动策略", "seo_tips": "SEO关键词技巧"}}
    }},
    "shipinhao": {{
      "video": {{"adaptation": "视频号版本调整", "aspect_ratio": "9:16或1:1", "duration": "建议时长", "social_sharing_hook": "朋友圈转发引导语", "private_domain_guide": "私域导流策略"}},
      "publish_strategy": {{"best_times": ["时段1", "时段2"], "best_days": ["周X"], "frequency": "发布频率", "first_comment": "首条评论", "interaction_guide": "互动+裂变", "fission_guide": "扩散方法"}}
    }}
  }},
  "tags": {{
    "core": ["#核心词1", "#核心词2"],
    "trending": ["#热搜词1", "#热搜词2", "#热搜词3", "#热搜词4"],
    "long_tail": ["#长尾词1", "#长尾词2", "#长尾词3"]
  }},
  "comments": [
    "引导转化评论1",
    "增加互动评论2",
    "触发讨论评论3",
    "隐藏种草评论4"
  ],
  "creative_direction": {{
    "season_hook": "当前季节热点",
    "holiday_tie_in": "近期节日切入点"
  }},
  "live_stream": {{
    "wei_bie_dan": {{
      "suitable": "在线50人+、主推爆款时使用",
      "host_position": "真人全身出镜或坐播",
      "cycle": "5分钟循环（转速品情必）",
      "segments": [
        {{"phase": "转·留人", "duration": "0-30s", "script": "开场口播（融入主播人设开场句式）", "tips": "点关注+扣1互动"}},
        {{"phase": "速·种草", "duration": "30-75s", "script": "痛点场景+产品解法口播", "tips": "场景化描述"}},
        {{"phase": "品·FABE讲解", "duration": "75-180s", "script": "特性→优势→利益→证据完整讲解口播", "tips": "试穿+细节展示"}},
        {{"phase": "情·信任连接", "duration": "180-240s", "script": "使用体验+运费险+复购佐证口播（合规替换词典检查）", "tips": "真实体验替代浮夸承诺"}},
        {{"phase": "必·合规收单", "duration": "240-300s", "script": "合规软逼单口播（5法选2）", "tips": "🚨禁用绝对化用语/虚假限时"}}
      ],
      "compliance_alerts": ["🚨不虚假限时", "🚨不绝对化", "🚨不功效承诺"]
    }},
    "ping_bo": {{
      "suitable": "日常直播、低流量时段",
      "host_position": "坐播或不出镜",
      "cycle": "8分钟循环（开场→痛点→FABE→搭配→答疑→收单）",
      "segments": [
        {{"phase": "开场承接", "duration": "0-60s", "script": "欢迎+主题说明口播（平播关键短语）", "tips": "告知今天把每款讲透"}},
        {{"phase": "痛点共鸣", "duration": "60-120s", "script": "穿搭痛点+提问互动口播", "tips": "引导评论"}},
        {{"phase": "FABE专业讲解", "duration": "120-300s", "script": "完整FABE+试穿+细节口播", "tips": "逐一说明"}},
        {{"phase": "搭配建议", "duration": "300-390s", "script": "3套场景搭配方案口播", "tips": "增加连带率"}},
        {{"phase": "互动答疑", "duration": "390-450s", "script": "回复评论+引导详情页口播", "tips": "信任机会"}},
        {{"phase": "自然收单", "duration": "450-480s", "script": "轻声提醒+售后保障口播（合规替换词典）", "tips": "退换货兜底消除顾虑"}}
      ],
      "compliance_alerts": ["🚨平播也禁绝对化用语", "🚨不虚假承诺"]
    }}
  }},
  "paid_promotion": {{
    "douyin": {{"tool": "巨量千川·乘方", "recommendation_level": "推荐", "cold_start": {{"budget": "单计划100-300元/天", "targeting": "莱卡行为兴趣+达人相似", "bidding": "放量投放+系统出价上浮10%", "material_count": "20条+素材"}}, "scaling": {{"roi_model": "净成交ROI", "budget_scale": "消耗达80%且ROI达标→追加15-20%", "roi_adjust": "连续3天消耗递增→ROI×1.05微调", "material_update": "3天更新素材"}}, "roi_tips": "阶梯出价+赔付对冲", "budget_advice": "日预算≥客单价×20，新手100元/天起测", "compliance": ["🚨不碰功效承诺", "🚨不虚假限时限量"]}},
    "kuaishou": {{"tool": "磁力金牛", "recommendation_level": "推荐", "cold_start": {{"budget": "100-200元/天", "targeting": "全站推广", "bidding": "Nobid智能出价", "material_count": "20-30条素材"}}, "scaling": {{"roi_model": "净成交ROI", "budget_scale": "度过冷启动→预算日增30%", "roi_adjust": "模型稳定后微调", "material_update": "货直双投"}}, "roi_tips": "全店托管+AI选品", "budget_advice": "首次充值1000元起", "compliance": ["🚨快手接地气但不低俗", "🚨禁用诱导话术"]}},
    "xiaohongshu": {{"tool": "薯条+聚光", "recommendation_level": "推荐", "cold_start": {{"budget": "薯条75-150元/6h", "targeting": "智能推荐→自定义AB测试", "bidding": "CPM/CPC/CPE", "material_count": "3-5篇笔记"}}, "scaling": {{"roi_model": "薯条测点击率→聚光放量", "budget_scale": "爆款→聚光500-2000元/天", "roi_adjust": "优化封面+标题+钩子", "material_update": "蒲公英平台报备"}}, "roi_tips": "内容为王，薯条测款→聚光放量→店铺闭环", "budget_advice": "新手从薯条75元起测", "compliance": ["🚨严禁站外导流", "🚨商业合作必须蒲公英报备"]}},
    "shipinhao": {{"tool": "ADQ+微信豆", "recommendation_level": "推荐", "cold_start": {{"budget": "ADQ 100-300元/天", "targeting": "地域+年龄+兴趣", "bidding": "oCPM/oCPA", "material_count": "5-10条素材"}}, "scaling": {{"roi_model": "oCPM/oCPA并行", "budget_scale": "多版位放量", "roi_adjust": "2-4周稳定期后调整", "material_update": "直播切片自动生成+私域反哺"}}, "roi_tips": "私域反哺公域：朋友圈/社群→自然流量→付费加成", "budget_advice": "日预算200-500元", "compliance": ["🚨AI内容必须标注", "🚨严禁价格误导"]}}
  }}
}}"""
