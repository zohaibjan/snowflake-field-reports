import io
from datetime import datetime
import re
import pytz
import logging

logger = logging.getLogger(__name__)

# Word document generation imports
try:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.shared import OxmlElement, qn
    DOCX_AVAILABLE = True
    pass  # Do not log uploaded content or personal data.
except ImportError as e:
    DOCX_AVAILABLE = False
    Document = None
    pass  # Do not log uploaded content or personal data.
except Exception as e:
    DOCX_AVAILABLE = False
    Document = None
    pass  # Do not log uploaded content or personal data.


def build_defects_with_photos_content(defects_with_photos):
    """
    Build content structure for defects with photos inline (instead of separate photo section).
    Returns a marker that will be replaced with actual Word elements.
    
    Args:
        defects_with_photos: List of dicts with defect info + photos array
        
    Returns:
        String marker for replacement
    """
    # Return a special marker that will be processed later in insert_defects_with_photos_in_doc
    return "{{ DEFECTS_WITH_PHOTOS_INLINE }}"


def insert_defects_with_photos_in_doc(doc, defects_with_photos, marker_paragraph_idx=None, table=None, row=None, cell=None, paragraph_index=None):
    """
    Insert defects with photos inline at the marker location.
    Each defect gets its details + photos underneath.
    
    Args:
        doc: Word document object
        defects_with_photos: List of dicts with defect info + photos
        marker_paragraph_idx: Index where marker was found
    """
    from api.snowflake_service import SnowflakeService
    service = SnowflakeService()
    
    # Determine the marker paragraph object we should insert before
    if marker_paragraph_idx is not None:
        marker_para = doc.paragraphs[marker_paragraph_idx]
    elif cell is not None and paragraph_index is not None:
        marker_para = cell.paragraphs[paragraph_index]
    else:
        # Fallback: try to find a paragraph containing the inline marker
        marker_para = None
        for paragraph in doc.paragraphs:
            if 'DEFECTS_WITH_PHOTOS_INLINE' in paragraph.text:
                marker_para = paragraph
                break
        if marker_para is None:
            # As a last resort, append at end of document
            marker_para = doc.paragraphs[-1]
    
    for idx, defect in enumerate(defects_with_photos, 1):
        # Add defect heading
        p = marker_para.insert_paragraph_before()
        run = p.add_run(f"{idx}. DEFECT ITEM: {defect.get('defect_found', 'Unnamed Defect')}")
        run.bold = True
        run.font.size = Pt(12)
        
        # Add defect code
        p = marker_para.insert_paragraph_before()
        p.add_run(f"   Defect Code: {defect.get('defect_code', 'N/A')}")
        
        # Add category
        if defect.get('category'):
            p = marker_para.insert_paragraph_before()
            category_text = f"{defect['category']}"
            if defect.get('subcategory'):
                category_text += f" › {defect['subcategory']}"
            p.add_run(f"   Category: {category_text}")
        
        # Add non-compliance
        p = marker_para.insert_paragraph_before()
        p.add_run(f"   Non-Compliance: {defect.get('non_compliance', 'N/A')}")
        
        # Add standard
        if defect.get('standard') and defect['standard'] != 'N/A':
            p = marker_para.insert_paragraph_before()
            p.add_run(f"   Standard: {defect['standard']}")
        
        # Add blank line
        p = marker_para.insert_paragraph_before()
        p.add_run("")
        
        # Add photos if any
        photos = defect.get('photos', [])
        if photos:
            num_photos = len(photos)
            cols = min(3, num_photos)  # Max 3 photos per row
            rows = (num_photos + cols - 1) // cols
            
            # Create table for photos
            table = doc.add_table(rows=rows, cols=cols)
            table.alignment = WD_TABLE_ALIGNMENT.LEFT
            
            # Move table to correct position (before marker)
            table_element = table._element
            marker_para._element.addprevious(table_element)
            
            for photo_idx, photo_file in enumerate(photos):
                row_idx = photo_idx // cols
                col_idx = photo_idx % cols
                cell = table.rows[row_idx].cells[col_idx]
                
                try:
                    image_bytes = service.get_file_from_stage(photo_file)
                    paragraph = cell.paragraphs[0]
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run = paragraph.add_run()
                    image_stream = io.BytesIO(image_bytes)
                    run.add_picture(image_stream, width=Inches(2.0))
                    pass  # Do not log uploaded content or personal data.
                except Exception as e:
                    pass  # Do not log uploaded content or personal data.
                    cell.text = "[Image not available]"
            
            # Add spacing after photos
            p = marker_para.insert_paragraph_before()
            p.add_run("")
        
        # Add separator between defects
        if idx < len(defects_with_photos):
            p = marker_para.insert_paragraph_before()
            p.add_run("─" * 80)
            p = marker_para.insert_paragraph_before()
            p.add_run("")
    
    # Remove the marker paragraph
    marker_para._element.getparent().remove(marker_para._element)
    pass  # Do not log uploaded content or personal data.


def format_structured_inspection_data(inspection_data):
    """
    Format structured inspection data into properly formatted Word document text.
    
    Args:
        inspection_data: Dict with keys: defects, safety_concerns, recommended_actions, conclusion
        
    Returns:
        Formatted string ready for Word document
    """
    if not DOCX_AVAILABLE:
        return "Document formatting not available"
    
    # Defensive programming: handle case where inspection_data is a string instead of dict
    if isinstance(inspection_data, str):
        logger.warning(f"format_structured_inspection_data received string instead of dict: {inspection_data[:200]}...")
        # Convert string to basic dict structure
        inspection_data = {
            "defects": [{"title": "Data Processing Error", "description": "Received raw text instead of structured data", "standard": "N/A", "clause": "N/A", "requirement": "N/A"}],
            "safety_concerns": [{"category": "Data Processing Error", "description": "Could not process inspection data properly", "standards_violated": []}],
            "recommended_actions": [{"action": "Review Required", "details": "Manual review of inspection data needed", "standard": "N/A", "clause": "N/A"}],
            "conclusion": "Inspection data processing error occurred. Manual review required."
        }
    elif not isinstance(inspection_data, dict):
        logger.error(f"format_structured_inspection_data received invalid type: {type(inspection_data)}")
        inspection_data = {
            "defects": [{"title": "Data Type Error", "description": "Invalid data type received", "standard": "N/A", "clause": "N/A", "requirement": "N/A"}],
            "safety_concerns": [],
            "recommended_actions": [{"action": "Review Required", "details": "Data type validation failed", "standard": "N/A", "clause": "N/A"}],
            "conclusion": "Data processing error occurred."
        }
    
    lines = []
    
    # List of Audit Items - format exactly as requested
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


def format_notes_for_doc(inspection_data: dict) -> str:
    """
    Helper that composes the notes string that will be inserted into the document.
    This includes the main notes content plus an optional conversation_transcript section.

    Returns the final notes string (or a special inline marker when defects_with_photos are passed).
    """
    notes_content = inspection_data.get('notes', '') or ''

    # (NOTE) Do not append conversation here; conversation may be inserted into
    # a dedicated template placeholder `{{ CONVERSATION_WITH_BUILDER }}`.

    # If defects_with_photos provided, return the inline marker so the doc builder will process it
    if inspection_data.get('defects_with_photos'):
        return build_defects_with_photos_content(inspection_data.get('defects_with_photos'))

    return notes_content


def format_conversation_for_doc(inspection_data: dict) -> str:
    """
    Format the builder/inspector conversation in a consistent block suitable for
    inserting into a template placeholder (e.g. {{ CONVERSATION_WITH_BUILDER }}).
    Returns an empty string if no conversation is present.
    """
    conversation_transcript = inspection_data.get('conversation_transcript') or ''
    if not conversation_transcript.strip():
        return ''

    block = []
    block.append('CONVERSATION BETWEEN BUILDER AND INSPECTOR')
    block.append('\n')
    block.append(conversation_transcript)
    return '\n'.join(block)


def generate_inspection_report(inspection_data):
    """
    Generate a building inspection Word report for FIELD Inspection using template.
    
    Replaces Jinja2-style placeholders in template.docx:
        {{ Inspector_Details }}
        {{ Contractor_Name }}
        {{ Address }}
        {{ Notes }}
        {{ Other_Contractos }}
        {{ Main_Site_Image }}
        {% for photo in Site_Photos %} ... {{ photo.image }} ... {% endfor %}
    
    Args:
        inspection_data: dict with keys:
            - inspector_name: str
            - contractor_name: str
            - site_address: str
            - inspection_date: str
            - notes: str (contains transcript and summary)
            - audio_file: str (optional)
            - other_contractors: str (optional)
            - main_site_image: str (optional, stage filename)
            - defect_images: list (optional, stage filenames)
    
    Returns:
        bytes: Word document content
    """
    import os
    from pathlib import Path
    
    # Load template
    template_path = Path(__file__).parent.parent / 'templates' / 'template.docx'
    
    if not template_path.exists():
        # Fallback: create a basic document if template doesn't exist
        pass  # Do not log uploaded content or personal data.
        return generate_basic_report(inspection_data)
    
    # Load the template document
    doc = Document(str(template_path))
    
    # Debug: Find all placeholders in the template
    found_placeholders = set()
    for paragraph in doc.paragraphs:
        import re
        matches = re.findall(r'\{\{[^}]+\}\}', paragraph.text)
        found_placeholders.update(matches)
    
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    matches = re.findall(r'\{\{[^}]+\}\}', paragraph.text)
                    found_placeholders.update(matches)
    
    pass  # Do not log uploaded content or personal data.
    
    # Set all paragraphs to left alignment (remove justify)
    for paragraph in doc.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    
    # Set alignment in tables too
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    
    # Prepare replacement data
    # Compose notes (including optional conversation transcript or inline defects marker)
    formatted_notes = format_notes_for_doc(inspection_data)
    
    # NEW: If defects_with_photos is provided, build structured content with photos inline
    defects_with_photos = inspection_data.get('defects_with_photos')
    if defects_with_photos:
        pass  # Do not log uploaded content or personal data.
        formatted_notes = build_defects_with_photos_content(defects_with_photos)
    
    # Handle general site photos (separate from defect photos)
    general_photos = inspection_data.get('general_photos', [])
    pass  # Do not log uploaded content or personal data.
    
    # Generate inspection date in AEST timezone
    aest = pytz.timezone('Australia/Brisbane')  # Brisbane doesn't observe DST, always AEST
    inspection_date = datetime.now(aest).strftime("%d %B %Y")
    
    # Use canonical placeholder names (without surrounding braces) and perform regex replacements
    replacements = {
        'Inspector_Name': inspection_data.get('inspector_name', 'N/A'),
        'Inspector_Details': inspection_data.get('inspector_name', 'N/A'),  # Legacy
        'Contractor_Name': inspection_data.get('contractor_name', 'N/A'),
        'Site_Address': inspection_data.get('site_address', 'N/A'),
        'Address': inspection_data.get('site_address', 'N/A'),  # Legacy
        'Inspection_Date': inspection_date,
        'Notes': formatted_notes,
        'Other_Contractors': inspection_data.get('other_contractors', 'N/A'),
        'Other_Contractos': inspection_data.get('other_contractors', 'N/A')  # Legacy typo
    }

    # Add a dedicated conversation replacement so templates with {{ CONVERSATION_WITH_BUILDER }}
    # can receive the builder-inspector conversation if provided or be removed otherwise.
    conversation_transcript = inspection_data.get('conversation_transcript') or ''
    replacements['CONVERSATION_WITH_BUILDER'] = (f"CONVERSATION BETWEEN BUILDER AND INSPECTOR\n\n{conversation_transcript}" if conversation_transcript.strip() else '')
    
    pass  # Do not log uploaded content or personal data.
    pass  # Do not log uploaded content or personal data.
    pass  # Do not log uploaded content or personal data.
    pass  # Do not log uploaded content or personal data.
    pass  # Do not log uploaded content or personal data.
    
    import re
    # Helper: replace placeholder name tolerant to extra whitespace inside braces
    def replace_placeholder_in_text(text, name, value):
        pattern = re.compile(r'\{\{\s*' + re.escape(name) + r"\s*\}\}")
        return pattern.sub(str(value), text)

    # Replace text placeholders in all paragraphs
    for paragraph in doc.paragraphs:
        original_text = paragraph.text
        for placeholder_name, value in replacements.items():
            if re.search(r"\{\{\s*" + re.escape(placeholder_name) + r"\s*\}\}", paragraph.text):
                pass  # Do not log uploaded content or personal data.
                paragraph.text = replace_placeholder_in_text(paragraph.text, placeholder_name, value)
        
        # Center the address paragraph after replacement
        if '{{ Address }}' in original_text or '{{ Site_Address }}' in original_text:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pass  # Do not log uploaded content or personal data.
        
        # Replace main site image in paragraphs
        if re.search(r"\{\{\s*Main_Site_Image\s*\}\}", paragraph.text) or '{{ Main_Site_Image' in paragraph.text:
            if inspection_data.get('main_site_image'):
                replace_image_placeholder(paragraph, inspection_data['main_site_image'])
                # Center the image paragraph
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                # Remove placeholder if no image
                paragraph.text = paragraph.text.replace('{{ Main_Site_Image  }}', '')
    
    # Replace placeholders in tables using same regex tolerant method
    # (ensures {{ Inspector_Name  }} variants are matched)
    # Replace placeholders in tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    original_text = paragraph.text
                    # Replace text placeholders
                    for placeholder_name, value in replacements.items():
                        if re.search(r"\{\{\s*" + re.escape(placeholder_name) + r"\s*\}\}", paragraph.text):
                            paragraph.text = replace_placeholder_in_text(paragraph.text, placeholder_name, value)
                    
                    # Center the address paragraph in table cells after replacement
                    if '{{ Address }}' in original_text or '{{ Site_Address }}' in original_text:
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        pass  # Do not log uploaded content or personal data.
                    
                    # Replace main site image in table cells
                    if '{{ Main_Site_Image' in paragraph.text:
                        if inspection_data.get('main_site_image'):
                            replace_image_placeholder(paragraph, inspection_data['main_site_image'])
                            # Center the image paragraph
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        else:
                            # Remove placeholder if no image
                            paragraph.text = paragraph.text.replace('{{ Main_Site_Image  }}', '')
    
    # NEW: Process inline defects with photos if marker is found
    if defects_with_photos:
        pass  # Do not log uploaded content or personal data.
        marker_found = False
        # Try multiple candidate patterns to be resilient to template spacing/typos
        candidate_patterns = [
            '{{ DEFECTS_WITH_PHOTOS_INLINE }}',
            '{{DEFECTS_WITH_PHOTOS_INLINE}}',
            '{{ DEFECTS_WITH_PHOTOS_INLINE}}',
            '{{DEFECTS_WITH_PHOTOS_INLINE }}',
            'DEFECTS_WITH_PHOTOS_INLINE'
        ]
        # First search top-level paragraphs
        for idx, paragraph in enumerate(doc.paragraphs):
            para_text = paragraph.text.strip()
            for pat in candidate_patterns:
                if pat in para_text:
                    pass  # Do not log uploaded content or personal data.
                    insert_defects_with_photos_in_doc(doc, defects_with_photos, idx)
                    marker_found = True
                    break
            if marker_found:
                break
        # If not found in top-level paragraphs, search inside table cells' paragraphs
        if not marker_found:
            for table in doc.tables:
                for r_idx, row in enumerate(table.rows):
                    for c_idx, cell in enumerate(row.cells):
                        for p_idx, paragraph in enumerate(cell.paragraphs):
                            para_text = paragraph.text.strip()
                            for pat in candidate_patterns:
                                if pat in para_text:
                                    pass  # Do not log uploaded content or personal data.
                                    # We have cell paragraph; insert before this paragraph
                                    insert_defects_with_photos_in_doc(doc, defects_with_photos, None, table, row, cell, p_idx)
                                    marker_found = True
                                    break
                            if marker_found:
                                break
                        if marker_found:
                            break
                    if marker_found:
                        break
        
        if not marker_found:
            pass  # Do not log uploaded content or personal data.
            pass  # Do not log uploaded content or personal data.
            for idx, paragraph in enumerate(doc.paragraphs):
                if 'DEFECTS_WITH_PHOTOS_INLINE' in paragraph.text or 'DEFECTS' in paragraph.text or 'INLINE' in paragraph.text:
                    pass  # Do not log uploaded content or personal data.
        else:
            pass  # Do not log uploaded content or personal data.
    else:
        pass  # Do not log uploaded content or personal data.
    
    # Handle defect photos loop (legacy) — only if NOT using new defects_with_photos workflow
    if not defects_with_photos:
        handle_defect_photos_loop(doc, inspection_data.get('defect_images', []))
    
    # Handle general photos (no AI captions)
    handle_general_photos_loop(doc, inspection_data.get('general_photos', []))
    # Ensure conversation transcript (if any) is present in document.
    # Some templates may not include a {{ Notes }} placeholder; if so, append the notes/conversation at the end.
    try:
        conversation_transcript = inspection_data.get('conversation_transcript')
        if conversation_transcript and isinstance(conversation_transcript, str) and conversation_transcript.strip():
            # search all doc text for conversation marker or the transcript snippet
            all_text = '\n'.join([p.text for p in doc.paragraphs])
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            all_text += '\n' + p.text

            if conversation_transcript.strip() not in all_text and 'CONVERSATION BETWEEN BUILDER AND INSPECTOR' not in all_text:
                # Append a clear heading and the conversation to the end of the document
                doc.add_page_break()
                h = doc.add_paragraph('CONVERSATION BETWEEN BUILDER AND INSPECTOR')
                h.runs[0].bold = True
                doc.add_paragraph(conversation_transcript)
                pass  # Do not log uploaded content or personal data.
    except Exception as e:
        pass  # Do not log uploaded content or personal data.
    
    # FINAL CLEANUP: Remove any leftover Jinja for-loop markers for Site_Photos or Defect_Photos
    # Accept multiple loop naming variants and also support GENERAL_PHOTOS
    jinja_for_pattern = re.compile(r"\{\%\s*for\s+photo\s+in\s+(?:Site_Photos|GENERAL_PHOTOS|Defect_Photos)\s*\%\s*\}")
    jinja_endfor_pattern = re.compile(r"\{\%\s*endfor\s*\%\s*\}")
    to_remove = []
    for idx, paragraph in enumerate(doc.paragraphs):
        txt = paragraph.text.strip()
        if jinja_for_pattern.search(txt) or jinja_endfor_pattern.search(txt):
            to_remove.append(paragraph)
    # Also search inside tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    txt = paragraph.text.strip()
                    if jinja_for_pattern.search(txt) or jinja_endfor_pattern.search(txt):
                        to_remove.append(paragraph)
    for paragraph in to_remove:
        try:
            paragraph._element.getparent().remove(paragraph._element)
        except Exception as e:
            pass  # Do not log uploaded content or personal data.
    # Save to bytes
    # Final check: find any remaining unresolved placeholders in document
    unresolved = set()
    for paragraph in doc.paragraphs:
        matches = re.findall(r"\{\{[^}]+\}\}", paragraph.text)
        for m in matches:
            unresolved.add(m)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    matches = re.findall(r"\{\{[^}]+\}\}", paragraph.text)
                    for m in matches:
                        unresolved.add(m)
    if unresolved:
        pass  # Do not log uploaded content or personal data.

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def replace_image_placeholder(paragraph, stage_filename):
    """
    Replace {{ Main_Site_Image }} placeholder with actual image from stage.
    """
    from api.snowflake_service import SnowflakeService
    import os
    
    try:
        # Download image from stage
        service = SnowflakeService()
        pass  # Do not log uploaded content or personal data.
        image_bytes = service.get_file_from_stage(stage_filename)
        
        # Clear the paragraph text
        for run in paragraph.runs:
            run.text = ''
        
        # Add image to paragraph
        run = paragraph.add_run()
        image_stream = io.BytesIO(image_bytes)
        run.add_picture(image_stream, width=Inches(4.5))
        pass  # Do not log uploaded content or personal data.
        
        # Center the paragraph containing the image
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
    except Exception as e:
        # If image fails, just remove placeholder
        pass  # Do not log uploaded content or personal data.
        import re
        paragraph.text = re.sub(r"\{\{\s*Main_Site_Image\s*\}\}", '[Image not available]', paragraph.text)


def handle_defect_photos_loop(doc, defect_images_data):
    if not defect_images_data:
        return
    """
    Handle the {% for photo in Site_Photos %} ... {% endfor %} loop.
    Creates a 3-column table layout with images and captions.
    
    Args:
        doc: Word document object
        defect_images_data: List of dict with {'file': stage_file, 'caption': caption_text}
    """
    from api.snowflake_service import SnowflakeService
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    
    # Create Snowflake service at the start (needed in both code paths)
    service = SnowflakeService()
    
    # Find the loop markers in paragraphs (defect-specific loop, named Defect_Photos)
    loop_start_idx = None
    loop_end_idx = None
    
    for idx, paragraph in enumerate(doc.paragraphs):
        if re.search(r"\{\%\s*for\s+photo\s+in\s+Defect_Photos\s*\%\s*\}", paragraph.text):
            loop_start_idx = idx
        elif re.search(r"\{\%\s*endfor\s*\%\s*\}", paragraph.text):
            loop_end_idx = idx
    
    if loop_start_idx is None or loop_end_idx is None:
        pass  # Do not log uploaded content or personal data.
        pass  # Do not log uploaded content or personal data.
        images_per_row = 3
        num_images = len(defect_images_data)
        if num_images == 0:
            return
        
        num_rows = (num_images + images_per_row - 1) // images_per_row
        
        # Create table: 2 rows per image row (image + caption)
        table = doc.add_table(rows=num_rows * 2, cols=images_per_row)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        
        # Populate table
        current_image_idx = 0
        for row_idx in range(num_rows):
            image_row_idx = row_idx * 2
            caption_row_idx = row_idx * 2 + 1
            for col_idx in range(images_per_row):
                if current_image_idx >= num_images:
                    break
                item = defect_images_data[current_image_idx]
                image_file = item.get('file')
                caption_text = item.get('caption', '')
                try:
                    image_bytes = service.get_file_from_stage(image_file)
                    image_cell = table.rows[image_row_idx].cells[col_idx]
                    image_paragraph = image_cell.paragraphs[0]
                    image_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run = image_paragraph.add_run()
                    image_stream = io.BytesIO(image_bytes)
                    run.add_picture(image_stream, width=Inches(2.0))
                    pass  # Do not log uploaded content or personal data.
                    # Add caption below
                    caption_cell = table.rows[caption_row_idx].cells[col_idx]
                    caption_paragraph = caption_cell.paragraphs[0]
                    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    caption_run = caption_paragraph.add_run(caption_text)
                    caption_run.font.size = Pt(8)
                    caption_run.italic = True
                except Exception as e:
                    pass  # Do not log uploaded content or personal data.
                    image_cell = table.rows[image_row_idx].cells[col_idx]
                    image_cell.text = "[Image not available]"
                current_image_idx += 1
        return
    
    # Loop markers found - process normally
    pass  # Do not log uploaded content or personal data.
    
    # Debug: log all filenames
    filenames = [item.get('file') for item in defect_images_data]
    pass  # Do not log uploaded content or personal data.
    pass  # Do not log uploaded content or personal data.
    
    # Since filenames now include timestamps and original names, they should be unique
    # No need for deduplication - show all uploaded images
    image_caption_pairs = []
    for item in defect_images_data:
        image_file = item.get('file')
        caption_text = item.get('caption', '')
        if image_file:  # Only add if filename exists
            image_caption_pairs.append((image_file, caption_text))
    
    pass  # Do not log uploaded content or personal data.
    
    images_per_row = 3
    num_images = len(image_caption_pairs)
    if num_images == 0:
        pass  # Do not log uploaded content or personal data.
        return
    
    num_rows = (num_images + images_per_row - 1) // images_per_row
    
    # Create table and insert it at the loop position
    table = doc.add_table(rows=num_rows * 2, cols=images_per_row)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Move the table to the correct position (after the loop start paragraph)
    table_element = table._element
    loop_start_paragraph = doc.paragraphs[loop_start_idx]
    loop_start_paragraph._element.addnext(table_element)
    
    # Now remove the loop paragraphs
    for i in range(loop_end_idx, loop_start_idx - 1, -1):
        if i < len(doc.paragraphs):
            p = doc.paragraphs[i]
            # Don't remove the table we just inserted
            if p._element != table_element:
                p._element.getparent().remove(p._element)
    current_image_idx = 0
    for row_idx in range(num_rows):
        image_row_idx = row_idx * 2
        caption_row_idx = row_idx * 2 + 1
        for col_idx in range(images_per_row):
            if current_image_idx >= num_images:
                break
            image_file, caption_text = image_caption_pairs[current_image_idx]
            try:
                image_bytes = service.get_file_from_stage(image_file)
                image_cell = table.rows[image_row_idx].cells[col_idx]
                image_paragraph = image_cell.paragraphs[0]
                image_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = image_paragraph.add_run()
                image_stream = io.BytesIO(image_bytes)
                run.add_picture(image_stream, width=Inches(2.0))
                # Add caption below
                caption_cell = table.rows[caption_row_idx].cells[col_idx]
                caption_paragraph = caption_cell.paragraphs[0]
                caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                caption_run = caption_paragraph.add_run(caption_text)
                caption_run.font.size = Pt(8)
                caption_run.font.italic = True
            except Exception as e:
                pass  # Do not log uploaded content or personal data.
                image_cell = table.rows[image_row_idx].cells[col_idx]
                image_cell.text = "[Image not available]"
            current_image_idx += 1


def handle_general_photos_loop(doc, general_photos_list):
    if not general_photos_list:
        return
    """
    Handle {% for photo in Site_Photos %} loop OR table with [Image not available] placeholders.
    Supports both loop-based and table-based templates for general site photos.
    
    Args:
        doc: Word document object
        general_photos_list: List of stage filenames (strings)
    """
    from api.snowflake_service import SnowflakeService
    from docx.shared import Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    import docx
    
    pass  # Do not log uploaded content or personal data.
    # Debug: show the exact list contents so we can diagnose single-photo issues
    try:
        pass  # Do not log uploaded content or personal data.
        for i, item in enumerate(general_photos_list):
            pass  # Do not log uploaded content or personal data.
    except Exception as e:
        pass  # Do not log uploaded content or personal data.
    
    # Create Snowflake service
    service = SnowflakeService()
    
    # Method 1: Try to find and process loop markers first (search paragraphs and table cells)
    loop_start = None
    loop_end = None
    import re

    # Search top-level paragraphs
    for idx, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text.strip()
        if re.search(r"\{\%\s*for\s+photo\s+in\s+(?:Site_Photos|GENERAL_PHOTOS)\s*\%\s*\}", text):
            loop_start = { 'type': 'para', 'idx': idx }
            pass  # Do not log uploaded content or personal data.
        elif re.search(r"\{\%\s*endfor\s*\%\s*\}", text) and loop_start is not None and loop_start.get('type') == 'para':
            loop_end = { 'type': 'para', 'idx': idx }
            pass  # Do not log uploaded content or personal data.
            break

    # If not found at top-level, search inside table cells
    if loop_start is None or loop_end is None:
        for t_idx, table in enumerate(doc.tables):
            for r_idx, row in enumerate(table.rows):
                for c_idx, cell in enumerate(row.cells):
                    for p_idx, paragraph in enumerate(cell.paragraphs):
                        text = paragraph.text.strip()
                        if re.search(r"\{\%\s*for\s+photo\s+in\s+(?:Site_Photos|GENERAL_PHOTOS)\s*\%\s*\}", text):
                            # Record the cell location
                            loop_start = {
                                'type': 'cell', 'table_idx': t_idx, 'row_idx': r_idx, 'cell_idx': c_idx, 'para_idx': p_idx
                            }
                            pass  # Do not log uploaded content or personal data.
                        elif re.search(r"\{\%\s*endfor\s*\%\s*\}", text) and loop_start is not None and loop_start.get('type') == 'cell':
                            loop_end = {
                                'type': 'cell', 'table_idx': t_idx, 'row_idx': r_idx, 'cell_idx': c_idx, 'para_idx': p_idx
                            }
                            pass  # Do not log uploaded content or personal data.
                            break
                    if loop_end is not None:
                        break
                if loop_end is not None:
                    break
            if loop_end is not None:
                break

    if loop_start is not None and loop_end is not None and loop_start.get('type') == loop_end.get('type'):
        pass  # Do not log uploaded content or personal data.
        
        if not general_photos_list or len(general_photos_list) == 0:
            # Remove empty loop either for top-level paragraph context or cell-based context
            if loop_start['type'] == 'para':
                for idx in range(loop_end['idx'], loop_start['idx'] - 1, -1):
                    p = doc.paragraphs[idx]
                    p._element.getparent().remove(p._element)
            else:
                # cell context
                t_idx = loop_start['table_idx']
                r_idx = loop_start['row_idx']
                c_idx = loop_start['cell_idx']
                start_p = loop_start['para_idx']
                end_p = loop_end['para_idx']
                try:
                    target_cell = doc.tables[t_idx].rows[r_idx].cells[c_idx]
                    for p_idx in range(end_p, start_p - 1, -1):
                        p = target_cell.paragraphs[p_idx]
                        p._element.getparent().remove(p._element)
                except Exception as e:
                    pass  # Do not log uploaded content or personal data.
            pass  # Do not log uploaded content or personal data.
            # Also remove any leftover '{{ photo.image }}' tokens in the doc
            _remove_photo_image_placeholders(doc)
            return
        
        # Two contexts supported: top-level paragraphs or inside a table cell
        if loop_start['type'] == 'para':
            # Top-level paragraph insertion logic
            loop_start_para = doc.paragraphs[loop_start['idx']]
            parent = loop_start_para._element.getparent()
            insert_before = loop_start_para._element
        
        # Insert each photo (top-level paragraph context)
        if loop_start['type'] == 'para':
            # When multiple general photos are provided, insert them as a 3-column table
            num_photos = len(general_photos_list)
            if num_photos == 1:
                # keep the single-image behavior (large centered image)
                photo_file = general_photos_list[0]
                try:
                    image_bytes = service.get_file_from_stage(photo_file)
                    if image_bytes:
                        new_para_element = docx.oxml.shared.OxmlElement('w:p')
                        parent.insert(parent.index(insert_before), new_para_element)
                        new_para = None
                        for p in doc.paragraphs:
                            if p._element == new_para_element:
                                new_para = p
                                break
                        if new_para:
                            run = new_para.add_run()
                            image_stream = io.BytesIO(image_bytes)
                            run.add_picture(image_stream, width=Inches(4.0))
                            new_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            pass  # Do not log uploaded content or personal data.
                except Exception as e:
                    pass  # Do not log uploaded content or personal data.
            else:
                # Create a 3-column table and place images into the cells (similar to defect photos)
                cols = 3
                rows = (num_photos + cols - 1) // cols
                table = doc.add_table(rows=rows, cols=cols)
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                table_element = table._element
                # Move table to correct position (before marker)
                parent.insert(parent.index(insert_before), table_element)

                # Now populate table cells with images
                for idx, photo_file in enumerate(general_photos_list):
                    row_idx = idx // cols
                    col_idx = idx % cols
                    cell = table.rows[row_idx].cells[col_idx]
                    try:
                        image_bytes = service.get_file_from_stage(photo_file)
                        if image_bytes:
                            paragraph = cell.paragraphs[0]
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            run = paragraph.add_run()
                            image_stream = io.BytesIO(image_bytes)
                            run.add_picture(image_stream, width=Inches(2.5))
                            pass  # Do not log uploaded content or personal data.
                        else:
                            cell.text = '[Image not available]'
                    except Exception as e:
                        pass  # Do not log uploaded content or personal data.
                        cell.text = '[Image not available]'
        
            # Remove loop markers (top-level paragraphs)
            for idx in range(loop_end['idx'], loop_start['idx'] - 1, -1):
                p = doc.paragraphs[idx]
                p._element.getparent().remove(p._element)
        else:
            # Cell-based insertion: insert images into the cell where the loop was defined
            t_idx = loop_start['table_idx']
            r_idx = loop_start['row_idx']
            c_idx = loop_start['cell_idx']
            start_p = loop_start['para_idx']
            end_p = loop_end['para_idx']

            try:
                target_table = doc.tables[t_idx]
                target_cell = target_table.rows[r_idx].cells[c_idx]

                if not general_photos_list or len(general_photos_list) == 0:
                    # Remove the loop paragraphs inside the cell
                    for p_idx in range(end_p, start_p - 1, -1):
                        p = target_cell.paragraphs[p_idx]
                        p._element.getparent().remove(p._element)
                    pass  # Do not log uploaded content or personal data.
                    _remove_photo_image_placeholders(doc)
                    return

                for photo_file in general_photos_list:
                    try:
                        image_bytes = service.get_file_from_stage(photo_file)
                        if not image_bytes:
                            pass  # Do not log uploaded content or personal data.
                            continue
                        # Add a new paragraph in the cell for the image
                        new_para = target_cell.add_paragraph()
                        run = new_para.add_run()
                        image_stream = io.BytesIO(image_bytes)
                        run.add_picture(image_stream, width=Inches(4.0))
                        new_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        pass  # Do not log uploaded content or personal data.
                    except Exception as e:
                        pass  # Do not log uploaded content or personal data.
                        import traceback
                        traceback.print_exc()
                        continue

                # Remove the loop paragraphs inside the cell
                for p_idx in range(end_p, start_p - 1, -1):
                    p = target_cell.paragraphs[p_idx]
                    p._element.getparent().remove(p._element)

            except Exception as e:
                pass  # Do not log uploaded content or personal data.
                import traceback
                traceback.print_exc()
                # fallback to table-based method
        
        # Clean up any leftover photo placeholders in other parts of the document
        _remove_photo_image_placeholders(doc)
        pass  # Do not log uploaded content or personal data.
        return
    
    # Method 2: Table-based approach - find tables with [Image not available] placeholders
    pass  # Do not log uploaded content or personal data.
    
    if not general_photos_list or len(general_photos_list) == 0:
        pass  # Do not log uploaded content or personal data.
        # Remove any placeholder tables that were intended for general photos
        tables_to_remove = []
        for t_idx, table in enumerate(doc.tables):
            remove_table = False
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        if '[Image not available]' in paragraph.text:
                            remove_table = True
                            break
                    if remove_table:
                        break
                if remove_table:
                    break
            if remove_table:
                tables_to_remove.append(table)
        for table in tables_to_remove:
            try:
                table._element.getparent().remove(table._element)
                pass  # Do not log uploaded content or personal data.
            except Exception as e:
                pass  # Do not log uploaded content or personal data.
        # Also remove any '{{ photo.image }}' placeholders in paragraphs/cells
        _remove_photo_image_placeholders(doc)
        return
    
    photos_inserted = 0
    
    # Find tables and replace [Image not available] with actual images
    last_table_element = None
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if '[Image not available]' in paragraph.text:
                        # Check if we have photos left to insert
                        if photos_inserted < len(general_photos_list):
                            photo_file = general_photos_list[photos_inserted]
                            try:
                                # Download from stage
                                image_bytes = service.get_file_from_stage(photo_file)
                                if image_bytes:
                                    # Clear the placeholder text
                                    paragraph.clear()
                                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                    
                                    # Add image
                                    run = paragraph.add_run()
                                    image_stream = io.BytesIO(image_bytes)
                                    run.add_picture(image_stream, width=Inches(2.0))
                                    
                                    photos_inserted += 1
                                    last_table_element = table._element
                                    pass  # Do not log uploaded content or personal data.
                                else:
                                    pass  # Do not log uploaded content or personal data.
                            except Exception as e:
                                pass  # Do not log uploaded content or personal data.
                                import traceback
                                traceback.print_exc()
    
    # If there are still photos left after replacing placeholders in tables,
    # insert the remaining photos as full-width paragraphs after the last found placeholder table
    if photos_inserted < len(general_photos_list):
        remaining = len(general_photos_list) - photos_inserted
        try:
            pass  # Do not log uploaded content or personal data.
            start_idx = None
            parent = None
            insert_before = None
            if last_table_element is not None:
                # insert after the last table element
                elem_parent = last_table_element.getparent()
                parent = elem_parent
                insert_before = last_table_element.getnext()
            else:
                # fallback to end of document
                insert_before = None

            # Insert remaining photos sequentially
            for i in range(photos_inserted, len(general_photos_list)):
                photo_file = general_photos_list[i]
                try:
                    image_bytes = service.get_file_from_stage(photo_file)
                    if not image_bytes:
                        pass  # Do not log uploaded content or personal data.
                        continue

                    # Add a paragraph at the end (or before insert_before if set)
                    new_para = doc.add_paragraph()
                    new_para_run = new_para.add_run()
                    image_stream = io.BytesIO(image_bytes)
                    new_para_run.add_picture(image_stream, width=Inches(4.0))
                    new_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    photos_inserted += 1
                    pass  # Do not log uploaded content or personal data.
                except Exception as e:
                    pass  # Do not log uploaded content or personal data.
                    import traceback
                    traceback.print_exc()
                    continue
        except Exception as e:
            pass  # Do not log uploaded content or personal data.

    pass  # Do not log uploaded content or personal data.

    # After table-based insertion, remove any remaining Jinja-style placeholders for photo.image
    _remove_photo_image_placeholders(doc)


def _remove_photo_image_placeholders(doc):
    """
    Remove any leftover Jinja placeholders like '{{ photo.image }}' from the document.
    This clears paragraphs or table cell paragraphs containing the token.
    """
    import re
    # Accept both {{ photo.image }} and the newer {{ photo }} placeholder
    pattern = re.compile(r"\{\{\s*(?:photo\.image|photo)\s*\}\}")
    to_remove = []

    # Top-level paragraphs
    for p in list(doc.paragraphs):
        if pattern.search(p.text):
            to_remove.append(p)

    for p in to_remove:
        try:
            p._element.getparent().remove(p._element)
        except Exception:
            pass

    # Table cell paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                cell_paras = list(cell.paragraphs)
                for p in cell_paras:
                    try:
                        if pattern.search(p.text):
                            p._element.getparent().remove(p._element)
                    except Exception:
                        continue


def inline_replace_in_paragraph(paragraph, placeholder, value):
    """
    Replace placeholder in paragraph while preserving formatting.
    Handles multi-line values by adding line breaks.
    """
    # Check if placeholder exists in the full paragraph text
    if placeholder not in paragraph.text:
        return
    
    # Clear the paragraph but keep its format
    paragraph_format = paragraph.paragraph_format
    for run in paragraph.runs:
        run.text = ''
    
    # Split value by newlines and add with proper line breaks
    lines = value.split('\n')
    
    for i, line in enumerate(lines):
        if line.strip():  # Only add non-empty lines
            run = paragraph.add_run(line)
            run.font.size = Pt(9)
        
        # Add line break if not the last line
        if i < len(lines) - 1:
            run = paragraph.add_run()
            run.add_break()


def generate_basic_report(inspection_data):
    """
    Fallback: Generate a basic report if template is not found.
    """
    doc = Document()
    
    # Title
    title = doc.add_heading('Building Inspection Report', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Inspector Details
    doc.add_heading('Inspector Details', level=1)
    doc.add_paragraph(inspection_data.get('inspector_name', 'N/A'))
    
    # Contractor
    doc.add_heading('Contractor Information', level=1)
    doc.add_paragraph(inspection_data.get('contractor_name', 'N/A'))
    
    # Site Address
    doc.add_heading('Site Address', level=1)
    doc.add_paragraph(inspection_data.get('site_address', 'N/A'))
    
    # Notes
    doc.add_heading('Inspection Notes', level=1)
    notes_text = inspection_data.get('notes', 'N/A')
    for line in notes_text.split('\n'):
        if line.strip():
            doc.add_paragraph(line.strip())
    
    # Save to bytes
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def generate_word_report(feedback: dict, filename: str = "analysis_report") -> bytes:
    """
    Generate a professional Word document report from analysis feedback.
    Uses python-docx for better text flow and formatting than PDF.
    """
    
    # Import required classes - always try fresh import
    try:
        from docx import Document
        from docx.shared import Inches, Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
        pass  # Do not log uploaded content or personal data.
    except ImportError:
        raise ImportError("python-docx library not available. Please install with: pip install python-docx")
    
    try:
        # Create new Word document
        doc = Document()
        
        # Set document margins
        sections = doc.sections
        for section in sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)
        
        # Title
        title = doc.add_heading('REFERENCE Licence Application Analysis Report', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Subtitle with timestamp in AEST
        # Force AEST timezone (UTC+10) instead of AEDT during daylight saving
        aest = pytz.timezone('Australia/Brisbane')  # Brisbane doesn't observe daylight saving, always UTC+10
        timestamp = datetime.now(aest).strftime("%B %d, %Y at %I:%M %p AEST")
        subtitle = doc.add_paragraph(f'Generated on {timestamp}')
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        subtitle_format = subtitle.runs[0].font
        subtitle_format.size = Pt(12)
        subtitle_format.italic = True
        
        doc.add_paragraph()  # Space
        
        # Executive Summary & Overall Assessment
        overall_assessment = None
        
        # Check for overall assessment in multiple places with priority order
        if 'document_summary' in feedback and isinstance(feedback['document_summary'], dict):
            doc_summary = feedback['document_summary']
            if 'overall_assessment' in doc_summary and doc_summary['overall_assessment']:
                candidate = doc_summary['overall_assessment']
                # Skip the basic fallback message
                if not candidate.startswith('Application analysis completed.'):
                    overall_assessment = candidate
        
        # If no good assessment found in document_summary, check root level
        if not overall_assessment and 'overall_assessment' in feedback and feedback['overall_assessment']:
            candidate = feedback['overall_assessment']
            if not candidate.startswith('Application analysis completed.'):
                overall_assessment = candidate
        
        # If still no assessment, look for other comprehensive content
        if not overall_assessment:
            # Try to find analysis summary or other detailed content
            if 'document_summary' in feedback and isinstance(feedback['document_summary'], dict):
                doc_summary = feedback['document_summary']
                if 'analysis_summary' in doc_summary and doc_summary['analysis_summary']:
                    overall_assessment = doc_summary['analysis_summary']
        
        # Always create an Executive Summary section
        doc.add_heading('Executive Summary & Overall Assessment', level=1)
        
        # Add a professional disclaimer
        disclaimer = doc.add_paragraph()
        disclaimer_run = disclaimer.add_run('IMPORTANT NOTICE: This is an AI-assisted analysis tool designed to support the REFERENCE licence application review process. While this system uses advanced artificial intelligence, all outputs must be independently verified by qualified professionals. This analysis does not replace human judgment, professional expertise, or synthetic demonstration assessment procedures. Users are responsible for ensuring accuracy and compliance with all applicable regulations.')
        disclaimer_run.italic = True
        disclaimer_run.font.size = Pt(9)
        disclaimer_run.font.color.rgb = None  # Ensures it uses default text color
        doc.add_paragraph()
        
        if overall_assessment:
            assessment_text = str(overall_assessment)
            
            # Clean up and format the assessment text
            if assessment_text and assessment_text.strip():
                # Remove AI prompt artifacts - more comprehensive filtering
                patterns_to_remove = [
                    'Certainly! Below is a model REFERENCE Medium-Rise Builder Licence Assessment Report. This template is based on your framework and can be tailored to a specific applicant by inserting their evidence and details.',
                    'Certainly! Below is a model REFERENCE Low-Rise Builder Licence Assessment Report. This template is based on your framework and can be tailored to a specific applicant by inserting their evidence and details.',
                    'Below is a model REFERENCE Medium-Rise Builder licence assessment report. This template is based on your framework and can be tailored to a specific applicant by inserting their evidence and details. For demonstration, I will use plausible, generic applicant evidence and highlight both strengths and gaps.',
                    'Below is a model REFERENCE Low-Rise Builder licence assessment report. This template is based on your framework and can be tailored to a specific applicant by inserting their evidence and details. For demonstration, I will use plausible, generic applicant evidence and highlight both strengths and gaps.',
                    'Below is a model REFERENCE Medium-Rise Builder licence assessment report.',
                    'Below is a model REFERENCE Low-Rise Builder licence assessment report.',
                    'This template is based on your framework and can be tailored to a specific applicant by inserting their evidence and details.',
                    'For demonstration, I will use plausible, generic applicant evidence and highlight both strengths and gaps.',
                    'Certainly!',
                    'Below is a model'
                ]
                
                for pattern in patterns_to_remove:
                    assessment_text = assessment_text.replace(pattern, '')
                
                assessment_text = assessment_text.strip()
                
                # Remove markdown headers and clean formatting
                assessment_text = assessment_text.replace('---', '').replace('###', '').replace('##', '').replace('#', '')
                
                # If it's a single line or short text, just add it as a paragraph
                if '\n\n' not in assessment_text and len(assessment_text) < 500:
                    clean_text = assessment_text.replace('**', '').replace('*', '').strip()
                    if clean_text:
                        p = doc.add_paragraph(clean_text)
                        p.space_after = Pt(12)
                else:
                    # Split into sections and paragraphs for longer content
                    sections = assessment_text.split('\n\n')
                    
                    for section_text in sections:
                        section_text = section_text.strip()
                        if section_text and len(section_text) > 5:
                            # Check if this looks like a section header (shorter lines with specific patterns)
                            is_header = (
                                len(section_text) < 100 and 
                                (':' in section_text or 
                                 section_text.isupper() or 
                                 section_text.startswith(('**', '*')) or
                                 (len(section_text.split()) < 8 and 
                                  any(word in section_text.upper() for word in ['ASSESSMENT', 'SUMMARY', 'FINDINGS', 'RECOMMENDATION', 'CONCLUSION', 'ANALYSIS'])))
                            )
                            
                            if is_header:
                                # This looks like a header
                                clean_header = section_text.replace('**', '').replace('*', '').strip()
                                if clean_header:
                                    header_para = doc.add_paragraph()
                                    header_run = header_para.add_run(clean_header)
                                    header_run.bold = True
                                    header_run.font.size = Pt(12)
                                    header_para.space_after = Pt(6)
                            else:
                                # This is regular content
                                clean_text = section_text.replace('**', '').replace('*', '').strip()
                                if clean_text:
                                    p = doc.add_paragraph(clean_text)
                                    p.space_after = Pt(8)
        else:
            # Create a comprehensive summary when no detailed assessment is available
            doc.add_paragraph('Document Analysis Summary', style='Heading 2')
            
            # Count items from verification table
            verification_count = 0
            if 'verification_table' in feedback and feedback['verification_table']:
                verification_count = len(feedback['verification_table'])
            
            # Get document info
            doc_type = 'Unknown'
            if 'document_summary' in feedback and isinstance(feedback['document_summary'], dict):
                doc_type = feedback['document_summary'].get('document_type', 'Unknown')
            
            # Create summary content
            summary_text = f"""This analysis covers a {doc_type} document containing {verification_count} claimed items that were verified against supporting documentation. The review process examined the application for completeness, accuracy, and compliance with REFERENCE requirements.

Key areas of assessment include:
• Applicant information and credentials verification
• Supporting documentation completeness
• Compliance with regulatory requirements
• Identification of any discrepancies or missing information

For detailed findings and recommendations, please refer to the sections below."""
            
            p = doc.add_paragraph(summary_text)
            p.space_after = Pt(12)
            
        doc.add_page_break()
        
        # Document Summary
        if 'document_summary' in feedback:
            doc.add_heading('Document Summary', level=1)
            doc_summary = feedback['document_summary']
            
            if isinstance(doc_summary, dict):
                # Create a simple table for document info
                table = doc.add_table(rows=1, cols=2)
                table.alignment = WD_TABLE_ALIGNMENT.LEFT
                
                # Header row
                header_cells = table.rows[0].cells
                header_cells[0].text = 'Property'
                header_cells[1].text = 'Value'
                
                # Make header bold
                for cell in header_cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True
                
                # Add data rows with more comprehensive information
                summary_items = [
                    ('Document Type', doc_summary.get('document_type', 'Unknown')),
                    ('Applicant Name', doc_summary.get('applicant_name', 'Not specified')),
                    ('Licence Type', doc_summary.get('licence_type', 'Not specified')),
                    ('Application Status', doc_summary.get('status', 'Under Review')),
                    ('Total Pages', doc_summary.get('total_pages', 'Unknown')),
                    ('Word Count', doc_summary.get('word_count', 'Unknown')),
                    ('Critical Sections', doc_summary.get('critical_sections_status', 'Not assessed'))
                ]
                
                for key, value in summary_items:
                    if value and str(value).strip() and str(value) not in ['Unknown', 'Not specified', 'Not assessed']:
                        row_cells = table.add_row().cells
                        row_cells[0].text = key
                        row_cells[1].text = str(value)
                
                # Add main sections if available
                if 'main_sections' in doc_summary and doc_summary['main_sections']:
                    sections_text = ', '.join(doc_summary['main_sections'][:5])  # Limit to first 5
                    if len(doc_summary['main_sections']) > 5:
                        sections_text += f' (+{len(doc_summary["main_sections"])-5} more)'
                    row_cells = table.add_row().cells
                    row_cells[0].text = 'Main Sections'
                    row_cells[1].text = sections_text
            
            doc.add_paragraph()
        
        # Guide Compliance Analysis
        if 'guide_compliance' in feedback and feedback['guide_compliance']:
            doc.add_heading('Guide Compliance Analysis', level=1)
            
            compliance = feedback['guide_compliance']
            
            # Overall Status Summary
            if 'overall_status' in compliance:
                status = compliance['overall_status']
                status_text = f"**Overall Status:** {status.replace('_', ' ').title()}"
                p = doc.add_paragraph(status_text)
                p.paragraph_format.space_after = Pt(6)
            
            # Risk Level
            if 'risk_level' in compliance:
                risk = compliance['risk_level']
                risk_text = f"**Risk Level:** {risk.upper()}"
                p = doc.add_paragraph(risk_text)
                p.paragraph_format.space_after = Pt(6)
            
            # Summary Statistics
            if any(k in compliance for k in ['total_requirements', 'requirements_met', 'missing_mandatory', 'missing_recommended']):
                doc.add_paragraph('Compliance Summary:', style='Heading 2')
                
                summary_table = doc.add_table(rows=1, cols=2)
                summary_table.alignment = WD_TABLE_ALIGNMENT.LEFT
                
                # Header
                header_cells = summary_table.rows[0].cells
                header_cells[0].text = 'Metric'
                header_cells[1].text = 'Value'
                for cell in header_cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True
                
                # Add metrics
                metrics = [
                    ('Total Requirements', compliance.get('total_requirements', 'N/A')),
                    ('Requirements Met', compliance.get('requirements_met', 'N/A')),
                    ('Missing Mandatory', compliance.get('missing_mandatory', 0)),
                    ('Missing Recommended', compliance.get('missing_recommended', 0)),
                    ('Partially Met', compliance.get('partial_requirements', 0))
                ]
                
                for metric_name, metric_value in metrics:
                    row_cells = summary_table.add_row().cells
                    row_cells[0].text = metric_name
                    row_cells[1].text = str(metric_value)
                
                doc.add_paragraph()
            
            # Detailed Compliance Results
            if 'compliance_results' in compliance and compliance['compliance_results']:
                doc.add_paragraph('Detailed Requirements Check:', style='Heading 2')
                
                results_table = doc.add_table(rows=1, cols=4)
                results_table.alignment = WD_TABLE_ALIGNMENT.LEFT
                results_table.style = 'Table Grid'
                
                # Header
                header_cells = results_table.rows[0].cells
                header_cells[0].text = 'Requirement'
                header_cells[1].text = 'Category'
                header_cells[2].text = 'Status'
                header_cells[3].text = 'Evidence'
                
                for cell in header_cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True
                
                # Add each compliance result
                for result in compliance['compliance_results'][:50]:  # Limit to first 50 to avoid huge reports
                    if isinstance(result, dict):
                        row_cells = results_table.add_row().cells
                        
                        # Requirement description
                        req_text = result.get('requirement_description', result.get('requirement', 'Unknown'))
                        row_cells[0].text = str(req_text)[:150]  # Limit length
                        
                        # Category
                        category = result.get('category', result.get('compliance_level', 'Unknown'))
                        row_cells[1].text = str(category).replace('_', ' ').title()
                        
                        # Status
                        status = result.get('status', 'Unknown')
                        status_text = str(status).replace('_', ' ').title()
                        if status == 'met':
                            status_text = '✅ ' + status_text
                        elif status == 'not_found':
                            status_text = '❌ ' + status_text
                        elif status == 'partial':
                            status_text = '⚠️ ' + status_text
                        row_cells[2].text = status_text
                        
                        # Evidence
                        evidence = result.get('evidence', result.get('explanation', 'None'))
                        row_cells[3].text = str(evidence)[:200] if evidence else 'No evidence found'
                
                if len(compliance['compliance_results']) > 50:
                    p = doc.add_paragraph()
                    p.add_run(f"Note: Showing first 50 of {len(compliance['compliance_results'])} total requirements.").italic = True
                
                doc.add_paragraph()
            
            # Recommendations
            if 'recommendations' in compliance and compliance['recommendations']:
                doc.add_paragraph('Recommendations:', style='Heading 2')
                recommendations = compliance['recommendations']
                if isinstance(recommendations, list):
                    for rec in recommendations:
                        doc.add_paragraph(str(rec), style='List Bullet')
                elif isinstance(recommendations, str):
                    doc.add_paragraph(recommendations)
                doc.add_paragraph()
            
            doc.add_page_break()
        
        # Verification Table
        if 'verification_table' in feedback and feedback['verification_table']:
            doc.add_heading('Claimed Information Verification', level=1)
            
            verification_items = feedback['verification_table']
            if verification_items:
                # Create verification table
                table = doc.add_table(rows=1, cols=4)
                table.alignment = WD_TABLE_ALIGNMENT.LEFT
                table.style = 'Table Grid'
                
                # Header row
                header_cells = table.rows[0].cells
                header_cells[0].text = 'Claimed Item'
                header_cells[1].text = 'Type'
                header_cells[2].text = 'Status' 
                header_cells[3].text = 'Supporting Documents'
                
                # Make header bold
                for cell in header_cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True
                
                # Add verification items
                for item in verification_items:
                    if isinstance(item, dict):
                        row_cells = table.add_row().cells
                        
                        # Try multiple field names for claimed item
                        claimed_item = (item.get('claimed_item') or 
                                      item.get('description') or 
                                      item.get('item') or 
                                      item.get('claim') or 'Unknown')
                        row_cells[0].text = str(claimed_item)[:100]  # Limit length
                        
                        # Try multiple field names for type
                        item_type = (item.get('item_type') or 
                                   item.get('type') or 
                                   item.get('category') or 'Unknown')
                        row_cells[1].text = str(item_type).replace('_', ' ').title()
                        
                        # Try multiple field names for status
                        status = (item.get('verification_status') or 
                                item.get('status') or 
                                item.get('result') or 'Unknown')
                        row_cells[2].text = str(status).replace('_', ' ').title()
                        
                        # Format supporting documents
                        docs = (item.get('supporting_documents') or 
                               item.get('documents') or 
                               item.get('evidence') or [])
                        if docs and isinstance(docs, list) and len(docs) > 0:
                            # Remove duplicates and clean up
                            unique_docs = list(set(docs))
                            doc_text = ', '.join(unique_docs[:3])  # Limit to first 3 docs
                            if len(unique_docs) > 3:
                                doc_text += f' (+{len(unique_docs)-3} more)'
                        else:
                            doc_text = 'None found'
                        row_cells[3].text = doc_text
            
            doc.add_paragraph()
        
        # Save to bytes buffer
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()
        
    except Exception as e:
        raise Exception(f"Word document generation failed: {str(e)}")