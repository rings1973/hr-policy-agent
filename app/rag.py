from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import EMPLOYEE_FILE, POLICY_DIR, VECTOR_TOP_K


@dataclass
class PolicyChunk:
    document_id: str
    title: str
    section: str
    snippet: str
    content: str


class PolicyRAG:
    def __init__(self, policy_dir: Path | None = None):
        self.policy_dir = policy_dir or POLICY_DIR
        self.chunks: list[PolicyChunk] = self._load_policy_chunks()

    def _load_policy_chunks(self) -> list[PolicyChunk]:
        chunks: list[PolicyChunk] = []
        for path in sorted(self.policy_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            sections = self._split_sections(path.name, text)
            chunks.extend(sections)
        return chunks

    def _split_sections(self, filename: str, text: str) -> list[PolicyChunk]:
        lines = text.splitlines()
        title = filename.replace(".md", "").replace("_", " ").title()
        current_section = "Overview"
        buffer: list[str] = []
        chunks: list[PolicyChunk] = []

        for line in lines:
            if line.startswith("#"):
                if buffer:
                    content = "\n".join(buffer).strip()
                    if content:
                        chunks.append(
                            PolicyChunk(
                                document_id=filename,
                                title=title,
                                section=current_section,
                                snippet=content[:220],
                                content=content,
                            )
                        )
                if line.startswith("##"):
                    current_section = line.lstrip("#").strip() or current_section
                buffer = []
            else:
                buffer.append(line.strip())

        if buffer:
            content = "\n".join(buffer).strip()
            if content:
                chunks.append(
                    PolicyChunk(
                        document_id=filename,
                        title=title,
                        section=current_section,
                        snippet=content[:220],
                        content=content,
                    )
                )

        return chunks if chunks else [
            PolicyChunk(
                document_id=filename,
                title=title,
                section="Overview",
                snippet=text[:220],
                content=text,
            )
        ]

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        top_k = top_k or VECTOR_TOP_K
        query_lower = query.lower()
        ranked: list[tuple[float, PolicyChunk]] = []
        for chunk in self.chunks:
            score = 0.0
            text = f"{chunk.title} {chunk.section} {chunk.content}".lower()
            for token in query_lower.split():
                if token in text:
                    score += 1.5
            if query_lower in text:
                score += 2.5
            if score > 0:
                ranked.append((score, chunk))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "document_id": chunk.document_id,
                "title": chunk.title,
                "section": chunk.section,
                "snippet": chunk.snippet,
                "score": round(score, 2),
            }
            for score, chunk in ranked[:top_k]
        ]

    def get_document_section(self, document_id: str, section_name: str) -> dict[str, Any] | None:
        for chunk in self.chunks:
            if chunk.document_id == document_id and chunk.section == section_name:
                return {
                    "document_id": chunk.document_id,
                    "title": chunk.title,
                    "section": chunk.section,
                    "snippet": chunk.snippet,
                    "content": chunk.content,
                }
        return None


class EmployeeStore:
    def __init__(self, data_file: Path | None = None):
        self.data_file = data_file or EMPLOYEE_FILE
        self.data = self._read_json()

    def _read_json(self) -> dict[str, Any]:
        raw = self.data_file.read_text(encoding="utf-8")
        return json.loads(raw)

    def get_employee(self, employee_id: str) -> dict[str, Any] | None:
        for employee in self.data.get("employees", []):
            if employee.get("employee_id") == employee_id:
                return employee
        return None
