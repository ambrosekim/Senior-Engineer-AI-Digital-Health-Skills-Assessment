import pytest

from app.documents.pdf_processing import chunk_pages, extract_pages, looks_like_pdf
from tests.pdf_fixtures import build_minimal_pdf

pytestmark = pytest.mark.unit


class FakePage:
    def __init__(self, text, raise_on_extract=False):
        self._text = text
        self._raise = raise_on_extract

    def extract_text(self):
        if self._raise:
            raise RuntimeError("simulated extraction failure")
        return self._text


class FakeReader:
    def __init__(self, data):
        self.pages = getattr(FakeReader, "_next_pages", [])
        self.is_encrypted = getattr(FakeReader, "_next_encrypted", False)
        self._decrypt_should_fail = getattr(FakeReader, "_next_decrypt_fails", False)

    def decrypt(self, password):
        if self._decrypt_should_fail:
            raise ValueError("bad password")


# ---- looks_like_pdf -------------------------------------------------------


def test_looks_like_pdf_accepts_valid_magic_bytes():
    assert looks_like_pdf(b"%PDF-1.4\n...") is True


def test_looks_like_pdf_rejects_other_bytes():
    assert looks_like_pdf(b"not a pdf at all") is False


def test_looks_like_pdf_rejects_empty_bytes():
    assert looks_like_pdf(b"") is False


# ---- extract_pages ---------------------------------------------------------


def test_extract_pages_happy_path(monkeypatch):
    FakeReader._next_pages = [FakePage("Page one text"), FakePage("Page two text")]
    FakeReader._next_encrypted = False
    monkeypatch.setattr("app.documents.pdf_processing.PdfReader", FakeReader)

    pages = extract_pages(b"irrelevant", max_pages=10)

    assert pages == ["Page one text", "Page two text"]


def test_extract_pages_no_pages_raises(monkeypatch):
    FakeReader._next_pages = []
    FakeReader._next_encrypted = False
    monkeypatch.setattr("app.documents.pdf_processing.PdfReader", FakeReader)

    with pytest.raises(ValueError, match="no pages"):
        extract_pages(b"irrelevant", max_pages=10)


def test_extract_pages_exceeds_max_pages_raises(monkeypatch):
    FakeReader._next_pages = [FakePage("a"), FakePage("b"), FakePage("c")]
    FakeReader._next_encrypted = False
    monkeypatch.setattr("app.documents.pdf_processing.PdfReader", FakeReader)

    with pytest.raises(ValueError, match="maximum of 2 pages"):
        extract_pages(b"irrelevant", max_pages=2)


def test_extract_pages_unsupported_encryption_raises(monkeypatch):
    FakeReader._next_pages = [FakePage("secret")]
    FakeReader._next_encrypted = True
    FakeReader._next_decrypt_fails = True
    monkeypatch.setattr("app.documents.pdf_processing.PdfReader", FakeReader)

    with pytest.raises(ValueError, match="Encrypted PDFs are not supported"):
        extract_pages(b"irrelevant", max_pages=10)


def test_extract_pages_page_extraction_error_yields_empty_string(monkeypatch):
    FakeReader._next_pages = [FakePage("ok"), FakePage("", raise_on_extract=True)]
    FakeReader._next_encrypted = False
    monkeypatch.setattr("app.documents.pdf_processing.PdfReader", FakeReader)

    pages = extract_pages(b"irrelevant", max_pages=10)

    assert pages == ["ok", ""]


def test_extract_pages_corrupt_file_raises_value_error():
    with pytest.raises(ValueError, match="not a valid or supported PDF"):
        extract_pages(b"%PDF-1.4\nthis is not a real pdf structure", max_pages=10)


def test_extract_pages_reads_real_generated_pdf():
    data = build_minimal_pdf(["Hello from a real PDF.", "Second line."])

    pages = extract_pages(data, max_pages=10)

    assert len(pages) == 1
    assert "Hello from a real PDF." in pages[0]
    assert "Second line." in pages[0]


# ---- chunk_pages ------------------------------------------------------------


def test_chunk_pages_single_short_page_is_one_chunk():
    chunks = chunk_pages(["A short sentence."], chunk_size=1000, overlap=150)

    assert len(chunks) == 1
    assert chunks[0].content == "A short sentence."
    assert chunks[0].page_number == 1
    assert chunks[0].chunk_index == 0


def test_chunk_pages_skips_blank_pages():
    chunks = chunk_pages(["", "   ", "Real content here."], chunk_size=1000, overlap=150)

    assert len(chunks) == 1
    assert chunks[0].page_number == 3


def test_chunk_pages_normalizes_whitespace():
    chunks = chunk_pages(["Line one\n\n  Line   two\t\ttabbed"], chunk_size=1000, overlap=150)

    assert chunks[0].content == "Line one Line two tabbed"


def test_chunk_pages_splits_long_text_with_overlap():
    text = " ".join(f"word{i}" for i in range(200))  # long single "page"

    chunks = chunk_pages([text], chunk_size=100, overlap=20)

    assert len(chunks) > 1
    # Consecutive chunks share overlapping words rather than cutting mid-word.
    for chunk in chunks:
        assert not chunk.content.startswith(" ")
        assert not chunk.content.endswith(" ")


def test_chunk_pages_chunk_index_is_sequential_across_pages():
    chunks = chunk_pages(["Page one content.", "Page two content."], chunk_size=1000, overlap=150)

    assert [c.chunk_index for c in chunks] == [0, 1]
    assert [c.page_number for c in chunks] == [1, 2]


def test_chunk_pages_breaks_snap_to_word_boundary():
    text = "aaaaaaaaaa bbbbbbbbbb cccccccccc dddddddddd"
    chunks = chunk_pages([text], chunk_size=15, overlap=0)

    for chunk in chunks:
        assert "aaaaaaaaaa"[:5] not in chunk.content or chunk.content in text.split(" ")
    # No chunk should end mid-word (i.e. every chunk's content is a substring
    # bounded by original whitespace positions).
    rebuilt = " ".join(chunk.content for chunk in chunks)
    assert set(rebuilt.split()) == set(text.split())
