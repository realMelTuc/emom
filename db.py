import os
import re
from dotenv import load_dotenv

load_dotenv('.env.emom')

import pg8000


class DictCursor:
    """Wraps pg8000 cursor to return dict rows."""

    def __init__(self, conn):
        self._conn = conn
        self._cursor = conn.cursor()
        self._description = None

    def execute(self, query, params=None):
        if params and isinstance(params, dict):
            keys = []
            def replacer(m):
                key = m.group(1)
                keys.append(key)
                return f'${len(keys)}'
            query = re.sub(r'%\((\w+)\)s', replacer, query)
            params = tuple(params[k] for k in keys)
        elif params:
            counter = [0]
            def pos_replacer(m):
                counter[0] += 1
                return f'${counter[0]}'
            query = re.sub(r'(?<!%)%s', pos_replacer, query)
            if isinstance(params, (list, tuple)):
                params = tuple(params)
            else:
                params = (params,)

        if params:
            self._cursor.execute(query, params)
        else:
            self._cursor.execute(query)
        self._description = self._cursor.description

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._make_dict(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [self._make_dict(r) for r in rows]

    def _make_dict(self, row):
        if self._description:
            cols = [d[0] for d in self._description]
            return dict(zip(cols, row))
        return row

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def close(self):
        self._cursor.close()


class Connection:
    """Wraps pg8000 connection to provide psycopg2-compatible interface."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return DictCursor(self._conn)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_db():
    """Get a database connection. Caller must call conn.close() when done."""
    import ssl
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    conn = pg8000.connect(
        host=os.environ['SUPABASE_DB_HOST'],
        database=os.environ['SUPABASE_DB_NAME'],
        user=os.environ['SUPABASE_DB_USER'],
        password=os.environ['SUPABASE_DB_PASSWORD'],
        port=int(os.environ.get('SUPABASE_DB_PORT', 6543)),
        ssl_context=ssl_context,
    )
    return Connection(conn)


def serialize_row(row):
    """Convert a database row to a JSON-safe dict."""
    from datetime import datetime, date
    from decimal import Decimal
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, date):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


# ─── EMOM domain constants ───

ORDER_STATUSES = ['active', 'fulfilled', 'expired', 'cancelled', 'paused']

ORDER_RANGES = ['station', 'solarsystem', 'region', '2', '3', '4', '5', '10', '20', '30', '40']

DURATION_OPTIONS = [1, 3, 7, 14, 30, 60, 90]

SECURITY_CLASSES = ['highsec', 'lowsec', 'nullsec', 'wormhole', 'pochven']

EVENT_TYPES = ['price_change', 'volume_change', 'fulfilled', 'expired', 'cancelled', 'manual_update', 'note']


def calc_margin(sell_price, cost_basis):
    """Return margin % and ISK profit per unit."""
    if not cost_basis or cost_basis <= 0:
        return None, None
    profit_isk = sell_price - cost_basis
    margin_pct = (profit_isk / cost_basis) * 100
    return round(margin_pct, 2), round(profit_isk, 2)


def calc_total_value(price, volume_remain):
    """Total ISK value of remaining volume."""
    return round((price or 0) * (volume_remain or 0), 2)


def calc_pct_filled(volume_total, volume_remain):
    """Percentage of order filled."""
    if not volume_total or volume_total <= 0:
        return 0.0
    filled = volume_total - volume_remain
    return round((filled / volume_total) * 100, 2)
