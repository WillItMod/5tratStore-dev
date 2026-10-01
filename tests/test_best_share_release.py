"""Template copied into Store/tests by prepare-best-share-store-update.py."""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest

import yaml
from test_pool_retention_release import APPS, previous_model

ROOT = Path(__file__).resolve().parents[1]
APP_IDS = {"willitmod-dev-" + suffix for suffix in ("bch", "axebch2", "btc", "fracattack", "bc2", "xec", "ppc")}


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class BestShareReleaseTests(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads((ROOT / "BEST-SHARE-2026-09-30.json").read_text())
        path = ROOT / self.receipt["baselineFile"]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.receipt["baselineSha256"])
        self.baseline = json.loads(path.read_text())
        self.current = json.loads((ROOT / "DIRECT-HASHRATE-2026-09-30.json").read_text())

    def test_exact_seven_new_verified_candidates_and_no_other_app_changes(self):
        self.assertEqual(set(self.receipt["apps"]), APP_IDS)
        expected = copy.deepcopy(self.baseline["release"])
        for app_id, fresh in self.receipt["apps"].items():
            old = expected["apps"][app_id]
            self.assertNotEqual(fresh["sourceRevision"], old["sourceRevision"])
            self.assertGreater(tuple(map(int, fresh["version"].removesuffix("-dev").split("."))),
                               tuple(map(int, old["version"].removesuffix("-dev").split("."))))
            self.assertEqual(fresh["platforms"], ["linux/amd64", "linux/arm64"])
            self.assertEqual(set(fresh["platformDigests"]), {"amd64", "arm64"})
            for value in fresh["platformDigests"].values():
                self.assertRegex(value, r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(fresh["imageRef"], r":" + re.escape(fresh["version"].removesuffix("-dev")) +
                             r"-mux\." + fresh["sourceRevision"][:12] + r"@sha256:[0-9a-f]{64}$")
            for field in ("runtimeTestsPassed", "provenanceVerified", "sbomVerified"):
                self.assertIs(fresh[field], True)
            expected["apps"][app_id] = fresh
            for row in expected["runtimeContracts"][app_id]["changes"]:
                path = tuple(row["path"])
                if path == ("services", "app", "image"):
                    row["after"] = fresh["imageRef"]
                elif path == ("services", "app", "environment", "APP_VERSION"):
                    row["after"] = fresh["version"]
                else:
                    self.fail("Unexpected reviewed historical runtime change: " + repr(path))
            for filename in ("umbrel-app.yml", "global-app.yml"):
                manifest_path = ROOT / app_id / filename
                if manifest_path.exists():
                    manifest = yaml.safe_load(manifest_path.read_text())
                    self.assertEqual(manifest["version"], APPS.get(app_id,fresh)["version"])
                    self.assertIn("Best-share records", manifest["releaseNotes"])
                    self.assertIn("Direct and mixed miners", manifest["releaseNotes"])
        self.assertEqual(self.current, expected, "Other apps or historical receipt fields changed")

    def test_full_compose_contract_changes_only_app_pin_and_existing_version(self):
        self.assertEqual(set(self.receipt["runtimeContracts"]), APP_IDS)
        for app_id, surfaces in self.receipt["runtimeContracts"].items():
            self.assertIn("docker-compose.yml", surfaces)
            for filename, contract in surfaces.items():
                with self.subTest(app=app_id, file=filename):
                    current = yaml.safe_load((ROOT / app_id / filename).read_text())
                    current = previous_model(app_id,current,filename)
                    restored = copy.deepcopy(current)
                    allowed = {("services", "app", "image"), ("services", "app", "environment", "APP_VERSION")}
                    self.assertEqual(digest(current), contract["afterComposeSha256"])
                    self.assertEqual(len({tuple(row["path"]) for row in contract["changes"]}), len(contract["changes"]))
                    for row in contract["changes"]:
                        self.assertIn(tuple(row["path"]), allowed)
                        target = restored
                        for part in row["path"][:-1]:
                            target = target[part]
                        self.assertEqual(target[row["path"][-1]], row["after"])
                        target[row["path"][-1]] = row["before"]
                    self.assertEqual(digest(restored), contract["baselineComposeSha256"])

    def test_only_targeted_current_contract_entries_change(self):
        current = json.loads((ROOT / "UMBREL-CONTRACTS-2026-09-30.json").read_text())
        expected = copy.deepcopy(self.baseline["contracts"])
        for app_id, fresh in self.receipt["apps"].items():
            expected["apps"][app_id] = {
                "package_version": fresh["version"],
                "compose_contract_sha256": self.receipt["runtimeContracts"][app_id]["docker-compose.yml"]["afterComposeSha256"],
            }
        self.assertEqual(current, expected, "Unrelated or historical Umbrel contract fields changed")


if __name__ == "__main__":
    unittest.main()
