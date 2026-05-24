"""AI Shooting Director — upload product images → get complete shooting plans."""
import asyncio
import json
import logging
import os
import uuid
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from config import Config
from services.prompt_engine import CATEGORY_CONFIGS, SCRIPT_TYPES
from services.plan_service import generate_plans, generate_plans_with_progress, auto_describe
from services.creative_engine import analyze_product as creative_analyze, analyze_product_ensemble, generate_creative_brief, build_creative_context
from services.product_classifier import quick_scan
from services.task_manager import task_manager
from db.models import GeneratedPlan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/director", tags=["director"])


# ============ HELPERS ============

def _save_upload(f: UploadFile) -> str:
    """Save a single uploaded file and return the path."""
    contents = f.file.read()
    ext = os.path.splitext(f.filename or "product.jpg")[1] or ".jpg"
    filename = f"director_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(Config.UPLOADS_DIR, filename)
    with open(path, "wb") as wf:
        wf.write(contents)
    return path


def _validate_analyze_input(files, industry, script_type, variant_count):
    """Validate input for the analyze endpoint."""
    if not files or all(not f.filename for f in files):
        raise HTTPException(400, "请上传产品图")
    if len(files) < 3:
        raise HTTPException(400, "请至少上传3张图片（正面/背面/侧面必填，细节和场景选填），多角度实拍识别更准。建议按页面角度指引上传5张")
    if len(files) > 5:
        raise HTTPException(400, "最多上传5张图片")
    if variant_count < 1 or variant_count > 5:
        raise HTTPException(400, "variant_count 仅支持 1-5")
    if script_type not in SCRIPT_TYPES:
        raise HTTPException(400, "script_type 仅支持 with_cart 或 without_cart")

    for f in files:
        if f.content_type and f.content_type not in ("image/jpeg", "image/png", "image/webp", "image/jpg"):
            raise HTTPException(400, f"仅支持 JPG/PNG/WebP 格式，不支持: {f.content_type}")

    # Reset file positions after validation
    for f in files:
        f.file.seek(0)


def _check_total_size(files) -> None:
    """Check cumulative upload size against limit."""
    total = sum(len(f.file.read()) for f in files)
    if total > Config.MAX_UPLOAD_SIZE * len(files):
        raise HTTPException(413, "文件总大小过大，请压缩后上传")
    for f in files:
        f.file.seek(0)


# ============ ENDPOINTS ============

@router.post("/analyze")
async def analyze_product(
    files: list[UploadFile] = File(...),
    industry: str = Form("鞋类"),
    extra_info: str = Form(""),
    script_type: str = Form("with_cart"),
    variant_count: int = Form(1),
):
    """Upload 3-5 product images, get 1-5 AI shooting plan variants."""
    _validate_analyze_input(files, industry, script_type, variant_count)
    _check_total_size(files)

    # Save images
    image_paths = [_save_upload(f) for f in files]

    try:
        # Stage 0: Fast local pre-screening (YOLOv11 color/category)
        local_scan = quick_scan(image_paths)

        # Stage 1: Structured product analysis (Doubao Vision → JSON, + Qwen-VL ensemble if available)
        try:
            product_analysis = analyze_product_ensemble(image_paths, industry)
        except Exception:
            product_analysis = creative_analyze(image_paths, industry)

        # Merge local scan results as supplementary data
        if not product_analysis.get("parse_error") and local_scan.get("dominant_colors") and not product_analysis.get("colors"):
            product_analysis["colors"] = [{"name": c["name"], "hex_guess": c["hex"]} for c in local_scan["dominant_colors"][:3]]
        product_analysis["_local_scan"] = local_scan

        # Stage 2: Creative brief generation (DeepSeek → JSON)
        creative_brief = generate_creative_brief(product_analysis, industry, extra_info)

        # Stage 3: Build enriched context for plan generation
        creative_context = build_creative_context(product_analysis, creative_brief)

        # Fetch top reference for data flywheel
        reference = _get_top_reference(industry, script_type)

        # Generate plan variants with enriched creative context
        result = generate_plans(creative_context, extra_info, industry, script_type, variant_count, reference)

        # Persist
        plan_id = None
        try:
            record = GeneratedPlan.create(
                industry=industry,
                script_type=script_type,
                product_analysis=json.dumps(product_analysis, ensure_ascii=False),
                creative_brief=json.dumps(creative_brief, ensure_ascii=False),
                extra_info=extra_info,
                image_paths=json.dumps(image_paths),
                variant_count=result["variant_count"],
                plans_json=json.dumps(result["plans"], ensure_ascii=False),
            )
            plan_id = record.plan_id
        except Exception as e:
            logger.warning(f"Failed to persist plan: {e}")

        return {
            "plan_id": plan_id,
            "product_analysis": product_analysis,
            "creative_brief": creative_brief,
            "plans": result["plans"],
            "script_type": script_type,
            "variant_count": result["variant_count"],
            "image_paths": image_paths,
            "errors": result["errors"],
        }
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/auto-describe")
async def auto_describe_product(
    files: list[UploadFile] = File(...),
    industry: str = Form("鞋类"),
    extra_info: str = Form(""),
):
    """AI帮写：根据上传图片自动生成产品补充说明"""
    if not files or all(not f.filename for f in files):
        raise HTTPException(400, "请上传产品图")
    if len(files) < 3:
        raise HTTPException(400, "请至少上传3张图片（正面/背面/侧面必填，细节和场景选填），多角度实拍识别更准。建议按页面角度指引上传5张")
    if len(files) > 5:
        raise HTTPException(400, "最多上传5张图片")

    _check_total_size(files)
    image_paths = [_save_upload(f) for f in files]

    try:
        result = auto_describe(image_paths, industry, extra_info)
        return {"description": result}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/analyze-async")
async def analyze_async(
    files: list[UploadFile] = File(...),
    industry: str = Form("鞋类"),
    extra_info: str = Form(""),
    script_type: str = Form("with_cart"),
    variant_count: int = Form(1),
):
    """Async version: returns task_id immediately, progress via WebSocket."""
    _validate_analyze_input(files, industry, script_type, variant_count)
    _check_total_size(files)

    image_paths = [_save_upload(f) for f in files]
    task = task_manager.create()

    # Launch background pipeline
    asyncio.create_task(_run_async_pipeline(
        task.task_id, image_paths, industry, extra_info, script_type, variant_count
    ))

    return {"task_id": task.task_id, "status": "pending"}


async def _run_async_pipeline(
    task_id: str,
    image_paths: list[str],
    industry: str,
    extra_info: str,
    script_type: str,
    variant_count: int,
):
    """Background pipeline: vision → generate → persist, with progress updates."""
    loop = asyncio.get_event_loop()

    try:
        # Stage 0: Fast local pre-screening
        local_scan = await loop.run_in_executor(None, quick_scan, image_paths)

        # Stage 1: Ensemble vision analysis (Doubao + Qwen-VL)
        task_manager.update(task_id, status="analyzing", progress=5, message="正在双模型并行分析产品图片...")
        product_analysis = await loop.run_in_executor(None, analyze_product_ensemble, image_paths, industry)
        if not product_analysis.get("parse_error") and local_scan.get("dominant_colors") and not product_analysis.get("colors"):
            product_analysis["colors"] = [{"name": c["name"], "hex_guess": c["hex"]} for c in local_scan["dominant_colors"][:3]]
        product_analysis["_local_scan"] = local_scan
        task_manager.update(task_id, status="analyzing", progress=15, message="产品双模型分析完成，正在生成创意方案...")

        # Stage 2: Creative brief generation (DeepSeek)
        creative_brief = await loop.run_in_executor(
            None, generate_creative_brief, product_analysis, industry, extra_info
        )
        task_manager.update(task_id, status="generating", progress=20, message="创意方案完成，正在检索高分参考...")

        # Stage 3: Build enriched context
        creative_context = build_creative_context(product_analysis, creative_brief)

        reference = await loop.run_in_executor(
            None,
            lambda: _get_top_reference(industry, script_type),
        )

        def on_progress(event):
            if event["type"] == "variant_started":
                pct = 25 + int(65 * (event["variant"] - 1) / variant_count)
                task_manager.update(task_id, progress=pct, message=f"正在生成第 {event['variant']}/{variant_count} 套方案...")
            elif event["type"] == "variant_complete":
                pct = 25 + int(65 * event["variant"] / variant_count)
                task_manager.push_event(task_id, {
                    "variant": event["variant"],
                    "total": variant_count,
                    "plan": event["plan"],
                })

        result = await loop.run_in_executor(
            None,
            lambda: generate_plans_with_progress(
                creative_context, extra_info, industry, script_type, variant_count, on_progress, reference
            ),
        )
        task_manager.update(task_id, progress=90, message="正在保存方案...")

        # Persist
        record = await loop.run_in_executor(
            None,
            lambda: GeneratedPlan.create(
                industry=industry,
                script_type=script_type,
                product_analysis=json.dumps(product_analysis, ensure_ascii=False),
                creative_brief=json.dumps(creative_brief, ensure_ascii=False),
                extra_info=extra_info,
                image_paths=json.dumps(image_paths),
                variant_count=result["variant_count"],
                plans_json=json.dumps(result["plans"], ensure_ascii=False),
            ),
        )

        task_manager.complete(task_id, {
            "plan_id": record.plan_id,
            "product_analysis": product_analysis,
            "creative_brief": creative_brief,
            "plans": result["plans"],
            "script_type": script_type,
            "variant_count": result["variant_count"],
            "image_paths": image_paths,
            "errors": result["errors"],
        })

    except Exception as e:
        logger.exception(f"Async pipeline {task_id} failed")
        task_manager.fail(task_id, str(e))


@router.websocket("/ws/{task_id}")
async def ws_progress(websocket: WebSocket, task_id: str):
    """WebSocket for real-time progress on an async task."""
    await websocket.accept()
    q = await task_manager.subscribe(task_id)
    try:
        while True:
            data = await q.get()
            await websocket.send_json(data)
            if data.get("status") in ("complete", "failed"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        task_manager.unsubscribe(task_id, q)


@router.get("/plans")
async def list_plans(limit: int = 20, offset: int = 0):
    """List recent generated plans (summary only, no full JSON)."""
    rows = (
        GeneratedPlan.select()
        .order_by(GeneratedPlan.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
    )
    results = []
    for r in rows:
        # Parse structured analysis for readable summary
        try:
            analysis = json.loads(r.product_analysis) if isinstance(r.product_analysis, str) else {}
            summary = " / ".join(filter(None, [
                analysis.get("category", ""),
                analysis.get("sub_category", ""),
                " ".join(analysis.get("style_keywords", [])),
            ])) or r.product_analysis[:80]
        except (json.JSONDecodeError, TypeError):
            summary = str(r.product_analysis)[:80]

        # Parse brief for concept name
        concept_name = ""
        try:
            brief = json.loads(r.creative_brief) if r.creative_brief and isinstance(r.creative_brief, str) else {}
            concept_name = brief.get("concept_name", "")
        except (json.JSONDecodeError, TypeError):
            pass

        results.append({
            "plan_id": r.plan_id,
            "industry": r.industry,
            "script_type": r.script_type,
            "product_analysis": summary,
            "concept_name": concept_name,
            "variant_count": r.variant_count,
            "rating": r.rating,
            "performance_note": r.performance_note,
            "created_at": r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else str(r.created_at),
        })
    return {"plans": results}


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str):
    """Get a single plan with full JSON data."""
    row = GeneratedPlan.get_or_none(GeneratedPlan.plan_id == plan_id)
    if not row:
        raise HTTPException(404, "方案不存在")
    # Parse stored JSON fields
    try:
        analysis = json.loads(row.product_analysis) if isinstance(row.product_analysis, str) else row.product_analysis
    except (json.JSONDecodeError, TypeError):
        analysis = row.product_analysis
    try:
        brief = json.loads(row.creative_brief) if row.creative_brief and isinstance(row.creative_brief, str) else {}
    except (json.JSONDecodeError, TypeError):
        brief = {}
    return {
        "plan_id": row.plan_id,
        "industry": row.industry,
        "script_type": row.script_type,
        "product_analysis": analysis,
        "creative_brief": brief,
        "extra_info": row.extra_info,
        "image_paths": json.loads(row.image_paths),
        "variant_count": row.variant_count,
        "plans": json.loads(row.plans_json),
        "rating": row.rating,
        "performance_note": row.performance_note,
        "created_at": row.created_at.isoformat() if hasattr(row.created_at, 'isoformat') else str(row.created_at),
    }


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str):
    """Delete a plan by ID."""
    row = GeneratedPlan.get_or_none(GeneratedPlan.plan_id == plan_id)
    if not row:
        raise HTTPException(404, "方案不存在")
    row.delete_instance()
    return {"ok": True}


@router.post("/plans/{plan_id}/rate")
async def rate_plan(plan_id: str, rating: int = 1, note: str = ""):
    """Rate a plan: 1=好 0=一般 -1=差. This feeds the data flywheel."""
    if rating not in (-1, 0, 1):
        raise HTTPException(400, "rating 仅支持 -1/0/1")
    row = GeneratedPlan.get_or_none(GeneratedPlan.plan_id == plan_id)
    if not row:
        raise HTTPException(404, "方案不存在")
    row.rating = rating
    row.performance_note = note
    row.save()
    return {"ok": True, "plan_id": plan_id, "rating": rating}


def _get_top_reference(industry: str, script_type: str) -> dict | None:
    """Get highest-rated plan for the same industry/script_type to inject as reference."""
    row = (
        GeneratedPlan.select()
        .where(
            (GeneratedPlan.industry == industry)
            & (GeneratedPlan.script_type == script_type)
            & (GeneratedPlan.rating == 1)
        )
        .order_by(GeneratedPlan.created_at.desc())
        .first()
    )
    if not row:
        return None
    try:
        plans = json.loads(row.plans_json)
        # Parse structured analysis for readable summary
        try:
            analysis = json.loads(row.product_analysis) if isinstance(row.product_analysis, str) else row.product_analysis
            summary = " / ".join(filter(None, [
                analysis.get("category", ""),
                analysis.get("sub_category", ""),
                " ".join(analysis.get("style_keywords", [])),
            ]))
        except (json.JSONDecodeError, TypeError, AttributeError):
            summary = str(row.product_analysis)[:120]
        return {
            "product_analysis": summary,
            "top_plan": plans[0] if plans else {},
            "extra_info": row.extra_info,
        }
    except Exception:
        return None
