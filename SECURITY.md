# Security Policy

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

**DO NOT** open a public GitHub issue for security vulnerabilities.

Instead, please email security concerns to: **[Your email will be added here]**

### What to Include

Please include the following information in your report:

1. **Description** - Clear description of the vulnerability
2. **Steps to reproduce** - Detailed steps to reproduce the issue
3. **Impact** - Your assessment of the potential impact
4. **Affected versions** - Which versions are affected
5. **Suggested fix** - If you have one (optional)
6. **Your contact information** - For follow-up questions

### Response Timeline

- **Acknowledgment**: Within 48 hours of report
- **Initial assessment**: Within 7 days
- **Fix timeline**: Depends on severity
  - Critical: Within 7 days
  - High: Within 14 days
  - Medium: Within 30 days
  - Low: Next regular release

### Disclosure Policy

- We will confirm the vulnerability and determine its impact
- We will release a fix as soon as possible
- We will publicly disclose the vulnerability after a fix is available
- We will credit you in the security advisory (unless you prefer to remain anonymous)

## Security Considerations

### GEDCOM Files

**Privacy Notice:**
- GEDCOM files typically contain sensitive personal information (names, dates, relationships)
- The GEDCOM MCP Server runs **locally on your machine** - data never leaves your system
- No data is sent to external servers except:
  - Optional geocoding via Nominatim (only place names, not personal info)
  - Optional query tool via Anthropic API (if you use it)
  - Optional semantic search model download (one-time, from Hugging Face)

**Recommendations:**
- Store GEDCOM files in a secure location
- Use appropriate file permissions (chmod 600 or 640)
- Be cautious when sharing GEDCOM files
- Consider removing living individuals before sharing

### API Keys

The server requires API keys only for optional features:

**Anthropic API Key** (for `query` tool only):
- Store in environment variables, never in code
- Use `.env` files for local development (git-ignored by default)
- Rotate keys regularly
- Use separate keys for development and production

**Never:**
- Commit API keys to version control
- Share API keys in public forums
- Store keys in plain text in shared locations

### Data Access

The server provides read-only access to GEDCOM data:
- **Cannot modify** your GEDCOM files
- **Cannot delete** data
- **Cannot create** new records
- Files are opened in read-only mode

### Network Security

**Local-only operation:**
- Server runs on your local machine via stdio
- No network server listening on ports
- Communication only via MCP protocol (stdin/stdout)

**External connections** (optional, can be disabled):
- Nominatim API for geocoding (rate-limited to 1 req/sec)
- Anthropic API for query tool (only if used)
- Hugging Face for semantic search model download (one-time)

### Dependencies

We use the following security practices for dependencies:

1. **Minimal dependencies** - Only essential packages included
2. **Vetted packages** - Use well-maintained, popular packages
3. **Version pinning** - Lock file ensures reproducible builds
4. **Regular updates** - Dependabot will be enabled for automated updates (post-1.0)

Current dependencies include:
- FastMCP (MCP server framework)
- ged4py (GEDCOM parsing)
- rapidfuzz (fuzzy string matching)
- Optional: sentence-transformers, requests, opentelemetry libraries

### Code Quality

Security through code quality:
- Type checking with mypy
- Linting with ruff
- Comprehensive test suite (471 tests)
- Pre-commit hooks enforce quality standards
- Code review process for all changes

## Known Limitations

### Out of Scope

These are explicitly **not** security issues:

1. **GEDCOM data accuracy** - We parse files as-is, cannot validate historical accuracy
2. **Genealogy privacy** - Users are responsible for determining what data to share
3. **Third-party GEDCOM exports** - We parse GEDCOM 5.5.1 format, but cannot control source data quality
4. **Living individuals** - GEDCOM format includes all individuals; filter before sharing if needed

### Performance

Not security issues but worth noting:
- Large GEDCOM files (>100MB) may use significant memory
- Background geocoding makes external API requests
- Semantic search builds embeddings on first run (may take 30+ seconds)

## Security Updates

Security updates will be:
1. Released as patch versions (e.g., 1.0.1, 1.0.2)
2. Announced in CHANGELOG.md
3. Posted as GitHub Security Advisories
4. Mentioned in release notes

## Questions

For security-related questions that are not vulnerabilities, you can:
- Open a GitHub Discussion
- Ask in Issues (if not sensitive)

Thank you for helping keep GEDCOM MCP Server secure!
