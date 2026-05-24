# FrameCraft 帧导 — AI 电商视频内容引擎

> 一句话：上传产品图 → AI 分析 → 生成拍摄方案 → 合成带货视频 MP4
> 独立状态：零 AVP 依赖 | commit `7d02975` | 2026-05-25

## 技术栈

| 层 | 技术 |
|----|------|
| Web 框架 | FastAPI + Jinja2 + Alpine.js + TailwindCSS |
| 数据库 | SQLite (Peewee ORM, WAL 模式) |
| AI 视觉 | Doubao Vision + Qwen-VL-Max 双模型并行 |
| AI 文本 | DeepSeek (deepseek-v4-flash) |
| TTS 语音 | edge-tts (免费, zh-CN-YunxiNeural)，多供应商自动降级 |
| 图像处理 | Pillow + rembg + OpenCV + YOLOv11 本地分类 |
| 视频渲染 | Playwright (Chromium headless) → GSAP HTML → ffmpeg → MP4 |
| 场景生成 | 12 种程序化 archetype (Pillow, 无需 GPU/API) |

## 启动

```bash
cd C:\Users\Administrator\visual-hub
python main.py              # :8000，首次启动自动初始化 DB + 迁移
python tests/test_e2e_video.py  # 端到端视频渲染测试
```

关键环境变量（`.env`）：`DEEPSEEK_API_KEY`, `DOUBAO_API_KEY`, `DASHSCOPE_API_KEY`, `API_KEY`

## 目录结构

```
visual-hub/
├── main.py                  # FastAPI 入口，AuthMiddleware，页面路由
├── config.py                # Config 类，所有路径/模型名/Key
├── requirements.txt
├── yolo11n-cls.pt           # YOLOv11 本地分类模型 (1.3MB)
│
├── config/prompts/          # YAML 知识库（改 prompt 不改代码）
│   ├── vision_prompts.yaml      # 视觉分析维度、品类配置
│   ├── plan_prompts.yaml        # 方案生成 prompt 模板
│   ├── hook_blueprints.yaml     # 钩子/标题公式/FABE框架/痛点库
│   ├── script_tiers.yaml        # L1/L2/L3 拍摄级别、踩坑指南
│   └── bgm_knowledge.yaml       # BGM 情绪弧线、卡点规则
│
├── services/                # 核心业务层
│   ├── creative_engine.py       # ① 产品分析（双模并行）+ ② 创意大纲
│   ├── plan_service.py          # ③ 方案生成（多变异+重试+QA排序）
│   ├── gatekeeper.py            # 7维QA：结构/L1口播/L2脚本/场景/视角/合规/钩子
│   ├── scene_generator.py       # ④ 程序化场景：12种archetype，Pillow生成PNG
│   ├── video_renderer.py        # ⑤ 视频导出入口：Plan→Script→TTS→HTML→MP4
│   ├── prompt_engine.py         # Prompt 构建器 + 知识注入
│   ├── script_knowledge.py      # YAML 知识库加载器
│   ├── script_models.py         # Beat/Script 数据类
│   ├── ai_client.py             # API 客户端（Doubao/DeepSeek/DashScope）
│   ├── task_manager.py          # 线程安全异步任务+WebSocket推送
│   ├── product_classifier.py    # YOLOv11 快速预分类 + 色彩聚类
│   ├── json_repair.py           # 修LLM输出的烂JSON
│   ├── quality_standards.py     # 视频质量6维验收(分辨率/时长/文件/节拍/TTS/组件)
│   │
│   └── rendering/           # 视频导出子系统
│       ├── assembler.py         # Script+TTS→GSAP HTML（含电商组件）
│       ├── asset_pipeline.py    # 多源素材匹配+AI生成降级链
│       ├── chromium_renderer.py # Playwright录制+ffmpeg混流→MP4
│       ├── tts_builder.py       # 逐镜头TTS+静音拼接+SRT生成
│       ├── tts_providers.py     # 多供应商策略模式(Edge→CosyVoice→Coqui→OpenAI)
│       ├── subtitle_engine.py   # 动态字幕（逐词/逐字弹出动画）
│       └── static/gsap.min.js   # GSAP 3.x 本地副本(72KB)
│
├── api/
│   └── creative_api.py      # 14 端点：分析/大纲/场景/方案/导出/进度
│
├── db/
│   ├── models.py            # 4表：RegisteredUser/GeneratedPlan/CreativeBrief/BatchJob
│   └── migrations.py        # 5版迁移，init_db() 自动执行
│
├── web/
│   ├── templates/           # 16个Jinja2模板（creative.html 是核心）
│   └── static/              # CSS/JS/PWA
│
├── tests/
│   ├── test_e2e_video.py    # 端到端：方案→TTS→HTML→MP4 + 文件验证
│   ├── test_api.py          # FastAPI TestClient 基础检查
│   ├── test_gatekeeper.py   # QA 门禁单元测试
│   └── test_creative_engine.py
│
└── data/
    ├── app.db               # SQLite (gitignored)
    ├── uploads/             # 用户上传产品图 (~80张)
    ├── scenes/custom/       # 程序化生成的场景背景
    └── videos/              # 渲染输出
```

## 核心流程

```
上传产品图(3-10张)
    │
    ▼
① 产品分析 (creative_engine.py)
   Doubao Vision + Qwen-VL 并行 → 品类/材质/风格/受众
    │
    ▼
② 创意大纲 (creative_engine.py)
   DeepSeek → 概念名/场景描述/配色/模特方向/BGM建议
    │
    ▼
③ 场景生成 (scene_generator.py)
   12种 archetype 关键词匹配 → Pillow 程序化 PNG
    │
    ▼
④ 方案生成 (plan_service.py)
   DeepSeek × N次变异 → gatekeeper 7维QA评分 → 按分数排序
    │
    ▼
⑤ 视频导出 (video_renderer.py)
   plan_to_script → TTS → 素材匹配 → GSAP HTML → Chromium → ffmpeg → MP4
    │
    ▼
⑥ 质量验收 (quality_standards.py)
   6维打分：分辨率/时长/文件/节拍数/TTS/电商组件
```

## 关键约定

### Peewee ORM 陷阱
```python
# ❌ 绝对不要用 get_by_id() — VARCHAR PK 会报错
GeneratedPlan.get_by_id(plan_id)  # BUG

# ✅ 必须用 Model.get()
GeneratedPlan.get(GeneratedPlan.plan_id == plan_id)
```

### 数据库初始化
```python
from db import db, init_db
init_db()            # 建目录 + 迁移
db.init(Config.DATABASE_PATH)
db.connect()
```

### QA Gatekeeper 要求
- 方案必须 ≥7 镜头，含 `shooting_template_card`（7个子字段）
- L1 口播 ≥15字，像朋友说话，**禁止**"颠覆性/重新定义/降维打击"等营销黑话
- L2 口播与 L1 不同且更长，带 FABE 结构
- 拍摄指南必须基于手机（不用专业设备）
- 通过 70 分才会进入渲染管线

### API 认证
- `/api/*` 需要 `X-API-Key` header
- 例外：`/api/health`、`/api/register`
- WebSocket `/api/creative/ws/*` 绕过认证（浏览器无法在 WS 握手设置 header）

### 图片处理
- Doubao 限制：30M 像素 / 5120px → `_resize_image_if_needed()` 自动降采样
- 上传格式：JPG/PNG/WebP only，限 10MB

### 渲染管线
- GSAP 已本地化到 `services/rendering/static/gsap.min.js`，不依赖 CDN
- HTML 中的音频路径是 `audio/narration.mp3`（相对 HTML 所在目录）
- Chromium 渲染用 Edge（`msedge.exe`），fallback → Chrome → Chromium

## 当前状态

| 能力 | 状态 |
|------|------|
| 服务启动 | ✅ `main.py` :8000 |
| AI 分析管道 | ✅ 双视并行+DeepSeek文案 |
| 场景生成 | ✅ 12种程序化场景 |
| 方案生成+QA | ✅ 7维评分+多变异 |
| 端到端视频 | ✅ 首条 MP4 已通过100分验收 |
| 电商组件 | ✅ 价格卡+卖点标签轮播+CTA引导条 |
| 批量导出 | ✅ 异步任务+WebSocket进度 |
| BGM 集成 | ❌ 代码接入了但未实现 |
| Web UI 端到端 | ❌ creative.html 可操作但未全链路调通 |

## 参考输出

- 首条带货视频：`data/videos/e2e_with_components/output.mp4`
  - 48s, 0.6MB, H.264, 1080×1920, 7镜头+电商组件
  - 质量验收：100/100
