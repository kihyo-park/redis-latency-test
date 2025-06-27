import redis
import psycopg2
import requests
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

# Configs.
REDIS_CONFIG = {
    'host': 'redis',
    'port': os.getenv('REDIS_BINDING_PORT', 6379),
    'db': 0
}
POSTGRES_CONFIG = {
    'dbname': 'myappdb',
    'user': 'myappuser',
    'password': 'password',
    'host': 'host.docker.internal',
    'port': 5432
}
API_ENDPOINT = "https://jsonplaceholder.typicode.com/posts/{}"
CACHE_EXPIRATION_SECONDS = 60

# DB setup
def setup_database(conn):
    """Creates the necessary table in PostgreSQL if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY,
                title TEXT,
                body TEXT,
                userId INTEGER
            );
        """)
    conn.commit()
    print("✅ [APP] Database table 'posts' is ready.")

# Caching logic
def get_data(post_id: int, redis_conn, pg_conn):
    cache_key = f"post:{post_id}"

    # 1. Check Redis (the cache) first
    cached_data = redis_conn.get(cache_key)
    if cached_data:
        print(f"✅ [ID: {post_id}] CACHE HIT!")
        return json.loads(cached_data)

    print(f"⚠️ [ID: {post_id}] CACHE MISS. Checking database...")

    # 2. If not in cache, check PostgreSQL (the database)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT id, title, body, userId FROM posts WHERE id = %s", (post_id,))
        db_data = cur.fetchone()

    if db_data:
        print(f"✅ [ID: {post_id}] DATABASE HIT. Populating cache...")
        post = {'id': db_data[0], 'title': db_data[1], 'body': db_data[2], 'userId': db_data[3]}
        redis_conn.setex(cache_key, CACHE_EXPIRATION_SECONDS, json.dumps(post))
        return post

    print(f"⚠️ [ID: {post_id}] DATABASE MISS. Fetching from external API...")

    # 3. If not in DB, fetch from the external API
    try:
        response = requests.get(API_ENDPOINT.format(post_id))
        response.raise_for_status()
        api_data = response.json()
        print(f"✅ [ID: {post_id}] API HIT. Saving to DB and Cache...")

        with pg_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO posts (id, title, body, userId) VALUES (%s, %s, %s, %s)",
                (api_data['id'], api_data['title'], api_data['body'], api_data['userId'])
            )
        pg_conn.commit()

        redis_conn.setex(cache_key, CACHE_EXPIRATION_SECONDS, json.dumps(api_data))
        return api_data
    except requests.exceptions.RequestException as e:
        print(f"❌ [ID: {post_id}] API FETCH FAILED: {e}")
        return None

# Main
if __name__ == "__main__":
    redis_conn = None
    pg_conn = None
    try:
        redis_conn = redis.Redis(decode_responses=True, **REDIS_CONFIG)
        redis_conn.ping()
        print(f"✅ [APP] Connected to Redis on port {REDIS_CONFIG['port']}")

        pg_conn = psycopg2.connect(**POSTGRES_CONFIG)
        print("✅ [APP] Connected to PostgreSQL successfully!")

        # Pass the correct connection object to the function
        setup_database(pg_conn)

        # Simulate multiple requests to test the caching logic
        print("\n--- Starting Simulation ---")

        # Pause to enable latency monitor
        print(">>> PAUSING FOR 10 SECONDS. Please enable latency monitor in the other terminal NOW. <<<")
        time.sleep(10)

        ids_to_fetch = [5, 10, 5, 15, 10]

        for post_id in ids_to_fetch:
            print(f"\n--- Requesting data for post_id = {post_id} ---")
            # Pass the correct connection objects to the function
            data = get_data(post_id, redis_conn, pg_conn)

            if post_id == 15:  # Run a slow command for ID 15 intentionally
                print("🐌 [APP] Intentionally running a slow command for ID 15...")
                # This Lua script blocks Redis for 1000 milliseconds
                redis_conn.eval("local end_time = redis.call('TIME')[1] * 1000 + redis.call('TIME')[2] / 1000 + 1000; while(redis.call('TIME')[1] * 1000 + redis.call('TIME')[2] / 1000 < end_time) do end; return 1;", 0)                
            if data:
                print(f"   -> Title: {data['title'][:40]}...")
            time.sleep(1)

    except Exception as e:
        print(f"❌ [APP] An error occurred: {e}")

    finally:
        if pg_conn and pg_conn.closed == 0:
            pg_conn.close()
            print("\n-> [APP] PostgreSQL connection closed.")