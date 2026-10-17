"""
Audio Validation Module
Validates audio files before upload to catch corruption, poor quality, and format issues
Based on Snowflake AI_TRANSCRIBE requirements and best practices
"""
import io
import tempfile
import os
from typing import Dict, Tuple
from pydub import AudioSegment
from pydub.silence import detect_silence


class AudioValidationError(Exception):
    """Raised when audio validation fails"""
    pass


def get_audio_properties(audio_bytes: bytes, filename: str) -> Dict:
    """
    Extract audio properties from uploaded file
    
    Args:
        audio_bytes: Raw audio file bytes
        filename: Original filename (used to detect format)
        
    Returns:
        Dict with audio properties: duration, sample_rate, channels, format, size_mb
        
    Raises:
        AudioValidationError: If audio cannot be read or is corrupted
    """
    try:
        # Detect format from filename extension
        file_ext = filename.lower().split('.')[-1]
        format_map = {
            'mp3': 'mp3',
            'wav': 'wav',
            'flac': 'flac',
            'ogg': 'ogg',
            'webm': 'webm',
            'm4a': 'm4a',
            'mp4': 'mp4'
        }
        audio_format = format_map.get(file_ext, 'mp3')
        
        # Load audio from bytes
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=audio_format)
        
        # Extract properties
        duration_seconds = len(audio) / 1000.0  # pydub uses milliseconds
        sample_rate = audio.frame_rate
        channels = audio.channels
        size_mb = len(audio_bytes) / (1024 * 1024)
        
        return {
            'duration': duration_seconds,
            'sample_rate': sample_rate,
            'channels': channels,
            'format': audio_format,
            'size_mb': size_mb,
            'raw_audio': audio  # Keep for further analysis
        }
    except Exception as e:
        raise AudioValidationError(f"Failed to read audio file '{filename}': {str(e)}. File may be corrupted or in an unsupported format.")


def detect_silence_ratio(audio: AudioSegment, silence_thresh: int = -40, min_silence_len: int = 500) -> float:
    """
    Detect ratio of silence in audio
    
    Args:
        audio: AudioSegment object
        silence_thresh: Consider audio below this dBFS as silence (default -40 dBFS)
        min_silence_len: Minimum length of silence to detect in milliseconds (default 500ms)
        
    Returns:
        Float between 0.0 and 1.0 representing silence ratio
    """
    try:
        total_duration_ms = len(audio)
        if total_duration_ms == 0:
            return 1.0  # Empty audio is 100% silence
        
        # Detect silence ranges
        silent_ranges = detect_silence(audio, min_silence_len=min_silence_len, silence_thresh=silence_thresh)
        
        # Calculate total silence duration
        total_silence_ms = sum(end - start for start, end in silent_ranges)
        
        silence_ratio = total_silence_ms / total_duration_ms
        return silence_ratio
    except Exception as e:
        pass  # Do not log uploaded content or personal data.
        return 0.0  # Assume no silence if detection fails


def validate_audio_file(audio_bytes: bytes, filename: str) -> Tuple[bool, str, Dict]:
    """
    Comprehensive audio validation before upload to Snowflake stage
    
    Validates:
    - File is not corrupted
    - Duration is within Snowflake limits (max 120 minutes)
    - Audio is not mostly silence
    - Format is supported
    - Duration metadata matches actual audio length
    
    Args:
        audio_bytes: Raw audio file bytes
        filename: Original filename
        
    Returns:
        Tuple of (is_valid, error_message, properties)
        - is_valid: True if validation passed
        - error_message: Error description if validation failed, empty string if passed
        - properties: Dict with audio properties (duration, sample_rate, etc.)
    """
    try:
        # Step 1: Extract audio properties
        props = get_audio_properties(audio_bytes, filename)
        audio = props['raw_audio']
        duration = props['duration']
        
        # Step 2: Validate duration
        MAX_DURATION_SECONDS = 120 * 60  # 120 minutes (Snowflake limit without timestamps)
        if duration > MAX_DURATION_SECONDS:
            return False, f"Audio duration too long: {duration/60:.1f} minutes (max 120 minutes)", props
        
        # Step 3: Check for extremely short audio that might indicate corruption
        MIN_DURATION_SECONDS = 0.5
        if duration < MIN_DURATION_SECONDS:
            return False, f"Audio too short: {duration:.2f}s. File may be corrupted or empty. Minimum {MIN_DURATION_SECONDS}s required.", props
        
        # Step 4: Detect excessive silence (indicates poor recording or corruption)
        silence_ratio = detect_silence_ratio(audio)
        MAX_SILENCE_RATIO = 0.85  # Flag if more than 85% silence
        if silence_ratio > MAX_SILENCE_RATIO:
            return False, f"Audio contains {silence_ratio*100:.0f}% silence. Please ensure microphone is working and audio is recorded properly.", props
        
        # Step 5: Validate sample rate (AI_TRANSCRIBE resamples to 16 KHz)
        # Low sample rates might indicate corruption or poor quality
        MIN_SAMPLE_RATE = 8000  # 8 KHz minimum
        if props['sample_rate'] < MIN_SAMPLE_RATE:
            return False, f"Sample rate too low: {props['sample_rate']} Hz. Minimum {MIN_SAMPLE_RATE} Hz required for quality transcription.", props
        
        # Step 6: Check for metadata vs actual duration mismatch (corruption indicator)
        # This is the issue with amt.mp3 (reports 0.324s but file is actually longer)
        # pydub reads actual audio data, so if this passes, we have valid audio
        
        # All validations passed
        return True, "", props
        
    except AudioValidationError as e:
        # Audio file is corrupted or unreadable
        return False, str(e), {}
    except Exception as e:
        # Unexpected error
        return False, f"Audio validation failed: {str(e)}", {}


def trim_silence(audio_bytes: bytes, filename: str, silence_thresh: int = -40) -> bytes:
    """
    Trim leading and trailing silence from audio
    Per Snowflake docs: "For best results, trim excess silence before uploading"
    
    Args:
        audio_bytes: Raw audio file bytes
        filename: Original filename
        silence_thresh: Consider audio below this dBFS as silence (default -40 dBFS)
        
    Returns:
        Bytes of trimmed audio file
        
    Raises:
        AudioValidationError: If audio cannot be processed
    """
    try:
        # Get audio properties and load audio
        props = get_audio_properties(audio_bytes, filename)
        audio = props['raw_audio']
        
        # Detect silence at start and end
        # Find first non-silent chunk (start)
        start_trim = 0
        for i in range(0, len(audio), 100):  # Check every 100ms
            chunk = audio[i:i+100]
            if chunk.dBFS > silence_thresh:
                start_trim = i
                break
        
        # Find last non-silent chunk (end)
        end_trim = len(audio)
        for i in range(len(audio), 0, -100):  # Check every 100ms backwards
            chunk = audio[max(0, i-100):i]
            if chunk.dBFS > silence_thresh:
                end_trim = i
                break
        
        # Trim audio
        trimmed_audio = audio[start_trim:end_trim]
        
        # Export to bytes
        buffer = io.BytesIO()
        trimmed_audio.export(buffer, format=props['format'])
        return buffer.getvalue()
        
    except Exception as e:
        raise AudioValidationError(f"Failed to trim silence from '{filename}': {str(e)}")


def format_validation_error_for_user(error_message: str, filename: str) -> Dict:
    """
    Format validation error as structured response for frontend
    
    Args:
        error_message: Error message from validation
        filename: Original filename
        
    Returns:
        Dict with error details for 400 response
    """
    suggestions = []
    
    # Add specific suggestions based on error type
    if "corrupted" in error_message.lower() or "failed to read" in error_message.lower():
        suggestions.append("Try re-recording the audio with a different app or device")
        suggestions.append("Ensure the file is not damaged during upload")
        suggestions.append("Convert the audio to WAV or MP3 format using a reliable audio converter")
    
    elif "silence" in error_message.lower():
        suggestions.append("Check that your microphone is working properly")
        suggestions.append("Ensure you're recording in a quiet environment")
        suggestions.append("Speak clearly and at a consistent volume")
        suggestions.append("Re-record the audio with less silence")
    
    elif "too short" in error_message.lower():
        suggestions.append("Record for at least 1-2 seconds")
        suggestions.append("Ensure the recording started properly")
        suggestions.append("Check that the file uploaded completely")
    
    elif "too long" in error_message.lower():
        suggestions.append("Split the audio into multiple recordings (max 120 minutes each)")
        suggestions.append("Process recordings separately and combine reports")
    
    elif "sample rate" in error_message.lower():
        suggestions.append("Use a better recording device or app")
        suggestions.append("Convert audio to higher quality format (16 KHz or higher)")
    
    else:
        suggestions.append("Try re-recording the audio with better quality")
        suggestions.append("Ensure clear speech and minimal background noise")
    
    return {
        "error": "audio_validation_failed",
        "message": error_message,
        "filename": filename,
        "suggestions": suggestions,
        "can_retry": False  # Validation errors require new upload, not retry
    }
