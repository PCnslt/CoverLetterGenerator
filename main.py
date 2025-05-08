import streamlit as st
import time
from docx import Document
from io import BytesIO
from utils.resume_parser import extract_resume_text
from utils.payment_handler import PaymentProcessor
from typing import Optional, Iterator
import os
from openai import OpenAI, APIError, AuthenticationError, RateLimitError

# Initialize clients with error handling
try:
    payment_processor = PaymentProcessor()
    openai_client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except Exception as e:
    st.error(f"Initialization failed: {str(e)}")
    st.stop()

def generate_cover_letter(resume_text: str, job_desc: str, company_name: str) -> Iterator[str]:
    """Generate cover letter using GPT-4 with streaming"""
    system_prompt = """You're a professional career coach. Generate a concise 250-word 
    cover letter that matches the resume skills to the job requirements. Use a professional tone."""
    
    try:
        stream = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Resume:\n{resume_text}\n\nJob Description:\n{job_desc}\n\nCompany: {company_name}"}
            ],
            temperature=0.7,
            stream=True
        )
        
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                
    except AuthenticationError:
        st.error("Invalid OpenAI API key. Please check your .env file")
        yield ""
    except RateLimitError:
        st.error("API rate limit exceeded. Please try again later")
        yield ""
    except APIError as e:
        st.error(f"API error: {str(e)}")
        yield ""


def create_docx(content: str) -> BytesIO:
    """Create DOCX file in memory"""
    doc = Document()
    doc.add_paragraph(content)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def main():
    # Handle payment success callback from Stripe
    if st.query_params.get("payment_success") == "true":
        session_id = st.query_params.get("session_id")
        if session_id:
            with st.spinner("Verifying payment..."):
                try:
                    payment_status = payment_processor.check_payment_status(session_id)
                    if payment_status == "paid":
                        st.session_state.payment_success = True
                        st.session_state.payment_session_id = session_id
                        st.rerun()
                    else:
                        st.error(f"Payment verification failed: {payment_status}")
                except Exception as e:
                    st.error(f"Payment verification error: {str(e)}")
    
    st.title("AI Cover Letter Generator")
    
    # Check required secrets
    required_secrets = ["OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY", "STRIPE_SECRET_KEY"]
    missing_secrets = [secret for secret in required_secrets if secret not in st.secrets]
    if missing_secrets:
        st.error(f"Missing required secrets: {', '.join(missing_secrets)}")
        st.stop()
    
    with st.form("inputs"):
        # Initialize payment state
        if 'payment_state' not in st.session_state:
            st.session_state.payment_state = {
                'status': 'unpaid',
                'session_id': None,
                'start_time': time.time(),
                'retries': 0
            }
        st.subheader("Application Details")
        resume = st.file_uploader("Upload Resume (PDF/DOCX)", type=["pdf", "docx"])
        job_desc = st.text_area("Paste Job Description", height=200)
        company_name = st.text_input("Company Name")
        submitted = st.form_submit_button("Generate Cover Letter ($1)")
    
    if submitted:
        # Handle payment flow
        with st.status("Processing Payment...", expanded=True) as status:
            if st.session_state.payment_state['status'] == 'paid':
                status.update(label="Payment Verified", state="complete")
                # Proceed to generation
            elif st.session_state.payment_state['status'] == 'pending':
                if time.time() - st.session_state.payment_state['start_time'] > 300:
                    st.error("Payment timed out after 5 minutes")
                    st.session_state.payment_state = {'status': 'unpaid'}
                    st.stop()
                
                try:
                    payment_status = payment_processor.check_payment_status(
                        st.session_state.payment_state['session_id']
                    )
                    if payment_status == 'paid':
                        st.session_state.payment_state['status'] = 'paid'
                        st.rerun()
                    else:
                        st.session_state.payment_state['retries'] += 1
                        if st.session_state.payment_state['retries'] >= 5:
                            st.error("Payment verification failed after 5 attempts")
                            st.session_state.payment_state = {'status': 'unpaid'}
                        else:
                            time.sleep(2)
                            st.rerun()
                except Exception as e:
                    st.error(f"Payment check failed: {str(e)}")
                    st.session_state.payment_state = {'status': 'unpaid'}
            else:
                try:
                    payment_url = payment_processor.create_payment_session("user123")
                    st.session_state.payment_state.update({
                        'status': 'pending',
                        'session_id': payment_url.split("/pay/")[-1].split("#")[0],
                        'start_time': time.time()
                    })
                    status.update(label="Payment Required", state="complete")
                    st.markdown(f"Please [complete your payment]({payment_url})")
                    st.stop()
                except Exception as e:
                    st.error(f"Payment initialization failed: {str(e)}")
                    st.session_state.payment_state = {'status': 'unpaid'}
        # Proceed only after successful payment
        if st.session_state.payment_state.get('status') != 'paid':
            return

        # Validate inputs
        validation_errors = []
        
        # File validation
        if not resume:
            validation_errors.append("Please upload a resume file")
        elif resume.type not in ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
            validation_errors.append("Invalid file type - only PDF/DOCX allowed")
            
        # Text input validation
        if not job_desc.strip():
            validation_errors.append("Job description cannot be empty")
        elif len(job_desc.strip()) < 50:
            validation_errors.append("Job description too short (min 50 characters)")
            
        if not company_name.strip():
            validation_errors.append("Company name cannot be empty")
            
        # Payment validation
        if not st.session_state.payment_success:
            validation_errors.append("Payment verification failed - please complete payment")
            
        # Show all errors at once
        if validation_errors:
            for error in validation_errors:
                st.error(f"❌ {error}")
            st.stop()
        
        # Payment processing flow
        if not st.session_state.payment_success:
            with st.status("Payment Gateway", expanded=True) as status:
                st.write(":lock: Initializing secure payment session...")
                try:
                    payment_url = payment_processor.create_payment_session("user123")
                    st.session_state.payment_url = payment_url
                    # Extract session ID from Stripe URL format: https://checkout.stripe.com/pay/cs_test_abc123...
                    st.session_state.payment_session_id = payment_url.split("/pay/")[-1].split("#")[0]
                    status.update(
                        label="Payment Required", 
                        state="complete", 
                        expanded=False
                    )
                    st.markdown(f"""
                    <div style='padding: 15px; border-radius: 5px; background-color: #fff3cd;'>
                        ⚠️ Please [complete your payment]({payment_url}) to continue
                    </div>
                    """, unsafe_allow_html=True)
                    return
                except Exception as e:
                    st.error(f"Payment initialization failed: {str(e)}")
                    return
        
        # Document processing flow
        with st.status("Generating Cover Letter...", expanded=True) as status:
            progress_bar = st.progress(0)
            
            try:
                # Step 1: Resume parsing
                status.write(":page_facing_up: Parsing resume content...")
                with st.spinner("Extracting text..."):
                    resume_text = extract_resume_text(resume)
                    if not resume_text:
                        st.error("Failed to extract text from resume")
                        return
                progress_bar.progress(25)
                
                # Step 2: Payment verification
                status.write(":credit_card: Verifying payment completion...")
                with st.spinner("Checking transaction status..."):
                    if "payment_session_id" not in st.session_state:
                        st.error("No payment session found")
                        st.stop()
                        
                    payment_status = payment_processor.check_payment_status(
                        st.session_state.payment_session_id
                    )
                    
                    if payment_status != "paid":
                        st.error(f"Payment status: {payment_status}. Please complete payment")
                        st.stop()
                progress_bar.progress(50)
                
                # Step 3: AI generation
                status.write(":brain: Generating cover letter with GPT-4...")
                # Collect and display streaming response
                full_content = []
                response_container = st.empty()
                for chunk in generate_cover_letter(resume_text, job_desc, company_name):
                    if chunk:
                        full_content.append(chunk)
                        response_container.markdown("".join(full_content) + "▌")
                cover_letter = "".join(full_content)
                
                if not cover_letter:
                    st.error("Failed to generate cover letter")
                    return
                progress_bar.progress(75)
                
                # Step 4: Document creation
                status.write(":floppy_disk: Creating downloadable document...")
                with st.spinner("Formatting DOCX file..."):
                    doc_buffer = create_docx(cover_letter)
                progress_bar.progress(100)
                
                # Display results
                status.update(
                    label="Generation Complete!", 
                    state="complete", 
                    expanded=False
                )
                st.success("Cover letter created successfully")
                
                # Show preview and download
                with st.expander("Preview Cover Letter"):
                    st.write(cover_letter[:500] + "...")
                
                st.download_button(
                    label=":arrow_down: Download DOCX",
                    data=doc_buffer,
                    file_name="cover_letter.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    help="Save your AI-generated cover letter"
                )
                
            except Exception as e:
                st.error(f"Generation failed: {str(e)}")

if __name__ == "__main__":
    main()
