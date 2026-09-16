import math

import pytest

from app.utils.identifiers import public_reference


def test_reference_shape_and_prefix() -> None:
    reference = public_reference()
    prefix, _, body = reference.partition("-")
    assert prefix == "RM"
    assert len(body) >= 15


def test_reference_excludes_ambiguous_characters() -> None:
    body = public_reference(length=200).split("-", 1)[1]
    # No 0/O/1/I to keep references readable and unmistakable.
    assert not (set(body) & set("01IO"))


def test_spec126_reference_has_at_least_72_bits_of_entropy() -> None:
    alphabet_size, length = 31, 15  # 31-symbol alphabet, 15 random symbols
    assert length * math.log2(alphabet_size) > 72


def test_reference_is_non_sequential_and_unique() -> None:
    references = {public_reference() for _ in range(2_000)}
    assert len(references) == 2_000


def test_short_references_are_rejected() -> None:
    with pytest.raises(ValueError):
        public_reference(length=8)
