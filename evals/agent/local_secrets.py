"""Generate isolated development credentials; never print them or reuse app secrets."""

import secrets
from pathlib import Path


def main():
    path = Path(".scratch/langfuse.env")
    if path.exists():
        raise SystemExit("Local secrets already exist; refusing to overwrite them.")
    path.parent.mkdir(exist_ok=True)
    names = (
        "POSTGRES_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        "REDIS_PASSWORD",
        "MINIO_PASSWORD",
        "SALT",
        "NEXTAUTH_SECRET",
        "USER_PASSWORD",
        "PUBLIC_KEY",
        "SECRET_KEY",
    )
    lines = [f"LF_{name}={secrets.token_hex(24)}" for name in names]
    lines.append("LF_ENCRYPTION_KEY=" + secrets.token_hex(32))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Created .scratch/langfuse.env (ignored by git).")


if __name__ == "__main__":
    main()
