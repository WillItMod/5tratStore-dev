"""Bind independently verified MUX app releases to every install surface."""
import json
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class MuxPackageTests(unittest.TestCase):
    def test_verified_images_and_versions_reach_every_install_surface(self):
        release = json.loads((ROOT / "MUX-HASHRATE-2026-09-28.json").read_text())
        self.assertEqual(release["schemaVersion"], 1)
        expected = {"willitmod-dev-" + name for name in
                    ("btc", "bch", "bc2", "axebch2", "dgb", "xec", "ppc", "powpow")}
        self.assertEqual(set(release["apps"]), expected)
        for name, record in release["apps"].items():
            with self.subTest(app=name):
                app = ROOT / name
                self.assertRegex(record["sourceRevision"], r"^[0-9a-f]{40}$")
                self.assertEqual(record["platforms"], ["linux/amd64", "linux/arm64"])
                version = record["version"].removesuffix("-dev")
                self.assertRegex(record["imageRef"], r":" + re.escape(version) + r"-mux\." +
                                 record["sourceRevision"][:12] + r"@sha256:[0-9a-f]{64}$")
                for filename in ("umbrel-app.yml", "global-app.yml"):
                    path = app / filename
                    if path.exists():
                        manifest = yaml.safe_load(path.read_text())
                        self.assertEqual(manifest["id"], name)
                        self.assertEqual(manifest["version"], record["version"])
                for filename in ("docker-compose.yml", "docker-compose.yml.template"):
                    path = app / filename
                    if not path.exists():
                        continue
                    service = yaml.safe_load(path.read_text())["services"]["app"]
                    self.assertEqual(service["image"], record["imageRef"])
                    environment = service["environment"]
                    self.assertEqual(environment["MUX_IDENTITY_URL"],
                                     "http://172.17.0.1:21222/api/integrations/workers")
                    if "APP_VERSION" in environment:
                        self.assertEqual(environment["APP_VERSION"], record["version"])


if __name__ == "__main__":
    unittest.main()
