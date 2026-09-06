"""A task = fixed prompt + tools + deterministic checker. No LLM judges anywhere in a checker."""
class Task:
    family = "base"; task_id = "none"; system = "You are a careful software agent."; prompt = ""; tools = []
    def fresh(self): return self.__class__()          # each episode gets a clean instance
    def execute(self, name, inp): raise NotImplementedError
    def check(self): raise NotImplementedError
