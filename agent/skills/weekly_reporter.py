"""
WeeklyReporter Skill
====================
Generates comprehensive weekly performance reports.
Sent every Friday evening with full analysis and recommendations.
"""

import logging
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Post, Idea, WeeklyReport as WeeklyReportModel

logger = logging.getLogger(__name__)


class WeeklyReporter(BaseSkill):
    """
    Generates and sends weekly performance reports.

    Report includes:
    - Stats overview (views, likes, comments)
    - Top performing post
    - What worked / didn't work analysis
    - Posting consistency
    - AI-powered recommendations
    """

    def __init__(self):
        super().__init__("WeeklyReporter")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

    async def execute(self) -> Dict[str, Any]:
        """
        Generate and send weekly report.
        Run every Friday at 18:00.
        """
        self.log_start()

        try:
            report = await self.generate_weekly_report()
            message = self._format_report_message(report)

            from ..integrations.whatsapp import whatsapp
            sid = whatsapp.send_message(message)

            # Store report in database
            await self._store_report(report)

            result = {
                "report_generated": True,
                "sent": sid is not None,
                "total_views": report["overview"]["total_views"],
                "posts_count": report["overview"]["posts_count"],
            }
            self.log_complete(result)
            return result

        except Exception as e:
            self.log_error(e)
            return {"error": str(e)}

    async def generate_weekly_report(self) -> Dict[str, Any]:
        """Generate comprehensive weekly report."""
        this_week = await self._get_week_data(weeks_ago=0)
        last_week = await self._get_week_data(weeks_ago=1)

        report = {
            "week_start": this_week["start_date"],
            "week_end": this_week["end_date"],
            "overview": self._calculate_overview(this_week, last_week),
            "top_post": self._find_top_post(this_week),
            "worst_post": self._find_worst_post(this_week),
            "what_worked": await self._analyze_what_worked(this_week),
            "what_didnt": await self._analyze_what_didnt(this_week),
            "consistency": self._calculate_consistency(this_week),
            "recommendations": await self._generate_recommendations(this_week, last_week),
            "trend_analysis": await self._analyze_trends(),
        }

        return report

    async def _get_week_data(self, weeks_ago: int = 0) -> Dict[str, Any]:
        """Get all data for a specific week."""
        session = db.get_session()
        try:
            # Calculate week boundaries
            today = datetime.utcnow().date()
            # Find last Friday
            days_since_friday = (today.weekday() - 4) % 7
            week_end = today - timedelta(days=days_since_friday + (weeks_ago * 7))
            week_start = week_end - timedelta(days=6)

            # Convert to datetime
            start_dt = datetime.combine(week_start, datetime.min.time())
            end_dt = datetime.combine(week_end, datetime.max.time())

            # Get posts from this week
            posts = session.query(Post).filter(
                Post.posted_at >= start_dt,
                Post.posted_at <= end_dt
            ).all()

            # Track which days had posts
            posted_days = [False] * 7  # Sun, Mon, Tue, Wed, Thu, Fri, Sat
            for post in posts:
                if post.posted_at:
                    day_index = post.posted_at.weekday()
                    # Convert Python weekday (Mon=0) to our format (Sun=0)
                    adjusted = (day_index + 1) % 7
                    posted_days[adjusted] = True

            return {
                "start_date": week_start,
                "end_date": week_end,
                "posts": posts,
                "posted_days": posted_days,
            }

        finally:
            session.close()

    def _calculate_overview(self, this_week: Dict, last_week: Dict) -> Dict[str, Any]:
        """Calculate main metrics and comparison."""
        posts = this_week["posts"]

        total_views = sum(p.views or 0 for p in posts)
        total_likes = sum(p.likes or 0 for p in posts)
        total_comments = sum(p.comments or 0 for p in posts)
        posts_count = len(posts)

        last_week_views = sum(p.views or 0 for p in last_week["posts"])
        last_week_posts = len(last_week["posts"])

        views_change = 0
        if last_week_views > 0:
            views_change = ((total_views - last_week_views) / last_week_views) * 100

        return {
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "posts_count": posts_count,
            "views_change_percent": views_change,
            "avg_views_per_post": total_views / posts_count if posts_count > 0 else 0,
            "last_week_views": last_week_views,
            "last_week_posts": last_week_posts,
        }

    def _find_top_post(self, week_data: Dict) -> Optional[Dict]:
        """Find best performing post of the week."""
        posts = week_data["posts"]
        if not posts:
            return None

        top = max(posts, key=lambda p: p.views or 0)
        return {
            "id": top.id,
            "caption": top.caption,
            "platform": top.platform,
            "views": top.views or 0,
            "likes": top.likes or 0,
            "comments": top.comments or 0,
        }

    def _find_worst_post(self, week_data: Dict) -> Optional[Dict]:
        """Find worst performing post of the week."""
        posts = week_data["posts"]
        if not posts:
            return None

        worst = min(posts, key=lambda p: p.views or 0)
        return {
            "id": worst.id,
            "caption": worst.caption,
            "views": worst.views or 0,
        }

    async def _analyze_what_worked(self, week_data: Dict) -> List[str]:
        """Analyze patterns in successful posts."""
        session = db.get_session()
        try:
            # Get overall average
            all_posts = session.query(Post).all()
            avg_views = sum(p.views or 0 for p in all_posts) / len(all_posts) if all_posts else 1

            # Get successful posts from this week
            successful = [p for p in week_data["posts"] if (p.views or 0) > avg_views]

            insights = []

            if not successful:
                return ["אין מספיק נתונים השבוע"]

            # Analyze posting times
            times = {}
            for post in successful:
                if post.posted_at:
                    hour = post.posted_at.hour
                    time_slot = f"{hour}:00-{hour+1}:00"
                    times[time_slot] = times.get(time_slot, 0) + 1

            if times:
                best_time = max(times, key=times.get)
                insights.append(f"זמן העלאה מוצלח: {best_time}")

            # Analyze categories
            categories = {}
            for post in successful:
                cat = post.category or "אחר"
                categories[cat] = categories.get(cat, 0) + 1

            if categories:
                best_cat = max(categories, key=categories.get)
                insights.append(f"קטגוריה מצליחה: {best_cat}")

            # Check girlfriend content
            girlfriend_posts = [
                p for p in successful
                if config.creator.girlfriend_name and
                config.creator.girlfriend_name.lower() in (p.caption or "").lower()
            ]
            if len(girlfriend_posts) > len(successful) * 0.5:
                insights.append(f"תוכן עם {config.creator.girlfriend_name} - ביצועים גבוהים")

            # Analyze formats
            video_count = sum(1 for p in successful if p.media_type == "video")
            if video_count == len(successful):
                insights.append("סרטונים עובדים הכי טוב")

            return insights[:4]  # Max 4 insights

        finally:
            session.close()

    async def _analyze_what_didnt(self, week_data: Dict) -> List[str]:
        """Analyze patterns in underperforming posts."""
        session = db.get_session()
        try:
            all_posts = session.query(Post).all()
            avg_views = sum(p.views or 0 for p in all_posts) / len(all_posts) if all_posts else 1

            weak_posts = [p for p in week_data["posts"] if (p.views or 0) < avg_views * 0.7]

            insights = []
            for post in weak_posts[:2]:
                reason = self._guess_failure_reason(post)
                caption_preview = (post.caption or "")[:30]
                if len(post.caption or "") > 30:
                    caption_preview += "..."
                insights.append(f"'{caption_preview}' - {reason}")

            return insights

        finally:
            session.close()

    def _guess_failure_reason(self, post: Post) -> str:
        """Guess why a post underperformed."""
        reasons = []

        # Check posting time
        if post.posted_at:
            hour = post.posted_at.hour
            if hour < 10 or hour > 23:
                reasons.append("זמן העלאה לא אופטימלי")

        # Check caption length
        caption_len = len(post.caption or "")
        if caption_len < 20:
            reasons.append("כיתוב קצר מדי")
        elif caption_len > 500:
            reasons.append("כיתוב ארוך מדי")

        # Check hashtags
        hashtags = post.hashtags or []
        if len(hashtags) < 3:
            reasons.append("מעט האשטגים")

        if not reasons:
            reasons.append("אולי לא הזמן הנכון לנושא הזה")

        return reasons[0]

    def _calculate_consistency(self, week_data: Dict) -> Dict[str, Any]:
        """Calculate posting consistency."""
        posted_days = week_data["posted_days"]
        posts_count = sum(posted_days)

        # Generate visual
        days_hebrew = ['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש']
        visual = ""
        for i, day in enumerate(days_hebrew):
            if posted_days[i]:
                visual += "✅"
            else:
                visual += "❌"

        # Generate message
        if posts_count >= 5:
            message = f"🔥 מדהים! {posts_count} ימים עם תוכן!"
            score = "excellent"
        elif posts_count >= 3:
            message = f"👍 טוב! {posts_count} ימים עם תוכן"
            score = "good"
        else:
            message = f"💪 {posts_count} ימים - אפשר יותר!"
            score = "needs_improvement"

        return {
            "posted_days_count": posts_count,
            "posted_days": posted_days,
            "visual": visual,
            "message": message,
            "score": score,
        }

    async def _generate_recommendations(self, this_week: Dict, last_week: Dict) -> List[str]:
        """Generate AI-powered recommendations for next week."""
        if not self.client:
            return [
                "המשך עם התוכן שעבד הכי טוב",
                "נסה להעלות בזמנים אופטימליים",
                "הוסף עוד האשטגים רלוונטיים"
            ]

        overview = self._calculate_overview(this_week, last_week)
        what_worked = await self._analyze_what_worked(this_week)
        what_didnt = await self._analyze_what_didnt(this_week)

        prompt = f"""Based on this week's content performance:

צפיות כולל: {overview['total_views']:,}
שינוי מהשבוע שעבר: {overview['views_change_percent']:.1f}%
מספר פוסטים: {overview['posts_count']}

מה עבד: {', '.join(what_worked)}
מה פחות עבד: {', '.join(what_didnt)}

צור 3 המלצות ספציפיות לשבוע הבא בעברית.
כל המלצה בשורה נפרדת, ללא מספור.
היה ספציפי ומעשי."""

        try:
            response = self.client.messages.create(
                model=config.ai.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.content[0].text
            recs = [line.strip() for line in text.split('\n') if line.strip()]
            return recs[:3]

        except Exception as e:
            logger.error(f"Error generating recommendations: {e}")
            return [
                "המשך עם התוכן שעבד הכי טוב",
                "נסה להעלות בזמנים אופטימליים"
            ]

    async def _analyze_trends(self) -> str:
        """Analyze trends over last 4 weeks."""
        session = db.get_session()
        try:
            views_by_week = []

            for weeks_ago in range(4):
                week_data = await self._get_week_data(weeks_ago)
                total_views = sum(p.views or 0 for p in week_data["posts"])
                views_by_week.append(total_views)

            # Analyze trend
            if len(views_by_week) >= 3:
                if views_by_week[0] > views_by_week[1] > views_by_week[2]:
                    return "📈 אתה במגמת עלייה! 3 שבועות של שיפור"
                elif views_by_week[0] < views_by_week[1] < views_by_week[2]:
                    return "📉 שים לב - מגמת ירידה. בוא נשנה משהו!"
                else:
                    return "📊 ביצועים יציבים"

            return "📊 עוד לא מספיק נתונים למגמה"

        finally:
            session.close()

    def _format_report_message(self, report: Dict) -> str:
        """Format report as WhatsApp message."""
        overview = report["overview"]
        top_post = report["top_post"]
        consistency = report["consistency"]

        views_arrow = "⬆️" if overview["views_change_percent"] > 0 else "⬇️"
        views_change = abs(overview["views_change_percent"])

        # Format what worked
        worked_text = "\n".join(f"✅ {w}" for w in report["what_worked"][:3])

        # Format what didn't
        didnt_text = "\n".join(f"• {d}" for d in report["what_didnt"][:2])

        # Format recommendations
        recs_text = "\n".join(f"{i+1}. {r}" for i, r in enumerate(report["recommendations"][:3]))

        # Top post section
        top_post_text = ""
        if top_post:
            caption_preview = (top_post["caption"] or "")[:40]
            if len(top_post["caption"] or "") > 40:
                caption_preview += "..."
            top_post_text = f"""
🏆 *הפוסט המוצלח:*
'{caption_preview}'
👁️ {top_post['views']:,} צפיות | ❤️ {top_post['likes']:,} לייקים"""

        message = f"""📊 *הסיכום השבועי שלך!*

📈 *סטטיסטיקות:*
- צפיות: {overview['total_views']:,} ({views_arrow} {views_change:.0f}% מהשבוע שעבר)
- לייקים: {overview['total_likes']:,}
- תגובות: {overview['total_comments']:,}
- סרטונים שהעלית: {overview['posts_count']}
{top_post_text}

📈 *מה עבד הכי טוב:*
{worked_text}

📉 *מה פחות עבד:*
{didnt_text if didnt_text else "הכל עבד טוב! 🎉"}

💡 *המלצות לשבוע הבא:*
{recs_text}

📅 *עקביות:*
{consistency['visual']}
{consistency['message']}

{report['trend_analysis']}

---
יאללה שבוע מעולה! 🚀
שלח "השוואה" לראות השוואה לחודש שעבר"""

        return message

    async def _store_report(self, report: Dict):
        """Store report in database."""
        session = db.get_session()
        try:
            top_post_id = report["top_post"]["id"] if report["top_post"] else None

            stored_report = WeeklyReportModel(
                week_start=report["week_start"],
                week_end=report["week_end"],
                total_views=report["overview"]["total_views"],
                total_likes=report["overview"]["total_likes"],
                total_comments=report["overview"]["total_comments"],
                posts_count=report["overview"]["posts_count"],
                best_post_id=top_post_id,
                report_json=report,
            )
            session.add(stored_report)
            session.commit()

        finally:
            session.close()

    async def generate_comparison(self, weeks: int = 4) -> str:
        """Generate comparison to previous weeks."""
        weeks_data = []
        for i in range(weeks):
            data = await self._get_week_data(weeks_ago=i)
            total_views = sum(p.views or 0 for p in data["posts"])
            total_posts = len(data["posts"])
            weeks_data.append({
                "week": i,
                "views": total_views,
                "posts": total_posts,
                "start": data["start_date"],
            })

        message = "📊 *השוואה לשבועות אחרונים:*\n\n"

        for i, week in enumerate(weeks_data):
            if i == 0:
                label = "השבוע"
            elif i == 1:
                label = "שבוע שעבר"
            else:
                label = f"לפני {i} שבועות"

            message += f"*{label}:*\n"
            message += f"👁️ {week['views']:,} צפיות | 📹 {week['posts']} פוסטים\n\n"

        # Add trend
        if len(weeks_data) >= 2:
            change = weeks_data[0]["views"] - weeks_data[1]["views"]
            if change > 0:
                message += f"📈 עלייה של {change:,} צפיות מהשבוע שעבר!"
            elif change < 0:
                message += f"📉 ירידה של {abs(change):,} צפיות מהשבוע שעבר"
            else:
                message += "📊 יציב"

        return message
