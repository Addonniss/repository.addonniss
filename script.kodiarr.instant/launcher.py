# -*- coding: utf-8 -*-
import sys

def _has_action():
    argv_text = " ".join([str(x) for x in sys.argv]).lower()
    return "action=" in argv_text

if __name__ == "__main__":
    if _has_action():
        from resources.lib.router import run
        run()
    else:
        from resources.lib.config_flow import show_launcher_menu
        show_launcher_menu()
