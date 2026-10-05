from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
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
    def __init__(self, policy_dir: Path | None = None, index_file: Path | None = None):
        self.policy_dir = policy_dir or POLICY_DIR
        self.index_file = index_file or self.policy_dir.parent / "policy_index.sqlite3"
        self.chunks: list[PolicyChunk] = self._load_policy_chunks()
        self.vectors = self._embed_chunks()
        self._persist_index()

    def _load_policy_chunks(self) -> list[PolicyChunk]:
        chunks: list[PolicyChunk] = []
        paths = sorted((*self.policy_dir.glob("*.md"), *self.policy_dir.glob("*.txt")))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            sections = self._split_sections(path.name, text) if path.suffix.lower() == ".md" else [
                PolicyChunk(
                    document_id=path.name,
                    title=path.stem.replace("_", " ").title(),
                    section="Overview",
                    snippet=text.strip()[:220],
                    content=text.strip(),
                )
            ]
            chunks.extend(sections)
        return chunks

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _embed_chunks(self) -> list[dict[str, float]]:
        term_counts = [
            Counter(self._tokens(f"{chunk.title} {chunk.section} {chunk.content}"))
            for chunk in self.chunks
        ]
        document_frequency: Counter[str] = Counter()
        for counts in term_counts:
            document_frequency.update(counts.keys())

        document_count = max(len(term_counts), 1)
        vectors: list[dict[str, float]] = []
        for counts in term_counts:
            vector = {
                token: (1 + math.log(count)) * (1 + math.log(document_count / document_frequency[token]))
                for token, count in counts.items()
            }
            magnitude = math.sqrt(sum(weight * weight for weight in vector.values())) or 1.0
            vectors.append({token: weight / magnitude for token, weight in vector.items()})
        return vectors

    def _persist_index(self) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.index_file) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS policy_chunks ("
                "id INTEGER PRIMARY KEY, document_id TEXT, title TEXT, section TEXT, "
                "snippet TEXT, content TEXT, embedding_json TEXT)"
            )
            connection.execute("DELETE FROM policy_chunks")
            connection.executemany(
                "INSERT INTO policy_chunks "
                "(id, document_id, title, section, snippet, content, embedding_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        index,
                        chunk.document_id,
                        chunk.title,
                        chunk.section,
                        chunk.snippet,
                        chunk.content,
                        json.dumps(self.vectors[index], sort_keys=True),
                    )
                    for index, chunk in enumerate(self.chunks)
                ],
            )

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
        top_k = VECTOR_TOP_K if top_k is None else top_k
        query_counts = Counter(self._tokens(query))
        document_frequency = Counter()
        for vector in self.vectors:
            document_frequency.update(vector.keys())
        document_count = max(len(self.vectors), 1)
        query_vector = {
            token: (1 + math.log(count)) * (1 + math.log(document_count / document_frequency[token]))
            for token, count in query_counts.items()
            if token in document_frequency
        }
        magnitude = math.sqrt(sum(weight * weight for weight in query_vector.values())) or 1.0
        query_vector = {token: weight / magnitude for token, weight in query_vector.items()}
        ranked = [
            (sum(query_vector.get(token, 0.0) * weight for token, weight in vector.items()), chunk)
            for chunk, vector in zip(self.chunks, self.vectors)
        ]
        ranked = [(score, chunk) for score, chunk in ranked if score > 0]
        ranked.sort(key=lambda item: (-item[0], item[1].document_id, item[1].section))
        return [
            {
                "document_id": chunk.document_id,
                "title": chunk.title,
                "section": chunk.section,
                "snippet": chunk.snippet,
                "score": round(score, 4),
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
