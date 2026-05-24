# FrameCraft 帧导 — 工厂AI电商内容引擎

> 🔍 Hermes 审计时间：2026-05-25 00:08
> 定位：电商带货视频（鞋类/消费品），与 auto-video-platform 独立

## ✅ 已完成

| 轮次 | 任务 | 成果 |
|------|------|------|
| 第 1 轮 | 数据与代码分离 | 5YAML, script_knowledge 476→44行 |
| 第 1 轮 | Git init + 测试 | 3文件 19 assert |
| 第 2 轮 | 搬渲染引擎 | 5文件→services/rendering/ |
| — | pipeline_bridge 删除 | ✅ 已删除 |
| — | director.py+html 删除 | ✅ 已删除 |

## ⚠️ 剩余问题（依赖分析）

| 问题 | 位置 | 详情 |
|------|------|------|
| `/director` 死路由 | main.py L110 | 模板已删，路由还挂着，访问 404 |
| brand_loader 依赖 | asset_pipeline.py L25 | `_brand_name()` 调 AVP 的 config.brand_loader |
| AssemblyEngine 依赖 | video_renderer.py L335 | 唯一剩余 AVP 依赖，from builders.assembly_engine |
| Git 未提交 | — | 第 2 轮 + 上述删除未 commit |

## 📋 第 3 轮任务

### 任务 1：Git commit（立即）
```bash
git add -A && git commit -m "第2轮: 渲染引擎独立 + 移除pipeline_bridge/director旧代码"
```

### 任务 2：清理 `/director` 死路由
| 规则 | 检查 |
|------|------|
| 规则1 | main.py L110-120 仅引用 director.html（已删），无其他依赖 |
| 规则2 | 不改目录，无需核算 |
| 规则3 | 无导入变更 |
| 规则4 | 诚实：仅删路由，不涉及其他 |

删除 main.py 中：
- `@app.get("/director")` 路由函数
- `async def director_page(...)` 

### 任务 3：移除 asset_pipeline.py 的 brand_loader
| 规则 | 检查 |
|------|------|
| 规则1 | `_brand_name()`(L23-26) → `get_brand_name()`(L25) → 用于水印文字(L243-244) |
| 规则2 | 文件已在 services/rendering/（深度3），不再变 |
| 规则3 | 不涉及导入路径变更 |
| 规则4 | 诚实：仅去掉 brand_loader import，水印改为参数传入 |
| 规则5 | 单文件改动，不涉及共享包 |

改法：
- `_brand_name()` 删除，L243 改为 `brand = brand_name or "AI电商"`
- `AssetPipeline.__init__` 加参数 `brand_name: str = None`

### 任务 4：替换 AssemblyEngine（最大任务）
| 规则 | 检查 |
|------|------|
| 规则1 | video_renderer.py L335-352 使用 AssemblyEngine。需分析 AssemblyEngine 做了什么 |
| 规则4 | 诚实：这是 AVP 最后残留，完成后帧导完全独立 |

做法：
1. 分析 `auto-video-platform/builders/assembly_engine.py` 的接口
2. 帧导已有 `components_ecommerce.py`(31KB)，包含电商组件
3. 在 `services/video_renderer.py` 中用一个轻量级函数替代 AssemblyEngine：
   - 输入：Script + assets + output_dir
   - 输出：index.html
   - 复用 components_ecommerce.py 的组件渲染

---

## 项目定位
电商带货视频引擎。上传产品图 → AI分析 → 创意大纲 → 场景合成 → 出图+出视频

## 技术栈
FastAPI :8000 / 豆包Vision+DeepSeek+DashScope / SQLite+Peewee / 自建渲染

## Peewee 陷阱
VARCHAR PK 用 `Model.get(Model.field == value)`，别用 get_by_id()

## Hermes 协作
Claude=程序员, Hermes=监理。调度: `hermes chat -q "任务"`
