"""
Improved Caption Generation with Defect Pattern Matching
Maps AI-generated descriptions to standardized technical captions
"""

import re
from typing import List, Optional

# Common defect patterns mapped to standard captions
DEFECT_PATTERNS = {
    # Bracing defects
    r'(ply|plywood).*brac.*(?:not|in|loose|unsecure)': 'Ply Bracing not secure',
    r'brac.*(?:not|in).*secure': 'Ply Bracing not secure',
    r'speed.*brace.*(?:not|incorrect|wrong|terminate|end)': 'Speed brace does not terminate at correct location',
    r'brace.*(?:terminate|termination|end).*(?:incorrect|wrong)': 'Speed brace does not terminate at correct location',
    
    # Window defects
    r'window.*(?:not|un|im).*pack': 'Window not packed',
    r'window.*gap.*(?:frame|wall)': 'Window not packed',
    r'window.*(?:shim|packing).*(?:missing|absent)': 'Window not packed',
    
    # Gas/Plumbing defects  
    r'gas.*(?:copper tail|copper|1m|one metre)': 'Gas with no 1m copper tail',
    r'copper tail.*(?:missing|absent|not|no)': 'Gas with no 1m copper tail',
    r'gas.*pipe.*(?:without|missing|no).*copper': 'Gas with no 1m copper tail',
    
    # Truss defects
    r'truss.*brac.*(?:not|dis).*continu': 'Truss bracing not continuous',
    r'roof.*brac.*(?:incomplete|discontinued)': 'Truss bracing not continuous',
    
    # Flashing defects
    r'flash.*(?:incorrect|wrong|improper|poor)': 'Flashing improperly installed',
    r'(?:no|missing|absent).*flash': 'Flashing missing',
    
    # Drainage defects
    r'drain.*(?:slope|grade|fall).*(?:incorrect|wrong|toward)': 'Site drainage slopes toward foundation',
    r'water.*(?:pond|pool).*foundation': 'Site drainage slopes toward foundation',
    
    # Foundation defects
    r'(?:base|bottom).*plate.*(?:not|un).*(?:anchor|secure|fix)': 'Bottom plate not secured',
    r'anchor.*(?:missing|loose|incorrect)': 'Anchor bolts not properly installed',
}

def map_caption_to_standard(ai_caption: str) -> Optional[str]:
    """
    Map AI-generated caption to standardized technical caption
    
    Args:
        ai_caption: Raw caption from AI model
        
    Returns:
        Standardized caption or None if no match
    """
    ai_lower = ai_caption.lower()
    
    for pattern, standard_caption in DEFECT_PATTERNS.items():
        if re.search(pattern, ai_lower, re.IGNORECASE):
            return standard_caption
    
    return None

def generate_improved_caption(ai_caption: str) -> str:
    """
    Generate improved caption - either mapped standard or cleaned AI caption
    
    Args:
        ai_caption: Raw caption from AI
        
    Returns:
        Improved caption
    """
    # Try to map to standard
    standard = map_caption_to_standard(ai_caption)
    if standard:
        return standard
    
    # Otherwise clean up AI caption
    # Remove verbose prefixes
    cleaned = ai_caption
    for prefix in ["The image shows", "This shows", "Visible is", "Caption:", "Defect:"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    
    # Remove trailing explanation
    if " - " in cleaned:
        cleaned = cleaned.split(" - ")[0]
    
    # Capitalize first word
    cleaned = cleaned[0].upper() + cleaned[1:] if cleaned else cleaned
    
    # Limit length
    words = cleaned.split()
    if len(words) > 10:
        cleaned = " ".join(words[:10]) + "..."
    
    return cleaned

def get_enhanced_caption_prompt() -> str:
    """
    Get optimized prompt for caption generation (without defect codes)
    
    Returns:
        Prompt string
    """
    return """Analyze this construction defect photograph.

Common defects to look for:
- Ply Bracing not secure (loose, not nailed properly)
- Window not packed (missing shims/packing, gaps around frame)
- Gas pipe without 1m copper tail (multi-layer pipe direct to appliance)
- Speed brace incorrect termination (doesn't reach top plate)
- Truss bracing not continuous (gaps, disconnected)
- Flashing improperly installed (incorrect overlap, unsealed)
- Site drainage issues (slopes toward foundation, ponding)
- Anchor bolts missing or loose (base plate not secured)

Identify the specific defect visible in this image. Respond with a brief technical description (under 10 words). Focus on what component is defective and how, WITHOUT using defect code numbers."""

# Example usage in snowflake_service.py:
"""
def analyze_image_content_enhanced(self, stage_filename: str, context: str = "") -> str:
    # Use enhanced prompt
    prompt = get_enhanced_caption_prompt()
    
    if context:
        prompt += f"\\n\\nInspection context: {context}"
    
    # Get AI caption
    ai_caption = self._generate_ai_caption(stage_filename, prompt)
    
    # Map to standard caption
    improved_caption = generate_improved_caption(ai_caption)
    
    return improved_caption
"""
