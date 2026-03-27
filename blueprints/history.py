from flask import Blueprint, render_template, jsonify, request
from db import get_db, serialize_row

bp = Blueprint('history', __name__)


@bp.route('/history/')
def index():
    return render_template('partials/history/index.html')


@bp.route('/api/history')
def api_list():
    order_id  = request.args.get('order_id', type=int)
    event_type = request.args.get('event_type', '').strip()
    limit     = min(int(request.args.get('limit', 100)), 500)

    where = []
    params = []

    if order_id:
        where.append('h.order_id = %s')
        params.append(order_id)

    if event_type:
        where.append('h.event_type = %s')
        params.append(event_type)

    clause = ('WHERE ' + ' AND '.join(where)) if where else ''

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT h.id, h.order_id, h.event_type, h.old_value, h.new_value,
                   h.notes, h.created_at,
                   o.type_name, o.is_buy_order, o.character_name
            FROM emom_order_history h
            LEFT JOIN emom_orders o ON o.id = h.order_id
            {clause}
            ORDER BY h.created_at DESC
            LIMIT %s
        """, params + [limit])
        rows = [serialize_row(r) for r in cur.fetchall()]
        return jsonify({'history': rows, 'count': len(rows)})
    finally:
        conn.close()


@bp.route('/api/history/order/<int:order_id>')
def api_order_history(order_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_type, old_value, new_value, notes, created_at
            FROM emom_order_history
            WHERE order_id = %s
            ORDER BY created_at DESC
            LIMIT 200
        """, [order_id])
        rows = [serialize_row(r) for r in cur.fetchall()]
        return jsonify({'history': rows})
    finally:
        conn.close()


@bp.route('/api/history/note', methods=['POST'])
def api_add_note():
    data = request.get_json(force=True)
    order_id = data.get('order_id')
    notes = data.get('notes', '').strip()
    if not order_id or not notes:
        return jsonify({'error': 'order_id and notes required'}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO emom_order_history (order_id, event_type, notes)
            VALUES (%s, 'note', %s)
        """, [order_id, notes])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
