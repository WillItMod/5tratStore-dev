import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from axebc2_release_state import APP_TAG, CORE_TAG, validate

class ReleaseStateTests(unittest.TestCase):
    def test_only_complete_prefinalization_is_accepted(self):
        text=f"{APP_TAG}@sha256:APP_CANDIDATE_DIGEST_REQUIRED\n{CORE_TAG}@sha256:CORE31_CANDIDATE_DIGEST_REQUIRED\n{CORE_TAG}@sha256:CORE31_CANDIDATE_DIGEST_REQUIRED"
        validate(text,"prefinalization")
        with self.assertRaises(ValueError): validate(text.replace("CORE31_CANDIDATE_DIGEST_REQUIRED","a"*64,1),"prefinalization")
    def test_only_complete_immutable_finalization_is_accepted(self):
        a="sha256:"+"a"*64; c="sha256:"+"c"*64
        text=f"{APP_TAG}@{a}\n{CORE_TAG}@{c}\n{CORE_TAG}@{c}"
        validate(text,"finalized")
        with self.assertRaises(ValueError): validate(text.replace(c,"sha256:"+"d"*64,1),"finalized")
        with self.assertRaises(ValueError): validate(text+"\n_DIGEST_REQUIRED","finalized")
    def test_lifecycle_matrix_rejects_cross_phase_validation(self):
        pre=f"{APP_TAG}@sha256:APP_CANDIDATE_DIGEST_REQUIRED\n{CORE_TAG}@sha256:CORE31_CANDIDATE_DIGEST_REQUIRED\n{CORE_TAG}@sha256:CORE31_CANDIDATE_DIGEST_REQUIRED"
        final=f"{APP_TAG}@sha256:{'a'*64}\n{CORE_TAG}@sha256:{'c'*64}\n{CORE_TAG}@sha256:{'c'*64}"
        validate(pre,"prefinalization"); validate(final,"finalized")
        with self.assertRaises(ValueError): validate(pre,"finalized")
        with self.assertRaises(ValueError): validate(final,"prefinalization")
