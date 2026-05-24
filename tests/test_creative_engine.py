"""Test creative_engine — product analysis returns valid structures."""

from services.creative_engine import build_creative_context


def test_build_creative_context_returns_string():
    """build_creative_context returns a prompt string with key info."""
    product_analysis = {
        "category": "老爹鞋",
        "style_keywords": ["复古", "厚底"],
        "materials": ["网面", "皮革"],
        "colors": [{"name": "米白"}, {"name": "灰蓝"}],
        "target_audience": {"gender": "女", "age_range": "18-28", "scenarios": ["日常通勤"]},
        "key_features": ["厚底增高", "透气"],
        "texture_notes": "网面透气",
        "design_highlights": "撞色拼接",
    }
    creative_brief = {
        "concept_name": "城市漫游者",
        "mood_keywords": ["复古", "街头"],
        "scenes": [{"scene_name": "旧城区斑马线", "description": "灰砖墙背景"}],
        "color_palette": {"primary": "#FF6B35"},
        "model_direction": {"look": "宽松牛仔裤+卫衣", "pose_style": "自然行走"},
        "composition_style": "低角度仰拍",
        "differentiation": "厚底增高6cm",
        "bgm_suggestion": {"genre": "轻快", "bpm_range": "85-95", "mood": "活力"},
        "top_hook_types": ["身份认同型", "痛点共鸣型"],
    }

    context = build_creative_context(product_analysis, creative_brief)

    assert isinstance(context, str)
    assert len(context) > 50
    assert "老爹鞋" in context
    assert "城市漫游者" in context


def test_build_creative_context_empty_inputs():
    """build_creative_context should not crash with empty dicts."""
    context = build_creative_context({}, {})
    assert isinstance(context, str)
    assert len(context) > 0
