"""Load the policy corpus (md, txt, pdf, html) into documents made of headed sections."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

SKIP_FILES = {"SOURCES.md", "README.md"}
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf", ".html"}
COMPANY_POLICY = "company_policy"
EXTERNAL_REFERENCE = "external_reference"


@dataclass
class Section:
    heading: str
    text: str
    page: int | None = None


@dataclass
class Document:
    doc_id: str
    title: str
    format: str
    source_type: str
    source_file: str
    source_url: str | None = None
    sections: list[Section] = field(default_factory=list)


def load_documents(policy_dir: Path) -> list[Document]:
    """Load every supported file in policy_dir, sorted by name so ingestion is deterministic."""
    provenance = _read_provenance(policy_dir / "SOURCES.md")
    docs = []
    for path in corpus_files(policy_dir):
        loader = _LOADERS[path.suffix.lower()]
        doc = loader(path)
        source_type, url = provenance.get(path.name, (None, None))
        # An explicit marker in the file (HTML <meta>) wins over SOURCES.md; otherwise default
        # to company policy, since every external document is listed in SOURCES.md.
        doc.source_type = doc.source_type or source_type or COMPANY_POLICY
        doc.source_url = doc.source_url or url
        doc.sections = [s for s in doc.sections if s.text.strip()]
        docs.append(doc)
    return docs


def corpus_files(policy_dir: Path) -> list[Path]:
    return sorted(
        p for p in policy_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and p.name not in SKIP_FILES
    )


def _read_provenance(sources_md: Path) -> dict[str, tuple[str, str | None]]:
    """Map file name -> (source_type, url) from the SOURCES.md table's Origin column."""
    if not sources_md.exists():
        return {}
    provenance = {}
    for line in sources_md.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[0].startswith("`"):
            continue
        name, origin = cells[0].strip("`"), cells[2]
        source_type = COMPANY_POLICY if origin.lower().startswith("synthetic") else EXTERNAL_REFERENCE
        url = re.search(r"https?://\S+", origin)
        provenance[name] = (source_type, url.group(0).rstrip(".,)") if url else None)
    return provenance


def _humanize(stem: str) -> str:
    return stem.replace("_", " ").title()


def _squash(text: str) -> str:
    """Collapse all whitespace, including non-breaking spaces, to single spaces."""
    return " ".join(text.split())


def _load_markdown(path: Path) -> Document:
    lines = path.read_text(encoding="utf-8").splitlines()
    title, title_found = _humanize(path.stem), False
    sections: list[Section] = []
    heading, buffer = "Overview", []
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.*)", line)
        if match:
            if len(match.group(1)) == 1 and not title_found:
                title, title_found = match.group(2).strip(), True
                continue
            sections.append(Section(heading, "\n".join(buffer).strip()))
            heading, buffer = match.group(2).strip(), []
        else:
            buffer.append(line)
    sections.append(Section(heading, "\n".join(buffer).strip()))
    return Document(path.stem, title, "md", "", path.name, sections=sections)


def _is_txt_heading(line: str, next_line: str) -> bool:
    """Plain-text headings are short lines with no sentence punctuation, followed by body text."""
    words = line.split()
    return (
        0 < len(words) <= 8
        and not line.rstrip().endswith((".", "!", "?", ",", ";"))
        and bool(next_line.strip())
    )


def _load_text(path: Path) -> Document:
    lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines()]
    non_empty = [i for i, ln in enumerate(lines) if ln.strip()]
    title = lines[non_empty[0]].strip() if non_empty else _humanize(path.stem)
    sections: list[Section] = []
    heading, buffer = "Overview", []
    for i, line in enumerate(lines):
        if non_empty and i == non_empty[0]:
            continue
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        if _is_txt_heading(line, next_line):
            sections.append(Section(heading, "\n".join(buffer).strip()))
            heading, buffer = line.strip(), []
        else:
            buffer.append(line)
    sections.append(Section(heading, "\n".join(buffer).strip()))
    return Document(path.stem, title, "txt", "", path.name, sections=sections)


# Lines repeated on every page of the NIST excerpt (running header and availability notice).
_PDF_BOILERPLATE = re.compile(
    r"^(NIST SP 800-46 REV\. 2 GUIDE TO ENTERPRISE TELEWORK,|REMOTE ACCESS, AND BYOD SECURITY"
    r"|This publication is available free of charge from:.*|\d{1,3})$"
)


def _clean_pdf_text(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not _PDF_BOILERPLATE.match(ln)]
    # Re-join words hyphenated across line breaks, then collapse hard-wrapped lines.
    joined = re.sub(r"(\w)-\n(\w)", r"\1\2", "\n".join(lines))
    return re.sub(r"[ \t]*\n[ \t]*", " ", joined).strip()


def _load_pdf(path: Path) -> Document:
    reader = PdfReader(path)
    meta = reader.metadata or {}
    title = str(meta.get("/Title") or _humanize(path.stem))
    sections = [
        Section(f"Page {n}", _clean_pdf_text(page.extract_text() or ""), page=n)
        for n, page in enumerate(reader.pages, start=1)
    ]
    return Document(path.stem, title, "pdf", "", path.name, sections=sections)


def _load_html(path: Path) -> Document:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    meta = {m.get("name"): m.get("content") for m in soup.find_all("meta") if m.get("name")}
    title = soup.title.get_text(strip=True) if soup.title else _humanize(path.stem)
    body = soup.body or soup
    sections: list[Section] = []
    heading, buffer = "Overview", []
    for element in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr", "caption"]):
        if element.name in {"h1", "h2", "h3", "h4"}:
            sections.append(Section(heading, "\n".join(buffer).strip()))
            heading, buffer = element.get_text(" ", strip=True), []
        elif element.find_parent(["li", "tr"]) is None:
            if element.name == "tr":
                # Table rows become "cell | cell" lines so the accrual table stays readable.
                text = " | ".join(_squash(c.get_text(" ")) for c in element.find_all(["th", "td"]))
            else:
                text = _squash(element.get_text(" "))
            if text:
                buffer.append(text)
    sections.append(Section(heading, "\n".join(buffer).strip()))
    return Document(path.stem, title, "html", meta.get("source_type") or "", path.name,
                    source_url=meta.get("source"), sections=sections)


_LOADERS = {".md": _load_markdown, ".txt": _load_text, ".pdf": _load_pdf, ".html": _load_html}
