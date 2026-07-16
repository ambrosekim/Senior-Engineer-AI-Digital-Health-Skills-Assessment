import httpx
import pytest

from app.documents.embeddings import EmbeddingError, embed_texts, to_pgvector_literal

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://ollama/api/embed")
            raise httpx.HTTPStatusError(
                "error", request=request, response=httpx.Response(self.status_code, request=request)
            )

    def json(self):
        return self._json_data


class FakeAsyncClient:
    """Stands in for httpx.AsyncClient; records every request it's asked to make."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        FakeAsyncClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json):
        self.calls.append((url, json))
        return self._next_response(json)

    def _next_response(self, json):
        raise NotImplementedError


@pytest.fixture(autouse=True)
def reset_fake_client_instances():
    FakeAsyncClient.instances = []
    yield
    FakeAsyncClient.instances = []


async def test_embed_texts_returns_empty_list_for_empty_input():
    assert await embed_texts([]) == []


async def test_embed_texts_success_returns_vectors(monkeypatch):
    dim = 384

    class OkClient(FakeAsyncClient):
        def _next_response(self, json):
            vectors = [[0.1] * dim for _ in json["input"]]
            return FakeResponse({"embeddings": vectors})

    monkeypatch.setattr("app.documents.embeddings.httpx.AsyncClient", OkClient)

    result = await embed_texts(["hello", "world"])

    assert len(result) == 2
    assert all(len(vec) == dim for vec in result)


async def test_embed_texts_batches_in_groups_of_32(monkeypatch):
    dim = 384
    seen_batches = []

    class OkClient(FakeAsyncClient):
        def _next_response(self, json):
            seen_batches.append(len(json["input"]))
            return FakeResponse({"embeddings": [[0.0] * dim for _ in json["input"]]})

    monkeypatch.setattr("app.documents.embeddings.httpx.AsyncClient", OkClient)

    texts = [f"chunk-{i}" for i in range(40)]
    result = await embed_texts(texts)

    assert len(result) == 40
    assert seen_batches == [32, 8]


async def test_embed_texts_dimension_mismatch_raises(monkeypatch):
    class WrongDimClient(FakeAsyncClient):
        def _next_response(self, json):
            return FakeResponse({"embeddings": [[0.1, 0.2]]})  # wrong dim vs settings.embedding_dim

    monkeypatch.setattr("app.documents.embeddings.httpx.AsyncClient", WrongDimClient)

    with pytest.raises(EmbeddingError, match="dimension mismatch"):
        await embed_texts(["only one"])


async def test_embed_texts_unexpected_shape_raises(monkeypatch):
    class EmptyClient(FakeAsyncClient):
        def _next_response(self, json):
            return FakeResponse({"embeddings": []})

    monkeypatch.setattr("app.documents.embeddings.httpx.AsyncClient", EmptyClient)

    with pytest.raises(EmbeddingError, match="unexpected response shape"):
        await embed_texts(["hello"])


async def test_embed_texts_http_error_raises_embedding_error(monkeypatch):
    class FailingClient(FakeAsyncClient):
        async def post(self, url, json):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.documents.embeddings.httpx.AsyncClient", FailingClient)

    with pytest.raises(EmbeddingError, match="request failed"):
        await embed_texts(["hello"])


async def test_embed_texts_http_status_error_raises_embedding_error(monkeypatch):
    class ErrorClient(FakeAsyncClient):
        def _next_response(self, json):
            return FakeResponse({}, status_code=500)

    monkeypatch.setattr("app.documents.embeddings.httpx.AsyncClient", ErrorClient)

    with pytest.raises(EmbeddingError):
        await embed_texts(["hello"])


def test_to_pgvector_literal_uses_fixed_point_notation():
    literal = to_pgvector_literal([0.1, -0.2, 1e-10])

    assert literal.startswith("[") and literal.endswith("]")
    assert "e" not in literal.lower()  # no scientific notation
    assert literal == "[0.10000000,-0.20000000,0.00000000]"


def test_to_pgvector_literal_empty_vector():
    assert to_pgvector_literal([]) == "[]"
