# Security review and repeatable tests

The download includes the source, existing unit/API/UI/distribution tests and adversarial regression tests added during the security review. All test data is disposable; the distribution excludes saved user uploads, databases and machine-specific environments.

## Changes included

- The local API checks browser origins and hostnames, bounds the complete request before multipart parsing, and keeps formula-like source text literal in standardized CSV exports. Original source JSON remains unchanged.
- Upload parsing rejects malformed CSV and UTC overflow, limits records, source size, document extraction and chunk output, and avoids the reproduced pathological regular expressions.
- File storage rejects redirected paths and symlink aliases. Distribution builders reject archive traversal, external linked files and nested private settings.
- Approved-document indexing validates embedding counts, dimensions and finite values. Cached workers refresh document deletion state; nonfinite retrieval scores are rejected.
- Model-generated draft timestamps cannot override the application timestamp; human review remains mandatory for reusable knowledge.
- Runtime shutdown handles terminal/process signals, duplicate launches reuse the verified local instance, and setup requires pip >=26.1.2.
- Test report XML is bounded and DTD/entity declarations are rejected. Local health requests and package-version checks restrict destinations and redirects.

## Run the tests

On macOS, double-click **RUN_UNIT_TESTS.command** in the extracted bundle, or **Run Unit Tests.command** in the source folder. Prepare the application with its normal launcher first.

If a fresh private environment lacks development dependencies, stop the app and install the declared extras using its active Python. From the source folder, this command finds that interpreter and installs the development tools without altering system Python:

```sh
python3.12 -c 'import start,subprocess; p=start.active_python(start.PROJECT); raise SystemExit(subprocess.call([str(p),"-m","pip","install","-e",str(start.PROJECT)+"[ui,dev]"]))'
```

For a prepared development environment, run:

```sh
python3.12 scripts/run_tests.py
```

**RUN_SECURITY_CHECKS.command** also runs the tests and security scans. Its first scanner installation needs internet and uses a separate `.frib/security-tools` environment. Reports go under `.frib/test-reports`. The source folder includes a GitHub Actions workflow template for tests, source scanning and package-advisory checks; it runs when the source is hosted as a GitHub repository, not merely by downloading this ZIP.

## Scope and limits

The earlier installed-package advisory snapshot is dated October 13, 2026. It reported pip 23.2.1; after updating to 26.2.1, 59 checked third-party distributions had no known advisories in that snapshot. This is historical evidence, not a current October 20 advisory scan. Optional AI packages not installed in that environment were not audited. The complete local application is tested on macOS Python 3.12; Windows-specific and unavailable optional-tool checks may be skipped.

The API is intended for a single-user local workspace, not an unauthenticated public deployment. These tests do not establish that every possible malicious PDF is isolated, that model answers are semantically correct, that the operating system/Python/browser is free of vulnerabilities, or that simultaneous malicious file replacement by another process with the same OS privileges is prevented. Human review and source checks remain necessary. No audit can guarantee prevention of every future vulnerability.
