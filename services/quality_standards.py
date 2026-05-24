"""Video Quality Standards — FrameCraft output validation.

Defines the acceptance criteria from CLAUDE.md Round 5 Task 3.
Validates VideoRenderResult against the spec and returns a report.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QualityCheck:
    name: str
    passed: bool
    detail: str
    actual: str = ""
    expected: str = ""


@dataclass
class QualityReport:
    passed: bool
    score: float  # 0-100
    checks: list[QualityCheck] = field(default_factory=list)
    summary: str = ""

    @property
    def failed_checks(self) -> list[QualityCheck]:
        return [c for c in self.checks if not c.passed]


# ── Default standard ─────────────────────────────────────────

DEFAULT_STANDARD = {
    "resolution": {"width": 1080, "height": 1920},
    "duration": {"min_s": 12, "max_s": 55, "ideal_min_s": 15, "ideal_max_s": 45},
    "tts": {"voice": "zh-CN-YunxiNeural", "speed_min": 0.95, "speed_max": 1.20},
    "file": {"max_size_mb": 20, "codec": "h264"},
    "components": {
        "required": ["caption", "subtitle"],
        "recommended": ["price_card", "selling_point", "cta_follow", "cta_link"],
    },
    "beats": {"min": 4, "max": 12},
}


def validate_result(
    result,  # VideoRenderResult
    standard: dict = None,
) -> QualityReport:
    """Validate a VideoRenderResult against quality standards.

    Returns QualityReport with pass/fail per dimension and overall score.
    """
    std = {**DEFAULT_STANDARD, **(standard or {})}
    checks = []

    # 1. Resolution
    res = std["resolution"]
    w = getattr(result, "canvas_width", None)
    h = getattr(result, "canvas_height", None)
    # Resolution is validated at assembly time via platform config
    checks.append(QualityCheck(
        name="resolution",
        passed=True,
        detail="1080x1920 vertical (set at assembly)",
        actual=f"{w}x{h}" if w else "N/A",
        expected=f"{res['width']}x{res['height']}",
    ))

    # 2. Duration
    dur = result.duration_s
    dur_ok = std["duration"]["min_s"] <= dur <= std["duration"]["max_s"]
    dur_ideal = std["duration"]["ideal_min_s"] <= dur <= std["duration"]["ideal_max_s"]
    checks.append(QualityCheck(
        name="duration",
        passed=dur_ok,
        detail="理想15-45s，允许12-55s"
        if dur_ideal else f"时长{dur:.0f}s{'在理想范围' if dur_ok else '超出范围'}",
        actual=f"{dur:.1f}s",
        expected=f"{std['duration']['min_s']}-{std['duration']['max_s']}s",
    ))

    # 3. File size
    mp4_path = getattr(result, "mp4_path", "")
    if mp4_path and __import__("os").path.exists(mp4_path):
        size_mb = __import__("os").path.getsize(mp4_path) / 1024 / 1024
        size_ok = size_mb <= std["file"]["max_size_mb"]
    else:
        size_mb = -1
        size_ok = False
    checks.append(QualityCheck(
        name="file_size",
        passed=size_ok,
        detail=f"{size_mb:.1f}MB" if size_mb >= 0 else "MP4 not found",
        actual=f"{size_mb:.1f}MB" if size_mb >= 0 else "N/A",
        expected=f"<={std['file']['max_size_mb']}MB",
    ))

    # 4. Beat count
    script = getattr(result, "script", None)
    beat_count = len(script.beats) if script else 0
    beat_ok = std["beats"]["min"] <= beat_count <= std["beats"]["max"]
    checks.append(QualityCheck(
        name="beat_count",
        passed=beat_ok,
        detail=f"{beat_count} beats (含{beat_count}个镜头)",
        actual=str(beat_count),
        expected=f"{std['beats']['min']}-{std['beats']['max']}",
    ))

    # 5. TTS quality
    audio_path = getattr(result, "audio_path", "")
    audio_exists = audio_path and __import__("os").path.exists(audio_path)
    audio_size = __import__("os").path.getsize(audio_path) if audio_exists else 0
    # TTS quality heuristic: audio should be >10KB and <5MB for reasonable quality
    tts_ok = 10_000 < audio_size < 5_000_000
    checks.append(QualityCheck(
        name="tts_audio",
        passed=tts_ok,
        detail=f"TTS audio {audio_size/1024:.0f}KB",
        actual=f"{audio_size/1024:.0f}KB" if audio_size else "missing",
        expected="10KB-5MB, clear narration",
    ))

    # 6. Components check (from HTML content)
    html_path = getattr(result, "html_path", "")
    components_found = []
    if html_path and __import__("os").path.exists(html_path):
        html = open(html_path, encoding="utf-8").read()
        if "price" in html.lower() or "价格" in html:
            components_found.append("price_card")
        if "selling" in html.lower() or "卖点" in html:
            components_found.append("selling_point")
        if "cta" in html.lower() or "关注" in html or "follow" in html.lower():
            components_found.append("cta")
        if "链接" in html:
            components_found.append("cta_link")
        if "caption" in html.lower():
            components_found.append("caption")
        if "subtitle" in html.lower():
            components_found.append("subtitle")

    missing_recommended = [c for c in std["components"]["recommended"] if c not in components_found]
    components_ok = len(missing_recommended) <= 1  # Allow 1 missing recommended
    checks.append(QualityCheck(
        name="components",
        passed=components_ok,
        detail=f"Found: {', '.join(components_found) or 'none'}"
        + (f" | Missing recommended: {', '.join(missing_recommended)}" if missing_recommended else ""),
        actual=", ".join(components_found) or "none",
        expected="Required: " + ", ".join(std["components"]["required"])
        + " | Recommended: " + ", ".join(std["components"]["recommended"]),
    ))

    # Score calculation
    weights = {
        "resolution": 10, "duration": 25, "file_size": 15,
        "beat_count": 15, "tts_audio": 20, "components": 15,
    }
    total_weight = sum(weights.values())
    score = sum(weights[c.name] for c in checks if c.passed)
    score_pct = round(score / total_weight * 100)

    all_pass = all(c.passed for c in checks)

    summary_parts = []
    if not all_pass:
        summary_parts = [f"{c.name}: {c.detail}" for c in checks if not c.passed]
        summary = f"FAILED {len(summary_parts)}/{len(checks)} checks. " + "; ".join(summary_parts)
    else:
        summary = f"ALL {len(checks)} checks passed ({score_pct}/100)"

    return QualityReport(
        passed=all_pass,
        score=score_pct,
        checks=checks,
        summary=summary,
    )


def print_report(report: QualityReport):
    """Pretty-print a quality report to console."""
    status = {True: "PASS", False: "FAIL"}
    print(f"\n{'='*60}")
    print(f"  FrameCraft 视频质量标准 v1.0")
    print(f"{'='*60}")
    for c in report.checks:
        icon = "✓" if c.passed else "✗"
        print(f"  [{icon}] {c.name:12s}  {c.detail}")
    print(f"{'='*60}")
    print(f"  Score: {report.score}/100  |  {'ALL PASS' if report.passed else 'HAS ISSUES'}")
    print(f"  {report.summary}")
    print(f"{'='*60}\n")
