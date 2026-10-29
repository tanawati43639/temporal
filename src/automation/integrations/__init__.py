"""Shared external-service clients, reused across processes.

An integration wraps one external system (a secret store, SharePoint, an email
gateway, an HTTP API, an MCP server...). Activities import integrations to do
their I/O; workflows must never touch them. Process-owned activities live in
each process's ``activities/`` package — only the reusable client lives here.
"""
