"""Creative API — batch product image analysis + scene generation + multi-plan output.

Endpoints:
  POST /api/creative/analyze       — Full pipeline: vision → brief → scenes
  POST /api/creative/batch-generate — Batch: multi-scene × multi-plan
  GET  /api/creative/briefs         — List saved creative briefs
  GET  /api/creative/briefs/{id}    — Get brief detail with scene images
  DELETE /api/creative/briefs/{id}  — Delete brief
  GET  /api/creative/jobs           — List batch jobs
  GET  /api/creative/jobs/{id}      — Job status + output files
  WS   /api/creative/ws/{task_id}   — Real-time progress
"""

import asyncio
import json
import logging
import os
import uuid
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from config import Config
from services.prompt_engine import CATEGORY_CONFIGS, SCRIPT_TYPES
from services.plan_service import generate_plans, generate_plans_with_progress, auto_describe
from services.creative_engine import (
    analyze_product_ensemble, analyze_product as creative_analyze,
    generate_creative_brief, build_creative_context,
)
from services.scene_generator import generate_scenes_from_brief, generate_scene, list_generated_scenes
from services.gatekeeper import review_all
from services.video_renderer import render_video, check_renderer_available
from services.task_manager import task_manager
from db.models import GeneratedPlan, CreativeBrief, BatchJob

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/creative", tags=["creative"])


# ============ HELPERS ============

def _save_upload(f: UploadFile) -> str:
    contents = f.file.read()
    ext = os.path.splitext(f.filename or "product.jpg")[1] or ".jpg"
    filename = f"creative_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(Config.UPLOADS_DIR, filename)
    with open(path, "wb") as wf:
        wf.write(contents)
    return path


def _validate_files(files: list[UploadFile], min_count: int = 3, max_count: int = 10):
    if not files or all(not f.filename for f in files):
        raise HTTPException(400, "请上传产品图")
    if len(files) < min_count:
        raise HTTPException(400, f"请至少上传{min_count}张图片（多角度实拍识别更准）")
    if len(files) > max_count:
        raise HTTPException(400, f"最多上传{max_count}张图片")
    for f in files:
        if f.content_type and f.content_type not in ("image/jpeg", "image/png", "image/webp", "image/jpg"):
            raise HTTPException(400, f"仅支持 JPG/PNG/WebP，不支持: {f.content_type}")


# ============ ENDPOINTS ============


@router.post("/analyze")
async def creative_analyze_endpoint(
    files: list[UploadFile] = File(...),
    industry: str = Form("鞋类"),
    extra_info: str = Form(""),
    script_type: str = Form("with_cart"),
    variant_count: int = Form(2),
    generate_scenes: bool = Form(False),
):
    """Full creative pipeline: upload product images → analysis → brief → plans → QA.

    Returns product_analysis, creative_brief, plans with QA reports, and optionally scene images.
    """
    _validate_files(files, min_count=3, max_count=10)

    # Reset and save
    for f in files:
        f.file.seek(0)
    image_paths = [_save_upload(f) for f in files]

    try:
        # Stage 1: Vision analysis (ensemble Doubao + Qwen-VL)
        try:
            product_analysis = analyze_product_ensemble(image_paths, industry)
        except Exception:
            product_analysis = creative_analyze(image_paths, industry)

        # Stage 2: Creative brief
        creative_brief = generate_creative_brief(product_analysis, industry, extra_info)

        # Stage 3: Scene generation (optional, takes extra time)
        scene_images = []
        if generate_scenes:
            try:
                scene_results = generate_scenes_from_brief(creative_brief)
                scene_images = [
                    {"name": s["scene_name"], "path": s["image_path"], "archetype": s["archetype"]}
                    for s in scene_results
                ]
            except Exception as e:
                logger.warning(f"Scene generation failed (non-blocking): {e}")

        # Stage 4: Build creative context + generate plans
        creative_context = build_creative_context(product_analysis, creative_brief)
        result = generate_plans(creative_context, extra_info, industry, script_type, variant_count)

        # Persist brief
        brief_id = None
        try:
            record = CreativeBrief.create(
                industry=industry,
                product_name=product_analysis.get("category", ""),
                product_analysis=json.dumps(product_analysis, ensure_ascii=False),
                creative_brief=json.dumps(creative_brief, ensure_ascii=False),
                image_paths=json.dumps(image_paths),
                scene_images=json.dumps([s["path"] for s in scene_images]),
                status="complete",
            )
            brief_id = record.brief_id
        except Exception as e:
            logger.warning(f"Failed to persist brief: {e}")

        return {
            "brief_id": brief_id,
            "product_analysis": product_analysis,
            "creative_brief": creative_brief,
            "scene_images": scene_images,
            "plans": result["plans"],
            "qa_reports": result.get("qa_reports", []),
            "script_type": script_type,
            "variant_count": result["variant_count"],
            "image_paths": image_paths,
        }
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/batch-generate")
async def batch_generate(
    files: list[UploadFile] = File(...),
    industry: str = Form("鞋类"),
    extra_info: str = Form(""),
    script_type: str = Form("with_cart"),
    variant_count: int = Form(2),
    scene_mode: str = Form("brief"),  # "brief" = auto from brief, "custom" = use scene_names
    scene_names: str = Form(""),  # Comma-separated scene names for custom mode
    platforms: str = Form("douyin"),  # Comma-separated: douyin,kuaishou,xiaohongshu,shipinhao
):
    """Batch generation: analyze product → generate scenes → multi-plan output.

    Returns a job_id for tracking progress via WebSocket.
    """
    _validate_files(files, min_count=3, max_count=10)

    for f in files:
        f.file.seek(0)
    image_paths = [_save_upload(f) for f in files]

    platform_list = [p.strip() for p in platforms.split(",") if p.strip()]
    scene_list = [s.strip() for s in scene_names.split(",") if s.strip()] if scene_names else []

    # Create job record
    job = BatchJob.create(
        status="pending",
        input_config=json.dumps({
            "image_paths": image_paths,
            "industry": industry,
            "script_type": script_type,
            "variant_count": variant_count,
            "scene_mode": scene_mode,
            "scene_names": scene_list,
            "platforms": platform_list,
            "extra_info": extra_info,
        }),
    )

    # Launch background pipeline
    asyncio.create_task(_run_batch_pipeline(
        job.job_id, image_paths, industry, extra_info, script_type,
        variant_count, scene_mode, scene_list, platform_list,
    ))

    return {
        "job_id": job.job_id,
        "status": "pending",
        "message": "批量生成已启动，通过 WebSocket 追踪进度",
        "ws_url": f"/api/creative/ws/{job.job_id}",
    }


async def _run_batch_pipeline(
    job_id: str,
    image_paths: list[str],
    industry: str,
    extra_info: str,
    script_type: str,
    variant_count: int,
    scene_mode: str,
    scene_names: list[str],
    platforms: list[str],
):
    """Background batch pipeline with progress tracking."""
    loop = asyncio.get_event_loop()

    try:
        # Step 1: Product analysis (5%)
        task_manager.update(task_id=job_id, status="analyzing", progress=5,
                            message="正在分析产品图片（双模型并行）...")

        try:
            product_analysis = await loop.run_in_executor(
                None, analyze_product_ensemble, image_paths, industry
            )
        except Exception:
            product_analysis = await loop.run_in_executor(
                None, creative_analyze, image_paths, industry
            )

        # Step 2: Creative brief (15%)
        task_manager.update(task_id=job_id, status="generating", progress=15,
                            message="正在生成创意方案...")

        creative_brief = await loop.run_in_executor(
            None, generate_creative_brief, product_analysis, industry, extra_info
        )

        # Step 3: Scene generation (30%)
        task_manager.update(task_id=job_id, status="generating", progress=20,
                            message="正在生成场景背景图...")

        scene_paths = []
        if scene_mode == "custom" and scene_names:
            from services.scene_generator import generate_scene_set
            color_palette = creative_brief.get("color_palette")
            scene_results = await loop.run_in_executor(
                None, generate_scene_set, scene_names, color_palette
            )
            scene_paths = [s["image_path"] for s in scene_results]
        else:
            scene_results = await loop.run_in_executor(
                None, generate_scenes_from_brief, creative_brief
            )
            scene_paths = [s["image_path"] for s in scene_results]

        task_manager.update(task_id=job_id, status="generating", progress=30,
                            message=f"场景生成完成（{len(scene_paths)}个场景）")

        # Step 4: Plan generation (30-80%)
        creative_context = build_creative_context(product_analysis, creative_brief)

        def on_progress(event):
            if event["type"] == "variant_started":
                pct = 30 + int(45 * (event["variant"] - 1) / variant_count)
                task_manager.update(task_id=job_id, progress=pct,
                                    message=f"正在生成第 {event['variant']}/{variant_count} 套方案...")
            elif event["type"] == "variant_complete":
                task_manager.push_event(task_id=job_id, event={
                    "type": "plan_ready",
                    "variant": event["variant"],
                    "total": variant_count,
                })

        result = await loop.run_in_executor(
            None,
            lambda: generate_plans_with_progress(
                creative_context, extra_info, industry, script_type,
                variant_count, on_progress
            ),
        )

        # Step 5: QA review (85%)
        task_manager.update(task_id=job_id, status="reviewing", progress=80,
                            message="正在质检方案...")

        qa_reports = await loop.run_in_executor(
            None, review_all, result["plans"], industry, False
        )

        qa_summary = [
            {"plan_index": r.plan_index, "score": r.score, "pass": r.pass_, "summary": r.summary}
            for r in qa_reports
        ]
        task_manager.update(task_id=job_id, status="reviewing", progress=85,
                            message=f"质检完成: {sum(1 for q in qa_summary if q['pass'])}/{len(qa_summary)} 通过")

        # Step 6: Persist (90%)
        task_manager.update(task_id=job_id, status="saving", progress=90,
                            message="正在保存结果...")

        brief_record = await loop.run_in_executor(
            None,
            lambda: CreativeBrief.create(
                industry=industry,
                product_name=product_analysis.get("category", ""),
                product_analysis=json.dumps(product_analysis, ensure_ascii=False),
                creative_brief=json.dumps(creative_brief, ensure_ascii=False),
                image_paths=json.dumps(image_paths),
                scene_images=json.dumps(scene_paths),
                status="complete",
            ),
        )

        # Update job
        output_summary = {
            "total_plans": len(result["plans"]),
            "scenes": len(scene_paths),
            "platforms": platforms,
            "qa_results": qa_summary,
        }

        def _update_job():
            job = BatchJob.get(BatchJob.job_id == job_id)
            job.status = "completed"
            job.progress = 100
            job.message = "批量生成完成"
            job.brief = brief_record
            job.output_summary = json.dumps(output_summary, ensure_ascii=False)
            job.output_files = json.dumps(scene_paths + [f"plan_{i}.json" for i in range(len(result["plans"]))])
            job.save()

        await loop.run_in_executor(None, _update_job)

        task_manager.complete(task_id=job_id, result={
            "job_id": job_id,
            "brief_id": brief_record.brief_id,
            "product_analysis": product_analysis,
            "creative_brief": creative_brief,
            "plans": result["plans"],
            "qa_reports": qa_summary,
            "scene_images": scene_paths,
            "scene_count": len(scene_paths),
            "output_summary": output_summary,
        })

    except Exception as e:
        logger.exception(f"Batch pipeline {job_id} failed")

        def _fail_job():
            job = BatchJob.get(BatchJob.job_id == job_id)
            job.status = "failed"
            job.message = str(e)[:200]
            job.save()

        await loop.run_in_executor(None, _fail_job)
        task_manager.fail(task_id=job_id, error=str(e))


# ============ BRIEFS CRUD ============


@router.get("/briefs")
async def list_briefs(limit: int = 20, offset: int = 0):
    """List saved creative briefs."""
    rows = (
        CreativeBrief.select()
        .order_by(CreativeBrief.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
    )
    results = []
    for r in rows:
        results.append({
            "brief_id": r.brief_id,
            "industry": r.industry,
            "product_name": r.product_name,
            "status": r.status,
            "image_count": len(json.loads(r.image_paths or "[]")),
            "scene_count": len(json.loads(r.scene_images or "[]")),
            "created_at": r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else str(r.created_at),
            "updated_at": r.updated_at.isoformat() if hasattr(r.updated_at, 'isoformat') else str(r.updated_at),
        })
    return {"briefs": results, "total": len(results)}


@router.get("/briefs/{brief_id}")
async def get_brief(brief_id: str):
    """Get a single creative brief with full data."""
    row = CreativeBrief.get_or_none(CreativeBrief.brief_id == brief_id)
    if not row:
        raise HTTPException(404, "创意方案不存在")

    try:
        analysis = json.loads(row.product_analysis) if isinstance(row.product_analysis, str) else row.product_analysis
    except (json.JSONDecodeError, TypeError):
        analysis = {}
    try:
        brief = json.loads(row.creative_brief) if row.creative_brief and isinstance(row.creative_brief, str) else {}
    except (json.JSONDecodeError, TypeError):
        brief = {}
    try:
        scene_images = json.loads(row.scene_images) if isinstance(row.scene_images, str) else []
    except (json.JSONDecodeError, TypeError):
        scene_images = []

    return {
        "brief_id": row.brief_id,
        "industry": row.industry,
        "product_name": row.product_name,
        "product_analysis": analysis,
        "creative_brief": brief,
        "image_paths": json.loads(row.image_paths or "[]"),
        "scene_images": scene_images,
        "status": row.status,
        "created_at": row.created_at.isoformat() if hasattr(row.created_at, 'isoformat') else str(row.created_at),
        "updated_at": row.updated_at.isoformat() if hasattr(row.updated_at, 'isoformat') else str(row.updated_at),
    }


@router.delete("/briefs/{brief_id}")
async def delete_brief(brief_id: str):
    """Delete a creative brief by ID."""
    row = CreativeBrief.get_or_none(CreativeBrief.brief_id == brief_id)
    if not row:
        raise HTTPException(404, "创意方案不存在")
    row.delete_instance()
    return {"ok": True}


# ============ JOBS ============


@router.get("/jobs")
async def list_jobs(limit: int = 20, offset: int = 0):
    """List batch generation jobs."""
    rows = (
        BatchJob.select()
        .order_by(BatchJob.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
    )
    results = []
    for r in rows:
        results.append({
            "job_id": r.job_id,
            "status": r.status,
            "progress": r.progress,
            "message": r.message,
            "created_at": r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else str(r.created_at),
            "completed_at": r.completed_at.isoformat() if r.completed_at and hasattr(r.completed_at, 'isoformat') else None,
        })
    return {"jobs": results}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job status, output summary, and files."""
    job = BatchJob.get_or_none(BatchJob.job_id == job_id)
    if not job:
        raise HTTPException(404, "任务不存在")

    try:
        output_summary = json.loads(job.output_summary) if isinstance(job.output_summary, str) else {}
    except (json.JSONDecodeError, TypeError):
        output_summary = {}
    try:
        output_files = json.loads(job.output_files) if isinstance(job.output_files, str) else []
    except (json.JSONDecodeError, TypeError):
        output_files = []

    brief_info = None
    if job.brief:
        brief_info = {
            "brief_id": job.brief.brief_id,
            "industry": job.brief.industry,
            "product_name": job.brief.product_name,
        }

    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "brief": brief_info,
        "input_config": json.loads(job.input_config or "{}"),
        "output_summary": output_summary,
        "output_files": output_files,
        "created_at": job.created_at.isoformat() if hasattr(job.created_at, 'isoformat') else str(job.created_at),
        "completed_at": job.completed_at.isoformat() if job.completed_at and hasattr(job.completed_at, 'isoformat') else None,
    }


# ============ WEBSOCKET ============


@router.get("/health")
async def creative_health():
    """Health check — connectivity status of all pipeline dependencies.

    Returns per-component status so operations can diagnose issues before
    launching batch exports.
    """
    import sys

    checks = {}

    # video renderer check
    try:
        from services.video_renderer import check_renderer_available
        checks["video_renderer"] = {
            "ok": check_renderer_available(),
            "detail": "importable + AssetPipeline + AssemblyEngine" if check_renderer_available() else "not importable",
        }
    except Exception as e:
        checks["video_renderer"] = {"ok": False, "detail": str(e)}

    # Database
    try:
        from db.models import db
        db.execute_sql("SELECT 1;")
        checks["database"] = {"ok": True, "detail": "connected"}
    except Exception as e:
        checks["database"] = {"ok": False, "detail": str(e)}

    # DeepSeek
    try:
        from config import Config
        if Config.DEEPSEEK_API_KEY:
            checks["deepseek"] = {"ok": True, "detail": f"model={Config.DEEPSEEK_MODEL}"}
        else:
            checks["deepseek"] = {"ok": False, "detail": "DEEPSEEK_API_KEY not set"}
    except Exception as e:
        checks["deepseek"] = {"ok": False, "detail": str(e)}

    # Doubao Vision
    try:
        if Config.DOUBAO_API_KEY:
            checks["doubao_vision"] = {"ok": True, "detail": f"model={Config.DOUBAO_VISION_MODEL}"}
        else:
            checks["doubao_vision"] = {"ok": False, "detail": "DOUBAO_API_KEY not set"}
    except Exception as e:
        checks["doubao_vision"] = {"ok": False, "detail": str(e)}

    # Qwen-VL (optional)
    try:
        if Config.DASHSCOPE_API_KEY:
            checks["qwen_vl"] = {"ok": True, "detail": f"model={Config.QWEN_VL_MODEL}"}
        else:
            checks["qwen_vl"] = {"ok": False, "detail": "DASHSCOPE_API_KEY not set (optional)"}
    except Exception as e:
        checks["qwen_vl"] = {"ok": False, "detail": str(e)}

    # Scene generator
    try:
        from services.scene_generator import list_generated_scenes
        list_generated_scenes()
        checks["scene_generator"] = {"ok": True, "detail": "Pillow-based, 12 archetypes"}
    except Exception as e:
        checks["scene_generator"] = {"ok": False, "detail": str(e)}

    all_ok = all(c.get("ok") for c in checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "checks": checks,
    }


@router.websocket("/ws/{task_id}")
async def ws_progress(websocket: WebSocket, task_id: str):
    """WebSocket for real-time batch job progress."""
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


# ============ SCENES ============


@router.get("/scenes")
async def list_scenes():
    """List all generated scene images."""
    scenes = list_generated_scenes()
    return {"scenes": scenes, "total": len(scenes)}


@router.post("/scenes/generate")
async def generate_scene_endpoint(
    scene_name: str = Form("窗边白墙"),
    scene_description: str = Form(""),
    primary_color: str = Form(""),
    secondary_color: str = Form(""),
    accent_color: str = Form(""),
    resolution: str = Form("portrait"),
):
    """Generate a single scene on demand."""
    color_palette = None
    if primary_color:
        color_palette = {"primary": primary_color, "secondary": secondary_color, "accent": accent_color}

    path = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: generate_scene(scene_name, scene_description or f"{scene_name}场景", color_palette, resolution),
    )

    return {
        "scene_name": scene_name,
        "image_path": path,
        "url": f"/data/scenes/custom/{os.path.basename(path)}",
    }


# ============ VIDEO EXPORT ============


@router.post("/export-video")
async def export_video_endpoint(
    brief_id: str = Form(""),
    plan_index: int = Form(0),
    industry: str = Form("鞋类"),
    script_type: str = Form("with_cart"),
    platform: str = Form("douyin"),
    tts_voice: str = Form("zh-CN-YunxiNeural"),
    tts_speed: float = Form(1.15),
    bgm: bool = Form(False),
):
    """Export a creative plan to finished MP4 video via auto-video-platform.

    Takes a saved creative brief (brief_id) or the latest plan,
    converts it to a Beat-level Script, and runs the full
    auto-video-platform pipeline: Script → TTS → Assets → Assembly → MP4.

    Returns paths to HTML preview, MP4 video, audio, and SRT subtitles.
    """
    if not check_renderer_available():
        raise HTTPException(503, "auto-video-platform 不可用，请检查依赖和路径配置")

    # Resolve plan data
    plan = None
    scene_images = []

    if brief_id:
        row = CreativeBrief.get_or_none(CreativeBrief.brief_id == brief_id)
        if not row:
            raise HTTPException(404, "创意方案不存在")

        try:
            scene_images = json.loads(row.scene_images) if isinstance(row.scene_images, str) else row.scene_images or []
        except (json.JSONDecodeError, TypeError):
            scene_images = []

        # Extract creative_brief and product_analysis from DB row
        try:
            creative_brief = json.loads(row.creative_brief) if isinstance(row.creative_brief, str) else row.creative_brief or {}
        except (json.JSONDecodeError, TypeError):
            creative_brief = {}
        try:
            product_analysis = json.loads(row.product_analysis) if isinstance(row.product_analysis, str) else row.product_analysis or {}
        except (json.JSONDecodeError, TypeError):
            product_analysis = {}

        # Get associated plans from batch job
        job = BatchJob.select().where(
            BatchJob.brief == row,
            BatchJob.status == "completed",
        ).order_by(BatchJob.created_at.desc()).first()

        if job:
            try:
                output_summary = json.loads(job.output_summary) if isinstance(job.output_summary, str) else {}
            except (json.JSONDecodeError, TypeError):
                output_summary = {}
            # Plans are stored in task_manager result — try loading from plan JSON files
            try:
                output_files = json.loads(job.output_files) if isinstance(job.output_files, str) else []
            except (json.JSONDecodeError, TypeError):
                output_files = []

            plan_files = [f for f in output_files if f.startswith("plan_") and f.endswith(".json")]
            if plan_files and plan_index > 0 and plan_index <= len(plan_files):
                plan_path = os.path.join(Config.DATA_DIR, "videos", plan_files[plan_index - 1])
                if os.path.exists(plan_path):
                    with open(plan_path, "r", encoding="utf-8") as pf:
                        plan = json.load(pf)

        if not plan:
            raise HTTPException(400, "该创意方案尚未生成拍摄方案，请先运行批量生成")
    else:
        raise HTTPException(400, "请提供 brief_id")

    if not plan:
        raise HTTPException(400, "未找到可导出的方案")

    # Run video export in executor (blocking pipeline)
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: render_video(
                plan=plan,
                scene_images=scene_images,
                video_type="product_promo",
                platform=platform,
                industry=industry,
                script_type=script_type,
                tts_voice=tts_voice,
                tts_speed=tts_speed,
                bgm=bgm,
                creative_brief=creative_brief,
                product_analysis=product_analysis,
            ),
        )
    except Exception as e:
        logger.exception("Video export failed")
        raise HTTPException(500, f"视频导出失败: {e}")

    if not result.ok:
        raise HTTPException(500, f"视频导出失败: {result.error}")

    return {
        "ok": True,
        "plan_index": result.plan_index,
        "output_dir": result.output_dir,
        "html_path": result.html_path,
        "mp4_path": result.mp4_path,
        "audio_path": result.audio_path,
        "srt_path": result.srt_path,
        "duration_s": result.duration_s,
        "title": result.script.title,
        "beats": len(result.script.beats),
        "preview_url": f"/data/videos/{os.path.basename(result.output_dir)}/index.html",
    }


@router.post("/export-videos-batch")
async def export_videos_batch_endpoint(
    brief_id: str = Form(...),
    industry: str = Form("鞋类"),
    script_type: str = Form("with_cart"),
    platform: str = Form("douyin"),
    tts_voice: str = Form("zh-CN-YunxiNeural"),
    tts_speed: float = Form(1.15),
    bgm: bool = Form(False),
):
    """Export all plans from a creative brief to videos in parallel.

    Launches a background job and returns a job_id for WebSocket progress tracking.
    """
    if not check_renderer_available():
        raise HTTPException(503, "auto-video-platform 不可用")

    row = CreativeBrief.get_or_none(CreativeBrief.brief_id == brief_id)
    if not row:
        raise HTTPException(404, "创意方案不存在")

    try:
        scene_images = json.loads(row.scene_images) if isinstance(row.scene_images, str) else row.scene_images or []
    except (json.JSONDecodeError, TypeError):
        scene_images = []

    # Extract creative_brief and product_analysis from DB row
    try:
        creative_brief = json.loads(row.creative_brief) if isinstance(row.creative_brief, str) else row.creative_brief or {}
    except (json.JSONDecodeError, TypeError):
        creative_brief = {}
    try:
        product_analysis = json.loads(row.product_analysis) if isinstance(row.product_analysis, str) else row.product_analysis or {}
    except (json.JSONDecodeError, TypeError):
        product_analysis = {}

    # Get plans from associated completed job
    job = BatchJob.select().where(
        BatchJob.brief == row,
        BatchJob.status == "completed",
    ).order_by(BatchJob.created_at.desc()).first()

    plans = []
    if job:
        try:
            output_files = json.loads(job.output_files) if isinstance(job.output_files, str) else []
        except (json.JSONDecodeError, TypeError):
            output_files = []
        plan_files = [f for f in output_files if f.startswith("plan_") and f.endswith(".json")]
        for pf in plan_files:
            plan_path = os.path.join(Config.DATA_DIR, "videos", pf)
            if os.path.exists(plan_path):
                with open(plan_path, "r", encoding="utf-8") as pf_handle:
                    plans.append(json.load(pf_handle))

    if not plans:
        raise HTTPException(400, "该创意方案尚未生成拍摄方案")

    # Create job for tracking
    video_job = BatchJob.create(
        status="pending",
        input_config=json.dumps({
            "brief_id": brief_id,
            "plan_count": len(plans),
            "scene_images": scene_images,
            "industry": industry,
            "script_type": script_type,
        }),
    )

    asyncio.create_task(_run_video_export_pipeline(
        video_job.job_id, plans, scene_images, industry, script_type, platform,
        tts_voice, tts_speed, bgm, creative_brief, product_analysis,
    ))

    return {
        "job_id": video_job.job_id,
        "status": "pending",
        "plan_count": len(plans),
        "message": f"开始批量导出 {len(plans)} 个方案的视频",
        "ws_url": f"/api/creative/ws/{video_job.job_id}",
    }


async def _run_video_export_pipeline(
    job_id: str,
    plans: list[dict],
    scene_images: list[str],
    industry: str,
    script_type: str,
    platform: str,
    tts_voice: str,
    tts_speed: float,
    bgm: bool,
    creative_brief: dict = None,
    product_analysis: dict = None,
):
    """Background pipeline for batch video export."""
    loop = asyncio.get_event_loop()

    try:
        total = len(plans)
        task_manager.update(task_id=job_id, status="processing", progress=5,
                            message=f"开始导出 {total} 个方案...")

        from config import Config as Cfg
        base_dir = os.path.join(Cfg.DATA_DIR, "videos", f"batch_{job_id}")
        os.makedirs(base_dir, exist_ok=True)

        results = []
        for i, plan in enumerate(plans):
            pct = 5 + int(85 * (i + 1) / total)
            task_manager.update(task_id=job_id, progress=pct,
                                message=f"正在导出方案 {i + 1}/{total}...")

            plan_dir = os.path.join(base_dir, f"plan_{i + 1}")
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda p=plan, pd=plan_dir: render_video(
                        plan=p,
                        scene_images=scene_images,
                        output_dir=pd,
                        video_type="product_promo",
                        platform=platform,
                        industry=industry,
                        script_type=script_type,
                        tts_voice=tts_voice,
                        tts_speed=tts_speed,
                        bgm=bgm,
                        creative_brief=creative_brief,
                        product_analysis=product_analysis,
                    ),
                )
                results.append({
                    "plan_index": i + 1,
                    "ok": result.ok,
                    "output_dir": result.output_dir,
                    "html_path": result.html_path,
                    "mp4_path": result.mp4_path,
                    "audio_path": result.audio_path,
                    "duration_s": result.duration_s,
                    "error": result.error,
                })
            except Exception as e:
                results.append({"plan_index": i + 1, "ok": False, "error": str(e)})

        # Update job
        ok_count = sum(1 for r in results if r["ok"])

        def _finish():
            j = BatchJob.get_by_id(job_id)
            j.status = "completed"
            j.progress = 100
            j.message = f"视频导出完成: {ok_count}/{total} 成功"
            j.output_summary = json.dumps({"total": total, "ok": ok_count, "results": results}, ensure_ascii=False)
            j.output_files = json.dumps([r.get("mp4_path", "") or r.get("html_path", "") for r in results])
            j.save()

        await loop.run_in_executor(None, _finish)
        task_manager.complete(task_id=job_id, result={
            "job_id": job_id,
            "total": total,
            "ok": ok_count,
            "results": results,
        })

    except Exception as e:
        logger.exception(f"Video export batch {job_id} failed")

        def _fail():
            j = BatchJob.get_by_id(job_id)
            j.status = "failed"
            j.message = str(e)[:200]
            j.save()

        await loop.run_in_executor(None, _fail)
        task_manager.fail(task_id=job_id, error=str(e))
