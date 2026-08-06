from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

print("=" * 40)
print("Smart Garage")
print("=" * 40)
print(f"Project : {config['project']['name']}")
print(f"Version : {config['project']['version']}")
print(f"LLM     : {config['llm']['provider']}")
print(f"Model   : {config['llm']['model']}")
print("=" * 40)
