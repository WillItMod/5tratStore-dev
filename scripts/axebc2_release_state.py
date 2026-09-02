import re
from pathlib import Path

APP_TAG = "ghcr.io/willitmod/axebc2-app-umbrel-dev:0.1.10-candidate.6e4ef58218e8"
CORE_TAG = "ghcr.io/willitmod/bitcoinii-core:31.1.0-rc.cdf44542dde2"

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

def validate_rendered_binds(contract, rendered, environment=None):
    environment = environment or {}
    def expand(value):
        if not isinstance(value, str): return value
        for name, replacement in environment.items():
            value = value.replace("${" + name + "}", replacement)
        return value
    def binds(document):
        for service, config in document.get("services", {}).items():
            for volume in config.get("volumes", []):
                if volume.get("type") == "bind":
                    yield service, volume
    expected = {}
    for service, volume in binds(contract):
        key = (service, expand(volume.get("source")), volume.get("target"))
        if volume.get("bind", {}).get("create_host_path") is not False:
            raise ValueError(f"contract bind is not fail-closed: service={service} source={key[1]} target={key[2]}")
        expected[key] = volume
    actual = {}
    for service, volume in binds(rendered):
        key = (service, volume.get("source"), volume.get("target"))
        if key not in expected:
            raise ValueError(f"unexpected rendered bind: service={service} source={key[1]} target={key[2]}")
        if volume.get("bind", {}).get("create_host_path") is True:
            raise ValueError(f"rendered bind enables host-path creation: service={service} source={key[1]} target={key[2]}")
        if not isinstance(key[1], str) or not Path(key[1]).exists():
            raise ValueError(f"rendered bind source was not pre-staged: service={service} source={key[1]} target={key[2]}")
        actual[key] = volume
    missing = set(expected) - set(actual)
    if missing:
        service, source, target = sorted(missing)[0]
        raise ValueError(f"rendered bind disappeared: service={service} source={source} target={target}")
