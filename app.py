from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify
import os
import zipfile
import threading
import time
import shutil
from datetime import datetime
import instaloader
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Background task status
STATUS = {
    "running": False,
    "progress": 0,
    "total": "???",
    "message": "Ready",
    "zip_path": None,
    "username": None
}

def create_zip_and_cleanup(folder):
    zip_path = f"temp_downloads/{folder}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(f"temp_downloads/{folder}"):
            for f in files:
                full_path = os.path.join(root, f)
                arcname = os.path.relpath(full_path, f"temp_downloads/{folder}")
                zf.write(full_path, arcname)
    return zip_path

def download_worker(username, password, max_posts, date_from, date_to):
    global STATUS
    folder_name = secure_filename(username)
    download_dir = f"temp_downloads/{folder_name}"
    os.makedirs(download_dir, exist_ok=True)

    try:
        L = instaloader.Instaloader(
            dirname_pattern=download_dir + "/{target}",
            download_video_thumbnails=True,
            save_metadata=True,
            compress_json=False,
            filename_pattern="{date_utc}_{shortcode}"
        )

        # Login if password provided
        if password:
            STATUS["message"] = "Logging in..."
            L.login(username, password)
            STATUS["message"] = f"Logged in as @{username}"

        profile = instaloader.Profile.from_username(L.context, username)
        posts = profile.get_posts()

        count = 0
        total_estimate = max_posts or 200

        STATUS["total"] = str(total_estimate)
        STATUS["message"] = "Downloading posts..."

        for post in posts:
            if max_posts and count >= max_posts:
                break
            if date_from and post.date_utc < date_from:
                break
            if date_to and post.date_utc > date_to:
                continue

            try:
                L.download_post(post, target=username)
                count += 1
                STATUS["progress"] = count
                time.sleep(2.5)  # Be gentle with Instagram
            except Exception as e:
                print(f"Post failed: {e}")

            if count % 5 == 0:
                STATUS["message"] = f"Downloaded {count} posts..."

        # Create ZIP
        STATUS["message"] = "Creating ZIP file..."
        zip_path = create_zip_and_cleanup(folder_name)
        STATUS["zip_path"] = zip_path
        STATUS["message"] = f"Ready! Downloaded {count} posts"
        STATUS["running"] = False

    except instaloader.exceptions.LoginRequiredException:
        STATUS["message"] = "Login failed – private profile requires correct credentials"
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        STATUS["message"] = "2FA enabled – not supported (use app password or disable 2FA)"
    except instaloader.exceptions.ConnectionException:
        STATUS["message"] = "Blocked by Instagram – try again later"
    except Exception as e:
        STATUS["message"] = f"Error: {str(e)}"
    finally:
        STATUS["running"] = False

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        target = request.form["target_username"].strip().lstrip("@")
        login_user = request.form["login_username"].strip()
        login_pass = request.form["login_password"]
        max_p = request.form.get("max_posts", "")
        max_posts = int(max_p) if max_p.isdigit() else None

        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        date_from = datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
        date_to = datetime.strptime(date_to, "%Y-%m-%d") if date_to else None

        if not target:
            flash("Please enter a username to download")
            return redirect("/")

        # Reset & start
        global STATUS
        STATUS = {
            "running": True,
            "progress": 0,
            "total": "???",
            "message": "Starting download...",
            "zip_path": None,
            "username": target
        }

        thread = threading.Thread(
            target=download_worker,
            args=(target, login_pass if login_user else "", max_posts, date_from, date_to)
        )
        thread.daemon = True
        thread.start()

        return redirect("/status")

    return render_template("index.html")

@app.route("/status")
def status_page():
    return render_template("status.html", status=STATUS)

@app.route("/api/status")
def api_status():
    return jsonify(STATUS)

@app.route("/download")
def download_file():
    if STATUS.get("zip_path") and os.path.exists(STATUS["zip_path"]):
        response = send_file(
            STATUS["zip_path"],
            as_attachment=True,
            download_name=f"{STATUS['username']}_instagram_posts.zip",
            mimetype="application/zip"
        )
        # Optional: clean up after send
        return response
    flash("File not ready yet")
    return redirect("/status")

@app.route("/cancel")
def cancel():
    global STATUS
    STATUS = {"running": False, "progress": 0, "message": "Cancelled", "zip_path": None}
    shutil.rmtree("temp_downloads", ignore_errors=True)
    return redirect("/")

if __name__ == "__main__":
    os.makedirs("temp_downloads", exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=False)
