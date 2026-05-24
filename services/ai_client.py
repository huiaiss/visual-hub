import base64
import io
import time
import requests
from PIL import Image
from openai import OpenAI
from config import Config


# Doubao Vision max pixels: 36M. Resize to stay safely under.
_MAX_PIXELS = 30_000_000  # ~5477x5477
_MAX_DIMENSION = 5120  # don't let any side exceed this


def _resize_image_if_needed(image_path: str) -> bytes:
    """Resize image to fit Doubao Vision pixel limit, return PNG bytes."""
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    pixels = w * h
    if pixels <= _MAX_PIXELS and w <= _MAX_DIMENSION and h <= _MAX_DIMENSION:
        # Already within limits, return original bytes
        with open(image_path, "rb") as f:
            return f.read()

    # Calculate new dimensions
    scale = min((_MAX_PIXELS / pixels) ** 0.5, _MAX_DIMENSION / max(w, h), 1.0)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()


def _get_doubao_client():
    return OpenAI(api_key=Config.DOUBAO_API_KEY, base_url=Config.DOUBAO_BASE_URL)


def _get_dashscope_client():
    return OpenAI(api_key=Config.DASHSCOPE_API_KEY, base_url=Config.DASHSCOPE_BASE_URL)


def _get_client():
    return OpenAI(api_key=Config.DEEPSEEK_API_KEY, base_url=Config.DEEPSEEK_BASE_URL)


# ---- Image Generation (Seedream 5.0) ----

def generate_image(prompt: str, size: str = "2K", n: int = 1) -> list[str]:
    """调用 Seedream 5.0 生成图片，返回 URL 列表。

    size: 预设档位 "2K" / "3K"，或精确像素 "1440x2560" (至少 3686400px)
    """
    client = _get_doubao_client()
    if not client:
        raise RuntimeError("豆包 API 未配置")
    resp = client.images.generate(
        model=Config.DOUBAO_IMAGE_MODEL,
        prompt=prompt,
        size=size,
        response_format="url",
        n=n,
        extra_body={"watermark": False},
    )
    return [d.url for d in resp.data]


# ---- Video Generation (Seedance 2.0) ----

def _doubao_headers() -> dict:
    return {
        "Authorization": f"Bearer {Config.DOUBAO_API_KEY}",
        "Content-Type": "application/json",
    }


def submit_video_task(
    prompt: str,
    duration: int = 5,
    resolution: str = "1080p",
    aspect_ratio: str = "9:16",
    fast: bool = False,
) -> str:
    """提交视频生成任务，返回 task_id。

    duration: 5 或 10 秒
    resolution: 480p / 720p / 1080p
    aspect_ratio: 16:9 / 9:16 / 1:1
    fast: True 用快速版模型
    """
    model = Config.DOUBAO_VIDEO_FAST_MODEL if fast else Config.DOUBAO_VIDEO_MODEL
    url = f"{Config.DOUBAO_BASE_URL}/contents/generations/tasks"
    body = {
        "model": model,
        "content": [
            {"type": "text", "text": prompt}
        ],
        "parameters": {
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        },
    }
    resp = requests.post(url, headers=_doubao_headers(), json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    task_id = data.get("id") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"提交视频任务失败: {data}")
    return task_id


def get_video_task(task_id: str) -> dict:
    """查询视频任务状态，返回完整 response JSON"""
    url = f"{Config.DOUBAO_BASE_URL}/contents/generations/tasks/{task_id}"
    resp = requests.get(url, headers=_doubao_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def generate_video(
    prompt: str,
    duration: int = 5,
    resolution: str = "1080p",
    aspect_ratio: str = "9:16",
    fast: bool = False,
    poll_interval: int = 10,
    max_wait: int = 600,
) -> list[str]:
    """提交视频生成任务并轮询直到完成，返回视频 URL 列表。

    poll_interval: 轮询间隔秒数
    max_wait: 最大等待秒数
    """
    task_id = submit_video_task(
        prompt=prompt,
        duration=duration,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        fast=fast,
    )
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        task = get_video_task(task_id)
        status = task.get("status", "")
        if status == "completed":
            videos = []
            for item in task.get("content", []):
                if item.get("type") == "video":
                    video_url = item.get("video_url") or item.get("url")
                    if video_url:
                        videos.append(video_url)
            if not videos:
                raise RuntimeError(f"视频任务完成但无视频输出: {task}")
            return videos
        elif status == "failed":
            raise RuntimeError(f"视频生成失败: {task.get('error', task)}")
        elif status in ("pending", "processing", "queued"):
            continue
        else:
            raise RuntimeError(f"未知任务状态: {status}")
    raise TimeoutError(f"视频生成超时 ({max_wait}s)，task_id={task_id}")


def _image_to_data_url(image_path: str) -> str:
    image_bytes = _resize_image_if_needed(image_path)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"
