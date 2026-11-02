# Changelog

## 0.2.0

- Save and apply exact plans with source hashes, root binding and collision checks.
- Read-only recovery diagnosis and complete version 2 transaction journals.
- Preflight all restore entries; reject unsafe paths, links, duplicate paths,
  malformed records, oversized JSON, and corrupt required backups.
- Protect formula-like CSV cells by default; explicit raw export remains available.
- Add fault-injection tests and a synthetic example with recovery instructions.
