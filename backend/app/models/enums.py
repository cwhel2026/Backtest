import enum


class AssetClass(str, enum.Enum):
    EQUITY_INDEX = "equity_index"
    METAL = "metal"
    ENERGY = "energy"
    CURRENCY = "currency"


class DataProviderStatus(str, enum.Enum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    ERROR = "error"


class DatasetValidationStatus(str, enum.Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    FAILED = "failed"


class StrategyLifecycle(str, enum.Enum):
    RESEARCHING = "researching"
    BACKTESTING = "backtesting"
    REJECTED = "rejected"
    HISTORICALLY_VALIDATED = "historically_validated"
    PAPER_TRADING = "paper_trading"
    PAPER_VALIDATED = "paper_validated"
    ELIGIBLE_FOR_APPROVAL = "eligible_for_approval"
    APPROVED_FOR_DEPLOYMENT = "approved_for_deployment"
    PAUSED = "paused"
    RETIRED = "retired"


class ResearchJobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchJobKind(str, enum.Enum):
    DATA_INGESTION = "data_ingestion"
    BACKTEST = "backtest"
    VALIDATION = "validation"
    AI_HYPOTHESIS = "ai_hypothesis"
    PAPER_SYNC = "paper_sync"
    HEALTH_CHECK = "health_check"


class PerformanceCategory(str, enum.Enum):
    BACKTEST = "backtest"
    OUT_OF_SAMPLE = "out_of_sample"
    WALK_FORWARD = "walk_forward"
    PAPER = "paper"
    LIVE = "live"


class ForwardTestState(str, enum.Enum):
    HISTORICAL_RESEARCH = "historical_research"
    HISTORICALLY_VALIDATED = "historically_validated"
    FORWARD_TEST_PENDING = "forward_test_pending"
    FORWARD_TEST_RUNNING = "forward_test_running"
    FORWARD_TEST_PAUSED = "forward_test_paused"
    FORWARD_TEST_FAILED = "forward_test_failed"
    FORWARD_TEST_REVIEW = "forward_test_review"
    PAPER_BROKER_ELIGIBLE = "paper_broker_eligible"


class MarketLatencyMode(str, enum.Enum):
    REALTIME = "realtime"
    DELAYED = "delayed"
    HISTORICAL_REPLAY = "historical_replay"
    SYNTHETIC = "synthetic"


class LiveFeedConnectionStatus(str, enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STALE = "stale"
    DEGRADED = "degraded"
    ERROR = "error"


class PaperOrderState(str, enum.Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class ScannerSetupStatus(str, enum.Enum):
    DETECTED = "DETECTED"
    PENDING_ENTRY = "PENDING_ENTRY"
    FILLED_PAPER = "FILLED_PAPER"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    INVALIDATED = "INVALIDATED"