from flask import Blueprint, render_template, jsonify
from db import get_db, serialize_row, calc_margin, calc_total_value

bp = Blueprint('dashboard', __name__)


@bp.route('/dashboard/')
def index():
    return render_template('partials/dashboard/index.html')


@bp.route('/api/dashboard/summary')
def api_summary():
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'active') AS active_count,
                COUNT(*) FILTER (WHERE status = 'active' AND is_buy_order = FALSE) AS active_sell,
                COUNT(*) FILTER (WHERE status = 'active' AND is_buy_order = TRUE) AS active_buy,
                COUNT(*) FILTER (WHERE status = 'fulfilled') AS fulfilled_count,
                COUNT(*) FILTER (WHERE status = 'expired') AS expired_count,
                COALESCE(SUM(price * volume_remain) FILTER (WHERE status = 'active' AND is_buy_order = FALSE), 0) AS sell_isk,
                COALESCE(SUM(price * volume_remain) FILTER (WHERE status = 'active' AND is_buy_order = TRUE), 0) AS buy_isk,
                COUNT(*) FILTER (
                    WHERE status = 'active'
                    AND expires_at IS NOT NULL
                    AND expires_at <= NOW() + INTERVAL '24 hours'
                ) AS expiring_soon
            FROM emom_orders
        """)
        totals = cur.fetchone() or {}

        cur.execute("""
            SELECT
                COALESCE(SUM((price - cost_basis) * volume_remain), 0) AS unrealized_profit,
                COALESCE(AVG((price - cost_basis) / NULLIF(cost_basis, 0) * 100), 0) AS avg_margin_pct
            FROM emom_orders
            WHERE status = 'active' AND is_buy_order = FALSE AND cost_basis IS NOT NULL AND cost_basis > 0
        """)
        margin_row = cur.fetchone() or {}

        cur.execute("""
            SELECT id, type_name, is_buy_order, price, volume_remain,
                   location_name, status, expires_at, character_name
            FROM emom_orders
            WHERE status = 'active'
              AND expires_at IS NOT NULL
              AND expires_at <= NOW() + INTERVAL '24 hours'
            ORDER BY expires_at ASC
            LIMIT 10
        """)
        expiring = [serialize_row(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT o.id, o.type_name, o.is_buy_order, o.price, o.volume_remain,
                   o.volume_total, o.status, o.location_name, o.character_name, o.updated_at
            FROM emom_orders o
            ORDER BY o.updated_at DESC
            LIMIT 8
        """)
        recent = [serialize_row(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT id, type_name, price, volume_remain, volume_total,
                   cost_basis, location_name, character_name, status
            FROM emom_orders
            WHERE status = 'active' AND is_buy_order = FALSE
            ORDER BY (price * volume_remain) DESC
            LIMIT 5
        """)
        top_sell = [serialize_row(r) for r in cur.fetchall()]

        return jsonify({
            'active_count':   int(totals.get('active_count', 0) or 0),
            'active_sell':    int(totals.get('active_sell', 0) or 0),
            'active_buy':     int(totals.get('active_buy', 0) or 0),
            'fulfilled_count': int(totals.get('fulfilled_count', 0) or 0),
            'expired_count':  int(totals.get('expired_count', 0) or 0),
            'sell_isk':       float(totals.get('sell_isk', 0) or 0),
            'buy_isk':        float(totals.get('buy_isk', 0) or 0),
            'expiring_soon':  int(totals.get('expiring_soon', 0) or 0),
            'unrealized_profit': float(margin_row.get('unrealized_profit', 0) or 0),
            'avg_margin_pct': float(margin_row.get('avg_margin_pct', 0) or 0),
            'expiring':       expiring,
            'recent':         recent,
            'top_sell':       top_sell,
        })
    finally:
        conn.close()
