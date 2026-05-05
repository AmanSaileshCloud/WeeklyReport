import os
import streamlit as st
from utils.db_handler import authenticate_user, get_user_by_email

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "logo.png")

def login_page(guest_mode=False):
    st.markdown("""
<style>
[data-testid='stImage'] img { mix-blend-mode: screen; }
[data-testid="stApp"] {
    display: flex !important;
    align-items: center !important;
    min-height: 100vh !important;
}
[data-testid="stAppViewContainer"] { width: 100% !important; }
.main .block-container {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    width: 100% !important;
}
</style>
""", unsafe_allow_html=True)

    # Outer centering gutters — card occupies middle 50% of viewport
    _, center, _ = st.columns([1, 2, 1])

    with center:
        with st.container(border=True):
            img_col, form_col = st.columns([4, 5])

            with img_col:
                st.image(_LOGO_PATH, use_container_width=True)

            with form_col:
                st.markdown("## Login")

                with st.form("login_form"):
                    email    = st.text_input("E-mail")
                    password = st.text_input("Password", type="password")
                    submitted = st.form_submit_button("Login", use_container_width=True)

                if submitted:
                    if not (email and password):
                        st.error("Please provide email and password.")
                    else:
                        with st.spinner("Authenticating..."):
                            ok = authenticate_user(email, password)
                        if ok:
                            from utils.db_handler import create_session_token
                            user  = get_user_by_email(email)
                            token = create_session_token(email)
                            st.session_state['authenticated'] = True
                            st.session_state['page']          = 'app'
                            st.session_state['email']         = email
                            st.session_state['name']          = user.get('name', email.split('@')[0]) if user else email.split('@')[0]
                            st.session_state['role']          = user.get('role', 'viewer') if user else 'viewer'
                            st.session_state['pending_token'] = token
                            st.rerun()
                        else:
                            st.error("Invalid email or password.")

                if st.button("Sign Up", use_container_width=True):
                    st.session_state['page'] = 'signup'
                    st.rerun()

                if guest_mode:
                    if st.button("Continue as Guest", use_container_width=True):
                        st.session_state['guest_mode']    = True
                        st.session_state['authenticated'] = True
                        st.session_state['page']          = 'app'
                        st.rerun()
