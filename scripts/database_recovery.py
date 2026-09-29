#!/usr/bin/env python3
"""Back up a container database; rehearse restores without exposing a test server."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def backup(args):
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.stat().st_mode & 0o077:
        raise ValueError("Backup directory must be private (chmod 700).")
    image = docker("inspect", "--format", "{{.Image}}", args.container, capture_output=True, text=True).stdout.strip()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = directory / f"workflow-db-{stamp}-{secrets.token_hex(4)}.dump"
    partial = archive.with_suffix(".partial")
    try:
        with partial.open("xb") as stream:
            docker(
                "exec",
                args.container,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--username",
                args.user,
                "--dbname",
                args.database,
                stdout=stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        with partial.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                raise ValueError("pg_dump did not produce a custom PostgreSQL archive.")
        partial.rename(archive)
        write_json(
            archive.with_suffix(".json"),
            {
                "created_at": datetime.now(UTC).isoformat(),
                "archive": archive.name,
                "sha256": digest(archive),
                "source_image": image,
                "source_container": args.container,
                "source_database": args.database,
            },
        )
    finally:
        partial.unlink(missing_ok=True)
    print(archive)


def rehearse(args):
    if args.evidence.exists():
        raise ValueError("Evidence file already exists; choose a new path.")
    archive = args.archive.resolve()
    manifest = json.loads(archive.with_suffix(".json").read_text())
    if manifest["archive"] != archive.name or manifest["sha256"] != digest(archive):
        raise ValueError("Archive name or SHA256 does not match its manifest.")
    image = manifest["source_image"]
    if not isinstance(image, str) or not image.startswith("sha256:"):
        raise ValueError("Manifest must specify the immutable source image ID.")
    name = f"workflow-restore-rehearsal-{secrets.token_hex(12)}"
    created = False
    start = time.monotonic()
    try:
        # No ports, host mounts or network: ordinary test clients cannot reach this DB.
        docker(
            "create",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/var/lib/postgresql:rw",
            "--tmpfs",
            "/var/lib/postgresql/data:rw",
            "--tmpfs",
            "/tmp:rw",
            "--tmpfs",
            "/var/run/postgresql:rw",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "--env",
            "POSTGRES_DB=rehearsal",
            image,
            "postgres",
            "-c",
            "listen_addresses=",
            "-c",
            "unix_socket_directories=/var/run/postgresql",
            stdout=subprocess.DEVNULL,
        )
        created = True
        docker("start", name, stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + args.startup_timeout
        while True:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "sh",
                    "-c",
                    '[ "$(cat /proc/1/comm)" = postgres ] && pg_isready -h /var/run/postgresql -U postgres',
                ],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Isolated PostgreSQL did not become ready.")
            time.sleep(0.5)
        with archive.open("rb") as stream:
            docker(
                "exec",
                "-i",
                name,
                "pg_restore",
                "-h",
                "/var/run/postgresql",
                "-U",
                "postgres",
                "--dbname",
                "rehearsal",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                stdin=stream,
                stdout=subprocess.DEVNULL,
            )
        # Record structural evidence only, never customer rows.
        sql = """SELECT json_build_object(
            'tables', (SELECT count(*) FROM information_schema.tables
                       WHERE table_schema='public' AND table_type='BASE TABLE'),
            'constraints', (SELECT count(*) FROM information_schema.table_constraints
                            WHERE table_schema='public'),
            'database_bytes', pg_database_size(current_database()));"""
        result = docker(
            "exec",
            name,
            "psql",
            "-h",
            "/var/run/postgresql",
            "-U",
            "postgres",
            "-d",
            "rehearsal",
            "-X",
            "-A",
            "-t",
            "--set",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
            capture_output=True,
            text=True,
        )
        counts = json.loads(result.stdout)
        if counts["tables"] == 0:
            raise ValueError("Restore contains no public tables.")
        evidence = {
            "completed_at": datetime.now(UTC).isoformat(),
            "sha256": manifest["sha256"],
            "image": image,
            "network": "none",
            "published_ports": [],
            "elapsed_seconds": round(time.monotonic() - start, 2),
            **counts,
        }
    finally:
        if created:
            docker("rm", "--force", "--volumes", name, stdout=subprocess.DEVNULL)
    # Only successful restoration AND cleanup can publish successful evidence.
    write_json(args.evidence, evidence)
    print(args.evidence)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dump = commands.add_parser("backup")
    dump.add_argument("--container", required=True)
    dump.add_argument("--database", required=True)
    dump.add_argument("--user", default="workflow_rw")
    dump.add_argument("--directory", type=Path, required=True)
    restore = commands.add_parser("rehearse")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--evidence", type=Path, required=True)
    restore.add_argument("--startup-timeout", type=float, default=60)
    args = parser.parse_args()
    try:
        (backup if args.command == "backup" else rehearse)(args)
    except (OSError, ValueError, KeyError, TimeoutError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Database recovery failed: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
