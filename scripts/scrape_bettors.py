#!/usr/bin/env python3
"""
Scrape and organize contacts for active sports betters.
Finds users across Reddit, Discord, Twitter/X, and betting forums with public contact info.

Usage:
  python scripts/scrape_bettors.py --show               # Display current list
  python scripts/scrape_bettors.py --add <data>         # Add new contact
  python scripts/scrape_bettors.py --verify             # Check for duplicates/validity
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

@dataclass
class Bettor:
    """A sports bettor with contact info."""
    name: str                              # Handle or full name
    platform: str                          # reddit, twitter, discord, forum, etc.
    handle: str                            # Username or @handle
    activity_indicator: str                # "active" / "very active" / posts in past 30d / etc.
    contact_method: str                    # "email" / "reddit_dm" / "discord_id" / "twitter_dm" / "website"
    contact_value: str                     # email@example.com or username
    niche: str                             # "F1" / "general sports" / "polymarket" / "kalshi" / etc.
    notes: str = ""                        # relevance notes, engagement level, etc.
    added_date: str = ""
    
    def __post_init__(self):
        if not self.added_date:
            self.added_date = datetime.utcnow().isoformat()

class BettorList:
    """Manage a list of bettor contacts."""
    
    def __init__(self, filepath: Path = None):
        if filepath is None:
            filepath = Path(__file__).parent.parent / "data" / "bettors_contacts.json"
        self.filepath = filepath
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.bettors: List[Bettor] = []
        self.load()
    
    def load(self):
        """Load existing contacts from file."""
        if self.filepath.exists():
            with open(self.filepath) as f:
                data = json.load(f)
                self.bettors = [Bettor(**b) for b in data]
    
    def save(self):
        """Save contacts to file."""
        with open(self.filepath, 'w') as f:
            json.dump([asdict(b) for b in self.bettors], f, indent=2)
    
    def add(self, bettor: Bettor) -> bool:
        """Add a new bettor. Return False if duplicate."""
        # Check for duplicates
        for existing in self.bettors:
            if (existing.platform == bettor.platform and 
                existing.handle.lower() == bettor.handle.lower()):
                print(f"⚠️  Duplicate: {bettor.platform}/@{bettor.handle} already in list")
                return False
        
        self.bettors.append(bettor)
        self.save()
        print(f"✓ Added: {bettor.platform}/@{bettor.handle} ({bettor.contact_method})")
        return True
    
    def show(self, group_by: str = "platform"):
        """Display all contacts."""
        if not self.bettors:
            print("No contacts yet.")
            return
        
        if group_by == "platform":
            by_platform = {}
            for b in self.bettors:
                if b.platform not in by_platform:
                    by_platform[b.platform] = []
                by_platform[b.platform].append(b)
            
            for platform, bettos in sorted(by_platform.items()):
                print(f"\n📱 {platform.upper()} ({len(bettos)})")
                print("-" * 80)
                for b in bettos:
                    print(f"  @{b.handle:20} | {b.contact_method:12} | {b.niche:15} | {b.activity_indicator}")
                    if b.contact_value:
                        print(f"    → {b.contact_value}")
                    if b.notes:
                        print(f"    ℹ️  {b.notes}")
        else:
            for b in self.bettors:
                print(f"{b.platform:10} @{b.handle:20} | {b.contact_method:12} | {b.contact_value}")
        
        print(f"\n{'='*80}")
        print(f"Total: {len(self.bettors)} contacts")
        print(f"Saved to: {self.filepath}")
    
    def summary(self):
        """Print summary stats."""
        by_platform = {}
        by_method = {}
        by_niche = {}
        
        for b in self.bettors:
            by_platform[b.platform] = by_platform.get(b.platform, 0) + 1
            by_method[b.contact_method] = by_method.get(b.contact_method, 0) + 1
            by_niche[b.niche] = by_niche.get(b.niche, 0) + 1
        
        print(f"\n📊 Summary: {len(self.bettors)} contacts")
        print(f"\nBy platform: {dict(sorted(by_platform.items()))}")
        print(f"By contact method: {dict(sorted(by_method.items()))}")
        print(f"By niche: {dict(sorted(by_niche.items()))}")

if __name__ == "__main__":
    bl = BettorList()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--show":
            bl.show()
        elif sys.argv[1] == "--summary":
            bl.summary()
        elif sys.argv[1] == "--example":
            # Add example contacts for testing
            bl.add(Bettor(
                name="example_user",
                platform="reddit",
                handle="example_user",
                activity_indicator="active (posted 3x last 30d)",
                contact_method="email",
                contact_value="user@example.com",
                niche="general sports",
                notes="Active in r/sportsbook, posts analysis"
            ))
            bl.show()
    else:
        bl.summary()
