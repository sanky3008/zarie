#!/usr/bin/env python3
"""
Script to analyze a single user's usage pattern.
Useful for testing before running full analysis.

Usage:
    python scripts/analyze_single_user.py <user_id>
"""

import os
import sys
import json
import asyncio

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

# Import from main analysis script
from scripts.analyze_user_patterns import UserPatternAnalyzer

async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_single_user.py <user_id>")
        print("\nTo find user IDs, run: python scripts/list_users.py")
        sys.exit(1)

    user_id = sys.argv[1]

    print("="*80)
    print(f"Analyzing single user: {user_id}")
    print("="*80)

    analyzer = UserPatternAnalyzer()

    # Analyze single user
    result = await analyzer.analyze_user_pattern(user_id)

    if not result:
        print("\nNo analysis generated.")
        sys.exit(1)

    # Print result
    print("\n" + "="*80)
    print("ANALYSIS RESULT")
    print("="*80)

    if "error" in result:
        print(f"\nError: {result['error']}")
    else:
        print(f"\nUser ID: {result['user_id']}")
        print(f"Message Count: {result['message_count']}")
        print(f"Timestamp: {result['timestamp']}")
        print("\n" + "-"*80)
        print("Analysis Results:")
        print("-"*80)

        # Parse and display structured output
        analysis = result.get('analysis', '')
        for line in analysis.split('\n'):
            line = line.strip()
            if line and (line.startswith('PRIMARY_PATTERN:') or
                        line.startswith('CONFIDENCE:') or
                        line.startswith('PERCENTAGE:') or
                        line.startswith('KEY_EXAMPLES:') or
                        line.startswith('REASONING:')):
                print(line)

        print("\n" + "-"*80)
        print("Full Analysis:")
        print("-"*80)
        print(result['analysis'])

    print("\n" + "="*80)

    # Save single result
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "analysis_output")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, f"single_user_analysis_{user_id}.json")
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\nResult saved to: {output_file}")
    print("="*80)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user.")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
