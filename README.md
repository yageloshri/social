# Content Master Agent 🎬

A sophisticated, self-improving AI agent that helps content creators grow their social media presence with personalized, actionable recommendations.

## Features

- **Smart Content Analysis** - Analyzes your past content to understand what works
- **AI-Powered Ideas** - Generates specific, actionable content ideas (never vague!)
- **Trend Monitoring** - Tracks Israeli news and entertainment for timely content opportunities
- **WhatsApp Reminders** - Sends personalized messages at optimal times throughout the day
- **Self-Improving** - Learns from your preferences and performance over time

## Architecture

```
ContentMasterAgent (Orchestrator)
├── ProfileScanner      - Scrapes Instagram & TikTok
├── DeepAnalyzer        - AI-powered content analysis
├── TrendRadar          - RSS feed monitoring
├── IdeaEngine          - Content idea generation
├── MessageCrafter      - WhatsApp message composition
├── MemoryCore          - Persistent memory & context
└── FeedbackLearner     - Learning from outcomes
```

## Tech Stack

- **AI**: Claude API (Anthropic) - Best quality AI
- **Messaging**: Twilio WhatsApp
- **Scraping**: Instaloader (Instagram), Apify (TikTok)
- **Database**: SQLite with SQLAlchemy
- **Scheduling**: APScheduler

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/yageloshri/social.git
cd social
pip install -r requirements.txt
```

### 2. Configure

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required credentials:
- `ANTHROPIC_API_KEY` - Get from [Anthropic Console](https://console.anthropic.com)
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` - Get from [Twilio Console](https://www.twilio.com/console)
- `TWILIO_WHATSAPP_NUMBER` - Your Twilio WhatsApp sandbox number
- `MY_WHATSAPP_NUMBER` - Your personal WhatsApp number
- `APIFY_TOKEN` - Get from [Apify](https://apify.com)
- `INSTAGRAM_HANDLE` / `TIKTOK_HANDLE` - Your social media handles

### 3. Run

```bash
# Test mode - verify everything works
python main.py --test

# Generate ideas now
python main.py --generate

# Check trends
python main.py --trends

# Run full agent with scheduler
python main.py
```

## Daily Schedule (Israel Time)

| Time | Action |
|------|--------|
| 06:00 | Morning routine (scan, analyze, generate ideas) |
| 09:00 | Send morning motivation message |
| 12:00 | Quick update (check for breaking trends) |
| 13:00 | Send midday message (if urgent trends) |
| 17:00 | Send afternoon reminder |
| 18:00 | Quick update |
| 21:00 | Send evening summary |
| 00:00 | Quick update |

## Message Examples

### Morning Message (Good)
```
☀️ בוקר טוב!

💡 הרעיון להיום: צלם את [שם] כשהיא מגלה הפתעה קטנה שהכנת לה.

פתיחה: "הבעת הפנים של [שם] כש..."

🔥 טרנד: כולם מדברים על הפרק אתמול של הישרדות - יש פה הזדמנות!

⏰ הזמן הכי טוב להעלות: 18:00-20:00

יאללה יום מעולה! 🎬
```

### Bad (Never Generated)
```
בוקר טוב! אל תשכח להעלות תוכן היום 😊
```
*Too vague - no actionable information!*

## Project Structure

```
├── agent/
│   ├── __init__.py
│   ├── config.py           # Configuration management
│   ├── database.py         # Database models
│   ├── core_agent.py       # Main orchestrator
│   ├── scheduler.py        # Task scheduling
│   ├── skills/
│   │   ├── profile_scanner.py
│   │   ├── deep_analyzer.py
│   │   ├── trend_radar.py
│   │   ├── idea_engine.py
│   │   ├── message_crafter.py
│   │   ├── memory_core.py
│   │   └── feedback_learner.py
│   └── integrations/
│       └── whatsapp.py
├── data/                   # Database files (gitignored)
├── logs/                   # Log files (gitignored)
├── main.py                 # Entry point
├── requirements.txt
├── .env.example
└── .gitignore
```

## Commands

```bash
# Production mode (with scheduler)
python main.py

# Test mode
python main.py --test

# Run morning routine now
python main.py --morning

# Generate ideas
python main.py --generate

# Check trends
python main.py --trends

# Show status
python main.py --status
```

## Learning System

The agent improves over time by:

1. **Tracking idea usage** - Detects when you post content similar to suggested ideas
2. **Analyzing performance** - Compares predicted vs actual engagement
3. **Adjusting patterns** - Updates success pattern weights based on outcomes
4. **Learning preferences** - Notes which types of ideas you use vs skip

After a few weeks, recommendations become highly personalized.

## Security

- `.env` file is gitignored - never committed
- API keys are loaded from environment variables
- Database is stored locally in `data/` directory

## Deployment

For 24/7 operation, deploy to a server:

```bash
# Using screen
screen -S agent
python main.py
# Ctrl+A, D to detach

# Or using systemd (create service file)
sudo systemctl start content-agent
```

## Contributing

This is a personal project, but feel free to fork and adapt for your needs!

## License

MIT
