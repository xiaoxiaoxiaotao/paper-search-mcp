# paper-search-mcp

paper-search-mcp is an MCP server for agents that need to search papers, read arXiv PDFs, align records across sources, and produce structured literature-analysis inputs.

The server currently integrates two paper sources:

- Semantic Scholar for citation-aware discovery and metadata lookup
- arXiv for recent papers, metadata lookup, and PDF text extraction

It also includes higher-level utilities for cross-source alignment, BibTeX export, and compact literature digests.

Chinese documentation is available in `README-zh.md`.

## MCP Tools

### `search_semantic_scholar`

Search Semantic Scholar and return normalized paper metadata sorted by citation count.

Parameters:

- `query`: Search query
- `max_results`: Maximum number of results, default `10`

### `get_semantic_scholar_paper`

Fetch detailed metadata for a Semantic Scholar paper by `paper_id`.

### `search_arxiv`

Search arXiv and return normalized metadata.

Parameters:

- `query`: Search query
- `max_results`: Maximum number of results, default `10`
- `sort_by`: `relevance`, `lastUpdatedDate`, or `submittedDate`
- `sort_order`: `ascending` or `descending`

### `get_arxiv_paper`

Fetch metadata for one arXiv paper using an arXiv ID, abstract URL, or PDF URL.

### `read_arxiv_paper`

Download an arXiv PDF, cache it locally, extract text from the first pages, and return a structured reading pack.

Parameters:

- `arxiv_id_or_url`: arXiv ID, abstract URL, or PDF URL
- `max_pages`: Maximum number of pages to extract, default `8`
- `max_characters`: Maximum number of extracted characters, default `20000`

### `export_bibtex`

Export a paper as BibTeX.

Parameters:

- `source`: `semantic_scholar` or `arxiv`
- `identifier`: Semantic Scholar `paper_id` or arXiv ID/URL

### `align_paper_by_title`

Search Semantic Scholar and arXiv by title and return exact normalized title matches across both sources.

Parameters:

- `title`: Paper title used for exact title alignment
- `semantic_scholar_max_results`: Search limit for Semantic Scholar, default `10`
- `arxiv_max_results`: Search limit for arXiv, default `10`

### `build_literature_digest`

Search across Semantic Scholar and arXiv, deduplicate overlapping papers, and return a compact literature-analysis bundle.

This is useful for downstream agent tasks such as:

- finding classic work versus recent work
- grouping methods into families
- comparing datasets, metrics, and limitations

## Installation

This project is designed to use `uv` for environment and dependency management.

```bash
uv sync
```

This creates `.venv` in the project directory and installs the project dependencies.

To include development dependencies as well:

```bash
uv sync --group dev
```

If you have a Semantic Scholar API key:

```bash
export S2_API_KEY=your_key_here
```

Optional environment variables:

- `S2_API_KEY`: Semantic Scholar API key
- `PAPER_MCP_HTTP_TIMEOUT`: HTTP timeout in seconds, default `30`
- `PAPER_MCP_USER_AGENT`: Custom user agent string
- `PAPER_MCP_CACHE_DIR`: Override the on-disk cache directory for downloaded PDFs

### Install As A Python Package

For local development or direct Python-based deployment:

```bash
pip install .
```

To install directly from a Git repository after you publish it:

```bash
pip install git+https://github.com/<your-org>/paper-search-mcp.git
```

If you publish to PyPI later, the runtime shape stays the same and the MCP entrypoint remains `paper-search-mcp`.

### Deploy With Docker

Build the image:

```bash
docker build -t paper-search-mcp .
```

Run the MCP server over stdio:

```bash
docker run -i --rm \
  -e S2_API_KEY=your_key_here \
  -v paper-search-cache:/root/.cache/paper-search-mcp \
  paper-search-mcp
```

The volume mount keeps the PDF cache across container restarts.

## Running The Server

Start the server directly:

```bash
uv run paper-search-mcp
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "uv",
      "args": ["run", "paper-search-mcp"],
      "cwd": "/home/tao/code/projects/paper-search-mcp"
    }
  }
}
```

Example MCP client configuration using Docker instead of a local Python environment:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "S2_API_KEY",
        "-v",
        "paper-search-cache:/root/.cache/paper-search-mcp",
        "paper-search-mcp"
      ]
    }
  }
}
```

If you want to launch the module explicitly:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "uv",
      "args": ["run", "python", "-m", "paper_search_mcp.server"],
      "cwd": "/home/tao/code/projects/paper-search-mcp"
    }
  }
}
```

## Notes

- Semantic Scholar is better for established, citation-rich papers.
- arXiv is better for recent work and full-text PDF reading.
- `build_literature_digest` reduces prompt assembly work for downstream agents.
- `read_arxiv_paper` returns text and analysis prompts instead of hard-coded conclusions.
- PDF downloads are cached on disk to avoid repeated arXiv fetches.
- An npm package is possible as a thin wrapper, but the primary runtime is still Python or Docker.

## Possible Extensions

- DOI / PMID / ACL Anthology / OpenAlex support
- citation graph and related-paper retrieval
- richer section-aware PDF chunking
- persistent metadata caching beyond PDFs