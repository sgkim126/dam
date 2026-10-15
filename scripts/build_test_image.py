"""Build a test image from installed dam package resources."""

import argparse

from dam.assets import build_context
from dam.process import run

parser = argparse.ArgumentParser()
parser.add_argument("--tag", required=True)
args = parser.parse_args()
with build_context() as directory:
    run(["docker", "build", "--pull", "--tag", args.tag, str(directory)])
