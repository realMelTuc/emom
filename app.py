import os
import sys
import traceback

try:
    from dotenv import load_dotenv
    from flask import Flask, jsonify, render_template, request
    from db import get_db, serialize_row
    load_dotenv('.env.emom')
    _BOOT_ERROR = None
except Exception as _e:
    _BOOT_ERROR = traceback.format_exc()
    from flask import Flask, jsonify
    def get_db(): raise RuntimeError('DB not available')
    def render_template(*a, **kw): return f'<pre>Boot error:\n{_BOOT_ERROR}</pre>'
    def serialize_row(r): return r
    class _R:
        path = ''
        method = ''
        endpoint = ''
        headers = {}
        remote_addr = ''
    request = _R()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'emom-dev-key')

if _BOOT_ERROR:
    @app.route('/')
    @app.route('/<path:p>')
    def boot_error(p=''):
        return f'<pre style="background:#0d1117;color:#ef4444;padding:20px;font-family:monospace">EMOM Boot Error:\n\n{_BOOT_ERROR}</pre>', 500

@app.errorhandler(Exception)
def handle_global_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    error_msg = str(e)
    tb = traceback.format_exc()
    print(f"Error: {error_msg}\n{tb}", file=sys.stderr)
    if request.path.startswith('/api/'):
        return jsonify({'error': error_msg}), 500
    return f'<pre style="background:#0d1117;color:#ef4444;padding:20px">{error_msg}</pre>', 500

blueprints_dir = os.path.join(os.path.dirname(__file__), 'blueprints')
sys.path.insert(0, os.path.dirname(__file__))

_bp_errors = []
if not _BOOT_ERROR:
    import importlib.util
    for filename in sorted(os.listdir(blueprints_dir)):
        if filename.endswith('.py') and filename != '__init__.py':
            module_name = filename[:-3]
            try:
                spec = importlib.util.spec_from_file_location(
                    module_name, os.path.join(blueprints_dir, filename))
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                if hasattr(module, 'bp'):
                    app.register_blueprint(module.bp)
            except Exception as e:
                _bp_errors.append(f'{filename}: {e}')


@app.route('/')
def index():
    return render_template('landing.html')


@app.route('/app/')
def app_shell():
    return render_template('shell.html')


@app.route('/api/health')
def health_check():
    return jsonify({'status': 'ok', 'app': 'EMOM', 'python': sys.version})


@app.route('/api/debug')
def debug_info():
    return jsonify({
        'boot_error': _BOOT_ERROR,
        'blueprint_errors': _bp_errors,
        'python': sys.version,
        'app': 'EMOM'
    })


@app.route('/api/migrate', methods=['POST'])
def migrate():
    """Create all EMOM tables if they don't exist."""
    conn = get_db()
    try:
        cur = conn.cursor()
        statements = [
            """CREATE TABLE IF NOT EXISTS emom_orders (
                id SERIAL PRIMARY KEY,
                order_id BIGINT UNIQUE,
                character_name VARCHAR(200),
                character_id BIGINT,
                type_name VARCHAR(200) NOT NULL,
                type_id INTEGER,
                location_name VARCHAR(200),
                station_id BIGINT,
                region_name VARCHAR(100),
                is_buy_order BOOLEAN DEFAULT FALSE,
                price NUMERIC(20,2) NOT NULL,
                volume_total INTEGER DEFAULT 1,
                volume_remain INTEGER DEFAULT 1,
                min_volume INTEGER DEFAULT 1,
                range VARCHAR(20) DEFAULT 'station',
                duration INTEGER DEFAULT 90,
                status VARCHAR(20) DEFAULT 'active',
                cost_basis NUMERIC(20,2),
                issued_at TIMESTAMP,
                expires_at TIMESTAMP,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )""",
            """CREATE TABLE IF NOT EXISTS emom_order_history (
                id SERIAL PRIMARY KEY,
                order_id INTEGER REFERENCES emom_orders(id) ON DELETE CASCADE,
                event_type VARCHAR(30) NOT NULL DEFAULT 'manual_update',
                old_value TEXT,
                new_value TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )""",
            """CREATE TABLE IF NOT EXISTS emom_snapshots (
                id SERIAL PRIMARY KEY,
                order_id INTEGER REFERENCES emom_orders(id) ON DELETE CASCADE,
                snapshot_date DATE DEFAULT CURRENT_DATE,
                price NUMERIC(20,2),
                volume_remain INTEGER,
                created_at TIMESTAMP DEFAULT NOW()
            )""",
        ]
        for stmt in statements:
            cur.execute(stmt)
        conn.commit()
        return jsonify({'ok': True, 'tables': 3})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5015, debug=os.environ.get('FLASK_DEBUG', '0') == '1', use_reloader=False)
