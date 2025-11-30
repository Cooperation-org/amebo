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

WORKSPACE_ID = "W_DEFAULT"
BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
APP_TOKEN = os.getenv("SLACK_APP_TOKEN")


async def process_slash_command(client: SocketModeClient, req: SocketModeRequest):
    """Process slash command requests"""
    if req.type == "slash_commands":
        # Acknowledge the request immediately
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        # Get command details
        command = req.payload["command"]
        text = req.payload.get("text", "").strip()
        user_id = req.payload["user_id"]
        channel_id = req.payload["channel_id"]

        logger.info(f"📩 Command: {command} from {user_id}: {text}")

        # Create web client for posting messages
        web_client = AsyncWebClient(token=BOT_TOKEN)

        if command == "/ask":
            await handle_ask(web_client, user_id, channel_id, text, private=True)
        elif command == "/askall":
            await handle_ask(web_client, user_id, channel_id, text, private=False)


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
        # Get answer from Q&A service
        qa_service = QAService(workspace_id=WORKSPACE_ID)
        result = qa_service.answer_question(
            question=question,
            n_context_messages=10
        )

        # Format answer
        if private:
            answer_text = f"*Question:* {question}\n\n"
        else:
            answer_text = f"<@{user_id}> asked: *{question}*\n\n"

        answer_text += f"*Answer:*\n{result['answer']}\n\n"

        # Add confidence with percentage
        confidence = result.get('confidence', 50)
        confidence_exp = result.get('confidence_explanation', 'No explanation')

        # Add confidence bar emoji based on percentage
        if confidence >= 80:
            conf_emoji = "🟢"
        elif confidence >= 60:
            conf_emoji = "🟡"
        elif confidence >= 40:
            conf_emoji = "🟠"
        else:
            conf_emoji = "🔴"

        answer_text += f"{conf_emoji} *Confidence:* {confidence}% - _{confidence_exp}_\n\n"

        # Add project links if found
        project_links = result.get('project_links', [])
        if project_links:
            answer_text += "🔗 *Related Links:*\n"
            for link in project_links[:5]:
                if link['type'] == 'github':
                    answer_text += f"• 📂 GitHub: <{link['url']}>\n"
                else:
                    answer_text += f"• 📄 Docs: <{link['url']}>\n"
            answer_text += "\n"

        # Add sources (top 5)
        if result.get('sources') and private:
            answer_text += "📚 *Sources:*\n"
            for source in result['sources'][:5]:
                ref_num = source.get('reference_number', '?')
                ch = source.get('channel', 'unknown')
                usr = source.get('user', 'unknown')
                txt = source['text'][:70] + "..." if len(source['text']) > 70 else source['text']
                answer_text += f"[{ref_num}] #{ch} - {usr}: _{txt}_\n"
            answer_text += "\n"

        answer_text += f"_Based on {result.get('context_used', 0)} messages_"

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

        logger.info(f"✅ Answered question from {user_id}")

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)

        error_text = f"❌ Sorry, I encountered an error:\n```{str(e)}```"

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

                # Format response
                response_text = f"*Q:* {question}\n\n*A:* {result['answer']}\n\n"

                confidence = result.get('confidence', 50)
                confidence_exp = result.get('confidence_explanation', '')

                # Confidence emoji
                if confidence >= 80:
                    conf_emoji = "🟢"
                elif confidence >= 60:
                    conf_emoji = "🟡"
                elif confidence >= 40:
                    conf_emoji = "🟠"
                else:
                    conf_emoji = "🔴"

                response_text += f"{conf_emoji} {confidence}% - _{confidence_exp}_\n"

                # Add project links if found
                project_links = result.get('project_links', [])
                if project_links:
                    response_text += "\n🔗 *Links:*\n"
                    for link in project_links[:3]:
                        if link['type'] == 'github':
                            response_text += f"• 📂 <{link['url']}>\n"
                        else:
                            response_text += f"• 📄 <{link['url']}>\n"

                response_text += f"\n_Based on {result.get('context_used', 0)} messages_"

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


async def main():
    """Main function to start Socket Mode client"""

    if not BOT_TOKEN:
        logger.error("❌ SLACK_BOT_TOKEN not set!")
        return

    if not APP_TOKEN:
        logger.error("❌ SLACK_APP_TOKEN not set!")
        return

    logger.info("🚀 Starting Slack command handler...")
    logger.info(f"✅ Bot token: {BOT_TOKEN[:20]}...")
    logger.info(f"✅ App token: {APP_TOKEN[:20]}...")
    logger.info(f"✅ Workspace: {WORKSPACE_ID}")

    # Create Socket Mode client
    client = SocketModeClient(
        app_token=APP_TOKEN,
        web_client=AsyncWebClient(token=BOT_TOKEN)
    )

    # Register handlers
    client.socket_mode_request_listeners.append(process_slash_command)
    client.socket_mode_request_listeners.append(process_events)

    logger.info("✅ Ready! You can now use /ask in Slack")

    # Start client
    await client.connect()
    await asyncio.Event().wait()  # Keep running


if __name__ == "__main__":
    asyncio.run(main())
