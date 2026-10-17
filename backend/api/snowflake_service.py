"""
Snowflake Service for FIELD Inspection
Handles Snowflake connections, file uploads, and AI operations
"""
import os
import json
import tempfile
from typing import BinaryIO
from datetime import datetime
from snowflake.snowpark import Session
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

load_dotenv()

class SnowflakeService:
    """Service class for Snowflake operations"""
    
    # Select a supported model for your own account and region.
    AI_MODELS = {key: os.getenv('SNOWFLAKE_MODEL', 'openai-gpt-4.1')
                 for key in ('summary', 'captions', 'extraction')}

    @property
    def AI_MODEL(self):
        """Backward compatibility"""
        return self.AI_MODELS["summary"]
    
    def __init__(self):
        """Initialize Snowflake connection"""
        self.session = self._create_session()
        self.stage_name = os.getenv("SNOWFLAKE_STAGE", "FIELD_AUDIO_FILES")
    
    def _get_oauth_token(self):
        """
        Get OAuth token from multiple sources:
        1. SPCS file (/snowflake/session/token) - for SPCS containers
        2. Environment variable SNOWFLAKE_OAUTH_TOKEN - for local development
        3. File path from SNOWFLAKE_OAUTH_TOKEN_FILE - for local development
        """
        # Try SPCS token file first (production)
        token_path = '/snowflake/session/token'
        try:
            if os.path.exists(token_path):
                with open(token_path, 'r') as f:
                    token = f.read().strip()
                    pass  # Do not log uploaded content or personal data.
                    return token
        except Exception as e:
            pass  # Do not log uploaded content or personal data.
        
        # Try environment variable (local development)
        token = os.getenv("SNOWFLAKE_OAUTH_TOKEN")
        if token:
            pass  # Do not log uploaded content or personal data.
            return token
        
        # Try token file path (local development)
        token_file = os.getenv("SNOWFLAKE_OAUTH_TOKEN_FILE")
        if token_file and os.path.exists(token_file):
            try:
                with open(token_file, 'r') as f:
                    token = f.read().strip()
                    pass  # Do not log uploaded content or personal data.
                    return token
            except Exception as e:
                pass  # Do not log uploaded content or personal data.
        
        pass  # Do not log uploaded content or personal data.
        return None
    
    def _create_session(self):
        """
        Create Snowflake session using OAuth authentication (SPCS or local),
        or fallback to private key authentication for local development.
        """
        base_conn = {
            "account": os.getenv("SNOWFLAKE_ACCOUNT"),
            "user": os.getenv("SNOWFLAKE_USER"),
            "role": os.getenv("SNOWFLAKE_ROLE"),
            "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
            "database": os.getenv("SNOWFLAKE_DATABASE"),
            "schema": os.getenv("SNOWFLAKE_SCHEMA"),
        }

        snowflake_host = os.getenv("SNOWFLAKE_HOST")
        token = self._get_oauth_token()

        # Try OAuth authentication (SPCS or local)
        conn = {
            "account": base_conn["account"],
        }
        
        # In SPCS OAuth mode, do NOT include user - it comes from the token
        if not (snowflake_host and token):
            conn["user"] = base_conn["user"]
        
        conn["role"] = base_conn.get("role")
        conn["warehouse"] = base_conn.get("warehouse")
        conn["database"] = base_conn.get("database")
        conn["schema"] = base_conn.get("schema")
        
        if snowflake_host:
            pass  # Do not log uploaded content or personal data.
            conn["host"] = snowflake_host
        if token:
            pass  # Do not log uploaded content or personal data.
            conn["token"] = token
            conn["authenticator"] = "oauth"
        if snowflake_host or token:
            try:
                session = Session.builder.configs(conn).create()
                pass  # Do not log uploaded content or personal data.
                
                # Verify current user
                try:
                    current_user = session.sql("SELECT CURRENT_USER()").collect()[0][0]
                    current_role = session.sql("SELECT CURRENT_ROLE()").collect()[0][0]
                    pass  # Do not log uploaded content or personal data.
                    pass  # Do not log uploaded content or personal data.
                except:
                    pass
                
                warehouse = base_conn.get("warehouse")
                database = base_conn.get("database")
                schema = base_conn.get("schema")
                
                # In SPCS, warehouse is REQUIRED for operations
                if warehouse:
                    try:
                        session.sql(f"USE WAREHOUSE {warehouse}").collect()
                        pass  # Do not log uploaded content or personal data.
                    except Exception as wh_err:
                        error_msg = f"Failed to activate warehouse {warehouse}: {wh_err}"
                        pass  # Do not log uploaded content or personal data.
                        if snowflake_host:
                            # In SPCS, warehouse is required - fail hard
                            raise RuntimeError(f"SPCS requires warehouse access: {error_msg}")
                        else:
                            pass  # Do not log uploaded content or personal data.
                else:
                    if snowflake_host:
                        raise RuntimeError("SPCS requires SNOWFLAKE_WAREHOUSE environment variable to be set")
                
                if database:
                    try:
                        session.sql(f"USE DATABASE {database}").collect()
                        pass  # Do not log uploaded content or personal data.
                    except Exception as db_err:
                        pass  # Do not log uploaded content or personal data.
                
                if schema:
                    try:
                        session.sql(f"USE SCHEMA {schema}").collect()
                        pass  # Do not log uploaded content or personal data.
                    except Exception as sch_err:
                        pass  # Do not log uploaded content or personal data.
                
                return session
            except Exception as e:
                pass  # Do not log uploaded content or personal data.
                # If we're in SPCS (snowflake_host is set), OAuth is required - don't try fallbacks
                if snowflake_host:
                    pass  # Do not log uploaded content or personal data.
                    raise RuntimeError(f"SPCS OAuth authentication failed: {e}")

        # Try private key authentication (local dev fallback)
        pass  # Do not log uploaded content or personal data.
        try:
            from cryptography.hazmat.primitives import serialization
            key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
            if key_path and os.path.exists(key_path):
                with open(key_path, "rb") as key_file:
                    private_key = serialization.load_pem_private_key(
                        key_file.read(),
                        password=None
                    )
                private_key_der = private_key.private_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                )
                connection_params = {
                    "account": base_conn["account"],
                    "user": base_conn["user"],
                    "role": base_conn["role"],
                    "warehouse": base_conn["warehouse"],
                    "database": base_conn["database"],
                    "schema": base_conn["schema"],
                    "private_key": private_key_der
                }
                session = Session.builder.configs(connection_params).create()
                pass  # Do not log uploaded content or personal data.
                return session
        except Exception as e:
            pass  # Do not log uploaded content or personal data.

        # If both methods fail, raise error
        pass  # Do not log uploaded content or personal data.
        raise RuntimeError(
            "No valid authentication method found. For local development, set: "
            "- SNOWFLAKE_OAUTH_TOKEN environment variable, or "
            "- SNOWFLAKE_OAUTH_TOKEN_FILE pointing to a file containing the token, or "
            "- SNOWFLAKE_PRIVATE_KEY_PATH pointing to a private key file. "
            "For SPCS, ensure /snowflake/session/token exists."
        )
    
    def test_connection(self):
        """Test Snowflake connection"""
        try:
            result = self.session.sql("SELECT CURRENT_VERSION()").collect()
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    def upload_to_stage(self, file_data: BinaryIO, filename: str, file_type: str = "audio"):
        """
        Upload file to Snowflake stage
        
        Args:
            file_data: File binary data
            filename: Original filename
            file_type: Type of file (audio/image)
            
        Returns:
            Stage filename
        """
        try:
            # Use UUID prefix to guarantee uniqueness even with rapid uploads
            import uuid
            unique_id = str(uuid.uuid4())[:8]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")  # Include microseconds
            
            # Clean filename to remove any unsafe characters
            safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
            if not safe_filename:
                safe_filename = f"{file_type}.dat"  # fallback
            
            stage_filename = f"{timestamp}_{unique_id}_{safe_filename}"
            
            # Create temporary file with the target name
            temp_dir = tempfile.gettempdir()
            tmp_path = os.path.join(temp_dir, stage_filename)
            
            with open(tmp_path, 'wb') as tmp_file:
                content = file_data.read()
                if len(content) == 0:
                    raise Exception(f"File {filename} is empty (0 bytes)")
                tmp_file.write(content)
                logger.info(f"Wrote {len(content)} bytes to temp file: {tmp_path}")
            
            try:
                # Upload to stage - Snowflake preserves the filename
                put_result = self.session.file.put(
                    tmp_path,
                    f"@{self.stage_name}",
                    auto_compress=False,
                    overwrite=True
                )
                
                logger.info(f"File uploaded to stage: {stage_filename}")
                logger.info(f"PUT result: {put_result}")
                
                # Small delay to ensure Snowflake has flushed the file to stage storage
                # before AI_TRANSCRIBE attempts to read it
                import time
                time.sleep(0.5)
                
                return stage_filename
                
            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                    
        except Exception as e:
            logger.error(f"Failed to upload to stage: {e}")
            raise
    
    def transcribe_audio(self, stage_filename: str):
        """
        Transcribe audio using Snowflake AI_TRANSCRIBE (premium/cloud)
        
        Args:
            stage_filename: Filename in Snowflake stage
            
        Returns:
            Transcript text
        """
        try:
            sql = f"""
            SELECT AI_TRANSCRIBE(
                TO_FILE('@{self.stage_name}/{stage_filename}')
            ) as transcription
            """
            # Execute the blocking Snowflake query with a configurable timeout
            import concurrent.futures
            timeout = int(os.getenv('SNOWFLAKE_TRANSCRIBE_TIMEOUT', '600'))  # seconds
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(lambda: self.session.sql(sql).collect())
            try:
                result = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise Exception(f"AI_TRANSCRIBE timed out after {timeout} seconds. Consider using shorter audio or increasing SNOWFLAKE_TRANSCRIBE_TIMEOUT in environment.")
            
            if result and len(result) > 0:
                transcription_json = result[0]["TRANSCRIPTION"]
                
                if isinstance(transcription_json, str):
                    transcription_data = json.loads(transcription_json)
                else:
                    transcription_data = transcription_json
                
                # Extract text and metadata
                transcript_text = transcription_data.get("text", str(transcription_data))
                audio_duration = transcription_data.get("audio_duration", 0)
                
                # Log raw response for debugging
                logger.info(f"AI_TRANSCRIBE returned: duration={audio_duration}s, text_length={len(transcript_text)}")
                
                # CRITICAL VALIDATION: Detect known hallucination patterns
                # Snowflake AI_TRANSCRIBE sometimes hallucinates these phrases for poor quality audio
                # Based on Snowflake docs: hallucination occurs with silence, corruption, or poor quality
                # Common patterns from YouTube/video training data
                hallucination_patterns = [
                    # Original patterns
                    "I'M GOING TO TELL YOU",
                    "I'M GOING TO TELL YOU.",
                    "I AM GOING TO TELL YOU",
                    "THANK YOU FOR WATCHING",
                    "PLEASE SUBSCRIBE",
                    # Additional YouTube/video patterns from model training data
                    "DON'T FORGET TO LIKE",
                    "DON'T FORGET TO SUBSCRIBE",
                    "LIKE AND SUBSCRIBE",
                    "IN THIS VIDEO",
                    "HEY GUYS",
                    "WHAT'S UP",
                    "WHAT'S UP GUYS",
                    "WELCOME BACK",
                    "THANKS FOR WATCHING",
                    "SEE YOU NEXT TIME",
                    "BYE BYE",
                    # Generic filler phrases (silence hallucinations)
                    "UM",
                    "UH",
                    "HMM",
                    "OKAY",
                    "RIGHT",
                ]
                
                transcript_upper = transcript_text.upper().strip()
                for pattern in hallucination_patterns:
                    if transcript_upper == pattern or transcript_upper == pattern + ".":
                        error_msg = (
                            f"AI_TRANSCRIBE returned a hallucinated phrase: '{transcript_text}'. "
                            f"This typically indicates poor audio quality, silence, or corruption. "
                            f"Audio duration: {audio_duration}s. "
                            f"Please re-record the audio with better quality or check the recording device."
                        )
                        logger.error(error_msg)
                        raise Exception(error_msg)
                
                # CRITICAL: Check for metadata corruption (duration mismatch)
                # Per your amt.mp3 case: file reports 0.324s but has long transcript
                # This indicates file corruption or metadata issues
                if audio_duration < 1.0 and len(transcript_text) > 50:
                    error_msg = (
                        f"Audio file metadata corruption detected: Duration reports {audio_duration}s "
                        f"but transcript is {len(transcript_text)} characters long. "
                        f"This indicates file corruption or format incompatibility. "
                        f"Please re-record or convert the audio to a standard format (WAV or MP3)."
                    )
                    logger.error(error_msg)
                    raise Exception(error_msg)
                
                # Sanity check: if audio is >10s but transcript is suspiciously short, warn
                if audio_duration > 10 and len(transcript_text) < 50:
                    logger.warning(
                        f"Suspiciously short transcript for {audio_duration}s audio. "
                        f"Text: '{transcript_text}'. This may indicate incomplete transcription."
                    )
                
                # Additional check: if transcript is very short relative to duration, warn
                # Expect roughly 2-3 words per second for normal speech
                expected_min_words = max(1, int(audio_duration * 1.5))  # Conservative estimate
                actual_words = len(transcript_text.split())
                
                if audio_duration > 5 and actual_words < expected_min_words:
                    logger.warning(
                        f"Transcript may be incomplete: {actual_words} words for {audio_duration}s audio "
                        f"(expected at least {expected_min_words} words). "
                        f"Check audio quality and re-record if necessary."
                    )
                
                return transcript_text
            
            raise Exception("No transcription result returned")
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise
    
    def transcribe_audio_whisper(self, stage_filename: str):
        """
        Transcribe audio using OpenAI Whisper (free/local)
        
        NOTE: Requires ffmpeg to be installed and available in PATH
        
        Args:
            stage_filename: Filename in Snowflake stage
            
        Returns:
            Transcript text
            
        Raises:
            Exception: If ffmpeg is not installed or transcription fails
        """
        try:
            import whisper
            import subprocess
            import sys
            import shutil
            
            # Check if ffmpeg is available
            if not shutil.which('ffmpeg'):
                raise Exception(
                    "ffmpeg is not installed or not in PATH. "
                    "Whisper requires ffmpeg for audio processing. "
                    "Install it from https://ffmpeg.org/download.html or use Snowflake AI transcription instead. "
                    "On Windows: Download from https://github.com/BtbN/FFmpeg-Builds/releases and add to PATH"
                )
            
            # Download file from stage to temp location
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(stage_filename)[1]) as tmp_file:
                tmp_path = tmp_file.name
                
            downloaded_file = None
            
            try:
                # Download from stage
                get_sql = f"GET '@{self.stage_name}/{stage_filename}' 'file://{os.path.dirname(tmp_path)}'"
                self.session.sql(get_sql).collect()
                
                # The GET command downloads with original filename
                downloaded_file = os.path.join(os.path.dirname(tmp_path), stage_filename)
                
                if not os.path.exists(downloaded_file):
                    raise Exception(f"Failed to download file from stage: {stage_filename}")
                
                # Load Whisper model and transcribe directly (no subprocess needed)
                logger.info("Loading Whisper model...")
                model = whisper.load_model("base")
                
                logger.info(f"Transcribing audio file: {downloaded_file}")
                result = model.transcribe(downloaded_file, fp16=False)  # Force CPU mode
                
                transcript = result["text"].strip()
                
                logger.info(f"Transcription complete: {len(transcript)} characters")
                
                # Cleanup
                if os.path.exists(downloaded_file):
                    os.unlink(downloaded_file)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                
                return transcript
                
            except Exception as e:
                # Cleanup on error
                if downloaded_file and os.path.exists(downloaded_file):
                    os.unlink(downloaded_file)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
                
        except Exception as e:
            error_msg = str(e)
            
            # Provide helpful error messages
            if "ffmpeg" in error_msg.lower() or "no such file or directory: 'ffmpeg'" in error_msg.lower():
                logger.error("ffmpeg not found - required for Whisper transcription")
                raise Exception(
                    "Whisper transcription requires ffmpeg to be installed. "
                    "Please install ffmpeg and add it to your system PATH, "
                    "or use Snowflake AI transcription instead (set use_whisper=false)."
                )
            
            logger.error(f"Whisper transcription failed: {e}")
            raise Exception(f"Whisper transcription error: {error_msg}")
    
    def summarize_transcript(self, transcript: str):
        """
        Summarize transcript using Snowflake AI_COMPLETE
        
        Args:
            transcript: Transcript text
            
        Returns:
            Dict with structured inspection data
        """
        try:
            # Load ALL defect codes from JSON file
            defect_codes_list = []
            try:
                from pathlib import Path
                codes_file = Path(__file__).parent.parent / 'codes' / 'defect_codes.json'
                if codes_file.exists():
                    with open(codes_file, 'r') as f:
                        defect_codes_data = json.load(f)
                        
                        # Load ALL codes with full context
                        defect_codes_list = [
                            f"{item['code']}: [{item['category']}] {item['subcategory']} - {item['description']}"
                            for item in defect_codes_data
                        ]
                        
                        logger.info(f"Loaded {len(defect_codes_list)} defect codes for AI prompt")
                else:
                    logger.warning(f"Defect codes file not found at {codes_file}")
            except Exception as e:
                logger.warning(f"Could not load defect codes: {e}")
            
            # Build defect codes reference string
            defect_codes_ref = "\n".join(defect_codes_list) if defect_codes_list else "Use only the supplied synthetic demonstration categories; otherwise UNKNOWN"
            
            escaped_transcript = transcript.replace("'", "''")
            
            prompt = f"""You are a professional field reviewer producing a Field Reports (REFERENCE) report.

CRITICAL: Read the transcript and COUNT how many separate defects are mentioned BEFORE you start mapping them to codes. Each distinct issue must have its own entry.

Read the inspection transcript and map EVERY defect to an synthetic demonstration defect code from the library below. Respond with structured JSON in the EXACT format:

{{
    "defects": [
        {{
            "defect_code": "REFERENCE code from the library (e.g., D.1.1)",
            "category": "Category from the library (e.g., Site Drainage)",
            "subcategory": "Subcategory from the library",
            "code_description": "Description text supplied in the library",
            "defect_found": "Plain-language summary of what was observed",
            "non_compliance": "Observation requiring reviewer confirmation",
            "standard": "User-supplied reference only; otherwise Not assessed",
            "evidence_quote": "Short quote from the transcript that proves the issue"
        }}
    ]
}}

REFERENCE DEFECT CODE LIBRARY (use ONLY these codes; copy category/subcategory/description EXACTLY):
{defect_codes_ref}

SELECTION RULES:
1. Read the transcript carefully and identify EVERY SINGLE distinct defect mentioned - do not skip any.
2. Each separate issue, non-compliance, or defect observation must be listed as its own entry.
3. For each defect, choose the SINGLE code whose category + subcategory best matches the described issue.
4. Never invent, approximate, or use legacy audit codes (D1, AL2, etc.). Only choose from the library above.
5. If no supplied demonstration category matches, use UNKNOWN and request human review.
6. Include the exact code description from the library so auditors can see the example wording.
7. Provide a one-sentence "defect_found" summary and a separate "non_compliance" explanation referencing performance requirements.
8. Use only a reference explicitly provided in the input; otherwise write Not assessed. Do not invent standards or regulatory findings.
9. Include an "evidence_quote"—a short phrase pulled verbatim from the transcript supporting your finding.
10. Return STRICT JSON. Do not wrap it in markdown or add commentary.
11. IMPORTANT: If the transcript mentions 5 defects, your response must contain 5 separate defect entries.

Transcript:
{escaped_transcript}

Respond with ONLY the JSON structure shown above."""
            
            escaped_prompt = prompt.replace("'", "''")
            
            # Removed AI_COUNT_TOKENS-based estimator because Snowflake often rejects
            # requests for certain model identifiers (e.g., OPENAI-GPT-4.1). This
            # keeps the transcription workflow clean and avoids noisy warnings.
            
            sql = f"""
            SELECT AI_COMPLETE(
                '{self.AI_MODELS["summary"]}',
                '{escaped_prompt}',
                {{'max_tokens': 16000}}
            ) as summary
            """
            
            # Run AI_COMPLETE with timeout guard
            import concurrent.futures
            timeout = int(os.getenv('SNOWFLAKE_AI_TIMEOUT', '300'))  # seconds (default 5 minutes)
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(lambda: self.session.sql(sql).collect())
            try:
                result = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise Exception(f"AI_COMPLETE timed out after {timeout} seconds. Consider shortening the request or increasing SNOWFLAKE_AI_TIMEOUT.")
            
            if result and len(result) > 0:
                json_response = result[0]["SUMMARY"]
                logger.info(f"Raw AI response type: {type(json_response)}, length: {len(str(json_response))}")
                
                # Handle both string and dict responses from AI_COMPLETE
                if isinstance(json_response, str):
                    # Clean the response - remove any text before JSON and markdown code blocks
                    original_response = json_response
                    json_response = json_response.strip()
                    
                    # Remove common prefixes like "Here is the structured JSON response:"
                    prefixes_to_remove = [
                        "Here is the structured JSON response:",
                        "Here is the JSON response:",
                        "Here's the structured JSON:",
                        "Here's the JSON:",
                        "Here is the response:",
                        "Here's the response:"
                    ]
                    for prefix in prefixes_to_remove:
                        if json_response.startswith(prefix):
                            json_response = json_response[len(prefix):].strip()
                            logger.info(f"Removed prefix: {prefix}")
                    
                    # Remove markdown code blocks - be aggressive
                    # Remove opening code fence
                    if json_response.startswith('```json'):
                        json_response = json_response[7:].strip()
                        logger.info("Removed ```json opening fence")
                    elif json_response.startswith('```'):
                        json_response = json_response[3:].strip()
                        logger.info("Removed ``` opening fence")
                    
                    # Remove closing code fence
                    if json_response.endswith('```'):
                        json_response = json_response[:-3].strip()
                        logger.info("Removed ``` closing fence")
                    
                    # Extra check: if response still starts with { or [, we're good
                    # If not, try to find the first { or [
                    if not json_response.startswith('{') and not json_response.startswith('['):
                        logger.warning(f"Response doesn't start with {{ or [, trying to find JSON start")
                        # Find first occurrence of { or [
                        json_start = min(
                            (json_response.find('{') if json_response.find('{') != -1 else len(json_response)),
                            (json_response.find('[') if json_response.find('[') != -1 else len(json_response))
                        )
                        if json_start < len(json_response):
                            json_response = json_response[json_start:]
                            logger.info(f"Trimmed to JSON start at position {json_start}")
                    
                    # Similarly, ensure it ends with } or ]
                    if not json_response.endswith('}') and not json_response.endswith(']'):
                        logger.warning(f"Response doesn't end with }} or ], trying to find JSON end")
                        # Find last occurrence of } or ]
                        json_end = max(
                            json_response.rfind('}'),
                            json_response.rfind(']')
                        )
                        if json_end != -1:
                            json_response = json_response[:json_end+1]
                            logger.info(f"Trimmed to JSON end at position {json_end}")
                    
                    logger.info(f"Cleaned response starts with: {json_response[:50]}")
                    logger.info(f"Cleaned response ends with: {json_response[-50:]}")
                    
                    # Decode escaped newlines and quotes that might be in the string
                    # The AI sometimes returns JSON with escaped characters like \n and \"
                    json_response = json_response.encode().decode('unicode_escape')
                    logger.info(f"After unicode_escape: starts with {json_response[:50]}")
                    
                    # Parse JSON string
                    try:
                        import json as json_lib
                        structured_data = json_lib.loads(json_response)
                        logger.info(f"Successfully parsed JSON string response, type: {type(structured_data)}")
                        return structured_data
                    except json_lib.JSONDecodeError as e:
                        logger.error(f"Failed to parse AI response as JSON after cleaning")
                        logger.error(f"Original response: {original_response[:200]}...")
                        logger.error(f"Cleaned response: {json_response[:200]}...")
                        logger.error(f"JSON error: {e}")
                        # Fallback to basic text response
                        return {
                            "defects": [{"title": "Analysis Error", "description": "Failed to parse inspection analysis", "standard": "N/A", "clause": "N/A", "requirement": "N/A"}],
                            "safety_concerns": [{"category": "Analysis Error", "description": "Could not analyze safety concerns", "standards_violated": []}],
                            "recommended_actions": [{"action": "Review Required", "details": "Manual review of inspection findings needed", "standard": "N/A", "clause": "N/A"}],
                            "conclusion": "Inspection analysis could not be completed. Manual review required."
                        }
                else:
                    # AI_COMPLETE returned a dict directly
                    logger.info(f"AI_COMPLETE returned dict directly, type: {type(json_response)}")
                    return json_response
            
            logger.error("No summary result returned from AI_COMPLETE")
            raise Exception("No summary result returned")
            
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            # Return a safe fallback dictionary instead of raising exception
            return {
                "defects": [{"title": "Processing Error", "description": f"Failed to analyze transcript: {str(e)}", "standard": "N/A", "clause": "N/A", "requirement": "N/A"}],
                "safety_concerns": [],
                "recommended_actions": [{"action": "Review Required", "details": "Manual review of inspection transcript needed", "standard": "N/A", "clause": "N/A"}],
                "conclusion": "Inspection analysis could not be completed due to processing error."
            }
    
    def extract_defects_from_transcript(self, transcript: str, num_images: int) -> list:
        """
        Extract specific defects from transcript to match with images
        
        Args:
            transcript: Full transcript text
            num_images: Number of images to generate captions for
            
        Returns:
            List of defect descriptions (one per image)
        """
        try:
            escaped_transcript = transcript.replace("'", "''")
            
            prompt = f"""You are analyzing a building inspection transcript to extract specific defects that can be matched to {num_images} photographs.

Analyze the transcript and identify exactly {num_images} distinct defects or issues mentioned. For each defect, provide:
1. The specific location
2. The actual defect or issue
3. Keep it concise (1-2 sentences per defect)

Transcript:
{escaped_transcript}

Return ONLY a JSON array with {num_images} objects, each with a "caption" field.

If there are fewer than {num_images} distinct defects in the transcript, repeat the most critical ones or provide general observations. Ensure exactly {num_images} captions are returned."""
            
            escaped_prompt = prompt.replace("'", "''")
            
            sql = f"""
            SELECT AI_COMPLETE(
                '{self.AI_MODELS["captions"]}',
                '{escaped_prompt}',
                {{'max_tokens': 8096}}
            ) as defects_json
            """
            
            result = self.session.sql(sql).collect()
            
            if result and len(result) > 0:
                defects_json = result[0]["DEFECTS_JSON"]
                # Clean the response - remove markdown code blocks and quotes
                defects_json = defects_json.strip('"').strip()
                
                # Remove markdown code blocks if present
                if defects_json.startswith('```'):
                    # Remove opening ```json or ```
                    defects_json = defects_json.split('\n', 1)[1] if '\n' in defects_json else defects_json[3:]
                    # Remove closing ```
                    if '```' in defects_json:
                        defects_json = defects_json.rsplit('```', 1)[0]
                
                # Remove any remaining "json" prefix
                if defects_json.startswith('json'):
                    defects_json = defects_json[4:]
                
                defects_json = defects_json.strip().replace('\\n', '').replace('\\"', '"')
                
                # Try to parse as JSON
                try:
                    import json as json_lib
                    defects = json_lib.loads(defects_json)
                    
                    # Extract just the captions
                    captions = [d.get('caption', f'Defect {i+1}') for i, d in enumerate(defects)]
                    
                    # Ensure we have exactly num_images captions
                    while len(captions) < num_images:
                        captions.append(f"Additional defect - See inspection notes")
                    
                    return captions[:num_images]
                    
                except json_lib.JSONDecodeError as e:
                    logger.error(f"Failed to parse defects JSON: {defects_json[:200]}... Error: {e}")
                    # Fallback: split by lines and take first num_images
                    lines = [line.strip() for line in defects_json.split('\n') if line.strip() and not line.startswith('[') and not line.startswith(']')]
                    return lines[:num_images] if lines else [f"Defect {i+1} - See inspection notes" for i in range(num_images)]
            
            return [f"Defect {i+1} - See inspection notes for details" for i in range(num_images)]
            
        except Exception as e:
            logger.error(f"Defect extraction failed: {e}")
            return [f"Defect {i+1} - See inspection notes for details" for i in range(num_images)]
    
    def analyze_image_content(self, stage_filename: str, context: str = "") -> str:
        """
        Generate caption for image by analyzing the actual image content
        
        Args:
            stage_filename: Filename in Snowflake stage
            context: Context from transcript to help generate relevant caption
            
        Returns:
            Caption describing the defect visible in the image
        """
        try:
            # Build simple, direct prompt for AI caption generation
            if context and context.strip():
                prompt = f"""You are a professional field reviewer analyzing a defect photograph.

Analyze this image and identify the specific construction defect or issue visible.

Context from inspection: {context}

Respond with a concise, professional caption (1-2 sentences) describing the defect visible in this image. Focus on what the defect is and why it's non-compliant, without using defect code numbers or referencing specific standard clause numbers. If you cannot clearly identify a defect in the image, respond with "Not identified"."""
            else:
                prompt = """You are a professional field reviewer analyzing a defect photograph.

Analyze this image and identify the specific construction defect or issue visible. Provide a professional caption that would appear in an inspection report.

Respond with a concise, professional caption (1-2 sentences) describing the defect visible in this image. Focus on what the defect is and why it's non-compliant, without using defect code numbers or referencing specific standard clause numbers. If you cannot clearly identify a defect in the image, respond with "Not identified"."""
            
            escaped_prompt = prompt.replace("'", "''")
            
            sql = f"""
            SELECT AI_COMPLETE(
                '{self.AI_MODELS["captions"]}',
                '{escaped_prompt}',
                TO_FILE('@{self.stage_name}/{stage_filename}'),
                {{'max_tokens': 8096}}
            ) as caption
            """
            
            result = self.session.sql(sql).collect()
            
            if result and len(result) > 0:
                caption = result[0]["CAPTION"]
                # Clean up the caption
                caption = caption.strip('"').replace('\\n', ' ').replace('**', '').strip()
                
                return caption
            
            # Fallback if no result
            return f"Defect image - see inspection notes for details"
            
        except Exception as e:
            logger.error(f"Image analysis failed for {stage_filename}: {e}")
            return f"Image analysis failed"
    
    def generate_captions_for_images(self, image_files: list, context: str = "", defects: list = None) -> list:
        """
        Generate captions for multiple images by analyzing each image directly.
        
        This approach analyzes what's ACTUALLY visible in each image rather than
        trying to match images to defects from the transcript (which can mismatch).

        Args:
            image_files: List of stage filenames
            context: Context string (summary or transcript) - used as general background only
            defects: Structured defect list (REFERENCE codes + descriptions) for optional alignment

        Returns:
            List of captions, one per image
        """
        captions = []
        defects = defects or []

        if not image_files:
            return []

        try:
            # Get a brief summary of inspection context (but don't try to match specific defects)
            context_summary = ""
            if context and len(context) > 100:
                # Extract just the general type of inspection for context
                if "gas" in context.lower():
                    context_summary += "Gas installation issues. "
                if "brac" in context.lower():
                    context_summary += "Structural bracing concerns. "
                if "window" in context.lower():
                    context_summary += "Window installation issues. "
                if "drain" in context.lower():
                    context_summary += "Drainage defects. "
                if not context_summary:
                    context_summary = "Building construction defects identified. "
            else:
                context_summary = "Building inspection defects. "
            
            defect_options_text = ""
            if defects:
                defect_lines = []
                for item in defects:
                    code = item.get('defect_code', 'N/A')
                    title = item.get('defect_found') or item.get('description') or 'Unnamed defect'
                    defect_lines.append(f"{code}: {title}")
                if defect_lines:
                    defect_options_text = "\n".join(defect_lines[:12])  # keep prompt compact
                    if len(defect_lines) > 12:
                        defect_options_text += "\n..."
            
            pass  # Do not log uploaded content or personal data.
            pass  # Do not log uploaded content or personal data.
            
            # Analyze each image independently based on what's visible
            for i, stage_filename in enumerate(image_files):
                try:
                    pass  # Do not log uploaded content or personal data.

                    # Pure vision approach - describe what's visible without forcing code matches
                    prompt = f"""You are a REFERENCE field reviewer writing a caption for a defect photograph in an official inspection report.

INSPECTION TYPE: {context_summary}

TASK: Write a single professional caption (2-3 sentences maximum) for this photograph.

REQUIREMENTS:
1. Start with what you SEE in the photo (e.g., "Photograph shows..." or "Image depicts...")
2. Identify the specific building element and its condition (e.g., "external drainage pipe showing cracking")
3. Clearly state why this is a defect or non-compliance issue
4. Be specific about location and extent (e.g., "along 3-meter section of northern boundary")
5. Write in third person, professional tone suitable for legal documentation
6. Do NOT invent defect codes or reference specific standard clauses
7. Focus ONLY on what is objectively visible in the photograph

EXAMPLE FORMAT (do not copy - this is just to show structure):
"Photograph shows inadequate drainage slope at western perimeter, with visible stormwater ponding against the building foundation. The drainage fails to meet minimum fall requirements, creating risk of water ingress and structural damage."
"""

                    escaped_prompt = prompt.replace("'", "''")

                    sql = f"""
                    SELECT AI_COMPLETE(
                        '{self.AI_MODELS["captions"]}',
                        '{escaped_prompt}',
                        TO_FILE('@{self.stage_name}/{stage_filename}'),
                        {{'max_tokens': 8096}}
                    ) as caption
                    """

                    result = self.session.sql(sql).collect()

                    if result and len(result) > 0:
                        caption = result[0]["CAPTION"]
                        # Clean up the caption
                        caption = caption.strip('"').replace('\\n', ' ').replace('**', '').strip()

                        # Use generic fallback only if caption is empty
                        if not caption or len(caption) < 15:
                            caption = f"Construction defect {i+1} - see inspection notes for details"
                            pass  # Do not log uploaded content or personal data.
                        else:
                            # Try to match this caption with transcript defects
                            match_result = self.match_caption_to_defect(caption, defects)
                            
                            if match_result.get('matched'):
                                caption = match_result['caption']
                                pass  # Do not log uploaded content or personal data.
                            else:
                                pass  # Do not log uploaded content or personal data.

                        captions.append(caption)
                        pass  # Do not log uploaded content or personal data.

                    else:
                        fallback_caption = f"Construction defect {i+1} - see inspection notes"
                        captions.append(fallback_caption)
                        pass  # Do not log uploaded content or personal data.

                except Exception as e:
                    logger.error(f"Failed to analyze image {stage_filename}: {e}")
                    pass  # Do not log uploaded content or personal data.
                    fallback_caption = f"Building defect {i+1} - see inspection notes"
                    captions.append(fallback_caption)
                    pass  # Do not log uploaded content or personal data.

            return captions

        except Exception as e:
            logger.error(f"Caption generation failed: {e}")
            # Use professional generic captions as final fallback
            return [f"Construction defect {i+1} - see inspection notes for details" for i in range(len(image_files))]
    
    def _get_transcript_segment_for_image(self, transcript: str, image_index: int, total_images: int) -> str:
        """
        Extract a relevant segment of transcript that might correspond to a specific image
        
        Args:
            transcript: Full transcript
            image_index: Index of the image (0-based)
            total_images: Total number of images
            
        Returns:
            Relevant transcript segment
        """
        if not transcript:
            return ""
        
        # Simple approach: divide transcript into roughly equal segments
        words = transcript.split()
        segment_size = max(1, len(words) // total_images)
        start_idx = image_index * segment_size
        end_idx = min(len(words), (image_index + 1) * segment_size)
        
        segment = " ".join(words[start_idx:end_idx])
        return segment
    
    def _generate_transcript_based_caption(self, transcript_segment: str, image_number: int) -> str:
        """
        Generate a caption based on a transcript segment when image analysis fails
        
        Args:
            transcript_segment: Portion of transcript
            image_number: Image number for fallback
            
        Returns:
            Caption string
        """
        try:
            if not transcript_segment or not transcript_segment.strip():
                return f"Defect {image_number} - Building inspection image"
            
            escaped_segment = transcript_segment.replace("'", "''")
            
            prompt = f"""Based on this segment of an inspection transcript, generate a concise professional caption for a defect photograph.

Transcript segment: {escaped_segment}

Create a 1-2 sentence caption describing what might be shown in a photograph related to this part of the inspection."""
            
            escaped_prompt = prompt.replace("'", "''")
            
            sql = f"""
            SELECT AI_COMPLETE(
                '{self.AI_MODELS["captions"]}',
                '{escaped_prompt}'
            ) as caption
            """
            
            import concurrent.futures
            timeout = int(os.getenv('SNOWFLAKE_AI_TIMEOUT', '300'))
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(lambda: self.session.sql(sql).collect())
            try:
                result = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise Exception(f"AI_COMPLETE (captions) timed out after {timeout} seconds. Try reducing batch size or increasing SNOWFLAKE_AI_TIMEOUT.")
            
            if result and len(result) > 0:
                caption = result[0]["CAPTION"]
                return caption.strip('"').replace('\\n', ' ').replace('**', '').strip()
            
        except Exception as e:
            logger.error(f"Transcript-based caption generation failed: {e}")
        
        return f"Defect {image_number} - Building inspection image"
    
    def generate_image_caption(self, transcript: str, image_number: int, total_images: int) -> str:
        """
        Generate caption for a specific image based on transcript
        
        DEPRECATED: Use extract_defects_from_transcript for better results
        
        Args:
            transcript: Full transcript text
            image_number: Current image number (1-indexed)
            total_images: Total number of images
            
        Returns:
            Caption text for the image
        """
        # Use the new method
        captions = self.extract_defects_from_transcript(transcript, total_images)
        return captions[image_number - 1] if image_number <= len(captions) else f"Defect {image_number}"
    
    def get_file_from_stage(self, stage_filename: str):
        """Download file from Snowflake stage"""
        try:
            import tempfile
            import os
            import requests
            
            # Create a temporary directory
            temp_dir = tempfile.mkdtemp()
            
            # Try first to get a presigned URL and download via HTTP
            try:
                presigned = self.get_stage_file_url(stage_filename)
                if presigned:
                    r = requests.get(presigned, timeout=30)
                    r.raise_for_status()
                    logger.debug(f"Downloaded {stage_filename} via presigned URL")
                    return r.content
            except Exception as e:
                logger.debug(f"Presigned URL download failed for {stage_filename}: {e}")

            # Fallback to GET command to download from stage (SQL)
            # Quote the filename/path to safely handle spaces and special characters
            # Escape single quotes in stage_filename
            safe_name = stage_filename.replace("'", "''")
            safe_stage_path = f"@{self.stage_name}/'{safe_name}'"
            get_sql = f"GET {safe_stage_path} file://{temp_dir}"
            self.session.sql(get_sql).collect()
            logger.debug(f"Downloaded {stage_filename} using Snowflake GET")
            
            # Find the downloaded file
            files = os.listdir(temp_dir)
            if not files:
                raise Exception(f"File {stage_filename} not found in stage")
            
            # Read the file content
            file_path = os.path.join(temp_dir, files[0])
            with open(file_path, 'rb') as f:
                file_bytes = f.read()
            
            # Clean up
            os.remove(file_path)
            os.rmdir(temp_dir)
            
            return file_bytes
            
        except Exception as e:
            logger.error(f"Failed to get file from stage: {e}")
            raise Exception(f"Failed to download {stage_filename} from stage: {e}")
    
    def get_stage_file_url(self, stage_filename: str):
        """Get presigned URL for stage file"""
        try:
            sql = f"SELECT GET_PRESIGNED_URL(@{self.stage_name}, '{stage_filename}', 3600) as url"
            result = self.session.sql(sql).collect()
            
            if result and len(result) > 0:
                return result[0]["URL"]
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get presigned URL: {e}")
            return None
    
    def match_caption_to_defect(self, image_caption: str, defects: list) -> dict:
        """
        Match an image caption to the most likely defect from the transcript analysis.
        Uses AI to determine semantic similarity between what's visible in the photo
        and what was described in the audio transcript.
        
        Args:
            image_caption: Caption generated from image analysis (what AI sees)
            defects: List of defect objects from transcript analysis (what inspector said)
            
        Returns:
            Dict with matched defect info and combined caption, or original caption if no match
        """
        if not defects or not image_caption:
            return {
                "matched": False,
                "caption": image_caption,
                "defect_code": None
            }
        
        try:
            # Build defect options for matching
            defect_options = []
            for idx, defect in enumerate(defects):
                defect_options.append({
                    "index": idx,
                    "code": defect.get('defect_code', 'UNKNOWN'),
                    "description": defect.get('defect_found', ''),
                    "category": defect.get('category', ''),
                    "subcategory": defect.get('subcategory', '')
                })
            
            defects_text = "\n".join([
                f"{d['index']+1}. {d['code']}: {d['description']} ({d['category']} - {d['subcategory']})"
                for d in defect_options
            ])
            
            escaped_caption = image_caption.replace("'", "''")
            
            prompt = f"""You are matching a photograph caption to the most likely defect from an audio transcript.

PHOTOGRAPH CAPTION (what AI sees in the image):
{escaped_caption}

DEFECTS FROM AUDIO TRANSCRIPT (what inspector verbally described):
{defects_text}

TASK: Determine if the photograph clearly matches one of the transcript defects.

Respond with JSON in this EXACT format:
{{
    "matched": true or false,
    "defect_index": number (0-based index, or null if no match),
    "confidence": "high", "medium", or "low",
    "reasoning": "brief explanation of match or why no match"
}}

MATCHING RULES:
1. Only match if there's clear semantic overlap (e.g., both mention "window crack" or "drainage ponding")
2. Consider synonyms (e.g., "stormwater" = "drainage", "foundation" = "footing")
3. Return matched=false if the photo shows something completely different from all defects
4. Use high confidence only if specific details match (location, type, extent)
5. Return ONLY the JSON, no other text."""
            
            escaped_prompt = prompt.replace("'", "''")
            
            sql = f"""
            SELECT AI_COMPLETE(
                '{self.AI_MODELS["summary"]}',
                '{escaped_prompt}',
                {{'max_tokens': 500}}
            ) as match_result
            """
            
            result = self.session.sql(sql).collect()
            
            if result and len(result) > 0:
                match_json = result[0]["MATCH_RESULT"]
                
                # Clean and parse JSON
                if isinstance(match_json, str):
                    match_json = match_json.strip().strip('```').strip('json').strip()
                    import json as json_lib
                    match_data = json_lib.loads(match_json)
                else:
                    match_data = match_json
                
                # If we have a high-confidence match, combine the information
                if match_data.get('matched') and match_data.get('confidence') in ['high', 'medium']:
                    defect_idx = match_data.get('defect_index')
                    if defect_idx is not None and 0 <= defect_idx < len(defects):
                        matched_defect = defects[defect_idx]
                        
                        # Combine visual caption with transcript defect code and description
                        combined_caption = (
                            f"{image_caption} "
                            f"This corresponds to REFERENCE defect {matched_defect.get('defect_code')}: "
                            f"{matched_defect.get('defect_found')}"
                        )
                        
                        logger.info(f"✅ Matched caption to defect {matched_defect.get('defect_code')} with {match_data.get('confidence')} confidence")
                        
                        return {
                            "matched": True,
                            "caption": combined_caption,
                            "defect_code": matched_defect.get('defect_code'),
                            "confidence": match_data.get('confidence'),
                            "original_caption": image_caption,
                            "defect_description": matched_defect.get('defect_found')
                        }
                
                # Low confidence or no match - use original caption
                logger.info(f"⚠️ No confident match found, using original caption")
                return {
                    "matched": False,
                    "caption": image_caption,
                    "defect_code": None
                }
            
        except Exception as e:
            logger.error(f"Caption matching failed: {e}")
        
        # Fallback to original caption
        return {
            "matched": False,
            "caption": image_caption,
            "defect_code": None
        }
    
    def insert_audit_record(self, inspection_data: dict, structured_summary: dict, audio_duration: float = None):
        """Operational audit persistence is excluded from this public edition."""
        return None

