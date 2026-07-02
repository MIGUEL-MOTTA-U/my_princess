"""Estructuracion de metadata via LLM.

El prompt y el parseo son agnosticos al proveedor: cualquier objeto con un
metodo `complete(system, user) -> str` sirve como cliente. La demo incluye
la implementacion para Anthropic (unico proveedor con API key disponible);
los tests usan un cliente falso.
"""
from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import ValidationError

from .models import AssetMetadata

SYSTEM_PROMPT = """\
Eres un documentalista de una empresa de television y noticias. Recibes la
transcripcion de un video proxy y produces metadata estructurada para el
archivo documental.

Responde UNICAMENTE con un objeto JSON valido (sin markdown, sin texto extra)
con exactamente estas claves:

{
  "title": "string, maximo 120 caracteres, titular descriptivo del contenido",
  "summary_short": "string, 1-2 frases",
  "summary_long": "string, 1-2 parrafos",
  "tags": ["3 a 10 strings, temas y palabras clave en minusculas"],
  "staff": ["nombres propios de personas mencionadas; lista vacia si no hay"],
  "confidence_score": 0.0
}

Calcula confidence_score (float entre 0 y 1) con este criterio:
- Parte de 1.0.
- Resta hasta 0.3 si la transcripcion es corta (< 50 palabras) o parece
  incompleta/entrecortada, senal de audio pobre.
- Resta hasta 0.3 si el tema central es ambiguo y el titulo/resumen requirio
  interpretacion tuya en lugar de estar explicito en el texto.
- Resta hasta 0.2 si los nombres propios detectados son dudosos (posibles
  errores de transcripcion fonetica).
- Resta hasta 0.2 si hay jerga, multiples idiomas o ruido que dificulte
  el resumen.
Nunca devuelvas un valor fuera de [0, 1].
"""

CORRECTION_PROMPT = """\
Tu respuesta anterior no cumplio el contrato JSON. Error de validacion:

{error}

Respuesta anterior:
{previous}

Devuelve SOLO el objeto JSON corregido, cumpliendo exactamente el esquema
indicado en las instrucciones del sistema.
"""


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicClient:
    """Implementacion para la API de Anthropic (SDK oficial)."""

    def __init__(self, model: str = "claude-opus-4-8"):
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic()

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - red real
        response = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("el modelo rechazo la solicitud (stop_reason=refusal)")
        return "".join(
            block.text for block in response.content if block.type == "text"
        )


def build_llm_client(provider: str, model: str) -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient(model=model)
    raise ValueError(f"Proveedor LLM no soportado: {provider}")


def _extract_json(raw: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta, tolerando fences de
    markdown que algunos proveedores agregan aunque se les pida no hacerlo."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("la respuesta no contiene un objeto JSON")
        text = text[start : end + 1]
    return json.loads(text)


def structure_metadata(
    llm: LLMClient, transcript: str
) -> tuple[AssetMetadata | None, str | None]:
    """Envia la transcripcion al LLM y valida contra el contrato.

    Devuelve (metadata, None) en exito, o (None, error_code) si la respuesta
    no valida tras un reintento de correccion.
    """
    user_prompt = f"Transcripcion del video:\n\n{transcript}"
    raw = llm.complete(SYSTEM_PROMPT, user_prompt)

    for attempt in range(2):
        try:
            payload = _extract_json(raw)
            return AssetMetadata.model_validate(payload), None
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            if attempt == 1:
                return None, f"LLM_SCHEMA_VALIDATION_FAILED: {exc}"
            raw = llm.complete(
                SYSTEM_PROMPT,
                CORRECTION_PROMPT.format(error=exc, previous=raw[:2000]),
            )
    return None, "LLM_SCHEMA_VALIDATION_FAILED"  # pragma: no cover - inalcanzable
