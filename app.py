from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, render_template, request, jsonify
import requests
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor, execute_batch
import logging

app = Flask(__name__)

logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database connection parameters
DB_HOST = "bdat1004.cbyqyiee6ovr.us-east-1.rds.amazonaws.com"
DB_NAME = "BDAT1004"
DB_USER = "postgres"
DB_PASS = "BDAT1004"

@app.route('/update-currencies', methods=['POST'])
def update_currencies():
    # Connect to the database
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST)
    cur = conn.cursor()

    # Fetch currency name and code data from the API
    response = requests.get("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies.json")
    currency_data = response.json()

    # SQL to insert or update currency data
    sql = """
    INSERT INTO currencies (currency_code, currency_name)
    VALUES (%s, %s)
    ON CONFLICT (currency_code) DO UPDATE SET
        currency_name = EXCLUDED.currency_name;
    """

    # Prepare data for batch insertion
    data = [(code, name) for code, name in currency_data.items() if name]

    # Execute batch insertion
    execute_batch(cur, sql, data)
    conn.commit()

    currency_codes =['eur', 'btc', 'cad', 'usd', 'jpy']

    for currency_code in currency_codes:
        # Fetch exchange rate in eur from the API
        response = requests.get(
            f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency_code}.json")
        currency_data = response.json()
        rates = currency_data[currency_code]

        # SQL to update exchange_rate_eur based on currency_code
        sql = f"""
               UPDATE currencies
               SET exchange_rate_{currency_code} = %s
               WHERE currency_code = %s;
               """

        # Prepare data for batch update
        update_data = [(rate, code) for code, rate in rates.items()]

        # Execute batch update
        execute_batch(cur, sql, update_data)
        conn.commit()

    # Close the connection
    cur.close()
    conn.close()

    return jsonify({'message': 'Currencies updated successfully'}), 200

@app.route('/update-currencies-history', methods=['POST'])
def update_currencies_history():
    # Connect to the database
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST)
    cur = conn.cursor()

    currency_codes = ['usd', 'eur', 'btc', 'jpy', 'cad', 'inr', 'sgd', 'chf', 'krw', 'gbp']

    exchange_currency_codes = ['eur', 'usd', 'jpy', 'cad', 'btc']

    today = datetime.date.today()
    start_date = datetime.datetime.strptime("2024-03-06", '%Y-%m-%d').date()
    days = (today - start_date).days

    for exchange_currency_code in exchange_currency_codes:
        for day in range(days):
            exchange_date = (start_date + datetime.timedelta(days=day)).strftime('%Y-%m-%d')
            url = f"https://{exchange_date}.currency-api.pages.dev/v1/currencies/{exchange_currency_code}.json"

            try:
                response = requests.get(url)
                response.raise_for_status()
                currency_history_data = response.json()
                exchange_rates = currency_history_data[exchange_currency_code]

                sql = f"""
                        INSERT INTO currencies_history (currency_code, exchange_rate_{exchange_currency_code}, exchange_date)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (currency_code, exchange_date) DO UPDATE SET
                            exchange_rate_{exchange_currency_code} = EXCLUDED.exchange_rate_{exchange_currency_code};
                       """

                # Collect all data to insert in a single list to execute in one batch
                insert_data = []
                for currency_code in currency_codes:
                    rate = exchange_rates.get(currency_code)  # Assuming `exchange_rates` is a dictionary
                    if rate is not None:
                        insert_data.append((currency_code, rate, exchange_date))

                # Execute batch insertion only once
                execute_batch(cur, sql, insert_data)
                conn.commit()

            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to fetch data for {currency_code} on {exchange_date}: {str(e)}")
            except Exception as e:
                logging.error(f"Error processing data for {currency_code} on {exchange_date}: {str(e)}")

    # Close the connection
    cur.close()
    conn.close()

    return jsonify({'message': 'Currencies history updated successfully'}), 200

@app.route('/', methods=['GET', 'POST'])
def dashboard():
    currency_codes = ['usd', 'eur', 'btc', 'jpy', 'cad', 'inr', 'sgd', 'chf', 'krw', 'gbp']
    default_start_date = '2024-03-06'
    today_date = datetime.date.today().strftime("%Y-%m-%d")
    default_end_date = today_date

    if request.method == 'POST':
        selected_currency = request.form.get('currency_code', 'cad')
        start_date = request.form.get('start_date', default_start_date)
        end_date = request.form.get('end_date', default_end_date)
    else:
        selected_currency = 'cad'
        start_date = default_start_date
        end_date = default_end_date

    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT currency_code, %s as exchange_date, exchange_rate_usd, exchange_rate_eur, exchange_rate_jpy,
                       exchange_rate_cad, exchange_rate_btc
                FROM currencies
                WHERE currency_code = %s
                UNION
                SELECT currency_code, exchange_date, exchange_rate_usd, exchange_rate_eur, exchange_rate_jpy,
                       exchange_rate_cad, exchange_rate_btc
                FROM currencies_history
                WHERE currency_code = %s AND exchange_date BETWEEN %s AND %s
                ORDER BY exchange_date ASC
            """, (today_date, selected_currency, selected_currency, start_date, end_date))
            data = cur.fetchall()
    finally:
        conn.close()

    return render_template('dashboard.html', title="Dashboard", currency_codes=currency_codes, data=data,
                           selected_currency=selected_currency, start_date=start_date, end_date=end_date)

@app.route('/currencies', methods=['GET'])
def all_currencies():
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM currencies")
            currencies = cur.fetchall()  # Fetches all currencies as a list of dicts
            return render_template('table.html', title="All Currencies with Today's Exchange Rate",
                                   currencies=currencies)
    except Exception as e:
        return render_template('error.html', error=str(e))
    finally:
        conn.close()


@app.route('/range', methods=['GET', 'POST'])
def currency_range():
    currency_codes = ['usd', 'eur', 'btc', 'jpy', 'cad', 'inr', 'sgd', 'chf', 'krw', 'gbp']
    default_start_date = '2024-03-06'
    today_date = datetime.date.today().strftime("%Y-%m-%d")
    default_end_date = today_date

    selected_currency = request.form.get('currency_code', 'cad')
    start_date = request.form.get('start_date', default_start_date)
    end_date = request.form.get('end_date', default_end_date)

    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT currency_code, %s as exchange_date, exchange_rate_usd, exchange_rate_eur, exchange_rate_jpy,
                       exchange_rate_cad, exchange_rate_btc
                FROM currencies
                WHERE currency_code = %s
                UNION
                SELECT currency_code, exchange_date, exchange_rate_usd, exchange_rate_eur, exchange_rate_jpy,
                       exchange_rate_cad, exchange_rate_btc
                FROM currencies_history
                WHERE currency_code = %s AND exchange_date BETWEEN %s AND %s
                ORDER BY exchange_date DESC
            """, (today_date, selected_currency, selected_currency, start_date, end_date))
            data = cur.fetchall()
    finally:
        conn.close()
    return render_template('currency_range.html', title = "Exchange rate over a period of time", currency_codes=currency_codes, data=data,
                           selected_currency=selected_currency, start_date=start_date, end_date=end_date)


def copy_currencies_to_history():
    logging.info("Job started - Coping data from currencies to currencies history")
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST)
    cur = conn.cursor()

    # Here, perform your operations of copying data from currencies to currencies_history
    cur.execute("""
        INSERT INTO currencies_history (
            currency_code,
            exchange_rate_usd,
            exchange_rate_eur,
            exchange_rate_jpy,
            exchange_rate_cad,
            exchange_rate_btc,
            exchange_date
        )
        SELECT
            currency_code,
            exchange_rate_usd,
            exchange_rate_eur,
            exchange_rate_jpy,
            exchange_rate_cad,
            exchange_rate_btc,
            CURRENT_DATE - INTERVAL '1 day' AS exchange_date
        FROM
            currencies
        where currency_code in ('usd', 'eur', 'btc', 'jpy', 'cad', 'inr', 'sgd', 'chf', 'krw', 'gbp');
    """)
    conn.commit()

    # Close the connection
    cur.close()
    conn.close()

    # Updating the currencies
    update_currencies()

    logging.info("Job completed - Copied data from currencies to currencies history")


scheduler = BackgroundScheduler()
scheduler.add_job(func=copy_currencies_to_history, trigger='cron', hour=18, minute=40)
scheduler.start()

if __name__ == '__main__':
    app.run(debug=True)
