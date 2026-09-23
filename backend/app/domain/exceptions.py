class DomainError(Exception):
    """Base class for all domain-layer errors."""


class DomainValidationException(DomainError):
    """Raised when a domain invariant is violated."""


class ResourceNotFoundException(DomainError):
    """Raised when a requested aggregate cannot be found."""


class UnverifiedDataException(DomainError):
    """Raised when unverified data is used where only verified data is allowed."""


class InsufficientVerifiedDataException(DomainError):
    """Raised when too few verified frames are available for a dataset version."""


class DatasetVersionConflictException(DomainError):
    """Raised when a dataset version number collides under concurrency."""


class KeypointMatchingFailedException(DomainValidationException):
    """Raised when keypoint matching cannot project a box onto the target frame."""


class DatasetNotReadyException(DomainValidationException):
    """Raised when training is requested for a non-READY dataset version."""


class ModelWeightsMissingException(DomainValidationException):
    """Raised when model weights file is missing on disk."""


class TaskTypeMismatchException(DomainError):
    """Raised when an operation does not apply to the project's task type."""
