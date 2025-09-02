#!/usr/bin/env python3
"""
Terminal-based interactive chat with Gemini API and file access
"""

import os
import sys
import json
import mimetypes
import base64
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
import requests
import argparse

class GeminiChat:
    def __init__(self, api_key: str, allowed_dirs: List[str] = None):
        self.api_key = api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.model = "gemini-1.5-flash"  # or gemini-1.5-pro
        self.allowed_dirs = [Path(d).resolve() for d in (allowed_dirs or ["."])]
        self.conversation_history = []
        self.uploaded_files = {}  # Track uploaded files by URI
        
    def is_file_accessible(self, file_path: str) -> bool:
        """Check if file is within allowed directories"""
        try:
            file_path = Path(file_path).resolve()
            return any(
                str(file_path).startswith(str(allowed_dir)) 
                for allowed_dir in self.allowed_dirs
            )
        except Exception:
            return False
    
    def upload_file_to_gemini(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Upload file to Gemini File API"""
        if not self.is_file_accessible(file_path):
            return None
            
        try:
            path = Path(file_path)
            if not path.exists():
                return None
                
            mime_type, _ = mimetypes.guess_type(str(path))
            
            # Check if it's a supported video format
            video_formats = {
                '.mp4': 'video/mp4',
                '.avi': 'video/x-msvideo', 
                '.mov': 'video/quicktime',
                '.mkv': 'video/x-matroska',
                '.webm': 'video/webm',
                '.flv': 'video/x-flv',
                '.wmv': 'video/x-ms-wmv',
                '.m4v': 'video/mp4'
            }
            
            if path.suffix.lower() not in video_formats:
                return None
                
            mime_type = video_formats[path.suffix.lower()]
            
            # Check file size (Gemini has limits)
            file_size = path.stat().st_size
            max_size = 2 * 1024 * 1024 * 1024  # 2GB limit
            if file_size > max_size:
                return {"error": f"File too large: {file_size / (1024*1024*1024):.1f}GB (max 2GB)"}
            
            print(f"📤 Uploading video file ({file_size / (1024*1024):.1f}MB)...")
            
            # Use the resumable upload API
            # Step 1: Start upload session
            upload_url = f"{self.base_url}/files"
            headers = {
                'X-Goog-Upload-Protocol': 'resumable',
                'X-Goog-Upload-Command': 'start',
                'X-Goog-Upload-Header-Content-Length': str(file_size),
                'X-Goog-Upload-Header-Content-Type': mime_type,
                'Content-Type': 'application/json'
            }
            
            metadata = {
                'file': {
                    'display_name': path.name
                }
            }
            
            response = requests.post(
                f"{upload_url}?key={self.api_key}",
                headers=headers,
                json=metadata,
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"Failed to start upload session: {response.status_code}")
                print(f"Response: {response.text}")
                return {"error": f"Upload session failed: {response.status_code}"}
            
            # Get upload URL from response headers
            upload_session_url = response.headers.get('X-Goog-Upload-URL')
            if not upload_session_url:
                return {"error": "No upload URL received"}
            
            # Step 2: Upload the file content
            with open(path, 'rb') as f:
                file_content = f.read()
            
            headers = {
                'Content-Length': str(file_size),
                'X-Goog-Upload-Offset': '0',
                'X-Goog-Upload-Command': 'upload, finalize'
            }
            
            response = requests.post(
                upload_session_url,
                headers=headers,
                data=file_content,
                timeout=300
            )
            
            if response.status_code == 200:
                result = response.json()
                file_uri = result.get('file', {}).get('uri')
                if file_uri:
                    self.uploaded_files[file_path] = {
                        'uri': file_uri,
                        'name': result.get('file', {}).get('name'),
                        'mime_type': mime_type,
                        'size': file_size
                    }
                    
                    # Wait for processing
                    print("⏳ Processing video...")
                    self.wait_for_file_processing(result.get('file', {}).get('name'))
                    
                    return {
                        'uri': file_uri,
                        'mime_type': mime_type
                    }
            
            print(f"Upload failed with status: {response.status_code}")
            print(f"Response: {response.text}")
            return {"error": f"Upload failed: {response.status_code} - {response.text}"}
            
        except Exception as e:
            print(f"Exception during upload: {str(e)}")
            return {"error": f"Error uploading file: {str(e)}"}
    
    def wait_for_file_processing(self, file_name: str, max_wait: int = 300):
        """Wait for file processing to complete"""
        if not file_name:
            return
            
        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                response = requests.get(
                    f"{self.base_url}/files/{file_name}?key={self.api_key}",
                    timeout=10
                )
                
                if response.status_code == 200:
                    result = response.json()
                    state = result.get('state', 'PROCESSING')
                    
                    if state == 'ACTIVE':
                        print("✅ Video processing complete!")
                        return
                    elif state == 'FAILED':
                        print("❌ Video processing failed")
                        return
                        
                time.sleep(2)
                
            except Exception as e:
                print(f"⚠️ Error checking processing status: {e}")
                break
                
        print("⚠️ Processing timeout - continuing anyway")
    
    def delete_uploaded_file(self, file_name: str):
        """Delete uploaded file from Gemini"""
        try:
            response = requests.delete(
                f"{self.base_url}/files/{file_name}?key={self.api_key}",
                timeout=10
            )
            return response.status_code == 204
        except Exception:
            return False
    def read_file_content(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Read file content and return in format suitable for Gemini"""
        if not self.is_file_accessible(file_path):
            return None
            
        try:
            path = Path(file_path)
            if not path.exists():
                return None
                
            mime_type, _ = mimetypes.guess_type(str(path))
            
            # Check if it's a video file
            video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}
            if path.suffix.lower() in video_extensions:
                # Upload video to Gemini
                upload_result = self.upload_file_to_gemini(file_path)
                if upload_result and 'uri' in upload_result:
                    return {
                        "file_data": {
                            "file_uri": upload_result['uri'],
                            "mime_type": upload_result['mime_type']
                        }
                    }
                elif upload_result and 'error' in upload_result:
                    return {"text": f"❌ {upload_result['error']}"}
                else:
                    return {"text": f"❌ Failed to upload video: {file_path}"}
            
            # For text files, read as text
            if mime_type and mime_type.startswith('text/'):
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                return {
                    "text": f"File: {file_path}\n\n{content}"
                }
            
            # For code files without proper mime type
            code_extensions = {'.py', '.js', '.html', '.css', '.java', '.cpp', '.c', 
                             '.h', '.json', '.xml', '.yaml', '.yml', '.md', '.txt',
                             '.sh', '.bat', '.ps1', '.sql', '.r', '.php', '.go',
                             '.rs', '.swift', '.kt', '.ts', '.jsx', '.tsx', '.vue'}
            
            if path.suffix.lower() in code_extensions:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                return {
                    "text": f"File: {file_path}\n\n{content}"
                }
            
            # For image files, encode as base64
            image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
            if path.suffix.lower() in image_extensions:
                with open(path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode()
                return {
                    "inline_data": {
                        "mime_type": mime_type or f"image/{path.suffix[1:]}",
                        "data": image_data
                    }
                }
                
            # For other files, just mention the file exists
            return {
                "text": f"File exists: {file_path} (binary file, {mime_type or 'unknown type'})"
            }
            
        except Exception as e:
            return {"text": f"Error reading file {file_path}: {str(e)}"}
    
    def list_files(self, directory: str = ".") -> str:
        """List files in directory"""
        if not self.is_file_accessible(directory):
            return f"Directory {directory} is not accessible"
            
        try:
            path = Path(directory)
            if not path.exists() or not path.is_dir():
                return f"Directory {directory} does not exist"
                
            files = []
            for item in sorted(path.iterdir()):
                if item.is_file():
                    size = item.stat().st_size
                    # Add video file indicators
                    video_exts = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}
                    if item.suffix.lower() in video_exts:
                        files.append(f"🎬 {item.name} ({size / (1024*1024):.1f}MB)")
                    else:
                        files.append(f"📄 {item.name} ({size} bytes)")
                elif item.is_dir():
                    files.append(f"📁 {item.name}/")
                    
            return f"Contents of {directory}:\n" + "\n".join(files)
        except Exception as e:
            return f"Error listing directory {directory}: {str(e)}"
    
    def process_message(self, user_input: str) -> str:
        """Process user message and handle file operations"""
        
        # Check for file commands
        if user_input.startswith("/read "):
            file_path = user_input[6:].strip()
            file_content = self.read_file_content(file_path)
            if file_content:
                # Add file content to conversation and ask Gemini about it
                self.conversation_history.append({
                    "role": "user",
                    "parts": [file_content]
                })
                return self.call_gemini(f"I've shared the file {file_path} with you. Please analyze it and tell me about its contents.")
            else:
                return f"❌ Cannot access file: {file_path}"
                
        elif user_input.startswith("/ls") or user_input.startswith("/list"):
            directory = user_input.split(maxsplit=1)[1] if len(user_input.split()) > 1 else "."
            return self.list_files(directory)
            
        elif user_input.startswith("/help"):
            return self.show_help()
            
        elif user_input.startswith("/clear"):
            self.conversation_history.clear()
            return "🧹 Conversation history cleared"
            
        elif user_input.startswith("/cleanup"):
            # Clean up uploaded files
            cleaned = 0
            for file_path, file_info in list(self.uploaded_files.items()):
                file_name = file_info.get('name')
                if file_name and self.delete_uploaded_file(file_name):
                    cleaned += 1
                del self.uploaded_files[file_path]
            return f"🧹 Cleaned up {cleaned} uploaded files"
            
        elif user_input.startswith("/uploads"):
            if not self.uploaded_files:
                return "📁 No uploaded files"
            files_info = []
            for file_path, info in self.uploaded_files.items():
                size_mb = info.get('size', 0) / (1024 * 1024)
                files_info.append(f"🎬 {Path(file_path).name} ({size_mb:.1f}MB)")
        elif user_input.startswith("/dirs"):
            return "📁 Allowed directories:\n" + "\n".join(str(d) for d in self.allowed_dirs)
            
        else:
            # Regular chat message
            return self.call_gemini(user_input)
    
    def call_gemini(self, message: str) -> str:
        """Make API call to Gemini"""
        try:
            # Add user message to history
            self.conversation_history.append({
                "role": "user",
                "parts": [{"text": message}]
            })
            
            # Prepare API request
            url = f"{self.base_url}/models/{self.model}:generateContent"
            headers = {
                "Content-Type": "application/json",
            }
            
            data = {
                "contents": self.conversation_history,
                "generationConfig": {
                    "temperature": 0.7,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 8192,
                }
            }
            
            response = requests.post(
                f"{url}?key={self.api_key}",
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and len(result['candidates']) > 0:
                    ai_response = result['candidates'][0]['content']['parts'][0]['text']
                    
                    # Add AI response to history
                    self.conversation_history.append({
                        "role": "model",
                        "parts": [{"text": ai_response}]
                    })
                    
                    return ai_response
                else:
                    return "❌ No response generated"
            else:
                error_details = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
                return f"❌ API Error ({response.status_code}): {error_details}"
                
        except requests.exceptions.Timeout:
            return "❌ Request timed out. Please try again."
        except requests.exceptions.RequestException as e:
            return f"❌ Network error: {str(e)}"
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    def show_help(self) -> str:
        """Show help message"""
        return """
🤖 Gemini Terminal Chat Commands:

💬 Chat Commands:
  • Just type your message to chat with Gemini
  • /clear - Clear conversation history

📁 File Commands:
  • /read <file_path> - Read and analyze a file (text, code, images, videos)
  • /ls [directory] - List files in directory (default: current)
  • /list [directory] - Same as /ls
  • /dirs - Show allowed directories

🎬 Video Commands:
  • /read video.mp4 - Upload and analyze video content
  • /uploads - Show currently uploaded files
  • /cleanup - Delete all uploaded files from Gemini

❓ Other:
  • /help - Show this help
  • /quit or /exit - Exit the chat
  • Ctrl+C - Exit

Supported Video Formats:
  • MP4, AVI, MOV, MKV, WebM, FLV, WMV, M4V
  • Max size: 2GB per video

Examples:
  • /read demo.mp4
  • /read presentation.mov  
  • What happens in this video?
  • Describe the key scenes in the video
  • Extract text from this video
        """
    
    def run(self):
        """Run the interactive chat"""
        print("🤖 Gemini Terminal Chat with Video Support")
        print("=" * 55)
        print(f"📁 Allowed directories: {', '.join(str(d) for d in self.allowed_dirs)}")
        print("🎬 Supports: MP4, AVI, MOV, MKV, WebM, FLV, WMV, M4V")
        print("Type /help for commands or just start chatting!")
        print("=" * 55)
        
        try:
            while True:
                try:
                    user_input = input("\n💬 You: ").strip()
                    
                    if not user_input:
                        continue
                        
                    if user_input.lower() in ['/quit', '/exit', 'quit', 'exit']:
                        print("👋 Goodbye!")
                        break
                    
                    print("\n🤖 Gemini: ", end="", flush=True)
                    response = self.process_message(user_input)
                    print(response)
                    
                except KeyboardInterrupt:
                    print("\n🧹 Cleaning up uploaded files...")
                    for file_path, file_info in self.uploaded_files.items():
                        file_name = file_info.get('name')
                        if file_name:
                            self.delete_uploaded_file(file_name)
                    print("👋 Goodbye!")
                    break
                except EOFError:
                    print("\n👋 Goodbye!")
                    break
                    
        except Exception as e:
            print(f"\n❌ Unexpected error: {str(e)}")


def main():
    parser = argparse.ArgumentParser(description="Terminal chat with Gemini API and file access")
    parser.add_argument("--api-key", help="Gemini API key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--dirs", nargs="+", default=["."], 
                       help="Allowed directories for file access (default: current directory)")
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: Please provide Gemini API key via --api-key or GEMINI_API_KEY environment variable")
        print("Get your API key from: https://makersuite.google.com/app/apikey")
        sys.exit(1)
    
    # Create and run chat
    chat = GeminiChat(api_key, args.dirs)
    chat.run()


if __name__ == "__main__":
    main()