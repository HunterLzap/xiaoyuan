import sys

from .config import ROOT

COMMUNITY_ROOT = ROOT / "third_party" / "xiaozhi-server"
if str(COMMUNITY_ROOT) not in sys.path:
    sys.path.insert(0, str(COMMUNITY_ROOT))

from core.connection import ConnectionHandler
from core.utils.audioRateController import AudioRateController
from core.handle.abortHandle import handleAbortMessage

__all__ = ["ConnectionHandler", "AudioRateController", "handleAbortMessage"]
