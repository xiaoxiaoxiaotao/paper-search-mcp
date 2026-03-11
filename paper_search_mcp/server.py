from __future__ import annotations

import io
import os
import re
import time
import warnings
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import backoff
import requests
from mcp.server.fastmcp import FastMCP
from pypdf import PdfReader


SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_DETAILS_URL = "https://api.semanticscholar.org/graph/v1/paper/{}"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_ABS_URL = "https://arxiv.org/abs/{}"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{}.pdf"
DEFAULT_TIMEOUT = float(os.getenv("PAPER_MCP_HTTP_TIMEOUT", "30"))
DEFAULT_USER_AGENT = os.getenv(
    "PAPER_MCP_USER_AGENT",
    "paper-search-mcp/0.1.0 (+https://github.com/modelcontextprotocol)",
)

ARXIV_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def on_backoff(details: dict[str, Any]) -> None:
    print(
        f"Backing off {details['wait']:0.1f} seconds after {details['tries']} tries "
        f"calling {details['target'].__name__} at {time.strftime('%X')}"
    )


@dataclass(slots=True)
class PaperRecord:
    source: str
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    url: str
    pdf_url: str | None = None
    citation_count: int | None = None
    published: str | None = None
    updated: str | None = None
    categories: list[str] | None = None
    external_ids: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PaperService:
    def __init__(self) -> None:
        self.semantic_scholar_api_key = os.getenv("S2_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        if not self.semantic_scholar_api_key:
            warnings.warn(
                "No Semantic Scholar API key found. Requests will be subject to stricter rate limits. "
                "Set S2_API_KEY for higher limits.",
                stacklevel=2,
            )

    @backoff.on_exception(
        backoff.expo,
        (requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.Timeout),
        on_backoff=on_backoff,
        max_time=60,
    )
    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        response = self.session.get(url, timeout=DEFAULT_TIMEOUT, **kwargs)
        response.raise_for_status()
        return response

    def _semantic_scholar_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.semantic_scholar_api_key:
            headers["X-API-KEY"] = self.semantic_scholar_api_key
        return headers

    def search_semantic_scholar(self, query: str, max_results: int = 10) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query must not be empty")

        response = self._get(
            SEMANTIC_SCHOLAR_SEARCH_URL,
            headers=self._semantic_scholar_headers(),
            params={
                "query": query,
                "limit": max_results,
                "fields": (
                    "paperId,title,authors,venue,year,abstract,url,openAccessPdf,citationCount,externalIds"
                ),
            },
        )
        payload = response.json()
        papers = [self._normalize_semantic_scholar_paper(item) for item in payload.get("data", [])]
        papers.sort(key=lambda item: item.citation_count or 0, reverse=True)
        return {
            "source": "semantic_scholar",
            "query": query,
            "total": payload.get("total", len(papers)),
            "papers": [paper.to_dict() for paper in papers],
        }

    def get_semantic_scholar_paper(self, paper_id: str) -> dict[str, Any]:
        if not paper_id.strip():
            raise ValueError("paper_id must not be empty")

        response = self._get(
            SEMANTIC_SCHOLAR_DETAILS_URL.format(paper_id),
            headers=self._semantic_scholar_headers(),
            params={
                "fields": (
                    "paperId,title,authors,venue,year,abstract,url,openAccessPdf,citationCount,"
                    "referenceCount,influentialCitationCount,externalIds,publicationDate"
                )
            },
        )
        record = self._normalize_semantic_scholar_paper(response.json())
        data = record.to_dict()
        data["source"] = "semantic_scholar"
        return data

    def search_arxiv(
        self,
        query: str,
        max_results: int = 10,
        sort_by: str = "relevance",
        sort_order: str = "descending",
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query must not be empty")

        response = self._get(
            ARXIV_API_URL,
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max_results,
                "sortBy": sort_by,
                "sortOrder": sort_order,
            },
        )
        papers = self._parse_arxiv_feed(response.text)
        return {
            "source": "arxiv",
            "query": query,
            "total": len(papers),
            "papers": [paper.to_dict() for paper in papers],
        }

    def get_arxiv_paper(self, arxiv_id_or_url: str) -> dict[str, Any]:
        arxiv_id = self._extract_arxiv_id(arxiv_id_or_url)
        response = self._get(ARXIV_API_URL, params={"id_list": arxiv_id})
        papers = self._parse_arxiv_feed(response.text)
        if not papers:
            raise ValueError(f"No arXiv paper found for identifier: {arxiv_id_or_url}")
        return papers[0].to_dict()

    def read_arxiv_paper(
        self,
        arxiv_id_or_url: str,
        max_pages: int = 8,
        max_characters: int = 20000,
    ) -> dict[str, Any]:
        paper = self.get_arxiv_paper(arxiv_id_or_url)
        pdf_url = paper.get("pdf_url")
        if not pdf_url:
            raise ValueError(f"Paper does not expose a PDF URL: {arxiv_id_or_url}")

        response = self._get(pdf_url)
        pdf_reader = PdfReader(io.BytesIO(response.content))
        extracted_pages: list[dict[str, Any]] = []
        chunks: list[str] = []

        for index, page in enumerate(pdf_reader.pages[:max_pages], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                extracted_pages.append({"page": index, "characters": len(text)})
                chunks.append(text)

        combined_text = "\n\n".join(chunks)
        truncated_text = combined_text[:max_characters]

        return {
            "paper": paper,
            "pages_read": len(extracted_pages),
            "page_stats": extracted_pages,
            "text": truncated_text,
            "truncated": len(combined_text) > len(truncated_text),
            "suggested_analysis_prompts": [
                "Summarize the paper's research question, method, and main findings.",
                "Identify assumptions, limitations, and potential failure modes.",
                "Compare this paper with prior work in the same area.",
                "Extract datasets, benchmarks, and evaluation metrics if present.",
            ],
        }

    def build_literature_digest(
        self,
        query: str,
        max_results_per_source: int = 5,
        include_semantic_scholar: bool = True,
        include_arxiv: bool = True,
    ) -> dict[str, Any]:
        if not include_semantic_scholar and not include_arxiv:
            raise ValueError("At least one source must be enabled")

        collected: list[PaperRecord] = []
        source_summaries: list[dict[str, Any]] = []

        if include_semantic_scholar:
            semantic_payload = self.search_semantic_scholar(query, max_results=max_results_per_source)
            semantic_papers = [self._paper_from_dict(item) for item in semantic_payload["papers"]]
            collected.extend(semantic_papers)
            source_summaries.append(
                {"source": "semantic_scholar", "count": len(semantic_papers)}
            )

        if include_arxiv:
            arxiv_payload = self.search_arxiv(query, max_results=max_results_per_source)
            arxiv_papers = [self._paper_from_dict(item) for item in arxiv_payload["papers"]]
            collected.extend(arxiv_papers)
            source_summaries.append({"source": "arxiv", "count": len(arxiv_papers)})

        unique: dict[str, PaperRecord] = {}
        for paper in collected:
            key = self._dedupe_key(paper)
            if key not in unique:
                unique[key] = paper

        ranked = sorted(
            unique.values(),
            key=lambda item: (
                item.citation_count or 0,
                item.year or 0,
                item.title.lower(),
            ),
            reverse=True,
        )

        return {
            "query": query,
            "sources": source_summaries,
            "paper_count": len(ranked),
            "papers": [paper.to_dict() for paper in ranked],
            "analysis_hints": [
                "Group papers by problem setting and methodological family.",
                "Check whether the most cited papers are still aligned with recent arXiv directions.",
                "Use the abstracts to extract differences in data, evaluation, and assumptions.",
            ],
        }

    def _normalize_semantic_scholar_paper(self, raw: dict[str, Any]) -> PaperRecord:
        open_access_pdf = raw.get("openAccessPdf") or {}
        external_ids = raw.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv")
        url = raw.get("url") or (ARXIV_ABS_URL.format(arxiv_id) if arxiv_id else "")
        pdf_url = open_access_pdf.get("url") or (ARXIV_PDF_URL.format(arxiv_id) if arxiv_id else None)
        return PaperRecord(
            source="semantic_scholar",
            paper_id=raw.get("paperId", ""),
            title=(raw.get("title") or "").strip(),
            authors=[author.get("name", "Unknown") for author in raw.get("authors", [])],
            year=raw.get("year"),
            venue=(raw.get("venue") or None),
            abstract=(raw.get("abstract") or None),
            url=url,
            pdf_url=pdf_url,
            citation_count=raw.get("citationCount"),
            external_ids=external_ids or None,
        )

    def _parse_arxiv_feed(self, xml_text: str) -> list[PaperRecord]:
        root = ElementTree.fromstring(xml_text)
        papers: list[PaperRecord] = []

        for entry in root.findall("atom:entry", ARXIV_NAMESPACES):
            entry_id = (entry.findtext("atom:id", default="", namespaces=ARXIV_NAMESPACES) or "").strip()
            title = self._clean_whitespace(
                entry.findtext("atom:title", default="", namespaces=ARXIV_NAMESPACES)
            )
            summary = self._clean_whitespace(
                entry.findtext("atom:summary", default="", namespaces=ARXIV_NAMESPACES)
            )
            published = entry.findtext("atom:published", default=None, namespaces=ARXIV_NAMESPACES)
            updated = entry.findtext("atom:updated", default=None, namespaces=ARXIV_NAMESPACES)
            authors = [
                self._clean_whitespace(author.findtext("atom:name", default="Unknown", namespaces=ARXIV_NAMESPACES))
                for author in entry.findall("atom:author", ARXIV_NAMESPACES)
            ]
            categories = [category.attrib.get("term", "") for category in entry.findall("atom:category", ARXIV_NAMESPACES)]

            arxiv_id = self._extract_arxiv_id(entry_id)
            pdf_url = None
            for link in entry.findall("atom:link", ARXIV_NAMESPACES):
                if link.attrib.get("title") == "pdf":
                    pdf_url = link.attrib.get("href")
                    break

            papers.append(
                PaperRecord(
                    source="arxiv",
                    paper_id=arxiv_id,
                    title=title,
                    authors=authors,
                    year=int(published[:4]) if published else None,
                    venue="arXiv",
                    abstract=summary,
                    url=entry_id or ARXIV_ABS_URL.format(arxiv_id),
                    pdf_url=pdf_url or ARXIV_PDF_URL.format(arxiv_id),
                    published=published,
                    updated=updated,
                    categories=categories,
                )
            )

        return papers

    def _extract_arxiv_id(self, arxiv_id_or_url: str) -> str:
        value = arxiv_id_or_url.strip()
        if not value:
            raise ValueError("arXiv identifier must not be empty")

        if value.startswith("http://") or value.startswith("https://"):
            parsed = urlparse(value)
            path = parsed.path.strip("/")
            if path.startswith("abs/"):
                identifier = path[len("abs/") :]
            elif path.startswith("pdf/"):
                identifier = path[len("pdf/") :]
            else:
                identifier = path.rsplit("/", maxsplit=1)[-1]
        else:
            identifier = value

        return identifier.removesuffix(".pdf")

    def _paper_from_dict(self, payload: dict[str, Any]) -> PaperRecord:
        return PaperRecord(
            source=payload["source"],
            paper_id=payload["paper_id"],
            title=payload["title"],
            authors=list(payload.get("authors") or []),
            year=payload.get("year"),
            venue=payload.get("venue"),
            abstract=payload.get("abstract"),
            url=payload["url"],
            pdf_url=payload.get("pdf_url"),
            citation_count=payload.get("citation_count"),
            published=payload.get("published"),
            updated=payload.get("updated"),
            categories=list(payload.get("categories") or []) or None,
            external_ids=dict(payload.get("external_ids") or {}) or None,
        )

    def _dedupe_key(self, paper: PaperRecord) -> str:
        arxiv_id = self._find_arxiv_id(paper)
        if arxiv_id:
            return f"arxiv:{arxiv_id}"
        normalized = re.sub(r"\W+", "", paper.title.lower())
        return normalized or f"{paper.source}:{paper.paper_id}"

    def _find_arxiv_id(self, paper: PaperRecord) -> str | None:
        if paper.source == "arxiv" and paper.paper_id:
            return paper.paper_id

        external_ids = paper.external_ids or {}
        if external_ids.get("ArXiv"):
            return external_ids["ArXiv"]

        for candidate in (paper.url, paper.pdf_url):
            if candidate and "arxiv.org" in candidate:
                return self._extract_arxiv_id(candidate)

        return None

    def _clean_whitespace(self, text: str | None) -> str:
        return re.sub(r"\s+", " ", text or "").strip()


service = PaperService()
mcp = FastMCP("paper-search")


@mcp.tool()
def search_semantic_scholar(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search Semantic Scholar for papers and return normalized metadata sorted by citation count."""
    return service.search_semantic_scholar(query=query, max_results=max_results)


@mcp.tool()
def get_semantic_scholar_paper(paper_id: str) -> dict[str, Any]:
    """Fetch detailed metadata for a Semantic Scholar paper by paper ID."""
    return service.get_semantic_scholar_paper(paper_id=paper_id)


@mcp.tool()
def search_arxiv(
    query: str,
    max_results: int = 10,
    sort_by: str = "relevance",
    sort_order: str = "descending",
) -> dict[str, Any]:
    """Search arXiv and return normalized metadata for matching papers."""
    return service.search_arxiv(
        query=query,
        max_results=max_results,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@mcp.tool()
def get_arxiv_paper(arxiv_id_or_url: str) -> dict[str, Any]:
    """Fetch normalized metadata for a specific arXiv paper using an arXiv ID, abs URL, or PDF URL."""
    return service.get_arxiv_paper(arxiv_id_or_url=arxiv_id_or_url)


@mcp.tool()
def read_arxiv_paper(
    arxiv_id_or_url: str,
    max_pages: int = 8,
    max_characters: int = 20000,
) -> dict[str, Any]:
    """Download an arXiv PDF, extract text from the first pages, and return a reading pack for analysis."""
    return service.read_arxiv_paper(
        arxiv_id_or_url=arxiv_id_or_url,
        max_pages=max_pages,
        max_characters=max_characters,
    )


@mcp.tool()
def build_literature_digest(
    query: str,
    max_results_per_source: int = 5,
    include_semantic_scholar: bool = True,
    include_arxiv: bool = True,
) -> dict[str, Any]:
    """Search across sources, deduplicate overlapping papers, and return a compact literature review digest."""
    return service.build_literature_digest(
        query=query,
        max_results_per_source=max_results_per_source,
        include_semantic_scholar=include_semantic_scholar,
        include_arxiv=include_arxiv,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()