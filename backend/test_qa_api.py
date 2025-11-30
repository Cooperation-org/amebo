#!/usr/bin/env python3
"""
Test script for Q&A API with main server
"""
import requests
import time
import json

def test_qa_api():
    """Test the Q&A API endpoint"""
    base_url = "http://localhost:8000"
    
    # Wait for server to be ready
    print("Waiting for server to be ready...")
    for i in range(10):
        try:
            response = requests.get(f"{base_url}/health", timeout=2)
            if response.status_code == 200:
                print("✅ Server is ready!")
                break
        except:
            pass
        time.sleep(1)
    else:
        print("❌ Server not ready after 10 seconds")
        return
    
    # Test Q&A endpoint
    print("\nTesting Q&A API...")
    
    test_questions = [
        "What is the weather like today?",
        "Hello, how are you?",
        "Can you help me with my project?",
        "What are the latest updates?"
    ]
    
    for question in test_questions:
        try:
            response = requests.post(
                f"{base_url}/api/qa/ask",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer test-token"
                },
                json={
                    "question": question,
                    "workspace_id": "test-workspace"
                },
                timeout=5
            )
            
            print(f"\n📝 Question: {question}")
            print(f"📊 Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"💬 Answer: {data.get('answer', 'No answer')}")
                print(f"🎯 Confidence: {data.get('confidence', 'N/A')}")
            else:
                print(f"❌ Error: {response.text}")
                
        except Exception as e:
            print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_qa_api()