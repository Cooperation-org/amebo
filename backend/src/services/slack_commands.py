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
from slack_sdk.errors import SlackApiError

from src.services.qa_service import QAService
from src.db.connection import DatabaseConnection
from psycopg2 import extras

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_org_and_instance(workspace_id: str):
    """Map a Slack workspace (team_id) to its (org_id, instance_slug).

    The conversation loop needs both: org_id so gated actions (e.g. creating a
    Taiga task) have a team identity to attribute the draft to, and the instance
    slug so the model is offered that instance's allowed_tools. Returns
    (None, None) if the workspace isn't connected to an org yet.
    """
    org_id = None
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT org_id FROM org_workspaces WHERE workspace_id = %s LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()
            if row:
                org_id = row[0]
    finally:
        DatabaseConnection.return_connection(conn)

    instance_slug = None
    if org_id is not None:
        from src.db.repositories.instance_repo import InstanceRepo
        inst = InstanceRepo().get_by_org(org_id)
        if inst:
            instance_slug = inst["slug"]
    return org_id, instance_slug


def _log_slack_query_usage(workspace_id: str, question: str):
    """Log Slack query for usage tracking and analytics"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            # Look up org_id from workspace
            cur.execute(
                "SELECT org_id FROM org_workspaces WHERE workspace_id = %s LIMIT 1",
                (workspace_id,)
            )
            row = cur.fetchone()
            if not row:
                logger.warning(f"No org found for workspace {workspace_id}, skipping usage log")
                return
            org_id = row[0]

            # Update usage metrics
            cur.execute(
                """
                INSERT INTO usage_metrics (org_id, metric_type, count, period_start, period_end)
                VALUES (%s, 'queries', 1, CURRENT_DATE, CURRENT_DATE + INTERVAL '1 day')
                ON CONFLICT (org_id, metric_type, period_start)
                DO UPDATE SET count = usage_metrics.count + 1
                """,
                (org_id,)
            )

            # Log in audit logs
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, action, resource_type, resource_id, details)
                VALUES (%s, 'qa_query', 'workspace', %s, %s)
                """,
                (org_id, workspace_id, extras.Json({
                    'question_length': len(question),
                    'source': 'slack'
                }))
            )

            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to log Slack query usage: {e}")
        conn.rollback()
    finally:
        DatabaseConnection.return_connection(conn)

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

        # Format answer
        if private:
            answer_text = f"*Question:* {question}\n\n"
        else:
            answer_text = f"<@{user_id}> asked: *{question}*\n\n"

        answer_text += result['answer']

        # Add compact source attribution for Slack context
        sources = result.get('sources', [])
        if sources:
            # Show up to 3 sources as a compact footer
            source_parts = []
            for s in sources[:3]:
                ch = s.get('channel', '')
                usr = s.get('user', '')
                if ch and usr:
                    source_parts.append(f"#{ch} ({usr})")
                elif ch:
                    source_parts.append(f"#{ch}")
            if source_parts:
                answer_text += f"\n\n_Sources: {' · '.join(source_parts)}_"

        # Add confidence
        confidence = result.get('confidence', 50)
        answer_text += f"\n_Confidence: {confidence}%_"

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

        # Log usage for analytics
        _log_slack_query_usage(workspace_id, question)

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
                result = qa_service.answer_question(
                    question=question,
                    n_context_messages=10,
                    thread_ref=thread_ts,
                    source_type="slack",
                    author_info=f"slack:{user_id}"
                )

                response_text = f"*Q:* {question}\n\n{result['answer']}"

                # Compact source footer
                sources = result.get('sources', [])
                if sources:
                    source_parts = [f"#{s.get('channel','')}" for s in sources[:3] if s.get('channel')]
                    if source_parts:
                        response_text += f"\n\n_Sources: {' · '.join(source_parts)}_"

                confidence = result.get('confidence', 50)
                response_text += f"\n_Confidence: {confidence}%_"

                await web_client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=response_text
                )

                # Log usage for analytics
                _log_slack_query_usage(WORKSPACE_ID, question)
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

        # Get answer from Q&A service (with thread context for conversation memory).
        # Resolve org + instance so the loop can use this team's tools and
        # attribute gated actions (e.g. creating a Taiga task) to the org.
        org_id, instance_slug = _resolve_org_and_instance(team_id)
        qa_service = QAService(workspace_id=team_id, org_id=org_id)
        result = qa_service.answer_question(
            question=question,
            n_context_messages=10,
            thread_ref=ts,
            source_type="slack",
            author_info=f"slack:{user}",
            instance_slug=instance_slug,
        )

        response_text = f"*Q:* {question}\n\n{result['answer']}"

        # Compact source footer
        sources = result.get('sources', [])
        if sources:
            source_parts = [f"#{s.get('channel','')}" for s in sources[:3] if s.get('channel')]
            if source_parts:
                response_text += f"\n\n_Sources: {' · '.join(source_parts)}_"

        confidence = result.get('confidence', 50)
        response_text += f"\n_Confidence: {confidence}% | rearchitect v2_"

        # Send response in thread
        await web_client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=response_text
        )

        # Log usage for analytics
        _log_slack_query_usage(team_id, question)

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


async def is_thread_parent_our_bot(
    channel: str,
    thread_ts: str,
    bot_user_id: str,
) -> bool:
    """
    True iff the parent message of the given thread was posted by our
    bot. Used by the message-event handler to decide whether a thread
    reply is implicitly directed at amebo.

    One Slack API call per thread-reply event. Cheap; if we ever feel
    pressure, swap for an in-memory LRU populated by slack_post.
    """
    if not thread_ts or not channel:
        return False
    try:
        web_client = AsyncWebClient(token=BOT_TOKEN)
        resp = await web_client.conversations_history(
            channel=channel,
            latest=thread_ts,
            limit=1,
            inclusive=True,
        )
        messages = resp.get("messages", [])
        if not messages:
            return False
        parent = messages[0]
        # Bots post with `bot_id`; the message may also include `user` set
        # to the bot's user id. Either match counts.
        if parent.get("user") == bot_user_id:
            return True
        return False
    except SlackApiError as exc:
        logger.warning(
            "Could not fetch thread parent for channel=%s thread_ts=%s: %s",
            channel, thread_ts, exc,
        )
        return False
    except Exception:
        logger.exception("Unexpected error checking thread parent")
        return False


async def handle_thread_reply(team_id, channel, text, user, ts, thread_ts):
    """
    Handle a user's reply in a thread that amebo started. Reuses the
    QAService thread-context path so amebo answers WITH conversation
    memory of the prior turns in that thread.

    Different from handle_app_mention in two small ways:
      1. There's no @-mention to strip — the text is used as-is.
      2. We reply in the same thread (thread_ts is the original message,
         not the reply).
    """
    try:
        question = (text or "").strip()
        if not question:
            return

        web_client = AsyncWebClient(token=BOT_TOKEN)

        org_id, instance_slug = _resolve_org_and_instance(team_id)
        qa_service = QAService(workspace_id=team_id, org_id=org_id)
        result = qa_service.answer_question(
            question=question,
            n_context_messages=10,
            thread_ref=thread_ts,
            source_type="slack",
            author_info=f"slack:{user}",
            instance_slug=instance_slug,
        )

        response_text = result.get("answer", "(no response)")

        sources = result.get("sources", [])
        if sources:
            source_parts = [f"#{s.get('channel','')}" for s in sources[:3] if s.get('channel')]
            if source_parts:
                response_text += f"\n\n_Sources: {' · '.join(source_parts)}_"

        confidence = result.get('confidence', 50)
        response_text += f"\n_Confidence: {confidence}%_"

        await web_client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=response_text,
        )

        _log_slack_query_usage(team_id, question)
        logger.info(
            "Answered thread reply from %s in %s thread_ts=%s",
            user, channel, thread_ts,
        )

    except Exception as exc:
        logger.error(f"Error handling thread reply: {exc}", exc_info=True)
        try:
            web_client = AsyncWebClient(token=BOT_TOKEN)
            await web_client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Sorry, I encountered an error: {exc}",
            )
        except Exception:
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
