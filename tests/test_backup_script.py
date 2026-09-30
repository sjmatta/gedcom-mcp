"""Exercise snapshot staging/read-back/retention boundaries without live repositories."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "backup-rivendell.sh"


@pytest.mark.parametrize("failure", ["", "nas"])
def test_backup_script_requires_both_readbacks_before_cleanup(tmp_path, failure):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    store = tmp_path / "store"
    replication = store / "replication"
    replication.mkdir(parents=True)
    old = replication / "snapshot-old.sqlite"
    old.write_bytes(b"old")
    trace = tmp_path / "trace.jsonl"
    docker = binaries / "docker"
    docker.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['MOCK_TRACE'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if args[0] == 'inspect':
    print('true')
elif args[:3] == ['exec', 'gedcom-mcp', 'python']:
    destination = Path(os.environ['GEDCOM_HOST_STORE']) / args[-1].removeprefix('/state/')
    destination.write_bytes(b'consistent-snapshot')
    Path(os.environ['MOCK_LATEST']).write_text(str(destination))
elif args[0] == 'exec' and args[2:4] == ['restic','dump']:
    if args[1] == 'restic-' + os.environ.get('MOCK_FAILURE', ''):
        sys.stdout.buffer.write(b'corrupt')
    else:
        sys.stdout.buffer.write(Path(Path(os.environ['MOCK_LATEST']).read_text()).read_bytes())
""")
    docker.chmod(0o755)
    # The actual flock and NFS mount guards are host-specific; emulate their success.
    for name, body in (
        ("flock", "exit 0"),
        ("findmnt", "echo '192.168.5.37:/volume1/DockerBackup'"),
    ):
        path = binaries / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
            "GEDCOM_BACKUP_ROOT": str(tmp_path / "root"),
            "GEDCOM_HOST_STORE": str(store),
            "MOCK_TRACE": str(trace),
            "MOCK_FAILURE": failure,
            "MOCK_LATEST": str(tmp_path / "latest"),
        },
        timeout=10,
    )
    commands = [json.loads(line) for line in trace.read_text().splitlines()]
    backups = [
        args for args in commands if args[:1] == ["exec"] and args[2:4] == ["restic", "backup"]
    ]
    assert len(backups) == 2
    assert all("--tag" in args and "gedcom-mcp" in args for args in backups)
    forgotten = [
        args for args in commands if args[:1] == ["exec"] and args[2:4] == ["restic", "forget"]
    ]
    if failure:
        assert result.returncode != 0
        assert old.exists()
        assert len(forgotten) == 1  # S3 succeeded; NAS failed before its retention.
    else:
        assert result.returncode == 0, result.stderr
        assert not old.exists()
        assert len(forgotten) == 2
        assert all(args[args.index("--group-by") + 1] == "host,tags" for args in forgotten)
        assert len(list(replication.glob("snapshot-*.sqlite"))) == 1
    assert not list(replication.glob(".restore-*"))
