#!/usr/bin/env python3
"""
Quick test script to check if MCP server is working using fastmcp.
Run with: python3 scripts/test_smithery_mcp.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import Client

load_dotenv()


async def test_mcp_server():
    """Test MCP server connectivity using fastmcp."""
    
    server_url = os.getenv("BRAVE_MCP_SERVER_URL")
    if not server_url:
        print("❌ BRAVE_MCP_SERVER_URL not set in .env")
        return False
    
    print(f"Testing MCP server...")
    print(f"URL: {server_url[:70]}...")
    print()
    
    try:
        print("→ Step 1: Creating Client with fastmcp...")
        client = Client(server_url)
        print("✓ Client created")
        print()
        
        print("→ Step 2: Connecting and initializing...")
        try:
            async with client:
                print("✓ Connected and initialized!")
                print()
                
                print("→ Step 3: Pinging server...")
                await asyncio.wait_for(client.ping(), timeout=10.0)
                print("✓ Server is reachable")
                print()
                
                print("→ Step 4: Listing tools...")
                tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
                print(f"✓ Got {len(tools)} tools:")
                for tool in tools:
                    print(f"  - {tool.name}: {tool.description[:60] if tool.description else 'No description'}...")
                print()
                
                print("✅ SUCCESS! MCP server is working!")
                return True
                
        except asyncio.TimeoutError:
            print("❌ TIMEOUT after 10 seconds")
            print("   Server is not responding")
            print()
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        print(f"   Type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        print()
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("MCP SERVER TEST (using fastmcp)")
    print("=" * 70)
    print()
    
    success = asyncio.run(test_mcp_server())
    
    print("=" * 70)
    if success:
        print("Result: ✅ SERVER IS WORKING")
        sys.exit(0)
    else:
        print("Result: ❌ SERVER IS NOT WORKING")
        sys.exit(1)
