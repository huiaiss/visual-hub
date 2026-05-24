"""Multi-TTS Provider System — strategy pattern + config-driven.

Supports Edge TTS, CosyVoice, Coqui TTS, OpenAI TTS.
Key feature: word-level timestamps for precise subtitle animation.

Architecture inspired by MoneyPrinterTurbo (55K⭐) + Pixelle-Video (11K⭐).

Usage:
    from services.rendering.tts_providers import TTSDispatcher
    dispatcher = TTSDispatcher()
    result = dispatcher.synthesize("你好世界")
"""

import json, os, subprocess, tempfile, asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Auto-load .env ─────────────────────────────────────────

try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass


# ─── Config ─────────────────────────────────────────────────

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _load_config(config_path: str = None) -> dict:
    path = Path(config_path) if config_path else CONFIG_DIR / "tts_config.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "default_voice": "zh-CN-YunxiNeural",
        "default_speed": 1.1,
        "pause_between_shots_s": 0.35,
        "providers": [
            {"name": "edge_tts", "display_name": "Edge TTS", "priority": 1, "enabled": True},
        ],
    }


# ─── Data Types ─────────────────────────────────────────────

@dataclass
class WordTimestamp:
    word: str
    start_s: float
    end_s: float


@dataclass
class TTSResult:
    audio_path: str
    duration_s: float
    provider: str
    voice: str
    word_timestamps: list = field(default_factory=list)
    srt_path: str = ""

    @property
    def has_word_timestamps(self) -> bool:
        return len(self.word_timestamps) > 0


@dataclass
class TTSSegment:
    """A single sentence/shot with its audio."""
    shot: int
    text: str
    audio_path: str
    duration_s: float
    word_timestamps: list = field(default_factory=list)


@dataclass
class TTSCompiled:
    """Final compiled narration — all segments stitched with pauses."""
    audio_path: str
    srt_path: str
    segments: list[TTSSegment] = field(default_factory=list)
    total_duration_s: float = 0.0


# ─── Base Provider ─────────────────────────────────────────

class BaseTTSProvider(ABC):
    """Abstract TTS provider. All voice providers implement this interface."""

    def __init__(self, config: dict):
        self.config = config
        self.name = config["name"]
        self.display_name = config["display_name"]
        self.supports_word_timestamps = config.get("word_timestamps", False)

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is ready to use."""

    @abstractmethod
    def synthesize(self, text: str, voice: str = None,
                   speed: float = 1.0, output_dir: str = None) -> TTSResult:
        """Synthesize a single text segment. Returns TTSResult with audio path."""


# ─── Edge TTS Provider ─────────────────────────────────────

class EdgeTTSProvider(BaseTTSProvider):
    """Microsoft Edge TTS — free, high quality, no API key needed."""

    def is_available(self) -> bool:
        try:
            subprocess.run(["edge-tts", "--version"], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def synthesize(self, text: str, voice: str = None,
                   speed: float = 1.0, output_dir: str = None) -> TTSResult:
        import edge_tts
        import threading as _threading

        out_dir = Path(output_dir or tempfile.mkdtemp(prefix="tts_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "output.mp3"

        used_voice = voice or self.config.get("voices", ["zh-CN-YunxiNeural"])[0]
        rate = f"+{int((speed - 1) * 100)}%" if speed >= 1 else f"{int((speed - 1) * 100)}%"

        async def _tts():
            communicate = edge_tts.Communicate(text=text, voice=used_voice, rate=rate)
            await communicate.save(str(out_path))

        try:
            asyncio.get_running_loop()
            # Running loop (Gradio/Playwright) — run Python API in separate thread
            exc = [None]
            def _run():
                try:
                    asyncio.run(_tts())
                except Exception as e:
                    exc[0] = e
            t = _threading.Thread(target=_run)
            t.start()
            t.join(timeout=120)
            if exc[0]:
                raise exc[0]
        except RuntimeError:
            # No running loop — use asyncio.run() directly
            asyncio.run(_tts())

        duration = _get_audio_duration(str(out_path))
        return TTSResult(
            audio_path=str(out_path),
            duration_s=duration,
            provider="edge_tts",
            voice=used_voice,
            word_timestamps=_estimate_word_timestamps(text, duration),
        )


# ─── CosyVoice Provider ────────────────────────────────────

class CosyVoiceProvider(BaseTTSProvider):
    """Alibaba CosyVoice — word-level timestamps, excellent Chinese quality.

    Requires local installation:
        pip install cosyvoice
        python -m cosyvoice.download
    """

    def is_available(self) -> bool:
        try:
            import cosyvoice
            return True
        except ImportError:
            return False

    def synthesize(self, text: str, voice: str = None,
                   speed: float = 1.0, output_dir: str = None) -> TTSResult:
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice
        except ImportError:
            raise RuntimeError(
                "CosyVoice not installed. Run: pip install cosyvoice && python -m cosyvoice.download"
            )

        out_dir = Path(output_dir or tempfile.mkdtemp(prefix="tts_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "output.wav"

        model_name = self.config.get("default_model", "cosyvoice-300m-sft")

        # CosyVoice inference with word timestamps
        cosyvoice = CosyVoice(model_name)
        result = cosyvoice.inference(
            text=text,
            stream=False,
            speed=1.0 / speed if speed > 0 else 1.0,
        )

        # Save audio
        import soundfile as sf
        sf.write(str(out_path), result['audio'], result['sample_rate'])

        # Convert to MP3 for compatibility
        mp3_path = out_dir / "output.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-i", str(out_path), "-c:a", "libmp3lame", "-b:a", "128k",
            str(mp3_path),
        ], check=True)

        # Extract word timestamps
        word_timestamps = []
        if hasattr(result, 'word_timestamps') and result['word_timestamps']:
            for wt in result['word_timestamps']:
                word_timestamps.append(WordTimestamp(
                    word=wt.get('word', ''),
                    start_s=wt.get('start', 0.0),
                    end_s=wt.get('end', 0.0),
                ))

        duration = _get_audio_duration(str(mp3_path))
        return TTSResult(
            audio_path=str(mp3_path),
            duration_s=duration,
            provider="cosyvoice",
            voice=model_name,
            word_timestamps=word_timestamps or _estimate_word_timestamps(text, duration),
        )


# ─── Coqui TTS Provider ────────────────────────────────────

class CoquiTTSProvider(BaseTTSProvider):
    """Coqui TTS — open-source, offline, many models."""

    def is_available(self) -> bool:
        try:
            import TTS
            return True
        except ImportError:
            return False

    def synthesize(self, text: str, voice: str = None,
                   speed: float = 1.0, output_dir: str = None) -> TTSResult:
        from TTS.api import TTS

        out_dir = Path(output_dir or tempfile.mkdtemp(prefix="tts_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "output.wav"

        model_name = voice or self.config.get("default_model",
            "tts_models/zh-CN/baker/tacotron2-DDC-GST")

        tts = TTS(model_name=model_name)
        tts.tts_to_file(text=text, file_path=str(out_path))

        # Convert to MP3
        mp3_path = out_dir / "output.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-i", str(out_path), "-c:a", "libmp3lame", "-b:a", "128k",
            str(mp3_path),
        ], check=True)

        duration = _get_audio_duration(str(mp3_path))
        return TTSResult(
            audio_path=str(mp3_path),
            duration_s=duration,
            provider="coqui_tts",
            voice=model_name,
            word_timestamps=_estimate_word_timestamps(text, duration),
        )


# ─── OpenAI TTS Provider ───────────────────────────────────

class OpenAITTSProvider(BaseTTSProvider):
    """OpenAI TTS API — premium quality."""

    def is_available(self) -> bool:
        key = os.environ.get("OPENAI_API_KEY")
        return bool(key)

    def synthesize(self, text: str, voice: str = None,
                   speed: float = 1.0, output_dir: str = None) -> TTSResult:
        import urllib.request, urllib.error

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        out_dir = Path(output_dir or tempfile.mkdtemp(prefix="tts_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "output.mp3"

        used_voice = voice or self.config.get("voices", ["alloy"])[0]
        model = self.config.get("default_model", "tts-1")

        data = json.dumps({
            "model": model,
            "input": text,
            "voice": used_voice,
            "speed": speed,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                out_path.write_bytes(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:500] if e.fp else ""
            raise RuntimeError(f"OpenAI TTS HTTP {e.code}: {body}")

        duration = _get_audio_duration(str(out_path))
        return TTSResult(
            audio_path=str(out_path),
            duration_s=duration,
            provider="openai_tts",
            voice=used_voice,
            word_timestamps=_estimate_word_timestamps(text, duration),
        )


# ─── Provider Registry ─────────────────────────────────────

TTS_PROVIDER_CLASSES = {
    "edge_tts": EdgeTTSProvider,
    "cosyvoice": CosyVoiceProvider,
    "coqui_tts": CoquiTTSProvider,
    "openai_tts": OpenAITTSProvider,
}


# ─── Dispatcher ────────────────────────────────────────────

class TTSDispatcher:
    """Multi-provider TTS dispatcher with auto-fallback.

    Usage:
        dispatcher = TTSDispatcher()
        result = dispatcher.synthesize("你好世界，今天天气真好。")
        print(f"Audio: {result.audio_path}")
        print(f"Duration: {result.duration_s:.1f}s")
        print(f"Provider: {result.provider}")
    """

    def __init__(self, config_path: str = None):
        self.config = _load_config(config_path)
        self.default_voice = self.config.get("default_voice", "zh-CN-YunxiNeural")
        self.default_speed = self.config.get("default_speed", 1.1)
        self.pause_s = self.config.get("pause_between_shots_s", 0.35)

        self._providers: list[BaseTTSProvider] = []
        for pconf in sorted(self.config.get("providers", []),
                            key=lambda x: x.get("priority", 99)):
            if not pconf.get("enabled", True):
                continue
            cls = TTS_PROVIDER_CLASSES.get(pconf["name"])
            if cls:
                self._providers.append(cls(pconf))

        self._word_config = self.config.get("word_timestamp", {})

    # ─── Public API ─────────────────────────────────────

    def synthesize(self, text: str, voice: str = None,
                   speed: float = None) -> TTSResult:
        """Synthesize single text segment. Auto-fallback through providers."""
        used_voice = voice or self.default_voice
        used_speed = speed if speed is not None else self.default_speed

        last_error = ""
        for provider in self._providers:
            if not provider.is_available():
                continue
            try:
                result = provider.synthesize(
                    text=text, voice=used_voice, speed=used_speed)
                return result
            except Exception as e:
                last_error = str(e)
                continue

        raise RuntimeError(
            f"All TTS providers exhausted. Last error: {last_error}"
        )

    def synthesize_segments(self, segments: list[dict],
                           voice: str = None, speed: float = None,
                           output_dir: str = None) -> TTSCompiled:
        """Synthesize multiple segments and stitch into final audio + SRT.

        Args:
            segments: [{"shot": 1, "text": "口播文案"}, ...]
            voice: Voice name (provider-specific)
            speed: Speed multiplier
            output_dir: Output directory

        Returns:
            TTSCompiled with final audio_path, srt_path, word timestamps
        """
        out_dir = Path(output_dir or tempfile.mkdtemp(prefix="tts_compiled_"))
        out_dir.mkdir(parents=True, exist_ok=True)

        # Synthesize each segment
        tts_segments = []
        for seg in segments:
            text = seg.get("text", seg.get("audio", ""))
            if not text.strip():
                continue

            result = self.synthesize(text=text, voice=voice, speed=speed)
            tts_segments.append(TTSSegment(
                shot=seg.get("shot", len(tts_segments)),
                text=text,
                audio_path=result.audio_path,
                duration_s=result.duration_s,
                word_timestamps=result.word_timestamps,
            ))

        # Stitch audio with pauses
        stitched_path = self._stitch_with_pauses(tts_segments, out_dir)
        srt_path = self._build_srt(tts_segments, out_dir)
        total = sum(s.duration_s for s in tts_segments) + \
                self.pause_s * max(0, len(tts_segments) - 1)

        return TTSCompiled(
            audio_path=str(stitched_path),
            srt_path=str(srt_path),
            segments=tts_segments,
            total_duration_s=total,
        )

    def _stitch_with_pauses(self, segments: list[TTSSegment],
                            out_dir: Path) -> Path:
        """Concatenate segment MP3s with pauses."""
        concat_file = out_dir / "concat.txt"
        silence_path = None

        with open(concat_file, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments):
                abs_path = os.path.abspath(seg.audio_path).replace("\\", "/")
                f.write(f"file '{abs_path}'\n")
                if i < len(segments) - 1 and self.pause_s > 0:
                    if silence_path is None:
                        silence_path = out_dir / "_silence.mp3"
                        _make_silence_mp3(str(silence_path), self.pause_s)
                    abs_silence = os.path.abspath(str(silence_path)).replace("\\", "/")
                    f.write(f"file '{abs_silence}'\n")

        output = out_dir / "narration.mp3"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy", str(output),
            ], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            # Fallback: copy first segment
            if segments:
                import shutil
                shutil.copy2(segments[0].audio_path, str(output))
        except FileNotFoundError:
            if segments:
                import shutil
                shutil.copy2(segments[0].audio_path, str(output))

        return output

    def _build_srt(self, segments: list[TTSSegment], out_dir: Path) -> Path:
        """Generate SRT from segment timings."""
        srt_path = out_dir / "subtitles.srt"
        lines = []
        cursor = 0.0

        for i, seg in enumerate(segments):
            start = cursor
            end = cursor + seg.duration_s
            lines.append(f"{i + 1}")
            lines.append(f"{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}")
            lines.append(seg.text)
            lines.append("")
            cursor = end + self.pause_s

        srt_path.write_text("\n".join(lines), encoding="utf-8")
        return srt_path

    def get_available_provider(self) -> Optional[str]:
        """Get name of first available provider."""
        for p in self._providers:
            if p.is_available():
                return p.name
        return None

    def get_providers_status(self) -> list[dict]:
        """Return list of provider status dicts for UI display."""
        result = []
        for p in self._providers:
            available = p.is_available()
            result.append({
                "name": p.display_name,
                "display_name": p.display_name,
                "available": available,
                "supports_word_timestamps": p.supports_word_timestamps,
            })
        return result

    def print_status(self):
        """Print provider status table."""
        print("\n  TTS Provider Status:")
        print(f"  {'Provider':<25} {'Available':<12} {'Timestamps'}")
        print(f"  {'-'*25} {'-'*12} {'-'*12}")
        for p in self._providers:
            available = p.is_available()
            status = "[ONLINE]" if available else "[OFFLINE]"
            ts = "YES" if p.supports_word_timestamps else "no"
            print(f"  {p.display_name:<25} {status:<12} {ts}")


# ─── Word Timestamp Estimation ─────────────────────────────

def _estimate_word_timestamps(text: str, total_duration_s: float) -> list[WordTimestamp]:
    """Fallback: estimate word timings from character count.

    Not as precise as CosyVoice's native timestamps, but enables word-level
    subtitle animation for any TTS provider.
    """
    cps = 4.5  # Chinese chars per second (average speech rate)
    words = []
    start = 0.0

    # Split by common boundaries: Chinese chars, English words
    import re
    tokens = re.findall(
        r'[一-鿿]|[a-zA-Z]+|\d+|['
        r'，。！？、；：“”‘’'
        r'（）\s]',
        text
    )

    for token in tokens:
        if token.strip():
            char_count = len(token)
            duration = char_count / cps
            words.append(WordTimestamp(
                word=token,
                start_s=round(start, 3),
                end_s=round(min(start + duration, total_duration_s), 3),
            ))
            start += duration

    return words


# ─── Helpers ───────────────────────────────────────────────

def _get_audio_duration(path: str) -> float:
    """Get audio file duration via ffprobe."""
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 2.0


def _make_silence_mp3(path: str, duration_s: float):
    """Generate a silent MP3 for pauses between segments."""
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=24000",
        "-t", f"{duration_s:.3f}",
        "-c:a", "libmp3lame", "-b:a", "64k",
        path,
    ], check=True)


def _fmt_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─── Singleton ─────────────────────────────────────────────

_tts_dispatcher: Optional[TTSDispatcher] = None


def get_tts_dispatcher(config_path: str = None) -> TTSDispatcher:
    """Get or create the global TTS dispatcher."""
    global _tts_dispatcher
    if _tts_dispatcher is None or config_path:
        _tts_dispatcher = TTSDispatcher(config_path)
    return _tts_dispatcher
