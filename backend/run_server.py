#!/usr/bin/env python3
"""
Minimal FastAPI server for Q&A functionality
"""

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Response, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Slack Helper Q&A API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class LoginRequest(BaseModel):
    email: str
    password: str

class QARequest(BaseModel):
    question: str
    workspace_id: Optional[str] = None
    include_documents: bool = True
    include_slack: bool = True
    max_sources: int = 10

class QAResponse(BaseModel):
    answer: str
    confidence: int
    confidence_explanation: Optional[str] = None
    project_links: list = []
    sources: list = []
    question: str
    processing_time_ms: Optional[float] = None

# Mock auth
def get_current_user():
    return {
        "user_id": 1,
        "org_id": 8,
        "email": "orjienekenechukwu@gmail.com"
    }

# Routes
@app.post("/api/auth/login")
async def login(request: LoginRequest):
    if request.email == "orjienekenechukwu@gmail.com" and request.password == "Lekan2904.":
        return {
            "access_token": "mock-jwt-token-" + str(hash(request.email)),
            "token_type": "bearer",
            "user": {
                "user_id": 1,
                "email": request.email,
                "org_id": 8,
                "org_name": "WhatsCookin Team",
                "role": "admin"
            }
        }
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/auth/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": 1,
        "email": "orjienekenechukwu@gmail.com",
        "org_id": 8,
        "org_name": "WhatsCookin Team",
        "role": "admin"
    }

@app.post("/api/qa/ask", response_model=QAResponse)
async def ask_question(request: QARequest, current_user: dict = Depends(get_current_user)):
    """Ask a question and get AI response"""
    
    question_lower = request.question.lower()
    
    # Generate response based on question content
    if any(word in question_lower for word in ['weather', 'temperature', 'rain', 'sunny']):
        answer = "I don't have access to real-time weather data. To get weather information, you'd need to connect a weather API or check a weather service."
        confidence = 60
    elif any(word in question_lower for word in ['hello', 'hi', 'hey', 'greetings']):
        answer = "Hello! I'm your AI assistant. I can help answer questions about your team's Slack conversations once you connect a workspace."
        confidence = 95
    elif any(word in question_lower for word in ['help', 'what can you do', 'capabilities']):
        answer = "I can help you search through your team's Slack messages, find relevant conversations, and answer questions based on your team's knowledge. Connect a workspace to get started!"
        confidence = 90
    elif any(word in question_lower for word in ['project', 'code', 'development', 'bug', 'feature']):
        answer = "I can help you find discussions about projects, code reviews, bug reports, and feature requests from your team's Slack conversations. Connect your workspace to search through your team's development discussions."
        confidence = 75
    else:
        answer = f"I understand you're asking about '{request.question}'. Once you connect a Slack workspace, I'll be able to search through your team's conversations to provide more specific and relevant answers."
        confidence = 70
        
    return QAResponse(
        answer=answer,
        confidence=confidence,
        confidence_explanation=f'Demo response with {confidence}% confidence based on question keywords.',
        sources=[],
        project_links=[],
        question=request.question,
        processing_time_ms=50.0
    )

@app.get("/api/workspaces")
@app.get("/api/workspaces/")
async def get_workspaces(current_user: dict = Depends(get_current_user)):
    return {
        "workspaces": [
            {
                "workspace_id": "W_DEFAULT",
                "team_name": "WhatsCookinTeam",
                "team_domain": None,
                "icon_url": None,
                "is_active": True,
                "installed_at": None,
                "last_active": None,
                "status": "active",
                "message_count": 0,
                "channel_count": 0,
                "last_sync_at": None
            }
        ],
        "total": 1
    }

@app.get("/api/documents")
@app.get("/api/documents/")
async def get_documents(current_user: dict = Depends(get_current_user)):
    return {
        "documents": [],
        "total": 0,
        "page": 1,
        "page_size": 20
    }

@app.post("/api/documents/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
    workspace_id: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """Mock document upload endpoint"""
    results = []
    for file in files:
        content = await file.read()
        results.append({
            'filename': file.filename,
            'status': 'indexed',
            'document_id': f'doc_{hash(file.filename)}',
            'chunk_count': len(content) // 1000 + 1
        })
    
    return {
        "success": True,
        "uploaded_count": len(files),
        "failed_count": 0,
        "results": results
    }

@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str, current_user: dict = Depends(get_current_user)):
    """Mock document delete endpoint"""
    return {"success": True, "message": "Document deleted"}

@app.options("/{path:path}")
async def options_handler(path: str):
    return Response(status_code=200)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "slack-helper-qa"}

if __name__ == "__main__":
    print("🚀 Starting Slack Helper Q&A API...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")