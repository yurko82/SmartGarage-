import logging

logger = logging.getLogger(__name__)

try:
    from interpreter import interpreter
except ImportError:
    interpreter = None


class Chat:

    def ask(self, prompt: str) -> None:
        if interpreter is None:
            logger.warning("OpenInterpreter не встановлено або видалено з оточення.")
            print("\n[Увага] Модуль OpenInterpreter не встановлено в системі.\n")
            return

        print("""
========== AI ==========
""")
        interpreter.chat(prompt)
        print("""
========================
""")

