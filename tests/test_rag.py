"""Retrieval tests. They use the keyless TF-IDF embedder, so CI needs no API key."""

from __future__ import annotations

from itertools import pairwise

import pytest

from app.config import POLICY_DIR
from app.rag import IndexMismatchError, PolicyIndex, open_index
from app.rag.chunker import MAX_WORDS, chunk_documents, make_snippet, window_words
from app.rag.embeddings import TfidfEmbedder
from app.rag.index import build_index
from app.rag.loaders import load_documents

NIST = "nist_sp800_46r2_telework_security_excerpt"
OPM = "opm_annual_leave_fact_sheet"


@pytest.fixture(scope="module")
def docs():
    return load_documents(POLICY_DIR)


@pytest.fixture(scope="module")
def index_base(tmp_path_factory, docs):
    base = tmp_path_factory.mktemp("index")
    build_index(docs, chunk_documents(docs), TfidfEmbedder(), base / "tfidf", POLICY_DIR)
    return base


@pytest.fixture(scope="module")
def index(index_base):
    ix = PolicyIndex.load(index_base / "tfidf")
    yield ix
    ix.close()


def test_all_four_formats_load_with_provenance(docs):
    by_id = {d.doc_id: d for d in docs}
    assert {d.format for d in docs} == {"md", "txt", "pdf", "html"}
    assert "SOURCES" not in by_id
    assert by_id[NIST].source_type == "external_reference"  # from SOURCES.md
    assert by_id[OPM].source_type == "external_reference"   # from the HTML <meta>
    assert by_id["pto_policy"].source_type == "company_policy"
    assert by_id[NIST].source_url.startswith("https://nvlpubs.nist.gov/")
    assert by_id[OPM].source_url.startswith("https://www.opm.gov/")


def test_headings_are_detected_per_format(docs):
    by_id = {d.doc_id: d for d in docs}
    assert by_id["pto_policy"].title == "Paid Time Off Policy"
    assert "Annual PTO Entitlement" in [s.heading for s in by_id["pto_policy"].sections]
    assert [s.heading for s in by_id["onboarding_checklist"].sections][:2] == [
        "Purpose", "Before the Start Date"]
    assert "Annual Leave Ceilings" in [s.heading for s in by_id[OPM].sections]
    pdf_pages = [s.page for s in by_id[NIST].sections]
    assert pdf_pages == list(range(1, 11))


def test_pdf_running_header_is_stripped(docs):
    nist = next(d for d in docs if d.doc_id == NIST)
    text = " ".join(s.text for s in nist.sections)
    assert "This publication is available free of charge from:" not in text
    assert "GUIDE TO ENTERPRISE TELEWORK," not in text.split("Guide to Enterprise Telework")[-1]


def test_html_table_rows_keep_all_cells(docs):
    opm = next(d for d in docs if d.doc_id == OPM)
    entitlement = next(s for s in opm.sections if s.heading == "Annual Leave Entitlement")
    row = next(ln for ln in entitlement.text.splitlines() if ln.startswith("Full-time employees"))
    assert row.count(" | ") == 3


def test_chunk_ids_are_deterministic_and_unique(docs):
    first = [c.chunk_id for c in chunk_documents(docs)]
    second = [c.chunk_id for c in chunk_documents(load_documents(POLICY_DIR))]
    assert first == second
    assert len(set(first)) == len(first)
    # The OPM page repeats a heading; numbering keeps both chunks.
    assert f"{OPM}#non-federal-service-or-uniformed-service#1" in first


def test_long_section_splits_with_sentence_overlap():
    sentences = [f"Rule {i} requires approval from the manager before the start date." for i in range(60)]
    windows = window_words(" ".join(sentences), max_words=100, overlap=30)
    assert len(windows) > 1
    assert all(len(w.split()) <= 100 for w in windows)
    for previous, current in pairwise(windows):
        last_sentence = previous.rsplit(". ", 1)[-1]
        assert current.startswith(last_sentence.split(" ", 2)[0])  # overlap starts the next window
        assert last_sentence in current
    assert all(w.endswith(".") for w in windows)  # never cut mid-sentence


def test_real_chunks_respect_max_words_and_snippets(docs):
    chunks = chunk_documents(docs)
    assert all(len(c.text.split()) <= MAX_WORDS for c in chunks)
    assert all(len(c.snippet) <= 241 for c in chunks)
    assert make_snippet("Short text.") == "Short text."


def test_remote_work_question_ranks_remote_policy_first(index):
    hits = index.search("work from another state", k=2)
    assert "remote_work_policy" in [h.doc_id for h in hits]
    assert hits[0].chunk_id and hits[0].snippet and hits[0].section


def test_document_and_source_type_filters(index):
    hits = index.search("annual leave", k=3, document_id="pto_policy")
    assert hits and {h.doc_id for h in hits} == {"pto_policy"}
    external = index.search("telework security", k=4, source_type="external_reference")
    assert external and {h.source_type for h in external} == {"external_reference"}


def test_gibberish_query_is_weak(index):
    hits = index.search("zxqv blorf wuggle", k=3)
    assert hits and all(h.weak for h in hits)
    assert not index.search("How many PTO days do I get after 5 years?", k=1)[0].weak


def test_get_section_and_list_documents(index):
    section = index.get_section("pto_policy", "annual pto entitlement")  # case-insensitive
    assert section and "15" in section["text"]
    docs = index.list_documents()
    assert len(docs) == 12 and {d["format"] for d in docs} == {"md", "txt", "pdf", "html"}


def test_manifest_records_build(index):
    manifest = index.manifest
    assert manifest["embedder"] == "tfidf"
    assert manifest["chunking"] == {"strategy": "heading-aware", "max_words": 350, "overlap_words": 60}
    assert len(manifest["corpus_sha256"]) == 64


def test_mismatched_query_embedder_is_rejected(index_base):
    other = TfidfEmbedder().fit(["a different vocabulary entirely"])
    with pytest.raises(IndexMismatchError):
        PolicyIndex.load(index_base / "tfidf", embedder=other)


def test_open_index_falls_back_to_tfidf(index_base):
    ix = open_index(index_base, preferred="gemini")  # no gemini index in this directory
    assert ix.manifest["embedder"] == "tfidf"
    ix.close()


def test_min_score_override(index_base):
    ix = PolicyIndex.load(index_base / "tfidf", min_score=0.99)
    assert all(h.weak for h in ix.search("PTO entitlement", k=2))
    ix.close()
