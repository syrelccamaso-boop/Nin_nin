import streamlit as st
import base64
import os
from supabase import create_client, Client
import re

st.set_page_config(
    page_title="Computer Monitoring and Management System", layout="centered"
)
# ==========================================
# suppabase connection
# ==========================================
supabase_url = "https://tulzhwumlzaidknodnob.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR1bHpod3VtbHphaWRrbm9kbm9iIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk3MzQ3ODIsImV4cCI6MjEwNTMxMDc4Mn0.RSvksN-9ZpPGO4R42Snr-5xkChJZA_v-YQjezXLegOQ"
supabase = create_client(supabase_url, supabase_key)

# ==========================================
# BACKGROUND IMAGE
# ==========================================

def set_background(image_file):
    with open(image_file, "rb") as file:
        encoded_image = base64.b64encode(file.read()).decode()

    st.markdown(
        f"""
        <style>

        /* BIG BACKGROUND IMAGE */
        .stApp {{
            background-image:
                linear-gradient(
                    rgba(0, 0, 0, 0.35),
                    rgba(0, 0, 0, 0.35)
                ),
                url("data:image/jpeg;base64,{encoded_image}");

            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}

        /* Center the login card */
        .block-container {{
            padding-top: 4rem;
        }}

        /* WHITE SECOND BACKGROUND */
        .st-key-login_card {{
            background-color: white;
            padding: 40px 42px 45px 42px;
            border-radius: 20px;
            width: 420px;
            margin: 40px auto;
            box-shadow: 0px 8px 30px rgba(0, 0, 0, 0.30);
        }}

        /* INPUT LABEL */
        .st-key-login_card label {{
            color: #333333 !important;
            font-size: 13px !important;
            font-weight: 600 !important;
        }}

        /* INPUT BOX */
        .st-key-login_card input {{
            height: 45px !important;
            background-color: white !important;
            border: 1px solid #cccccc !important;
            border-radius: 6px !important;
            color: #333333 !important;
            padding-left: 12px !important;
        }}

        /* INPUT FOCUS */
        .st-key-login_card input:focus {{
            border-color: #244966 !important;
            box-shadow: 0 0 0 1px #244966 !important;
        }}

        /* SIGN IN BUTTON */
        .st-key-login_card .stButton > button {{
            width: 100% !important;
            height: 45px !important;
            background-color: #244966 !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-size: 14px !important;
            font-weight: 600 !important;
            margin-top: 12px !important;
        }}

        .st-key-login_card .stButton > button:hover {{
            background-color: #18384f !important;
        }}

        </style>
        """,
        unsafe_allow_html=True
    )


# Get isu.jpg from the same folder as system.py
image_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "isu.jpg"
)
set_background(image_path)


# ==========================================
# LOGIN / SIGN UP MODE
# ==========================================

if "page" not in st.session_state:
    st.session_state.page = "login"


# ==========================================
# LOGIN PAGE
# ==========================================

if st.session_state.page == "login":

    with st.container(key="login_card"):

        st.markdown(
            """
            <h3 style="
                text-align:center;
                color:#243447;
                margin-bottom:1px;
                font-size:22px;
            ">
                College of Computing Studies, Information and Communication Technology
            </h3>

            <p style="
                text-align:center;
                color:#777777;
                font-size:17px;
                margin-bottom:10px;
                margin-top:1px;
            ">
                Computer Monitoring and Management System
            </p>
            """,
            unsafe_allow_html=True
        )

        # EMAIL
        email = st.text_input(
            "Email Address",
            placeholder="you@example.com"
        )

        # PASSWORD
        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password"
        )

        # REMEMBER ME
        col1, col2 = st.columns([1, 1])

        with col1:
            remember_me = st.checkbox("Remember Me")

        with col2:
            st.markdown(
                """
                <div style="
                    text-align:right;
                    margin-top:5px;
                ">
                    <span style="color:#3974a8;">
                        Forgot password?
                    </span>
                </div>
                """,
                unsafe_allow_html=True
            )

        # SIGN IN
        login = st.button(
            "Sign In",
            width=350
        )

        if login:

            if email == "" or password == "":
                st.warning("Please enter your email and password.")

            # FIXED EMAIL REGEX
            elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                st.warning("Invalid email address.")

            else:

                try:

                    response = supabase.auth.sign_in_with_password({
                        "email": email,
                        "password": password
                    })

                    if response.user:

                        st.success("Login successful!")

                        # Get user information from Users table
                        user_data = supabase.table("Users") \
                            .select("*") \
                            .eq("Id", response.user.id) \
                            .execute()

                        if user_data.data:

                            user = user_data.data[0]

                            st.write(
                                "Welcome,",
                                user["FullName"]
                            )

                            st.write(
                                "Role:",
                                user["Role"]
                            )

                        if remember_me:
                            st.info("Your login will be remembered.")

                except Exception as e:

                    st.error(
                        f"Login failed: {str(e)}"
                    )

        # SIGN UP LINK
        st.markdown(
            "<p style='text-align:center; color:#777; margin-top:20px;'>"
            "Don't have an account?"
            "</p>",
            unsafe_allow_html=True
        )

        signup_button = st.button(
            "Create an Account",
            width=350
        )

        if signup_button:
            st.session_state.page = "signup"
            st.rerun()


# ==========================================
# SIGN UP PAGE
# ==========================================

elif st.session_state.page == "signup":

    with st.container(key="login_card"):

        st.markdown(
            """
            <h3 style="
                text-align:center;
                color:#243447;
                margin-bottom:5px;
                font-size:24px;
            ">
                Create Account
            </h3>

            <p style="
                text-align:center;
                color:#777777;
                font-size:14px;
                margin-bottom:25px;
            ">
                Register your account
            </p>
            """,
            unsafe_allow_html=True
        )

        # FULL NAME
        full_name = st.text_input(
            "Full Name",
            placeholder="Enter your full name"
        )

        # EMAIL
        signup_email = st.text_input(
            "Email Address",
            placeholder="you@example.com"
        )

        # PASSWORD
        signup_password = st.text_input(
            "Password",
            type="password",
            placeholder="Create a password"
        )

        # CONFIRM PASSWORD
        confirm_password = st.text_input(
            "Confirm Password",
            type="password",
            placeholder="Confirm your password"
        )

        # ROLE
        role = st.selectbox(
            "Role",
            [
                "Student",
                "Teacher",
                "Admin"
            ]
        )

        # SIGN UP BUTTON
        signup = st.button(
            "Sign Up",
            width=350
        )

        if signup:

            if (
                full_name == ""
                or signup_email == ""
                or signup_password == ""
                or confirm_password == ""
            ):

                st.warning(
                    "Please complete all fields."
                )

            elif not re.match(
                r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                signup_email
            ):

                st.warning(
                    "Invalid email address."
                )

            elif signup_password != confirm_password:

                st.warning(
                    "Passwords do not match."
                )

            elif len(signup_password) < 6:

                st.warning(
                    "Password must be at least 6 characters."
                )

            else:

                try:

                    # ==========================================
                    # CREATE AUTH ACCOUNT
                    # ==========================================

                    response = supabase.auth.sign_up({
                        "email": signup_email,
                        "password": signup_password
                    })

                    if response.user:

                        user_id = response.user.id

                        # ==========================================
                        # SAVE USER INFORMATION
                        # ==========================================

                        supabase.table("Users").insert({
                            "Id": user_id,
                            "Email": signup_email,
                            "FullName": full_name,
                            "Role": role
                        }).execute()

                        st.success(
                            "Account created successfully!"
                        )

                        st.info(
                            "You can now sign in using your email and password."
                        )

                except Exception as e:

                    st.error(
                        f"Sign up failed: {str(e)}"
                    )

        # BACK TO LOGIN
        st.markdown(
            "<p style='text-align:center; color:#777; margin-top:20px;'>"
            "Already have an account?"
            "</p>",
            unsafe_allow_html=True
        )

        back_button = st.button(
            "Back to Login",
            width=350
        )

        if back_button:
            st.session_state.page = "login"
            st.rerun()