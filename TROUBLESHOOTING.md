# Troubleshooting

Common issues and solutions for the GEDCOM MCP Server.

## Installation Issues

### "Command not found: gedcom-server"

**Problem:** After installing with `uv tool install`, the command is not found.

**Solution:** Ensure uv's tool bin directory is in your PATH:
```bash
# Add to ~/.bashrc, ~/.zshrc, or equivalent
export PATH="$HOME/.local/bin:$PATH"

# Reload shell config
source ~/.bashrc  # or ~/.zshrc
```

**Alternative:** Use `uvx` instead, which doesn't require PATH setup:
```bash
uvx gedcom-server --gedcom-file /path/to/tree.ged
```

### "No such file or directory" when starting server

**Problem:** GEDCOM file path not found.

**Solution:** Use absolute paths, not relative paths:
```bash
# Bad - relative path
gedcom-server --gedcom-file family.ged

# Good - absolute path
gedcom-server --gedcom-file /Users/you/Documents/family.ged

# Good - expand ~ to home directory
gedcom-server --gedcom-file ~/Documents/family.ged
```

## Runtime Issues

### "No individuals found in GEDCOM file"

**Problem:** Server starts but reports 0 individuals.

**Possible causes:**
1. **Empty or corrupt GEDCOM file** - Test by opening in genealogy software (Gramps, Ancestry.com)
2. **Wrong file format** - Ensure file is GEDCOM 5.5.1 (most genealogy software uses this)
3. **Encoding issues** - Try re-exporting GEDCOM as UTF-8

**Solution:**
```bash
# Check file size
ls -lh /path/to/tree.ged

# Check first few lines (should start with "0 HEAD")
head -n 20 /path/to/tree.ged
```

### "Permission denied" error

**Problem:** Cannot read GEDCOM file.

**Solution:** Check file permissions:
```bash
# View permissions
ls -l /path/to/tree.ged

# Fix permissions if needed
chmod 644 /path/to/tree.ged
```

## Semantic Search Issues

### Semantic search tool not available

**Problem:** `semantic_search` tool returns error: "sentence-transformers not installed"

**Solution:** Enable semantic search:
```bash
export SEMANTIC_SEARCH_ENABLED=true
gedcom-server --gedcom-file /path/to/tree.ged
```

The sentence-transformers library is included in dependencies, but the feature must be explicitly enabled.

### First run is very slow

**Problem:** First run with semantic search takes 15-30 seconds to start.

**Explanation:** This is normal! The server is:
1. Parsing the GEDCOM file
2. Building text embeddings for all individuals
3. Saving embeddings to cache file

**Cache location:** `{gedcom-file}.embeddings.npz`

Subsequent runs load from cache and start in seconds.

### Embeddings cache not updating after GEDCOM changes

**Problem:** Search results are stale after updating GEDCOM file.

**Solution:** Cache is hash-validated. If embeddings aren't rebuilding:
```bash
# Manually delete cache files
rm /path/to/tree.ged.embeddings.npz
rm /path/to/tree.ged.geocache.json

# Restart server
gedcom-server --gedcom-file /path/to/tree.ged
```

## GIS Search Issues

### `search_nearby` returns no results

**Problem:** GIS search finds no people near a location.

**Possible causes:**
1. **Geocoding not complete** - Background geocoding thread is still running
2. **Location not found** - Try different location names
3. **No people in that area** - Your tree may not have people in that region

**Check geocoding progress:**
```bash
# Server logs show geocoding progress
# Look for: "Geocoded X/Y places..."
```

**Geocoding cache location:** `{gedcom-file}.geocache.json`

### Geocoding is very slow

**Problem:** Background geocoding takes a long time.

**Explanation:** The server rate-limits Nominatim API requests to 1 per second (respectful usage). For large trees with many unique places, this can take time.

**Coverage:** Check `get_statistics()` result for geocoding coverage percentage.

**Note:** Geocoding runs in background and doesn't block server startup. You can start using other tools immediately.

### Network timeout errors during geocoding

**Problem:** Geocoding fails with timeout errors.

**Solution:**
1. Check internet connection
2. Nominatim may be temporarily unavailable
3. Restart server to retry failed locations
4. Cached locations won't be re-requested

## Query Tool Issues

### Query tool fails with "Missing API key"

**Problem:** Natural language `query` tool returns error about API key.

**Solution:** Set Anthropic API key:
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
gedcom-server --gedcom-file /path/to/tree.ged
```

**Note:** Only the `query` tool requires an API key. All other tools work without it.

**Alternative:** Use specific tools directly instead of the query tool:
- `get_biography` instead of "tell me about person X"
- `get_ancestors` instead of "show me ancestors"
- `get_relationship` instead of "how are X and Y related"

## Performance Issues

### Slow startup time

**Normal startup times:**
- Small files (<1MB, <1000 people): 1-2 seconds
- Medium files (1-10MB, 1000-10000 people): 2-5 seconds
- Large files (>10MB, >10000 people): 5-10 seconds

**Additional time for optional features:**
- Semantic search (first run): +15-30 seconds (cached thereafter)
- GIS geocoding: Runs in background, doesn't block startup

**If startup is much slower:**
1. Check if semantic search is enabled (disable if not needed)
2. Check if GEDCOM file has unusual complexity
3. Check system resources (memory, CPU)

### High memory usage

**Expected memory usage:**
- Base server: ~50-100MB
- Small trees (<1000 people): +50-100MB
- Medium trees (1000-10000 people): +100-300MB
- Large trees (>10000 people): +300-500MB
- Semantic search: +200-300MB

**If memory usage is excessive:**
1. Disable semantic search if not needed
2. Check for memory leaks (shouldn't happen, but report if found)

## Claude Desktop Issues

### Server not appearing in Claude Desktop

**Problem:** After configuring, server doesn't show up.

**Solution:**
1. **Check config location:**
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%/Claude/claude_desktop_config.json`

2. **Validate JSON:**
   ```bash
   # macOS
   cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | python -m json.tool
   ```

3. **Restart Claude Desktop** after config changes

4. **Check server logs** in Claude Desktop: View → Server Logs

### "Server crashed" error in Claude Desktop

**Problem:** Server starts but immediately crashes.

**Common causes:**
1. **GEDCOM_FILE not set or file not found**
   ```json
   {
     "mcpServers": {
       "gedcom": {
         "command": "uvx",
         "args": ["gedcom-server"],
         "env": {
           "GEDCOM_FILE": "/full/path/to/tree.ged"
         }
       }
     }
   }
   ```

2. **Path contains spaces** - Use absolute paths:
   ```json
   "GEDCOM_FILE": "/Users/name/My Documents/tree.ged"
   ```

3. **uvx or gedcom-server not in PATH**
   - Try full path to uvx: `/usr/local/bin/uvx`
   - Or use `uv tool install gedcom-server` and use full path

### Server logs show errors

**Check logs location:**
- Claude Desktop: View → Server Logs
- Look for lines with "GEDCOM" or "gedcom_server"

**Common error patterns:**
- "FileNotFoundError" → Check GEDCOM_FILE path
- "PermissionError" → Check file permissions
- "ImportError" → Reinstall: `uvx --force gedcom-server`

## Getting More Help

### Verbose logging

For debugging, run server manually with verbose logs:
```bash
GEDCOM_FILE=/path/to/tree.ged python -m gedcom_server 2>&1 | tee debug.log
```

This captures all startup logging and errors.

### Reporting Issues

If you encounter a bug:

1. **Check this troubleshooting guide first**
2. **Verify your setup:**
   - GEDCOM file is valid (opens in other software)
   - All tests pass: `uv run poe test`
   - Using latest version: `pip show gedcom-server`

3. **Open an issue** with:
   - Description of the problem
   - Steps to reproduce
   - Error messages from logs
   - GEDCOM file stats from `get_statistics()` (don't share the file itself)
   - System info (OS, Python version)

**GitHub Issues:** https://github.com/sjmatta/gedcom-mcp/issues

### Performance Profiling

For performance issues, gather stats:
```bash
# Check GEDCOM file size
ls -lh /path/to/tree.ged

# Get statistics
# Use get_statistics() tool via Claude Desktop or MCP client
# Record: individual count, family count, date range
```

Include these stats when reporting performance issues.
