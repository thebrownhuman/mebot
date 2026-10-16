"""Checks extracted resume items against the source text (filled in next)."""

from mebot.imports.pipelines import Extracted


def review(ex: Extracted, source: str) -> Extracted:
    return ex
