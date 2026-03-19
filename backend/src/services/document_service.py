"""
Document Processing Service
Handles file upload, text extraction, and ChromaDB indexing
"""

import logging
import os
import tempfile
from typing import List, Dict, Any, Optional
from pathlib import Path
import hashlib

from src.db.chromadb_client import ChromaDBClient
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

class DocumentService:
    """Service for processing and indexing documents"""
    
    def __init__(self):
        self.chromadb = ChromaDBClient()
        self.supported_types = {
            'text/plain': self._extract_text,
            'text/markdown': self._extract_text,
            'application/pdf': self._extract_pdf,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': self._extract_docx,
        }
    
    async def process_documents(
        self, 
        files: List[Dict[str, Any]], 
        org_id: int, 
        user_id: int,
        workspace_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Process multiple documents and store in database"""
        results = []
        
        for file_data in files:
            try:
                result = await self._process_single_document(
                    file_data, org_id, user_id, workspace_id
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing {file_data.get('filename', 'unknown')}: {e}")
                results.append({
                    'filename': file_data.get('filename', 'unknown'),
                    'status': 'failed',
                    'error': str(e)
                })
        
        return results
    
    async def _process_single_document(
        self, 
        file_data: Dict[str, Any], 
        org_id: int, 
        user_id: int,
        workspace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process a single document"""
        filename = file_data['filename']
        content_type = file_data['content_type']
        file_content = file_data['content']
        
        # Extract text content
        if content_type not in self.supported_types:
            raise ValueError(f"Unsupported file type: {content_type}")
        
        text_content = await self.supported_types[content_type](file_content)
        
        if not text_content or len(text_content.strip()) < 10:
            raise ValueError("No meaningful text content found")
        
        # Create chunks
        chunks = self._create_chunks(text_content)
        
        # Store in database
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()

        try:
            # Insert document record
            cursor.execute("""
                INSERT INTO documents (org_id, workspace_id, title, file_name, file_type,
                                     file_size_bytes, chunk_count, uploaded_by, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING document_id, created_at
            """, (
                org_id, workspace_id, filename, filename, content_type,
                len(file_content), len(chunks), user_id, True
            ))

            document_id, created_at = cursor.fetchone()

            # Store in ChromaDB BEFORE committing to DB
            try:
                await self._store_in_chromadb(
                    document_id, chunks, filename, workspace_id, org_id
                )
            except Exception as e:
                logger.error(f"ChromaDB indexing failed for {filename}: {e}")
                conn.rollback()
                raise ValueError(f"Failed to index document in search engine: {e}")

            # Only commit DB after ChromaDB succeeds
            conn.commit()

            return {
                'document_id': document_id,
                'filename': filename,
                'status': 'indexed',
                'chunk_count': len(chunks),
                'created_at': created_at
            }

        except ValueError:
            raise
        except Exception as e:
            conn.rollback()
            raise
        finally:
            cursor.close()
            DatabaseConnection.return_connection(conn)
    
    async def _extract_text(self, content: bytes) -> str:
        """Extract text from plain text files"""
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            return content.decode('latin-1')
    
    async def _extract_pdf(self, content: bytes) -> str:
        """Extract text from PDF files"""
        try:
            import PyPDF2
            import io
            
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        except ImportError:
            raise ValueError("PyPDF2 not installed - PDF processing unavailable")
        except Exception as e:
            raise ValueError(f"Failed to extract PDF text: {e}")
    
    async def _extract_docx(self, content: bytes) -> str:
        """Extract text from DOCX files"""
        try:
            import docx
            import io
            
            doc = docx.Document(io.BytesIO(content))
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text
        except ImportError:
            raise ValueError("python-docx not installed - DOCX processing unavailable")
        except Exception as e:
            raise ValueError(f"Failed to extract DOCX text: {e}")
    
    def _create_chunks(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """Split text into overlapping chunks"""
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence endings
                for i in range(end, max(start + chunk_size // 2, end - 100), -1):
                    if text[i] in '.!?':
                        end = i + 1
                        break
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            start = end - overlap
            if start >= len(text):
                break
        
        return chunks
    
    async def _store_in_chromadb(
        self, 
        document_id: int, 
        chunks: List[str], 
        filename: str,
        workspace_id: Optional[str],
        org_id: int
    ):
        """Store document chunks in ChromaDB"""
        collection_name = workspace_id if workspace_id else f"org_{org_id}"
        collection = self.chromadb.get_or_create_collection(collection_name)
        
        # Prepare data for ChromaDB
        ids = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"doc_{document_id}_chunk_{i}"
            metadata = {
                'document_id': str(document_id),
                'filename': filename,
                'chunk_index': i,
                'chunk_count': len(chunks),
                'source_type': 'document',
                'workspace_id': workspace_id or '',
                'org_id': str(org_id)
            }
            
            ids.append(chunk_id)
            metadatas.append(metadata)
        
        # Store in ChromaDB
        try:
            collection.upsert(
                documents=chunks,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"Stored {len(chunks)} chunks for document {document_id} in ChromaDB")
        except Exception as e:
            logger.error(f"ChromaDB upsert failed for document {document_id}: {e}")
            raise