"""
SeriesDetector Skill
====================
Identifies posts with series potential based on performance and comments.
Suggests continuation ideas when a topic can become a recurring series.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Post, ContentSeries, SeriesPart

logger = logging.getLogger(__name__)


class SeriesDetector(BaseSkill):
    """
    Detects posts that could become content series.

    Criteria for series potential:
    - Performance 2x+ average
    - Comments asking for "part 2" / "more"
    - Repeatable topic (not one-time event)
    - Similar content worked before
    """

    def __init__(self):
        super().__init__("SeriesDetector")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

        # Keywords indicating audience wants more
        self.continuation_keywords = [
            'part 2', 'פארט 2', 'חלק 2',
            'המשך', 'עוד', 'תמשיך',
            'מתי הבא', 'עוד אחד',
            'סדרה', 'תעשה עוד',
            'רוצים עוד', 'רוצה עוד',
            'תעלה עוד', 'עוד כאלה',
            'part 3', 'פארט 3', 'חלק 3',
            'הבא', 'next', 'more',
            'תמשיכו', 'ממתינים להמשך'
        ]

        # Topics that are naturally repeatable
        self.repeatable_patterns = [
            'דברים ש', 'things that',
            'טיפים', 'tips',
            'סיבות', 'reasons',
            'סימנים', 'signs',
            'שלבים', 'stages',
            'יום בחיי', 'day in',
            'איך ל', 'how to',
            'מה קורה כש', 'what happens when',
            'pov:', 'POV:',
            'סוגי', 'types of',
            'דרכים', 'ways to',
            'טעויות', 'mistakes',
            'שיעורים', 'lessons',
            'הבדלים', 'differences'
        ]

    async def execute(self) -> Dict[str, Any]:
        """
        Scan recent successful posts for series potential.
        Run weekly (Saturday evening).
        """
        self.log_start()

        results = {
            "posts_scanned": 0,
            "series_potential_found": 0,
            "alerts_sent": 0,
        }

        try:
            # Get successful posts from last 7 days
            successful_posts = await self._get_successful_posts(days=7)

            for post in successful_posts:
                results["posts_scanned"] += 1

                analysis = await self.analyze_series_potential(post)

                if analysis["has_potential"]:
                    results["series_potential_found"] += 1

                    # Generate series ideas
                    ideas = await self._generate_series_ideas(post, analysis)

                    # Send alert
                    await self._send_series_alert(post, analysis, ideas)
                    results["alerts_sent"] += 1

            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["error"] = str(e)

        return results

    async def _get_successful_posts(self, days: int = 7) -> List[Post]:
        """Get posts performing above 2x average from last N days."""
        session = db.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)

            # Get all posts for average calculation
            all_posts = session.query(Post).all()
            avg_views = sum(p.views or 0 for p in all_posts) / len(all_posts) if all_posts else 0

            # Get recent posts above 2x average
            recent_posts = session.query(Post).filter(
                Post.posted_at >= cutoff,
                Post.views >= avg_views * 2
            ).order_by(Post.views.desc()).all()

            # Filter out posts already part of a series
            existing_series_posts = set()
            series_parts = session.query(SeriesPart).all()
            for part in series_parts:
                if part.post_id:
                    existing_series_posts.add(part.post_id)

            return [p for p in recent_posts if p.id not in existing_series_posts]

        finally:
            session.close()

    async def analyze_series_potential(self, post: Post) -> Dict[str, Any]:
        """
        Analyze if post has series potential.

        Returns score 0-100 and reasons.
        """
        session = db.get_session()
        try:
            score = 0
            reasons = []

            # Get average views for comparison
            all_posts = session.query(Post).all()
            avg_views = sum(p.views or 0 for p in all_posts) / len(all_posts) if all_posts else 1

            # 1. Performance check (2x+ average) - 30 points
            if (post.views or 0) >= avg_views * 2:
                multiplier = (post.views or 0) / avg_views
                score += 30
                reasons.append(f"ביצועים גבוהים: פי {multiplier:.1f} מהממוצע")

            # 2. Check for continuation comments - 30 points
            continuation_count = await self._count_continuation_comments(post)
            if continuation_count >= 5:
                score += 30
                reasons.append(f"{continuation_count} תגובות מבקשות המשך!")
            elif continuation_count >= 3:
                score += 20
                reasons.append(f"{continuation_count} תגובות מבקשות המשך")
            elif continuation_count >= 1:
                score += 10
                reasons.append(f"יש בקשות להמשך בתגובות")

            # 3. Repeatable topic check - 20 points
            if self._is_repeatable_topic(post):
                score += 20
                reasons.append("נושא שאפשר להמשיך")

            # 4. Similar content worked before - 20 points
            similar_posts = await self._find_similar_successful_posts(post)
            if similar_posts:
                score += 20
                reasons.append(f"תוכן דומה הצליח בעבר ({len(similar_posts)} פוסטים)")

            return {
                "score": score,
                "has_potential": score >= 50,
                "reasons": reasons,
                "continuation_comments": continuation_count,
            }

        finally:
            session.close()

    async def _count_continuation_comments(self, post: Post) -> int:
        """
        Count comments asking for more/part 2.
        Note: This requires comment data from scraper.
        """
        # For now, estimate based on engagement rate
        # In production, would parse actual comments
        comments_count = post.comments or 0

        # Estimate ~5-10% of engaged comments ask for more on viral posts
        if (post.views or 0) > 50000:
            estimated = int(comments_count * 0.08)
        elif (post.views or 0) > 20000:
            estimated = int(comments_count * 0.05)
        else:
            estimated = int(comments_count * 0.02)

        return min(estimated, 20)  # Cap at 20

    def _is_repeatable_topic(self, post: Post) -> bool:
        """Check if topic can have multiple parts."""
        caption_lower = (post.caption or "").lower()
        return any(pattern in caption_lower for pattern in self.repeatable_patterns)

    async def _find_similar_successful_posts(self, post: Post) -> List[Post]:
        """Find similar posts that also performed well."""
        session = db.get_session()
        try:
            # Get posts with similar category that performed well
            if not post.category:
                return []

            all_posts = session.query(Post).all()
            avg_views = sum(p.views or 0 for p in all_posts) / len(all_posts) if all_posts else 1

            similar = session.query(Post).filter(
                Post.id != post.id,
                Post.category == post.category,
                Post.views >= avg_views * 1.5
            ).limit(5).all()

            return similar

        finally:
            session.close()

    async def _generate_series_ideas(self, post: Post, analysis: Dict) -> Dict[str, str]:
        """Use Claude to generate series continuation ideas."""
        if not self.client:
            return {
                "part_2": "רעיון להמשך...",
                "part_3": "רעיון נוסף...",
                "part_4": "עוד רעיון...",
                "spinoff": "וריאציה על הנושא...",
            }

        prompt = f"""אתה עוזר ליוצר תוכן ישראלי (מוזיקאי, תוכן זוגיות).

הסרטון המקורי שהצליח:
כיתוב: "{post.caption}"
צפיות: {post.views:,}
לייקים: {post.likes:,}

צור 4 רעיונות להמשך סדרה.
כל רעיון צריך להיות קשור אבל ייחודי.

החזר JSON בלבד:
{{
    "part_2": "כותרת/רעיון לחלק 2",
    "part_3": "כותרת/רעיון לחלק 3",
    "part_4": "כותרת/רעיון לחלק 4",
    "spinoff": "וריאציה/ספין-אוף של הנושא"
}}"""

        try:
            response = self.client.messages.create(
                model=config.ai.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            import json
            text = response.content[0].text
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])

        except Exception as e:
            logger.error(f"Error generating series ideas: {e}")

        return {
            "part_2": "המשך הסיפור...",
            "part_3": "עוד זווית על הנושא...",
            "part_4": "סיכום / קטע בונוס...",
            "spinoff": "וריאציה עם טוויסט...",
        }

    async def _send_series_alert(self, post: Post, analysis: Dict, ideas: Dict):
        """Send WhatsApp alert about series potential."""
        caption_preview = (post.caption or "")[:40]
        if len(post.caption or "") > 40:
            caption_preview += "..."

        reasons_text = "\n".join(f"• {reason}" for reason in analysis["reasons"])

        message = f"""🎬 *זיהיתי פוטנציאל לסדרה!*

📹 הסרטון '{caption_preview}' עשה {post.views:,} צפיות!

✨ *למה זה מתאים לסדרה:*
{reasons_text}

💡 *רעיונות להמשך:*

🔢 *Part 2:* {ideas.get('part_2', '')}

🔢 *Part 3:* {ideas.get('part_3', '')}

🔢 *Part 4:* {ideas.get('part_4', '')}

🔄 *Spin-off:* {ideas.get('spinoff', '')}

📈 *למה סדרות עובדות:*
✅ אנשים חוזרים לראות המשך
✅ קל לייצר - הנוסחה כבר עובדת
✅ אלגוריתם אוהב המשכיות
✅ בונה ציפייה וקהל נאמן

---
שלח "סדרות" לראות את כל הסדרות שלך"""

        sid = whatsapp.send_message(message)
        logger.info(f"Series alert sent for post {post.id}")
        return sid is not None

    async def create_series(self, post: Post, name: str, ideas: List[str]) -> ContentSeries:
        """Create a new content series from a successful post."""
        session = db.get_session()
        try:
            series = ContentSeries(
                name=name,
                original_post_id=post.id,
                total_parts_planned=len(ideas) + 1,  # +1 for original
                parts_posted=1,
            )
            session.add(series)
            session.flush()

            # Add original post as part 1
            part_1 = SeriesPart(
                series_id=series.id,
                part_number=1,
                post_id=post.id,
                idea=post.caption,
                status="posted"
            )
            session.add(part_1)

            # Add planned parts
            for i, idea in enumerate(ideas, 2):
                part = SeriesPart(
                    series_id=series.id,
                    part_number=i,
                    idea=idea,
                    status="planned"
                )
                session.add(part)

            session.commit()
            return series

        finally:
            session.close()

    async def get_series_summary(self) -> Dict[str, Any]:
        """
        Get summary of all series.
        Used for "סדרות" command.
        """
        session = db.get_session()
        try:
            active_series = []
            potential_series = []

            # Get all series
            series_list = session.query(ContentSeries).order_by(
                ContentSeries.created_at.desc()
            ).all()

            for series in series_list:
                # Get parts
                parts = session.query(SeriesPart).filter(
                    SeriesPart.series_id == series.id
                ).order_by(SeriesPart.part_number).all()

                posted_parts = [p for p in parts if p.status == "posted"]
                planned_parts = [p for p in parts if p.status == "planned"]

                # Get views for posted parts
                total_views = 0
                for part in posted_parts:
                    if part.post_id:
                        post = session.query(Post).get(part.post_id)
                        if post:
                            total_views += post.views or 0

                series_info = {
                    "id": series.id,
                    "name": series.name,
                    "parts_posted": len(posted_parts),
                    "parts_planned": series.total_parts_planned,
                    "total_views": total_views,
                    "next_idea": planned_parts[0].idea if planned_parts else None,
                }

                if planned_parts:
                    active_series.append(series_info)

            # Get potential series (high-performing posts not yet in series)
            potential = await self._get_successful_posts(days=30)
            for post in potential[:3]:  # Top 3
                analysis = await self.analyze_series_potential(post)
                if analysis["has_potential"]:
                    potential_series.append({
                        "post_id": post.id,
                        "caption": (post.caption or "")[:40],
                        "views": post.views,
                        "score": analysis["score"],
                    })

            return {
                "active": active_series,
                "potential": potential_series,
            }

        finally:
            session.close()
