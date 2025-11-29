import streamlit as st
import os
import pandas as pd
from engine import StrataEngine

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="StrataScribe", page_icon="🏢", layout="centered")

# --- CSS FOR MOBILE FRIENDLINESS ---
st.markdown("""
<style>
    .stButton button { width: 100%; border-radius: 10px; height: 3em; }
</style>
""", unsafe_allow_html=True)

# --- AUTHENTICATION ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

def check_password():
    def password_entered():
        if st.session_state["password"] == "Wombat2025":
            st.session_state.authenticated = True
            del st.session_state["password"]
        else:
            st.session_state.authenticated = False
            
    if not st.session_state.authenticated:
        st.text_input("Enter Password:", type="password", on_change=password_entered, key="password")
        return False
    return True

if check_password():
    # --- SIDEBAR SETTINGS ---
    with st.sidebar:
        st.header("⚙️ Settings")
        # NEW: Strata Plan Number
        strata_plan_no = st.text_input("Strata Plan No.", "SP [Insert Number]")
        
        user_name = st.text_input("Your Name", "The Committee")
        user_title = st.text_input("Your Title", "Strata Managing Agent")
        
        st.divider()
        st.info("💡 **Tip:** Pass a by-law allowing recordings to ensure you are always covered legally.")
        st.caption("StrataScribe v1.8") # Removed "Legal Edition"

    # --- MAIN APP ---
    st.title("🏢 StrataScribe")
    st.write("### Meeting Dashboard")

    # --- LEGAL WARNING ---
    with st.expander("⚠️ Important Legal Notice regarding Recordings"):
        st.warning("""
        **NSW Surveillance Devices Act 2007:**
        It is generally an offense to record a 'private conversation' without the consent of all parties. 
        Strata meetings may be considered private conversations. 
        
        **Best Practice:**
        1. Obtain verbal consent at the start of the meeting.
        2. Pass a motion or by-law explicitly allowing recordings for minute-taking.
        """)

    if 'processed_data' not in st.session_state:
        st.session_state.processed_data = None
    if 'files_ready' not in st.session_state:
        st.session_state.files_ready = False

    uploaded_file = st.file_uploader("Tap to upload recording", type=['mp3', 'mp4', 'm4a', 'wav'])

    if uploaded_file is not None:
        temp_filename = "temp_upload.mp3"
        with open(temp_filename, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.divider()

        # --- THE CONSENT GATE ---
        consent = st.checkbox("✅ I confirm that I have obtained consent from all attendees to record this meeting.")

        if st.button("Start Processing 🚀", type="primary", disabled=not consent):
            engine = StrataEngine()
            
            with st.status("⚙️ Analyzing meeting...", expanded=True) as status:
                try:
                    status.write("🎧 Listening...")
                    text = engine.process_audio_robust(temp_filename)
                    
                    status.write("⚖️ Drafting minutes...")
                    # PASS THE STRATA PLAN NUMBER TO THE ENGINE
                    data = engine.analyze_text(text, strata_plan=strata_plan_no)
                    
                    status.write("📄 Finalizing documents...")
                    pdf_path = engine.generate_pdf(data, "Minutes.pdf")
                    csv_path = engine.generate_csv(data, "Actions.csv")
                    
                    # EMAIL CLEANUP + SIGNATURE
                    email_raw = data.get('email_draft', "")
                    if isinstance(email_raw, dict):
                         subject = email_raw.get('subject', 'Meeting Update')
                         body = email_raw.get('body', str(email_raw))
                         email_text = f"Subject: {subject}\n\n{body}"
                    else:
                         email_text = str(email_raw)
                    
                    email_text_clean = engine.clean_markdown(email_text)
                    
                    # SIGNATURE INJECTION (No Double-Up)
                    # We check if the user accidentally typed "Sincerely" in the prompt output (rare now)
                    signature_block = f"\n\nSincerely,\n\n{user_name}\n{user_title}"
                    if "Sincerely" not in email_text_clean:
                        email_text_clean += signature_block
                    
                    st.session_state.processed_data = {
                        'pdf': pdf_path,
                        'csv': csv_path,
                        'email': email_text_clean,
                        'actions_json': data.get('action_list', [])
                    }
                    st.session_state.files_ready = True
                    status.update(label="✅ Done!", state="complete", expanded=False)

                except Exception as e:
                    st.error(f"Error: {e}")
                
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)

    # --- DASHBOARD ---
    if st.session_state.files_ready and st.session_state.processed_data:
        data = st.session_state.processed_data
        st.success("Meeting Processed Successfully")
        
        tab1, tab2, tab3 = st.tabs(["📄 Minutes", "📋 Action Items", "📧 Email"])
        
        with tab1:
            if data['pdf']:
                with open(data['pdf'], "rb") as f:
                    st.download_button("Download PDF", f, "Minutes.pdf", "application/pdf")

        with tab2:
            if data['actions_json']:
                df = pd.DataFrame(data['actions_json'])
                st.dataframe(df, hide_index=True, use_container_width=True)
            if data['csv']:
                with open(data['csv'], "rb") as f:
                    st.download_button("Download Spreadsheet", f, "Actions.csv", "text/csv")

        with tab3:
            new_email = st.text_area("Edit before sending:", value=data['email'], height=300)