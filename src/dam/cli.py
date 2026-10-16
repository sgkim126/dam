"""CLI dispatch; only installed command modules are exposed."""

import argparse
import importlib
import importlib.util
import sys

from .errors import DamError

ROOT_COMMANDS = (
    "init",
    "list",
    "shell",
    "build",
    "stop",
    "down",
    "ps",
    "logs",
    "config",
    "sync",
)
GROUP_COMMANDS = {
    "profile": ("create", "list"),
    "mount": ("add", "list", "share", "delete"),
    "user": ("add", "list", "switch", "delete"),
    "session": (
        "create",
        "show",
        "list",
        "add",
        "delete",
        "swap",
        "attach",
        "restart",
        "remove",
    ),
}


def command_module(name):
    full_name = f"dam.commands.{name}"
    if importlib.util.find_spec(full_name) is None:
        return None
    return importlib.import_module(full_name)


def parser():
    result = argparse.ArgumentParser(
        prog="dam", description="Manage persistent Docker workspaces."
    )
    result.add_argument("-w", "--workspace", help="workspace name (before the command)")
    result.set_defaults(handler=None, help_parser=result)
    commands = result.add_subparsers(dest="command")
    for name in ROOT_COMMANDS:
        module = command_module("sync" if name == "sync" else f"workspace_{name}")
        if module is None:
            continue
        command = commands.add_parser(
            name, description=module.__doc__, help=module.__doc__
        )
        module.configure(command)
        command.set_defaults(handler=module.run, workspace_required=name != "list")
    for group, names in GROUP_COMMANDS.items():
        modules = [(name, command_module(f"{group}_{name}")) for name in names]
        modules = [(name, module) for name, module in modules if module is not None]
        if not modules:
            continue
        parent = commands.add_parser(group)
        parent.set_defaults(help_parser=parent)
        children = parent.add_subparsers(dest="action")
        for name, module in modules:
            command = children.add_parser(
                name, description=module.__doc__, help=module.__doc__
            )
            module.configure(command)
            command.set_defaults(
                handler=module.run, workspace_required=group != "profile"
            )
    return result


def main(argv=None):
    command_parser = parser()
    args = command_parser.parse_args(argv)
    if args.handler is None:
        args.help_parser.print_help()
        return 0
    if args.workspace_required and not args.workspace:
        command_parser.error("this command requires --workspace/-w before the command")
    if not args.workspace_required and args.workspace is not None:
        command_parser.error("this command does not accept --workspace/-w")
    try:
        from .model import validate_workspace_name
        from .store import Store

        if args.workspace is not None:
            validate_workspace_name(args.workspace)
        return args.handler(args, Store()) or 0
    except DamError as error:
        print(f"dam: {error}", file=sys.stderr)
        return error.exit_code
    except (OSError, ValueError) as error:
        print(f"dam: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
