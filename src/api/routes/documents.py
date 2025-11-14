"""
Documents routes - upload, list, delete documents
"""

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
import logging

from src.api.models import DocumentUploadResponse, DocumentListResponse
from src.api.auth_utils import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a document (PDF, DOCX, TXT, MD)
    Processes and stores in ChromaDB
    """
    # TODO: Implement document upload
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Document upload coming soon"
    )


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """
    List all documents for the organization
    """
    # TODO: Implement document listing
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Document listing coming soon"
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a document (soft delete)
    """
    # TODO: Implement document deletion
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Document deletion coming soon"
    )
