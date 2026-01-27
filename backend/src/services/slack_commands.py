"""
Slack Slash Commands - Simple version using Socket Mode Client directly
No Bolt framework - just raw SDK
"""

import logging
import os
import asyncio
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from src.services.qa_service import QAService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

# Get workspace ID dynamically from bot token
def get_workspace_id():
    """Get workspace ID from bot token"""
    try:
        if not BOT_TOKEN:
            return None
        from slack_sdk import WebClient
        client = WebClient(token=BOT_TOKEN)
        response = client.auth_test()
        return response['team_id']
    except Exception as e:
        logger.error(f"Failed to get workspace ID: {e}")
        return None

WORKSPACE_ID = get_workspace_id()


async def process_slash_command(client: SocketModeClient, req: SocketModeRequest):
    """Process slash command requests"""
    if req.type == "slash_commands":
        # Acknowledge the request immediately
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        try:
            # Get command details
            command = req.payload["command"]
            text = req.payload.get("text", "").strip()
            user_id = req.payload["user_id"]
            channel_id = req.payload["channel_id"]

            logger.info(f"Command: {command} from {user_id}: {text}")

            # Create web client for posting messages
            web_client = AsyncWebClient(token=BOT_TOKEN)

            if command == "/ask":
                await handle_ask(web_client, user_id, channel_id, text, private=True)
            elif command == "/askall":
                await handle_ask(web_client, user_id, channel_id, text, private=False)

        except Exception as e:
            logger.error(f"Error processing slash command: {e}", exc_info=True)
            try:
                web_client = AsyncWebClient(token=BOT_TOKEN)
                await web_client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"Sorry, an error occurred: {str(e)}"
                )
            except:
                pass


async def handle_ask(web_client, user_id, channel_id, question, private=True):
    """Handle /ask command"""

    if not question:
        await web_client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="❓ Please provide a question.\n\nUsage: `/ask What are people discussing?`"
        )
        return

    # Send thinking message
    if private:
        await web_client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"🤔 Searching for: _{question}_\n\nThis may take a few seconds..."
        )
    else:
        thinking_msg = await web_client.chat_postMessage(
            channel=channel_id,
            text=f"<@{user_id}> asked: _{question}_\n🤔 Searching..."
        )

    try:
        # Check workspace ID
        workspace_id = WORKSPACE_ID
        if not workspace_id:
            workspace_id = get_workspace_id()
            if not workspace_id:
                raise Exception("Failed to get workspace ID")

        # Get answer from Q&A service
        qa_service = QAService(workspace_id=workspace_id)
        result = qa_service.answer_question(
            question=question,
            n_context_messages=10
        )

        # Format answer - QA service now returns fully formatted response
        if private:
            answer_text = f"*Question:* {question}\n\n"
        else:
            answer_text = f"<@{user_id}> asked: *{question}*\n\n"

        # Answer is already formatted with Style A (includes "What I found:" section)
        answer_text += result['answer']

        # Add short confidence indicator
        confidence = result.get('confidence', 50)
        answer_text += f"\n\n_CF: {confidence}%_"

        # Send answer
        if private:
            await web_client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=answer_text
            )
        else:
            await web_client.chat_update(
                channel=channel_id,
                ts=thinking_msg['ts'],
                text=answer_text
            )

        logger.info(f"Answered question from {user_id}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

        error_text = f"Sorry, I encountered an error:\n```{str(e)}```"

        if private:
            await web_client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=error_text
            )
        else:
            await web_client.chat_update(
                channel=channel_id,
                ts=thinking_msg['ts'],
                text=error_text
            )


async def process_events(client: SocketModeClient, req: SocketModeRequest):
    """Process event requests (app mentions)"""
    if req.type == "events_api":
        # Acknowledge
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        event = req.payload["event"]

        if event["type"] == "app_mention":
            user_id = event["user"]
            text = event["text"]
            channel_id = event["channel"]
            thread_ts = event.get("thread_ts", event["ts"])

            # Remove bot mention
            import re
            question = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

            web_client = AsyncWebClient(token=BOT_TOKEN)

            if not question or question.lower() in ['hi', 'hello', 'hey']:
                await web_client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"Hi <@{user_id}>! 👋\n\nAsk me questions!\n\n*Examples:*\n• What hackathon projects are discussed?\n• Who is working on AI?\n• What are the main topics?"
                )
                return

            try:
                qa_service = QAService(workspace_id=WORKSPACE_ID)
                result = qa_service.answer_question(question=question, n_context_messages=10)

                # Answer is already formatted with Style A
                response_text = f"*Q:* {question}\n\n{result['answer']}"

                # Add confidence
                confidence = result.get('confidence', 50)
                response_text += f"\n\n_CF: {confidence}%_"

                await web_client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=response_text
                )
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
                await web_client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"Sorry, error: {str(e)}"
                )


async def handle_app_mention(team_id, channel, text, user, ts):
    """
    Handle app mention from Event Subscriptions API
    This is called when the bot is mentioned via HTTP Events API (not Socket Mode)
    """
    try:
        # Remove bot mention from text
        import re
        question = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

        # Create web client
        web_client = AsyncWebClient(token=BOT_TOKEN)

        # Handle greetings
        if not question or question.lower() in ['hi', 'hello', 'hey']:
            await web_client.chat_postMessage(
                channel=channel,
                thread_ts=ts,
                text=f"Hi <@{user}>!\n\nAsk me questions!\n\n*Examples:*\n• What projects are being worked on?\n• Who is working on AI?\n• What are the main topics?"
            )
            return

        # Get answer from Q&A service
        qa_service = QAService(workspace_id=team_id)
        result = qa_service.answer_question(question=question, n_context_messages=10)

        # Answer is already formatted with Style A
        response_text = f"*Q:* {question}\n\n{result['answer']}"

        # Add confidence
        confidence = result.get('confidence', 50)
        response_text += f"\n\n_CF: {confidence}%_"

        # Send response in thread
        await web_client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=response_text
        )

        logger.info(f"Answered app mention from {user} in {channel}")

    except Exception as e:
        logger.error(f"Error handling app mention: {e}", exc_info=True)
        try:
            web_client = AsyncWebClient(token=BOT_TOKEN)
            await web_client.chat_postMessage(
                channel=channel,
                thread_ts=ts,
                text=f"Sorry, I encountered an error: {str(e)}"
            )
        except:
            pass


async def main():
    """Main function to start Socket Mode client"""

    if not BOT_TOKEN:
        logger.error("SLACK_BOT_TOKEN not set!")
        return

    if not APP_TOKEN:
        logger.error("SLACK_APP_TOKEN not set!")
        return

    logger.info("Starting Slack command handler...")
    logger.info(f"Bot token: {BOT_TOKEN[:20]}...")
    logger.info(f"App token: {APP_TOKEN[:20]}...")
    logger.info(f"Workspace: {WORKSPACE_ID}")

    # Create Socket Mode client
    client = SocketModeClient(
        app_token=APP_TOKEN,
        web_client=AsyncWebClient(token=BOT_TOKEN)
    )

    # Register handlers
    client.socket_mode_request_listeners.append(process_slash_command)
    client.socket_mode_request_listeners.append(process_events)

    logger.info("Ready! You can now use /ask in Slack")

    # Start client
    await client.connect()
    await asyncio.Event().wait()  # Keep running


if __name__ == "__main__":
    asyncio.run(main())
