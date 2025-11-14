"""
Q&A routes - ask questions against Slack + documents
"""

from fastapi import APIRouter, HTTPException, status, Depends
from psycopg2 import extras
import logging
import time

from src.api.models import QARequest, QAResponse, QASource
from src.api.auth_utils import get_current_user
from src.services.qa_service import QAService
from src.db.connection import DatabaseConnection

router = APIRouter()
logger = logging.getLogger(__name__)


def get_workspace_ids_for_org(org_id: int) -> list:
    """Get all workspace IDs connected to an organization"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT workspace_id
                FROM org_workspaces
                WHERE org_id = %s
                """,
                (org_id,)
            )
            workspaces = cur.fetchall()
            return [ws['workspace_id'] for ws in workspaces]
    finally:
        DatabaseConnection.return_connection(conn)


@router.post("/ask", response_model=QAResponse)
async def ask_question(
    request: QARequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Ask a question - searches Slack messages and documents
    Uses RAG with Claude for answer generation
    """
    start_time = time.time()

    try:
        # Get workspaces for this organization
        workspace_ids = get_workspace_ids_for_org(current_user['org_id'])

        if not workspace_ids and request.include_slack:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Slack workspaces connected. Please connect a workspace first."
            )

        # Determine which workspace to query
        if request.workspace_id:
            # Verify user has access to this workspace
            if request.workspace_id not in workspace_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have access to this workspace"
                )
            workspace_id = request.workspace_id
        else:
            # Use first workspace (or could search all)
            workspace_id = workspace_ids[0] if workspace_ids else None

        # Initialize Q&A service
        if not workspace_id and request.include_slack:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No workspace specified and no workspaces connected"
            )

        qa_service = QAService(workspace_id=workspace_id)

        # Ask question
        result = qa_service.answer_question(
            question=request.question,
            n_context_messages=request.max_sources
        )

        # Format sources
        sources = []
        for msg in result.get('sources', []):
            sources.append(QASource(
                source_type='slack_message',
                text=msg.get('text', ''),
                metadata={
                    'channel_name': msg.get('metadata', {}).get('channel_name'),
                    'user_name': msg.get('metadata', {}).get('user_name'),
                    'timestamp': msg.get('metadata', {}).get('timestamp'),
                    'workspace_id': workspace_id
                },
                relevance_score=msg.get('distance')  # ChromaDB distance score
            ))

        # Calculate processing time
        processing_time = (time.time() - start_time) * 1000  # Convert to ms

        # Log usage for billing/analytics
        _log_query_usage(current_user['org_id'], workspace_id, request.question)

        return QAResponse(
            answer=result['answer'],
            confidence=result.get('confidence', 'medium'),
            sources=sources,
            question=request.question,
            processing_time_ms=processing_time
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Q&A error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process question: {str(e)}"
        )


def _log_query_usage(org_id: int, workspace_id: str, question: str):
    """Log query for usage tracking and analytics"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
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

            # Log query in audit logs
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, action, resource_type, resource_id, details)
                VALUES (%s, 'qa_query', 'workspace', %s, %s)
                """,
                (org_id, workspace_id, extras.Json({'question_length': len(question)}))
            )

            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to log usage: {e}")
        conn.rollback()
    finally:
        DatabaseConnection.return_connection(conn)


@router.get("/history")
async def get_query_history(
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """
    Get recent Q&A query history for the organization
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    action,
                    resource_type,
                    resource_id as workspace_id,
                    details,
                    created_at
                FROM audit_logs
                WHERE org_id = %s AND action = 'qa_query'
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (current_user['org_id'], limit)
            )
            history = cur.fetchall()

            return {
                "queries": history,
                "total": len(history)
            }
    finally:
        DatabaseConnection.return_connection(conn)


@router.get("/stats")
async def get_qa_stats(current_user: dict = Depends(get_current_user)):
    """
    Get Q&A usage statistics for the organization
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Get queries this month
            cur.execute(
                """
                SELECT COALESCE(SUM(count), 0) as total_queries
                FROM usage_metrics
                WHERE org_id = %s
                  AND metric_type = 'queries'
                  AND period_start >= DATE_TRUNC('month', CURRENT_DATE)
                """,
                (current_user['org_id'],)
            )
            stats = cur.fetchone()

            # Get queries today
            cur.execute(
                """
                SELECT COALESCE(SUM(count), 0) as queries_today
                FROM usage_metrics
                WHERE org_id = %s
                  AND metric_type = 'queries'
                  AND period_start = CURRENT_DATE
                """,
                (current_user['org_id'],)
            )
            today_stats = cur.fetchone()

            return {
                "total_queries_this_month": stats['total_queries'],
                "queries_today": today_stats['queries_today'],
                "org_id": current_user['org_id']
            }
    finally:
        DatabaseConnection.return_connection(conn)
