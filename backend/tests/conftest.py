"""Root fixtures shared by both suites.

Sets placeholder DB credentials before ``app.db`` is imported anywhere, since
``Settings`` has no defaults for them and the unit suite never opens a real
connection (its ``get_session`` dependency is overridden with a fake).
"""

import os

os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")
