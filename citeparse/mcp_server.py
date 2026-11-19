"""MCP server: lets an agent parse a reference list and check it for citations that point to no real work.

    pip install "citeparse[mcp]"
    claude mcp add citeparse -- citeparse-mcp
"""
from __future__ import annotations

import json
import os

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

mcp = _Server("citeparse")
_parser = None


def _p():
    global _parser
    if _parser is None:
        from . import Parser
        _parser = Parser(os.environ.get("CITEPARSE_MODEL", "hedwigai/citeparse-32m"))
    return _parser


def _lines(references: str) -> list[str]:
    return [l.strip() for l in references.splitlines() if l.strip()][:500]


@mcp.tool()
def parse_references(references: str, format: str = "csl-json") -> str:
    """Parse reference strings (one per line) into structured records. format: "csl-json" or "bibtex".
    Runs a small local model; nothing is sent anywhere."""
    lines = _lines(references)
    items = _p().parse(lines)
    if format == "bibtex":
        from .__main__ import bibtex
        return "\n\n".join(bibtex(it, i) for i, it in enumerate(items))
    return json.dumps(items, ensure_ascii=False, indent=1)


@mcp.tool()
def check_references(references: str) -> str:
    """Check a reference list (one per line) for citations that point to no real work, such as invented
    references in AI-written text. Each is parsed locally, then looked up on Crossref, DataCite and OpenAlex.
    Verdicts: ok, mismatch (the DOI or title exists but authors/year/title disagree), bad_doi (DOI not
    registered), not_found (no close record; check by hand, since theses and old books are often unindexed)."""
    from .check import check, report
    lines = _lines(references)
    res = check(_p().parse(lines), lines, os.environ.get("CITEPARSE_MAILTO"))
    return report(res) + "\n\n" + json.dumps(res, ensure_ascii=False)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
