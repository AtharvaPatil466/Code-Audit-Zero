from flask import Flask, request, jsonify, send_file
import sqlite3
import os
import requests
import json
import uuid

app = Flask(__name__)

# Basic in-memory Database for SQLi Auth Bypass
def init_db():
    conn = sqlite3.connect(':memory:')
    c = conn.cursor()
    c.execute('''CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, secret_token TEXT)''')
    c.execute("INSERT INTO users (username, password, role, secret_token) VALUES ('admin', 'supersecret_admin_pass123!', 'admin', 'LEGACY_ADMIN_555')")
    c.execute("INSERT INTO users (username, password, role, secret_token) VALUES ('guest', 'guest', 'user', 'none')")
    conn.commit()
    return conn

# Needs to be global for in-memory persistence across requests in a simple dev setup
db_conn = init_db()


@app.route('/api/login', methods=['POST'])
def login():
    """Vulnerable to SQL Injection (Auth bypass)"""
    data = request.json or {}
    username = data.get('username', '')
    password = data.get('password', '')
    
    # VULNERABILITY: String concatenation SQLi
    query = f"SELECT role, secret_token FROM users WHERE username='{username}' AND password='{password}'"
    
    try:
        c = db_conn.cursor()
        c.execute(query)
        result = c.fetchone()
        
        if result:
            role, token = result
            return jsonify({"status": "success", "role": role, "token": token}), 200
        else:
            return jsonify({"status": "error", "message": "Invalid credentials"}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/download', methods=['GET'])
def download_file():
    """Vulnerable to Path Traversal (LFI)"""
    file_path = request.args.get('file')
    if not file_path:
        return jsonify({"status": "error", "message": "Missing 'file' parameter"}), 400
        
    # Create a safe base directory and a dummy config file
    base_dir = os.path.join(os.getcwd(), 'public_files')
    os.makedirs(base_dir, exist_ok=True)
    with open(os.path.join(base_dir, 'app_config.json'), 'w') as f:
         f.write('{"public_key": "12345"}')

    # Also make sure there's a sensitive file elsewhere to steal
    with open('secret_config.json', 'w') as f:
         f.write('{"jwt_secret": "SUPERSAFE_JWT_SIGNING_KEY_999"}')
         
    # VULNERABILITY: No sanitization of path traversal characters (../)
    target_path = os.path.join(base_dir, file_path)
    
    try:
        if os.path.exists(target_path) and os.path.isfile(target_path):
            with open(target_path, 'r') as f:
                content = f.read()
            return jsonify({"status": "success", "file": file_path, "content": content}), 200
        else:
            return jsonify({"status": "error", "message": "File not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/fetch', methods=['POST'])
def fetch_url():
    """Vulnerable to Server-Side Request Forgery (SSRF)"""
    data = request.json or {}
    target_url = data.get('url')
    
    if not target_url:
        return jsonify({"status": "error", "message": "Missing 'url' parameter"}), 400
        
    # VULNERABILITY: Blindly fetching user-supplied URLs without validation
    try:
        # We simulate a sensitive internal endpoint locally
        if target_url == "http://localhost:8001/internal/admin":
            return jsonify({"status": "success", "data": "INTERNAL_ADMIN_DASHBOARD_TOKEN_777"}), 200
            
        response = requests.get(target_url, timeout=2)
        return jsonify({"status": "success", "fetched_content": response.text[:200]}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": "Fetch failed"}), 500


@app.route('/internal/admin', methods=['GET'])
def internal_admin():
    """Simulates an internal-only admin endpoint that SSRF can hit"""
    return jsonify({"status": "success", "secret": "INTERNAL_ADMIN_DASHBOARD_TOKEN_777"}), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == '__main__':
    # Run slightly differently than the main target_app (which is FastAPI on 8000)
    print("Starting Target App 2 (Flask) on port 8001...")
    # Initialize the decoy file
    with open('secret_config.json', 'w') as f:
         f.write('{"jwt_secret": "SUPERSAFE_JWT_SIGNING_KEY_999"}')
    app.run(host='0.0.0.0', port=8001, debug=False)
