#!/usr/bin/env python3
"""
Smart Garage - Open Interpreter Prompt & Tools Loader
Loads `prompts/system_prompt.txt` and `prompts/tool_definitions.json` into Open Interpreter.
"""
import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("PromptLoader")

# Determine project paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "system_prompt.txt"
TOOL_DEFS_PATH = PROJECT_ROOT / "prompts" / "tool_definitions.json"
CONFIG_YAML_PATH = PROJECT_ROOT / "config" / "interpreter_config.yaml"


def load_system_prompt() -> str:
    """Read system_prompt.txt."""
    if not SYSTEM_PROMPT_PATH.is_file():
        raise FileNotFoundError(f"System prompt file not found: {SYSTEM_PROMPT_PATH}")
    with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_tool_definitions() -> Dict[str, Any]:
    """Read and validate tool_definitions.json."""
    if not TOOL_DEFS_PATH.is_file():
        raise FileNotFoundError(f"Tool definitions file not found: {TOOL_DEFS_PATH}")
    with open(TOOL_DEFS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "tools" not in data or not isinstance(data["tools"], list):
        raise ValueError("Invalid tool definitions format: 'tools' array is required")
    return data


def generate_composite_instructions() -> str:
    """
    Combines system_prompt.txt and tool_definitions.json into a consolidated
    instruction set formatted for Open Interpreter.
    """
    system_prompt = load_system_prompt()
    tool_defs = load_tool_definitions()

    tools_summary = []
    for tool in tool_defs.get("tools", []):
        name = tool.get("name")
        desc = tool.get("description", "")
        params = tool.get("parameters", {}).get("properties", {})
        param_list = ", ".join(f"{k} ({v.get('type', 'any')})" for k, v in params.items())
        tools_summary.append(f"- `{name}`: {desc}\n  Parameters: {param_list}")

    tools_block = "\n".join(tools_summary)

    composite = f"""{system_prompt}

### 7. DETAILED TOOL SCHEMAS:
The following tools are strictly available for invocation. When an action is needed, output:
{{"action": "tool_name", "parameters": {{...}}}}

Available Tools:
{tools_block}

Full JSON Schemas are stored in: {TOOL_DEFS_PATH}
"""
    return composite.strip()


def configure_interpreter(custom_model: Optional[str] = None):
    """
    Configures and returns the Open Interpreter instance with Antigravity Core prompts.
    """
    try:
        from interpreter import interpreter
    except ImportError:
        logger.error("Open Interpreter package not found in current Python path.")
        logger.info("Activate venv: source ~/AI/OpenInterpreter/venv/bin/activate")
        sys.exit(1)

    composite_instructions = generate_composite_instructions()

    # Apply configuration
    interpreter.custom_instructions = composite_instructions
    interpreter.llm.model = custom_model or "ollama/qwen2.5-coder:7b"
    interpreter.llm.context_window = 8192
    interpreter.llm.temperature = 0.1
    interpreter.llm.max_tokens = 4096
    interpreter.auto_run = False
    interpreter.safe_mode = True
    interpreter.offline = False

    logger.info("Open Interpreter successfully configured with Antigravity Core prompts:")
    logger.info(" - Model: %s", interpreter.llm.model)
    logger.info(" - Context Window: %d", interpreter.llm.context_window)
    logger.info(" - Safe Mode: %s | Auto Run: %s", interpreter.safe_mode, interpreter.auto_run)
    logger.info(" - Loaded Tools: %d definitions", len(load_tool_definitions()["tools"]))

    return interpreter


def sync_to_yaml_config():
    """Sync composite prompt to config/interpreter_config.yaml."""
    composite_instructions = generate_composite_instructions()
    import yaml

    if CONFIG_YAML_PATH.is_file():
        with open(CONFIG_YAML_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    cfg["custom_instructions"] = composite_instructions
    cfg["system_prompt"] = composite_instructions
    cfg["version"] = "0.2.5"

    with open(CONFIG_YAML_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info("Synchronized composite prompt into: %s", CONFIG_YAML_PATH)


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--print" in args:
        print(generate_composite_instructions())
        sys.exit(0)

    if "--sync-yaml" in args:
        sync_to_yaml_config()
        sys.exit(0)

    # Validate prompts
    try:
        sp = load_system_prompt()
        td = load_tool_definitions()
        print(f"[✓] System prompt validated successfully ({len(sp.splitlines())} lines).")
        print(f"[✓] Tool definitions validated successfully ({len(td['tools'])} tools loaded).")
        for tool in td["tools"]:
            print(f"    • {tool['name']}: {tool['description'][:60]}...")
    except Exception as e:
        print(f"[✗] Validation error: {e}")
        sys.exit(1)

    if "--test" in args or len(args) == 0:
        oi = configure_interpreter()
        print("\n[✓] Interpreter is ready for interactive session.")
