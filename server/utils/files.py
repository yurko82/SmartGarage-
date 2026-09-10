from pathlib import Path


class FileManager:

    @staticmethod
    def read(path):

        path = Path(path)

        if not path.exists():
            return None

        return path.read_text(encoding="utf-8")

    @staticmethod
    def write(path, text):

        path = Path(path)

        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(text, encoding="utf-8")

    @staticmethod
    def exists(path):

        return Path(path).exists()

    @staticmethod
    def list(path):

        return sorted(Path(path).iterdir())
