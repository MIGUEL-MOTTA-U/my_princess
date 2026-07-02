"""Tests de estructuración LLM con cliente falso (sin llamadas reales)."""
import json

import pytest

from my_princess.llm import (
    SYSTEM_PROMPT,
    build_llm_client,
    _extract_json,
    structure_metadata,
)

VALID_PAYLOAD = {
    "title": "Entrevista sobre movilidad urbana",
    "summary_short": "Entrevista sobre el nuevo plan de movilidad.",
    "summary_long": "Un funcionario explica el plan de movilidad y sus fases.",
    "tags": ["movilidad", "entrevista", "ciudad"],
    "staff": ["Laura Rincón"],
    "confidence_score": 0.85,
}


class FakeLLM:
    """Devuelve respuestas encoladas y registra los prompts recibidos."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.responses.pop(0)


def test_valid_response_first_try():
    llm = FakeLLM([json.dumps(VALID_PAYLOAD)])
    metadata, error = structure_metadata(llm, "texto de prueba")
    assert error is None
    assert metadata.title == VALID_PAYLOAD["title"]
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == SYSTEM_PROMPT
    assert "texto de prueba" in llm.calls[0][1]


def test_markdown_fenced_response_is_parsed():
    llm = FakeLLM([f"```json\n{json.dumps(VALID_PAYLOAD)}\n```"])
    metadata, error = structure_metadata(llm, "t")
    assert error is None
    assert metadata.confidence_score == 0.85


def test_invalid_then_corrected():
    bad = dict(VALID_PAYLOAD, confidence_score=7)  # fuera de rango
    llm = FakeLLM([json.dumps(bad), json.dumps(VALID_PAYLOAD)])
    metadata, error = structure_metadata(llm, "t")
    assert error is None
    assert metadata.confidence_score == 0.85
    assert len(llm.calls) == 2
    assert "Error de validacion" in llm.calls[1][1]


def test_invalid_twice_returns_error_code():
    bad = dict(VALID_PAYLOAD, tags=[])  # menos de 3 tags
    llm = FakeLLM([json.dumps(bad), json.dumps(bad)])
    metadata, error = structure_metadata(llm, "t")
    assert metadata is None
    assert error.startswith("LLM_SCHEMA_VALIDATION_FAILED")


def test_non_json_response_then_corrected():
    llm = FakeLLM(["Lo siento, aquí está la metadata...", json.dumps(VALID_PAYLOAD)])
    metadata, error = structure_metadata(llm, "t")
    assert error is None
    assert metadata is not None


def test_extract_json_with_surrounding_text():
    payload = _extract_json(f"Claro: {json.dumps({'a': 1})} — listo.")
    assert payload == {"a": 1}


def test_extract_json_without_object_raises():
    with pytest.raises(ValueError):
        _extract_json("sin json aquí")


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("gemini", "gemini-2.5-flash", "gemini/gemini-2.5-flash"),
        ("openai", "gpt-4o-mini", "openai/gpt-4o-mini"),
        ("anthropic", "claude-opus-4-8", "anthropic/claude-opus-4-8"),
        ("Ollama", " llama3.1 ", "ollama/llama3.1"),
    ],
)
def test_build_llm_client_composes_litellm_model(provider, model, expected):
    client = build_llm_client(provider, model)
    assert client.model == expected
    assert client.api_base is None


def test_build_llm_client_passes_api_base():
    client = build_llm_client("ollama", "llama3.1", api_base="http://nas:11434")
    assert client.api_base == "http://nas:11434"


@pytest.mark.parametrize(("provider", "model"), [("", "x"), ("gemini", ""), ("  ", "x")])
def test_build_llm_client_rejects_empty_values(provider, model):
    with pytest.raises(ValueError, match="no pueden estar vacios"):
        build_llm_client(provider, model)


def test_litellm_client_calls_completion(monkeypatch):
    import litellm
    from unittest.mock import MagicMock

    from my_princess.llm import LiteLLMClient

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "respuesta"
    completion = MagicMock(return_value=fake_response)
    monkeypatch.setattr(litellm, "completion", completion)

    client = LiteLLMClient("gemini/gemini-2.5-flash", api_base=None)
    assert client.complete("sys", "user") == "respuesta"

    kwargs = completion.call_args.kwargs
    assert kwargs["model"] == "gemini/gemini-2.5-flash"
    assert kwargs["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


def test_litellm_client_handles_none_content(monkeypatch):
    import litellm
    from unittest.mock import MagicMock

    from my_princess.llm import LiteLLMClient

    fake_response = MagicMock()
    fake_response.choices[0].message.content = None
    monkeypatch.setattr(litellm, "completion", MagicMock(return_value=fake_response))

    assert LiteLLMClient("openai/gpt-4o-mini").complete("s", "u") == ""
