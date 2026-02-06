"""
Skills Package
==============
Each skill is an independent, specialized module that handles a specific function.
Skills can be improved and tested separately.
"""

from .profile_scanner import ProfileScanner
from .deep_analyzer import DeepAnalyzer
from .trend_radar import TrendRadar
from .idea_engine import IdeaEngine
from .message_crafter import MessageCrafter
from .memory_core import MemoryCore
from .feedback_learner import FeedbackLearner
from .golden_moment import GoldenMomentDetector

__all__ = [
    "ProfileScanner",
    "DeepAnalyzer",
    "TrendRadar",
    "IdeaEngine",
    "MessageCrafter",
    "MemoryCore",
    "FeedbackLearner",
    "GoldenMomentDetector",
]
