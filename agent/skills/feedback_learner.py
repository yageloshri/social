"""
FeedbackLearner Skill
=====================
Processes feedback and improves recommendations over time.
Learns from both explicit and implicit feedback.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import json

from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Idea, Post, SuccessPattern, CreatorPreference

logger = logging.getLogger(__name__)


class FeedbackLearner(BaseSkill):
    """
    Processes feedback to improve recommendations.

    Feedback Types:
    - Explicit: Creator rates/comments on ideas
    - Implicit: Detecting if similar content was posted after idea sent

    Learning Actions:
    - Adjust pattern weights based on outcomes
    - Update creator preferences
    - Improve prediction accuracy
    """

    def __init__(self):
        super().__init__("FeedbackLearner")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

    async def execute(
        self,
        operation: str = "learn_from_recent"
    ) -> Dict[str, Any]:
        """
        Execute learning operations.

        Args:
            operation: Operation type
                - 'learn_from_recent': Analyze recent ideas and outcomes
                - 'detect_used_ideas': Find ideas that were likely used
                - 'update_weights': Update pattern weights
                - 'analyze_predictions': Compare predictions vs actuals

        Returns:
            Dict with learning results
        """
        self.log_start()

        results = {"operation": operation}

        try:
            if operation == "learn_from_recent":
                results = await self._learn_from_recent()
            elif operation == "detect_used_ideas":
                results = await self._detect_used_ideas()
            elif operation == "update_weights":
                results = await self._update_weights()
            elif operation == "analyze_predictions":
                results = await self._analyze_predictions()
            else:
                results["error"] = f"Unknown operation: {operation}"

            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["error"] = str(e)

        return results

    async def _learn_from_recent(self) -> Dict[str, Any]:
        """
        Learn from recent idea outcomes.

        Returns:
            Learning summary
        """
        # First detect which ideas were likely used
        detection_results = await self._detect_used_ideas()

        # Then update weights based on outcomes
        weight_results = await self._update_weights()

        # Analyze prediction accuracy
        prediction_results = await self._analyze_predictions()

        return {
            "ideas_analyzed": detection_results.get("ideas_analyzed", 0),
            "ideas_matched_to_posts": detection_results.get("matches_found", 0),
            "patterns_updated": weight_results.get("patterns_updated", 0),
            "prediction_accuracy": prediction_results.get("accuracy", 0),
            "insights": prediction_results.get("insights", []),
            "summary": "Learning cycle complete"
        }

    async def _detect_used_ideas(self) -> Dict[str, Any]:
        """
        Detect ideas that were likely used based on similar posts.

        Returns:
            Detection results
        """
        session = db.get_session()
        try:
            # Get ideas sent in the last 7 days that haven't been marked as used
            ideas = session.query(Idea).filter(
                Idea.sent_at >= datetime.utcnow() - timedelta(days=7),
                Idea.status == "sent"
            ).all()

            if not ideas:
                return {"ideas_analyzed": 0, "matches_found": 0}

            # Get posts from the same period
            posts = session.query(Post).filter(
                Post.posted_at >= datetime.utcnow() - timedelta(days=7)
            ).all()

            matches_found = 0

            for idea in ideas:
                # Look for posts that appeared after the idea was sent
                # and might match the idea content
                for post in posts:
                    if not post.posted_at or not idea.sent_at:
                        continue

                    # Post must be after idea was sent
                    if post.posted_at < idea.sent_at:
                        continue

                    # Post must be within 48 hours of idea
                    if (post.posted_at - idea.sent_at) > timedelta(hours=48):
                        continue

                    # Check for content similarity
                    if self._check_content_match(idea, post):
                        idea.status = "used"
                        idea.used_at = post.posted_at
                        idea.resulting_post_id = post.id
                        matches_found += 1
                        break

            session.commit()

            return {
                "ideas_analyzed": len(ideas),
                "matches_found": matches_found,
                "summary": f"Found {matches_found} matches out of {len(ideas)} ideas"
            }

        finally:
            session.close()

    def _check_content_match(self, idea: Idea, post: Post) -> bool:
        """
        Check if a post matches an idea.

        Args:
            idea: The generated idea
            post: The posted content

        Returns:
            True if likely a match
        """
        if not post.caption:
            return False

        post_text = post.caption.lower()
        idea_text = (idea.hook or "" + idea.description or "").lower()

        # Check for keyword overlap
        idea_words = set(idea_text.split())
        post_words = set(post_text.split())

        # Remove common words
        common_words = {"את", "של", "על", "עם", "לא", "כן", "אני", "היא", "הוא", "זה", "מה"}
        idea_words -= common_words
        post_words -= common_words

        if not idea_words:
            return False

        overlap = len(idea_words & post_words)
        overlap_ratio = overlap / len(idea_words)

        # Consider it a match if >30% overlap
        if overlap_ratio > 0.3:
            return True

        # Also check category match
        if idea.category and post.category and idea.category == post.category:
            # Lower threshold for same category
            if overlap_ratio > 0.15:
                return True

        return False

    async def _update_weights(self) -> Dict[str, Any]:
        """
        Update pattern weights based on idea outcomes.

        Returns:
            Update results
        """
        session = db.get_session()
        try:
            # Get ideas with outcomes
            used_ideas = session.query(Idea).filter(
                Idea.status == "used",
                Idea.resulting_post_id.isnot(None)
            ).all()

            skipped_ideas = session.query(Idea).filter(
                Idea.status == "skipped"
            ).all()

            patterns_updated = 0

            # Boost patterns from used ideas
            for idea in used_ideas:
                if idea.based_on_pattern:
                    pattern = session.query(SuccessPattern).filter(
                        SuccessPattern.pattern_value.contains(idea.based_on_pattern)
                    ).first()

                    if pattern:
                        # Increase confidence and multiplier slightly
                        pattern.confidence = min(0.95, (pattern.confidence or 0.5) + 0.05)

                        # Check actual performance
                        if idea.resulting_post_id:
                            post = session.query(Post).filter_by(id=idea.resulting_post_id).first()
                            if post and post.engagement_rate:
                                # Get baseline
                                baseline = session.query(Post).filter(
                                    Post.posted_at >= datetime.utcnow() - timedelta(days=90)
                                ).all()
                                avg_engagement = sum(p.engagement_rate or 0 for p in baseline) / len(baseline) if baseline else 1

                                actual_multiplier = post.engagement_rate / avg_engagement if avg_engagement > 0 else 1

                                # Blend actual with predicted
                                pattern.engagement_multiplier = (
                                    (pattern.engagement_multiplier or 1) * 0.7 + actual_multiplier * 0.3
                                )

                        pattern.last_validated = datetime.utcnow()
                        pattern.sample_size = (pattern.sample_size or 0) + 1
                        patterns_updated += 1

            # Decrease confidence for patterns from skipped ideas
            for idea in skipped_ideas:
                if idea.based_on_pattern:
                    pattern = session.query(SuccessPattern).filter(
                        SuccessPattern.pattern_value.contains(idea.based_on_pattern)
                    ).first()

                    if pattern:
                        # Slight decrease in confidence
                        pattern.confidence = max(0.1, (pattern.confidence or 0.5) - 0.02)
                        patterns_updated += 1

            session.commit()

            return {
                "patterns_updated": patterns_updated,
                "used_ideas_processed": len(used_ideas),
                "skipped_ideas_processed": len(skipped_ideas),
                "summary": f"Updated {patterns_updated} patterns"
            }

        finally:
            session.close()

    async def _analyze_predictions(self) -> Dict[str, Any]:
        """
        Analyze prediction accuracy.

        Returns:
            Accuracy analysis
        """
        session = db.get_session()
        try:
            # Get ideas that were used and have performance data
            ideas_with_outcomes = session.query(Idea).filter(
                Idea.status == "used",
                Idea.resulting_post_id.isnot(None),
                Idea.predicted_engagement.isnot(None)
            ).all()

            if not ideas_with_outcomes:
                return {"accuracy": 0, "insights": ["Not enough data yet"]}

            # Get baseline engagement
            posts_90d = session.query(Post).filter(
                Post.posted_at >= datetime.utcnow() - timedelta(days=90)
            ).all()
            baseline = sum(p.engagement_rate or 0 for p in posts_90d) / len(posts_90d) if posts_90d else 1

            predictions = []
            actuals = []

            for idea in ideas_with_outcomes:
                post = session.query(Post).filter_by(id=idea.resulting_post_id).first()
                if post and post.engagement_rate and idea.predicted_engagement:
                    predicted_multiplier = idea.predicted_engagement
                    actual_multiplier = post.engagement_rate / baseline if baseline > 0 else 1

                    predictions.append(predicted_multiplier)
                    actuals.append(actual_multiplier)

                    # Store comparison
                    idea.actual_vs_predicted = actual_multiplier / predicted_multiplier if predicted_multiplier > 0 else 1

            session.commit()

            if not predictions:
                return {"accuracy": 0, "insights": ["Not enough data yet"]}

            # Calculate accuracy (within 30% = accurate)
            accurate_count = sum(
                1 for p, a in zip(predictions, actuals)
                if 0.7 <= a/p <= 1.3
            )
            accuracy = accurate_count / len(predictions) * 100

            # Generate insights
            insights = []

            # Tendency to over or under predict
            avg_ratio = sum(a/p for p, a in zip(predictions, actuals)) / len(predictions)
            if avg_ratio < 0.8:
                insights.append("Predictions tend to be optimistic. Consider lowering confidence.")
            elif avg_ratio > 1.2:
                insights.append("Predictions tend to be conservative. Content performs better than expected!")

            # Category-specific insights
            # (Would need to group by category and analyze separately)

            return {
                "accuracy": round(accuracy, 1),
                "predictions_analyzed": len(predictions),
                "avg_actual_vs_predicted": round(avg_ratio, 2),
                "insights": insights,
                "summary": f"Prediction accuracy: {accuracy:.1f}%"
            }

        finally:
            session.close()

    async def process_explicit_feedback(
        self,
        idea_id: int,
        rating: int = None,
        feedback: str = None,
        was_helpful: bool = None
    ) -> Dict[str, Any]:
        """
        Process explicit feedback from creator.

        Args:
            idea_id: ID of the idea
            rating: 1-5 rating
            feedback: Text feedback
            was_helpful: Whether the idea was helpful

        Returns:
            Processing result
        """
        session = db.get_session()
        try:
            idea = session.query(Idea).filter_by(id=idea_id).first()
            if not idea:
                return {"error": "Idea not found"}

            if rating:
                idea.creator_rating = rating
            if feedback:
                idea.creator_feedback = feedback

            # Determine if positive or negative
            is_positive = (rating and rating >= 4) or was_helpful

            # Update creator preference
            if idea.category:
                pref = session.query(CreatorPreference).filter_by(
                    preference_type="category",
                    preference_value=idea.category
                ).first()

                if pref:
                    # Update acceptance rate
                    current_rate = pref.acceptance_rate or 0.5
                    pref.acceptance_rate = current_rate * 0.9 + (1 if is_positive else 0) * 0.1
                    pref.sample_size = (pref.sample_size or 0) + 1
                    pref.confidence = min(0.95, 0.3 + pref.sample_size * 0.05)
                else:
                    new_pref = CreatorPreference(
                        preference_type="category",
                        preference_value=idea.category,
                        acceptance_rate=1 if is_positive else 0,
                        sample_size=1,
                        confidence=0.3,
                    )
                    session.add(new_pref)

            session.commit()

            return {
                "idea_id": idea_id,
                "feedback_recorded": True,
                "is_positive": is_positive,
                "summary": f"Feedback recorded for idea {idea_id}"
            }

        finally:
            session.close()

    async def get_learning_summary(self) -> Dict[str, Any]:
        """
        Get summary of what the agent has learned.

        Returns:
            Learning summary
        """
        session = db.get_session()
        try:
            # Pattern count
            pattern_count = session.query(SuccessPattern).count()
            high_confidence_patterns = session.query(SuccessPattern).filter(
                SuccessPattern.confidence >= 0.7
            ).count()

            # Preference count
            preference_count = session.query(CreatorPreference).count()

            # Idea stats
            total_ideas = session.query(Idea).count()
            used_ideas = session.query(Idea).filter(Idea.status == "used").count()
            rated_ideas = session.query(Idea).filter(Idea.creator_rating.isnot(None)).count()

            # Average rating
            rated = session.query(Idea).filter(Idea.creator_rating.isnot(None)).all()
            avg_rating = sum(i.creator_rating for i in rated) / len(rated) if rated else 0

            return {
                "patterns_learned": pattern_count,
                "high_confidence_patterns": high_confidence_patterns,
                "preferences_learned": preference_count,
                "total_ideas_generated": total_ideas,
                "ideas_used": used_ideas,
                "idea_acceptance_rate": (used_ideas / total_ideas * 100) if total_ideas > 0 else 0,
                "ideas_rated": rated_ideas,
                "average_rating": round(avg_rating, 1),
                "summary": f"Learned {pattern_count} patterns, {preference_count} preferences. {used_ideas}/{total_ideas} ideas used."
            }

        finally:
            session.close()
