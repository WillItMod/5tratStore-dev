import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from axebc2_release_state import APP_DIGEST, APP_TAG, CORE_DIGEST, CORE_TAG, validate, validate_rendered_binds

class ReleaseStateTests(unittest.TestCase):
    def test_only_complete_prefinalization_is_accepted(self):
        core=f"{CORE_TAG}@{CORE_DIGEST}"
        text=f"{APP_TAG}@sha256:APP_CANDIDATE_DIGEST_REQUIRED\n{core}\n{core}"
        validate(text,"prefinalization")
        with self.assertRaises(ValueError): validate(text.replace(CORE_DIGEST,"sha256:"+"b"*64,1),"prefinalization")
    def test_only_complete_immutable_finalization_is_accepted(self):
        core=f"{CORE_TAG}@{CORE_DIGEST}"
        text=f"{APP_TAG}@{APP_DIGEST}\n{core}\n{core}"
        validate(text,"finalized")
        with self.assertRaises(ValueError): validate(text.replace(APP_DIGEST,"sha256:"+"a"*64),"finalized")
        with self.assertRaises(ValueError): validate(text.replace(CORE_DIGEST,"sha256:"+"d"*64,1),"finalized")
        with self.assertRaises(ValueError): validate(text+"\n_DIGEST_REQUIRED","finalized")
    def test_lifecycle_matrix_rejects_cross_phase_validation(self):
        core=f"{CORE_TAG}@{CORE_DIGEST}"
        pre=f"{APP_TAG}@sha256:APP_CANDIDATE_DIGEST_REQUIRED\n{core}\n{core}"
        final=f"{APP_TAG}@{APP_DIGEST}\n{core}\n{core}"
        validate(pre,"prefinalization"); validate(final,"finalized")
        with self.assertRaises(ValueError): validate(pre,"finalized")
        with self.assertRaises(ValueError): validate(final,"prefinalization")
    def test_hosted_compose_may_omit_false_bind_metadata(self):
        import tempfile
        with tempfile.TemporaryDirectory() as source:
            contract={"services":{"init":{"volumes":[{"type":"bind","source":source,"target":"/data","bind":{"create_host_path":False}}]}}}
            hosted={"services":{"init":{"volumes":[{"type":"bind","source":source,"target":"/data"}]}}}
            validate_rendered_binds(contract,hosted)
            hosted["services"]["init"]["volumes"][0]["bind"]={"create_host_path":True}
            with self.assertRaisesRegex(ValueError,"service=init.*source=.*target=/data"):
                validate_rendered_binds(contract,hosted)
