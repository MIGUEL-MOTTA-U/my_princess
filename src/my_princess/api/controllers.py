"""Controladores HTTP (routers de FastAPI).

Cada factory recibe su servicio ya construido (inyeccion en el composition
root, `app.py`) y solo se ocupa de HTTP: validacion de entrada, verbos,
codigos de estado y contratos de respuesta.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, UploadFile, status

from ..models import AssetStatus
from .schemas import (
    AssetDetail,
    AssetSummary,
    ConfigOut,
    ConfigUpdate,
    HealthOut,
    OutputFileOut,
    OutputFolder,
    Page,
    TransformLogOut,
    UploadOut,
)
from .services import (
    AssetNotFoundError,
    AssetService,
    ConfigService,
    DuplicateUploadError,
    FileService,
    InvalidUploadError,
)

PageParam = Query(1, ge=1, description="Pagina (1-based)")
SizeParam = Query(20, ge=1, le=100, description="Elementos por pagina")


def build_assets_router(service: AssetService) -> APIRouter:
    router = APIRouter(prefix="/assets", tags=["assets"])

    @router.get("", response_model=Page[AssetSummary], summary="Listar assets")
    def list_assets(
        status_filter: AssetStatus | None = Query(
            None, alias="status", description="Filtrar por estado del pipeline"
        ),
        page: int = PageParam,
        size: int = SizeParam,
    ):
        return service.list_assets(
            status_filter.value if status_filter else None, page, size
        )

    @router.get(
        "/{asset_id}",
        response_model=AssetDetail,
        summary="Detalle de un asset (incluye transcripcion y metadata)",
    )
    def get_asset(asset_id: str):
        try:
            return service.get_asset(asset_id)
        except AssetNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Asset {asset_id} no existe")

    @router.get(
        "/{asset_id}/logs",
        response_model=Page[TransformLogOut],
        summary="Trazabilidad de un asset (transiciones de estado)",
    )
    def get_asset_logs(asset_id: str, page: int = PageParam, size: int = SizeParam):
        try:
            return service.list_asset_logs(asset_id, page, size)
        except AssetNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Asset {asset_id} no existe")

    return router


def build_logs_router(service: AssetService) -> APIRouter:
    router = APIRouter(prefix="/logs", tags=["traceability"])

    @router.get(
        "",
        response_model=Page[TransformLogOut],
        summary="Feed global de trazabilidad (mas reciente primero)",
    )
    def list_logs(page: int = PageParam, size: int = SizeParam):
        return service.list_logs(page, size)

    return router


def build_files_router(service: FileService) -> APIRouter:
    router = APIRouter(tags=["files"])

    @router.post(
        "/videos",
        response_model=UploadOut,
        status_code=status.HTTP_201_CREATED,
        summary="Subir un video .mp4 al watchfolder",
        description="El pipeline lo detecta y procesa automaticamente; "
        "consulta su avance en /assets y /logs.",
    )
    def upload_video(file: UploadFile):
        try:
            return service.save_upload(file.filename, file.file)
        except InvalidUploadError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        except DuplicateUploadError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Ya existe un archivo llamado {exc} en el watchfolder",
            )

    @router.get(
        "/outputs/{folder}",
        response_model=Page[OutputFileOut],
        summary="Listar archivos de salida (output o approved)",
    )
    def list_outputs(folder: OutputFolder, page: int = PageParam, size: int = SizeParam):
        return service.list_outputs(folder, page, size)

    @router.get(
        "/outputs/{folder}/{asset_id}",
        summary="Contenido JSON de la salida de un asset",
        response_description="Transcripcion completa + metadata estructurada",
    )
    def get_output(folder: OutputFolder, asset_id: str):
        try:
            return service.read_output(folder, asset_id)
        except AssetNotFoundError:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"No hay salida de {asset_id} en {folder.value}/"
            )

    return router


def build_config_router(service: ConfigService) -> APIRouter:
    router = APIRouter(prefix="/config", tags=["config"])

    @router.get("", response_model=ConfigOut, summary="Configuracion actual del agente")
    def get_config():
        return service.get()

    @router.put(
        "",
        response_model=ConfigOut,
        summary="Actualizar el umbral de confianza del triage",
        description="Cambio en caliente: el pipeline lo aplica en el siguiente "
        "asset sin reiniciar. Valores entre 0 y 1.",
    )
    def update_config(body: ConfigUpdate):
        return service.update_threshold(body.confidence_threshold)

    return router


def build_health_router(ping) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health", response_model=HealthOut, summary="Estado del servicio")
    def health():
        try:
            ping()
            return {"status": "ok", "database": "up"}
        except Exception:
            return {"status": "degraded", "database": "down"}

    return router
