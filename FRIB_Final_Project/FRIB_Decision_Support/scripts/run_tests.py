"""Run the complete suite and optional security checks in the active FRIB runtime."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--security', action='store_true', help='Also scan source and installed third-party dependencies')
    parser.add_argument('--install-tools', action='store_true', help='Install missing scanners into a separate private tools environment')
    parser.add_argument('--python', help='Use a specific test interpreter, for example a CI environment')
    args = parser.parse_args(arguments)
    spec = importlib.util.spec_from_file_location('frib_check_startup', PROJECT / 'start.py')
    startup = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = startup
    spec.loader.exec_module(startup)
    python = Path(args.python) if args.python else startup.active_python(PROJECT)
    if not python.is_file():
        print('Run the normal START_FRIB launcher once to prepare the application environment.')
        return 2
    report_dir = startup.guard_control_path(PROJECT / '.frib/test-reports')
    report_dir.mkdir(parents=True, exist_ok=True)
    available = subprocess.run([str(python), '-c', 'import pytest'], cwd=PROJECT, capture_output=True, text=True)
    if available.returncode:
        print('The private environment needs the development tools. Stop FRIB, then install this project with its [ui,dev] extras in the private environment. See docs/SECURITY_AUDIT.md.')
        return 2
    print('Running all unit, API, adversarial, UI and distribution tests in disposable workspaces.', flush=True)
    tests = subprocess.run([str(python), '-m', 'pytest', '-q', '--junitxml=' + str(report_dir / 'tests.xml')], cwd=PROJECT)
    if tests.returncode or not args.security:
        print('Test report: ' + str(report_dir / 'tests.xml'), flush=True)
        return tests.returncode
    tool_python = Path(os.environ.get('FRIB_SECURITY_PYTHON', str(python)))
    def scanners_ready(executable):
        return executable.is_file() and subprocess.run([str(executable), '-c', 'import pip_audit, bandit'], capture_output=True).returncode == 0
    if not scanners_ready(tool_python):
        tool_dir = startup.guard_control_path(PROJECT / '.frib/security-tools')
        tool_python = startup.environment_python(tool_dir)
        if not scanners_ready(tool_python):
            if not args.install_tools:
                print('Scanners are missing. Run again with --security --install-tools to install them privately.')
                return 2
            with startup.ProjectLock(PROJECT / '.frib/security-tools.lock'):
                if not scanners_ready(tool_python):
                    print('Preparing private security tools; first setup needs internet.', flush=True)
                    for command in ([str(python), '-m', 'venv', str(tool_dir)],
                                    [str(tool_python), '-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip>=26.1.2', 'pip-audit>=2.10.1', 'bandit>=1.9.4']):
                        result = subprocess.run(command, cwd=PROJECT)
                        if result.returncode: return result.returncode
    paths = subprocess.run([str(python), '-c', 'import site,json; print(json.dumps(site.getsitepackages()))'], capture_output=True, text=True, check=True)
    audit = [str(tool_python), '-m', 'pip_audit', '--skip-editable', '--progress-spinner', 'off', '-f', 'json', '-o', str(report_dir / 'dependencies.json')]
    for path in json.loads(paths.stdout): audit += ['--path', path]
    commands = [
        [str(tool_python), '-m', 'bandit', '-r', 'src', 'start.py', 'scripts', '-ll', '-ii', '-f', 'json', '-o', str(report_dir / 'source-security.json')],
        audit,
    ]
    failed = False
    for command in commands:
        if subprocess.run(command, cwd=PROJECT).returncode: failed = True
    print('Security reports: ' + str(report_dir), flush=True)
    print('A passing scan covers known advisories and tested attacks; it is not proof that every possible vulnerability is absent.', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
