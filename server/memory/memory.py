import json
from pathlib import Path
from server.config import config


class Memory:

    def __init__(self, filename=None):

        if filename is not None:
            self.file = Path(filename)
        else:
            mem_path = config.get("memory", {}).get("path", "./memory")
            path_obj = Path(mem_path)
            if path_obj.is_dir() or not path_obj.suffix:
                self.file = path_obj / "memory.json"
            else:
                self.file = path_obj

        if not self.file.exists():
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text("{}", encoding="utf-8")

    def load(self):

        try:
            if not self.file.exists():
                return {}
            text = self.file.read_text(encoding="utf-8").strip()

            if not text:
                return {}

            return json.loads(text)

        except (json.JSONDecodeError, FileNotFoundError, OSError):
            return {}

    def save(self, data):

        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.file.with_suffix(".tmp")
        tmp_file.write_text(
            json.dumps(data, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
        tmp_file.replace(self.file)

    def get(self, key, default=None):

        data = self.load()
        return data.get(key, default)

    def set(self, key, value):

        data = self.load()
        data[key] = value
        self.save(data)

    def delete(self, key):

        data = self.load()

        if key in data:
            del data[key]
            self.save(data)
            return True
        return False

    def clear(self):

        self.save({})

    def all(self):

        return self.load()

