"""Command line interface for blueprints, yards, and maps."""

import argparse
import importlib
import importlib.util
import sys

from .errors import DamError

COMMANDS = {
    "blueprint": ("create", "list", "delete"),
    "yard": ("create", "list", "ps", "shell", "stop", "logs", "delete"),
    "yard.mount": ("create", "list", "delete"),
    "map": ("create", "list", "show", "open", "delete"),
    "map.pin": ("create", "delete", "move"),
}


def command_module(name):
    full_name = f"dam.commands.{name}"
    if importlib.util.find_spec(full_name) is None:
        return None
    return importlib.import_module(full_name)


def parser():
    root = argparse.ArgumentParser(prog="dam", description="Manage Docker yards.")
    root.set_defaults(handler=None, help_parser=root)
    roots = root.add_subparsers(dest="group")
    for group in ("blueprint", "yard", "map"):
        child_modules = {
            action: command_module(f"{group}_{action}") for action in COMMANDS[group]
        }
        nested = {
            subgroup: {
                action: command_module(f"{group}_{subgroup}_{action}")
                for action in COMMANDS[f"{group}.{subgroup}"]
            }
            for subgroup in ("mount", "pin")
            if f"{group}.{subgroup}" in COMMANDS
        }
        if not any(child_modules.values()) and not any(
            any(modules.values()) for modules in nested.values()
        ):
            continue
        group_parser = roots.add_parser(group)
        group_parser.set_defaults(help_parser=group_parser)
        actions = group_parser.add_subparsers(dest="action")
        for action, module in child_modules.items():
            if module is None:
                continue
            command = actions.add_parser(
                action, description=module.__doc__, help=module.__doc__
            )
            module.configure(command)
            command.set_defaults(handler=module.run)
        for subgroup, modules in nested.items():
            if not any(modules.values()):
                continue
            subgroup_parser = actions.add_parser(subgroup)
            subgroup_parser.set_defaults(help_parser=subgroup_parser)
            subactions = subgroup_parser.add_subparsers(dest="subaction")
            for action, module in modules.items():
                if module is None:
                    continue
                command = subactions.add_parser(
                    action, description=module.__doc__, help=module.__doc__
                )
                module.configure(command)
                command.set_defaults(handler=module.run)
    return root


def main(argv=None):
    command_parser = parser()
    args = command_parser.parse_args(argv)
    if args.handler is None:
        args.help_parser.print_help()
        return 0
    try:
        from .store import Store

        return args.handler(args, Store()) or 0
    except DamError as error:
        print(f"dam: {error}", file=sys.stderr)
        return error.exit_code
    except (OSError, ValueError) as error:
        print(f"dam: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
