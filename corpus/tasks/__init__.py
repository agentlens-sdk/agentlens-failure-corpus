def load_family(name):
    if name == "tools": from .family_tools import TASKS
    elif name == "flakiness": from .family_flakiness import TASKS
    elif name == "swebench": from .family_swebench import TASKS
    else: raise ValueError(name)
    return TASKS
