"""`GET|PUT /vocabulary`: the global glossary file (`VOCABULARY_FILE`, phase 19)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import Vocabulary
from vozata.vocabulary import VocabularyStore

router = APIRouter(tags=["vocabulary"])
Container = Annotated[ApiContainer, Depends(container)]


@router.get("/vocabulary", response_model=Vocabulary)
def get_vocabulary(c: Container) -> Vocabulary:
    try:
        return Vocabulary(terms=_store(c).read())
    except (OSError, UnicodeDecodeError) as error:
        raise ApiError(503, "vocabulary_failed", reason=error) from None


@router.put("/vocabulary", response_model=Vocabulary)
def put_vocabulary(body: Vocabulary, c: Container) -> Vocabulary:
    """Replace the terms; they come back cleaned (trimmed, no blanks or duplicates)."""
    try:
        return Vocabulary(terms=_store(c).write(body.terms))
    except OSError as error:
        raise ApiError(503, "vocabulary_failed", reason=error) from None


def _store(c: ApiContainer) -> VocabularyStore:
    return VocabularyStore(c.vocabulary_file())  # follows a `VOCABULARY_FILE` saved in settings
