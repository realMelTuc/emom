from flask import Blueprint, render_template, jsonify, request
from db import get_db, serialize_row, ORDER_STATUSES, ORDER_RANGES, DURATION_OPTIONS

bp = Blueprint('settings', __name__)


@bp.route('/settings/')
def index():
    return render_template('partials/settings/index.html')


@bp.route('/api/settings/constants')
def api_constants():
    return jsonify({
        'order_statuses':  ORDER_STATUSES,
        'order_ranges':    ORDER_RANGES,
        'duration_options': DURATION_OPTIONS,
    })


@bp.route('/api/settings/stats')
def api_stats():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) AS cnt FROM emom_orders')
        orders_count = cur.fetchone()['cnt']
        cur.execute('SELECT COUNT(*) AS cnt FROM emom_order_history')
        history_count = cur.fetchone()['cnt']
        cur.execute('SELECT COUNT(*) AS cnt FROM emom_snapshots')
        snapshots_count = cur.fetchone()['cnt']
        return jsonify({
            'orders':    int(orders_count),
            'history':   int(history_count),
            'snapshots': int(snapshots_count),
        })
    finally:
        conn.close()


@bp.route('/api/settings/bulk-status', methods=['POST'])
def api_bulk_status():
    data = request.get_json(force=True)
    ids    = data.get('ids', [])
    status = data.get('status', '')
    if not ids or not status:
        return jsonify({'error': 'ids and status required'}), 400
    if status not in ORDER_STATUSES:
        return jsonify({'error': f'Invalid status: {status}'}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        placeholders = ', '.join(['%s'] * len(ids))
        cur.execute(f"""
            UPDATE emom_orders
            SET status = %s, updated_at = NOW()
            WHERE id IN ({placeholders})
        """, [status] + list(ids))
        count = cur.rowcount
        conn.commit()
        return jsonify({'ok': True, 'updated': count})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@bp.route('/api/settings/purge-expired', methods=['POST'])
def api_purge_expired():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM emom_orders
            WHERE status IN ('expired', 'cancelled')
              AND updated_at < NOW() - INTERVAL '30 days'
        """)
        count = cur.rowcount
        conn.commit()
        return jsonify({'ok': True, 'deleted': count})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
