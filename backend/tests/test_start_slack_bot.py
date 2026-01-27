#!/usr/bin/env python3
"""
Start Slack Bot for registered workspaces
"""

import asyncio
import logging
from src.services.slack_bot_service import start_slack_bot_for_workspace
from src.db.connection import DatabaseConnection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_all_workspace_bots():
    """Start Slack bots for all registered workspaces"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Get all active workspaces with credentials
        cursor.execute("""
            SELECT DISTINCT w.workspace_id, w.team_name
            FROM workspaces w
            JOIN installations i ON w.workspace_id = i.workspace_id
            WHERE w.is_active = true
        """)
        
        workspaces = cursor.fetchall()
        
        if not workspaces:
            logger.info("No active workspaces found")
            return
        
        logger.info(f"Starting Slack bots for {len(workspaces)} workspaces...")
        
        # Start bots for each workspace
        bot_services = []
        for workspace_id, team_name in workspaces:
            logger.info(f"Starting bot for {team_name} ({workspace_id})")
            bot_service = await start_slack_bot_for_workspace(workspace_id)
            if bot_service:
                bot_services.append(bot_service)
        
        logger.info(f"Successfully started {len(bot_services)} Slack bots")
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down Slack bots...")
            for bot_service in bot_services:
                await bot_service.stop()
        
    except Exception as e:
        logger.error(f"Error starting Slack bots: {e}")
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)

if __name__ == "__main__":
    print("🤖 Starting Slack Helper Bots...")
    asyncio.run(start_all_workspace_bots())