from interpreter import interpreter

class Chat:

    def ask(self, prompt):
        print("""
========== AI ==========
""")
        interpreter.chat(prompt)
        print("""
========================
""")
