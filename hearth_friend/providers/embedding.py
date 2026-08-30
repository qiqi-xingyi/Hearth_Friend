"""Turning text into something attention can be paid over.

Local rather than through an API. An embedding call carries the text itself, so
sending memories out to be vectorised would ship exactly the material this whole
project exists to keep in one file on your machine -- a worse leak than a search
query, which at least gets abstracted first.

Optional. Without it the runtime falls back to keyword matching, so cloning the
repository does not oblige anyone to download a couple of gigabytes.
"""

from __future__ import annotations

import struct
from typing import Protocol, Sequence, runtime_checkable

DEFAULT_MODEL = "BAAI/bge-m3"


@runtime_checkable
class EmbeddingProvider(Protocol):
    model_id: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


class LocalEmbedding:
    """sentence-transformers, loaded once and kept resident.

    Loading is slow enough (tens of seconds for a large multilingual model) that
    it must not happen on the path of a reply. The runtime warms it in the
    background instead.
    """

    def __init__(self, model_id: str = DEFAULT_MODEL):
        self.model_id = model_id
        self._model = None
        self._dimension = 0

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return

        # A progress bar, a warning about anonymous downloads and a deprecation
        # notice all land on the terminal in the middle of a conversation. None
        # of them are anything to do with the person using this.
        import logging
        import os
        import warnings

        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        logging.getLogger("sentence_transformers").setLevel(logging.ERROR)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from sentence_transformers import SentenceTransformer

            # After the import and before the model is built: the library sets
            # levels on its own child loggers, which overrides anything put on
            # the parent beforehand, and the warning is emitted while loading
            # rather than while importing.
            for name in list(logging.root.manager.loggerDict):
                if name.startswith(("huggingface_hub", "transformers", "httpcore")):
                    logging.getLogger(name).setLevel(logging.ERROR)

            self._model = SentenceTransformer(self.model_id)
            # Renamed upstream; the old name still works and still warns.
            measure = getattr(
                self._model,
                "get_embedding_dimension",
                getattr(self._model, "get_sentence_embedding_dimension", None),
            )
            self._dimension = int(measure()) if measure else 0

    @property
    def dimension(self) -> int:
        self.load()
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        self.load()
        assert self._model is not None
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False
        )
        return [[float(x) for x in row] for row in vectors]


def build_embedding(config) -> LocalEmbedding | None:
    """None means keyword matching, which is a working system, not a failure."""
    name = getattr(config, "embedding_model", DEFAULT_MODEL)
    if not name or name.lower() in ("off", "none", "disabled"):
        return None
    return LocalEmbedding(name)
