from enum import Enum


class SourceType(str, Enum):
    MANUAL = "MANUAL"
    KEYPOINT_PROPAGATION = "KEYPOINT_PROPAGATION"
    MODEL_PREDICTION = "MODEL_PREDICTION"


class VerificationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ImageStatus(str, Enum):
    UNANNOTATED = "UNANNOTATED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ImageSourceType(str, Enum):
    MANUAL_UPLOAD = "MANUAL_UPLOAD"
    STREAM_INGEST = "STREAM_INGEST"
    DATASET_IMPORT = "DATASET_IMPORT"


class SplitType(str, Enum):
    TRAIN = "train"
    VALID = "valid"
    TEST = "test"


class DatasetVersionStatus(str, Enum):
    PREPARING = "PREPARING"
    READY = "READY"
    FAILED = "FAILED"


class TrainingJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AutoLabelJobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
