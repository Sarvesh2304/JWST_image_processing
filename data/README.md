# Local data folder

This is where the examples cache their downloads and outputs, for instance
`python examples/ngc3132_example.py --cache data/ngc3132`. It is also the default root of the
read-only MCP server (`astroledger mcp --root data`): its tools can read only files under this
folder.

Everything here except this README is git-ignored. FITS data are never committed.
