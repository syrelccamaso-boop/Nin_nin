import streamlit as st
import base64
import re

st.set_page_config(
    page_title="Computer Monitoring and Management System", layout="centered"
)

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
            font-size: 12px !important;
            font-weight: 600 !important;
            margin-top: 12px !important;
        }}

        .st-key-login_card .stButton > button:hover {{
            transform: translateY(5px);
            box-shadow: 0 5px 0 #8A795D;
        }}

        </style>
        """,
        unsafe_allow_html=True,
    )


set_background("C:/Users/Asus/Downloads/isu.jpg")


# ==========================================
# WHITE CARD
# ==========================================

with st.container(key="login_card"):

    st.markdown(
        """
        <h3 style="
            text-align:center;
            color:#243447;
            margin-bottom:1px;
            font-size: 22px;
        ">
            College of Computing Studies, Information and Communication Technology
        </h3>

        <h3 style="
            text-align:center;
            color:#777777;
            font-size:17px;
            margin-bottom:10px;
            margin-top: 1px;
        ">
            Computer Monitoring and Management System
        </h3>
        """,
        unsafe_allow_html=True,
    )

    # EMAIL
    email = st.text_input("Email Address", placeholder="you@example.com")

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        st.warning("Invalid email address.")

    # PASSWORD
    password = st.text_input(
        "Password", type="password", placeholder="Enter your password"
    )

    # ==========================================
    # REMEMBER ME / FORGOT PASSWORD
    # ==========================================

    col1, col2 = st.columns([1, 1])

    # Remember Me
    with col1:
        remember_me = st.checkbox("Remember Me")

    # Forgot Password
with col2:
    st.markdown(
        """
      <div class="forgot-password">
        <a href="#" onclick="return false;">
         Forgot password?
        </a>
      </div>
      """,
        unsafe_allow_html=True,
    )

    # ==========================================
    # SIGN IN BUTTON
    # ==========================================

    login = st.button("Sign In", width=350)

    # ==========================================
    # LOGIN CHECK
    # ==========================================

    if login:

        if email == "" or password == "":
            st.warning("Please enter your email and password.")

        else:
            st.success("Login successful!")

            if remember_me:
                st.info("Your login will be remembered.")
