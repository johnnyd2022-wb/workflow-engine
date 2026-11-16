"""bize_mcp: the public MCP server for Biz-E (roadmap 8.2c).

A protocol adapter. It speaks MCP (Streamable HTTP, stateless) to an assistant such as Claude or
ChatGPT, and turns each tool call into one read-only ``GET`` on the Biz-E app, forwarding the
caller's bearer token. All authority (who the person is, what their role may read, tenant
isolation) stays in the app; this package holds no database credentials and no app secrets.

It imports nothing from ``app/`` (an import-graph test, AC29, enforces that), so it can run in a
container that has no copy of the application.

Spec: ``.agents/specs/public-mcp.md``, "bize_mcp server (8.2c)".
"""
