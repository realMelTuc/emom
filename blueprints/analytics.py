from flask import Blueprint, render_template, jsonify, request
from db import get_db, serialize_row

bp = Blueprint('analytics', __name__)


@bp.route('/analytics/')
def index():
    return render_template('partials/analytics/index.html')


@bp.route('/api/analytics/margins')
def api_margins():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                type_name,
                region_name,
                character_name,
                price,
                cost_basis,
                volume_remain,
                volume_total,
                status,
                CASE
                    WHEN cost_basis IS NOT NULL AND cost_basis > 0
                    THEN ROUND((price - cost_basis) / cost_basis * 100, 2)
                    ELSE NULL
                END AS margin_pct,
                CASE
                    WHEN cost_basis IS NOT NULL AND cost_basis > 0
                    THEN ROUND((price - cost_basis) * volume_remain, 2)
                    ELSE NULL
                END AS unrealized_profit,
                id
            FROM emom_orders
            WHERE is_buy_order = FALSE
              AND status IN ('active', 'fulfilled')
              AND cost_basis IS NOT NULL AND cost_basis > 0
            ORDER BY margin_pct DESC NULLS LAST
            LIMIT 200
        """)
        rows = [serialize_row(r) for r in cur.fetchall()]
        return jsonify({'margins': rows})
    finally:
        conn.close()


@bp.route('/api/analytics/performance')
def api_performance():
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                COALESCE(character_name, 'Unknown') AS character_name,
                COUNT(*) AS total_orders,
                COUNT(*) FILTER (WHERE status = 'active') AS active_orders,
                COUNT(*) FILTER (WHERE status = 'fulfilled') AS fulfilled_orders,
                COUNT(*) FILTER (WHERE status = 'expired') AS expired_orders,
                COALESCE(SUM(price * volume_remain) FILTER (WHERE status = 'active' AND is_buy_order = FALSE), 0) AS active_sell_value,
                COALESCE(SUM(price * (volume_total - volume_remain)) FILTER (WHERE is_buy_order = FALSE), 0) AS total_filled_value
            FROM emom_orders
            GROUP BY character_name
            ORDER BY total_orders DESC
        """)
        by_char = [serialize_row(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT
                COALESCE(region_name, 'Unknown') AS region_name,
                COUNT(*) AS total_orders,
                COUNT(*) FILTER (WHERE status = 'active') AS active_orders,
                COALESCE(SUM(price * volume_remain) FILTER (WHERE status = 'active'), 0) AS active_value,
                COUNT(DISTINCT type_name) AS unique_items
            FROM emom_orders
            GROUP BY region_name
            ORDER BY active_value DESC
        """)
        by_region = [serialize_row(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT
                type_name,
                COUNT(*) AS order_count,
                COALESCE(SUM(volume_remain) FILTER (WHERE status = 'active'), 0) AS active_volume,
                COALESCE(SUM(price * volume_remain) FILTER (WHERE status = 'active'), 0) AS active_value,
                AVG(price) FILTER (WHERE status = 'active') AS avg_price,
                AVG(CASE WHEN cost_basis > 0 THEN (price - cost_basis) / cost_basis * 100 ELSE NULL END) AS avg_margin_pct
            FROM emom_orders
            GROUP BY type_name
            ORDER BY active_value DESC
            LIMIT 20
        """)
        by_item = [serialize_row(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT
                COALESCE(SUM(volume_total - volume_remain), 0) AS total_filled,
                COALESCE(SUM(volume_total), 0) AS total_volume,
                COUNT(*) FILTER (WHERE status = 'fulfilled') AS fulfilled_count,
                COUNT(*) AS total_count
            FROM emom_orders
        """)
        overall = serialize_row(cur.fetchone() or {})

        return jsonify({
            'by_character': by_char,
            'by_region':    by_region,
            'by_item':      by_item,
            'overall':      overall,
        })
    finally:
        conn.close()
