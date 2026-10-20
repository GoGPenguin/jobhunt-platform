"""Parser plugins. Importing this package registers every parser in REGISTRY."""

from jobhunt.sources.parsers import linkedin_email

__all__ = ["linkedin_email"]
