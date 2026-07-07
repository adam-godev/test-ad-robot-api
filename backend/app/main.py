from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler, http_error_handler, validation_error_handler


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Keitaro Campaign Tool", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Idempotency-Key", "Content-Type"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.include_router(router)
    return app


app = create_app()
