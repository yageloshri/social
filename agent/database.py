"""
Database schema and models for the Content Master Agent.
Uses SQLAlchemy ORM for clean database interactions.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from pathlib import Path

from .config import config

Base = declarative_base()


class Post(Base):
    """Scraped social media post with metrics."""
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    platform = Column(String(20), nullable=False)  # 'instagram' or 'tiktok'
    post_id = Column(String(100), unique=True, nullable=False)
    url = Column(String(500))

    # Content
    caption = Column(Text)
    hashtags = Column(JSON)  # List of hashtags
    mentions = Column(JSON)  # List of mentions
    media_type = Column(String(20))  # 'video', 'image', 'carousel'
    duration_seconds = Column(Integer)  # For videos

    # Metrics (updated over time)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    engagement_rate = Column(Float, default=0.0)

    # Analysis
    category = Column(String(50))  # 'couple_content', 'story_times', etc.
    topics = Column(JSON)  # List of detected topics
    sentiment = Column(String(20))  # 'positive', 'neutral', 'negative'
    hook_text = Column(String(500))  # Opening line/hook
    ai_analysis = Column(Text)  # Claude's detailed analysis
    success_score = Column(Float)  # 0-100 score

    # Timestamps
    posted_at = Column(DateTime)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    metric_history = relationship("PostMetricHistory", back_populates="post")


class PostMetricHistory(Base):
    """Historical metrics for tracking post performance over time."""
    __tablename__ = "post_metric_history"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)

    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    saves = Column(Integer, default=0)

    recorded_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    post = relationship("Post", back_populates="metric_history")


class Idea(Base):
    """Generated content idea with tracking."""
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True)

    # Idea content
    title = Column(String(200), nullable=False)
    hook = Column(String(500))  # Exact opening line
    description = Column(Text, nullable=False)
    steps = Column(JSON)  # List of steps
    duration_recommendation = Column(String(50))
    hashtags = Column(JSON)
    best_time = Column(String(50))

    # Categorization
    category = Column(String(50))  # 'couple_content', etc.
    based_on_trend = Column(String(200))  # If inspired by a trend
    based_on_pattern = Column(String(200))  # Which success pattern

    # Prediction
    predicted_performance = Column(String(20))  # 'high', 'medium', 'low'
    predicted_engagement = Column(Float)
    confidence_score = Column(Float)
    reasoning = Column(Text)  # Why this will work

    # Status tracking
    status = Column(String(20), default="generated")  # 'generated', 'sent', 'used', 'skipped'
    sent_at = Column(DateTime)
    used_at = Column(DateTime)

    # If used, link to the actual post
    resulting_post_id = Column(Integer, ForeignKey("posts.id"))

    # Creator feedback
    creator_rating = Column(Integer)  # 1-5 rating
    creator_feedback = Column(Text)

    # Performance comparison
    actual_vs_predicted = Column(Float)  # Ratio of actual/predicted

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    resulting_post = relationship("Post")


class Message(Base):
    """Sent WhatsApp message log."""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)

    # Message content
    message_type = Column(String(20), nullable=False)  # 'morning', 'midday', 'afternoon', 'evening'
    content = Column(Text, nullable=False)

    # Related ideas
    idea_ids = Column(JSON)  # List of idea IDs included
    trend_ids = Column(JSON)  # List of trend IDs mentioned

    # Delivery
    twilio_sid = Column(String(100))
    status = Column(String(20), default="sent")  # 'sent', 'delivered', 'read', 'failed'

    # Timestamps
    sent_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime)
    read_at = Column(DateTime)


class Trend(Base):
    """Tracked trend from RSS feeds."""
    __tablename__ = "trends"

    id = Column(Integer, primary_key=True)

    # Source
    source = Column(String(100), nullable=False)  # Feed name/URL
    source_url = Column(String(500))

    # Content
    title = Column(String(500), nullable=False)
    summary = Column(Text)
    full_content = Column(Text)

    # Relevance
    relevance_score = Column(Float)  # 0-100
    matched_keywords = Column(JSON)  # Keywords that matched
    category = Column(String(50))  # 'entertainment', 'news', etc.

    # Content opportunity
    content_opportunity = Column(Text)  # AI-generated suggestion
    urgency = Column(String(20))  # 'immediate', 'today', 'this_week'

    # Status
    status = Column(String(20), default="new")  # 'new', 'notified', 'used', 'expired'
    notified_at = Column(DateTime)
    used_in_idea_id = Column(Integer, ForeignKey("ideas.id"))

    # Timestamps
    published_at = Column(DateTime)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class SuccessPattern(Base):
    """Learned success pattern from historical analysis."""
    __tablename__ = "success_patterns"

    id = Column(Integer, primary_key=True)

    # Pattern identification
    pattern_type = Column(String(50), nullable=False)  # 'category', 'timing', 'format', 'hook_style'
    pattern_value = Column(String(200), nullable=False)

    # Performance metrics
    avg_engagement_rate = Column(Float)
    avg_views = Column(Float)
    sample_size = Column(Integer)
    engagement_multiplier = Column(Float)  # vs baseline

    # Confidence
    confidence = Column(Float)  # 0-1
    last_validated = Column(DateTime)

    # Examples
    example_post_ids = Column(JSON)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreatorPreference(Base):
    """Learned creator preferences."""
    __tablename__ = "creator_preferences"

    id = Column(Integer, primary_key=True)

    # Preference
    preference_type = Column(String(50), nullable=False)  # 'idea_style', 'posting_time', etc.
    preference_value = Column(String(200), nullable=False)

    # Learning data
    acceptance_rate = Column(Float)  # % of ideas accepted
    sample_size = Column(Integer)
    confidence = Column(Float)

    # Timestamps
    learned_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Conversation(Base):
    """WhatsApp conversation history."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)

    # Message details
    phone_number = Column(String(50))
    direction = Column(String(20), nullable=False)  # 'incoming' or 'outgoing'
    content = Column(Text, nullable=False)

    # Context
    detected_command = Column(String(50))  # If a command was detected
    detected_preference = Column(String(200))  # If a preference was detected
    related_idea_id = Column(Integer, ForeignKey("ideas.id"))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)


class UserPreference(Base):
    """User preferences learned from conversations."""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)

    # Preference
    preference_type = Column(String(20), nullable=False)  # 'positive' or 'negative'
    value = Column(String(500), nullable=False)  # What they like/dislike
    original_message = Column(Text)  # The message that expressed this

    # Strength (increases with repeated mentions)
    strength = Column(Float, default=0.5)  # 0-1
    mention_count = Column(Integer, default=1)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_mentioned = Column(DateTime, default=datetime.utcnow)


class DailyReport(Base):
    """Daily summary report."""
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False, unique=True)

    # Activity
    posts_created = Column(Integer, default=0)
    ideas_sent = Column(Integer, default=0)
    ideas_used = Column(Integer, default=0)
    messages_sent = Column(Integer, default=0)

    # Performance
    total_views = Column(Integer, default=0)
    total_engagement = Column(Integer, default=0)
    avg_engagement_rate = Column(Float)
    best_performing_post_id = Column(Integer, ForeignKey("posts.id"))

    # Trends
    trends_discovered = Column(Integer, default=0)
    trends_used = Column(Integer, default=0)

    # Learning
    patterns_updated = Column(Integer, default=0)
    new_insights = Column(JSON)

    # AI Summary
    summary = Column(Text)
    recommendations = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)


class Database:
    """Database manager class."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = config.database.path

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self.Session = sessionmaker(bind=self.engine)

    def create_tables(self):
        """Create all tables if they don't exist."""
        Base.metadata.create_all(self.engine)

    def get_session(self):
        """Get a new database session."""
        return self.Session()

    def close(self):
        """Close the database connection."""
        self.engine.dispose()


# Global database instance
db = Database()
