#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import argparse
from axebc2_release_state import validate as validate_release_state, validate_rendered_binds


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "willitmod-dev-bc2"


def require(condition, message):
    if not condition:
        raise SystemExit(message)


compose = (APP / "docker-compose.yml").read_text(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--phase", required=True, choices=("prefinalization", "finalized"))
phase = parser.parse_args().phase
try:
    validate_release_state(compose, phase)
except ValueError as exc:
    raise SystemExit(str(exc))
manifest = (APP / "umbrel-app.yml").read_text(encoding="utf-8")
node_config = (APP / "data/templates/bitcoinII.conf.template").read_text(encoding="utf-8")
evidence = json.loads((APP / "DEV-ACCEPTANCE-EVIDENCE.json").read_text(encoding="utf-8"))

require('version: "0.1.11-dev"' in manifest, "manifest must be 0.1.11-dev")
require(evidence.get("app_version") == "0.1.11-dev", "evidence must name the 0.1.11 DEV app version")
require(
    evidence.get("app_image")
    == "ghcr.io/willitmod/axebc2-app-umbrel-dev:0.1.11-candidate.ecf6e2c8cfd0",
    "evidence must name the exact application candidate tag",
)
require(
    evidence.get("source_revision") == "ecf6e2c8cfd0e42ea53d3cc146b18cd6d4c4b563",
    "evidence must name the exact application source revision",
)
require(
    evidence.get("app_digest")
    == "sha256:23a7962e223da5549eba52697c6f4cfa16ab74cba935c68c48148a4c515302b4",
    "evidence must name the exact application index digest",
)
require(evidence.get("app_candidate_run") == 33895447789, "evidence must name the application candidate workflow run")
require(
    evidence.get("core_image") == "ghcr.io/willitmod/bitcoinii-core:31.1.0-rc.cdf44542dde2"
    and evidence.get("core_digest")
    == "sha256:8875917ece57668fe9925d40a256ce8d429a3071511bb555d4ace1fa4370afc6"
    and evidence.get("core_source_revision") == "cdf44542dde255648008249d187fafc15f3a2f09",
    "evidence must retain the accepted Core 31 tag, digest, and source revision",
)
require("Requires 5tratumOS 0.7.12" in manifest, "OS prerequisite must be disclosed")
require(evidence.get("tested_os_version") == "v0.7.12-dev", "evidence must name the tested DEV OS release")
require(
    evidence.get("tested_os_bundle_sha256")
    == "11a35e68ab169eb0446485992a57b33fae018a92020b7d86bbf9a005571377af",
    "evidence must be bound to the exact verified v0.7.12-dev bundle",
)
require('"2345:3333/tcp"' in compose, "Stratum host port 2345 must be retained")
require("SUPPORT_CHECKIN_ENABLED: \"false\"" in compose, "telemetry must default off")
require("create_host_path: false" in compose, "build metadata bind must fail closed")
require("/etc/5tratumos/build.json" in compose, "build metadata must be mounted")
require('JWT_SECRET: "${JWT_SECRET}"' in compose, "init must receive the platform JWT secret")
require(
    ".5tratumos-rollback-policy.json" in (APP / "data/init/init.sh").read_text(encoding="utf-8"),
    "init must use the policy filename consumed by AxeBC2 and 5tratumOS",
)
require(
    "alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1"
    in compose,
    "init image must be pinned",
)
require(
    "ghcr.io/willitmod/docker-ckpool-solo:590fb2a@sha256:8a9a7f10c8138d0f55533132ee7710a06715a42a49f75efb39be3350ada4fa6e"
    in compose,
    "CKPool image must retain its exact pin",
)
require("natpmp=0" in node_config and "upnp=1" not in node_config, "NAT-PMP must be off")
require(not re.search(r'^\s+-\s+"?8338:', compose, re.MULTILINE), "P2P must not be published")

require(
    compose.count("create_host_path: false") == 9,
    "every AxeBC2 host bind must disable implicit source-path creation",
)


def yaml_python():
    candidates = [os.environ.get("YAML_PYTHON"), "/usr/bin/python3", sys.executable]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            check = subprocess.run(
                [candidate, "-c", "import yaml"], capture_output=True, check=False
            )
            if check.returncode == 0:
                return candidate
    raise SystemExit("PyYAML-capable Python is required for merged Compose validation")


def validate_platform_merged_compose():
    docker = shutil.which("docker")
    require(docker is not None, "Docker Compose is required for merged Compose validation")
    with tempfile.TemporaryDirectory(prefix="axebc2-compose-") as raw_temp:
        temp = Path(raw_temp)
        app_data = temp / "state/apps/axebc2"
        for relative in (
            "data/templates",
            "data/init",
            "data/node",
            "data/pool/config",
            "data/pool/www",
        ):
            (app_data / relative).mkdir(parents=True, exist_ok=True)
        (app_data / "data/init/init.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        source = temp / "docker-compose.yml"
        build_metadata = temp / "build.json"
        build_metadata.write_text('{"tag":"v0.7.12-dev"}\n', encoding="utf-8")
        source.write_text(
            compose.replace("APP_CANDIDATE_DIGEST_REQUIRED", "b" * 64)
            .replace("/etc/5tratumos/build.json", str(build_metadata)),
            encoding="utf-8",
        )
        parsed = temp / "parsed-compose.json"
        merged = temp / "platform-merged-compose.json"
        transform = """
import json, sys, yaml
with open(sys.argv[1], encoding='utf-8') as handle:
    config = yaml.safe_load(handle)
with open(sys.argv[2], 'w', encoding='utf-8') as handle:
    json.dump(config, handle)
"""
        subprocess.run([yaml_python(), "-c", transform, source, parsed], check=True)
        contract_path = ROOT / "tests/fixtures/5tratumos_contract_4f979cb.py"
        spec = importlib.util.spec_from_file_location("pinned_5tratumos_contract", contract_path)
        contract = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(contract)
        rendered_contract = contract.materialize_compose(
            json.loads(parsed.read_text(encoding="utf-8")), 21219
        )
        merged.write_text(json.dumps(rendered_contract), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "APP_DATA_DIR": str(app_data),
                "APP_PASSWORD": "validation-only",
                "JWT_SECRET": "validation-only",
                "NETWORK_IP": "10.21.0.0",
            }
        )
        result = subprocess.run(
            [docker, "compose", "-f", str(merged), "config", "--format", "json"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        require(result.returncode == 0, f"merged Compose is invalid: {result.stderr}")
        rendered = json.loads(result.stdout)
        services = rendered["services"]
        require("app_proxy" not in services, "platform merge must remove legacy app_proxy")
        require(
            services["init"]["environment"]["JWT_SECRET"] == "validation-only",
            "platform-merged init service must receive JWT_SECRET",
        )
        require(
            services["app"]["ports"] == [{"mode": "ingress", "target": 3000, "published": "21219", "protocol": "tcp"}],
            "platform merge must materialize the app-proxy host port on the app service",
        )
        require(
            "umbrel_main_network" not in rendered.get("networks", {}),
            "platform merge must remove the legacy shared network",
        )
        require(
            services["app"]["restart"] == "unless-stopped"
            and services["ckpool"]["restart"] == "unless-stopped",
            "platform merge must normalize service restart policies",
        )
        require(
            services["btc2d"]["depends_on"]["init"]["condition"]
            == "service_completed_successfully",
            "Core must wait for successful init completion",
        )
        try:
            validate_rendered_binds(rendered_contract, rendered, {"APP_DATA_DIR": str(app_data)})
        except ValueError as exc:
            raise SystemExit(str(exc))


validate_platform_merged_compose()

subprocess.run(["sh", "-n", str(APP / "data/init/init.sh")], check=True)
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_axebc2_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
