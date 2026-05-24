"""TTS Builder — script storyboard → audio narration + SRT subtitles.

Generates per-shot TTS audio via edge-tts, stitches them with pauses,
and produces a synchronized SRT subtitle timeline.

Usage:
    from services.rendering.tts_builder import TTSBuilder
    builder = TTSBuilder()
    timeline = builder.build(script_dict)
"""
import asyncio, json, os, shutil, subprocess, tempfile
from dataclasses import dataclass, field


@dataclass
class AudioSegment:
    shot: int
    text: str
    audio_path: str
    duration_s: float


@dataclass
class TTSTimeline:
    audio_path: str           # Combined MP3
    srt_path: str             # SRT subtitle file
    segments: list = field(default_factory=list)
    total_duration_s: float = 0.0


class TTSBuilder:
    """Generate narrated audio + subtitle timeline from a production script.

    Supports multi-provider fallback via TTSDispatcher.
    """

    def __init__(self, voice: str = "zh-CN-YunxiNeural", speed: float = 1.0,
                 pause_between_shots: float = 0.35,
                 output_dir: str = None, dispatcher=None):
        self.voice = voice
        self.speed = f"+{int((speed - 1) * 100)}%" if speed >= 1 else f"{int((speed - 1) * 100)}%"
        self.speed_float = speed
        self.pause = pause_between_shots
        self.output_dir = os.path.abspath(output_dir or tempfile.mkdtemp(prefix="tts_"))
        self._dispatcher = dispatcher  # TTSDispatcher instance (optional)

    # ─── Public API ───────────────────────────────────────

    def build(self, script: dict) -> TTSTimeline:
        """Main entry (old API): script dict → TTS audio + SRT timeline."""
        os.makedirs(self.output_dir, exist_ok=True)

        storyboard = script.get("storyboard", [])
        if not storyboard:
            raise ValueError("Script has no storyboard")

        # Generate per-shot audio
        segments = self._run_async_safe(self._generate_all(storyboard))

        # Stitch audio files together
        combined_path = self._stitch_audio(segments)

        # Generate SRT from segment timings
        srt_path = self._build_srt(segments)

        total = sum(s.duration_s for s in segments) + self.pause * (len(segments) - 1)

        return TTSTimeline(
            audio_path=combined_path,
            srt_path=srt_path,
            segments=segments,
            total_duration_s=total,
        )

    def build_from_script(self, script) -> TTSTimeline:
        """New API: Script object → TTS audio + SRT timeline.

        Accepts the new Script dataclass from script_engine.py.
        """
        os.makedirs(self.output_dir, exist_ok=True)

        # Convert Script beats → storyboard-compatible list
        storyboard = []
        for beat in script.beats:
            storyboard.append({
                "shot": beat.index,
                "audio": beat.text,
                "caption": beat.text,
            })
        # Add outro
        storyboard.append({
            "shot": script.outro.index,
            "audio": script.outro.text,
            "caption": script.outro.text,
        })

        segments = self._run_async_safe(self._generate_all(storyboard))
        combined_path = self._stitch_audio(segments)
        srt_path = self._build_srt(segments)

        total = sum(s.duration_s for s in segments) + self.pause * (len(segments) - 1)

        return TTSTimeline(
            audio_path=combined_path,
            srt_path=srt_path,
            segments=segments,
            total_duration_s=total,
        )

    # ─── Per-shot TTS ─────────────────────────────────────

    def _run_async_safe(self, coro):
        """Safely run a coroutine — handles nested event loops (e.g. Gradio)."""
        try:
            return asyncio.run(coro)
        except RuntimeError:
            # Already in an event loop (Gradio, Playwright, etc.)
            # Use a nested event loop in a thread
            import threading
            result = [None]
            exc = [None]

            def _runner():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result[0] = loop.run_until_complete(coro)
                    loop.close()
                except Exception as e:
                    exc[0] = e

            t = threading.Thread(target=_runner)
            t.start()
            t.join()
            if exc[0]:
                raise exc[0]
            return result[0]

    async def _generate_all(self, storyboard: list) -> list[AudioSegment]:
        """Generate TTS for each shot — tries dispatcher first, falls back to edge-tts."""
        # Try multi-provider dispatcher for segment synthesis
        if self._dispatcher:
            try:
                return self._generate_via_dispatcher(storyboard)
            except Exception as e:
                print(f"  [WARN] TTS dispatcher failed ({e}), falling back to edge-tts")

        # Try lazy-global dispatcher
        try:
            from services.rendering.tts_providers import get_tts_dispatcher
            tts_disp = get_tts_dispatcher()
            if tts_disp.get_available_provider():
                self._dispatcher = tts_disp
                return self._generate_via_dispatcher(storyboard)
        except Exception:
            pass

        # Original edge-tts parallel generation
        tasks = []
        for shot in storyboard:
            text = shot.get("audio", shot.get("caption", ""))
            if not text.strip():
                continue
            tasks.append(self._tts_one(shot["shot"], text))

        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    def _generate_via_dispatcher(self, storyboard: list) -> list[AudioSegment]:
        """Use TTSDispatcher to synthesize all segments at once."""
        from services.rendering.tts_providers import TTSCompiled

        compiled: TTSCompiled = self._dispatcher.synthesize_segments(
            segments=storyboard,
            voice=self.voice,
            speed=self.speed_float,
            output_dir=self.output_dir,
        )

        return [
            AudioSegment(
                shot=seg.shot,
                text=seg.text,
                audio_path=seg.audio_path,
                duration_s=seg.duration_s,
            )
            for seg in compiled.segments
        ]

    async def _tts_one(self, shot_num: int, text: str) -> AudioSegment:
        """Generate TTS for a single shot."""
        import edge_tts

        out_path = os.path.join(self.output_dir, f"shot_{shot_num:02d}.mp3")

        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.speed,
        )
        await communicate.save(out_path)

        duration = self._get_duration(out_path)
        return AudioSegment(
            shot=shot_num,
            text=text,
            audio_path=out_path,
            duration_s=duration,
        )

    # ─── Audio stitching ──────────────────────────────────

    def _stitch_audio(self, segments: list[AudioSegment]) -> str:
        """Concatenate per-shot MP3s with pauses into a single narration track."""

        concat_file = os.path.join(self.output_dir, "concat.txt")
        silence_path = None

        with open(concat_file, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments):
                # Use absolute forward-slash paths for ffmpeg concat demuxer
                abs_path = os.path.abspath(seg.audio_path).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
                if i < len(segments) - 1 and self.pause > 0:
                    if silence_path is None:
                        silence_path = self._make_silence()
                    abs_silence = os.path.abspath(silence_path).replace('\\', '/')
                    f.write(f"file '{abs_silence}'\n")

        combined = os.path.join(self.output_dir, "narration.mp3")
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy", combined,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            # Fallback: simple copy of first segment (better than nothing)
            print(f"  [WARN] FFmpeg concat failed: {e.stderr[:200] if e.stderr else e}")
            if segments:
                shutil.copy2(segments[0].audio_path, combined)
        except FileNotFoundError:
            # ffmpeg not installed — just copy first segment
            if segments:
                shutil.copy2(segments[0].audio_path, combined)

        return combined

    def _make_silence(self) -> str:
        """Generate a short silent MP3 for gaps between shots."""
        path = os.path.join(self.output_dir, "_silence.mp3")
        duration_ms = int(self.pause * 1000)
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"anullsrc=r=24000",
            "-t", f"{self.pause:.3f}",
            "-c:a", "libmp3lame", "-b:a", "64k",
            path,
        ], check=True)
        return path

    # ─── SRT generation ───────────────────────────────────

    def _build_srt(self, segments: list[AudioSegment]) -> str:
        """Generate SRT subtitle file from segment timing."""
        srt_path = os.path.join(self.output_dir, "subtitles.srt")
        lines = []
        cursor = 0.0

        for i, seg in enumerate(segments):
            start = cursor
            end = cursor + seg.duration_s
            lines.append(f"{i + 1}")
            lines.append(f"{self._fmt_time(start)} --> {self._fmt_time(end)}")
            lines.append(seg.text)
            lines.append("")  # blank line separator
            cursor = end + self.pause

        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return srt_path

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _get_duration(path: str) -> float:
        """Get audio duration using ffprobe."""
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ], capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 2.0  # fallback estimate
