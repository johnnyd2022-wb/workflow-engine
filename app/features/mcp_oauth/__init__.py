"""Public MCP, phase 8.2b: sign-in for assistants (OAuth 2.1 authorization server, read-only tokens).

Spec: ``.agents/specs/public-mcp.md``. The app is the authorization server; a separate resource
server (``bize_mcp``, phase 8.2c) forwards the caller's bearer token to the ordinary JSON API.
"""

# What a token with the ``bize.read`` scope may reach (see ``access_policy`` for the rule).
SCOPE_READ = "bize.read"
SUPPORTED_SCOPES = (SCOPE_READ,)
