import asyncio
import logging
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from config import Config
from db.migrations import init_db
from db.models import RegisteredUser

from api.creative_api import router as creative_router
from services.task_manager import task_manager
from services.prompt_engine import CATEGORY_CONFIGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_VERSION = "0.3.0"

PUBLIC_API_PATHS = {"/api/health", "/api/register"}
WS_PREFIXES = {"/api/creative/ws/"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/") and request.url.path not in PUBLIC_API_PATHS:
            # WebSocket paths pass through — browsers can't set custom headers on WS upgrade
            if any(request.url.path.startswith(p) for p in WS_PREFIXES):
                return await call_next(request)
            api_key = Config.API_KEY
            if api_key:
                req_key = request.headers.get("X-API-Key", "")
                if req_key != api_key:
                    return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)


app = FastAPI(title="FrameCraft — AI电商拍摄方案", version=APP_VERSION)
app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory="web/static"), name="static")

app.include_router(creative_router)
templates = Jinja2Templates(directory="web/templates")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/factory")
async def factory_page(request: Request):
    return templates.TemplateResponse("factory.html", {"request": request})


@app.get("/en")
async def index_en(request: Request):
    return templates.TemplateResponse("landing-en.html", {"request": request})


@app.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/support")
async def support_page(request: Request):
    return templates.TemplateResponse("support.html", {"request": request})


@app.get("/privacy")
async def privacy_page(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})


@app.get("/terms")
async def terms_page(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})



@app.get("/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/preview")
async def preview_page(request: Request):
    return templates.TemplateResponse("preview.html", {"request": request})


@app.get("/test-results")
async def test_results_page(request: Request):
    return templates.TemplateResponse("test_results.html", {"request": request})


@app.get("/direct-gen")
async def direct_gen_page(request: Request):
    return templates.TemplateResponse("direct_gen.html", {"request": request})


@app.get("/director")
async def director_page(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/factory")


@app.get("/creative")
async def creative_page(request: Request):
    return templates.TemplateResponse("creative.html", {"request": request})


@app.get("/sw.js")
async def service_worker():
    return FileResponse("web/static/sw.js", media_type="application/javascript")


@app.post("/api/register")
async def register_user(request: Request):
    """Register a new user. Expects JSON: {phone, platform, category, name?}."""
    try:
        data = await request.json()
        phone = data.get("phone", "").strip()
        platform = data.get("platform", "").strip()
        category = data.get("category", "").strip()
        name = data.get("name", "").strip()

        if not phone or not platform or not category:
            return JSONResponse({"success": False, "message": "手机号、主营平台、经营品类为必填项"}, status_code=400)

        if RegisteredUser.select().where(RegisteredUser.phone == phone).exists():
            return {"success": True, "message": "该手机号已注册，直接跳转"}

        RegisteredUser.create(phone=phone, platform=platform, category=category, name=name)
        logger.info("New user registered: %s", phone)
        return {"success": True, "message": "注册成功"}
    except ValueError as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)
    except Exception as e:
        logger.error("Registration error: %s", e)
        return JSONResponse({"success": False, "message": "注册失败，请稍后重试"}, status_code=500)


@app.on_event("startup")
async def startup():
    init_db()
    task_manager.set_loop(asyncio.get_event_loop())
    logger.info("Database initialized at %s", Config.DATABASE_PATH)


if __name__ == "__main__":
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
