import re

APP_TAG = "ghcr.io/willitmod/axebc2-app-umbrel-dev:0.1.10-candidate.6e4ef58218e8"
CORE_TAG = "ghcr.io/willitmod/bitcoinii-core:31.1.0-rc.3c2cafcab19e"

def validate(compose, phase):
    if phase not in {"prefinalization", "finalized"}:
        raise ValueError("phase must be prefinalization or finalized")
    app_sentinel = APP_TAG + "@sha256:APP_CANDIDATE_DIGEST_REQUIRED"
    core_sentinel = CORE_TAG + "@sha256:CORE31_CANDIDATE_DIGEST_REQUIRED"
    if phase == "prefinalization":
        if compose.count(app_sentinel) != 1 or compose.count(core_sentinel) != 2:
            raise ValueError("prefinalization requires the exact three digest sentinels")
        if compose.count("_DIGEST_REQUIRED") != 3:
            raise ValueError("unknown or partial digest sentinel state")
        return
    if "_DIGEST_REQUIRED" in compose:
        raise ValueError("finalized release contains a digest sentinel")
    app = re.findall(re.escape(APP_TAG) + r"@(sha256:[0-9a-f]{64})", compose)
    core = re.findall(re.escape(CORE_TAG) + r"@(sha256:[0-9a-f]{64})", compose)
    if len(app) != 1 or len(core) != 2 or len(set(core)) != 1:
        raise ValueError("finalized release requires one app pin and two identical Core pins")
