#!/usr/bin/env python3
"""Validate a v1 profile offline. Never execute its commands or approve evidence."""
import argparse
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

SCHEMA = Path(__file__).resolve().parents[1] / "schemas/local-validation-profile.schema.json"
OUTCOMES = ("PASS", "FAIL", "BLOCKED", "TIMEOUT", "ERROR")


class InvalidProfile(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidProfile(message)


def check(value, rule, root, location="$profile"):
    """Interpret only the schema vocabulary used by our bundled v1 contract."""
    if "$ref" in rule:
        target = root
        for part in rule["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return check(value, target, root, location)
    kinds = {"object": lambda v: type(v) is dict, "array": lambda v: type(v) is list,
             "string": lambda v: type(v) is str, "integer": lambda v: type(v) is int,
             "number": lambda v: type(v) in (int, float) and math.isfinite(v)}
    if "type" in rule:
        require(kinds[rule["type"]](value), f"{location}: wrong type")
    if "const" in rule:
        require(type(value) is type(rule["const"]) and value == rule["const"], f"{location}: wrong constant")
    if "enum" in rule:
        require(value in rule["enum"], f"{location}: unknown value")
    if isinstance(value, dict):
        props = rule.get("properties", {})
        require(set(rule.get("required", [])) <= value.keys(), f"{location}: missing fields")
        if rule.get("additionalProperties") is False:
            require(value.keys() <= props.keys(), f"{location}: unknown fields")
        for key, child in value.items():
            if key in props:
                check(child, props[key], root, f"{location}.{key}")
    if isinstance(value, list):
        require(len(value) >= rule.get("minItems", 0), f"{location}: too few items")
        require(len(value) <= rule.get("maxItems", float("inf")), f"{location}: too many items")
        if rule.get("uniqueItems"):
            require(len({json.dumps(v, sort_keys=True) for v in value}) == len(value), f"{location}: duplicates")
        if "items" in rule:
            for child in value:
                check(child, rule["items"], root, location + "[]")
    if isinstance(value, str):
        require(rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", float("inf")), f"{location}: length")
        if "pattern" in rule:
            require(re.search(rule["pattern"], value) is not None, f"{location}: pattern")
    if type(value) in (int, float):
        require(rule.get("minimum", -float("inf")) <= value <= rule.get("maximum", float("inf")), f"{location}: budget/range")


def safe_path(value):
    require("\\" not in value and not any(ord(c) < 32 or ord(c) == 127 for c in value), "unsafe path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts and ":" not in value and "~" not in value, "unsafe path")


def validate(profile):
    schema = json.loads(SCHEMA.read_text())
    check(profile, schema, schema)
    steps = profile["steps"]
    ids = {s["id"] for s in steps}
    require(len(ids) == len(steps), "duplicate step id")
    for step in steps:
        for field in ("cwd", "evidence"):
            safe_path(step[field])
            step[field] = str(PurePosixPath(step[field]))
        require(step["evidence"] != ".", "dot output forbidden")
        for path in step["fixtures"]:
            safe_path(path)
        step["fixtures"] = [str(PurePosixPath(p)) for p in step["fixtures"]]
        require(len(set(step["fixtures"])) == len(step["fixtures"]), "duplicate fixture paths")
    require(len({s["evidence"] for s in steps}) == len(steps), "evidence paths must be distinct")
    kinds = {s["kind"] for s in steps}
    mandatory = {"static", "unit", "integration"}
    mandatory |= {"web": {"ui", "recording"}, "mobile": {"emulator", "recording"}}.get(profile["stack"], set())
    require(mandatory <= kinds, "missing mandatory gates")
    by_id = {s["id"]: s for s in steps}
    seen, visiting = set(), set()

    def visit(step_id):
        require(step_id in ids, "unknown dependency")
        require(step_id not in visiting, "cyclic dependency")
        if step_id in seen:
            return
        visiting.add(step_id)
        for dep in by_id[step_id]["needs"]:
            visit(dep)
        visiting.remove(step_id)
        seen.add(step_id)

    for step in steps:
        visit(step["id"])
        for path in (step["cwd"], step["evidence"], *step["fixtures"]):
            safe_path(path)
        argv = step["argv"]
        # This is a review boundary, not a sandbox: package scripts and executables
        # remain trusted repository code and must be inspected independently.
        require(all(not re.search(r"[;&|`$<>\x00-\x1f\x7f]", arg) for arg in argv), "shell syntax forbidden")
        executable = PurePosixPath(argv[0]).name.lower()
        executable = executable.removesuffix(".exe")
        require(executable not in {"sh", "bash", "rbash", "zsh", "dash", "ash", "ksh", "fish", "csh", "tcsh", "cmd", "command", "busybox", "powershell", "pwsh", "rm", "sudo", "curl", "wget", "eval", "exec", "env"}, "dangerous command")
        require(not any(arg.lower().startswith(("-c", "--eval", "-e", "/c", "-p", "--print")) for arg in argv[1:]), "inline code forbidden")
        safe_path(argv[0])
        require(step["timeout_seconds"] <= profile["budget"]["wall_seconds"], "step exceeds wall budget")
        if step["kind"] in {"unit", "integration", "ui", "emulator"}:
            require(step["min_tests"] >= 1, "zero-test acceptance forbidden")
    for step in steps:
        if step["kind"] == "recording":
            ancestors = set()
            pending = list(step["needs"])
            while pending:
                dep = pending.pop()
                if dep not in ancestors:
                    ancestors.add(dep)
                    pending.extend(by_id[dep]["needs"])
            producers = [by_id[d] for d in ancestors if by_id[d]["kind"] in {"ui", "emulator"}]
            require(producers, "recording requires ancestor UI/emulator")
            require(any(p["evidence"] in step["fixtures"] for p in producers), "recording must consume ancestor evidence")
    return profile


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args(argv)
    try:
        profile = json.loads(args.profile.read_text(), object_pairs_hook=strict_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(InvalidProfile("nonfinite JSON")))
        validate(profile)
    except (OSError, ValueError, RecursionError) as exc:
        print(json.dumps({"result": "INVALID_PROFILE", "detail": str(exc)}))
        return 2
    print(json.dumps({"result": "VALID_PROFILE", "version": 1, "execution": "NOT_RUN"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
