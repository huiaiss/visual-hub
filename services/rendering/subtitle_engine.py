"""Subtitle Engine — kinetic typography for HyperFrames compositions.

Generates word-by-word and character-by-character pop animations synced
to audio timing. Supports keyword highlighting (red pulse for AI-flaw terms).

Output: GSAP animation code + HTML spans, injected into the assembled HTML.

Usage:
    from services.rendering.subtitle_engine import SubtitleEngine
    engine = SubtitleEngine()
    html, gsap = engine.build(subtitle_lines, style="word_pop")
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data types (self-contained, no external deps)
# ---------------------------------------------------------------------------

@dataclass
class SubtitleLine:
    """A line of subtitle text with optional animation hints."""
    text: str                    # full line text
    start: float                 # absolute start time
    end: float                   # absolute end time
    mode: str = "fade"           # "fade" | "word_pop" | "char_pop"
    keywords: list[str] = field(default_factory=list)   # words to highlight


# ---------------------------------------------------------------------------
# Style presets
# ---------------------------------------------------------------------------

@dataclass
class SubtitleStyle:
    """Visual + animation parameters for a subtitle style."""
    font_size: str = "38px"
    font_weight: str = "700"
    color: str = "#ffffff"
    highlight_color: str = "#ff1744"
    outline: str = "0 2px 12px rgba(0,0,0,0.8)"
    position: str = "bottom"       # "bottom" | "center" | "top"
    bottom_offset: str = "160px"
    align: str = "center"
    max_width: str = "920px"

    # Animation
    in_anim: str = "fade_up"       # "fade_up" | "scale_pop" | "char_pop" | "none"
    out_anim: str = "fade_down"
    easing: str = "power3.out"
    stagger: float = 0.04          # per-word stagger delay
    scale_peak: float = 1.08       # for scale_pop


# Pre-built styles
STYLE_PRESETS: dict[str, SubtitleStyle] = {
    "default": SubtitleStyle(),
    "word_pop": SubtitleStyle(
        font_size="40px",
        font_weight="800",
        in_anim="scale_pop",
        stagger=0.05,
    ),
    "char_pop": SubtitleStyle(
        font_size="42px",
        font_weight="900",
        in_anim="char_pop",
        stagger=0.03,
    ),
    "minimal": SubtitleStyle(
        font_size="34px",
        font_weight="600",
        in_anim="fade_up",
        stagger=0.02,
        bottom_offset="120px",
    ),
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SubtitleEngine:
    """Generate kinetic typography HTML + GSAP from SubtitleLine list."""

    def __init__(self, style: str = "default", custom_style: Optional[SubtitleStyle] = None):
        self.preset = STYLE_PRESETS.get(style, STYLE_PRESETS["default"])
        if custom_style:
            self.preset = custom_style

    # ─── Public API ──────────────────────────────────────────

    def build(self, lines: list[SubtitleLine]) -> tuple[str, str]:
        """Generate (HTML, GSAP) for a list of subtitle lines."""
        html_parts = []
        gsap_parts = []

        for i, line in enumerate(lines):
            container_id = f"sub{i}"
            html_parts.append(self._line_html(container_id, line))
            gsap_parts.append(self._line_gsap(container_id, line))

        return "\n".join(html_parts), "\n".join(gsap_parts)

    def build_overlay_css(self) -> str:
        """Return CSS for the subtitle container + spans."""
        s = self.preset
        position_css = ""
        if s.position == "bottom":
            position_css = f"bottom: {s.bottom_offset};"
        elif s.position == "center":
            position_css = "top: 50%; transform: translateY(-50%);"
        elif s.position == "top":
            position_css = "top: 100px;"

        return f"""
    .sub-container {{
      position: absolute; left: 50%; transform: translateX(-50%);
      {position_css}
      width: {s.max_width}; text-align: {s.align};
      z-index: 20; pointer-events: none;
    }}
    .sub-word {{
      display: inline-block; font-size: {s.font_size};
      font-weight: {s.font_weight}; color: {s.color};
      text-shadow: {s.outline};
      margin: 0 0.12em;
    }}
    .sub-word-kw {{
      display: inline-block; font-size: {s.font_size};
      font-weight: 900; color: {s.highlight_color};
      text-shadow: 0 0 30px {s.highlight_color}88, {s.outline};
      margin: 0 0.12em;
    }}
    .sub-char {{
      display: inline-block; font-size: {s.font_size};
      font-weight: {s.font_weight}; color: {s.color};
      text-shadow: {s.outline};
    }}
    .sub-char-kw {{
      display: inline-block; font-size: {s.font_size};
      font-weight: 900; color: {s.highlight_color};
      text-shadow: 0 0 30px {s.highlight_color}88, {s.outline};
    }}
"""

    # ─── Internal ────────────────────────────────────────────

    def _line_html(self, container_id: str, line: SubtitleLine) -> str:
        """Build HTML for one subtitle line."""
        keywords = set(line.keywords)
        mode = line.mode

        if mode == "char_pop":
            spans = self._char_spans(line.text, keywords)
        else:
            spans = self._word_spans(line.text, keywords)

        # Build inner HTML from spans
        inner = "".join(spans)

        return f'  <div class="sub-container" id="{container_id}">{inner}</div>'

    def _word_spans(self, text: str, keywords: set[str]) -> list[str]:
        """Split text into word-level spans, highlighting keywords."""
        spans = []
        for word in text:
            if word in keywords or any(kw in word for kw in keywords if len(kw) > 1):
                spans.append(f'<span class="sub-word-kw">{word}</span>')
            else:
                spans.append(f'<span class="sub-word">{word}</span>')
        return spans

    def _char_spans(self, text: str, keywords: set[str]) -> list[str]:
        """Split text into char-level spans (for char_pop mode)."""
        spans = []
        i = 0
        while i < len(text):
            ch = text[i]
            # Check if this char starts a keyword
            is_kw = False
            for kw in sorted(keywords, key=len, reverse=True):
                if text[i:].startswith(kw):
                    for c in kw:
                        spans.append(f'<span class="sub-char-kw">{c}</span>')
                    i += len(kw)
                    is_kw = True
                    break
            if not is_kw:
                spans.append(f'<span class="sub-char">{ch}</span>')
                i += 1
        return spans

    def _line_gsap(self, container_id: str, line: SubtitleLine) -> str:
        """Generate GSAP animation for one subtitle line."""
        s = self.preset
        t = line.start
        word_selector = f"#{container_id} .sub-word, #{container_id} .sub-word-kw"
        char_selector = f"#{container_id} .sub-char, #{container_id} .sub-char-kw"

        lines = []

        if line.mode == "char_pop":
            # Character-by-character pop-in
            lines.append(f"""
// Subtitle char-pop @ {t:.3f}s: "{line.text[:20]}..."
tl.from("{char_selector}",{{
  opacity:0, scale:0.3, y:15,
  duration:0.35, ease:"back.out(2)",
  stagger:{s.stagger}
}},{t});
tl.to("{char_selector}",{{opacity:0, y:-10, duration:0.25, ease:"power3.in",
  stagger:0.015}},{line.end - 0.3});
""")
        elif line.mode == "scale_pop":
            # Word-by-word scale pop
            lines.append(f"""
// Subtitle word-pop @ {t:.3f}s: "{line.text[:20]}..."
tl.from("{word_selector}",{{
  opacity:0, scale:0.3, y:18,
  duration:0.4, ease:"back.out(2)",
  stagger:{s.stagger}
}},{t});
tl.to("{word_selector}",{{opacity:0, y:-8, duration:0.25, ease:"power3.in",
  stagger:0.02}},{line.end - 0.3});
""")
        elif line.mode == "fade":
            # Simple fade-in
            lines.append(f"""
// Subtitle fade @ {t:.3f}s: "{line.text[:20]}..."
tl.set("#{container_id}",{{opacity:0}},{t});
tl.to("#{container_id}",{{opacity:1,duration:0.3,ease:"power3.out"}},{t});
tl.to("#{container_id}",{{opacity:0,duration:0.25,ease:"power3.in"}},{line.end - 0.3});
""")
        else:
            # fallback: same as fade
            lines.append(f"""
tl.set("#{container_id}",{{opacity:0}},{t});
tl.to("#{container_id}",{{opacity:1,duration:0.3}},{t});
tl.to("#{container_id}",{{opacity:0,duration:0.25}},{line.end - 0.3});
""")

        # Keyword pulse animation
        for kw in line.keywords:
            kw_sel = f"#{container_id} .sub-word-kw"
            lines.append(f"""
tl.to("{kw_sel}",{{scale:{s.scale_peak},duration:0.2,repeat:1,yoyo:true,
  ease:"sine.inOut"}},{t + 0.45});
""")
            break  # one pulse for all keywords in the line

        return "\n".join(lines)
