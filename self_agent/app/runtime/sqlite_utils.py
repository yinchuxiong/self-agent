from pathlib import Path


def sqlite_path_from_url(database_url: str) -> str:
    """Return a sqlite3-compatible path from the app's DATABASE_URL setting."""
    memory_urls = {"sqlite:///:memory:", "sqlite+aiosqlite:///:memory:", ":memory:"}
    if database_url in memory_urls:
        return ":memory:"

    prefixes = ("sqlite+aiosqlite:///", "sqlite:///")
    for prefix in prefixes:
        if database_url.startswith(prefix):
            raw_path = database_url.removeprefix(prefix)
            if not raw_path:
                raise ValueError("SQLite DATABASE_URL is missing a database path")
            path = Path(raw_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            return str(path)

    raise ValueError(f"Unsupported SQLite DATABASE_URL: {database_url}")
