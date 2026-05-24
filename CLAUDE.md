# FrameCraft 帧导 — 工厂AI电商内容引擎

> 🔍 Hermes 审计时间：2026-05-24 23:06
> 定位：电商带货视频（鞋类/消费品），与 auto-video-platform（企业宣传）独立

## ⚠️ 当前架构问题

### P0 — Git 未初始化
项目 21 个 .py 文件、6,449 行代码，零版本控制。

### P0 — 零测试
tests/ 目录只有空的 __init__.py。

### P0 — pipeline_bridge.py 是错误架构
30KB 的桥代码把 visual-hub 连到了 auto-video-platform。
两个项目定位不同（电商 vs 企业宣传），不应该有依赖。
→ 需要移除 pipeline_bridge，帧导自建视频渲染。

### P1 — 旧 API 未清理
director.py（16KB）标了"旧版"，但还在 main.py 里注册。
两个 API 并存，维护成本翻倍。

### P1 — 5 个服务文件超过 25KB
prompt_engine.py(33KB) / creative_api.py(33KB) / pipeline_bridge.py(30KB)
gatekeeper.py(29KB) / script_knowledge.py(28KB)
→ 功能堆在一起，改一处容易牵动全局。

### P1 — 输出数据未清理
data/ 目录数百张生成图片，未区分测试/生产。

---

## 📋 本次会话任务（按顺序执行）

### 任务 1：Git 初始化
```bash
git init && git add -A && git commit -m "帧导初始版本：电商AI内容引擎"
```

### 任务 2：移除 pipeline_bridge.py
1. 确认哪些文件引用了 `pipeline_bridge`
2. 去掉 `main.py` 和 `creative_api.py` 中的 bridge 调用
3. 帧导不依赖 auto-video-platform，自建轻量视频渲染（用现有的 Chromium 方案）
4. 删掉 `services/pipeline_bridge.py`

### 任务 3：清理旧 API
1. 从 `main.py` 中移除 `director.py` 的路由注册
2. 确认 `director.html` 模板不被引用后删除
3. 删掉 `api/director.py`

### 任务 4：创建 tests/
至少 3 个测试文件，每个至少 1 个 assert：
- `tests/test_creative_engine.py` — 产品分析返回合法 JSON
- `tests/test_gatekeeper.py` — QA 评分在 0-100 范围
- `tests/test_api.py` — FastAPI 端点返回 200

### 完成后
Hermes 会验证并更新本文件审计状态。

---


## 项目定位
两产品架构：**一键出图**（Image Factory）+ **帧导短视频**（Video Factory），面向开山网女鞋工厂，也适用于全品类。
- 上传产品图 → AI 分析产品属性 → 生成创意大纲 → 场景合成 → 多平台套图 + 拍摄脚本

## 技术栈
- 后端：FastAPI (Python 3.14) + Jinja2 模板
- 前端：Alpine.js 3.14 + TailwindCSS CDN
- AI：豆包 Vision Pro（产品分析）+ DeepSeek Chat（创意大纲/脚本）+ 阿里云 DashScope
- 数据库：SQLite + Peewee ORM（`data/app.db`）
- 视频管线：自建 Chromium 渲染（不再依赖 auto-video-platform）
- 运行端口：8000

## 当前项目结构
```
visual-hub/
├── main.py                 # FastAPI 入口，路由注册，启动事件
├── config.py               # API Key、路径等配置
├── requirements.txt
├── api/
│   ├── director.py          # 旧版导演 API（/director 页面后端）
│   └── creative_api.py      # ★ 新版创意 API（analyze/batch-generate/export-video）
├── services/
│   ├── ai_client.py         # AI 客户端工厂（豆包/DeepSeek/DashScope）
│   ├── creative_engine.py   # 产品分析 + 创意大纲生成
│   ├── gatekeeper.py        # 拍摄方案 QA 质检（评分/通过/拒绝）
│   ├── json_repair.py       # 截断 JSON 修复
│   ├── pipeline_bridge.py   # ★ visual-hub ↔ auto-video-platform 桥接层
│   ├── plan_service.py      # 拍摄方案生成服务
│   ├── product_classifier.py# 产品快速分类（本地特征分析）
│   ├── prompt_engine.py     # Prompt 模板引擎
│   ├── scene_generator.py   # 创意驱动场景图生成
│   ├── script_knowledge.py  # 脚本知识库（BGM/钩子/情绪弧/拍摄层级）
│   └── task_manager.py      # 异步任务进度管理
├── web/templates/
│   ├── base.html
│   ├── factory.html         # ★ 一键出图页面（4 步流程）
│   ├── director.html        # 旧版导演页面
│   ├── direct_gen.html      # 方案生成页面
│   └── creative.html        # 创意工作室页面
├── web/static/              # CSS/JS/图标/PWA
├── db/
│   ├── models.py            # Peewee ORM 模型（CreativeBrief, BatchJob, GeneratedPlan）
│   └── migrations.py        # 数据库迁移
└── data/                    # SQLite + 上传 + 输出（不提交）
```

## 关键数据流
```
产品图 → creative_engine.analyze_product() → product_analysis
       → creative_engine.generate_creative_brief() → creative_brief
       → plan_service.generate_plans() → plans[]
       → scene_generator 生成场景图
       → 自建视频渲染引擎 → MP4
```

## 数据库核心表
- `CreativeBrief`: brief_id(VARCHAR PK), product_analysis(JSON), creative_brief(JSON), scene_images, status
- `BatchJob`: job_id(VARCHAR PK), brief(FK), status, progress, output_files
- `GeneratedPlan`: 旧版方案存储

## Peewee 陷阱
- `Model.get_by_id()` 只认 INTEGER `id` 列，不认 VARCHAR PK
- 查 VARCHAR 主键用 `Model.get(Model.field == value)`

## 用户信息
- 台州隆江自动化设备（无刷电机绕线机工厂）+ 自主鞋品牌 XINYUE（凯妮芬）
- 编程经验：零基础，需要通俗解释
- 目标：将产品做成商业 SaaS 上线运营

## 关键惯例

### 定期瘦身（所有 Claude 实例必须执行）
**每完成一个大功能模块后，主动执行以下检查：**
```bash
# 1. 找零引用的 Python 文件
grep -rn "^from|^import" --include="*.py" api/ services/ | \
  awk -F: '{print $NF}' | sort -u > /tmp/imported.txt
find . -name "*.py" ! -path "*__pycache__*" | sort > /tmp/all_py.txt
# 手动对比两者，找出未被 import 的文件

# 2. 找零引用模板/静态文件
grep -rn "模板文件名" --include="*.py" main.py
```
- 删除前确认：没有任何文件 import 它
- 删完验证：`python main.py` 能正常启动 + `curl` 三个页面全部 200
- 不删：config.py、数据库文件、__init__.py、tests/

### 其他惯例
- 做事严谨：引用编号必须和清单一致
- 提交前必须先自审复核
- 做完页面/视频必须自动打开预览
- 做方案前先盘点现有资源

---

## Hermes 协作模式（铁律）

### 角色分工
- **Claude Code** = 主力程序员
- **Hermes** = 项目记忆 + 架构监理
  
### 调度 Hermes
```bash
hermes chat -q "审计 visual-hub/services/，报告模块耦合度"
hermes chat -q "检查 director.py 引用，确认是否可以安全删除"
```

### 当前审计状态
见本文件顶部 Hermes 审计报告。每次 Claude 会话开始先读审计报告。
