import sqlite3
import os
import base64
import numpy as np
import cv2
from flask import Flask, request, jsonify
from flask_cors import CORS

# Lightweight ML Imports
from skimage.feature import hog
from scipy.spatial.distance import euclidean

# --- CONFIGURATION ---
DATABASE_NAME = 'signature_db.sqlite'
STORAGE_DIR = 'signatures_storage'

app = Flask(__name__)
CORS(app) 

def init_db():
    """Initializes the database and creates the storage folder if missing."""
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR, exist_ok=True)
        
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            reference_signature_path TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def base64_to_cv2(b64_string):
    """Converts base64 string to a CV2 image."""
    img_data = base64.b64decode(b64_string)
    nparr = np.frombuffer(img_data, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

def calculate_mse(img1, img2):
    """
    Calculates Mean Squared Error (MSE) between two images.
    Used for signature comparison logic.
    """
    # Resize to identical dimensions for comparison
    img1 = cv2.resize(img1, (300, 150))
    img2 = cv2.resize(img2, (300, 150))
    
    # Convert to grayscale
    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    
    # MSE Formula: sum of squared differences / total pixels
    err = np.sum((gray1.astype("float") - gray2.astype("float")) ** 2)
    err /= float(gray1.shape[0] * gray1.shape[1])
    return err

def get_hog_features(cv2_img):
    """Extracts HOG features for signature matching."""
    gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (128, 64)) 
    features, _ = hog(resized, orientations=9, pixels_per_cell=(8, 8),
                    cells_per_block=(2, 2), visualize=True)
    return features

@app.route('/api/upload_reference', methods=['POST'])
def upload_reference():
    data = request.json
    user_id = data.get('userId')
    img_b64 = data.get('imageB64')
    
    if not user_id or not img_b64:
        return jsonify({"success": False, "error": "Missing data"}), 400

    # Use os.path.join for Linux compatibility
    filename = f"{user_id}_reference.png"
    file_path = os.path.join(STORAGE_DIR, filename)
    
    # Save the reference image
    with open(file_path, "wb") as fh:
        fh.write(base64.decodebytes(img_b64.encode()))
    
    # Update Database
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, reference_signature_path) VALUES (?, ?)', 
                   (user_id, file_path))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "Reference uploaded successfully"})

@app.route('/api/recognize', methods=['POST'])
def recognize():
    data = request.json
    input_img = base64_to_cv2(data.get('input_image_b64'))
    reference_img = base64_to_cv2(data.get('reference_image_b64'))
    
    # 1. MSE Calculation
    mse_value = calculate_mse(input_img, reference_img)
    
    # 2. HOG + Euclidean Distance
    input_vec = get_hog_features(input_img)
    ref_vec = get_hog_features(reference_img)
    dist = euclidean(input_vec, ref_vec)
    
    # Similarity logic
    similarity = max(0, 100 - (dist * 10)) 
    
    # Decision threshold (Adjust these values for your lab demo)
    is_match = similarity > 75.0 and mse_value < 5000 
    
    return jsonify({
        "success": True, 
        "is_match": bool(is_match), 
        "similarity": round(similarity, 2),
        "mse_score": round(mse_value, 2)
    })

@app.route('/api/get_reference', methods=['GET'])
def get_reference():
    user_id = request.args.get('userId')
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT reference_signature_path FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        file_path = row[0]
        # Check if file exists on disk (using joined path)
        if os.path.exists(file_path):
            with open(file_path, "rb") as img_file:
                b64_string = base64.b64encode(img_file.read()).decode('utf-8')
            return jsonify({"success": True, "signatureB64": b64_string})
    
    return jsonify({"success": False, "error": "User not found"}), 404

if __name__ == '__main__':
    init_db()
    # Port configuration for Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)