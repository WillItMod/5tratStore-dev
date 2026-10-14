"""Actual pool PID1 shutdown; optional real offline Core, never fake RPC/mining."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid

from test_pool_supervisor_delivery import APPS, ROOT, source

POOL = 'ghcr.io/willitmod/docker-ckpool-solo@sha256:8a9a7f10c8138d0f55533132ee7710a06715a42a49f75efb39be3350ada4fa6e'
NODE = 'ghcr.io/willitmod/axebtc-bitcoind-switch@sha256:a9276924c0fce0d4664ab1515a949d96bead0c43c053319cb4876779928bc2af'
OWNER = 'codex-pool-supervisor-real-runtime-20261014'
RECEIPTS = []


def run(argv, timeout=60):
    return subprocess.check_output(argv, text=True, stderr=subprocess.PIPE, timeout=timeout).strip()


def inspect(reference):
    return json.loads(run(['docker', 'inspect', reference]))[0]


def volume(name):
    name = OWNER + '-' + name + '-' + uuid.uuid4().hex[:10]
    assert subprocess.run(['docker', 'volume', 'inspect', name], capture_output=True).returncode != 0
    assert run(['docker', 'volume', 'create', '--label', 'dev.compat.owner=' + OWNER, name]) == name
    return name


def remove_volume(name):
    record = json.loads(run(['docker', 'volume', 'inspect', name]))[0]
    assert record['Labels']['dev.compat.owner'] == OWNER
    run(['docker', 'volume', 'rm', name])


def remove_stopped(cid):
    record = inspect(cid)
    assert record['Config']['Labels']['dev.compat.owner'] == OWNER
    assert not record['State']['Running'] and record['State']['Pid'] == 0
    run(['docker', 'rm', '-v', cid])


def pool_file_metadata(config_volume):
    return run(['docker', 'run', '--rm', '--label', 'dev.compat.owner=' + OWNER,
        '--network', 'none', '--read-only', '--mount', 'type=volume,src=' + config_volume + ',dst=/config,readonly',
        '--entrypoint', '/bin/sh', POOL, '-ec',
        'find /config -type f -exec stat -c "%n|%a|%u|%g|%h|%s" {} +; find /config -type f -exec sha256sum {} +'])


def pool_case(app, signal, config_volume, node=None, baseline=False):
    cid = None
    name = OWNER + '-' + app + '-' + uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix=OWNER + '-', dir=os.environ.get('TMPDIR')) as directory:
        wrapper = Path(directory) / 'entrypoint.sh'
        body = source(app, 'data/templates/ckpool-entrypoint.sh', baseline)
        wrapper.write_bytes(body); wrapper.chmod(0o644)
        before = pool_file_metadata(config_volume)
        try:
            cid = run(['docker', 'run', '-d', '--name', name, '--label', 'dev.compat.owner=' + OWNER,
                '--network', 'container:' + node if node else 'none', '--read-only', '--user', '1000:1000',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--memory', '192m', '--cpus', '1', '--pids-limit', '64',
                '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=16m', '--tmpfs', '/www:rw,nosuid,nodev,size=16m,uid=1000,gid=1000',
                '--mount', 'type=bind,src=' + str(wrapper) + ',dst=/ckpool-entrypoint.sh,readonly',
                '--mount', 'type=volume,src=' + config_volume + ',dst=/config,readonly',
                '--entrypoint', '/bin/sh', POOL, '/ckpool-entrypoint.sh'])
            deadline = time.monotonic() + 20
            while True:
                state = inspect(cid)
                assert state['State']['Running'], 'Owned pool wrapper exited before supervision proof'
                names = run(['docker', 'top', cid, '-eo', 'pid,ppid,comm']).splitlines()
                expected = 'ckpool' if node else 'sleep'
                if any(line.split()[-1] == expected for line in names[1:]): break
                assert time.monotonic() < deadline, 'Expected real child was not observed'
                time.sleep(.1)
            started = time.monotonic()
            if signal == 'TERM':
                run(['docker', 'stop', '--timeout', '5', cid], timeout=15)
            else:
                assert signal == 'INT'
                run(['docker', 'kill', '--signal', 'INT', cid]); run(['docker', 'wait', cid], timeout=10)
            elapsed = time.monotonic() - started
            after = inspect(cid)
            assert not after['State']['Running'] and after['State']['Pid'] == 0 and not after['State']['OOMKilled']
            assert after['State']['ExitCode'] == (137 if baseline else 0)
            assert baseline or elapsed < 4
            assert pool_file_metadata(config_volume) == before
            record = {'app': app, 'signal': signal, 'baseline': baseline,
                'image': POOL, 'wrapper_sha256': hashlib.sha256(body).hexdigest(),
                'exit_code': after['State']['ExitCode'], 'elapsed_s': round(elapsed, 3),
                'normal_docker_stop_used': signal == 'TERM', 'oom_killed': False,
                'container_pid_after': 0, 'processes_before_pid_ppid_names_only': names,
                'actual_pool_child_observed': node is not None, 'config_bytes_modes_owner_unchanged': True,
                'isolated_network': 'shared loopback of network-none real Core' if node else 'none',
                'host_ports_or_original_app_data': False, 'synthetic_rpc_or_mining_protocol_fixture': False}
            RECEIPTS.append(record)
        finally:
            if cid:
                if inspect(cid)['State']['Running']:
                    # Normal stop of only this owned fixture; never force rm/kill.
                    run(['docker', 'stop', '--timeout', '5', cid], timeout=15)
                remove_stopped(cid)


@unittest.skipUnless(os.environ.get('POOL_SUPERVISOR_DOCKER') == '1', 'opt-in actual network-none PID1 fixtures')
class ActualPoolSupervisor(unittest.TestCase):
    def test_missing_config_baseline_failure_and_both_candidate_signals(self):
        config = volume('empty-config')
        try:
            pool_case('btc', 'TERM', config, baseline=True)
            for app in APPS:
                for signal in ('TERM', 'INT'):
                    with self.subTest(app=app, signal=signal):
                        pool_case(app, signal, config)
        finally:
            remove_volume(config)

    @unittest.skipUnless(os.environ.get('POOL_SUPERVISOR_REAL_NODE') == '1', 'opt-in actual offline Core and pool child')
    def test_started_real_pool_child_is_signalled_and_reaped_against_offline_core(self):
        node = None; data = volume('offline-node'); config = volume('real-pool-config')
        try:
            run(['docker', 'run', '--rm', '--label', 'dev.compat.owner=' + OWNER, '--network', 'none',
                '--mount', 'type=volume,src=' + data + ',dst=/qa', '--entrypoint', '/bin/sh', NODE, '-ec',
                'umask 077; printf "server=1\nrpcport=18443\nrpcbind=127.0.0.1\nrpcallowip=127.0.0.1\nlisten=0\ndnsseed=0\ndiscover=0\nnetworkactive=0\nconnect=0\nwalletbroadcast=0\n" >/qa/bitcoin.conf; chown -R 1000:1000 /qa'])
            node = run(['docker', 'run', '-d', '--name', OWNER + '-node-' + uuid.uuid4().hex[:10],
                '--label', 'dev.compat.owner=' + OWNER, '--network', 'none', '--read-only', '--user', '1000:1000',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--memory', '512m', '--cpus', '1',
                '--pids-limit', '64', '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m',
                '--mount', 'type=volume,src=' + data + ',dst=/qa',
                '--entrypoint', '/opt/bitcoind/current/bitcoind', NODE, '-datadir=/qa', '-printtoconsole=0'])
            cli = ['docker', 'exec', node, '/opt/bitcoind/current/bitcoin-cli', '-datadir=/qa']
            deadline = time.monotonic() + 45
            while True:
                response = subprocess.run(cli + ['getblockchaininfo'], capture_output=True, text=True, timeout=10)
                if response.returncode == 0: break
                assert inspect(node)['State']['Running'] and time.monotonic() < deadline
                time.sleep(.2)
            chain = json.loads(response.stdout)
            assert chain['blocks'] == 0 and json.loads(run(cli + ['getnetworkinfo']))['networkactive'] is False
            assert inspect(node)['HostConfig']['NetworkMode'] == 'none'
            run(cli + ['createwallet', 'owned-offline-supervisor'])
            # Only a new public receiving address is returned; wallet keys stay in
            # this private fixture volume and no transactions/miners are used.
            address = run(cli + ['-rpcwallet=owned-offline-supervisor', 'getnewaddress', 'owned-offline-supervisor', 'legacy'])
            assert address.startswith('1')
            wallet = json.loads(run(cli + ['-rpcwallet=owned-offline-supervisor', 'getwalletinfo']))
            assert wallet['txcount'] == 0
            assert json.loads(run(cli + ['-rpcwallet=owned-offline-supervisor', 'getbalances']))['mine']['trusted'] == 0
            run(['docker', 'run', '--rm', '--label', 'dev.compat.owner=' + OWNER, '--network', 'none',
                '--mount', 'type=volume,src=' + data + ',dst=/qa,readonly',
                '--mount', 'type=volume,src=' + config + ',dst=/config', '--entrypoint', '/bin/sh', NODE, '-ec',
                'umask 027; cookie=$(cat /qa/.cookie); auth=${cookie%%:*}; password=${cookie#*:}; '
                'printf \'{"btcd":[{"url":"127.0.0.1:18443","auth":"%s","pass":"%s","notify":false}],"btcaddress":"%s","btcsig":"/OwnedOfflineSupervisor/","mindiff":1,"startdiff":1,"maxdiff":1,"logdir":"/www","webdir":"/www/pool","userdir":"/www/users"}\\n\' "$auth" "$password" "$1" >/config/ckpool.conf; '
                'printf "%s\\n" "-B" >/config/ckpool.args; chown 1000:1000 /config/ckpool.conf /config/ckpool.args', 'fixture', address])
            for app in APPS:
                for signal in ('TERM', 'INT'):
                    with self.subTest(app=app, signal=signal):
                        pool_case(app, signal, config, node=node)
            RECEIPTS.append({'real_offline_core': NODE, 'height': chain['blocks'], 'network_active': False,
                'public_wallet_address': address, 'private_keys_exported': False, 'transactions_or_miners': False,
                'wallet_txcount_verified': wallet['txcount'], 'wallet_trusted_balance_verified': 0,
                'scope': 'Supervisor only; no Bitcoin or Fractal chain/mining qualification'})
        finally:
            if node:
                if inspect(node)['State']['Running']:
                    run(['docker', 'exec', node, '/opt/bitcoind/current/bitcoin-cli', '-datadir=/qa', 'stop'])
                    assert run(['docker', 'wait', node], timeout=30) == '0'
                remove_stopped(node)
            remove_volume(config); remove_volume(data)

    @classmethod
    def tearDownClass(cls):
        if os.environ.get('POOL_SUPERVISOR_RECEIPT'):
            Path(os.environ['POOL_SUPERVISOR_RECEIPT']).write_text(json.dumps(RECEIPTS, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
