"""
FastAPI Backend for Field Notes Studio Report Generator
Modern API with audio transcription and report generation
"""
import os
import io
import json
import tempfile
from datetime import datetime
from typing import List, Optional, Union
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
import jwt

from api.snowflake_service import SnowflakeService
from api.report_generator import generate_inspection_report, format_structured_inspection_data
from api.audio_validator import validate_audio_file, format_validation_error_for_user
from PIL import Image

# Configuration
# Upload limits (what the API will accept)
MAX_AUDIO_SIZE_MB = 50    # 50MB max per audio file
MAX_IMAGE_SIZE_MB = 50    # 50MB max per uploaded image
MAX_TOTAL_REQUEST_MB = 200 # 200MB max for entire request

# External AI/image-analysis service limit (cannot be increased from application side)
EXTERNAL_IMAGE_LIMIT_MB = 10  # Snowflake/OpenAI external function limit for single file

def sanitize_filename(text: str) -> str:
    """
    Sanitize text for use in filename
    - Remove special characters
    - Replace spaces with underscores
    - Limit length
    """
    import re
    # Remove special characters, keep alphanumeric, spaces, hyphens
    text = re.sub(r'[^\w\s-]', '', text)
    # Replace spaces with underscores
    text = text.replace(' ', '_')
    # Remove multiple consecutive underscores
    text = re.sub(r'_+', '_', text)
    # Limit length
    return text[:50].strip('_')

def format_inspection_data_simple(inspection_data):
    """
    Simple text formatter for inspection data that doesn't depend on docx library.
    Formats audit items in the template format: List of Audit Items with defect item, code, non-compliance, and standard.
    """
    if not isinstance(inspection_data, dict):
        return str(inspection_data)
    
    lines = []
    
    # List of Audit Items - format exactly as requested for template
    if inspection_data.get('defects') or inspection_data.get('audit_items'):
        lines.append("List of Audit Items")
        lines.append("=" * 80)
        lines.append("")
        
        # Prefer structured defects; fall back to legacy audit_items if needed
        items = inspection_data.get('defects') or inspection_data.get('audit_items', [])
        
        for i, item in enumerate(items, 1):
            # Defect item title
            defect_title = item.get('defect_found') or item.get('title', 'Unnamed Defect')
            lines.append(f"{i}. DEFECT ITEM: {defect_title}")
            
            # Defect code
            defect_code = item.get('defect_code', 'N/A')
            lines.append(f"   Defect Code: {defect_code}")
            
            # Category/subcategory context
            category = item.get('category')
            subcategory = item.get('subcategory')
            if category or subcategory:
                if category and subcategory:
                    lines.append(f"   Category: {category} > {subcategory}")
                else:
                    lines.append(f"   Category: {category or subcategory}")
            
            # Non compliance explanation
            non_compliance = item.get('non_compliance') or item.get('description', 'No details available')
            lines.append(f"   Non-Compliance: {non_compliance}")
            
            # Standard reference
            standard = item.get('standard', 'N/A')
            if standard and standard != 'N/A':
                lines.append(f"   Standard: {standard}")
            
            # Add separator between items
            lines.append("")
            if i < len(items):
                lines.append("-" * 80)
                lines.append("")
    
    return "\n".join(lines)

# Initialize FastAPI app
app = FastAPI(
    title="Field Notes Studio API",
    description="AI-assisted audio and photo reports with human review",
    version="1.0.0"
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Improved visibility when FastAPI rejects incoming form data before hitting our route handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(status_code=422, content={'detail': 'Invalid request fields. Check the API schema.'})


@app.get('/api/csrf-token')
async def get_csrf_token(response: JSONResponse):
    """Return a CSRF token and set it in a cookie (double-submit cookie pattern).

    Clients should call this endpoint early (e.g. on app load) and then include
    the token value in the `X-XSRF-TOKEN` header for subsequent modifying requests.
    """
    import secrets
    token = secrets.token_urlsafe(32)
    # Set a non-HttpOnly cookie so frontends can read it for header injection
    # Use secure and samesite attributes in production
    secure = os.getenv('ENV', '').lower() == 'production'
    response = JSONResponse(content={'csrf': token})
    response.set_cookie('XSRF-TOKEN', token, samesite='Lax', secure=secure, httponly=False)
    return response


@app.middleware('http')
async def csrf_middleware(request: Request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        import secrets
        cookie = request.cookies.get('XSRF-TOKEN', '')
        header = request.headers.get('X-XSRF-TOKEN', '')
        if not cookie or not header or not secrets.compare_digest(cookie, header):
            return JSONResponse(status_code=403, content={'detail': 'Missing or invalid CSRF token'})
    return await call_next(request)

# Initialize services (lazy loading)
snowflake_service = None

def get_snowflake_service():
    """Get or create Snowflake service instance"""
    global snowflake_service
    if snowflake_service is None:
        try:
            snowflake_service = SnowflakeService()
        except Exception as e:
            pass  # Do not log uploaded content or personal data.
            raise HTTPException(status_code=503, detail=f"Snowflake service unavailable: {str(e)}")
    return snowflake_service

# Pydantic models
class InspectionRequest(BaseModel):
    inspector_name: str
    contractor_name: str
    site_address: str
    other_contractors: Optional[str] = None
    inspection_date: Optional[str] = None

class TranscriptionResponse(BaseModel):
    status: str
    transcript: str
    summary: Union[str, dict]
    audio_filename: str
    timestamp: str

class HealthResponse(BaseModel):
    status: str
    message: str
    snowflake_connected: bool

# Routes
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Field Notes Studio API",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        service = get_snowflake_service()
        service.test_connection()
        
        return HealthResponse(
            status="healthy",
            message="All systems operational",
            snowflake_connected=True
        )
    except Exception as e:
        return HealthResponse(
            status="degraded",
            message=f"Service running but Snowflake unavailable: {str(e)}",
            snowflake_connected=False
        )



class TelemetryEvent(BaseModel):
    app_name: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_role: Optional[str] = None
    warehouse: Optional[str] = None
    token_usage_total: Optional[float] = None
    environment: Optional[str] = None
    app_version: Optional[str] = None
    event_name: Optional[str] = None
    event_props: Optional[dict] = None




@app.post("/api/upload-audio")
async def upload_audio(audio_file: UploadFile = File(...)):
    """
    Upload audio file to Snowflake stage
    """
    try:
        service = get_snowflake_service()
        
        # Read file to check size
        contents = await audio_file.read()
        file_size_mb = len(contents) / (1024 * 1024)
        
        # Validate file size
        if file_size_mb > MAX_AUDIO_SIZE_MB:
            raise HTTPException(
                status_code=400, 
                detail=f"Audio file too large: {file_size_mb:.1f}MB (max {MAX_AUDIO_SIZE_MB}MB)"
            )
        
        # Validate file type
        allowed_types = ["audio/mpeg", "audio/wav", "audio/flac", "audio/ogg", "audio/webm", "audio/m4a", "audio/mp4"]
        if audio_file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Invalid audio file type: {audio_file.content_type}")
        
        # Validate audio quality and format (corruption, silence, duration, etc.)
        is_valid, error_message, audio_props = validate_audio_file(contents, audio_file.filename)
        if not is_valid:
            error_detail = format_validation_error_for_user(error_message, audio_file.filename)
            raise HTTPException(status_code=400, detail=error_detail)
        
        # Log audio properties for debugging
        pass  # Do not log uploaded content or personal data.
        
        # Reset file pointer after reading
        await audio_file.seek(0)
        
        # Upload to stage
        stage_filename = service.upload_to_stage(audio_file.file, audio_file.filename, "audio")
        
        return {
            "status": "success",
            "stage_filename": stage_filename,
            "original_filename": audio_file.filename,
            "audio_duration": audio_props.get('duration', 0)  # Return duration for frontend display
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/transcribe")
async def transcribe_audio(
    stage_filename: str = Form(...)
):
    """
    Transcribe audio file using Snowflake AI_TRANSCRIBE
    
    Args:
        stage_filename: Audio file in stage
    """
    try:
        service = get_snowflake_service()
        
        # Use Snowflake AI transcription (only option in production)
        transcript = service.transcribe_audio(stage_filename)
        
        # Generate summary
        structured_summary = service.summarize_transcript(transcript)
        
        # Convert structured summary to formatted string for frontend display
        if isinstance(structured_summary, dict):
            display_summary = format_structured_inspection_data(structured_summary)
            # Extract defects for separate review
            defects_list = structured_summary.get('defects', [])
        else:
            display_summary = structured_summary
            defects_list = []
        
        return {
            "status": "success",
            "transcript": transcript,
            "summary": display_summary,  # Formatted string for frontend
            "defects": defects_list,  # NEW: Structured defects for review modal
            "audio_filename": stage_filename,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        error_message = str(e)
        
        # Check if this is an audio quality/hallucination error
        if "hallucinated phrase" in error_message.lower() or "poor audio quality" in error_message.lower():
            raise HTTPException(
                status_code=422,  # Unprocessable Entity
                detail={
                    "error": "audio_quality_issue",
                    "message": error_message,
                    "suggestion": "You can either:\n1. Re-record the audio with better quality\n2. Manually type what you said instead",
                    "can_retry": True,
                    "can_manual_input": True,  # NEW: Allow manual transcription
                    "stage_filename": stage_filename  # Keep filename for potential retry
                }
            )
        else:
            # Other transcription errors
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "transcription_failed",
                    "message": error_message,
                    "can_retry": False
                }
            )

@app.post("/api/manual-transcript")
async def submit_manual_transcript(
    manual_transcript: str = Form(...),
    stage_filename: str = Form(...)
):
    """
    Submit manually typed transcript when audio transcription fails
    Allows users to type what they said instead of re-recording
    
    Args:
        manual_transcript: User-typed transcript text
        stage_filename: Original audio stage filename (for audit trail)
    """
    try:
        service = get_snowflake_service()
        
        # Validate manual transcript is not empty
        if not manual_transcript or len(manual_transcript.strip()) < 10:
            raise HTTPException(
                status_code=400,
                detail="Manual transcript too short. Please provide at least 10 characters describing the defects."
            )
        
        # Generate summary from manual transcript (same as audio transcript)
        structured_summary = service.summarize_transcript(manual_transcript)
        
        # Convert structured summary to formatted string for frontend display
        if isinstance(structured_summary, dict):
            display_summary = format_structured_inspection_data(structured_summary)
        else:
            display_summary = structured_summary
        
        return TranscriptionResponse(
            status="success",
            transcript=manual_transcript,
            summary=display_summary,
            audio_filename=f"{stage_filename} (manual)",  # Mark as manual entry
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "manual_transcript_failed",
                "message": f"Failed to process manual transcript: {str(e)}",
                "can_retry": False
            }
        )

@app.post("/api/upload-conversation")
async def upload_conversation(audio_file: UploadFile = File(...)):
    """
    Upload review conversation audio file to Snowflake stage
    """
    try:
        service = get_snowflake_service()
        
        # Read file to check size
        contents = await audio_file.read()
        file_size_mb = len(contents) / (1024 * 1024)
        
        # Validate file size
        if file_size_mb > MAX_AUDIO_SIZE_MB:
            raise HTTPException(
                status_code=400, 
                detail=f"Conversation audio file too large: {file_size_mb:.1f}MB (max {MAX_AUDIO_SIZE_MB}MB)"
            )
        
        # Validate file type
        allowed_types = ["audio/mpeg", "audio/wav", "audio/flac", "audio/ogg", "audio/webm", "audio/m4a", "audio/mp4"]
        if audio_file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Invalid conversation audio file type: {audio_file.content_type}")
        
        # Validate audio quality and format (corruption, silence, duration, etc.)
        is_valid, error_message, audio_props = validate_audio_file(contents, audio_file.filename)
        if not is_valid:
            error_detail = format_validation_error_for_user(error_message, audio_file.filename)
            raise HTTPException(status_code=400, detail=error_detail)
        
        # Log audio properties for debugging
        pass  # Do not log uploaded content or personal data.
        
        # Reset file pointer after reading
        await audio_file.seek(0)
        
        # Upload to stage
        stage_filename = service.upload_to_stage(audio_file.file, audio_file.filename, "audio")
        
        return {
            "status": "success",
            "stage_filename": stage_filename,
            "original_filename": audio_file.filename,
            "audio_duration": audio_props.get('duration', 0)  # Return duration for frontend display
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/transcribe-conversation")
async def transcribe_conversation(
    stage_filename: str = Form(...)
):
    """
    Transcribe review conversation audio using Snowflake AI_TRANSCRIBE
    Returns only transcript (no AI analysis/summary)
    
    Args:
        stage_filename: Audio file in stage
    """
    try:
        service = get_snowflake_service()
        
        # Use Snowflake AI transcription (only option in production)
        transcript = service.transcribe_audio(stage_filename)
        
        return {
            "status": "success",
            "transcript": transcript,
            "audio_filename": stage_filename,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        error_message = str(e)
        
        # Check if this is an audio quality/hallucination error
        if "hallucinated phrase" in error_message.lower() or "poor audio quality" in error_message.lower():
            raise HTTPException(
                status_code=422,  # Unprocessable Entity
                detail={
                    "error": "audio_quality_issue",
                    "message": error_message,
                    "suggestion": "You can either:\n1. Re-record the conversation with better quality\n2. Manually type the conversation instead",
                    "can_retry": True,
                    "can_manual_input": True,  # NEW: Allow manual transcription
                    "stage_filename": stage_filename
                }
            )
        else:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "transcription_failed",
                    "message": error_message,
                    "can_retry": False
                }
            )

@app.post("/api/upload-general-photo")
async def upload_general_photo(image_file: UploadFile = File(...)):
    """
    Upload general site photo to Snowflake stage (no AI processing)
    """
    try:
        service = get_snowflake_service()
        
        # Read file to check size
        contents = await image_file.read()
        file_size_mb = len(contents) / (1024 * 1024)

        # Validate file type
        allowed_types = ["image/jpeg", "image/png", "image/jpg"]
        if image_file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Invalid image file type: {image_file.content_type}")

        # Enforce upload cap (no need to compress for AI since these won't be analyzed)
        if file_size_mb > MAX_IMAGE_SIZE_MB:
            raise HTTPException(
                status_code=400,
                detail=f"Image file too large: {file_size_mb:.1f}MB (max {MAX_IMAGE_SIZE_MB}MB). Please compress the image before uploading."
            )

        # Reset file pointer after reading
        await image_file.seek(0)

        # Upload to stage (no AI processing needed for general photos)
        stage_filename = service.upload_to_stage(image_file.file, image_file.filename, "image")
        
        return {
            "status": "success",
            "stage_filename": stage_filename,
            "original_filename": image_file.filename
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload-image")
async def upload_image(image_file: UploadFile = File(...)):
    """
    Upload image file to Snowflake stage
    """
    try:
        service = get_snowflake_service()
        
        # Read file to check size
        contents = await image_file.read()
        file_size_mb = len(contents) / (1024 * 1024)

        # Validate file type
        allowed_types = ["image/jpeg", "image/png", "image/jpg"]
        if image_file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Invalid image file type: {image_file.content_type}")

        # Enforce a hard upload cap
        if file_size_mb > MAX_IMAGE_SIZE_MB:
            raise HTTPException(
                status_code=400,
                detail=f"Image file too large: {file_size_mb:.1f}MB (max {MAX_IMAGE_SIZE_MB}MB). Please compress the image before uploading."
            )

        # If file will exceed the external analysis limit, try to compress it automatically
        if file_size_mb > EXTERNAL_IMAGE_LIMIT_MB:
            try:
                buf = io.BytesIO(contents)
                img = Image.open(buf)
                img_rgb = img.convert("RGB")

                # Try progressively lower quality settings to reach the external limit
                target_bytes = int(EXTERNAL_IMAGE_LIMIT_MB * 1024 * 1024)
                quality = 85
                compressed = io.BytesIO()
                img_rgb.save(compressed, format='JPEG', quality=quality, optimize=True)

                while compressed.getbuffer().nbytes > target_bytes and quality > 20:
                    quality -= 10
                    compressed = io.BytesIO()
                    img_rgb.save(compressed, format='JPEG', quality=quality, optimize=True)

                if compressed.getbuffer().nbytes <= target_bytes:
                    # Upload compressed image via a temporary file
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                    try:
                        tmp.write(compressed.getvalue())
                        tmp.flush()
                        tmp.seek(0)
                        with open(tmp.name, 'rb') as fobj:
                            stage_filename = service.upload_to_stage(fobj, image_file.filename.rsplit('.', 1)[0] + '.jpg', "image")
                    finally:
                        tmp.close()
                        try:
                            os.unlink(tmp.name)
                        except Exception:
                            pass
                    return {
                        "status": "success",
                        "stage_filename": stage_filename,
                        "original_filename": image_file.filename,
                        "note": f"Image was compressed to fit external analysis limit ({EXTERNAL_IMAGE_LIMIT_MB}MB)"
                    }
                else:
                    # Could not compress sufficiently
                    raise HTTPException(status_code=400, detail=f"Image too large for automatic compression to {EXTERNAL_IMAGE_LIMIT_MB}MB. Please reduce the image size and try again.")
            except HTTPException:
                raise
            except Exception as comp_err:
                # Compression failed - ask user to manually compress
                raise HTTPException(status_code=400, detail=f"Failed to compress image: {comp_err}. Please reduce the image size below {EXTERNAL_IMAGE_LIMIT_MB}MB and try again.")

        # Reset file pointer after reading (file was not modified)
        await image_file.seek(0)

        # Upload to stage (original image already within acceptable upload limit and external limit)
        stage_filename = service.upload_to_stage(image_file.file, image_file.filename, "image")
        
        return {
            "status": "success",
            "stage_filename": stage_filename,
            "original_filename": image_file.filename
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate-report")
async def generate_report(
    inspector_name: str = Form(...),
    contractor_name: str = Form(...),
    site_address: str = Form(...),
    other_contractors: str = Form(None),
    inspection_date: str = Form(None),
    transcript: Optional[str] = Form(None),
    summary: Optional[str] = Form(None),
    audio_filename: Optional[str] = Form(None),
    main_site_image: str = Form(None),
    defect_images: str = Form(None),  # JSON string of array (DEPRECATED - use defects_with_photos)
    defects_with_photos: str = Form(None),  # NEW: JSON string of array with defect details + photos
    conversation_transcript: str = Form(None),  # NEW: Builder-inspector conversation
    general_photos: str = Form(None),  # NEW: General site photos (JSON string of array)
    is_compliant: bool = Form(False)  # NEW: Site compliance flag
):
    """
    Generate inspection report Word document
    
    New workflow: defects_with_photos contains array of:
    {
        defect_code, category, subcategory, standard, 
        defect_found, non_compliance, evidence_quote,
        caption, photos: [stage_filenames]
    }
    """
    try:
        # Normalize required string fields so missing form keys don't trigger a 422
        transcript = transcript or ""
        summary = summary or ""
        audio_filename = audio_filename or ""

        if not is_compliant and not transcript.strip():
            raise HTTPException(status_code=400, detail="Transcript missing for non-compliant site. Please rerun transcription before generating the report.")

        # Parse arrays from JSON strings
        defect_images_list = []
        defects_with_photos_list = []
        
        # NEW: Check if using new defects_with_photos format
        if defects_with_photos:
            defects_with_photos_list = json.loads(defects_with_photos)
            pass  # Do not log uploaded content or personal data.
        elif defect_images:
            # LEGACY: Old workflow with separate defect_images
            defect_images_list = json.loads(defect_images)
            pass  # Do not log uploaded content or personal data.
        
        general_photos_list = []
        if general_photos:
            general_photos_list = json.loads(general_photos)
        
        service = get_snowflake_service()
        
        # If site is compliant, skip AI analysis and generate simple report
        if is_compliant:
            pass  # Do not log uploaded content or personal data.
            
            inspection_data = {
                "inspector_name": inspector_name,
                "contractor_name": contractor_name,
                "site_address": site_address,
                "other_contractors": other_contractors or "N/A",
                "inspection_date": inspection_date or datetime.now().strftime("%Y-%m-%d"),
                "notes": "No observations were entered. This report does not establish compliance or certification.",
                "structured_summary": {"defects": []},  # Empty defects for compliant site
                "audio_file": audio_filename,
                "main_site_image": main_site_image,
                "defect_images": [],  # No defect images for compliant site
                "general_photos": general_photos_list,
                "conversation_transcript": conversation_transcript,
                "is_compliant": True
            }
            
            # Generate report
            report_bytes = generate_inspection_report(inspection_data)
            
            # Generate filename: buildersname_siteaddress_timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            sanitized_contractor = sanitize_filename(contractor_name)
            sanitized_address = sanitize_filename(site_address)
            report_filename = f"{sanitized_contractor}_{sanitized_address}_{timestamp}.docx"
            
            # Insert audit record for compliant site
            try:
                audit_id = service.insert_audit_record(
                    inspection_data=inspection_data,
                    structured_summary={"defects": []},  # No defects for compliant site
                    audio_duration=None
                )
                if audit_id:
                    pass  # Do not log uploaded content or personal data.
            except Exception as audit_error:
                pass  # Do not log uploaded content or personal data.
            
            return StreamingResponse(
                io.BytesIO(report_bytes),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={
                    "Content-Disposition": f"attachment; filename={report_filename}"
                }
            )
        
        # Non-compliant site - run full AI analysis
        pass  # Do not log uploaded content or personal data.
        
        # NEW WORKFLOW: Use defects_with_photos directly (no AI caption generation needed)
        if defects_with_photos_list:
            pass  # Do not log uploaded content or personal data.
            
            # Build structured summary from provided defects
            structured_summary_dict = {
                "defects": []
            }
            
            defect_images_with_captions = []
            
            for defect_item in defects_with_photos_list:
                # Add to structured summary for the defect table
                structured_summary_dict["defects"].append({
                    "defect_code": defect_item.get("defect_code"),
                    "category": defect_item.get("category"),
                    "subcategory": defect_item.get("subcategory"),
                    "standard": defect_item.get("standard"),
                    "defect_found": defect_item.get("defect_found"),
                    "non_compliance": defect_item.get("non_compliance"),
                    "evidence_quote": defect_item.get("evidence_quote")
                })
                
                # Add photos with defect description as caption
                caption = defect_item.get("caption") or defect_item.get("defect_found") or "Defect Photo"
                for photo_stage_file in defect_item.get("photos", []):
                    defect_images_with_captions.append({
                        'file': photo_stage_file,
                        'caption': caption
                    })
            
            # Format notes from structured summary
            formatted_notes = format_inspection_data_simple(structured_summary_dict)
            
            # Extract structured defect items for logging
            structured_defect_items = structured_summary_dict.get('defects', [])
            
        else:
            # LEGACY WORKFLOW: Generate structured summary from transcript + AI captions
            pass  # Do not log uploaded content or personal data.
            structured_summary = service.summarize_transcript(transcript)
        
            # Format the structured summary for display in notes
            pass  # Do not log uploaded content or personal data.
            pass  # Do not log uploaded content or personal data.
        
            if isinstance(structured_summary, dict):
                # Check if it's an error response
                if structured_summary.get('defects') and len(structured_summary['defects']) > 0:
                    first_defect = structured_summary['defects'][0]
                    if first_defect.get('title') == 'Analysis Error':
                        pass  # Do not log uploaded content or personal data.
                        pass  # Do not log uploaded content or personal data.
                
                try:
                    pass  # Do not log uploaded content or personal data.
                    formatted_notes = format_inspection_data_simple(structured_summary)
                    pass  # Do not log uploaded content or personal data.
                except Exception as e:
                    pass  # Do not log uploaded content or personal data.
                    import traceback
                    traceback.print_exc()
                    formatted_notes = str(structured_summary)
            elif isinstance(structured_summary, str):
                try:
                    pass  # Do not log uploaded content or personal data.
                    parsed = json.loads(structured_summary)
                    formatted_notes = format_inspection_data_simple(parsed)
                    structured_summary = parsed  # Update for later use
                    pass  # Do not log uploaded content or personal data.
                except json.JSONDecodeError as e:
                    pass  # Do not log uploaded content or personal data.
                    pass  # Do not log uploaded content or personal data.
                    formatted_notes = structured_summary
                except Exception as e:
                    pass  # Do not log uploaded content or personal data.
                    import traceback
                    traceback.print_exc()
                    formatted_notes = structured_summary
            else:
                pass  # Do not log uploaded content or personal data.
                formatted_notes = str(structured_summary)
            
            # Ensure structured_summary is a dict for downstream use
            structured_summary_dict = structured_summary
            if isinstance(structured_summary, str):
                try:
                    structured_summary_dict = json.loads(structured_summary)
                    pass  # Do not log uploaded content or personal data.
                except json.JSONDecodeError as e:
                    pass  # Do not log uploaded content or personal data.
                    pass  # Do not log uploaded content or personal data.
                    structured_summary_dict = {}
            elif not isinstance(structured_summary, dict):
                pass  # Do not log uploaded content or personal data.
                structured_summary_dict = {}

            structured_defect_items = []
            if structured_summary_dict and isinstance(structured_summary_dict, dict):
                structured_defect_items = structured_summary_dict.get('defects') or structured_summary_dict.get('audit_items') or []

            # Generate AI captions for each image based on transcript and structured defects
            defect_images_with_captions = []
            if defect_images_list and transcript:
                context_for_captions = formatted_notes if formatted_notes else str(structured_summary)

                if structured_defect_items:
                    defect_outline = "\n".join([
                        f"{idx + 1}. {item.get('defect_code', 'N/A')} - {item.get('defect_found', 'Unknown defect')}"
                        for idx, item in enumerate(structured_defect_items)
                    ])
                    context_for_captions = f"{context_for_captions}\n\nREFERENCE Defects:\n{defect_outline}"
                
                pass  # Do not log uploaded content or personal data.
                pass  # Do not log uploaded content or personal data.
                captions = service.generate_captions_for_images(defect_images_list, context_for_captions, structured_defect_items)
                
                for idx, image_file in enumerate(defect_images_list):
                    caption = captions[idx] if idx < len(captions) else f"Defect {idx + 1}"
                    defect_images_with_captions.append({
                        'file': image_file,
                        'caption': caption
                    })
                    pass  # Do not log uploaded content or personal data.
            else:
                defect_images_with_captions = [{'file': img, 'caption': ''} for img in defect_images_list]
        
        # Log structured defects for debugging
        if structured_summary_dict and isinstance(structured_summary_dict, dict):
            if structured_defect_items:
                pass  # Do not log uploaded content or personal data.
                for item in structured_defect_items:
                    pass  # Do not log uploaded content or personal data.
            else:
                pass  # Do not log uploaded content or personal data.
                pass  # Do not log uploaded content or personal data.
        
        # Prepare inspection data (use structured summary for proper report formatting)
        inspection_data = {
            "inspector_name": inspector_name,
            "contractor_name": contractor_name,
            "site_address": site_address,
            "other_contractors": other_contractors or "N/A",
            "inspection_date": inspection_date or datetime.now().strftime("%Y-%m-%d"),
            "notes": formatted_notes,  # Use formatted notes for display
            "structured_summary": structured_summary_dict,  # Pass parsed dict for table population
            "audio_file": audio_filename,
            "main_site_image": main_site_image,
            "defect_images": defect_images_with_captions,  # Now includes {file, caption}
            "defects_with_photos": defects_with_photos_list if defects_with_photos_list else None,  # NEW: Structured defects with photos
            "general_photos": general_photos_list,  # NEW: General photos without captions
            "conversation_transcript": conversation_transcript,  # NEW: Builder-inspector conversation
            "is_compliant": False  # Non-compliant site with defects
        }
        
        # Generate report
        try:
            report_bytes = generate_inspection_report(inspection_data)
        except Exception as report_error:
            pass  # Do not log uploaded content or personal data.
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Report generation failed: {str(report_error)}")
        
        # Generate filename: buildersname_siteaddress_timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sanitized_contractor = sanitize_filename(contractor_name)
        sanitized_address = sanitize_filename(site_address)
        report_filename = f"{sanitized_contractor}_{sanitized_address}_{timestamp}.docx"
        
        # Insert audit record after successful report generation
        try:
            # Extract audio duration if available
            audio_duration = None
            if audio_filename and transcript:
                # Try to get audio duration from filename or metadata (if stored)
                # For now, we'll skip it - can be added later if needed
                pass
            
            audit_id = service.insert_audit_record(
                inspection_data=inspection_data,
                structured_summary=structured_summary_dict,
                audio_duration=audio_duration
            )
            if audit_id:
                pass  # Do not log uploaded content or personal data.
            else:
                pass  # Do not log uploaded content or personal data.
        except Exception as audit_error:
            pass  # Do not log uploaded content or personal data.
            # Continue with report delivery even if audit fails
        
        # Return as downloadable file
        return StreamingResponse(
            io.BytesIO(report_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename={report_filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        pass  # Do not log uploaded content or personal data.
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
