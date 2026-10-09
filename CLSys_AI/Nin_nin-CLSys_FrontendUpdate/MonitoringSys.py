import streamlit as st
import base64

st.set_page_config(
    page_title="Login",
    layout="centered"
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


set_background("isu.jpg")


# ==========================================
# WHITE CARD
# ==========================================

with st.container(key="login_card"):

    st.markdown(
        """
        <h2 style="
            text-align:center;
            color:#243447;
            margin-bottom:5px;
        ">
            Login
        </h2>

        <p style="
            text-align:center;
            color:#777777;
            font-size:13px;
            margin-bottom:28px;
        ">
            Sign in to your account
        </p>
        """,
        unsafe_allow_html=True
    )

    # EMAIL
    email = st.text_input(
        "Email Address",
        placeholder="Enter your email"
    )

    # PASSWORD
    password = st.text_input(
        "Password",
        type="password",
        placeholder="Enter your password"
    )

    # REMEMBER ME / FORGOT PASSWORD
    st.markdown(
        """
        <div style="
            display:flex;
            justify-content:space-between;
            font-size:12px;
            margin-top:3px;
            margin-bottom:8px;
        ">
            <span style="color:#777777;">
                ☐ Remember Me
            </span>

            <span style="color:#3974a8;">
                Forgot password?
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    # BUTTON
    login = st.button("↪  Sign In")

    # LOGIN CHECK
    if login:

        if email == "" or password == "":
            st.warning("Please enter your email and password.")

        else:
            st.success("Login successful!")