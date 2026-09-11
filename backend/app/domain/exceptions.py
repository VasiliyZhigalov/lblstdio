class DomainError(Exception):
    """Base class for all domain-layer errors."""


class DomainValidationException(DomainError):
    """Raised when a domain invariant is violated."""


class ResourceNotFoundException(DomainError):
    """Raised when a requested aggregate cannot be found."""


class UnverifiedDataException(DomainError):
    """Raised when unverified data is used where only verified data is allowed."""
