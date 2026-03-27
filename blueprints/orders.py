from flask import Blueprint, render_template, jsonify, request
from db import get_db, serialize_row, calc_margin, calc_total_value, calc_pct_filled
from db import ORDER_STATUSES, ORDER_RANGES, DURATION_OPTIONS

bp = Blueprint('orders', __name__)


@bp.route('/orders/')
def index():
    return render_template('partials/orders/index.html')


@bp.route('/orders/<int:order_id>/')
def detail(order_id):
    return render_template('partials/orders/detail.html', order_id=order_id)


@bp.route('/api/orders')
def api_list():
    order_type = request.args.get('type', '')
    status     = request.args.get('status', '')
    search     = request.args.get('q', '').strip()
    region     = request.args.get('region', '').strip()
    expiring   = request.args.get('expiring', '')
    sort       = request.args.get('sort', 'updated_at')
    direction  = request.args.get('dir', 'desc').upper()
    if direction not in ('ASC', 'DESC'):
        direction = 'DESC'

    allowed_sorts = {'updated_at', 'price', 'volume_remain', 'type_name',
                     'expires_at', 'issued_at', 'created_at'}
    if sort not in allowed_sorts:
        sort = 'updated_at'

    where = []
    params = []

    if order_type == 'buy':
        where.append('is_buy_order = TRUE')
    elif order_type == 'sell':
        where.append('is_buy_order = FALSE')

    if status:
        where.append('status = %s')
        params.append(status)

    if search:
        where.append('(type_name ILIKE %s OR location_name ILIKE %s OR character_name ILIKE %s)')
        params += [f'%{search}%', f'%{search}%', f'%{search}%']

    if region:
        where.append('region_name ILIKE %s')
        params.append(f'%{region}%')

    if expiring == '1':
        where.append("expires_at IS NOT NULL AND expires_at <= NOW() + INTERVAL '24 hours' AND status = 'active'")

    clause = ('WHERE ' + ' AND '.join(where)) if where else ''

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, order_id, character_name, type_name, type_id,
                   location_name, region_name, is_buy_order,
                   price, volume_total, volume_remain, min_volume,
                   range, duration, status, cost_basis,
                   issued_at, expires_at, notes, created_at, updated_at
            FROM emom_orders
            {clause}
            ORDER BY {sort} {direction}
            LIMIT 500
        """, params if params else None)
        rows = [serialize_row(r) for r in cur.fetchall()]

        for r in rows:
            r['pct_filled'] = calc_pct_filled(r['volume_total'], r['volume_remain'])
            r['total_value'] = calc_total_value(r['price'], r['volume_remain'])
            if not r['is_buy_order'] and r['cost_basis']:
                r['margin_pct'], r['profit_per_unit'] = calc_margin(r['price'], r['cost_basis'])
            else:
                r['margin_pct'] = None
                r['profit_per_unit'] = None

        return jsonify({'orders': rows, 'count': len(rows)})
    finally:
        conn.close()


@bp.route('/api/orders/<int:order_id>')
def api_get(order_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM emom_orders WHERE id = %s', [order_id])
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        r = serialize_row(row)
        r['pct_filled'] = calc_pct_filled(r['volume_total'], r['volume_remain'])
        r['total_value'] = calc_total_value(r['price'], r['volume_remain'])
        if not r['is_buy_order'] and r['cost_basis']:
            r['margin_pct'], r['profit_per_unit'] = calc_margin(r['price'], r['cost_basis'])
        else:
            r['margin_pct'] = None
            r['profit_per_unit'] = None

        cur.execute("""
            SELECT snapshot_date, price, volume_remain
            FROM emom_snapshots
            WHERE order_id = %s
            ORDER BY snapshot_date DESC, id DESC
            LIMIT 30
        """, [order_id])
        r['snapshots'] = [serialize_row(s) for s in cur.fetchall()]

        return jsonify(r)
    finally:
        conn.close()


@bp.route('/api/orders', methods=['POST'])
def api_create():
    data = request.get_json(force=True)
    required = ['type_name', 'price']
    for f in required:
        if not data.get(f):
            return jsonify({'error': f'Missing required field: {f}'}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO emom_orders
              (order_id, character_name, character_id, type_name, type_id,
               location_name, station_id, region_name, is_buy_order,
               price, volume_total, volume_remain, min_volume, range,
               duration, status, cost_basis, issued_at, expires_at, notes)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, [
            data.get('order_id'),
            data.get('character_name', ''),
            data.get('character_id'),
            data['type_name'],
            data.get('type_id'),
            data.get('location_name', ''),
            data.get('station_id'),
            data.get('region_name', ''),
            bool(data.get('is_buy_order', False)),
            float(data['price']),
            int(data.get('volume_total', 1)),
            int(data.get('volume_remain', data.get('volume_total', 1))),
            int(data.get('min_volume', 1)),
            data.get('range', 'station'),
            int(data.get('duration', 90)),
            data.get('status', 'active'),
            float(data['cost_basis']) if data.get('cost_basis') else None,
            data.get('issued_at'),
            data.get('expires_at'),
            data.get('notes', ''),
        ])
        row = cur.fetchone()
        new_id = row['id']

        cur.execute("""
            INSERT INTO emom_order_history (order_id, event_type, notes)
            VALUES (%s, 'manual_update', 'Order created')
        """, [new_id])

        conn.commit()
        return jsonify({'ok': True, 'id': new_id})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@bp.route('/api/orders/<int:order_id>', methods=['PATCH'])
def api_update(order_id):
    data = request.get_json(force=True)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM emom_orders WHERE id = %s', [order_id])
        old = cur.fetchone()
        if not old:
            return jsonify({'error': 'Not found'}), 404
        old = serialize_row(old)

        allowed = ['type_name', 'character_name', 'character_id', 'type_id',
                   'location_name', 'station_id', 'region_name', 'is_buy_order',
                   'price', 'volume_total', 'volume_remain', 'min_volume',
                   'range', 'duration', 'status', 'cost_basis',
                   'issued_at', 'expires_at', 'notes', 'order_id']
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return jsonify({'error': 'No valid fields to update'}), 400

        set_parts = [f'{k} = %s' for k in fields]
        set_parts.append('updated_at = NOW()')
        vals = list(fields.values()) + [order_id]
        cur.execute(f"UPDATE emom_orders SET {', '.join(set_parts)} WHERE id = %s", vals)

        if 'price' in fields and str(fields['price']) != str(old.get('price', '')):
            cur.execute("""
                INSERT INTO emom_order_history (order_id, event_type, old_value, new_value)
                VALUES (%s, 'price_change', %s, %s)
            """, [order_id, str(old.get('price')), str(fields['price'])])

        if 'volume_remain' in fields and str(fields['volume_remain']) != str(old.get('volume_remain', '')):
            cur.execute("""
                INSERT INTO emom_order_history (order_id, event_type, old_value, new_value)
                VALUES (%s, 'volume_change', %s, %s)
            """, [order_id, str(old.get('volume_remain')), str(fields['volume_remain'])])

        if 'status' in fields and fields['status'] != old.get('status'):
            cur.execute("""
                INSERT INTO emom_order_history (order_id, event_type, old_value, new_value)
                VALUES (%s, %s, %s, %s)
            """, [order_id, fields['status'], old.get('status'), fields['status']])

        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@bp.route('/api/orders/<int:order_id>', methods=['DELETE'])
def api_delete(order_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM emom_orders WHERE id = %s', [order_id])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@bp.route('/api/orders/<int:order_id>/snapshot', methods=['POST'])
def api_snapshot(order_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute('SELECT price, volume_remain FROM emom_orders WHERE id = %s', [order_id])
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        cur.execute("""
            INSERT INTO emom_snapshots (order_id, price, volume_remain)
            VALUES (%s, %s, %s)
        """, [order_id, row['price'], row['volume_remain']])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@bp.route('/api/orders/meta/regions')
def api_regions():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT region_name FROM emom_orders WHERE region_name IS NOT NULL AND region_name != '' ORDER BY region_name")
        regions = [r['region_name'] for r in cur.fetchall()]
        return jsonify({'regions': regions})
    finally:
        conn.close()


@bp.route('/api/orders/meta/characters')
def api_characters():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT character_name FROM emom_orders WHERE character_name IS NOT NULL AND character_name != '' ORDER BY character_name")
        chars = [r['character_name'] for r in cur.fetchall()]
        return jsonify({'characters': chars})
    finally:
        conn.close()
