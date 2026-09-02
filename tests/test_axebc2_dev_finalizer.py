import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/finalize-axebc2-0.1.10-dev.sh"
COMPOSE = ROOT / "willitmod-dev-bc2/docker-compose.yml"
APP_DIGEST = "sha256:" + "a" * 64
CORE_DIGEST = "sha256:" + "b" * 64
CORE_TAG = "31.1.0-rc.cdf44542dde2"

class AxeBC2DevFinalizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="axebc2-dev-finalizer-")
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir(); (self.root / "willitmod-dev-bc2").mkdir()
        shutil.copy2(SCRIPT, self.root / "scripts" / SCRIPT.name)
        shutil.copy2(COMPOSE, self.root / "willitmod-dev-bc2/docker-compose.yml")
        self.original = (self.root / "willitmod-dev-bc2/docker-compose.yml").read_bytes()
        self.log = self.root / "docker.log"
        self.fake = self.root / "docker"
        self.fake.write_text("""#!/bin/sh
set -eu
printf '%s\\n' "$*" >>"$FAKE_DOCKER_LOG"
config="$2"; [ "$1" = --config ]; [ "$(cat "$config/config.json")" = '{"auths":{}}' ]; shift 2
if [ "$1 $2" = 'buildx imagetools' ]; then
 case "$4" in
  ghcr.io/willitmod/axebc2-app-umbrel-dev:0.1.10-candidate.6e4ef58218e8) printf 'Digest: %s\\n' "$APP_DIGEST" ;;
  ghcr.io/willitmod/bitcoinii-core:31.1.0-rc.cdf44542dde2) printf 'Digest: %s\\n' "$CORE_DIGEST" ;;
  *) exit 2 ;;
 esac
elif [ "$1 $2" = 'manifest inspect' ]; then
 printf '%s\\n' '{"manifests":[{"platform":{"os":"linux","architecture":"amd64"}},{"platform":{"os":"linux","architecture":"arm64"}}]}'
elif [ "$1" = pull ]; then exit 0
else exit 3
fi
""", encoding="utf-8")
        self.fake.chmod(0o755)
        self.curl_log = self.root / "curl.log"
        self.fake_curl = self.root / "curl"
        self.fake_curl.write_text("""#!/bin/sh
set -eu
printf '%s\\n' "$*" >>"$FAKE_CURL_LOG"
for arg in "$@"; do url="$arg"; done
case "$url" in
 *'/token?'*) printf '%s\\n' '{"token":"anonymous-test-token"}' ;;
 *)
  case "${CURL_DIGEST_MODE:-correct}" in
   correct) case "$url" in *axebc2-app-umbrel-dev*) digest="$APP_DIGEST";; *) digest="$CORE_DIGEST";; esac ;;
   wrong) digest="sha256:$(printf '%064d' 0)" ;;
   missing) printf 'HTTP/2 200\\r\\n\\r\\n'; exit 0 ;;
   malformed) digest='sha256:not-a-digest' ;;
  esac
  printf 'HTTP/2 200\\r\\ndocker-content-digest: %s\\r\\n\\r\\n' "$digest"
 ;;
esac
""", encoding="utf-8")
        self.fake_curl.chmod(0o755)

    def tearDown(self): self.temp.cleanup()

    def run_it(self, core_tag=CORE_TAG, curl_mode="correct"):
        env=os.environ.copy(); env.update({"DOCKER_BIN":str(self.fake),"CURL_BIN":str(self.fake_curl),"FAKE_DOCKER_LOG":str(self.log),"FAKE_CURL_LOG":str(self.curl_log),"CURL_DIGEST_MODE":curl_mode,"APP_DIGEST":APP_DIGEST,"CORE_DIGEST":CORE_DIGEST})
        return subprocess.run([str(self.root/"scripts"/SCRIPT.name),APP_DIGEST,core_tag,CORE_DIGEST],env=env,text=True,capture_output=True,check=False)

    def test_anonymous_candidate_checks_finalize_and_emit_evidence(self):
        result=self.run_it(); self.assertEqual(result.returncode,0,result.stderr)
        compose=(self.root/"willitmod-dev-bc2/docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("_DIGEST_REQUIRED",compose)
        core_ref="ghcr.io/willitmod/bitcoinii-core:"+CORE_TAG+"@"+CORE_DIGEST
        self.assertEqual(compose.count(core_ref),2)
        evidence=json.loads((self.root/"willitmod-dev-bc2/DEV-ACCEPTANCE-EVIDENCE.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["source_revision"],"6e4ef58218e8cd5a4d1113196f9872a7f501f52e")
        self.assertEqual(evidence["core_source_revision"],"cdf44542dde255648008249d187fafc15f3a2f09")
        self.assertEqual(evidence["core_candidate_run"],33675068951)
        self.assertEqual(evidence["app_digest"],APP_DIGEST); self.assertEqual(evidence["core_digest"],CORE_DIGEST)
        calls=self.log.read_text(encoding="utf-8")
        self.assertEqual(calls.count("--platform linux/amd64"),2); self.assertEqual(calls.count("--platform linux/arm64"),2)
        self.assertNotIn("buildx", calls)
        self.assertTrue(all("--config" in line for line in calls.splitlines()))

    def test_bad_registry_digest_headers_fail_without_docker_or_mutation(self):
        for mode in ("wrong", "missing", "malformed"):
            if self.log.exists(): self.log.unlink()
            result=self.run_it(curl_mode=mode); self.assertNotEqual(result.returncode,0)
            self.assertFalse(self.log.exists())
            self.assertEqual((self.root/"willitmod-dev-bc2/docker-compose.yml").read_bytes(),self.original)

    def test_wrong_core_revision_tag_fails_before_registry_and_mutation(self):
        result=self.run_it("31.1.0-rc.000000000000"); self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.log.exists())
        self.assertEqual((self.root/"willitmod-dev-bc2/docker-compose.yml").read_bytes(),self.original)

if __name__ == "__main__": unittest.main()
