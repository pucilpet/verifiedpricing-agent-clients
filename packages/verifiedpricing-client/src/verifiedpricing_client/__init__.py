"""Public client shared by the CLI and local protocol adapters."""

from .client import Client, ClientError

__version__ = "0.1.1"
__all__ = ["Client", "ClientError", "__version__"]
