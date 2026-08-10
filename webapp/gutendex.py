"""Search the Project Gutenberg catalog via the Gutendex JSON API.

Thin wrapper over book_creator.fetch.search_gutenberg (the shared
implementation, also used by the librarian agent) so existing callers of
this module keep working unchanged.
"""

from __future__ import annotations

from book_creator.fetch import search_gutenberg as search  # noqa: F401
