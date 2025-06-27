import pandas as pd
import psycopg2
from initialize import db_conn

connection, cursor = db_conn()

query = "SELECT * FROM inventory"
df = pd.read_sql_query(query, connection)

csv_filename = "output_data.csv"
df.to_csv(csv_filename, index=False)

connection.close()
