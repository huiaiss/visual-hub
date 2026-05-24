import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

ROOT_DIR = Path(__file__).parent


class Config:
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    # 豆包/火山引擎视觉 API (https://console.volcengine.com/ark)
    DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
    DOUBAO_BASE_URL = os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    DOUBAO_VISION_MODEL = os.getenv("DOUBAO_VISION_MODEL", "doubao-seed-1-6-vision-250815")
    DOUBAO_IMAGE_MODEL = os.getenv("DOUBAO_IMAGE_MODEL", "doubao-seedream-5-0-260128")
    DOUBAO_VIDEO_MODEL = os.getenv("DOUBAO_VIDEO_MODEL", "doubao-seedance-2-0-260128")
    DOUBAO_VIDEO_FAST_MODEL = os.getenv("DOUBAO_VIDEO_FAST_MODEL", "doubao-seedance-2-0-fast-260128")

    # 阿里 DashScope API (https://dashscope.console.aliyun.com)
    # Qwen-VL-Max: 国内最强VLM，达GPT-4o 98.3%精度，用作第二视觉引擎
    # Qwen3-VL-Flash: 轻量视觉模型，快速属性提取
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    QWEN_VL_MODEL = os.getenv("QWEN_VL_MODEL", "qwen-vl-max")
    QWEN_VL_FAST_MODEL = os.getenv("QWEN_VL_FAST_MODEL", "qwen-vl-plus")
    QWEN_TEXT_MODEL = os.getenv("QWEN_TEXT_MODEL", "qwen3-235b-a22b-instruct-2507")

    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    API_KEY = os.getenv("API_KEY", "")

    DATABASE_PATH = str(ROOT_DIR / "data" / "app.db")
    DATA_DIR = str(ROOT_DIR / "data")
    UPLOADS_DIR = str(ROOT_DIR / "data" / "uploads")
    PROCESSED_DIR = str(ROOT_DIR / "data" / "processed")
    SCENES_DIR = str(ROOT_DIR / "data" / "scenes")
    VIDEOS_DIR = str(ROOT_DIR / "data" / "videos")

    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
    JPEG_QUALITY = 92
