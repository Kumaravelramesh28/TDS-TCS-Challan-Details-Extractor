import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
from datetime import datetime
import logging
from typing import Dict, List, Optional, Tuple, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
OUTPUT_COLUMNS = [
    "Date of Deposit",
    "BSR Code",
    "Challan No.",
    "Major Head",
    "Minor Head",
    "Code",
    "Tax",
    "Surcharge",
    "Cess",
    "Interest",
    "Penalty",
    "Fee under section 234E",
    "Total"
]

OUTPUT_COLUMNS_WITH_PAN = [
    "Date of Deposit",
    "BSR Code",
    "Challan No.",
    "Major Head",
    "Minor Head",
    "Code",
    "PAN",
    "Name",
    "Tax",
    "Surcharge",
    "Cess",
    "Interest",
    "Penalty",
    "Fee under section 234E",
    "Total"
]

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def clean_numeric(value: Any) -> str:
    """Clean and normalize numeric values from extracted text."""
    if not value:
        return ""
    value = str(value).replace("₹", "").replace(",", "")
    value = value.replace("O", "0").replace("o", "0")
    value = value.replace("I", "1").replace("l", "1")
    return re.sub(r"[^\d]", "", value)

def extract_text_from_page(page) -> str:
    """Extract text from a PDF page with error handling."""
    try:
        txt = page.extract_text()
        return txt if txt else ""
    except Exception as e:
        logger.warning(f"Error extracting text from page: {e}")
        return ""

def rx(text: str, pattern: str) -> str:
    """Extract pattern from text with error handling."""
    try:
        m = re.search(pattern, text, re.I | re.S)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""

def clean_pan(pan: str) -> str:
    """Clean and validate PAN number."""
    if not pan:
        return ""
    pan = pan.upper().strip()
    # Remove any special characters and spaces
    pan = re.sub(r'[^A-Z0-9]', '', pan)
    # Validate PAN format
    if re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', pan):
        return pan
    return ""

def extract_name_from_line(text: str, pan: str) -> str:
    """Extract the name that follows the PAN on the same line."""
    if not pan or not text:
        return ""
    
    # Find the line containing the PAN
    lines = text.split('\n')
    for line in lines:
        if pan in line:
            # Extract everything after the PAN
            parts = line.split(pan)
            if len(parts) > 1:
                name = parts[1].strip()
                # Remove any remaining special characters
                name = re.sub(r'[^\w\s\.\-]', '', name)
                name = re.sub(r'\s+', ' ', name).strip()
                if name and len(name) > 1:
                    return name
    return ""

def extract_pan_from_filename(filename: str) -> str:
    """Extract PAN from filename."""
    try:
        # Remove extension
        name = filename.rsplit('.', 1)[0]
        # Look for PAN pattern in filename
        pan_matches = re.findall(r'[A-Z]{5}[0-9]{4}[A-Z]', name.upper())
        if pan_matches:
            for pan in pan_matches:
                cleaned_pan = clean_pan(pan)
                if cleaned_pan:
                    return cleaned_pan
    except Exception as e:
        logger.warning(f"Error extracting PAN from filename: {e}")
    return ""

def extract_name_from_filename(filename: str, pan: str) -> str:
    """Extract name from filename after removing PAN."""
    if not pan or not filename:
        return ""
    
    try:
        # Remove extension
        name = filename.rsplit('.', 1)[0]
        # Remove PAN from filename
        name = name.replace(pan, '').strip()
        # Clean up extra spaces and special characters
        name = re.sub(r'[^\w\s\.\-]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        if name and len(name) > 1:
            return name
    except Exception as e:
        logger.warning(f"Error extracting name from filename: {e}")
    return ""

# ============================================================================
# PDF PROCESSING FUNCTIONS
# ============================================================================

def extract_major_head(text: str) -> str:
    """Extract Major Head from challan text."""
    try:
        m = re.search(r"Major\s+Head\s*:.*?\((\d{4})\)", text, re.I | re.S)
        return m.group(1) if m else ""
    except Exception:
        return ""

def extract_minor_head(text: str) -> str:
    """Extract Minor Head from challan text."""
    try:
        m = re.search(r"Minor\s+Head\s*:.*?\((\d{3})\)", text, re.I | re.S)
        return m.group(1) if m else ""
    except Exception:
        return ""

def extract_code(text: str) -> str:
    """Extract challan code from text."""
    try:
        # Common challan code pattern like 1073 before ₹ amount
        m = re.search(r"\b([0-9]{4})\s+₹", text)
        if m:
            return m.group(1)
        
        # Fallback: first 4-digit code in section-wise table area
        m = re.search(
            r"TDS/TCS\s+Section-Wise\s+Payment\s+Details.*?\b([0-9]{4})\b",
            text,
            re.I | re.S
        )
        if m:
            return m.group(1)
    except Exception as e:
        logger.warning(f"Error extracting code: {e}")
    
    return ""

def extract_tax_breakup(text: str) -> Tuple[str, str, str, str, str, str, str]:
    """Extract all tax components from challan text."""
    try:
        tax = clean_numeric(rx(text, r"A\s+Tax\s+₹?\s*([\d,]+)"))
        surcharge = clean_numeric(rx(text, r"B\s+Surcharge\s+₹?\s*([\d,]+)"))
        cess = clean_numeric(rx(text, r"C\s+Cess\s+₹?\s*([\d,]+)"))
        interest = clean_numeric(rx(text, r"D\s+Interest\s+₹?\s*([\d,]+)"))
        penalty = clean_numeric(rx(text, r"E\s+Penalty\s+₹?\s*([\d,]+)"))
        fee_234e = clean_numeric(rx(text, r"F\s+Fee under section 234E\s+₹?\s*([\d,]+)"))
        total = clean_numeric(rx(text, r"Total\s*\(A\+B\+C\+D\+E\+F\)\s+₹?\s*([\d,]+)"))
        return (tax, surcharge, cess, interest, penalty, fee_234e, total)
    except Exception as e:
        logger.warning(f"Error extracting tax breakup: {e}")
        return ("", "", "", "", "", "", "")

def extract_pan_from_text(text: str) -> str:
    """Extract first valid PAN from text."""
    try:
        # Look for PAN pattern in the text
        pan_matches = re.findall(r'[A-Z]{5}[0-9]{4}[A-Z]', text.upper())
        if pan_matches:
            # Return first valid PAN found
            for pan in pan_matches:
                cleaned_pan = clean_pan(pan)
                if cleaned_pan:
                    return cleaned_pan
    except Exception as e:
        logger.warning(f"Error extracting PAN from text: {e}")
    return ""

def extract_name_from_text(text: str, pan: str) -> str:
    """Extract name from text using PAN as reference."""
    if not pan:
        return ""
    
    try:
        # Try to find name directly after PAN
        name = extract_name_from_line(text, pan)
        if name:
            return name
        
        # Try to find name in Name/Party line
        m = re.search(r"(?:Name|Party)\s*[:：]\s*([^\n]+)", text, re.I | re.S)
        if m:
            name = m.group(1).strip()
            name = re.sub(r'[^\w\s\.\-]', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            if name and len(name) > 1:
                return name
        
        # Try to find business name near PAN
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if pan in line.upper():
                # Check current and next 3 lines for name
                for j in range(i, min(i + 4, len(lines))):
                    potential_name = lines[j].strip()
                    # Skip lines that are just numbers or codes
                    if potential_name and len(potential_name) > 3:
                        if not re.match(r'^[\d\s]+$', potential_name):
                            if not re.match(r'^[A-Z0-9]+$', potential_name):
                                # Clean the name
                                name = re.sub(r'[^\w\s\.\-]', '', potential_name)
                                name = re.sub(r'\s+', ' ', name).strip()
                                if name and len(name) > 1:
                                    return name
    except Exception as e:
        logger.warning(f"Error extracting name from text: {e}")
    
    return ""

def parse_challan(text: str, filename: str = "", include_pan: bool = False) -> Dict[str, str]:
    """Parse a single challan from text and return structured data."""
    # Initialize with proper columns
    if include_pan:
        row = {col: "" for col in OUTPUT_COLUMNS_WITH_PAN}
    else:
        row = {col: "" for col in OUTPUT_COLUMNS}
    
    # Extract basic fields (always do this)
    row["Date of Deposit"] = rx(
        text,
        r"Date\s+of\s+Deposit\s*[:：]\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4})"
    )
    
    row["BSR Code"] = clean_numeric(
        rx(text, r"BSR\s*code\s*[:：]\s*([^\n]+)")
    )
    
    row["Challan No."] = clean_numeric(
        rx(text, r"Challan\s*No\s*[:：]\s*([^\n]+)")
    )
    
    row["Major Head"] = extract_major_head(text)
    row["Minor Head"] = extract_minor_head(text)
    row["Code"] = extract_code(text)
    
    # Extract tax components
    (row["Tax"], row["Surcharge"], row["Cess"], 
     row["Interest"], row["Penalty"], 
     row["Fee under section 234E"], row["Total"]) = extract_tax_breakup(text)
    
    # Extract PAN and Name if requested
    if include_pan:
        # Try to get PAN from text first, then from filename
        pan = extract_pan_from_text(text)
        
        # If no PAN in text, try filename
        if not pan and filename:
            pan = extract_pan_from_filename(filename)
            
            # If we got PAN from filename, also try to get name from filename
            if pan:
                name = extract_name_from_filename(filename, pan)
                if name:
                    row["Name"] = name
        
        row["PAN"] = pan
        
        # If we have PAN but no name yet, try to extract name from text
        if pan and not row.get("Name"):
            name = extract_name_from_text(text, pan)
            if name:
                row["Name"] = name
    
    return row

def process_pdf_file(file_bytes: bytes, filename: str = "", include_pan: bool = False) -> List[Dict[str, str]]:
    """Process a single PDF file and extract all challans."""
    challans = []
    
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                txt = extract_text_from_page(page)
                
                # Check if this page contains a challan receipt
                if "Challan Receipt" not in txt and "CHALLAN RECEIPT" not in txt.upper():
                    continue
                
                # Parse the challan
                row = parse_challan(txt, filename, include_pan)
                challans.append(row)
                
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        raise
    
    return challans

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_single_pan(challans: List[Dict[str, str]]) -> Tuple[bool, Optional[str]]:
    """Validate that all challans have the same PAN."""
    pans = set()
    for challan in challans:
        pan = challan.get("PAN", "")
        if pan:
            pans.add(pan)
    
    if len(pans) == 0:
        return False, "No PAN detected in any challan. Please select 'Individual File of Different PAN' mode."
    elif len(pans) == 1:
        return True, list(pans)[0]
    else:
        return False, f"Multiple PANs detected: {', '.join(pans)}"

# ============================================================================
# EXCEL GENERATION FUNCTIONS
# ============================================================================

def generate_excel(data: List[Dict[str, str]], columns: List[str]) -> io.BytesIO:
    """Generate professional Excel output from challan data."""
    df = pd.DataFrame(data, columns=columns)
    
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Challan Data", index=False)
        
        # Get the workbook and worksheet
        workbook = writer.book
        worksheet = writer.sheets["Challan Data"]
        
        # Apply professional formatting
        # Bold headers
        for cell in worksheet[1]:
            cell.font = cell.font.copy(bold=True)
        
        # Auto column width
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except:
                    pass
            adjusted_width = min(max(max_length + 2, 12), 30)
            worksheet.column_dimensions[column_letter].width = adjusted_width
        
        # Freeze first row
        worksheet.freeze_panes = "A2"
        
        # Auto filter
        worksheet.auto_filter.ref = worksheet.dimensions
    
    output.seek(0)
    return output

def generate_filename(mode: str, pan: str = None, name: str = None) -> str:
    """Generate appropriate filename based on extraction mode."""
    if mode == "same_pan" and pan and name:
        # Clean name for filename
        clean_name = re.sub(r'[^\w\s\-]', '', name)
        clean_name = re.sub(r'\s+', '_', clean_name.strip())
        return f"{pan}_{clean_name}.xlsx"
    else:
        return "TDS_TCS_Challan_Extract.xlsx"

# ============================================================================
# STREAMLIT UI COMPONENTS
# ============================================================================

def render_header():
    """Render the application header."""
    st.set_page_config(
        page_title="TDS/TCS Challan Extract",
        page_icon="📋",
        layout="wide"
    )
    st.title("📋 TDS/TCS Challan Extract")
    st.markdown("---")

def render_pan_option() -> bool:
    """Render the PAN & Name inclusion option first."""
    st.markdown("### Step 1: Select Extraction Options")
    include_pan = st.radio(
        "Include PAN & Name?",
        ["No", "Yes"],
        index=0,
        help="Extract PAN and Name from challans (only works for certain formats)"
    )
    return include_pan == "Yes"

def render_extraction_mode(include_pan: bool) -> str:
    """Render the extraction mode selection."""
    if not include_pan:
        return "standard"
    
    st.markdown("### Step 2: Select Extraction Mode")
    mode = st.radio(
        "Choose how to process multiple challans",
        [
            "Individual / Single File of Same PAN",
            "Individual File of Different PAN",
            "Single File of Different PAN (Coming Soon)"
        ],
        index=0,
        help="Select the appropriate mode for your use case"
    )
    return mode

def render_file_uploader() -> List:
    """Render file uploader."""
    st.markdown("### Step 3: Upload PDF Files")
    files = st.file_uploader(
        "Upload PDF Challan(s)",
        type=["pdf"],
        accept_multiple_files=True,
        help="Upload one or more TDS/TCS challan PDFs for extraction"
    )
    return files

# ============================================================================
# MAIN APPLICATION LOGIC
# ============================================================================

def main():
    """Main application entry point."""
    render_header()
    
    # Step 1: Ask PAN option first
    include_pan = render_pan_option()
    
    # Step 2: Show extraction mode if PAN is selected
    mode = render_extraction_mode(include_pan)
    
    # Check if mode is "Coming Soon"
    if mode == "Single File of Different PAN (Coming Soon)":
        st.warning("⚠️ This feature is not available in the current version.")
        st.info("Please select one of the available modes.")
        return
    
    # Step 3: File uploader
    uploaded_files = render_file_uploader()
    
    if not uploaded_files:
        st.info("👆 Please upload TDS/TCS challan PDFs to begin extraction")
        return
    
    # Process button
    if st.button("🔄 Process Challans", type="primary"):
        process_challans(uploaded_files, include_pan, mode)

def process_challans(uploaded_files, include_pan: bool, mode: str):
    """Process uploaded challans based on selected options."""
    all_challans = []
    
    with st.spinner("Processing PDFs..."):
        try:
            # Process each uploaded file
            progress_bar = st.progress(0)
            total_files = len(uploaded_files)
            
            for idx, file in enumerate(uploaded_files):
                try:
                    file_bytes = file.read()
                    # Pass filename to the processing function
                    challans = process_pdf_file(file_bytes, file.name, include_pan)
                    all_challans.extend(challans)
                    st.success(f"✅ Processed: {file.name} ({len(challans)} challan(s))")
                except Exception as e:
                    st.error(f"❌ Error processing {file.name}: {str(e)}")
                
                # Update progress
                progress_bar.progress((idx + 1) / total_files)
            
            if not all_challans:
                st.warning("No valid challans were extracted from the uploaded files.")
                return
            
            # Determine columns based on include_pan
            columns = OUTPUT_COLUMNS_WITH_PAN if include_pan else OUTPUT_COLUMNS
            
            # Show extracted PANs for debugging
            if include_pan:
                extracted_pans = []
                for challan in all_challans:
                    if challan.get("PAN"):
                        extracted_pans.append(challan["PAN"])
                if extracted_pans:
                    st.info(f"🔍 Extracted PANs: {', '.join(set(extracted_pans))}")
                else:
                    st.warning("⚠️ No PAN extracted from any challan. Check if PAN is in the PDF or filename.")
            
            # Handle PAN validation for same PAN mode
            if include_pan and mode == "Individual / Single File of Same PAN":
                is_valid, result = validate_single_pan(all_challans)
                if not is_valid:
                    st.error(f"⚠️ {result}")
                    st.info("Please use 'Individual File of Different PAN' mode instead.")
                    return
                else:
                    # Get the name from the first challan with PAN
                    first_challan = next((c for c in all_challans if c.get("PAN")), None)
                    pan = result
                    name = first_challan.get("Name", "Unknown") if first_challan else "Unknown"
                    filename = generate_filename("same_pan", pan, name)
                    st.success(f"✅ All challans have the same PAN: {pan}")
            
            else:
                # Different PAN mode or no PAN extraction
                filename = generate_filename("different_pan")
                if include_pan:
                    st.success("✅ Processing with different PANs allowed")
                else:
                    st.success("✅ Processing without PAN extraction")
            
            # Generate Excel
            df = pd.DataFrame(all_challans, columns=columns)
            excel_data = generate_excel(all_challans, columns)
            
            # Display preview
            st.subheader("📊 Extracted Data Preview")
            st.dataframe(df, use_container_width=True)
            
            # Show statistics
            col1, col2 = st.columns(2)
            with col1:
                st.metric("📄 Files Processed", len(uploaded_files))
            with col2:
                st.metric("📋 Challans Extracted", len(all_challans))
            
            # Show PAN info if available
            if include_pan:
                pans = set()
                for challan in all_challans:
                    if challan.get("PAN"):
                        pans.add(challan["PAN"])
                if pans:
                    st.info(f"🏢 PANs Detected: {', '.join(pans)}")
            
            # Download button
            st.download_button(
                label="📥 Download Excel Report",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
        except Exception as e:
            st.error(f"❌ An error occurred during processing: {str(e)}")
            logger.error(f"Processing error: {e}", exc_info=True)

# ============================================================================
# APPLICATION ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()
