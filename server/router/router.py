class CommandRouter:

    def __init__(self, commands, ai, context_provider=None):
        self.commands = commands
        self.ai = ai
        self.context_provider = context_provider

    def execute(self, prompt, session_id: str = "default"):
        if prompt is None:
            return ""

        if not isinstance(prompt, str):
            prompt = str(prompt)

        prompt = prompt.strip()
        if not prompt:
            return ""

        handled, response = self.commands.execute(prompt)

        if handled:
            return response

        context_info = ""
        if callable(self.context_provider):
            try:
                context_info = self.context_provider()
            except Exception:
                context_info = ""

        try:
            return self.ai.chat(prompt, context_info=context_info, session_id=session_id)
        except TypeError:
            try:
                return self.ai.chat(prompt, context_info=context_info)
            except TypeError:
                return self.ai.chat(prompt)

