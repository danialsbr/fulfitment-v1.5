from flask import Flask, request, jsonify, session
from flask_cors import CORS
import pandas as pd
from datetime import datetime
from khayyam import JalaliDatetime
import os
import time
import uuid
import json

app = Flask(__name__)
CORS(app)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['LOGS_FOLDER'] = 'logs'
app.secret_key = 'your-secret-key'

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['LOGS_FOLDER'], exist_ok=True)

# In-memory databases
orders_db = {}

def get_log_file_path():
    """Get the current day's log file path."""
    current_date = JalaliDatetime.now().strftime("%Y-%m-%d")
    return os.path.join(app.config['LOGS_FOLDER'], f'log_{current_date}.json')

def load_logs():
    """Load logs from the current day's file."""
    log_file = get_log_file_path()
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_logs(logs):
    """Save logs to the current day's file."""
    log_file = get_log_file_path()
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

def add_log(message, status='success', details=None):
    """Add a log entry."""
    logs = load_logs()
    log_entry = {
        'id': str(uuid.uuid4()),
        'timestamp': JalaliDatetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        'message': message,
        'status': status,
        'details': details
    }
    logs.append(log_entry)
    save_logs(logs)
    return log_entry

@app.route('/api/ping', methods=['GET'])
def ping():
    """Simple ping endpoint for health checks."""
    return jsonify({
        'success': True,
        'message': 'pong',
        'timestamp': JalaliDatetime.now().strftime("%Y/%m/%d %H:%M:%S")
    })

@app.route('/api/system/status', methods=['GET'])
def system_status():
    """Get system status."""
    logs = load_logs()
    return jsonify({
        'success': True,
        'data': {
            'status': 'operational',
            'message': 'System is running normally',
            'timestamp': JalaliDatetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            'stats': {
                'total_orders': len(orders_db),
                'total_logs': len(logs)
            }
        }
    })

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get system logs."""
    logs = load_logs()
    return jsonify({
        'success': True,
        'data': logs,
        'message': 'Logs retrieved successfully'
    })

@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Get all orders."""
    orders_list = []
    for order_id, order_data in orders_db.items():
        for sku, details in order_data['SKUs'].items():
            orders_list.append({
                'id': order_id,
                'sku': sku,
                'title': details['Title'],
                'color': details['Color'],
                'quantity': details['Quantity'],
                'scanned': details['Scanned'],
                'status': 'Fulfilled' if details['Scanned'] >= details['Quantity'] else 'Pending',
                'price': details['Price'],
                'state': order_data.get('State'),
                'city': order_data.get('City'),
                'payment': order_data.get('Payment')
            })
    return jsonify({
        'success': True,
        'data': orders_list,
        'message': 'Orders retrieved successfully'
    })

@app.route('/api/orders/<order_id>', methods=['GET'])
def get_order(order_id):
    """Get a specific order."""
    if order_id not in orders_db:
        add_log(f'Order not found: {order_id}', 'error')
        return jsonify({
            'success': False,
            'message': 'Order not found'
        }), 404

    return jsonify({
        'success': True,
        'data': orders_db[order_id],
        'message': 'Order retrieved successfully'
    })

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload and process Excel file."""
    if 'file' not in request.files:
        add_log('File upload failed', 'error', 'No file provided')
        return jsonify({
            'success': False,
            'message': 'No file provided'
        }), 400

    file = request.files['file']
    if not file.filename.endswith('.xlsx'):
        add_log('File upload failed', 'error', 'Invalid file format')
        return jsonify({
            'success': False,
            'message': 'Invalid file format'
        }), 400

    try:
        # Save file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        
        # Read Excel file
        df = pd.read_excel(file_path)
        
        # Column mapping (Persian to English)
        column_mapping = {
            'سریال': 'OrderID',
            'لیست سفارشات - کد محصول': 'SKU',
            'لیست سفارشات - شرح محصول': 'Title',
            'رنگ': 'Color',
            'تعداد درخواستی': 'Quantity',
            'لیست سفارشات - قیمت لیبل': 'Price',
            'استان': 'State',
            'شهر': 'City',
            'مبلغ پرداختی': 'Payment'
        }

        # Check required columns
        missing_columns = [col for col in column_mapping.keys() if col not in df.columns]
        if missing_columns:
            error_msg = f"Missing required columns: {', '.join(missing_columns)}"
            add_log('File processing failed', 'error', error_msg)
            return jsonify({
                'success': False,
                'message': error_msg
            }), 400

        # Rename columns
        df.rename(columns=column_mapping, inplace=True)

        # Process orders
        processed_count = 0
        for _, row in df.iterrows():
            order_id = str(row['OrderID'])
            if order_id not in orders_db:
                orders_db[order_id] = {
                    'SKUs': {},
                    'State': row['State'],
                    'City': row['City'],
                    'Payment': f"{int(float(row['Payment'])):,}" if pd.notna(row['Payment']) else None,
                    'Status': 'Pending'
                }
            
            sku = str(row['SKU'])
            orders_db[order_id]['SKUs'][sku] = {
                'Title': row['Title'],
                'Color': row['Color'],
                'Quantity': int(row['Quantity']) if pd.notna(row['Quantity']) else 0,
                'Scanned': 0,
                'Price': f"{int(float(row['Price'])):,}" if pd.notna(row['Price']) else "0",
            }
            processed_count += 1

        add_log('File uploaded successfully', 'success', f'Processed {processed_count} orders')
        return jsonify({
            'success': True,
            'message': 'File uploaded and processed successfully',
            'data': {
                'processed_count': processed_count
            }
        })

    except Exception as e:
        error_msg = str(e)
        add_log('File processing failed', 'error', error_msg)
        return jsonify({
            'success': False,
            'message': f'Error processing file: {error_msg}'
        }), 500

@app.route('/api/scan', methods=['POST'])
def scan_order():
    """Scan an order item."""
    data = request.json
    order_id = data.get('orderId')
    sku = data.get('sku')
    
    if not order_id or not sku:
        add_log('Scan failed', 'error', 'Missing required fields')
        return jsonify({
            'success': False,
            'message': 'Missing required fields'
        }), 400
        
    if order_id not in orders_db or sku not in orders_db[order_id]['SKUs']:
        add_log('Scan failed', 'error', f'Order {order_id} or SKU {sku} not found')
        return jsonify({
            'success': False,
            'message': 'Order or SKU not found'
        }), 404
        
    # Update scanned count
    orders_db[order_id]['SKUs'][sku]['Scanned'] += 1
    current_count = orders_db[order_id]['SKUs'][sku]['Scanned']
    
    # Update scan timestamp
    scan_time = JalaliDatetime.now().strftime("%Y/%m/%d %H:%M")
    orders_db[order_id]['SKUs'][sku]['ScanTimestamp'] = scan_time
    
    add_log(
        f'Item scanned: Order {order_id}, SKU {sku}',
        'success',
        f'Scanned count: {current_count}'
    )
    
    return jsonify({
        'success': True,
        'message': 'Scan successful'
    })

if __name__ == '__main__':
    app.run(debug=True, port=5001)