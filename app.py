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

def get_hog_features(cv2_img):
    """
    Extracts HOG features.
    Standardizes image size to 128x64 for a consistent feature vector length.
    """
    # 1. Pre-processing: Grayscale and Resize
    gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (128, 64)) 
    
    # 2. Feature Extraction
    # orientations=9, pixels_per_cell=(8,8) are standard robust settings
    features = hog(resized, orientations=9, pixels_per_cell=(8, 8),
                   cells_per_block=(2, 2), visualize=False)
    return features

def base64_to_cv2(b64_string):
    img_data = base64.b64decode(b64_string)
    nparr = np.frombuffer(img_data, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

def cv2_to_base64(img):
    _, buffer = cv2.imencode('.png', img)
    return base64.b64encode(buffer).decode('utf-8')

@app.route('/api/save_reference', methods=['POST'])
def save_reference():
    data = request.get_json()
    user_id = data.get('user_id')
    reference_b64 = data.get('reference_b64')
    
    if not user_id or not reference_b64:
        return jsonify({"success": False, "message": "Missing ID or Image"}), 400

    file_path = os.path.join(STORAGE_DIR, f"{user_id}_reference.png")
    cv2.imwrite(file_path, base64_to_cv2(reference_b64))

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users VALUES (?, ?)', (user_id, file_path))
    conn.commit()
    conn.close()
            
    return jsonify({"success": True, "message": "Reference saved."})

@app.route('/api/recognize', methods=['POST'])
def recognize():
    data = request.get_json()
    input_img = base64_to_cv2(data.get('input_image_b64'))
    reference_img = base64_to_cv2(data.get('reference_image_b64'))
    
    # Extract HOG vectors
    input_vec = get_hog_features(input_img)
    ref_vec = get_hog_features(reference_img)
    
    # Calculate Euclidean Distance -->k-NN algorithm(lower is better/more similar)
    dist = euclidean(input_vec, ref_vec)
    
    # Convert distance to a 0-100 similarity score
    # A distance of 0 is 100% match. Thresholding dist at ~10.0 for 0% match.
    similarity = max(0, 100 - (dist * 10)) 
    
    # Match logic: if distance is small enough, it's a match
    # 80.0 is a good starting threshold for HOG-based signature matching
    is_match = similarity > 80.0 
    
    return jsonify({
        "success": True, 
        "is_match": bool(is_match), 
        "similarity": round(similarity, 2)
    })

@app.route('/api/get_reference', methods=['GET'])
def get_reference():
    user_id = request.args.get('userId')
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT reference_signature_path FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and os.path.exists(row[0]):
        img = cv2.imread(row[0])
        return jsonify({"success": True, "signatureB64": cv2_to_base64(img)})
    return jsonify({"success": False, "message": "User not found"}), 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)