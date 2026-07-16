import httpx
import pytest

from app.query.ollama_chat import ChatError, _build_context, generate_answer
from app.query.schemas import SourceChunk

pytestmark = pytest.mark.unit


def _source(content="chunk text", filename="doc.pdf", page_number=1):
    return SourceChunk(filename=filename, page_number=page_number, chunk_index=0, content=content, score=0.9)


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://ollama/api/chat")
            raise httpx.HTTPStatusError(
                "error", request=request, response=httpx.Response(self.status_code, request=request)
            )

    def json(self):
        return self._json_data


class FakeAsyncClient:
    captured_payload = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json):
        FakeAsyncClient.captured_payload = json
        return self._next_response()

    def _next_response(self):
        raise NotImplementedError


def test_build_context_formats_filename_and_page():
    context = _build_context([_source(content="First fact.", filename="a.pdf", page_number=3)])

    assert context == "[a.pdf, page 3]\nFirst fact."


def test_build_context_joins_multiple_sources_with_blank_line():
    sources = [_source(content="One", filename="a.pdf", page_number=1), _source(content="Two", filename="b.pdf", page_number=2)]

    context = _build_context(sources)

    assert context == "[a.pdf, page 1]\nOne\n\n[b.pdf, page 2]\nTwo"


async def test_generate_answer_success_returns_message_content(monkeypatch):
    class OkClient(FakeAsyncClient):
        def _next_response(self):
            return FakeResponse({"message": {"content": "The answer is 42."}})

    monkeypatch.setattr("app.query.ollama_chat.httpx.AsyncClient", OkClient)

    answer = await generate_answer("What is the answer?", [_source()])

    assert answer == "The answer is 42."


async def test_generate_answer_sends_model_and_context_in_payload(monkeypatch):
    class OkClient(FakeAsyncClient):
        def _next_response(self):
            return FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr("app.query.ollama_chat.httpx.AsyncClient", OkClient)

    await generate_answer("my question", [_source(content="grounding text")])

    payload = FakeAsyncClient.captured_payload
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    user_message = payload["messages"][1]["content"]
    assert "my question" in user_message
    assert "grounding text" in user_message


async def test_generate_answer_missing_content_raises_chat_error(monkeypatch):
    class EmptyClient(FakeAsyncClient):
        def _next_response(self):
            return FakeResponse({"message": {}})

    monkeypatch.setattr("app.query.ollama_chat.httpx.AsyncClient", EmptyClient)

    with pytest.raises(ChatError, match="unexpected response shape"):
        await generate_answer("q", [_source()])


async def test_generate_answer_http_error_raises_chat_error(monkeypatch):
    class FailingClient(FakeAsyncClient):
        async def post(self, url, json):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.query.ollama_chat.httpx.AsyncClient", FailingClient)

    with pytest.raises(ChatError, match="request failed"):
        await generate_answer("q", [_source()])


async def test_generate_answer_http_status_error_raises_chat_error(monkeypatch):
    class ErrorClient(FakeAsyncClient):
        def _next_response(self):
            return FakeResponse({}, status_code=503)

    monkeypatch.setattr("app.query.ollama_chat.httpx.AsyncClient", ErrorClient)

    with pytest.raises(ChatError):
        await generate_answer("q", [_source()])
