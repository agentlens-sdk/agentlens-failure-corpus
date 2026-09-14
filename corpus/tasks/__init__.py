def load_family(name):
    """Every task in a family: original, hard, then stacked tier. Which ones run nightly is config's call."""
    if name == "tools":
        from .family_tools import TASKS; from .family_tools_hard import TASKS as HARD; from .family_tools_stack import TASKS as STACK
    elif name == "flakiness":
        from .family_flakiness import TASKS; from .family_flakiness_hard import TASKS as HARD; from .family_flakiness_stack import TASKS as STACK
    elif name == "swebench": from .family_swebench import TASKS; HARD = STACK = []
    else: raise ValueError(name)
    return TASKS + HARD + STACK
