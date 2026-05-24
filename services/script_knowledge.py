"""Script knowledge base — loaded from config/prompts/ YAML files.

Sources:
- Streamer-Sales (销冠) 3.7k stars: Live streaming sales LLM, customer psychology patterns
- MoneyPrinterTurbo 39.9k stars: Full video script generation pipeline
- OpenReels: BGM selection + script structure methodology
- VideoProduction: SEO optimization + BGM mixing rules
"""
import yaml
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "config" / "prompts"


def _load_yaml(filename: str) -> dict:
    with open(_PROMPTS_DIR / filename, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── bgm_knowledge.yaml ──
_bgm = _load_yaml("bgm_knowledge.yaml")
BGM_KNOWLEDGE = _bgm["bgm_knowledge"]
EMOTIONAL_ARC = _bgm["emotional_arc"]

# ── hook_blueprints.yaml ──
_hb = _load_yaml("hook_blueprints.yaml")
HOOK_BLUEPRINTS = _hb["hook_blueprints"]
SHOT_STRUCTURE = _hb["shot_structure"]
TITLE_FORMULAS = _hb["title_formulas"]
CUSTOMER_QUESTION_TYPES = _hb["customer_question_types"]
FABE_FRAMEWORK = _hb["fabe_framework"]
ANCHOR_PERSONAS = _hb["anchor_personas"]
EDITING_KNOWLEDGE = _hb["editing_knowledge"]
LIVE_STREAM_PATTERNS = _hb["live_stream_patterns"]
CUSTOMER_PERSPECTIVE_RULES = _hb["customer_perspective_rules"]
PAIN_POINTS_BY_INDUSTRY = _hb["pain_points_by_industry"]

# ── script_tiers.yaml ──
_st = _load_yaml("script_tiers.yaml")
SHOOTING_TIERS = _st["shooting_tiers"]
SCRIPT_TIERS = _st["script_tiers"]
SHOOTING_PITFALLS = _st["shooting_pitfalls"]
SHOOTING_TEMPLATE_CARD = _st["shooting_template_card"]
SCENE_REPLACEMENTS = _st["scene_replacements"]
