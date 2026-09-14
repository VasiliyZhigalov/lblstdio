class DomainError(Exception):
    """Base class for all domain-layer errors."""


class DomainValidationException(DomainError):
    """Raised when a domain invariant is violated."""


class ResourceNotFoundException(DomainError):
    """Raised when a requested aggregate cannot be found."""


class UnverifiedDataException(DomainError):
    """Raised when unverified data is used where only verified data is allowed."""


class InsufficientVerifiedDataException(DomainValidationException):
    """Raised when too few verified frames are available for a dataset version."""


class KeypointMatchingFailedException(DomainValidationException):
    """Raised when keypoint matching cannot project a box onto the target frame."""
