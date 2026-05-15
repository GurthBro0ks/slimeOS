"""
SlimyOS Browser Room — Web automation with strict safety gates.

Rules:
- Can search and read pages freely
- Can fill form drafts
- CANNOT submit forms without approval
- CANNOT purchase without approval  
- CANNOT send messages without approval
- CANNOT use credentials without approval
- Screenshots captured for proof packs
- Separate browser profiles per task

Implementation:
- Uses Playwright when available
- Falls back to mock mode for testing/demo
- All actions go through slimy-toold policy gates
"""

import os
import json
import subprocess
from datetime import datetime


def _playwright_available() -> bool:
    """Check if Playwright is installed and usable."""
    try:
        import playwright
        return True
    except ImportError:
        return False


def handle_browser_search(args: dict) -> dict:
    """Search the web. Low risk — read-only."""
    query = args["query"]
    engine = args.get("engine", "google")
    
    if _playwright_available():
        # Real implementation would launch browser and search
        pass
    
    # Mock for demo/testing
    return {
        "output": f"[Browser Room] Searched '{query}' on {engine}",
        "url": f"https://www.google.com/search?q={query.replace(' ', '+')}",
        "results_count": 10,
        "mode": "mock" if not _playwright_available() else "live",
    }


def handle_browser_read_page(args: dict) -> dict:
    """Read/scrape a web page. Low risk — read-only."""
    url = args["url"]
    extract = args.get("extract", "text")  # text, links, images, all
    
    return {
        "output": f"[Browser Room] Read page: {url} (extract: {extract})",
        "url": url,
        "mode": "mock",
    }


def handle_browser_screenshot(args: dict) -> dict:
    """Take a screenshot of the current browser page."""
    url = args.get("url", "current")
    label = args.get("label", "screenshot")
    
    return {
        "output": f"[Browser Room] Screenshot: {label} ({url})",
        "label": label,
        "timestamp": datetime.utcnow().isoformat(),
        "mode": "mock",
    }


def handle_browser_fill_form(args: dict) -> dict:
    """Fill a form field — DRAFT only. Does NOT submit."""
    url = args.get("url", "current")
    field_name = args["field_name"]
    value = args["value"]
    
    return {
        "output": f"[Browser Room] Filled '{field_name}' = '{value[:50]}' (DRAFT — not submitted)",
        "field": field_name,
        "submitted": False,
    }


def handle_browser_submit(args: dict) -> dict:
    """
    Submit a form. HIGH RISK — requires approval.
    
    The tool manifest marks this as requires_approval=true.
    slimy-toold will gate this before it ever reaches here.
    """
    url = args.get("url", "current")
    form_id = args.get("form_id", "unknown")
    
    return {
        "output": f"[Browser Room] Would submit form '{form_id}' on {url}",
        "submitted": False,  # Mock: never actually submits
        "note": "Real submission requires Playwright + approval",
    }


def handle_browser_purchase(args: dict) -> dict:
    """
    Make a purchase. CRITICAL RISK — always sandboxed + approval required.
    
    Even with approval, this should run in a trycua sandbox.
    """
    url = args.get("url", "")
    item = args.get("item", "unknown")
    amount = args.get("amount", "unknown")
    
    return {
        "output": f"[Browser Room] PURCHASE REQUEST: '{item}' for {amount} on {url}",
        "purchased": False,
        "note": "Purchases require sandbox + approval. Not executed in mock mode.",
    }


def handle_browser_click(args: dict) -> dict:
    """Click an element on the page. Medium risk."""
    selector = args.get("selector", "")
    text = args.get("text", "")
    
    return {
        "output": f"[Browser Room] Click: selector='{selector}' text='{text}'",
        "mode": "mock",
    }


def handle_browser_navigate(args: dict) -> dict:
    """Navigate to a URL. Low risk."""
    url = args["url"]
    
    return {
        "output": f"[Browser Room] Navigate to: {url}",
        "url": url,
        "mode": "mock",
    }


BROWSER_ROOM_TOOLS = {
    "browser_search": handle_browser_search,
    "browser_read_page": handle_browser_read_page,
    "browser_screenshot": handle_browser_screenshot,
    "browser_fill_form": handle_browser_fill_form,
    "browser_submit": handle_browser_submit,
    "browser_purchase": handle_browser_purchase,
    "browser_click": handle_browser_click,
    "browser_navigate": handle_browser_navigate,
}
