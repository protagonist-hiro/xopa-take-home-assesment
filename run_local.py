import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def load_env_file(env_path: Path) -> dict:
    env = dict(os.environ)
    if not env_path.exists():
        return env

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def port_open(host: str, port: int, timeout: float = 0.75) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def start_process(args: list[str], cwd: Path, env: dict, name: str) -> subprocess.Popen:
    print(f"[start] {name}: {' '.join(args)}")
    return subprocess.Popen(args, cwd=str(cwd), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local dev stack (API + ARQ worker)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default="8090")
    parser.add_argument("--no-worker", action="store_true", help="Start API only")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    env = load_env_file(root / ".env")

    # Local defaults for no-MinIO dev.
    env.setdefault("STORAGE_BACKEND", "local")
    env.setdefault("LOCAL_RECORDINGS_DIR", "./data/recordings")
    env["PUBLIC_BASE_URL"] = f"http://localhost:{args.port}"

    recordings_dir = (root / env["LOCAL_RECORDINGS_DIR"]).resolve()
    recordings_dir.mkdir(parents=True, exist_ok=True)

    print("[info] Local storage backend enabled")
    print(f"[info] Recordings dir: {recordings_dir}")

    if not port_open("127.0.0.1", 5432):
        print("[warn] PostgreSQL not reachable on localhost:5432")
    if not port_open("127.0.0.1", 6379):
        print("[warn] Redis not reachable on localhost:6379")

    processes: list[subprocess.Popen] = []

    api_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--reload",
    ]
    processes.append(start_process(api_cmd, root, env, "api"))

    if not args.no_worker:
        worker_cmd = [sys.executable, "-m", "arq", "app.worker.WorkerSettings"]
        processes.append(start_process(worker_cmd, root, env, "worker"))

    print("[info] API: http://localhost:%s" % args.port)
    print("[info] Docs: http://localhost:%s/docs" % args.port)
    if env.get("DEBUG", "false").lower() == "true":
        print("[info] Debug UI: http://localhost:%s/debug?key=%s" % (args.port, env.get("ADMIN_KEY", "")))

    def shutdown(*_):
        print("\n[stop] Shutting down child processes...")
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        end = time.time() + 5
        for proc in processes:
            while proc.poll() is None and time.time() < end:
                time.sleep(0.1)
            if proc.poll() is None:
                proc.kill()
        print("[stop] Done")
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(0.5)
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    print(f"[exit] A child process exited with code {code}; stopping all.")
                    shutdown()
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
