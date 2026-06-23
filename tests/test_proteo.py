"""Tests for mspy.mod_proteo digestion/fragmentation + obj_sequence."""

import pytest

import mspy
from mspy import mod_proteo

from .conftest import scalar


def _chain(peptide):
    return "".join(peptide.chain)


def test_sequence_mass_positive():
    seq = mspy.sequence("ACDEFGHIK")
    assert scalar(seq.mass(0)) > 0.0  # monoisotopic
    assert scalar(seq.mass(1)) >= scalar(seq.mass(0))  # average >= monoisotopic


def test_trypsin_digest_cleaves_after_k_and_r():
    seq = mspy.sequence("ACDEFGHIKLMNPQRSTVWY")
    peptides = mspy.digest(seq, "Trypsin", miscleavage=0)
    chains = [_chain(p) for p in peptides]
    assert "ACDEFGHIK" in chains
    assert "LMNPQR" in chains
    assert "STVWY" in chains


def test_trypsin_miscleavage_adds_longer_peptides():
    seq = mspy.sequence("ACDEFGHIKLMNPQRSTVWY")
    none = mspy.digest(seq, "Trypsin", miscleavage=0)
    one = mspy.digest(seq, "Trypsin", miscleavage=1)
    assert len(one) > len(none)
    # a miscleaved peptide spans two cleavage products
    assert any(_chain(p) == "ACDEFGHIKLMNPQR" for p in one)


def test_digest_unknown_enzyme_raises():
    with pytest.raises(KeyError):
        mspy.digest(mspy.sequence("ACDK"), "NotAnEnzyme")


def test_digest_non_sequence_raises():
    with pytest.raises(TypeError):
        mspy.digest("ACDK", "Trypsin")


def test_coverage_full_and_partial():
    assert mspy.mod_proteo.coverage([(1, 10)], 10) == pytest.approx(100.0)
    assert mspy.mod_proteo.coverage([(1, 5)], 10) == pytest.approx(50.0)


def test_coverage_empty_is_zero():
    assert mspy.mod_proteo.coverage([], 10) == 0.0


def test_fragment_by_series_produces_fragments():
    seq = mspy.sequence("ACDEFG")
    frags = mspy.fragment(seq, ["b", "y"])
    series = {f.fragmentSerie for f in frags}
    assert "b" in series and "y" in series
    assert len(frags) > 0


def test_fragmentserie_b_ion_count():
    seq = mspy.sequence("ACDEF")  # 5 residues
    b_ions = mod_proteo.fragmentserie(seq, "b")
    # b-ion series for an n-residue peptide has n-1 internal fragments
    assert len(b_ions) >= 1
    for frag in b_ions:
        assert frag.fragmentSerie == "b"
