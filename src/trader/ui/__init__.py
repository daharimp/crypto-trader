"""Read-only dashboard: a small HTTP server and a phone-first page (ADR-026).

The server answers GET requests only. It reads saved session state, public market data,
and the paper perps replay. It never places orders, changes controls, or reads keys.
"""
