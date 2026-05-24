"""Frame Assembler — lightweight HTML assembly for FrameCraft.

Replaces auto-video-platform's AssemblyEngine with a standalone implementation.
Takes Script + asset_plan → generates TTS audio, SRT subtitles, and a simple
GSAP-driven HTML page suitable for Chromium rendering.

Usage:
    from services.rendering.assembler import FrameAssembler
    assembler = FrameAssembler(output_dir="output/ep1")
    result = assembler.assemble(script, asset_plan)
"""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AssemblyResult:
    html_path: str
    audio_path: str
    srt_path: str
    bgm_path: str
    output_dir: str
    total_duration_s: float
    metadata: dict


class FrameAssembler:
    """Script + assets → TTS + HTML page.

    Lightweight replacement for AVP's AssemblyEngine. Does NOT depend on
    CompositionBuilder or component libraries — generates plain HTML directly.
    """

    def __init__(self, output_dir: str = "output", tts_voice: str = None,
                 tts_speed: float = 1.1, canvas_width: int = 1080,
                 canvas_height: int = 1920, component_set: str = "ecommerce"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tts_voice = tts_voice or "zh-CN-YunxiNeural"
        self.tts_speed = tts_speed
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height

    # ─── Public API ─────────────────────────────────────

    def assemble(self, script, asset_plan: dict,
                 bgm_path: str = "", bgm_tracks: list = None,
                 ref_analysis: dict = None) -> AssemblyResult:
        """Full assembly: TTS → HTML → result."""
        audio_dir = self.output_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        # 1. Generate TTS narration + SRT
        audio_path, srt_path, total_dur = self._generate_tts(script, audio_dir)

        # 2. Build HTML page
        html_path = self._build_html(script, asset_plan, audio_path, srt_path,
                                     bgm_path, total_dur)

        # 3. Copy GSAP to output dir
        self._copy_gsap()

        # 4. Copy asset images
        self._copy_assets(asset_plan)

        # 5. Write metadata
        metadata = self._write_metadata(script, ref_analysis, total_dur)

        return AssemblyResult(
            html_path=str(html_path),
            audio_path=audio_path,
            srt_path=srt_path,
            bgm_path=bgm_path,
            output_dir=str(self.output_dir),
            total_duration_s=total_dur,
            metadata=metadata,
        )

    # ─── TTS ─────────────────────────────────────────────

    def _generate_tts(self, script, audio_dir: Path) -> tuple:
        from services.rendering.tts_builder import TTSBuilder

        builder = TTSBuilder(
            voice=self.tts_voice,
            speed=self.tts_speed,
            output_dir=str(audio_dir),
        )
        timeline = builder.build_from_script(script)

        audio_dest = str(audio_dir / "narration.mp3")
        srt_dest = str(audio_dir / "subtitles.srt")

        if timeline.audio_path and os.path.exists(timeline.audio_path):
            if os.path.abspath(timeline.audio_path) != os.path.abspath(audio_dest):
                shutil.copy2(timeline.audio_path, audio_dest)
        if timeline.srt_path and os.path.exists(timeline.srt_path):
            if os.path.abspath(timeline.srt_path) != os.path.abspath(srt_dest):
                shutil.copy2(timeline.srt_path, srt_dest)

        return audio_dest, srt_dest, timeline.total_duration_s

    # ─── HTML ────────────────────────────────────────────

    def _build_html(self, script, asset_plan: dict,
                    audio_path: str, srt_path: str,
                    bgm_path: str, total_dur: float) -> Path:
        """Generate a self-contained GSAP HTML page for Chromium rendering."""
        scenes_js = self._build_scenes_js(script, asset_plan)
        srt_entries = self._load_srt_entries(srt_path)
        subtitles_js = self._build_subtitles_js(srt_entries)

        audio_rel = os.path.basename(audio_path)
        bgm_rel = os.path.basename(bgm_path) if bgm_path and os.path.exists(bgm_path) else ""

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width={self.canvas_width},height={self.canvas_height}">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{self.canvas_width}px;height:{self.canvas_height}px;overflow:hidden;
      background:#000;font-family:"Microsoft YaHei","PingFang SC",sans-serif;
      position:relative}}
.scene{{position:absolute;inset:0;opacity:0;display:flex;
        flex-direction:column;align-items:center;justify-content:center}}
.scene img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.scene .caption{{position:absolute;bottom:200px;left:50%;transform:translateX(-50%);
    color:#fff;font-size:42px;font-weight:800;text-align:center;
    text-shadow:0 2px 12px rgba(0,0,0,0.85);z-index:10;max-width:900px;
    padding:16px 32px;background:rgba(0,0,0,0.45);border-radius:16px}}
.scene .subtitle{{position:absolute;bottom:120px;left:50%;transform:translateX(-50%);
    color:#fff;font-size:30px;font-weight:600;text-align:center;
    text-shadow:0 2px 10px rgba(0,0,0,0.8);z-index:10;max-width:900px}}
#progress{{position:absolute;bottom:0;left:0;height:4px;background:#ff1744;
           z-index:99;width:0%}}
.btn{{position:absolute;inset:0;z-index:100;cursor:pointer}}
</style>
</head>
<body>
<audio id="narration" src="{audio_rel}" preload="auto"></audio>
{"<audio id=\"bgm\" src=\"" + bgm_rel + "\" loop preload=\"auto\"></audio>" if bgm_rel else ""}
<div id="progress"></div>

<div id="scenes"></div>
<div id="subtitles"></div>

<div class="btn" id="playBtn" onclick="start()"></div>

<script src="gsap.min.js"></script>
<script>
var tl = gsap.timeline({{paused:true}});
var totalDur = {total_dur};

// ── Scenes ──
{scenes_js}

// ── Subtitles ──
{subtitles_js}

// ── Progress bar ──
tl.to("#progress", {{width:"100%",duration:totalDur,ease:"none"}}, 0);

// ── Audio ──
var narration = document.getElementById("narration");
var bgm = document.getElementById("bgm");
tl.call(function() {{ narration.play(); if(bgm) bgm.play(); }}, [], 0);

// ── Autoplay support ──
var autoplay = new URLSearchParams(window.location.search).get("autoplay");
if (autoplay === "1") {{
  document.getElementById("playBtn").style.display = "none";
  setTimeout(function() {{ start(); }}, 500);
}}

function start() {{
  document.getElementById("playBtn").style.display = "none";
  tl.seek(0);
  tl.play();
  narration.play();
  if (bgm) bgm.play();
}}
</script>
</body>
</html>'''

        html_path = self.output_dir / "index.html"
        html_path.write_text(html, encoding="utf-8")
        return html_path

    def _build_scenes_js(self, script, asset_plan: dict) -> str:
        """Generate GSAP JS for each beat's scene element."""
        lines = []
        lines.append("var container = document.getElementById('scenes');")
        cursor = 0.0

        for beat in script.beats:
            ap = asset_plan.get(beat.index)
            asset = ap.matched_asset if ap else None
            img_path = ""
            if asset and asset.file_path:
                img_path = os.path.basename(asset.file_path)

            scene_id = f"scene{beat.index}"
            dur = beat.duration_s

            img_html = f'<img src="assets/{img_path}" />' if img_path else ""
            html_content = (
                f'<div class="scene" id="{scene_id}">'
                f'{img_html}'
                f'<div class="caption">{self._escape_js(beat.text)}</div>'
                f'</div>'
            )

            lines.append(
                f'container.insertAdjacentHTML("beforeend",'
                f'"{html_content}");'
            )
            lines.append(
                f'tl.set("#{scene_id}",{{opacity:0}},{cursor});'
            )
            lines.append(
                f'tl.to("#{scene_id}",{{opacity:1,duration:0.3,ease:"power3.out"}},{cursor});'
            )
            lines.append(
                f'tl.to("#{scene_id}",{{opacity:0,duration:0.25,ease:"power3.in"}},{cursor + dur - 0.3});'
            )
            cursor += dur

        # Outro
        outro = script.outro
        ap = asset_plan.get(outro.index)
        asset = ap.matched_asset if ap else None
        img_path = ""
        if asset and asset.file_path:
            img_path = os.path.basename(asset.file_path)

        img_html = f'<img src="assets/{img_path}" />' if img_path else ""
        lines.append(
            f'container.insertAdjacentHTML("beforeend",'
            f'"<div class=\\"scene\\" id=\\"scene{outro.index}\\">'
            f'{img_html}'
            f'<div class=\\"caption\\">{self._escape_js(outro.text)}</div>'
            f'</div>");'
        )
        lines.append(f'tl.set("#scene{outro.index}",{{opacity:0}},{cursor});')
        lines.append(f'tl.to("#scene{outro.index}",{{opacity:1,duration:0.3,ease:"power3.out"}},{cursor});')

        return "\n".join(lines)

    def _build_subtitles_js(self, entries: list) -> str:
        """Generate GSAP JS for subtitle text overlay."""
        if not entries:
            return "// No subtitles"

        lines = []
        lines.append("var subContainer = document.getElementById('subtitles');")
        lines.append(
            'subContainer.innerHTML = \'<div id="subText" class="subtitle"></div>\';'
        )

        for i, (start, end, text) in enumerate(entries):
            lines.append(
                f'tl.call(function() {{'
                f'document.getElementById("subText").textContent = "{self._escape_js(text)}";'
                f'document.getElementById("subText").style.opacity = "1";'
                f'}}, [], {start});'
            )
            lines.append(
                f'tl.to("#subText", {{opacity:0, duration:0.2}}, {end - 0.2});'
            )

        return "\n".join(lines)

    def _load_srt_entries(self, srt_path: str) -> list:
        """Parse SRT file into [(start_s, end_s, text), ...]."""
        if not srt_path or not os.path.exists(srt_path):
            return []
        entries = []
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return entries
        blocks = content.split("\n\n")
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) >= 3:
                times = lines[1].split(" --> ")
                if len(times) == 2:
                    start = self._srt_time_to_s(times[0])
                    end = self._srt_time_to_s(times[1])
                    text = " ".join(lines[2:])
                    entries.append((start, end, text))
        return entries

    @staticmethod
    def _srt_time_to_s(t: str) -> float:
        """Convert SRT timestamp 'HH:MM:SS,mmm' to seconds."""
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    @staticmethod
    def _escape_js(text: str) -> str:
        """Escape text for safe embedding in JS string literals."""
        return (text.replace("\\", "\\\\")
                    .replace('"', '\\"')
                    .replace("\n", "\\n")
                    .replace("\r", ""))

    # ─── Assets ──────────────────────────────────────────

    def _copy_gsap(self):
        """Copy gsap.min.js into output_dir for local rendering."""
        dst = self.output_dir / "gsap.min.js"
        if dst.exists():
            return
        candidates = [
            Path(__file__).resolve().parent / "static" / "gsap.min.js",
        ]
        for src in candidates:
            if src.exists():
                shutil.copy2(str(src), str(dst))
                return

    def _copy_assets(self, asset_plan: dict):
        """Copy referenced images into output_dir/assets/."""
        assets_dir = self.output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        copied = set()

        for ap in asset_plan.values():
            src = ap.matched_asset.file_path if ap.matched_asset else ""
            if src and os.path.isfile(src) and src not in copied:
                dst = assets_dir / os.path.basename(src)
                if not dst.exists():
                    shutil.copy2(src, str(dst))
                copied.add(src)

    def _write_metadata(self, script, ref_analysis: dict, total_dur: float) -> dict:
        """Save metadata JSON alongside the output."""
        tags = getattr(script, "tags", [])
        meta = {
            "title": getattr(script, "title", ""),
            "hook_type": getattr(script, "hook_type", ""),
            "bgm_style": getattr(script, "bgm_style", ""),
            "tags": tags if isinstance(tags, list) else list(tags),
            "checklist": getattr(script, "checklist", ""),
            "total_duration_s": total_dur,
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
        }
        if ref_analysis:
            meta["brand_style"] = ref_analysis.get("brand_style", {})
        meta_path = self.output_dir / "metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta
