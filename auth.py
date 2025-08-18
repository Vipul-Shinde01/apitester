from functools import wraps
from flask import render_template, request, redirect, url_for, flash, session
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from app import app, db
from models import User
import os
from msal import ConfidentialClientApplication

CLIENT_ID = os.getenv("MS_CLIENT_ID")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
AUTHORITY = f"https://login.microsoftonline.com/{os.getenv('MS_TENANT_ID')}"
REDIRECT_PATH = "/auth/callback"
SCOPE = ["User.Read"]

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"

msal_app = ConfidentialClientApplication(
    CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def login_route():
    """Redirect to Microsoft login"""
    session["state"] = os.urandom(24).hex()
    auth_url = msal_app.get_authorization_request_url(
        scopes=SCOPE,
        state=session["state"],
        redirect_uri=url_for("auth_callback", _external=True),
    )
    return redirect(auth_url)


def signup_route():
    """Handle user registration"""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()

        # Validation
        errors = []

        if not username:
            errors.append("Username is required.")
        elif len(username) < 3:
            errors.append("Username must be at least 3 characters long.")
        elif User.query.filter_by(username=username).first():
            errors.append("Username already exists.")

        if not email:
            errors.append("Email is required.")
        elif User.query.filter_by(email=email).first():
            errors.append("Email already exists.")

        if not password:
            errors.append("Password is required.")
        elif len(password) < 6:
            errors.append("Password must be at least 6 characters long.")
        elif password != confirm_password:
            errors.append("Passwords do not match.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("signup.html")

        # Create new user
        try:
            user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            # Automatically log in the user
            login_user(user)
            flash(
                f"Account created successfully! Welcome, {user.get_display_name()}!",
                "success",
            )
            return redirect(url_for("index"))

        except Exception as e:
            db.session.rollback()
            flash(
                "An error occurred while creating your account. Please try again.",
                "error",
            )
            return render_template("signup.html")

    return render_template("signup.html")


def logout_route():
    """Handle user logout"""
    logout_user()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("landing"))


def require_login(f):
    """Decorator to require login for routes"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def auth_callback():
    """Microsoft OAuth callback"""
    if request.args.get("state") != session.get("state"):
        flash("Invalid login state.", "error")
        return redirect(url_for("login_route"))

    if "error" in request.args:
        flash(f"Login failed: {request.args['error_description']}", "error")
        return redirect(url_for("login_route"))

    code = request.args.get("code")
    result = msal_app.acquire_token_by_authorization_code(
        code, scopes=SCOPE, redirect_uri=url_for("auth_callback", _external=True)
    )

    if "id_token_claims" not in result:
        flash("Login failed. Please try again.", "error")
        return redirect(url_for("login_route"))

    profile = result["id_token_claims"]

    # Extract Microsoft user info
    email = profile.get("preferred_username")
    name = profile.get("name")

    # Check if user exists in DB
    user = User.query.filter_by(email=email).first()
    if not user:
        # Auto-provision new user
        user = User(email=email, username=email.split("@")[0], first_name=name)
        db.session.add(user)
        db.session.commit()

    login_user(user)
    flash(f"Welcome {user.first_name or user.username}!", "success")
    return redirect(url_for("index"))
