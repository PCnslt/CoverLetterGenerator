import pdfplumber
from docx import Document
import streamlit as st
from openai import OpenAI, APIError, AuthenticationError, RateLimitError
from pdfplumber import PDFSyntaxError  # pylint: disable=no-name-in-module
from typing import Union, Optional
import io

def extract_resume_text(uploaded_file: io.BytesIO) -> Optional[str]:
    """
    Extract text from PDF or Word resume files with enhanced error handling.
    
    Args:
        uploaded_file: UploadFile object from Streamlit containing the resume
    
    Returns:
        Clean text content or None if extraction fails
    """
    try:
        if uploaded_file.type == "application/pdf":
            try:
                with pdfplumber.open(uploaded_file) as pdf:
                    full_text = []
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if not page_text:
                            raise ValueError("Scanned PDF detected - text extraction failed")
                        full_text.append(page_text)
                    return "\n".join(full_text).replace("\n\n", "\n").strip()
            
            except PDFSyntaxError:
                st.error("Invalid or corrupted PDF file")
                return None
                
        elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                doc = Document(uploaded_file)
                return "\n".join([para.text for para in doc.paragraphs if para.text]).strip()
            except KeyError as e:
                st.error("Invalid Word document structure")
                return None
                
    except ValueError as ve:
        st.error(f"PDF text extraction failed: {str(ve)}")
        return None
    except Exception as e:
        st.error(f"Unexpected error processing file: {str(e)}")
        return None
