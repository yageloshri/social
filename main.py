#!/usr/bin/env python3
"""
Content Master Agent
====================
A sophisticated, self-improving content management agent for social media creators.

Usage:
    python main.py                    # Run with scheduler (production)
    python main.py --test             # Test mode (send test message)
    python main.py --morning          # Run morning routine now
    python main.py --generate         # Generate ideas now
    python main.py --trends           # Check trends now
    python main.py --status           # Show agent status
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent.config import config
from agent.core_agent import agent
from agent.scheduler import scheduler
from agent.database import db

# Rich console for beautiful output
console = Console()


def setup_logging():
    """Configure logging with rich handler."""
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


def validate_config():
    """Validate configuration and show status."""
    errors = config.validate()

    if errors:
        console.print(Panel(
            "\n".join([f"[red]✗[/red] {e}" for e in errors]),
            title="[red]Configuration Errors[/red]",
            border_style="red",
        ))
        console.print("\n[yellow]Please check your .env file and add missing values.[/yellow]")
        console.print("See .env.example for required variables.\n")
        return False

    console.print(Panel(
        "[green]✓[/green] All configuration validated",
        title="[green]Configuration OK[/green]",
        border_style="green",
    ))
    return True


async def run_test():
    """Run test mode - send a test message."""
    console.print("[bold]Running test mode...[/bold]\n")

    # Initialize
    await agent.initialize()

    # Generate one idea
    console.print("Generating test idea...")
    ideas = await agent.generate_ideas(count=1)

    if ideas:
        idea = ideas[0]
        console.print(Panel(
            f"[bold]{idea.get('title', 'Untitled')}[/bold]\n\n"
            f"[yellow]Hook:[/yellow] {idea.get('hook', 'N/A')}\n\n"
            f"[yellow]Description:[/yellow] {idea.get('description', 'N/A')}\n\n"
            f"[yellow]Category:[/yellow] {idea.get('category', 'N/A')}\n"
            f"[yellow]Predicted:[/yellow] {idea.get('predicted_performance', 'N/A')}",
            title="Generated Idea",
            border_style="green",
        ))

    # Send test message
    console.print("\nSending test message via WhatsApp...")
    from agent.integrations.whatsapp import whatsapp

    test_message = """🧪 Test Message from Content Master Agent

If you're seeing this, everything is working!

✓ AI connected
✓ WhatsApp connected
✓ Database initialized

Ready to help you create amazing content! 🎬"""

    sid = whatsapp.send_message(test_message)

    if sid:
        console.print(f"[green]✓ Test message sent! SID: {sid}[/green]")
    else:
        console.print("[red]✗ Failed to send test message[/red]")


async def run_morning():
    """Run morning routine now."""
    console.print("[bold]Running morning routine...[/bold]\n")

    await agent.initialize()
    result = await agent.morning_routine()

    # Display results
    table = Table(title="Morning Routine Results")
    table.add_column("Component", style="cyan")
    table.add_column("Result", style="green")

    table.add_row("Scan", result.get("scan", {}).get("summary", "N/A"))
    table.add_row("Analysis", result.get("analysis", {}).get("summary", "N/A") if result.get("analysis") else "Skipped")
    table.add_row("Trends", result.get("trends", {}).get("summary", "N/A"))
    table.add_row("Ideas", result.get("ideas", {}).get("summary", "N/A"))
    table.add_row("Learning", result.get("learning", {}).get("summary", "N/A"))

    console.print(table)

    # Send morning message
    console.print("\n[bold]Sending morning message...[/bold]")
    msg_result = await agent.send_morning_message()
    console.print(f"Message sent: {msg_result.get('sent')}")


async def run_generate():
    """Generate ideas now."""
    console.print("[bold]Generating content ideas...[/bold]\n")

    await agent.initialize()
    ideas = await agent.generate_ideas(count=5)

    for i, idea in enumerate(ideas, 1):
        console.print(Panel(
            f"[bold]{idea.get('title', 'Untitled')}[/bold]\n\n"
            f"[yellow]Hook:[/yellow] {idea.get('hook', 'N/A')}\n\n"
            f"[yellow]Description:[/yellow] {idea.get('description', 'N/A')}\n\n"
            f"[dim]Steps:[/dim]\n" + "\n".join([f"  • {s}" for s in idea.get('steps', [])]) + "\n\n"
            f"[yellow]Best time:[/yellow] {idea.get('best_time', 'N/A')} | "
            f"[yellow]Category:[/yellow] {idea.get('category', 'N/A')} | "
            f"[yellow]Predicted:[/yellow] {idea.get('predicted_performance', 'N/A')}",
            title=f"Idea {i}",
            border_style="green",
        ))


async def run_trends():
    """Check trends now."""
    console.print("[bold]Checking trends...[/bold]\n")

    await agent.initialize()
    trends = await agent.get_current_trends()

    if not trends:
        console.print("[yellow]No relevant trends found.[/yellow]")
        return

    table = Table(title="Current Relevant Trends")
    table.add_column("Title", style="cyan", max_width=40)
    table.add_column("Opportunity", style="green", max_width=40)
    table.add_column("Urgency", style="yellow")
    table.add_column("Score", style="magenta")

    for trend in trends:
        table.add_row(
            trend.get("title", "")[:40],
            (trend.get("opportunity") or "")[:40],
            trend.get("urgency", ""),
            str(trend.get("score", 0)),
        )

    console.print(table)


async def run_status():
    """Show agent status."""
    console.print("[bold]Agent Status[/bold]\n")

    await agent.initialize()
    status = await agent.get_status()

    # General status
    console.print(Panel(
        f"[green]Status:[/green] {status.get('status', 'Unknown')}\n"
        f"[yellow]Last Scan:[/yellow] {status.get('last_scan', 'Never')}\n"
        f"[yellow]Last Analysis:[/yellow] {status.get('last_analysis', 'Never')}\n"
        f"[yellow]Daily Ideas:[/yellow] {status.get('daily_ideas_count', 0)}\n"
        f"[yellow]WhatsApp:[/yellow] {'✓ Configured' if status.get('whatsapp_configured') else '✗ Not configured'}",
        title="General",
        border_style="cyan",
    ))

    # Recent activity
    activity = status.get("recent_activity", {})
    console.print(Panel(
        f"[yellow]Posts (24h):[/yellow] {activity.get('posts', 0)}\n"
        f"[yellow]Ideas Generated:[/yellow] {activity.get('ideas_generated', 0)}\n"
        f"[yellow]Trends Discovered:[/yellow] {activity.get('trends_discovered', 0)}",
        title="Recent Activity (24h)",
        border_style="yellow",
    ))

    # Learning summary
    learning = await agent.get_learning_summary()
    console.print(Panel(
        f"[yellow]Patterns Learned:[/yellow] {learning.get('patterns_learned', 0)}\n"
        f"[yellow]Preferences Learned:[/yellow] {learning.get('preferences_learned', 0)}\n"
        f"[yellow]Idea Acceptance Rate:[/yellow] {learning.get('idea_acceptance_rate', 0):.1f}%\n"
        f"[yellow]Average Rating:[/yellow] {learning.get('average_rating', 0)}/5",
        title="Learning Summary",
        border_style="green",
    ))

    # Scheduled jobs
    jobs = scheduler.get_jobs()
    table = Table(title="Scheduled Jobs")
    table.add_column("Job", style="cyan")
    table.add_column("Next Run", style="green")

    for job in jobs:
        table.add_row(job["name"], job["next_run"] or "Not scheduled")

    console.print(table)


async def run_production():
    """Run in production mode with scheduler."""
    console.print(Panel(
        "[bold green]Content Master Agent[/bold green]\n\n"
        "Starting in production mode...\n"
        "Press Ctrl+C to stop.",
        border_style="green",
    ))

    # Initialize
    await agent.initialize()

    # Start scheduler
    scheduler.start()

    # Show status
    await run_status()

    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
        scheduler.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Content Master Agent - AI-powered content assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                Run with scheduler (production)
  python main.py --test         Send test message
  python main.py --morning      Run morning routine
  python main.py --generate     Generate content ideas
  python main.py --trends       Check current trends
  python main.py --status       Show agent status
        """
    )

    parser.add_argument("--test", action="store_true", help="Run test mode")
    parser.add_argument("--morning", action="store_true", help="Run morning routine")
    parser.add_argument("--generate", action="store_true", help="Generate ideas")
    parser.add_argument("--trends", action="store_true", help="Check trends")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--skip-validation", action="store_true", help="Skip config validation")

    args = parser.parse_args()

    # Setup
    setup_logging()

    console.print(Panel(
        "[bold cyan]Content Master Agent[/bold cyan]\n"
        "[dim]AI-powered content assistant for social media creators[/dim]",
        border_style="cyan",
    ))

    # Validate config (unless skipped)
    if not args.skip_validation and not args.status:
        if not validate_config():
            sys.exit(1)

    # Run appropriate mode
    if args.test:
        asyncio.run(run_test())
    elif args.morning:
        asyncio.run(run_morning())
    elif args.generate:
        asyncio.run(run_generate())
    elif args.trends:
        asyncio.run(run_trends())
    elif args.status:
        asyncio.run(run_status())
    else:
        asyncio.run(run_production())


if __name__ == "__main__":
    main()
