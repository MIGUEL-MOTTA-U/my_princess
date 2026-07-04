"""Capa REST (FastAPI) para clientes front: consulta de assets, trazabilidad,
carga de videos, salidas y configuracion dinamica del agente.

Arquitectura en capas sobre lo ya existente:
    controllers.py  -> routers HTTP (validacion de entrada, codigos de estado)
    services.py     -> logica de aplicacion (paginacion, reglas, archivos)
    repositories.py -> patron repository; delegan en Database (unico punto
                       de acceso a MongoDB, compartido con el pipeline)
    schemas.py      -> contratos de entrada/salida (pydantic + OpenAPI)
    app.py          -> composition root (create_app)
"""
