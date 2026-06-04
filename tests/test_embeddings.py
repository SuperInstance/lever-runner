"""Tests for position-aware and hash embedding functions."""

from __future__ import annotations

import numpy as np
import pytest

from lever_runner.store import hash_embed, position_aware_embed


class TestHashEmbed:
    def test_output_shape(self):
        result = hash_embed("check disk usage", dim=64)
        assert isinstance(result, list)
        assert len(result) == 64

    def test_normalized(self):
        result = np.array(hash_embed("check disk usage", dim=64))
        assert abs(np.linalg.norm(result) - 1.0) < 1e-5

    def test_deterministic(self):
        a = hash_embed("check disk usage", dim=64)
        b = hash_embed("check disk usage", dim=64)
        assert a == b

    def test_different_inputs_different_outputs(self):
        a = np.array(hash_embed("check disk usage", dim=64))
        b = np.array(hash_embed("check memory usage", dim=64))
        assert not np.allclose(a, b)


class TestPositionAwareEmbed:
    def test_output_shape(self):
        result = position_aware_embed("check disk usage", dim=64)
        assert isinstance(result, list)
        assert len(result) == 64

    def test_normalized(self):
        result = np.array(position_aware_embed("check disk usage", dim=64))
        assert abs(np.linalg.norm(result) - 1.0) < 1e-5

    def test_deterministic(self):
        a = position_aware_embed("check disk usage", dim=64)
        b = position_aware_embed("check disk usage", dim=64)
        assert a == b

    def test_position_matters(self):
        """Same words in different order should produce different embeddings."""
        a = np.array(position_aware_embed("disk check usage", dim=64))
        b = np.array(position_aware_embed("check disk usage", dim=64))
        assert not np.allclose(a, b)


class TestPositionAwareBetterThanHash:
    def test_semantic_similarity(self):
        """Position-aware should have higher similarity for semantically similar text."""
        hash_vec = np.array(hash_embed("check disk usage", dim=64))
        pos_vec = np.array(position_aware_embed("check disk usage", dim=64))

        hash_q = np.array(hash_embed("how much disk space is left", dim=64))
        pos_q = np.array(position_aware_embed("how much disk space is left", dim=64))

        hash_sim = np.dot(hash_vec, hash_q)
        pos_sim = np.dot(pos_vec, pos_q)

        assert pos_sim > hash_sim, (
            f"Position-aware ({pos_sim:.4f}) should beat hash ({hash_sim:.4f}) "
            f"for semantic similarity"
        )

    def test_same_word_shared_vocabulary(self):
        """Both texts about 'disk' should be closer under position-aware."""
        # "check disk usage" vs "show disk partitions" — share "disk"
        pos_a = np.array(position_aware_embed("check disk usage", dim=64))
        pos_b = np.array(position_aware_embed("show disk partitions", dim=64))

        # Random unrelated pair
        pos_c = np.array(position_aware_embed("ping google", dim=64))

        sim_related = np.dot(pos_a, pos_b)
        sim_unrelated = np.dot(pos_a, pos_c)

        assert sim_related > sim_unrelated, (
            "Related commands should be more similar than unrelated ones"
        )
