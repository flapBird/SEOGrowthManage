from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .automation.scheduler import scheduler
from .config import BASE_DIR, get_settings
from .database import Base, engine
from .security import CredentialCipher
from .web import public_router, router
from .keyword_web import router as keyword_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.validate_secrets()
    CredentialCipher()  # Fail fast when FERNET_KEY is malformed.
    Base.metadata.create_all(bind=engine)
    if settings.scheduler_enabled:
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
app.include_router(public_router)
app.include_router(router)
app.include_router(keyword_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 303 and exc.headers and exc.headers.get("Location"):
        return RedirectResponse(exc.headers["Location"], status_code=303)
    from fastapi.exception_handlers import http_exception_handler as default_handler

    return await default_handler(request, exc)
