"""
Slack Slash Commands - Handle /ask command for Q&A in Slack
Users can type /ask <question> in any Slack channel
SIMPLE SINGLE-WORKSPACE VERSION
"""

import logging
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from src.services.qa_service import QAService

logger = logging.getLogger(__name__)

# Single workspace configuration
WORKSPACE_ID = "W_DEFAULT"
BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

# Initialize app in single-workspace mode (no installation store)
app = App(token=BOT_TOKEN)


@app.command("/ask")
def handle_ask_command(ack, command, say, client):
    """
    Handle /ask slash command
    Usage: /ask What hackathon projects are being discussed?
    """
    ack()  # Acknowledge immediately

    user_id = command['user_id']
    channel_id = command['channel_id']
    question = command['text'].strip()

    if not question:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="❓ Please provide a question.\n\nUsage: `/ask What are people discussing about AI?`"
        )
        return

    logger.info(f"📩 Question from {user_id}: {question}")

    # Send thinking message
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"🤔 Searching for: _{question}_\n\nThis may take a few seconds..."
    )

    try:
        # Get answer
        qa_service = QAService(workspace_id=WORKSPACE_ID)
        result = qa_service.answer_question(
            question=question,
            n_context_messages=10
        )

        # Format response
        answer_text = f"*Question:* {question}\n\n"
        answer_text += f"*Answer:*\n{result['answer']}\n\n"

        # Add sources
        if result.get('sources'):
            answer_text += "*Top Sources:*\n"
            for i, source in enumerate(result['sources'][:3], 1):
                channel = source.get('metadata', {}).get('channel_name', 'unknown')
                user = source.get('metadata', {}).get('user_name', 'unknown')
                text_preview = source['text'][:80] + "..." if len(source['text']) > 80 else source['text']
                answer_text += f"{i}. #{channel} - {user}: _{text_preview}_\n"

        answer_text += f"\n_Confidence: {result.get('confidence', 'medium')} | {len(result.get('sources', []))} sources_"

        # Send answer
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=answer_text
        )

        logger.info(f"✅ Answered question from {user_id}")

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"❌ Sorry, I encountered an error:\n```{str(e)}```\n\nPlease try again."
        )


@app.command("/askall")
def handle_askall_command(ack, command, client):
    """
    Handle /askall slash command (posts answer to channel)
    Usage: /askall What are people discussing?
    """
    ack()

    user_id = command['user_id']
    channel_id = command['channel_id']
    question = command['text'].strip()

    if not question:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="❓ Please provide a question.\n\nUsage: `/askall What are people discussing?`"
        )
        return

    # Post thinking message to channel
    thinking_msg = client.chat_postMessage(
        channel=channel_id,
        text=f"<@{user_id}> asked: _{question}_\n🤔 Searching..."
    )

    try:
        # Get answer
        qa_service = QAService(workspace_id=WORKSPACE_ID)
        result = qa_service.answer_question(question=question, n_context_messages=10)

        # Format answer
        answer_text = f"<@{user_id}> asked: *{question}*\n\n"
        answer_text += f"*Answer:*\n{result['answer']}\n\n"
        answer_text += f"_💡 Based on {len(result.get('sources', []))} messages | Confidence: {result.get('confidence', 'medium')}_"

        # Update message with answer
        client.chat_update(
            channel=channel_id,
            ts=thinking_msg['ts'],
            text=answer_text
        )

        logger.info(f"✅ Answered public question from {user_id}")

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        client.chat_update(
            channel=channel_id,
            ts=thinking_msg['ts'],
            text=f"❌ Sorry, I encountered an error: {str(e)}"
        )


@app.event("app_mention")
def handle_mention(event, say):
    """Handle @bot mentions"""
    user_id = event['user']
    text = event['text']

    # Remove bot mention
    import re
    question = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

    if not question or question.lower() in ['hi', 'hello', 'hey']:
        say(
            text=f"Hi <@{user_id}>! 👋\n\nAsk me questions about your Slack workspace!\n\n*Examples:*\n• What hackathon projects are being discussed?\n• Who is working on AI?\n• What are the main topics this week?",
            thread_ts=event.get('thread_ts', event['ts'])
        )
        return

    try:
        qa_service = QAService(workspace_id=WORKSPACE_ID)
        result = qa_service.answer_question(question=question, n_context_messages=10)

        say(
            text=f"*Q:* {question}\n\n*A:* {result['answer']}\n\n_Based on {len(result.get('sources', []))} messages_",
            thread_ts=event.get('thread_ts', event['ts'])
        )
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        say(
            text=f"Sorry <@{user_id}>, I encountered an error: {str(e)}",
            thread_ts=event.get('thread_ts', event['ts'])
        )


def start_command_handler():
    """Start the Slack command handler with Socket Mode"""
    logger.info("🚀 Starting Slack command handler (single workspace mode)...")

    if not APP_TOKEN:
        logger.error("❌ SLACK_APP_TOKEN not set!")
        logger.error("   Please enable Socket Mode and add SLACK_APP_TOKEN to .env")
        return

    if not BOT_TOKEN:
        logger.error("❌ SLACK_BOT_TOKEN not set!")
        return

    logger.info(f"✅ Bot token: {BOT_TOKEN[:20]}...")
    logger.info(f"✅ App token: {APP_TOKEN[:20]}...")
    logger.info(f"✅ Workspace: {WORKSPACE_ID}")

    handler = SocketModeHandler(app, APP_TOKEN)

    logger.info("✅ Ready! You can now use /ask in Slack")
    handler.start()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    start_command_handler()
