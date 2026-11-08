"""The tests of a site through the host (.github#30 as amended by .github#37): `site-tests.yml` is
the reusable workflow that the `ci.yml` of a site rendered from web-template calls with the input
`site` and the secret `WEB_READ_TOKEN`. It checks the site out at the caller's commit and the host
xippios-web at `main`, requires the site into the host at that commit through a Composer `vcs`
repository, and runs `php artisan test --testsuite=<site>`, Dusk too where the site has browser
tests. The tests read the declaration and the pins, and run the workflow's own steps with `composer`
and `php` replaced by fakes that record their calls; one test runs the requirement with the real
Composer, where the machine has one."""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "site-tests.yml"
# Read lazily, so a missing workflow fails each test, not the collection.
SITE_TESTS = WORKFLOW.read_text() if WORKFLOW.exists() else ""
KEY = "didaskalu"
TOKEN = "github_pat_test0123456789"

FAKE = """\
#!{python}
# A fake `{name}` that records its arguments, one call per line, and serves `composer config name`.
import json, os, sys
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps(["{name}", *sys.argv[1:]]) + "\\n")
if "{name}" == "composer" and sys.argv[1:] == ["config", "name"]:
    print(json.load(open("composer.json")).get("name", ""))
if "{name}" == "composer" and sys.argv[1:2] == ["require"]:
    with open(os.environ["CALLS"] + ".auth", "w") as auth:
        auth.write(os.environ.get("COMPOSER_AUTH", ""))
"""

PLUGIN = """\
<?php

namespace Probe;

use Composer\\Composer;
use Composer\\IO\\IOInterface;
use Composer\\Plugin\\PluginInterface;

class Plugin implements PluginInterface
{
    public function activate(Composer $composer, IOInterface $io)
    {
        touch(getcwd() . '/plugin-ran');
    }

    public function deactivate(Composer $composer, IOInterface $io)
    {
    }

    public function uninstall(Composer $composer, IOInterface $io)
    {
    }
}
"""


def step(name: str) -> str:
    """The `run:` script of the step `name` of site-tests.yml."""
    block = SITE_TESTS.split(f"- name: {name}\n", 1)[1]
    lines = block.split("        run: |\n", 1)[1].splitlines()
    script = []
    for line in lines:
        if line.strip() and not line.startswith("          "):
            break
        script.append(line[10:])
    return "\n".join(script) + "\n"


def steps() -> list[str]:
    """The steps of the job, each as its text."""
    body = "\n" + SITE_TESTS.split("\n    steps:\n", 1)[-1]
    return ["      - " + part.rstrip("\n") + "\n" for part in body.split("\n      - ")[1:]]


def run(name: str, workspace: Path, cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    """Run the step `name` in `cwd` with fakes first on the PATH: exit code and output."""
    bin_dir = workspace.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in ("composer", "php"):
        fake = bin_dir / tool
        fake.write_text(FAKE.format(python=sys.executable, name=tool))
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    done = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step(name)],
        cwd=cwd,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(workspace.parent / "calls"),
            "GITHUB_WORKSPACE": str(workspace),
            "RUNNER_TEMP": str(workspace.parent),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def calls(workspace: Path) -> list[list[str]]:
    """The calls the fakes recorded."""
    path = workspace.parent / "calls"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A runner's workspace: the site at a pull request's commit, detached, and the host."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    (origin / "composer.json").write_text(
        json.dumps({"name": f"xippios/web-{KEY}", "type": "library"}, indent=4) + "\n"
    )
    (origin / "VERSION").write_text("1.0.0\n")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "the site")
    git(origin, "tag", "v1.0.0")
    (origin / "VERSION").write_text("the pull request\n")
    git(origin, "commit", "-q", "-am", "the pull request")
    work = tmp_path / "work"
    site = work / "site"
    site.mkdir(parents=True)
    # As actions/checkout fetches a pull request: one commit, no branch.
    git(site, "init", "-q")
    git(site, "fetch", "-q", "--depth", "1", origin.as_uri(), "main")
    git(site, "checkout", "-q", "--detach", "FETCH_HEAD")
    (work / "host").mkdir()
    return work


def test_site_tests_runs_as_a_called_job_only() -> None:
    triggers = SITE_TESTS.split("\non:\n", 1)[-1].split("\npermissions:", 1)[0]
    assert "workflow_call:" in triggers
    assert "pull_request" not in triggers
    assert "push" not in triggers
    assert "\npermissions:\n  contents: read\n" in SITE_TESTS


def test_the_call_declares_the_input_site_and_the_secret_web_read_token() -> None:
    # The names of the call that web-template renders into a site's ci.yml (.github#37).
    call = "\n" + SITE_TESTS.split("\n  workflow_call:\n", 1)[-1].split("\npermissions:", 1)[0]
    inputs = call.split("\n    inputs:\n", 1)[-1].split("\n    secrets:\n", 1)[0]
    assert re.fullmatch(
        r"      site:\n        description: .+\n        required: true\n        type: string\n?",
        inputs,
    ), inputs
    secrets = call.split("\n    secrets:\n", 1)[-1]
    assert re.fullmatch(
        r"      WEB_READ_TOKEN:\n        description: .+\n        required: true\n?", secrets
    ), secrets


def test_the_input_and_the_secret_reach_scripts_through_the_environment() -> None:
    lines = [line for line in SITE_TESTS.splitlines() if "${{" in line]
    assert lines
    for line in lines:
        assert re.fullmatch(
            r" +(?:[A-Z_]+|token): \$\{\{ (?:inputs\.site|secrets\.WEB_READ_TOKEN) \}\}", line
        ), line


def test_actions_are_pinned_to_commits_and_no_checkout_keeps_a_credential() -> None:
    uses = re.findall(r"uses: (\S+)(?: # (v?[\d.]+))?", SITE_TESTS.split("\njobs:\n", 1)[-1])
    assert len(uses) == 3
    for ref, version in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), ref
        assert version, ref
    checkouts = [text for text in steps() if "uses: actions/checkout@" in text]
    assert len(checkouts) == 2
    for text in checkouts:
        assert "persist-credentials: false" in text


def test_the_site_is_checked_out_at_the_callers_commit_and_the_host_at_main() -> None:
    site, host = (text for text in steps() if "uses: actions/checkout@" in text)
    assert "path: site\n" in site
    assert "repository:" not in site
    assert "ref:" not in site
    assert "token:" not in site
    assert "repository: xippios/xippios-web\n" in host
    assert "ref: main\n" in host
    assert "path: host\n" in host
    assert "token: ${{ secrets.WEB_READ_TOKEN }}\n" in host


def test_the_token_reaches_only_the_host_checkout_and_composers_resolution() -> None:
    job = SITE_TESTS.split("\njobs:\n", 1)[-1].split("\n    steps:\n", 1)[0]
    assert "WEB_READ_TOKEN" not in job
    holders = [text.splitlines()[0] for text in steps() if "secrets.WEB_READ_TOKEN" in text]
    assert holders == [
        "      - name: token",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
        "      - name: require",
    ]
    for name in ("site", "environment", "suite", "dusk"):
        assert "WEB_READ_TOKEN" not in step(name), name


def test_php_and_composer_are_pinned() -> None:
    setup = next(text for text in steps() if "uses: shivammathur/setup-php@" in text)
    assert 'php-version: "8.4"\n' in setup
    assert re.search(r"tools: composer:\d+\.\d+\.\d+\n", setup), setup
    assert "coverage: none\n" in setup


def test_an_empty_token_fails_naming_the_secret(workspace: Path) -> None:
    code, out = run("token", workspace, workspace, {"WEB_READ_TOKEN": ""})
    assert code != 0, out
    assert "the secret WEB_READ_TOKEN is empty" in out
    code, out = run("token", workspace, workspace, {"WEB_READ_TOKEN": TOKEN})
    assert code == 0, out


def test_the_site_names_the_checked_out_commit_the_branch_site_tests(workspace: Path) -> None:
    site = workspace / "site"
    code, out = run("site", workspace, site, {"SITE": KEY})
    assert code == 0, out
    assert git(site, "rev-parse", "site-tests") == git(site, "rev-parse", "HEAD")
    assert calls(workspace) == [["composer", "config", "name"]]


@pytest.mark.parametrize("key", ["", "Didaskalu", "-didaskalu", "didaskalu-", "a--b", "a b", "a;b"])
def test_a_key_web_template_would_refuse_fails(workspace: Path, key: str) -> None:
    code, out = run("site", workspace, workspace / "site", {"SITE": key})
    assert code != 0, out
    assert "the input site is no site key" in out
    assert calls(workspace) == []


def test_a_site_whose_package_is_not_named_by_its_key_fails(workspace: Path) -> None:
    site = workspace / "site"
    code, out = run("site", workspace, site, {"SITE": "maul"})
    assert code != 0, out
    assert "the site's composer.json does not name xippios/web-maul" in out
    assert "site-tests" not in git(site, "branch", "--list")


def test_the_site_is_required_through_a_vcs_repository_on_its_checkout(workspace: Path) -> None:
    env = {"SITE": KEY, "WEB_READ_TOKEN": TOKEN}
    code, out = run("require", workspace, workspace / "host", env)
    assert code == 0, out
    assert calls(workspace) == [
        [
            "composer",
            "config",
            "--no-plugins",
            "repositories.site-tests",
            "vcs",
            str(workspace / "site"),
        ],
        [
            "composer",
            "require",
            f"xippios/web-{KEY}:dev-site-tests",
            "--update-with-dependencies",
            "--no-scripts",
            "--no-plugins",
            "--no-interaction",
            "--no-progress",
        ],
    ]
    auth = json.loads((workspace.parent / "calls.auth").read_text())
    assert auth == {"github-oauth": {"github.com": TOKEN}}


def test_the_environment_boots_the_host_without_the_token(workspace: Path) -> None:
    host = workspace / "host"
    (host / ".env.example").write_text("APP_KEY=\n")
    code, out = run("environment", workspace, host, {})
    assert code == 0, out
    assert (host / ".env").read_text() == "APP_KEY=\n"
    assert calls(workspace) == [
        ["composer", "dump-autoload", "--no-interaction"],
        ["php", "artisan", "key:generate", "--no-interaction"],
    ]


def test_the_environment_keeps_an_env_of_the_host(workspace: Path) -> None:
    host = workspace / "host"
    (host / ".env.example").write_text("APP_KEY=\n")
    (host / ".env").write_text("APP_ENV=testing\n")
    code, out = run("environment", workspace, host, {})
    assert code == 0, out
    assert (host / ".env").read_text() == "APP_ENV=testing\n"


def test_the_suite_of_the_site_runs_in_the_host(workspace: Path) -> None:
    code, out = run("suite", workspace, workspace / "host", {"SITE": KEY})
    assert code == 0, out
    assert calls(workspace) == [["php", "artisan", "test", f"--testsuite={KEY}"]]


def test_dusk_does_not_run_without_browser_tests(workspace: Path) -> None:
    code, out = run("dusk", workspace, workspace / "host", {"SITE": KEY})
    assert code == 0, out
    assert "the site has no tests/Browser, so Dusk does not run" in out
    assert calls(workspace) == []


def test_dusk_runs_the_suite_of_the_site_with_the_host_served(workspace: Path) -> None:
    (workspace / "site" / "tests" / "Browser").mkdir(parents=True)
    code, out = run("dusk", workspace, workspace / "host", {"SITE": KEY})
    assert code == 0, out
    recorded = calls(workspace)
    assert ["php", "artisan", "serve", "--no-reload"] in recorded
    assert [call for call in recorded if call[2] != "serve"] == [
        ["php", "artisan", "dusk:chrome-driver", "--detect"],
        ["php", "artisan", "dusk", f"--testsuite={KEY}"],
    ]


def test_dusk_names_the_address_the_host_is_served_at() -> None:
    # Laravel's recipe: `php artisan serve` listens on 127.0.0.1:8000, and APP_URL names it.
    dusk = next(text for text in steps() if text.startswith("      - name: dusk\n"))
    env = dusk.split("        env:\n", 1)[1].split("        run: |\n", 1)[0]
    assert "          APP_URL: http://127.0.0.1:8000\n" in env
    assert "php artisan serve --no-reload >" in step("dusk")


@pytest.mark.skipif(
    not (shutil.which("composer") and shutil.which("php")) and not os.environ.get("GITHUB_ACTIONS"),
    reason="needs Composer and PHP, which the runner of ci has",
)
def test_composer_requires_the_checked_out_commit_over_the_hosts_tag(workspace: Path) -> None:
    origin = workspace.parent / "origin"
    site = workspace / "site"
    host = workspace / "host"
    # A plugin the host allows: it marks each run of Composer that loads it.
    plugin = workspace.parent / "plugin"
    (plugin / "src").mkdir(parents=True)
    git(plugin, "init", "-q", "-b", "main")
    (plugin / "composer.json").write_text(
        json.dumps(
            {
                "name": "xippios/probe-plugin",
                "type": "composer-plugin",
                "require": {"composer-plugin-api": "^2.0"},
                "autoload": {"psr-4": {"Probe\\": "src/"}},
                "extra": {"class": "Probe\\Plugin"},
            },
            indent=4,
        )
        + "\n"
    )
    (plugin / "src" / "Plugin.php").write_text(PLUGIN)
    git(plugin, "add", ".")
    git(plugin, "commit", "-q", "-m", "the plugin")
    git(plugin, "tag", "v1.0.0")
    manifest = {
        "name": "xippios/xippios-web",
        "type": "project",
        "require": {f"xippios/web-{KEY}": "^1.0", "xippios/probe-plugin": "^1.0"},
        "repositories": [
            {"type": "vcs", "url": str(origin)},
            {"type": "vcs", "url": str(plugin)},
            {"packagist.org": False},
        ],
        "config": {"allow-plugins": {"xippios/probe-plugin": True}},
        "scripts": {"post-autoload-dump": ["@php -r \"touch('scripts-ran');\""]},
    }
    (host / "composer.json").write_text(json.dumps(manifest, indent=4) + "\n")
    env = {
        **os.environ,
        "COMPOSER_HOME": str(workspace.parent / "composer-home"),
        "COMPOSER_CACHE_DIR": str(workspace.parent / "composer-cache"),
        # As setup-php sets them for every step.
        "COMPOSER_NO_INTERACTION": "1",
        "COMPOSER_NO_AUDIT": "1",
        "GITHUB_WORKSPACE": str(workspace),
        "SITE": KEY,
        "WEB_READ_TOKEN": TOKEN,
    }
    # The host on main: its lock holds the site's tag.
    subprocess.run(
        ["composer", "update", "--no-scripts", "--no-plugins", "--no-progress"],
        cwd=host,
        env=env,
        check=True,
        capture_output=True,
    )
    assert (host / "vendor" / "xippios" / f"web-{KEY}" / "VERSION").read_text() == "1.0.0\n"
    assert (host / "vendor" / "xippios" / "probe-plugin").is_dir()
    for name, cwd in (("site", site), ("require", host)):
        done = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", step(name)],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
    installed = host / "vendor" / "xippios" / f"web-{KEY}"
    assert (installed / "VERSION").read_text() == "the pull request\n"
    lock = json.loads((host / "composer.lock").read_text())
    (package,) = (p for p in lock["packages"] if p["name"] == f"xippios/web-{KEY}")
    assert package["version"] == "dev-site-tests"
    assert package["source"]["reference"] == git(site, "rev-parse", "HEAD")
    assert not (host / "scripts-ran").exists()
    assert not (host / "plugin-ran").exists()


def test_the_readme_names_the_workflow_its_caller_and_the_secret() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "**`.github/workflows/site-tests.yml`**" in readme
    entry = readme.split("**`.github/workflows/site-tests.yml`**", 1)[-1].split("\n- **", 1)[0]
    assert "uses: xippios/.github/.github/workflows/site-tests.yml@main" in entry
    assert "site:" in entry
    assert "WEB_READ_TOKEN: ${{ secrets.WEB_READ_TOKEN }}" in entry
    assert "web-template" in entry
