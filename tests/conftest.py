import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeStore:
    """An object store in a dict, so the read-through path is testable without a bucket.

    It counts calls: "the plane was fetched once" is a claim worth asserting, because fetching a
    cube's 103 files to answer one of them would be the bug this design exists to avoid.
    """

    enabled = True

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.gets: list[str] = []
        self.puts: list[str] = []

    def get_bytes(self, name: str) -> bytes | None:
        self.gets.append(name)
        return self.objects.get(name)

    def put_bytes(self, name: str, data: bytes) -> None:
        self.puts.append(name)
        self.objects[name] = data

    def put_many(self, items: list[tuple[str, bytes]]) -> int:
        for name, data in items:
            self.puts.append(name)
            self.objects[name] = data
        return len(items)

    def list_prefix(self, prefix: str) -> list[str]:
        return sorted(name for name in self.objects if name.startswith(prefix))

    def ping(self) -> bool:
        return True
