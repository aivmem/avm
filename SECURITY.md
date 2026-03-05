# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.9.x   | :white_check_mark: |
| < 0.9   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it by emailing the maintainers directly rather than opening a public issue.

**Do not disclose security vulnerabilities publicly until they have been addressed.**

We will acknowledge receipt within 48 hours and provide a detailed response within 7 days.

## Security Considerations

AVM handles potentially sensitive data. Please consider:

- **Database Security**: The SQLite database may contain sensitive information. Ensure proper file permissions.
- **API Keys**: Store API keys in environment variables, not in code.
- **FUSE Mount**: When using `avm-mount`, be aware of file system permissions.
- **MCP Server**: The MCP server authenticates via `--user` flag. Ensure proper process isolation.
