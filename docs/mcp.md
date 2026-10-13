# Using astroledger from Claude (MCP server)

`astroledger mcp` runs a **read-only** [Model Context Protocol](https://modelcontextprotocol.io)
server. It lets Claude inspect and explain your FITS images and search MAST, using the same
code as the command line.

## Tools

| Tool | What it returns | Touches the network |
|------|-----------------|---------------------|
| `list_files` | FITS files under the data root, with sizes | no |
| `inspect` | The L1 fact sheet of an image: telescope, instrument, bandpass, observing mode, target designation, units, WCS footprint, pixel statistics | no |
| `explain` | Graded statements: L1 measured, L2 inferred with a cited rule or catalogue record, L3 hypothesis with its test. Sources with an L2 inference come first. Pass `gaia_table` (an ECSV of Gaia DR3 sources) to allow stars to be established. | no |
| `search` | MAST observations around a target name or `RA DEC`, with the true bandpass of each | yes (`mast.stsci.edu`) |

The server tells the client, in its instructions, to keep each statement's evidence level, never
to present an L3 as fact, and never to add object names that no catalogue record supplied.

## Security model

- **Read-only.** No tool writes, downloads or deletes anything. Each tool is annotated
  `readOnlyHint: true` and `destructiveHint: false`.
- **One folder.** Every path is resolved inside the data root given at start-up (`--root`,
  default `data/`). Paths that escape it (`..`, absolute paths, or symbolic links pointing
  outside) are refused with a clear error, and `list_files` does not offer them.
- **Errors carry their reason.** Expected failures are returned to the model as tool errors
  with their reason: a refused observing mode, an unreadable file, an unreachable archive.

## Claude Code (local)

The repository's `.mcp.json` registers the server for Claude Code sessions opened in this
folder:

```json
{"mcpServers": {"astroledger": {"command": ".venv/bin/astroledger", "args": ["mcp", "--root", "data"]}}}
```

1. Install the extra: `pip install -e ".[imaging,archives,mcp]"`. The SessionStart hook does this
   in cloud sessions.
2. Put FITS files under `data/`, for example by running
   `python examples/ngc3132_example.py --cache data/ngc3132`.
3. Approve the project MCP server when Claude Code asks, then ask, for example, *"List my FITS
   files and explain the F405N image of NGC 3132 using the Gaia table."*

## The Claude app (iPad, phone, web) as a remote connector

The Claude app connects to MCP servers over HTTPS (Settings → Connectors → add a custom
connector with the server's URL). For that the server must be reachable from the internet:

```bash
astroledger mcp --root /path/to/data --http --host 127.0.0.1 --port 8000   # serves /mcp
```

Put it behind an HTTPS tunnel or reverse proxy that **requires authentication**, for example on
your own machine or the lab computer. Only then give the connector its public URL ending in
`/mcp`.

Do not expose the bare HTTP endpoint: it has no authentication of its own (planned for a later
phase, roadmap §15). Even read-only, it would let anyone read your data folder and run MAST
searches through it.

## Verified

`tests/unit/test_mcp_server.py` drives the server through the MCP protocol: in-process, and as a
stdio subprocess launched exactly as `.mcp.json` launches it. The tests check:
- the tool list and its annotations;
- that paths cannot escape the root;
- the fact sheet;
- graded statements with Gaia;
- the refusal of a coronagraphic file;
- MAST search with a stubbed archive.

On real data, the tools were run against the NGC 3132 cutouts. In this cloud environment
`search` reports the proxy's refusal, because `mast.stsci.edu` is blocked here.
