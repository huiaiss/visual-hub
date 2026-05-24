"""Script data models — FrameCraft's own Beat/Script dataclasses.

Previously imported from auto-video-platform's generators.script_engine.
Now self-contained so FrameCraft has zero code dependency on AVP.
"""

from dataclasses import dataclass, field


@dataclass
class Beat:
    """一个Beat = 一句口播 + 一个画面动作。"""
    index: int
    text: str                       # 口播文案
    visual: str                     # 画面描述（供素材匹配用）
    animation: str                  # zoom/fade/slide/pop/pulse/none
    emotion: str                    # hook/curiosity/surprise/trust/desire/action
    duration_s: float
    is_save_trigger: bool = False   # 收藏诱因点
    is_share_trigger: bool = False  # 转发诱因点
    is_comment_trigger: bool = False  # 评论引爆点
    caption: str = ""               # 字幕文本
    how_to_shoot: str = ""          # 拍摄建议
    tier: str = "L1"                # L1(手机)/L2(专业)/L3(影棚)
    audio_l2_text: str = ""         # B-roll 备用口播


@dataclass
class Script:
    """完整Beat级生产脚本."""
    title: str
    hook_type: str                  # 悬念型/反常识型/恐惧型/好奇心型/身份认同型
    beats: list[Beat]
    outro: Beat
    tags: list[str]                 # 话题标签
    bgm_style: str                  # BGM风格
    checklist: str                  # 截图保存的检查清单（收藏诱因）
    total_duration_s: float
    bgm_search_keywords: list[str] = field(default_factory=list)
    bgm_tempo_bpm: str = ""
    bgm_usage_tips: str = ""
    composition_style: str = ""
    model_direction: str = ""
    differentiation: str = ""
    key_features: list[str] = field(default_factory=list)
    top_hook_types: list[str] = field(default_factory=list)
