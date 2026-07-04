"""Composition root de la API.

Ejecutar con:
    uvicorn my_princess.api.app:create_app --factory --port 8000

Documentacion automatica para el cliente front:
    Swagger UI -> http://localhost:8000/docs
    ReDoc      -> http://localhost:8000/redoc
    OpenAPI    -> http://localhost:8000/openapi.json
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Settings
from ..db import Database
from .controllers import (
    build_assets_router,
    build_config_router,
    build_files_router,
    build_health_router,
    build_logs_router,
)
from .repositories import AssetRepository, ConfigRepository, TransformLogRepository
from .services import AssetService, ConfigService, FileService

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    """`settings` y `db` son inyectables para tests; sin argumentos carga
    .env y se conecta al Mongo de docker-compose."""
    if settings is None:
        from dotenv import load_dotenv

        load_dotenv()
        settings = Settings()
    settings.ensure_dirs()
    if db is None:
        db = Database(settings.mongo_uri, settings.mongo_db)

    asset_service = AssetService(AssetRepository(db), TransformLogRepository(db))
    file_service = FileService(settings)
    config_service = ConfigService(ConfigRepository(db), settings)

    app = FastAPI(
        title="my_princess API",
        version="1.0.0",
        description=(
            "API para la interfaz de usuario del pipeline de documentalizacion: "
            "carga de videos, consulta de assets y salidas (output/approved), "
            "trazabilidad completa y configuracion dinamica del agente."
        ),
    )
    # front en desarrollo: origen abierto (restringir en produccion)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(build_health_router(db.count_assets), prefix=API_PREFIX)
    app.include_router(build_assets_router(asset_service), prefix=API_PREFIX)
    app.include_router(build_logs_router(asset_service), prefix=API_PREFIX)
    app.include_router(build_files_router(file_service), prefix=API_PREFIX)
    app.include_router(build_config_router(config_service), prefix=API_PREFIX)
    return app
