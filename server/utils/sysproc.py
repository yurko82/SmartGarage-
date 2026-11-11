"""
server/utils/sysproc.py — Безпечна обгортка над викликами subprocess
Запобігає зависанням процесів (обов'язковий timeout), логує команди та результати,
забороняє використання небезпечного shell=True.
"""
import logging
import subprocess
from typing import Any

logger = logging.getLogger("SysProc")


class SysProcError(Exception):
    """Помилка виконання зовнішньої системної команди."""
    pass


def safe_run(
    cmd: list[str],
    timeout: float = 5.0,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """
    Безпечне виконання команди через subprocess.run.
    Забороняє shell=True для запобігання командним ін'єкціям.
    """
    if kwargs.get("shell", False):
        raise ValueError("Параметр shell=True заборонено правилами безпеки Smart Garage!")

    if not isinstance(cmd, (list, tuple)) or not cmd:
        raise ValueError("Команда має бути непорожнім списком або кортежем рядків.")

    cmd_str = " ".join(str(c) for c in cmd)
    logger.debug(f"Виконання команди [timeout={timeout}s]: {cmd_str}")

    try:
        proc = subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=capture_output,
            text=text,
            check=check,
            **kwargs,
        )
        return proc
    except subprocess.TimeoutExpired as e:
        logger.warning(f"Таймаут виконання ({timeout}s) для команди: {cmd_str}")
        raise SysProcError(f"Таймаут ({timeout}s) для команди {cmd[0]}") from e
    except FileNotFoundError as e:
        logger.error(f"Програму '{cmd[0]}' не знайдено в системі.")
        raise SysProcError(f"Виконуваний файл не знайдено: {cmd[0]}") from e
    except subprocess.CalledProcessError as e:
        logger.error(f"Команда '{cmd[0]}' повернула код помилки {e.returncode}: {e.stderr}")
        raise SysProcError(f"Команда {cmd[0]} завершилась помилкою {e.returncode}") from e
    except Exception as e:
        logger.error(f"Непередбачена помилка виконання {cmd_str}: {e}")
        raise SysProcError(f"Помилка виклику процесу {cmd[0]}: {e}") from e
