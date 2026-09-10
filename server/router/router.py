class CommandRouter:

    def __init__(self, commands, ai):
        self.commands = commands
        self.ai = ai

    def execute(self, prompt):
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

        return self.ai.chat(prompt)

