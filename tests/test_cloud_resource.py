#!/usr/bin/env python3
"""The cloud-resource skill's templates meet the invariants the skill demands.

Static: remote backend, no literal account id, every example resource
encrypted with the named key, durable data protected, no workspace and no
remote_state; the skill ships an empty project map and no private paths. With
terraform and network: fmt -check, init -backend=false, validate and test on
the stack with the resource examples inside it, in a temporary directory.
The default run is offline: fmt -check runs when terraform meets
required_version; init/validate/test need SQUAD_TF_ONLINE=1 (local only, not
CI). Whatever does not run prints NOTICE and SKIP, never ok; the static part
always runs.

Self-checking: the exit code is the verdict.

    python3 tests/test_cloud_resource.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "cloud-resource")
STACK = os.path.join(SKILL, "templates", "stack")
RESOURCE = os.path.join(SKILL, "templates", "resource")

# Each example gets its own name when it becomes a .tf, so all three fit in one stack.
EXAMPLES = {
    "resource.tf.example": "queue",
    "durable-data.tf.example": "uploads",
    "durable-input.tf.example": "intake",
}

# Types that hold no data: they configure the bucket next to them.
AUXILIARY = {
    "aws_s3_bucket_versioning",
    "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_server_side_encryption_configuration",
}


# --- HCL reading, the minimum to find blocks and attributes outside comments ---

def strip_comments(src):
    """Blank out comments (#, //, /* */) and return (code, string mask).

    Strings stay intact, including "${...}" with braces inside; the mask marks
    which positions are string content, so brace counting ignores them.
    """
    out, mask = [], []
    modes = [["code", 0]]          # stack: code (with interpolation depth) or string
    i, n = 0, len(src)
    while i < n:
        c, mode = src[i], modes[-1]
        if mode[0] == "string":
            if c == "\\" and i + 1 < n:
                out += [c, src[i + 1]]; mask += [True, True]; i += 2; continue
            if src.startswith("${", i) or src.startswith("%{", i):
                out += [c, "{"]; mask += [True, True]; i += 2
                modes.append(["interp", 0]); continue
            out.append(c); mask.append(c != '"'); i += 1
            if c == '"':
                modes.pop()
            continue
        if c == "#" or src.startswith("//", i):
            while i < n and src[i] != "\n":
                out.append(" "); mask.append(False); i += 1
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out += [" " if ch != "\n" else ch for ch in src[i:end]]; mask += [False] * (end - i)
            i = end; continue
        if c == '"':
            modes.append(["string", 0]); out.append(c); mask.append(False); i += 1; continue
        if mode[0] == "interp":
            if c == "{":
                mode[1] += 1
            elif c == "}":
                if mode[1] == 0:
                    modes.pop(); out.append(c); mask.append(True); i += 1; continue
                mode[1] -= 1
            mask.append(True)
        else:
            mask.append(False)
        out.append(c); i += 1
    return "".join(out), mask


HEADER = re.compile(r'([A-Za-z_][\w-]*)((?:\s+"[^"]*")*)\s*$')


def blocks(code, mask=None):
    """Top-level blocks: a list of (type, [labels], body)."""
    if mask is None:
        code, mask = strip_comments(code)
    found, depth, line_start, opened, head = [], 0, 0, None, None
    for i, c in enumerate(code):
        if mask[i]:
            continue
        if c == "\n" and depth == 0:
            line_start = i + 1
        elif c == "{":
            if depth == 0:
                opened = i
                head = HEADER.search(code[line_start:i])
            depth += 1
        elif c == "}":
            depth -= 1
            assert depth >= 0, "brace closed without opening"
            if depth == 0 and head and opened is not None:
                labels = re.findall(r'"([^"]*)"', head.group(2))
                found.append((head.group(1), labels, code[opened + 1:i]))
                opened, head = None, None
    assert depth == 0, "brace opened without closing"
    return found


def children(body, kind):
    return [b for b in blocks(body) if b[0] == kind]


def attribute(body, name):
    """Value (raw text, one line) of a top-level attribute of the body."""
    code, mask = strip_comments(body)
    depth, line_depth, start = 0, 0, 0
    pattern = re.compile(r"\s*" + re.escape(name) + r"\s*=\s*(.+?)\s*$")
    for i, c in enumerate(code + "\n"):
        if c == "\n":
            m = pattern.match(code[start:i])
            if m and line_depth == 0:
                return m.group(1)
            start, line_depth = i + 1, depth
        elif not mask[i] and c in "{([":
            depth += 1
        elif not mask[i] and c in "})]":
            depth -= 1
    return None


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def templates():
    """(name, text) of every .tf and .tf.example in the templates, placeholders replaced."""
    out = []
    for root, _, files in os.walk(os.path.join(SKILL, "templates")):
        for a in sorted(files):
            if a.endswith(".tf") or a.endswith(".tf.example"):
                text = read(os.path.join(root, a))
                text = text.replace("{{resource}}", EXAMPLES.get(a, "example"))
                out.append((a, re.sub(r"\{\{\w+\}\}", "example", text)))
    return out


def resources(text):
    return {(b[1][0], b[1][1]): b[2] for b in blocks(text) if b[0] == "resource"}


def data_sources(text):
    return {(b[1][0], b[1][1]): b[2] for b in blocks(text) if b[0] == "data"}


# --- static ---

def test_parser_ignores_comment_and_brace_in_string():
    text = ('# resource "aws_s3_bucket" "fake" {\n'
            'resource "aws_sqs_queue" "q" {\n'
            '  name = "${local.a}-{x}" # }\n'
            '  b = var.x == "" ? null : "}"\n'
            '}\n')
    found = blocks(text)
    assert [(t, r) for t, r, _ in found] == [("resource", ["aws_sqs_queue", "q"])], found
    assert attribute(found[0][2], "b") == 'var.x == "" ? null : "}"'


def test_skill_metadata_and_references_resolve():
    text = read(os.path.join(SKILL, "SKILL.md"))
    assert text.startswith("---\nname: cloud-resource\n"), "frontmatter must name cloud-resource"
    desc = re.search(r"^description: (.+)$", text, re.M)
    assert desc and len(desc.group(1)) <= 700, "description missing or longer than 700 chars"
    if ": " in desc.group(1):
        assert desc.group(1).startswith(("'", '"')), "quote a YAML description with colon-space"
    cited = set(re.findall(r"`(references/[^`]+\.md)`", text))
    for link in cited:
        assert os.path.isfile(os.path.join(SKILL, link)), f"SKILL.md cites missing {link}"
    shipped = {"references/" + a for a in os.listdir(os.path.join(SKILL, "references"))}
    assert shipped <= cited, f"references not listed in SKILL.md: {sorted(shipped - cited)}"


def test_project_map_is_an_empty_template():
    text = read(os.path.join(SKILL, "references", "project-map.md"))
    rows = [line for line in text.splitlines()
            if line.startswith("|") and not re.fullmatch(r"[|\-\s]+", line)]
    assert len(rows) >= 2, "project map needs its header and a placeholder row"
    for row in rows[1:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        for cell in cells:
            assert re.fullmatch(r"`<[^`>]+>`(?: \(`<[^`>]+>`\))?", cell), \
                f"project map ships filled, not as a template: {row}"
    assert re.search(r"Reading of: `<YYYY-MM-DD>`", text), "the reading date must stay a placeholder"


def test_no_private_paths_or_keys():
    forbidden = re.compile(r"/home/[a-z]+/|/Users/[A-Za-z]+/|-----BEGIN .*PRIVATE KEY-----")
    for root, _, files in os.walk(SKILL):
        for a in files:
            path = os.path.join(root, a)
            assert not os.path.islink(path), f"{path}: symlink"
            hit = forbidden.search(read(path))
            assert not hit, f"{os.path.relpath(path, ROOT)}: private context {hit.group(0)}"


def test_stack_has_remote_backend():
    roots = 0
    for name, text in templates():
        for t, _, body in blocks(text):
            if t != "terraform":
                continue
            roots += 1
            back = children(body, "backend")
            assert back, f"{name}: terraform block without a backend"
            assert all(b[1] and b[1][0] != "local" for b in back), f"{name}: local backend"
    assert roots >= 1, "the template stack must declare the terraform block"
    envs = [a for a in os.listdir(STACK) if re.fullmatch(r"backend\.\w+\.hcl", a)]
    assert len(envs) >= 2, "one backend.<env>.hcl per environment, at least two"
    for a in envs:
        code, _ = strip_comments(read(os.path.join(STACK, a)))
        for key in ("bucket", "key", "region"):
            assert re.search(rf"^\s*{key}\s*=", code, re.M), f"{a}: missing {key}"
        assert re.search(r"^\s*use_lockfile\s*=\s*true", code, re.M), f"{a}: no use_lockfile"
        assert "kms_key_id" not in code, f"{a}: kms_key_id does not go in the backend"


def test_no_literal_account_id():
    for root, _, files in os.walk(SKILL):
        for a in files:
            path = os.path.join(root, a)
            text = read(path)
            hit = re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text)
            assert not hit, f"{os.path.relpath(path, ROOT)}: literal account id {hit.group(0)}"
            assert not re.search(r"arn:aws[\w-]*:[\w-]*:[\w-]*:[0-9]", text), \
                f"{os.path.relpath(path, ROOT)}: ARN with a literal account"


def test_account_lock_and_default_tags():
    prov = blocks(read(os.path.join(STACK, "providers.tf")))
    aws = [c for t, r, c in prov if t == "provider" and r == ["aws"]]
    assert aws, "providers.tf has no aws provider"
    assert "var.expected_account_id" in (attribute(aws[0], "allowed_account_ids") or ""), \
        "allowed_account_ids must come from var.expected_account_id"
    dt = children(aws[0], "default_tags")
    assert dt and attribute(dt[0][2], "tags") == "local.tags", "default_tags must use local.tags"
    loc = [c for t, _, c in blocks(read(os.path.join(STACK, "locals.tf"))) if t == "locals"][0]
    tags = loc[loc.index("tags"):]
    for key in ("Environment", "Project", "Service", "Repository"):
        assert re.search(rf"\b{key}\s*=", tags), f"default tag {key} missing"
    assert re.search(r'ManagedBy\s*=\s*"terraform"', tags), "ManagedBy must be terraform"
    assert re.search(r'^\s*service\s*=\s*"', loc, re.M), "Service is a local, never a tfvar"


def test_no_workspace_nor_remote_state():
    for name, text in templates():
        code, _ = strip_comments(text)
        assert "terraform.workspace" not in code, f"{name}: uses a workspace"
        assert "terraform_remote_state" not in code, f"{name}: uses terraform_remote_state"
        assert not re.search(r"force_destroy\s*=\s*true", code), f"{name}: force_destroy"


def _named_key(name, value, data):
    """kms_master_key_id reads the key named by alias (data source) or the one created in the stack."""
    assert value, f"{name}: resource without kms_master_key_id"
    ref = re.search(r"data\.aws_kms_key\.(\w+)", value)
    if ref:
        body = data.get(("aws_kms_key", ref.group(1)))
        assert body is not None, f"{name}: data.aws_kms_key.{ref.group(1)} not declared"
        assert attribute(body, "key_id") == "var.kms_key_alias", \
            f"{name}: the key must come from var.kms_key_alias"
    else:
        assert re.search(r"\baws_kms_key\.\w+\.arn", value), f"{name}: unnamed key ({value})"


def test_every_example_resource_encrypted():
    seen = 0
    for name, text in templates():
        res, data = resources(text), data_sources(text)
        for (kind, label), body in res.items():
            if kind in AUXILIARY:
                continue
            seen += 1
            where = f"{name}: {kind}.{label}"
            if kind == "aws_s3_bucket":
                ref = f"aws_s3_bucket.{label}"
                count = attribute(body, "count")

                def sibling(t):
                    found = [c for (tt, _), c in res.items()
                             if tt == t and ref in (attribute(c, "bucket") or "")]
                    assert found, f"{where}: missing {t}"
                    assert attribute(found[0], "count") == count, \
                        f"{where}: {t} with a count different from the bucket's ({count})"
                    return found[0]

                sse = sibling("aws_s3_bucket_server_side_encryption_configuration")
                rule = children(sse, "rule")
                assert rule, f"{where}: SSE without rule"
                assert attribute(rule[0][2], "bucket_key_enabled") == "true", \
                    f"{where}: bucket_key_enabled cuts the KMS cost"
                default = children(rule[0][2], "apply_server_side_encryption_by_default")
                assert default, f"{where}: SSE without apply_server_side_encryption_by_default"
                assert attribute(default[0][2], "sse_algorithm") == '"aws:kms"', f"{where}: not aws:kms"
                _named_key(where, attribute(default[0][2], "kms_master_key_id"), data)

                block = sibling("aws_s3_bucket_public_access_block")
                for k in ("block_public_acls", "block_public_policy",
                          "ignore_public_acls", "restrict_public_buckets"):
                    assert attribute(block, k) == "true", f"{where}: {k} must be true"
                versioning = children(sibling("aws_s3_bucket_versioning"), "versioning_configuration")
                assert versioning and attribute(versioning[0][2], "status") == '"Enabled"', \
                    f"{where}: versioning off"
            elif kind == "aws_sqs_queue":
                _named_key(where, attribute(body, "kms_master_key_id"), data)
                assert attribute(body, "sqs_managed_sse_enabled"), \
                    f"{where}: unencrypted on the empty-alias fallback"
            else:
                raise AssertionError(f"{where}: type with no encryption rule in this test; add one")
    assert seen >= 4, f"expected the resources of all three examples, saw {seen}"


def test_durable_data_has_prevent_destroy():
    res = resources(dict(templates())["durable-data.tf.example"])
    for (kind, label), body in res.items():
        if kind in AUXILIARY:
            continue
        lifecycle = children(body, "lifecycle")
        assert lifecycle and attribute(lifecycle[0][2], "prevent_destroy") == "true", \
            f"durable-data: {kind}.{label} without prevent_destroy = true"


# --- real terraform, when available ---
#
# Offline by default: the default run opens no socket. `terraform fmt -check`
# needs no provider and runs whenever a terraform that meets required_version
# is on the PATH. init/validate/test download the AWS provider (~760 MB) from
# the registry, so they run only with SQUAD_TF_ONLINE=1. That mode is for a
# local check by hand; it is not part of CI. It pins the provider to
# AWS_PROVIDER_TESTED (override with SQUAD_TF_AWS_VERSION) through an override
# file, because the template leaves the minor open and ships no lock file.

AWS_PROVIDER_TESTED = "6.71.0"


class Skip(Exception):
    """The test did not run; the runner prints SKIP instead of ok."""


def _skip(reason):
    print("NOTICE:", reason)
    raise Skip(reason)


def _version(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


def _pessimistic(constraint):
    """`~> X.Y` (or `~> X.Y.Z`) as (floor, ceiling); other forms fail the test."""
    m = re.fullmatch(r"~>\s*(\d+(?:\.\d+){1,2})", constraint.strip())
    assert m, f"unsupported version constraint in this test: {constraint!r}"
    floor = _version(m[1])
    ceiling = floor[:-2] + (floor[-2] + 1,)
    return floor, ceiling


def _declared(name):
    """A constraint from the stack's versions.tf: required_version or a provider."""
    code, _ = strip_comments(read(os.path.join(STACK, "versions.tf")))
    if name == "terraform":
        m = re.search(r'required_version\s*=\s*"([^"]+)"', code)
    else:
        m = re.search(name + r'\s*=\s*\{[^}]*?version\s*=\s*"([^"]+)"', code, re.S)
    assert m, f"versions.tf: no constraint for {name}"
    return m[1]


def _within(version, constraint):
    floor, ceiling = _pessimistic(constraint)
    return floor <= version[:len(floor)] and version[:len(ceiling)] < ceiling


def _tf_env():
    # CHECKPOINT_DISABLE: terraform's update check is a network call of its own.
    return dict(os.environ, TF_IN_AUTOMATION="1", CHECKPOINT_DISABLE="1")


def _tf(args, cwd, env):
    p = subprocess.run(["terraform", *args, "-no-color"], cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=600)
    return p.returncode, (p.stdout + p.stderr).strip()


def _require_terraform():
    """Skip with a notice when terraform is missing or older than required_version."""
    if not shutil.which("terraform"):
        _skip("terraform not found")
    rc, out = _tf(["version", "-json"], ROOT, _tf_env())
    assert rc == 0, f"terraform version failed:\n{out}"
    found = _version(json.loads(out)["terraform_version"])
    wanted = _declared("terraform")
    if not _within(found, wanted):
        _skip(f"terraform {'.'.join(map(str, found))} does not meet required_version {wanted}")


def build_stack(target):
    """Copy the stack and put the three examples inside it as .tf files."""
    shutil.copytree(STACK, target, dirs_exist_ok=True)
    for a, name in EXAMPLES.items():
        text = read(os.path.join(RESOURCE, a)).replace("{{resource}}", name)
        with open(os.path.join(target, a.replace(".tf.example", ".tf")), "w") as fh:
            fh.write(text)
    for root, _, files in os.walk(target):
        for a in files:
            if a.endswith(".tf") or a.endswith(".hcl"):
                path = os.path.join(root, a)
                text = re.sub(r"\{\{\w+\}\}", "example", read(path))
                with open(path, "w") as fh:
                    fh.write(text)


def pin_provider(target, version):
    """Pin the AWS provider with an override file, inside the declared constraint."""
    wanted = _declared("aws")
    assert _within(_version(version), wanted), \
        f"pinned aws provider {version} is outside versions.tf ({wanted})"
    with open(os.path.join(target, "pin_override.tf"), "w") as fh:
        fh.write('terraform {\n  required_providers {\n    aws = {\n'
                 '      source  = "hashicorp/aws"\n'
                 f'      version = "= {version}"\n    }}\n  }}\n}}\n')


def test_terraform_fmt():
    _require_terraform()
    tmp = tempfile.mkdtemp(prefix="cloud-resource-")
    try:
        build_stack(tmp)
        rc, out = _tf(["fmt", "-check", "-recursive", "-diff"], tmp, _tf_env())
        assert rc == 0, f"terraform fmt -check failed:\n{out}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_terraform_init_validate_and_test_online():
    if os.environ.get("SQUAD_TF_ONLINE") != "1":
        _skip("init/validate/test download the AWS provider; set SQUAD_TF_ONLINE=1 to run them")
    _require_terraform()
    tmp = tempfile.mkdtemp(prefix="cloud-resource-")
    try:
        build_stack(tmp)
        pin_provider(tmp, os.environ.get("SQUAD_TF_AWS_VERSION", AWS_PROVIDER_TESTED))
        env = _tf_env()
        env.setdefault("TF_PLUGIN_CACHE_DIR",
                       os.path.join(tempfile.gettempdir(), "squad-terraform-plugin-cache"))
        os.makedirs(env["TF_PLUGIN_CACHE_DIR"], exist_ok=True)
        rc, out = _tf(["init", "-backend=false", "-input=false"], tmp, env)
        assert rc == 0, f"terraform init failed:\n{out}"
        rc, out = _tf(["validate"], tmp, env)
        assert rc == 0, f"terraform validate failed:\n{out}"
        rc, out = _tf(["test"], tmp, env)
        assert rc == 0, f"terraform test failed:\n{out}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Skip as e:
                print("SKIP", name, "-", e)
                continue
            print("ok  ", name)
